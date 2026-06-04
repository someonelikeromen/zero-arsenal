"""
内置工具集 — 角色、记忆、骰子、世界状态、叙事工具。
文件末尾调用 _register_all() 完成自动注册。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from .registry import ToolDef, tool_registry

logger = logging.getLogger(__name__)


# ── 角色相关 ──────────────────────────────────────────────────────────────────

async def _read_character(session_id: str) -> dict:
    """从 character_cards 表读取角色卡 JSON。"""
    from ..db import get_db
    async with get_db() as db:
        row = await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )
        char = await row.fetchone()
    if not char:
        return {"error": "character not found", "session_id": session_id}
    return json.loads(char["data_json"])


async def _update_character_state(session_id: str, patches: list[dict]) -> dict:
    """用 TavernCommandProcessor 处理 patches，更新 character_cards 表。"""
    from ..db import get_db
    from ..engine import TavernCommandProcessor

    processor = TavernCommandProcessor()
    async with get_db() as db:
        row = await db.execute(
            "SELECT id, data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )
        char = await row.fetchone()
        if not char:
            return {"error": "character not found", "session_id": session_id}

        state = json.loads(char["data_json"])
        updated = processor.apply_patches(patches, state)
        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
            (json.dumps(updated, ensure_ascii=False), now, char["id"]),
        )
        await db.commit()

    return {"ok": True, "patches_applied": len(patches)}


# ── 记忆相关 ──────────────────────────────────────────────────────────────────

async def _search_memory(session_id: str, query: str, top_k: int = 5,
                         viewer_agent: str = "narrator") -> dict:
    """
    混合语义搜索记忆，返回拼接后的上下文字符串。
    viewer_agent 控制视角隔离（dm/npc/narrator/world/chronicler）。
    """
    from ..memory.adapter import memory_adapter
    from ..db import get_db

    # 获取 world_plugin
    world_plugin = "crossover"
    try:
        async with get_db() as db:
            sess = await (
                await db.execute("SELECT world_plugin FROM sessions WHERE id=?", (session_id,))
            ).fetchone()
            if sess:
                world_plugin = sess["world_plugin"]
    except Exception:
        pass

    results = await memory_adapter.recall(
        session_id=session_id,
        world_plugin=world_plugin,
        query_text=query,
        viewer_agent=viewer_agent,
        top_k=top_k,
    )
    return {"results": results}


async def _get_chapter_summaries(session_id: str, limit: int = 3) -> dict:
    """获取最近 N 章节摘要。"""
    from ..memory.adapter import memory_adapter
    text = await memory_adapter.get_chapter_summaries(session_id, limit=limit)
    return {"summaries": text}


# ── 骰子相关 ──────────────────────────────────────────────────────────────────

async def _roll_dice(pool: int, threshold: int = 8, reason: str = "") -> dict:
    """执行 d10 骰池判定，返回完整结果。"""
    from ..engine.dice import RollRequest, compute_roll_request
    req = RollRequest(pool=pool, threshold=threshold, reason=reason)
    result = compute_roll_request(req)
    return result.model_dump()


# ── 世界状态相关 ──────────────────────────────────────────────────────────────

async def _get_world_state(session_id: str) -> dict:
    """获取当前会话 state_json 快照。"""
    from ..db import get_db
    async with get_db() as db:
        row = await db.execute(
            "SELECT state_json FROM sessions WHERE id=?", (session_id,)
        )
        sess = await row.fetchone()
    if not sess:
        return {"error": "session not found", "session_id": session_id}
    raw = sess["state_json"]
    if not raw:
        return {}
    return json.loads(raw)


async def _update_world_state(session_id: str, patches: list[dict]) -> dict:
    """读取 state_json，用 TavernCommandProcessor 处理 patches，写回。"""
    from ..db import get_db
    from ..engine import TavernCommandProcessor

    processor = TavernCommandProcessor()
    async with get_db() as db:
        row = await db.execute(
            "SELECT state_json FROM sessions WHERE id=?", (session_id,)
        )
        sess = await row.fetchone()
        if not sess:
            return {"error": "session not found", "session_id": session_id}

        raw = sess["state_json"]
        state: dict = json.loads(raw) if raw else {}
        updated = processor.apply_patches(patches, state)
        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE sessions SET state_json=?, updated_at=? WHERE id=?",
            (json.dumps(updated, ensure_ascii=False), now, session_id),
        )
        await db.commit()

    return {"ok": True, "patches_applied": len(patches)}


# ── 叙事工具 ──────────────────────────────────────────────────────────────────

async def _write_journal(
    session_id: str,
    content: str,
    event_type: str = "general",
) -> dict:
    """将重要事件写入 memory_entries 表，tier='core'。"""
    from ..db import get_db
    async with get_db() as db:
        entry_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        await db.execute(
            "INSERT INTO memory_entries "
            "(id, session_id, chapter_id, content, tier, cognitive_partition, source_agent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                session_id,
                "",
                content,
                "core",
                event_type,
                "tool:write_journal",
                now,
            ),
        )
        await db.commit()
    return {"ok": True, "entry_id": entry_id}


# ── 世界设定库搜索 ────────────────────────────────────────────────────────────

async def _search_lore(session_id: str, query: str, top_k: int = 5) -> dict:
    """
    在世界档案（world_archives）中搜索 lore/rule 条目。
    与 search_memory 不同，此处搜索静态世界设定而非会话记忆。
    """
    from ..db import get_db
    try:
        async with get_db() as db:
            rows = await (await db.execute(
                "SELECT id, title, content, archive_type FROM world_archives "
                "WHERE session_id=? AND (title LIKE ? OR content LIKE ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, f"%{query}%", f"%{query}%", top_k)
            )).fetchall()
        entries = [
            {"id": r["id"], "title": r["title"],
             "content": r["content"][:400], "type": r["archive_type"]}
            for r in rows
        ]
        return {"entries": entries, "count": len(entries), "query": query}
    except Exception as e:
        return {"error": str(e), "entries": []}


# ── 属性技能检定（roll_check） ────────────────────────────────────────────────

async def _roll_check(
    session_id: str,
    attribute: str,
    skill: str = "",
    difficulty: int = 1,  # 注：当前未参与计算，threshold 固定为 8（见下方 RollRequest）
    reason: str = "",
) -> dict:
    """
    按角色属性/技能值自动建立骰池并执行 d10 判定。
    骰池 = attribute_dots + skill_dots（从角色卡读取）。
    返回 roll_result dict（含 rolls/net/verdict/narrative_hint）。

    注：difficulty 形参目前不影响判定（threshold 写死 8），保留以兼容已注册 schema。
    """
    from ..db import get_db
    from ..engine.dice import RollRequest, compute_roll_request

    # 读取属性/技能点
    pool = 2  # 默认最低骰池
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id,)
            )).fetchone()
        if row:
            char = json.loads(row["data_json"])
            attrs = char.get("attributes", {})
            skills = char.get("skills", {})
            attr_dots  = attrs.get(attribute, {}).get("dots", 0)
            skill_dots = skills.get(skill, {}).get("dots", 0) if skill else 0
            pool = max(1, attr_dots + skill_dots)
    except Exception:
        pass

    req = RollRequest(pool=pool, threshold=8, reason=reason or f"{attribute}+{skill or '无'} 检定")
    result = compute_roll_request(req)
    data = result.model_dump()
    data["attribute"] = attribute
    data["skill"] = skill

    # 构建可读的骰池公式：如 "力量(3d) + 格斗(2d) = 5d"
    attr_dots_str = f"{attribute}"
    skill_str = f" + {skill}" if skill else ""
    data["pool_formula"] = f"{attr_dots_str}{skill_str} = {pool}d"
    return data


# ── NPC 专用查询/更新工具 ────────────────────────────────────────────────────

# NEW-C11-01/02：NPC 单一存储源 = npc_profiles 表。
# spawn_npc / edit_npc_state / query_npc_profile / get_npc_knowledge_scope /
# update_npc_state 五个工具统一读写 npc_profiles，消除此前 world_archives 与
# npc_profiles 双存储导致的 spawned NPC 查不到 / 状态分裂问题。

async def _lookup_npc_row(db, session_id: str, npc_name: str):
    """在 npc_profiles 表中按 name / key 查找一条 NPC 记录（会话内优先，其次全局模板）。"""
    npc_key = npc_name.lower().replace(" ", "_").replace("-", "_")[:32]
    # 1) 会话内：name 精确 → key 精确 → name 模糊
    row = await (await db.execute(
        "SELECT id, key, name, profile_json, world_key FROM npc_profiles "
        "WHERE session_id=? AND (name=? OR key=?) ORDER BY updated_at DESC LIMIT 1",
        (session_id, npc_name, npc_key),
    )).fetchone()
    if row:
        return row
    row = await (await db.execute(
        "SELECT id, key, name, profile_json, world_key FROM npc_profiles "
        "WHERE session_id=? AND (name LIKE ? OR key LIKE ?) ORDER BY updated_at DESC LIMIT 1",
        (session_id, f"%{npc_name}%", f"%{npc_key}%"),
    )).fetchone()
    if row:
        return row
    # 2) 全局模板（world_key 非空）
    row = await (await db.execute(
        "SELECT id, key, name, profile_json, world_key FROM npc_profiles "
        "WHERE world_key!='' AND (name=? OR key=?) ORDER BY updated_at DESC LIMIT 1",
        (npc_name, npc_key),
    )).fetchone()
    return row


async def _query_npc_profile(session_id: str, npc_name: str) -> dict:
    """从 npc_profiles 表（单一存储源）查询 NPC 档案。"""
    from ..db import get_db
    try:
        async with get_db() as db:
            row = await _lookup_npc_row(db, session_id, npc_name)
        if row:
            try:
                profile = json.loads(row["profile_json"])
            except Exception:
                profile = {"text": row["profile_json"]}
            return {"npc_name": npc_name, "key": row["key"], "profile": profile, "found": True}
        return {"npc_name": npc_name, "profile": {}, "found": False}
    except Exception as e:
        return {"npc_name": npc_name, "profile": {}, "found": False, "error": str(e)}


async def _get_npc_knowledge_scope(session_id: str, npc_name: str) -> dict:
    """
    获取 NPC 的知识边界（knowledge_scope）。从 npc_profiles 表读取。
    无档案或档案缺该字段时返回 found:False（D-13：不伪造通用边界，
    让上层 Agent 知晓信息缺口，满足信息不对称约束）。
    """
    from ..db import get_db
    try:
        async with get_db() as db:
            row = await _lookup_npc_row(db, session_id, npc_name)
        if not row:
            return {"npc_name": npc_name, "scope": None, "found": False,
                    "note": "无 NPC 档案，知识边界未知"}
        try:
            profile = json.loads(row["profile_json"])
        except Exception:
            profile = {}
        scope = profile.get("knowledge_scope")
        if scope is None:
            return {"npc_name": npc_name, "scope": None, "found": False,
                    "note": "NPC 档案缺少 knowledge_scope 字段"}
        return {"npc_name": npc_name, "scope": scope, "found": True}
    except Exception as e:
        return {"npc_name": npc_name, "scope": None, "found": False, "error": str(e)}


async def _update_npc_state(session_id: str, npc_name: str, changes: dict) -> dict:
    """合并 changes 到 npc_profiles 表中对应 NPC 的 profile_json，写回或新建。"""
    from ..db import get_db
    now = datetime.now().timestamp()
    npc_key = npc_name.lower().replace(" ", "_").replace("-", "_")[:32]
    try:
        async with get_db() as db:
            row = await _lookup_npc_row(db, session_id, npc_name)
            if row:
                try:
                    existing = json.loads(row["profile_json"])
                except Exception:
                    existing = {}
                existing.update(changes)
                await db.execute(
                    "UPDATE npc_profiles SET profile_json=?, updated_at=? WHERE id=?",
                    (json.dumps(existing, ensure_ascii=False), now, row["id"]),
                )
            else:
                new_id = str(uuid.uuid4())
                profile = {"name": npc_name, **changes}
                await db.execute(
                    "INSERT OR IGNORE INTO npc_profiles "
                    "(id, session_id, key, name, profile_json, world_key, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                    (new_id, session_id, npc_key, npc_name,
                     json.dumps(profile, ensure_ascii=False), now, now),
                )
            await db.commit()
        return {"npc_name": npc_name, "updated": True, "changes": changes}
    except Exception as e:
        return {"npc_name": npc_name, "updated": False, "changes": changes, "error": str(e)}


# ── RulesAgent 专用工具 ───────────────────────────────────────────────────────

async def _check_skill_trigger(
    session_id: str,
    action_text: str,
) -> dict:
    """
    检查玩家行动是否触发角色技能（Skill）的特殊效果。
    读取角色技能列表，对比行动文本，返回应当激活的技能名和触发条件。
    供 RulesAgent tool_loop 使用。
    """
    from ..db import get_db
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id,)
            )).fetchone()
        if not row:
            return {"triggered": [], "note": "无角色卡"}

        char = json.loads(row["data_json"])
        skills: dict = char.get("skills", {})
        triggered = []
        action_lower = action_text.lower()
        for skill_name, level in skills.items():
            # 简单关键词匹配（技能名在行动文本中出现）
            if skill_name.lower() in action_lower:
                triggered.append({"skill": skill_name, "level": level,
                                   "note": f"行动含关键词「{skill_name}」"})

        return {"triggered": triggered, "total_skills": len(skills)}
    except Exception as e:
        return {"error": str(e)}


async def _query_world_rules(
    session_id: str,
    rule_topic: str,
) -> dict:
    """
    查询世界插件的硬性规则（从 world_archives 或 lore 中检索规则文本）。
    供 RulesAgent tool_loop 在裁决前查询世界观约束。
    """
    from ..db import get_db
    try:
        async with get_db() as db:
            # 从 world_archives 中检索 rule 类型的条目
            rows = await (await db.execute(
                "SELECT title, content FROM world_archives "
                "WHERE session_id=? AND archive_type='rule' "
                "ORDER BY updated_at DESC LIMIT 5",
                (session_id,)
            )).fetchall()

        rule_entries = []
        for row in rows:
            title = row["title"] or ""
            try:
                content_data = json.loads(row["content"])
                text = content_data.get("text", str(content_data))
            except Exception:
                text = str(row["content"])

            # 关键词过滤
            if rule_topic.lower() in (title + text).lower():
                rule_entries.append({"title": title, "rule": text[:300]})

        return {
            "topic": rule_topic,
            "rules": rule_entries,
            "found": len(rule_entries),
            "note": "若无规则，视为允许" if not rule_entries else "",
        }
    except Exception as e:
        return {"error": str(e)}


# ── 技能加载 ──────────────────────────────────────────────────────────────────

async def _load_skill(session_id: str, skill_name: str) -> dict:
    """
    按需加载指定技能（SKILL.md），注入 runtime Prompt 层并发布 skill_load Part。
    """
    from ..tools import skill_registry
    from ..bus import bus, BusEvent, EventType

    skill = skill_registry.get_skill(skill_name)
    if not skill:
        return {"error": f"skill '{skill_name}' not found"}

    # 读取技能内容（SkillMeta 字段是 path，不是 file_path）
    content = ""
    if skill.path and skill.path.exists():
        try:
            content = skill_registry.load_skill_content(skill_name)[:2000]
        except Exception:
            content = skill.description or ""
    if not content:
        content = skill.description or f"技能: {skill_name}"

    # 注入 runtime Prompt 层
    try:
        from ..prompts.registry import registry as _pr
        _pr.register_runtime(
            session_id=session_id,
            frag_id=f"skill_{skill_name}",
            content=f"[技能：{skill.name}]\n{content}",
            phase=["all"],
            priority=420,
        )
    except Exception:
        pass

    # 发布 skill_load Part
    part_id = str(uuid.uuid4())
    try:
        await bus.publish(BusEvent(
            type=EventType.PART_CREATED,
            session_id=session_id,
            data={
                "part_id": part_id,
                "part_type": "skill_load",
                "message_id": "",
                "agent": "tool:load_skill",
            }
        ))
        await bus.publish(BusEvent(
            type=EventType.PART_DONE,
            session_id=session_id,
            data={
                "part_id": part_id,
                "content": {"skill_name": skill_name, "trigger": "on_demand"},
            }
        ))
    except Exception:
        pass

    return {"ok": True, "skill_name": skill_name, "content_length": len(content)}


# ── NPC 生成 ──────────────────────────────────────────────────────────────────

async def _spawn_npc(
    session_id: str,
    name: str,
    role: str = "minor",
    traits: list[str] | None = None,
    faction: str = "",
) -> dict:
    """
    在当前会话生成并保存一个 NPC 到 npc_profiles 表。
    返回新 NPC 的 profile dict。
    """
    from ..db import get_db
    npc_key = name.lower().replace(" ", "_").replace("-", "_")[:32]
    npc_id = str(uuid.uuid4())
    profile = {
        "name": name,
        "role": role,
        "traits": traits or [],
        "faction": faction,
        "status": "alive",
        "relationship": "neutral",
    }
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO npc_profiles "
                "(id, session_id, key, name, profile_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (npc_id, session_id, npc_key, name,
                 json.dumps(profile, ensure_ascii=False), now, now)
            )
            await db.commit()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "npc_id": npc_id, "key": npc_key, "profile": profile}


# ── 生成行动选项 ──────────────────────────────────────────────────────────────

async def _generate_action_options(
    session_id: str,
    context: str = "",
    count: int = 3,
    _msg_id: str = "",
) -> dict:
    """
    根据当前场景生成玩家可选行动选项（A/B/C）。
    返回 options list，每项含 label 和 description。
    """
    from ..agents.llm import llm_complete
    from ..db import get_db

    # 获取角色简况
    char_summary = ""
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
        if row:
            c = json.loads(row["data_json"])
            identity = c.get("identity", {})
            char_name = identity.get("name", c.get("name", "未知"))
            psych = c.get("psychology", {}).get("state", {})
            char_summary = f"角色：{char_name}，心理状态：{psych}"
    except Exception:
        pass

    prompt = (
        f"当前场景：{context}\n{char_summary}\n\n"
        f"为玩家生成 {count} 个行动选项，每项包含简短标签和描述。\n"
        "以 JSON 数组返回：[{\"label\":\"A\",\"text\":\"...\"}, ...]"
    )
    try:
        resp = await llm_complete(
            messages=[
                {"role": "system", "content": "你是跑团GM，负责生成简洁的行动选项。"},
                {"role": "user", "content": prompt},
            ],
            # 注：此处硬编码 provider/model，未走 load_agent_config()（NEW-C11-04），
            # 故不受会话 LLM 配置影响；与 outline_chapter 等叙事工具行为不一致，待统一。
            provider="deepseek", model="deepseek-chat",
            temperature=0.7, max_tokens=300,
        )
        # 提取 JSON
        import re
        m = re.search(r"\[.*\]", resp, re.DOTALL)
        options = json.loads(m.group(0)) if m else []
    except Exception:
        labels = ["A", "B", "C", "D"]
        options = [{"label": labels[i], "text": f"行动选项 {labels[i]}"} for i in range(count)]

    # 发布 action_options Part（供前端渲染选项卡）
    try:
        from ..bus import bus as _bus
        from ..db import get_db as _get_db
        from ..db.schema import PartType as _PT
        import uuid as _uuid
        from datetime import datetime as _dt
        part_id = str(_uuid.uuid4())
        content = {"options": options, "context": context[:200] if context else ""}
        now_ts = _dt.now().timestamp()
        # 写 DB（尝试获取最新 message_id）
        try:
            async with _get_db() as _db:
                if not _msg_id:
                    msg_row = await (await _db.execute(
                        "SELECT id FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                        (session_id,),
                    )).fetchone()
                    msg_id = msg_row["id"] if msg_row else "unknown"
                else:
                    msg_id = _msg_id
                await _db.execute(
                    "INSERT OR IGNORE INTO message_parts "
                    "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'done', 'dm', ?, ?)",
                    (part_id, msg_id, session_id, _PT.ACTION_OPTIONS,
                     json.dumps(content, ensure_ascii=False), now_ts, now_ts),
                )
                await _db.commit()
        except Exception:
            pass
        # 先 created 再 done，确保前端 addPart 正确处理
        await _bus.publish_part_created(session_id, part_id, _PT.ACTION_OPTIONS, _msg_id or "unknown", "dm")
        await _bus.publish_part_done(session_id, part_id, content)
    except Exception:
        pass

    return {"options": options, "session_id": session_id}


# ── 叙事注入工具 ──────────────────────────────────────────────────────────────

async def _write_narrative(
    session_id: str,
    text: str,
    label: str = "",
) -> dict:
    """
    将指定文本作为 narrative Part 直接注入到当前回合的消息流（供 DM 手动追加叙事）。
    text: 要注入的叙事文本（支持 Markdown）
    label: 可选标签，显示在 Part 标题
    """
    from ..db import get_db as _gdb
    from ..bus import bus as _bus
    from ..db.schema import PartType as _PT
    import uuid as _u
    from datetime import datetime as _dt

    part_id = str(_u.uuid4())
    now_ts = _dt.now().timestamp()
    content = {"text": text, "label": label or "GM旁白"}

    try:
        async with _gdb() as db:
            msg_row = await (await db.execute(
                "SELECT id FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            )).fetchone()
            msg_id = msg_row["id"] if msg_row else "unknown"
            await db.execute(
                "INSERT OR IGNORE INTO message_parts "
                "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'done', 'dm', ?, ?)",
                (part_id, msg_id, session_id, _PT.NARRATIVE,
                 json.dumps(content, ensure_ascii=False), now_ts, now_ts),
            )
            await db.commit()
        await _bus.publish_part_created(session_id, part_id, _PT.NARRATIVE, msg_id, "dm")
        await _bus.publish_part_done(session_id, part_id, content)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "part_id": part_id}


async def _query_character_summary(session_id: str) -> dict:
    """
    返回人类可读的角色摘要（身份/核心属性/HP/心理状态/持有道具），
    比 read_character 更简洁，适合 DM 在 tool_loop 中快速了解角色状态。
    """
    from ..db import get_db
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )).fetchone()
    if not row:
        return {"error": "no character found"}

    c = json.loads(row["data_json"])
    identity = c.get("identity", {})
    attrs = c.get("attributes", {})
    psych = c.get("psychology", {}).get("state", {})
    inventory = c.get("inventory", [])

    # 提取属性摘要
    attr_summary = {k: v.get("current", v.get("base", v)) if isinstance(v, dict) else v
                    for k, v in attrs.items()}
    # 提取道具名
    items = [f"{it.get('name','?')}×{it.get('count',1)}" for it in inventory[:5]]

    return {
        "name": identity.get("name", "未知"),
        "age": identity.get("age", ""),
        "attributes": attr_summary,
        "psychology": psych,
        "inventory_preview": items,
        "meta": c.get("meta", {}),
    }


async def _edit_npc_state(
    session_id: str,
    npc_name: str,
    patches: list,
) -> dict:
    """
    通过 TavernCommand patches 修改 npc_profiles 表中指定 NPC 的 profile_json。
    patches 格式：[{cmd, key, value}]，key 为 profile_json 内的点分路径。
    """
    from ..db import get_db
    from ..engine import TavernCommandProcessor

    processor = TavernCommandProcessor()
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT id, profile_json FROM npc_profiles WHERE session_id=? AND name=?",
            (session_id, npc_name),
        )).fetchone()
        if not row:
            return {"error": f"NPC '{npc_name}' not found"}
        try:
            profile = json.loads(row["profile_json"])
        except Exception:
            profile = {}
        updated = processor.apply_patches(patches, profile)
        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE npc_profiles SET profile_json=?, updated_at=? WHERE id=?",
            (json.dumps(updated, ensure_ascii=False), now, row["id"]),
        )
        await db.commit()
    return {"ok": True, "npc": npc_name, "patches_applied": len(patches)}


# ── 奖励/经济系统 ─────────────────────────────────────────────────────────────

async def _earn_reward(
    session_id: str,
    item_name: str,
    item_key: str = "",
    count: int = 1,
    quality: str = "common",
    description: str = "",
) -> dict:
    """
    给角色添加一件物品到 inventory（角色卡 data_json.inventory 列表）。
    同时写入日志记忆条目。
    """
    from ..db import get_db
    key = item_key or item_name.lower().replace(" ", "_")[:32]
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}
            char = json.loads(row["data_json"])
            inventory: list = char.setdefault("inventory", [])
            # 如果已有同 key 物品，增加数量
            for item in inventory:
                if item.get("key") == key:
                    item["count"] = item.get("count", 1) + count
                    break
            else:
                inventory.append({
                    "id": str(uuid.uuid4()),
                    "key": key,
                    "name": item_name,
                    "count": count,
                    "quality": quality,
                    "description": description,
                })
            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )
            # 写日志记忆
            await db.execute(
                "INSERT OR IGNORE INTO memory_entries "
                "(id, session_id, content, tier, cognitive_partition, source_agent, created_at) "
                "VALUES (?, ?, ?, 'semantic', 'character_pov', 'tool:earn_reward', ?)",
                (str(uuid.uuid4()), session_id,
                 f"获得道具：{item_name}×{count}（{quality}品质）{' — '+description if description else ''}",
                 now)
            )
            await db.commit()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True, "item": {"key": key, "name": item_name, "count": count, "quality": quality}}


# ── 经济工具实现 ──────────────────────────────────────────────────────────────

async def _open_shop(
    session_id: str,
    shop_type: str = "misc",
    world_plugin: str = "",
    count: int = 5,
) -> dict:
    """
    调用 LLM 依据世界设定动态生成商店货架，返回商品列表。
    格式：[{name, key, price, quality, description}]
    """
    from ..llm.client import llm_complete
    from ..db import get_db

    # 获取世界插件名称
    if not world_plugin:
        try:
            async with get_db() as db:
                row = await (await db.execute(
                    "SELECT world_plugin FROM sessions WHERE id=?", (session_id,)
                )).fetchone()
                if row:
                    world_plugin = row["world_plugin"]
        except Exception:
            world_plugin = "crossover"

    count = max(3, min(8, count))
    prompt = (
        f"你是世界【{world_plugin}】中一名商人。请为玩家生成一个【{shop_type}】类型的商店货架，"
        f"包含 {count} 件商品。\n"
        "以 JSON 列表返回，每项格式：\n"
        '{"name":"...", "key":"...", "price":整数铜币, "quality":"common|rare|epic|legendary", "description":"..."}\n'
        "只输出 JSON 列表，不要任何解释。"
    )
    try:
        raw = await llm_complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=512,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            items = []
    except Exception as e:
        items = [
            {"name": "普通长剑", "key": "sword_basic", "price": 100, "quality": "common",
             "description": "标准铁制长剑"},
            {"name": "生命药水", "key": "potion_hp", "price": 50, "quality": "common",
             "description": "恢复 2d6 HP"},
        ]
    return {"ok": True, "shop_type": shop_type, "world": world_plugin, "items": items}


async def _evaluate_item(
    session_id: str,
    item_name: str,
    item_quality: str = "common",
    world_plugin: str = "",
) -> dict:
    """
    用 LLM 评估物品市场价值，返回价格区间和说明。
    """
    from ..llm.client import llm_complete
    from ..db import get_db

    if not world_plugin:
        try:
            async with get_db() as db:
                row = await (await db.execute(
                    "SELECT world_plugin FROM sessions WHERE id=?", (session_id,)
                )).fetchone()
                if row:
                    world_plugin = row["world_plugin"]
        except Exception:
            world_plugin = "crossover"

    prompt = (
        f"世界背景：{world_plugin}。物品：【{item_name}】（{item_quality}品质）。\n"
        "请估算该物品的公平市场价格，以铜币为单位。\n"
        "以 JSON 返回：{\"min\": 整数, \"max\": 整数, \"fair\": 整数, \"reason\": \"...\"}\n"
        "只输出 JSON，不要其他内容。"
    )
    try:
        raw = await llm_complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=128,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
    except Exception:
        quality_mult = {"common": 1, "rare": 5, "epic": 20, "legendary": 100}.get(item_quality, 1)
        result = {
            "min": 50 * quality_mult,
            "max": 200 * quality_mult,
            "fair": 100 * quality_mult,
            "reason": "基于品质估算",
        }
    return {"ok": True, "item": item_name, "quality": item_quality, **result}


async def _purchase_item(
    session_id: str,
    item_name: str,
    price: int,
    item_key: str = "",
    count: int = 1,
    quality: str = "common",
) -> dict:
    """
    购买物品：扣除角色 meta.gold（铜币），将物品加入 inventory。
    若余额不足，返回 insufficient_funds 错误。
    """
    from ..db import get_db
    key = item_key or item_name.lower().replace(" ", "_")[:32]
    total_cost = price * count
    now = datetime.now().timestamp()

    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}

            char = json.loads(row["data_json"])
            meta: dict = char.setdefault("meta", {})
            current_gold = int(meta.get("gold", 0))

            if current_gold < total_cost:
                return {
                    "ok": False,
                    "error": "insufficient_funds",
                    "current_gold": current_gold,
                    "required": total_cost,
                }

            # 扣除金币
            meta["gold"] = current_gold - total_cost

            # 添加物品
            inventory: list = char.setdefault("inventory", [])
            for item in inventory:
                if item.get("key") == key:
                    item["count"] = item.get("count", 1) + count
                    break
            else:
                inventory.append({
                    "id": str(uuid.uuid4()),
                    "key": key,
                    "name": item_name,
                    "count": count,
                    "quality": quality,
                    "description": f"购自商店，价格 {price} 铜币/个",
                })

            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )

            # 写购买记忆
            await db.execute(
                "INSERT OR IGNORE INTO memory_entries "
                "(id, session_id, content, tier, cognitive_partition, source_agent, created_at) "
                "VALUES (?, ?, ?, 'episodic', 'player_action', 'tool:purchase_item', ?)",
                (str(uuid.uuid4()), session_id,
                 f"购买：{item_name}×{count}，花费 {total_cost} 铜币，余额 {meta['gold']} 铜币",
                 now)
            )
            await db.commit()
    except Exception as e:
        return {"error": str(e)}

    return {
        "ok": True,
        "item": {"key": key, "name": item_name, "count": count, "quality": quality},
        "spent": total_cost,
        "remaining_gold": meta["gold"],
    }


# ── review / plan 专用工具 ───────────────────────────────────────────────────────

async def _read_chapter(session_id: str, limit: int = 3) -> dict:
    """
    读取最近 N 个章节的摘要和关键事件（review/plan 模式使用）。
    返回章节上下文字符串，供 Agent 重审或大纲规划。
    """
    try:
        from ..agents.chronicler_agent import get_chapter_context
        context = await get_chapter_context(session_id, limit=limit)
        return {"ok": True, "context": context, "session_id": session_id, "limit": limit}
    except Exception as e:
        logger.warning(f"[read_chapter] failed: {e}")
        return {"ok": False, "error": str(e), "context": ""}


async def _style_check(text: str) -> dict:
    """
    对指定文本执行文风纯净度检查（程序化，无需 LLM）。
    返回 score（0-1，越高越好）和 warnings 列表。
    """
    try:
        from ..agents.style_agent import _program_purity_scan
        score, warnings = _program_purity_scan(text)
        return {"ok": True, "score": score, "warnings": warnings, "passed": score >= 0.7}
    except Exception as e:
        return {"ok": False, "error": str(e), "score": 0.0, "warnings": []}


async def _purity_check(session_id: str) -> dict:
    """
    对当前会话最新 narrative Part 执行文风纯净度检查。
    review 模式下用于自动标记需要润色的段落。
    """
    from ..db import get_db
    latest_text = ""
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT content FROM message_parts "
                "WHERE session_id=? AND type='narrative' AND status='done' "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            )).fetchone()
        if row:
            import json as _json
            latest_text = _json.loads(row["content"]).get("text", "")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not latest_text:
        return {"ok": True, "score": 1.0, "warnings": [], "text_length": 0, "message": "no narrative found"}

    try:
        from ..agents.style_agent import _program_purity_scan
        score, warnings = _program_purity_scan(latest_text)
        return {
            "ok": True,
            "score": score,
            "warnings": warnings,
            "passed": score >= 0.7,
            "text_length": len(latest_text),
            "session_id": session_id,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _outline_chapter(
    session_id: str,
    goal: str = "",
    beats: int = 3,
) -> dict:
    """
    为下一章节生成结构化大纲（plan 模式使用）。
    返回 N 个叙事节拍（beats）的规划框架，不写入实际叙事。
    """
    from ..db import get_db
    from ..agents.llm import llm_complete, load_agent_config

    # 读取最近章节摘要作为上下文
    chapter_context = ""
    try:
        from ..agents.chronicler_agent import get_chapter_context
        chapter_context = await get_chapter_context(session_id, limit=2)
    except Exception:
        pass

    char_info = ""
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1",
                (session_id,),
            )).fetchone()
        if row:
            import json as _json
            char = _json.loads(row["data_json"])
            char_info = f"角色：{char.get('name', '主角')}，当前状态：{char.get('meta', {}).get('status', '正常')}"
    except Exception:
        pass

    system_prompt = (
        "你是专业的叙事规划师。根据已有章节摘要和目标，"
        f"为接下来的叙事生成 {beats} 个故事节拍的大纲。"
        "每个节拍格式：{index}. [节拍类型（行动/对话/转折/揭示）] 简短描述（≤30字）"
        "最后一行输出 JSON：{\"beats\": [...], \"chapter_goal\": \"...\", \"estimated_turns\": N}"
    )
    user_content = f"已有上下文：\n{chapter_context}\n\n{char_info}\n\n规划目标：{goal or '按自然叙事推进'}"

    try:
        cfg = load_agent_config("narrator")
        result = await llm_complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            provider=cfg.get("provider", "deepseek"),
            model=cfg.get("model", "deepseek-chat"),
            temperature=0.7,
            max_tokens=512,
        )
        return {"ok": True, "outline": result, "beats": beats, "goal": goal}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 章节分叉 / 固化工具 ───────────────────────────────────────────────────────

async def _fork_chapter(session_id: str, branch_label: str = "") -> dict:
    """
    从当前活跃章节创建分支章节。
    返回新章节 ID，供后续 NPC/DM 在分支叙事中使用。
    """
    from ..db import get_db
    now = datetime.now().timestamp()
    new_id = str(uuid.uuid4())
    label = branch_label or f"branch-{new_id[:8]}"

    async with get_db() as db:
        # 查最新 active 章节
        row = await (await db.execute(
            "SELECT id, chapter_index FROM chapters "
            "WHERE session_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )).fetchone()
        parent_id = row["id"] if row else None
        next_index = (row["chapter_index"] + 1) if row else 1

        await db.execute(
            "INSERT INTO chapters "
            "(id, session_id, parent_chapter_id, branch_label, chapter_index, "
            "summary, key_events, is_consolidated, turn_count, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', '[]', 0, 0, 'active', ?, ?)",
            (new_id, session_id, parent_id, label, next_index, now, now),
        )
        await db.commit()

    return {
        "ok": True,
        "chapter_id": new_id,
        "branch_label": label,
        "parent_chapter_id": parent_id,
        "chapter_index": next_index,
    }


async def _consolidate_chapter(session_id: str, chapter_id: str = "") -> dict:
    """
    触发指定章节（或最新活跃章节）的记忆固化：
    将 episodic 记忆条目标记为 consolidated，并生成 semantic 摘要节点。
    """
    from ..db import get_db

    # 若未指定章节，取最新 active 章节
    if not chapter_id:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id FROM chapters "
                "WHERE session_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            )).fetchone()
        if not row:
            return {"error": "no active chapter found", "ok": False}
        chapter_id = row["id"]

    try:
        from ..memory.chapter_consolidator import ChapterConsolidator
        result = await ChapterConsolidator().consolidate_chapter(session_id, chapter_id)
        result["ok"] = True
        result["chapter_id"] = chapter_id
        return result
    except Exception as e:
        logger.warning(f"[consolidate_chapter] failed: {e}")
        return {"ok": False, "error": str(e), "chapter_id": chapter_id}


# ── Combat 工具实现 ───────────────────────────────────────────────────────────

async def _apply_damage(
    session_id: str,
    damage: int,
    part: str = "torso",
    damage_type: str = "physical",
    is_critical: bool | None = None,
    attacker_tier: int = 1,
    bypass_armor: bool = False,
) -> dict:
    """对指定部位施加伤害，写回 DB。"""
    from ..db import get_db
    from ..engine.combat import CombatEngine
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT id, data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )).fetchone()
        if not row:
            return {"ok": False, "error": "character not found"}
        char_data = json.loads(row["data_json"])

    result = CombatEngine.apply_damage(
        char_data, damage, part=part, damage_type=damage_type,
        is_critical=is_critical, attacker_tier=attacker_tier, bypass_armor=bypass_armor,
    )

    async with get_db() as db:
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
            (json.dumps(char_data, ensure_ascii=False), datetime.now().timestamp(), row["id"]),
        )
        await db.commit()

    return {
        "ok": True,
        "part": result.target_part,
        "part_name": result.part_name,
        "actual_damage": result.actual_damage,
        "absorbed_by_armor": result.absorbed_by_armor,
        "hp_before": result.hp_before,
        "hp_after": result.hp_after,
        "is_critical": result.is_critical,
        "knocked_out": result.knocked_out,
        "is_fatal": result.is_fatal,
        "new_status_effects": result.new_status_effects,
        "narrative_hint": result.narrative_hint,
    }


async def _apply_heal(
    session_id: str,
    heal_amount: int,
    part: str = "torso",
    remove_status: list | None = None,
) -> dict:
    """对指定部位施加治疗，写回 DB。"""
    from ..db import get_db
    from ..engine.combat import CombatEngine
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT id, data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )).fetchone()
        if not row:
            return {"ok": False, "error": "character not found"}
        char_data = json.loads(row["data_json"])

    result = CombatEngine.apply_heal(
        char_data, heal_amount, part=part, remove_status=remove_status or [],
    )

    async with get_db() as db:
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
            (json.dumps(char_data, ensure_ascii=False), datetime.now().timestamp(), row["id"]),
        )
        await db.commit()

    return {
        "ok": True,
        "part": result.target_part,
        "part_name": result.part_name,
        "heal_amount": result.heal_amount,
        "hp_before": result.hp_before,
        "hp_after": result.hp_after,
        "removed_status_effects": result.removed_status_effects,
    }


async def _get_combat_status(session_id: str) -> dict:
    """获取角色当前战斗状态（各部位 HP + 状态效果）。"""
    from ..db import get_db
    from ..engine.combat import CombatEngine
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )).fetchone()
        if not row:
            return {"ok": False, "error": "character not found"}
        char_data = json.loads(row["data_json"])

    overall = CombatEngine.get_overall_hp_ratio(char_data)
    incap = CombatEngine.is_incapacitated(char_data)
    summary = CombatEngine.format_combat_summary(char_data)
    parts = char_data.get("attributes", {}).get("hp", {}).get("parts", {})
    return {
        "ok": True,
        "overall_hp_ratio": round(overall, 3),
        "incapacitated": incap,
        "summary": summary,
        "parts": {
            k: {
                "current": v.get("current", 0),
                "max": v.get("max", 100),
                "armor": v.get("armor", 0),
                "status_effects": v.get("status_effects", []),
            }
            for k, v in parts.items()
            if isinstance(v, dict)
        },
    }


async def _roll_hit_location(bias: str = "none") -> dict:
    """随机生成命中部位。"""
    from ..engine.combat import CombatEngine
    part = CombatEngine.roll_hit_location(bias=bias)
    from ..engine.combat import _PART_CONFIG
    _, _, name = _PART_CONFIG[part]
    return {"ok": True, "part": part, "part_name": name, "bias": bias}


# ── Web 爬虫工具 ─────────────────────────────────────────────────────────────

async def _fetch_web_lore(url: str, session_id: str = "", world_id: str = "") -> dict:
    """
    抓取指定 URL 的内容，通过 LLM 提炼为世界观档案条目。
    - 若指定 session_id：提炼结果写入该会话的 world_archives
    - 若指定 world_id：提炼结果写入全局世界模板 world_archive_entries
    - 两者都未指定：只返回提炼结果，不写库
    """
    from ..utils.web_scraper import fetch_url_text, get_rule_for_url
    from ..agents.llm import llm_complete

    rule = get_rule_for_url(url)
    logger.info(f"[fetch_web_lore] url={url[:80]} rule={rule.get('alias') if rule else 'default'}")

    try:
        raw_text, engine = await fetch_url_text(url)
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url, "entries": []}

    if not raw_text:
        return {"ok": False, "error": "页面内容为空", "url": url, "entries": []}

    _system = """你是一个世界观档案提炼助手。
从用户提供的原始文本中提炼适合 TRPG/小说创作的世界观条目。
每条包含：title（简洁标题）、content（具体内容，300字以内）、archive_type（lore/rule/setting/npc 之一）。
输出格式：JSON 数组 [{"title":"...","content":"...","archive_type":"..."}]
只输出 JSON，不要其他文字。"""

    try:
        raw = await llm_complete(
            messages=[
                {"role": "system", "content": _system},
                {"role": "user", "content": f"请从以下文本提炼世界观档案条目：\n\n{raw_text[:8000]}"},
            ],
            max_tokens=2000,
        )
        s = raw.find("[")
        e = raw.rfind("]") + 1
        entries = json.loads(raw[s:e]) if s >= 0 else []
    except Exception as ex:
        return {"ok": False, "error": f"LLM 提炼失败: {ex}", "url": url, "entries": []}

    # 写库
    written = 0
    if entries:
        now = __import__("time").time()
        if world_id:
            from ..db import get_db as _gdb
            import uuid as _uuid
            async with _gdb() as db:
                for entry in entries:
                    aid = str(_uuid.uuid4())
                    await db.execute(
                        "INSERT INTO world_archive_entries (id, world_id, title, content, archive_type, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (aid, world_id, entry.get("title", ""), entry.get("content", ""), entry.get("archive_type", "lore"), now, now)
                    )
                await db.commit()
                written = len(entries)
        elif session_id:
            from ..db import get_db as _gdb
            import uuid as _uuid
            async with _gdb() as db:
                for entry in entries:
                    aid = str(_uuid.uuid4())
                    wk = f"web_{aid[:8]}"
                    await db.execute(
                        "INSERT OR IGNORE INTO world_archives (id, session_id, title, content, archive_type, world_key, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (aid, session_id, entry.get("title", ""), entry.get("content", ""), entry.get("archive_type", "lore"), wk, now, now)
                    )
                await db.commit()
                written = len(entries)

    return {
        "ok": True,
        "url": url,
        "engine": engine,
        "entries": entries,
        "entries_count": len(entries),
        "written": written,
        "rule_alias": rule.get("alias", "default") if rule else "default",
    }


async def _list_scraper_rules() -> dict:
    """列出当前所有网页抓取站点规则（含禁用的），供 Agent 了解可用来源。"""
    from ..utils.web_scraper import list_rules
    rules = list_rules()
    return {
        "rules": [
            {
                "domain": r.get("domain"),
                "alias": r.get("alias"),
                "engine": r.get("engine"),
                "enabled": r.get("enabled", True),
                "notes": r.get("notes", ""),
            }
            for r in rules
        ],
        "total": len(rules),
        "enabled": sum(1 for r in rules if r.get("enabled", True)),
    }


# ── 注册函数 ──────────────────────────────────────────────────────────────────

def _register_all() -> None:
    """将所有内置工具注册到全局 tool_registry。"""

    tool_registry.register(ToolDef(
        name="read_character",
        description="从数据库读取当前会话的角色卡 JSON，包含属性、技能、心理状态等完整数据。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_read_character,
        permission_required="allow",
        tags=["read", "character"],
    ))

    tool_registry.register(ToolDef(
        name="update_character_state",
        description="更新角色状态（stress/morale/hp 等），使用 TavernCommand patches 格式。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "patches": {
                    "type": "array",
                    "description": "补丁列表，每项格式 {cmd, key, value}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "string", "enum": ["SET", "ADD", "MUL", "DIV"]},
                            "key": {"type": "string", "description": "点分隔的属性路径，如 psychology.state.stress"},
                            "value": {"type": "string", "description": "目标值（SET）或增量字符串（ADD）"},
                            "delta": {"type": "number", "description": "数值增量（ADD 专用，可选）"},
                        },
                        "required": ["cmd", "key", "value"],
                    },
                },
            },
            "required": ["session_id", "patches"],
        },
        handler=_update_character_state,
        permission_required="allow",
        tags=["write", "character"],
    ))

    tool_registry.register(ToolDef(
        name="search_memory",
        description="对会话记忆进行语义搜索，返回相关上下文片段（混合向量+词法召回）。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "query": {"type": "string", "description": "搜索查询文本"},
                "top_k": {"type": "integer", "description": "返回条目数上限", "default": 5},
            },
            "required": ["session_id", "query"],
        },
        handler=_search_memory,
        permission_required="allow",
        tags=["read", "memory"],
    ))

    tool_registry.register(ToolDef(
        name="get_chapter_summaries",
        description="获取最近 N 个已固化章节的摘要，用于长程记忆提取。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "limit": {"type": "integer", "description": "返回章节数", "default": 3},
            },
            "required": ["session_id"],
        },
        handler=_get_chapter_summaries,
        permission_required="allow",
        tags=["read", "memory"],
    ))

    tool_registry.register(ToolDef(
        name="roll_dice",
        description="执行 d10 骰池判定，返回完整结果（rolls、net、verdict、narrative_hint 等）。",
        parameters={
            "type": "object",
            "properties": {
                "pool": {"type": "integer", "description": "骰池大小（骰子数量）", "minimum": 0},
                "threshold": {"type": "integer", "description": "成功阈值（默认 8）", "default": 8, "minimum": 1, "maximum": 10},
                "reason": {"type": "string", "description": "判定原因（用于叙事提示）", "default": ""},
            },
            "required": ["pool"],
        },
        handler=_roll_dice,
        permission_required="allow",
        tags=["dice"],
    ))

    tool_registry.register(ToolDef(
        name="get_world_state",
        description="获取当前会话的世界状态快照（state_json），包含场景、NPC、天气等动态信息。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_get_world_state,
        permission_required="allow",
        tags=["read", "world"],
    ))

    tool_registry.register(ToolDef(
        name="update_world_state",
        description="通过 TavernCommand patches 更新世界状态，支持 SET/ADD/MUL/DIV 操作。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "patches": {
                    "type": "array",
                    "description": "补丁列表，每项格式 {cmd, key, value}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "string", "enum": ["SET", "ADD", "MUL", "DIV"]},
                            "key": {"type": "string", "description": "点分隔的状态路径"},
                            "value": {"type": "string", "description": "目标值或增量"},
                            "delta": {"type": "number", "description": "数值增量（ADD 专用，可选）"},
                        },
                        "required": ["cmd", "key", "value"],
                    },
                },
            },
            "required": ["session_id", "patches"],
        },
        handler=_update_world_state,
        permission_required="allow",
        tags=["write", "world"],
    ))

    tool_registry.register(ToolDef(
        name="write_journal",
        description="将重要事件写入玩家日志（memory_entries tier=core），用于长期记忆锚定。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "content": {"type": "string", "description": "日志内容"},
                "event_type": {"type": "string", "description": "事件类型标签，如 general/combat/discovery", "default": "general"},
            },
            "required": ["session_id", "content"],
        },
        handler=_write_journal,
        permission_required="allow",
        tags=["write", "narrative"],
    ))

    # ── 世界设定搜索 ──────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="search_lore",
        description="在世界档案（lore/rule/setting）中关键词搜索，返回相关设定条目。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "query": {"type": "string", "description": "搜索关键词"},
                "top_k": {"type": "integer", "description": "返回条目数", "default": 5},
            },
            "required": ["session_id", "query"],
        },
        handler=_search_lore,
        permission_required="allow",
        tags=["read", "lore"],
    ))

    # ── 属性技能检定 ──────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="roll_check",
        description="按角色属性+技能值建立骰池执行 d10 检定，自动读取角色卡数据。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "attribute": {"type": "string", "description": "属性名（如 strength/intelligence）"},
                "skill": {"type": "string", "description": "技能名（可空）", "default": ""},
                "difficulty": {"type": "integer", "description": "难度级别", "default": 1},
                "reason": {"type": "string", "description": "判定原因", "default": ""},
            },
            "required": ["session_id", "attribute"],
        },
        handler=_roll_check,
        permission_required="allow",
        tags=["dice", "character"],
    ))

    # ── 按需加载技能 ──────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="load_skill",
        description="按需加载指定技能（SKILL.md），注入当前回合提示词层并发布 skill_load Part。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "skill_name": {"type": "string", "description": "技能唯一名称"},
            },
            "required": ["session_id", "skill_name"],
        },
        handler=_load_skill,
        permission_required="allow",
        tags=["skill"],
    ))

    # ── NPC 生成 ──────────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="spawn_npc",
        description="在当前会话生成并持久化一个 NPC，返回 profile 供叙事使用。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "name": {"type": "string", "description": "NPC 名称"},
                "role": {"type": "string", "description": "角色定位：minor/major/boss", "default": "minor"},
                "traits": {"type": "array", "items": {"type": "string"}, "description": "性格/外观标签"},
                "faction": {"type": "string", "description": "所属势力", "default": ""},
            },
            "required": ["session_id", "name"],
        },
        handler=_spawn_npc,
        permission_required="allow",
        tags=["write", "npc"],
    ))

    # ── 行动选项生成 ──────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="generate_action_options",
        description="根据当前场景为玩家生成 3~4 个可选行动（A/B/C），方便玩家选择。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "context": {"type": "string", "description": "当前场景描述（可选）", "default": ""},
                "count": {"type": "integer", "description": "生成选项数量", "default": 3},
            },
            "required": ["session_id"],
        },
        handler=_generate_action_options,
        permission_required="allow",
        tags=["narrative", "options"],
    ))

    # ── 奖励道具 ──────────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="earn_reward",
        description="给角色 inventory 添加道具，并写入日志记忆。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "item_name": {"type": "string", "description": "物品名称"},
                "item_key": {"type": "string", "description": "物品唯一键（可选，默认由名称派生）", "default": ""},
                "count": {"type": "integer", "description": "数量", "default": 1},
                "quality": {"type": "string", "description": "品质等级：common/rare/epic/legendary", "default": "common"},
                "description": {"type": "string", "description": "物品描述", "default": ""},
            },
            "required": ["session_id", "item_name"],
        },
        handler=_earn_reward,
        permission_required="allow",
        tags=["write", "inventory"],
    ))

    # ── 叙事注入 ──────────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="write_narrative",
        description="将指定文本作为 narrative Part 直接注入消息流，供 DM 手动追加或修正叙事内容。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "text":       {"type": "string", "description": "要注入的叙事文本（支持 Markdown）"},
                "label":      {"type": "string", "description": "Part 标签，默认 GM旁白", "default": ""},
            },
            "required": ["session_id", "text"],
        },
        handler=_write_narrative,
        permission_required="allow",
        tags=["write", "narrative"],
    ))

    tool_registry.register(ToolDef(
        name="query_character_summary",
        description="获取角色简洁摘要（身份/属性/心理/道具），比 read_character 更适合 DM 快速决策使用。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_query_character_summary,
        permission_required="allow",
        tags=["read", "character"],
    ))

    tool_registry.register(ToolDef(
        name="edit_npc_state",
        description="通过 TavernCommand patches 修改 NPC 的 profile_json 状态（如 hp/relation/mood）。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "npc_name":   {"type": "string", "description": "NPC 名称（匹配 npc_profiles.name）"},
                "patches": {
                    "type": "array",
                    "description": "补丁列表 [{cmd, key, value}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cmd":   {"type": "string", "enum": ["SET", "ADD", "MUL", "DIV"]},
                            "key":   {"type": "string", "description": "点分隔的状态路径"},
                            "value": {"type": "string", "description": "目标值"},
                        },
                        "required": ["cmd", "key", "value"],
                    },
                },
            },
            "required": ["session_id", "npc_name", "patches"],
        },
        handler=_edit_npc_state,
        permission_required="allow",
        tags=["write", "npc"],
    ))

    # ── NPC 专用工具 ─────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="query_npc_profile",
        description="从世界档案或角色卡中查询指定 NPC 的完整档案（性格、背景、状态等）。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "npc_name": {"type": "string", "description": "NPC 名称"},
            },
            "required": ["session_id", "npc_name"],
        },
        handler=_query_npc_profile,
        permission_required="allow",
        tags=["read", "npc"],
        group="npc",
    ))

    tool_registry.register(ToolDef(
        name="get_npc_knowledge_scope",
        description="查询指定 NPC 的知识边界，返回该 NPC 已知与不知道的事项范围。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "npc_name": {"type": "string", "description": "NPC 名称"},
            },
            "required": ["session_id", "npc_name"],
        },
        handler=_get_npc_knowledge_scope,
        permission_required="allow",
        tags=["read", "npc"],
        group="npc",
    ))

    tool_registry.register(ToolDef(
        name="update_npc_state",
        description="更新指定 NPC 的状态字段（如情绪/态度/位置），合并写入世界档案。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "npc_name": {"type": "string", "description": "NPC 名称"},
                "changes": {
                    "type": "object",
                    "description": "要合并更新的字段 dict，如 {\"mood\": \"angry\", \"location\": \"tavern\"}",
                },
            },
            "required": ["session_id", "npc_name", "changes"],
        },
        handler=_update_npc_state,
        permission_required="allow",
        tags=["write", "npc"],
        group="npc",
    ))

    # ── RulesAgent 专用工具 ──────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="check_skill_trigger",
        description="检查玩家行动是否触发角色技能特效，返回应激活的技能列表。供 RulesAgent 裁决前使用。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "action_text": {"type": "string", "description": "玩家行动文本"},
            },
            "required": ["session_id", "action_text"],
        },
        handler=_check_skill_trigger,
        permission_required="allow",
        tags=["read", "rules", "character"],
        group="engine",
    ))

    tool_registry.register(ToolDef(
        name="query_world_rules",
        description="查询当前世界的硬性规则（从世界档案获取 rule 类型条目），供 RulesAgent 在裁决前确认约束。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "rule_topic": {"type": "string", "description": "规则主题（如 '魔法使用' / '领地限制'）"},
            },
            "required": ["session_id", "rule_topic"],
        },
        handler=_query_world_rules,
        permission_required="allow",
        tags=["read", "rules", "lore"],
        group="engine",
    ))

    # ── 经济工具 trio ─────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="open_shop",
        description="为当前场景生成一个商店货架列表（由 LLM 依据世界设定动态生成），返回可购买物品及其价格。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "shop_type": {"type": "string", "description": "商店类型，如 weapon/potion/misc", "default": "misc"},
                "world_plugin": {"type": "string", "description": "世界插件名称", "default": ""},
                "count": {"type": "integer", "description": "生成商品数量（3~8）", "default": 5},
            },
            "required": ["session_id"],
        },
        handler=_open_shop,
        permission_required="allow",
        tags=["economy", "narrative"],
        group="economy",
    ))

    tool_registry.register(ToolDef(
        name="evaluate_item",
        description="评估指定物品的公平市价（铜/银/金币单位），返回价格区间及说明。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "item_name": {"type": "string", "description": "物品名称"},
                "item_quality": {"type": "string", "description": "品质：common/rare/epic/legendary", "default": "common"},
                "world_plugin": {"type": "string", "description": "世界插件名称", "default": ""},
            },
            "required": ["session_id", "item_name"],
        },
        handler=_evaluate_item,
        permission_required="allow",
        tags=["economy", "read"],
        group="economy",
    ))

    tool_registry.register(ToolDef(
        name="purchase_item",
        description="执行购买操作：扣除角色金币，将物品加入 inventory；若余额不足则拒绝。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "item_name": {"type": "string", "description": "物品名称"},
                "item_key": {"type": "string", "description": "物品唯一键（可选）", "default": ""},
                "price": {"type": "integer", "description": "价格（铜币单位）"},
                "count": {"type": "integer", "description": "购买数量", "default": 1},
                "quality": {"type": "string", "description": "品质等级", "default": "common"},
            },
            "required": ["session_id", "item_name", "price"],
        },
        handler=_purchase_item,
        permission_required="allow",
        tags=["economy", "write", "inventory"],
        group="economy",
    ))

    tool_registry.register(ToolDef(
        name="read_chapter",
        description=(
            "读取最近 N 个章节的摘要和关键事件，返回章节上下文字符串。"
            "review/plan 模式专用：供 Agent 重审剧情或规划大纲时参考。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "limit": {"type": "integer", "description": "读取最近几章", "default": 3},
            },
            "required": ["session_id"],
        },
        handler=_read_chapter,
        permission_required="allow",
        tags=["chapter", "read"],
        group="chapter",
    ))

    tool_registry.register(ToolDef(
        name="style_check",
        description=(
            "对指定文本执行文风纯净度检查（程序化，无 LLM 调用）。"
            "返回 score（0-1）和命中俗套/心理分析的 warnings 列表。"
            "review 模式专用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待检查的正文文本"},
            },
            "required": ["text"],
        },
        handler=_style_check,
        permission_required="allow",
        tags=["style", "read"],
        group="narrative",
    ))

    tool_registry.register(ToolDef(
        name="purity_check",
        description=(
            "对当前会话最新 narrative Part 执行文风纯净度检查。"
            "score ≥ 0.7 为通过；低于该值会列出具体警告词组。"
            "review 模式专用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_purity_check,
        permission_required="allow",
        tags=["style", "read"],
        group="narrative",
    ))

    tool_registry.register(ToolDef(
        name="outline_chapter",
        description=(
            "为下一章节生成 N 个故事节拍的大纲规划（plan 模式专用）。"
            "基于已有章节摘要和目标，不写入实际叙事。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "goal": {"type": "string", "description": "本章规划目标（留空=自然推进）", "default": ""},
                "beats": {"type": "integer", "description": "故事节拍数量", "default": 3},
            },
            "required": ["session_id"],
        },
        handler=_outline_chapter,
        permission_required="allow",
        tags=["chapter", "plan", "write"],
        group="chapter",
    ))

    tool_registry.register(ToolDef(
        name="fork_chapter",
        description=(
            "从当前活跃章节创建分支章节（叙事分岔点），返回新章节 ID。"
            "用于 DM 想要开辟平行叙事线或玩家选择走不同路径时。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "branch_label": {"type": "string", "description": "分支名称（可选，如'timeline-A'）", "default": ""},
            },
            "required": ["session_id"],
        },
        handler=_fork_chapter,
        permission_required="ask",
        tags=["chapter", "write"],
        group="chapter",
    ))

    tool_registry.register(ToolDef(
        name="consolidate_chapter",
        description=(
            "触发章节记忆固化：将 episodic 记忆标记为 consolidated，"
            "生成 semantic 摘要节点，为下一章节腾出记忆空间。"
            "chapter_id 留空则自动选择最新活跃章节。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "chapter_id": {"type": "string", "description": "要固化的章节 ID（留空=自动选最新活跃章节）", "default": ""},
            },
            "required": ["session_id"],
        },
        handler=_consolidate_chapter,
        permission_required="allow",
        tags=["chapter", "write", "memory"],
        group="chapter",
    ))

    # ── Combat 工具 ───────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="apply_damage",
        description=(
            "对角色指定部位施加伤害，返回伤害计算结果（实际伤害、护甲减免、新增状态效果）。"
            "play 模式自动执行，plan/review 模式需 ask 确认。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id":    {"type": "string", "description": "会话 ID"},
                "damage":        {"type": "integer", "description": "原始伤害值（正整数）"},
                "part":          {"type": "string",  "description": "受击部位：head/torso/left_arm/right_arm/left_leg/right_leg", "default": "torso"},
                "damage_type":   {"type": "string",  "description": "伤害类型：physical/qi/magic/tech", "default": "physical"},
                "is_critical":   {"type": "boolean", "description": "强制暴击（null=随机）"},
                "attacker_tier": {"type": "integer", "description": "攻击方等级（影响穿甲）", "default": 1},
                "bypass_armor":  {"type": "boolean", "description": "是否真伤（无视护甲）", "default": False},
            },
            "required": ["session_id", "damage"],
        },
        handler=_apply_damage,
        permission_required="allow",
        tags=["combat", "write"],
        group="combat",
    ))

    tool_registry.register(ToolDef(
        name="apply_heal",
        description="对角色指定部位施加治疗，可同时移除出血/骨折等状态效果。",
        parameters={
            "type": "object",
            "properties": {
                "session_id":     {"type": "string", "description": "会话 ID"},
                "heal_amount":    {"type": "integer","description": "治疗量（正整数）"},
                "part":           {"type": "string", "description": "治疗部位", "default": "torso"},
                "remove_status":  {"type": "array",  "items": {"type": "string"}, "description": "要移除的状态效果列表", "default": []},
            },
            "required": ["session_id", "heal_amount"],
        },
        handler=_apply_heal,
        permission_required="allow",
        tags=["combat", "write"],
        group="combat",
    ))

    tool_registry.register(ToolDef(
        name="get_combat_status",
        description="获取角色当前战斗状态摘要（各部位 HP、状态效果、综合 HP 比例）。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_get_combat_status,
        permission_required="allow",
        tags=["combat", "read"],
        group="combat",
    ))

    tool_registry.register(ToolDef(
        name="roll_hit_location",
        description="随机生成命中部位（可指定 bias 偏向：upper/lower/head/none）。",
        parameters={
            "type": "object",
            "properties": {
                "bias": {"type": "string", "description": "命中偏向：upper/lower/head/none", "default": "none"},
            },
            "required": [],
        },
        handler=_roll_hit_location,
        permission_required="allow",
        tags=["combat", "dice"],
        group="combat",
    ))

    # ── Web 爬虫工具 ──────────────────────────────────────────────────────────

    tool_registry.register(ToolDef(
        name="fetch_web_lore",
        description=(
            "抓取指定网页 URL（Wiki / Fandom / Wikipedia 等），通过 LLM 提炼为世界观档案条目。"
            "自动选择最合适的抓取引擎（httpx / Playwright）。"
            "若提供 world_id，条目写入全局世界模板；若提供 session_id，写入当前会话档案。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标网页 URL（需是 http/https 链接）"},
                "session_id": {"type": "string", "description": "会话 ID（写入 world_archives，可选）", "default": ""},
                "world_id": {"type": "string", "description": "全局世界模板 ID（写入 world_archive_entries，可选）", "default": ""},
            },
            "required": ["url"],
        },
        handler=_fetch_web_lore,
        permission_required="ask",
        tags=["web", "lore", "scraper"],
        group="lore",
    ))

    tool_registry.register(ToolDef(
        name="list_scraper_rules",
        description="列出当前配置的所有网页抓取站点规则（domain、引擎、启用状态），方便 Agent 选择来源站点。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_list_scraper_rules,
        permission_required="allow",
        tags=["web", "scraper", "config"],
        group="lore",
    ))

    logger.info(f"Builtin tools registered: {len(tool_registry._tools)} tools")

    # 扩展工具自动发现
    _discover_extension_tools()


def _discover_extension_tools() -> None:
    """
    扫描 backend/extensions/*/tools.py，自动将其中定义的 ToolDef 实例注册到全局 registry。
    扩展 tools.py 须在模块级暴露 TOOLS: list[ToolDef] 变量。
    """
    import importlib
    import importlib.util
    import sys
    from pathlib import Path

    ext_root = Path(__file__).parent.parent / "extensions"
    if not ext_root.is_dir():
        return

    for tools_file in sorted(ext_root.glob("*/tools.py")):
        ext_name = tools_file.parent.name
        # NEW-C8-01：跳过 `_` 前缀目录（如 _template 骨架），与 extension_loader.discover_extensions 行为一致，
        # 避免演示工具 template_example 被当成生产工具注册进全局 registry。
        if ext_name.startswith("_"):
            continue
        module_name = f"backend.extensions.{ext_name}.tools"
        try:
            spec = importlib.util.spec_from_file_location(module_name, tools_file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            tools_list = getattr(mod, "TOOLS", [])
            for tool_def in tools_list:
                if isinstance(tool_def, ToolDef) and tool_def.name not in tool_registry._tools:
                    tool_registry.register(tool_def)
                    logger.info(f"[ext] Registered tool '{tool_def.name}' from {ext_name}")
        except Exception as e:
            logger.warning(f"[ext] Failed to load tools from {ext_name}: {e}")


# 自动注册
_register_all()
