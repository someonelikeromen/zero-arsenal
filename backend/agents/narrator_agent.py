"""
NarratorAgent — 四阶段叙事流水线。
P1: Plan    非流式，确定场景目标和叙事方向
P2: Context 记忆检索（简化版，Phase 5 接入完整 memory/）
P3: Write   流式，生成正文，每 delta 触发 SSE part.updated
P4: Settle  非流式，提取变量变化（TavernCommand 简化版）
"""
from __future__ import annotations
import logging
import uuid
import json
import re
from datetime import datetime
from .state import TurnContext
from .llm import llm_complete, llm_stream, load_agent_config
from ..bus import bus, BusEvent, EventType
from ..db.schema import PartType

logger = logging.getLogger(__name__)


# ── P1 规划 ──────────────────────────────────────────────────────────────────

PLAN_SYSTEM = """\
你是跑团小说的叙事规划引擎。根据玩家行动和裁判结果，快速规划本轮叙事目标。

输出格式（严格 JSON，无代码块包裹）：
{
  "scene_goal": "本轮场景核心目标（1句话）",
  "tone": "紧张|轻松|神秘|危险|日常",
  "focus": "行动结果|环境描写|人物反应|战斗|对话",
  "pov": "角色名或'全知'"
}
"""

async def _p1_plan(ctx: TurnContext) -> tuple[str, dict]:
    cfg = load_agent_config("narrator_plan")
    roll_info = ""
    if ctx.roll_result:
        roll_info = f"\n骰子结果：{ctx.roll_result.get('result','?')}（净成功{ctx.roll_result.get('net',0)}）"

    # 从 PromptRegistry 构建 P1 系统提示（含 Layer 0 HARD-GATE + agent.narrator_p1）
    p1_system = PLAN_SYSTEM
    try:
        from ..prompts.registry import registry as _pr
        from ..extensions.plugin import plugin_registry as _plug_reg
        plugin = _plug_reg.get(ctx.world_plugin)
        if plugin:
            plugin.apply_to_registry(_pr)
        built = _pr.build_system_prompt(
            phase="p1",
            session_id=ctx.session_id,
            state={"world_plugin": ctx.world_plugin, "mode": ctx.mode},
        )
        if built.strip():
            p1_system = built
    except Exception:
        pass

    messages = [
        {"role": "system", "content": p1_system},
        {"role": "user", "content": (
            f"玩家行动：{ctx.user_input}\n"
            f"DM裁决：{ctx.dm_verdict} — {ctx.dm_note}{roll_info}"
        )},
    ]
    try:
        raw = await llm_complete(messages, **{k: cfg[k] for k in ("provider","model","temperature","max_tokens") if k in cfg})
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        # 尝试提取第一个 JSON 对象
        start = raw.find("{")
        if start != -1:
            raw = raw[start:]
        plan = json.loads(raw)
        return plan.get("scene_goal", ""), plan
    except Exception:
        return ctx.user_input, {"tone": "日常", "focus": "行动结果", "pov": "全知"}


# ── P2 Backend Data Stream（并发多路检索）─────────────────────────────────────

import asyncio as _asyncio

async def _p2_context(ctx: TurnContext) -> str:
    """
    P2 Backend Data Stream：并发拉取多路上下文，合并为叙事参考层。
    参考设计文档 05-prompt-architecture.md §6 / 03-agent-system.md §6.2

    数据流：
      - 会话记忆（hybrid recall）
      - 角色属性快照
      - 世界档案 lore（按关键词）
      - 章节摘要
    """
    query = ctx.user_input[:200]

    async def _recall_memory() -> str:
        try:
            from ..memory import memory_adapter
            return await memory_adapter.recall(
                session_id=ctx.session_id,
                world_plugin=ctx.world_plugin,
                query_text=query,
                viewer_agent="narrator",
                top_k=6,
            )
        except Exception:
            return ""

    async def _recall_lore() -> str:
        try:
            from ..db import get_db
            # 从查询中提取关键词（简单分词，取前3个2字以上词）
            import re
            keywords = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z]{4,}', query)[:3]
            if not keywords:
                return ""
            async with get_db() as db:
                results = []
                for kw in keywords:
                    rows = await (await db.execute(
                        "SELECT title, content FROM world_archives "
                        "WHERE session_id=? AND (title LIKE ? OR content LIKE ?) LIMIT 2",
                        (ctx.session_id, f"%{kw}%", f"%{kw}%")
                    )).fetchall()
                    for r in rows:
                        results.append(f"[设定] {r['title']}: {r['content'][:150]}")
            return "\n".join(results[:4]) if results else ""
        except Exception:
            return ""

    async def _char_snapshot() -> str:
        try:
            c = ctx.character_data or {}
            if not c:
                return ""
            attrs = c.get("attributes", {})
            psych = c.get("psychology", {}).get("state", {})
            # 只传关键数值，节省 token
            lines = [f"[角色状态] {c.get('name','?')}"]
            for k, v in list(attrs.items())[:5]:
                dots = v.get("dots", "?") if isinstance(v, dict) else v
                lines.append(f"  {k}: {dots}")
            for k, v in psych.items():
                lines.append(f"  心理/{k}: {v}")
            return "\n".join(lines)
        except Exception:
            return ""

    async def _chapter_summaries() -> str:
        try:
            from ..memory import memory_adapter
            return await memory_adapter.get_chapter_summaries(ctx.session_id, limit=2)
        except Exception:
            return ""

    # 并发执行四路检索
    memory_text, lore_text, char_text, chapter_text = await _asyncio.gather(
        _recall_memory(),
        _recall_lore(),
        _char_snapshot(),
        _chapter_summaries(),
        return_exceptions=True,
    )

    # 聚合（过滤异常）
    parts = []
    for label, text in [
        ("记忆", memory_text),
        ("角色", char_text),
        ("设定", lore_text),
        ("章节摘要", chapter_text),
    ]:
        if isinstance(text, str) and text.strip():
            parts.append(f"=== {label} ===\n{text.strip()}")

    return "\n\n".join(parts)


# ── P3 正文生成（流式） ───────────────────────────────────────────────────────

def _get_writing_style_prefix(ctx: TurnContext) -> str:
    """从角色卡或会话配置中读取文风偏好，加载对应的 Skill 内容作为 Layer 5 注入。"""
    try:
        style_name = (
            ctx.character_data.get("meta", {}).get("writing_style", "")
            or ctx.character_data.get("writing_style", "")
        )
        if not style_name:
            return ""

        from ..tools.skill_loader import skill_registry
        skills = skill_registry.list_skills()
        for sk in skills:
            sk_name_lower = sk["name"].lower()
            style_lower = style_name.lower()
            if style_lower in sk_name_lower or sk_name_lower in style_lower:
                content = skill_registry.load_skill_content(sk["name"])
                if content:
                    return f"\n\n[文风指导 - {sk['name']}]\n{content[:800]}"
    except Exception:
        pass
    return ""


def _get_write_system(world_plugin: str = "crossover", state_snapshot: dict | None = None) -> str:
    """从 PromptRegistry 构建 P3 系统提示词（含世界插件片段 + Skill Layer 5）。"""
    base = """\
你是跑团式小说的叙事者。根据场景目标和玩家行动，用第三人称描写本轮发生的事情。
叙事驱动，不写主观形容词。对话用引号，动作用简洁动词。
每轮 150-400 字。文末用 {{SET: key=value}} 或 {{ADD: key=+N}} 标记状态变化。"""
    try:
        from ..prompts import registry
        from ..extensions import plugin_registry
        plugin = plugin_registry.get(world_plugin)
        if plugin:
            plugin.apply_to_registry(registry)
        base = registry.build_system_prompt("p3") or base
    except Exception:
        pass

    # 注入 trigger=always/auto 的 p3 相位 Skill（Layer 5）
    try:
        from ..tools.skill_loader import skill_registry
        skill_block = skill_registry.build_injection_block(
            phase="p3", state=state_snapshot or {}, world_plugin=world_plugin
        )
        if skill_block:
            base = base + "\n\n" + skill_block
    except Exception:
        pass

    return base

_P3_MIN_CHARS = 100          # 叙事最短字符数，低于此视为不足
_P3_MAX_RETRY = 2            # 最多重试次数（合计最多 3 次生成）


async def _p3_write(ctx: TurnContext, plan: dict, part_id: str) -> str:
    """
    P3 叙事生成（流式）。
    当生成字数低于 _P3_MIN_CHARS 时，最多重试 _P3_MAX_RETRY 次，
    每次追加续写提示（参照设计文档 03 §6.3 长度阈值重试）。
    """
    cfg = load_agent_config("narrator_write")
    roll_info = ""
    if ctx.roll_result:
        r = ctx.roll_result
        roll_info = f"\n判定：{r.get('pool_formula','?')} → {r.get('result','?')}（净{r.get('net',0)}）\n叙事建议：{r.get('narrative_hint','')}"

    context_block = f"\n【近期场景】\n{ctx.memory_context}" if ctx.memory_context else ""

    state_snap = {"world_plugin": ctx.world_plugin, "mode": ctx.mode,
                  "scene_goal": ctx.scene_goal}
    write_system = _get_write_system(ctx.world_plugin, state_snap)

    # 构建 NPC 反应摘要（供 P3 参考）
    npc_block = ""
    if ctx.npc_reactions:
        lines = []
        for r in ctx.npc_reactions[:4]:  # 最多 4 个
            name = r.get("npc_name", "?")
            intent = r.get("intention", "")
            dlg = r.get("dialogue")
            emotion = r.get("emotion", "平静")
            line = f"  · {name}[{emotion}]: {intent}"
            if dlg:
                line += f' / 台词: 「{dlg}」'
            lines.append(line)
        npc_block = "\n[NPC反应（本轮参考，可选融入叙事）]\n" + "\n".join(lines)

    # 构建世界事件摘要
    world_block = ""
    if ctx.world_events:
        lines = [f"  · {e.get('event_type','?')}: {e.get('description','')}"
                 for e in ctx.world_events[:3]]
        world_block = "\n[世界演变（本轮参考，可选融入叙事）]\n" + "\n".join(lines)

    # ── Layer 4: BackendDataStream（18 轴 Narrator 参考层）───────────────────
    data_stream_block = ""
    try:
        from ..engine.runtime_data_stream import RuntimeDataStreamBuilder
        data_stream_block = RuntimeDataStreamBuilder.build(ctx)
    except Exception:
        pass

    base_user_content = (
        f"场景目标：{ctx.scene_goal}\n"
        f"基调：{plan.get('tone','日常')} | 焦点：{plan.get('focus','行动结果')}\n"
        f"玩家行动：{ctx.user_input}"
        f"{roll_info}"
        f"{context_block}"
        f"{npc_block}"
        f"{world_block}"
    )
    if data_stream_block:
        base_user_content = data_stream_block + "\n\n" + base_user_content

    style_prefix = _get_writing_style_prefix(ctx)
    if style_prefix:
        base_user_content += style_prefix

    # 通知前端开始流式 Part（只在第一次生成前通知）
    await bus.publish_part_created(
        ctx.session_id, part_id, PartType.NARRATIVE, ctx.message_id, "narrator"
    )
    await _ensure_part_in_db(ctx, part_id, PartType.NARRATIVE)

    accumulated_text = ""

    for attempt in range(_P3_MAX_RETRY + 1):
        # 重试时追加续写指令
        if attempt == 0:
            user_content = base_user_content
        else:
            shortage = _P3_MIN_CHARS - len(accumulated_text)
            user_content = (
                base_user_content
                + f"\n\n[续写提示] 当前叙事仅 {len(accumulated_text)} 字，"
                f"请继续展开至少 {shortage} 字，不要重复已有内容。"
            )
            if accumulated_text:
                user_content += f"\n\n[已有叙事参考]\n{accumulated_text}"

        messages = [
            {"role": "system", "content": write_system},
            {"role": "user", "content": user_content},
        ]

        delta_text = ""

        async def on_delta(delta: str, _store: list = []) -> None:
            nonlocal delta_text
            delta_text += delta
            await bus.publish_part_delta(ctx.session_id, part_id, delta)

        try:
            delta_text = await llm_stream(
                messages=messages,
                on_delta=on_delta,
                provider=cfg.get("provider", "deepseek"),
                model=cfg.get("model", "deepseek-chat"),
                temperature=cfg.get("temperature", 0.85) + attempt * 0.05,
                max_tokens=cfg.get("max_tokens", 2048),
            )
        except Exception as e:
            error_str = str(e)
            delta_text = f"[叙事生成失败: {error_str}]"
            await bus.publish_part_delta(ctx.session_id, part_id, delta_text)
            # 发布 part.error 事件（设计文档 09 §3）
            try:
                await bus.publish(BusEvent(
                    type=EventType.PART_ERROR,
                    session_id=ctx.session_id,
                    data={"part_id": part_id, "error": error_str, "agent": "narrator"},
                ))
            except Exception:
                pass
            break

        if attempt == 0:
            accumulated_text = delta_text
        else:
            accumulated_text += "\n" + delta_text

        if len(accumulated_text) >= _P3_MIN_CHARS:
            break

    return accumulated_text


# ── P4 变量结算 ───────────────────────────────────────────────────────────────

_CMD_RE = re.compile(r"\{\{(SET|ADD|MUL|DIV|PUSH|POP):\s*([^=}]+)=([^}]+)\}\}")

def _extract_patches(text: str) -> tuple[str, list[dict]]:
    """
    从叙事文本中提取 {{SET: key=val}} / {{ADD: key=+N}} 标记。
    返回 (清理后的文本, patches列表)
    """
    patches = []
    for m in _CMD_RE.finditer(text):
        cmd, key, val = m.group(1), m.group(2).strip(), m.group(3).strip()
        try:
            num = float(val.lstrip("+"))
        except ValueError:
            num = None
        patches.append({"cmd": cmd, "key": key, "value": val, "delta": num})
    clean_text = _CMD_RE.sub("", text).strip()
    return clean_text, patches


async def _p4_settle(ctx: TurnContext, full_text: str) -> tuple[str, list[dict]]:
    """
    P4 变量结算：
    1. 先用 regex 从正文提取 {{CMD:key=val}} 标记
    2. 若未提取到任何 patch，则调用独立轻量 LLM（非流式）推断变量变化
    """
    clean_text, patches = _extract_patches(full_text)

    # LLM 兜底：当正文中没有任何显式标记时，调用独立小模型推断状态变化
    if not patches and ctx.user_input:
        try:
            patches = await _p4_llm_extract(ctx, clean_text)
        except Exception as e:
            logger.warning("[narrator P4] state_patch 提取失败，跳过变量结算: %s", e)
            patches = []

    if patches:
        ctx.state_patches = patches
    return clean_text, patches


async def _p4_llm_extract(ctx: TurnContext, narrative: str) -> list[dict]:
    """
    独立非流式 LLM 调用 — 从叙事结果推断应执行的 TavernCommand。
    只提取「状态真正发生了变化」的条目，不凭空捏造。
    """
    from .llm import llm_complete

    # 构造简洁的角色状态摘要
    char_summary = ""
    try:
        from ..db import get_db
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1",
                (ctx.session_id,)
            )).fetchone()
        if row:
            import json as _j
            c = _j.loads(row["data_json"])
            attrs = {k: v.get("current", v.get("base", v)) if isinstance(v, dict) else v
                     for k, v in c.get("attributes", {}).items()}
            meta = c.get("meta", {})
            char_summary = f"当前属性：{attrs}\n当前 meta：{meta}"
    except Exception:
        pass

    sys_msg = (
        "你是状态结算专家。根据叙事内容，判断角色属性/meta 是否发生了变化，"
        "输出需要执行的 TavernCommand 列表（JSON 数组）。\n"
        "格式：[{\"cmd\":\"ADD\",\"key\":\"meta.hp\",\"value\":\"-10\",\"delta\":-10}, ...]\n"
        "规则：\n"
        "1. 只输出确实发生变化的条目，不捏造无依据的变化\n"
        "2. 若无变化输出空数组 []\n"
        "3. cmd 只能是 SET/ADD/MUL/DIV/PUSH/POP"
    )
    user_msg = (
        f"{char_summary}\n\n"
        f"玩家行动：{ctx.user_input}\n"
        f"叙事结果：{narrative[:600]}\n\n"
        "请输出 TavernCommand JSON 数组："
    )

    try:
        resp = await llm_complete(
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            provider="deepseek",
            model="deepseek-chat",
            temperature=0.1,
            max_tokens=256,
            timeout=8.0,
        )
        import re as _re, json as _j
        m = _re.search(r"\[.*?\]", resp, _re.DOTALL)
        if m:
            patches = _j.loads(m.group(0))
            # 校验格式
            valid = []
            for p in patches:
                if isinstance(p, dict) and "cmd" in p and "key" in p:
                    if "delta" not in p:
                        try:
                            p["delta"] = float(p.get("value", "0").lstrip("+"))
                        except Exception:
                            p["delta"] = None
                    valid.append(p)
            return valid
    except Exception as e:
        logger.debug(f"[narrator P4 LLM] parse failed: {e}")
    return []


# ── 主入口 ────────────────────────────────────────────────────────────────────

async def narrator_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — NarratorAgent 四阶段（使用 agent_span 与其他节点保持一致）。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "narrator"):
        return await _narrator_impl(ctx)
    return ctx


async def _narrator_impl(ctx: TurnContext) -> TurnContext:
    """Narrator 四阶段主逻辑（从 narrator_agent_node 拆出，供 agent_span 包裹）。"""

    part_id = str(uuid.uuid4())
    ctx.narrative_part_id = part_id

    # P5: 若 DM 改写了行动（modify verdict），使用改写后的行动文本
    if ctx.modified_action:
        ctx.user_input = ctx.modified_action

    # P0: 上下文超限时压缩
    from .compaction import maybe_compact
    ctx = await maybe_compact(ctx)

    # P0.5: 把骰子结果注入 runtime Prompt 层（Layer 5 动态片段）
    if ctx.roll_result:
        try:
            from ..prompts.registry import registry as _prompt_reg
            r = ctx.roll_result
            runtime_content = (
                f"[本轮判定结果]\n"
                f"属性/技能：{r.get('attribute','')} {r.get('skill','')}\n"
                f"公式：{r.get('pool_formula','?')} 净成功：{r.get('net',0)}\n"
                f"结果：{r.get('verdict','?')} — {r.get('narrative_hint','')}\n"
                f"[叙事时必须体现上述判定结果，不可改变成败]"
            )
            _prompt_reg.register_runtime(
                session_id=ctx.session_id,
                frag_id=f"dice_result_{part_id}",
                content=runtime_content,
                phase=["p3"],
                priority=410,
            )
        except Exception:
            pass

    # P1: Plan
    ctx.scene_goal, plan = await _p1_plan(ctx)

    # P1 reasoning Part（plan/review 模式可见：供 DM 审阅叙事规划）
    if ctx.mode in ("plan", "review"):
        try:
            reasoning_id = str(uuid.uuid4())
            _now = datetime.now().timestamp()
            reasoning_content = {
                "scene_goal": ctx.scene_goal,
                "tone":       plan.get("tone", ""),
                "focus":      plan.get("focus", ""),
                "pov":        plan.get("pov", ""),
                "modified_action_applied": bool(ctx.modified_action),
            }
            await bus.publish_part_created(
                ctx.session_id, reasoning_id, PartType.REASONING,
                ctx.message_id or "", "narrator",
            )
            await bus.publish_part_done(ctx.session_id, reasoning_id, reasoning_content)
        except Exception:
            pass

    # P2: Context retrieval
    ctx.memory_context = await _p2_context(ctx)

    # P3: Write (streaming)
    raw_text = await _p3_write(ctx, plan, part_id)

    # P4: Settle
    clean_text, patches = await _p4_settle(ctx, raw_text)
    ctx.narrative_text = clean_text

    # 最终化 Part
    now = datetime.now().timestamp()
    await _finalize_part(ctx, part_id, {"text": clean_text}, now)
    await bus.publish_part_done(ctx.session_id, part_id, {"text": clean_text})

    # state_patch Part 由 var_agent 统一发布，narrator 侧不重复发布
    # patches 保存在 ctx.state_patches，供 var_agent 结算时使用
    if patches:
        ctx.state_patches = patches  # var_agent 会读取并执行

    return ctx


# ── DB 辅助 ──────────────────────────────────────────────────────────────────

async def _ensure_part_in_db(ctx: TurnContext, part_id: str, part_type: str) -> None:
    """写入 streaming 占位 Part；若无真实 message_id（测试场景）则静默跳过。"""
    if not ctx.session_id or not ctx.message_id:
        return
    from ..db import get_db
    import sqlite3
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO message_parts "
                "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '{}', 'streaming', 'narrator', ?, ?)",
                (part_id, ctx.message_id, ctx.session_id, part_type, now, now)
            )
            await db.commit()
    except sqlite3.IntegrityError:
        pass  # message_id 不存在（测试场景），跳过 DB 写入


async def _finalize_part(ctx: TurnContext, part_id: str, content: dict, now: float) -> None:
    if not ctx.session_id or not ctx.message_id:
        return
    from ..db import get_db
    import sqlite3
    try:
        async with get_db() as db:
            await db.execute(
                "UPDATE message_parts SET content=?, status='done', updated_at=? WHERE id=?",
                (json.dumps(content, ensure_ascii=False), now, part_id)
            )
            await db.commit()
    except sqlite3.IntegrityError:
        pass


async def _write_done_part(ctx: TurnContext, part_id: str, part_type: str, content: dict, now: float) -> None:
    if not ctx.session_id or not ctx.message_id:
        return
    from ..db import get_db
    import sqlite3
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO message_parts (id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'done', 'narrator', ?, ?)",
                (part_id, ctx.message_id, ctx.session_id,
                 part_type, json.dumps(content, ensure_ascii=False), now, now)
            )
            await db.commit()
    except sqlite3.IntegrityError:
        pass
