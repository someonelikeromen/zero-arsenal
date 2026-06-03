"""
会话管理路由：Session CRUD、角色卡、章节、记忆、NPC、骰子历史、Ask 权限、统计、重放。
对应设计文档 11-api-design.md §2 §4 §5
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...bus import bus, BusEvent, EventType
from ...db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    world_plugin: str = "crossover"
    agent_profile: str = "play"
    title: Optional[str] = None
    character_data: Optional[dict] = None
    # 新增：从全局模板创建（world_id / character_template_id 二选一或组合使用）
    world_id: Optional[str] = None              # 全局世界模板 ID → 复制 world_archive_entries
    character_template_id: Optional[str] = None  # 全局人物模板 ID → 使用其 data_json


class ModeChangeRequest(BaseModel):
    mode: str  # play | plan | review


class PatchSessionRequest(BaseModel):
    title: Optional[str] = None


class ForkRequest(BaseModel):
    branch_label: str
    fork_from_message_id: Optional[str] = None


class RevertRequest(BaseModel):
    message_id: str


class PatchCharacterRequest(BaseModel):
    patches: list[dict] = []
    raw_json: Optional[dict] = None


class CreateArchiveRequest(BaseModel):
    title: str
    content: dict
    archive_type: str = "lore"
    trigger_keywords: str = ""


class AskDecisionRequest(BaseModel):
    decision: str  # allow | deny


class AddMemoryRequest(BaseModel):
    content: str
    node_type: str = "event"
    chapter_id: str = ""
    metadata: dict = {}


class MemoryRollbackRequest(BaseModel):
    chapter_id: str = ""
    since_iso: str = ""


class ConsolidateRequest(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None


class ChapterRollbackRequest(BaseModel):
    confirm: bool = False
    create_branch: bool = False


# ── 会话 CRUD ─────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(req: CreateSessionRequest):
    session_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (id, world_plugin, agent_profile, mode, title, created_at, updated_at) "
            "VALUES (?, ?, ?, 'play', ?, ?, ?)",
            (session_id, req.world_plugin, req.agent_profile,
             req.title or f"Session {session_id[:8]}", now, now)
        )
        char_id = str(uuid.uuid4())
        from ...db.character_v4 import create_default_character, validate_character, migrate_v3_to_v4

        # 优先级：character_template_id > character_data > default
        if req.character_template_id:
            tmpl_row = await (await db.execute(
                "SELECT data_json, world_plugin FROM character_templates WHERE id=?",
                (req.character_template_id,)
            )).fetchone()
            if tmpl_row:
                try:
                    char_data = json.loads(dict(tmpl_row)["data_json"] or "{}")
                    if not char_data:
                        char_data = create_default_character("旅行者", req.world_plugin)
                except Exception:
                    char_data = create_default_character("旅行者", req.world_plugin)
            else:
                char_data = create_default_character("旅行者", req.world_plugin)
        elif req.character_data:
            char_data = req.character_data
            try:
                if "schema_version" not in char_data or str(char_data.get("schema_version", "0")) < "4":
                    char_data = migrate_v3_to_v4(char_data)
                valid, errs = validate_character(char_data)
                if not valid:
                    char_data = create_default_character("旅行者", req.world_plugin)
            except Exception:
                char_data = create_default_character("旅行者", req.world_plugin)
        else:
            char_data = create_default_character("旅行者", req.world_plugin)
            char_data["meta"]["session_id"] = session_id

        await db.execute(
            "INSERT INTO character_cards (id, session_id, data_json, schema_version, updated_at) "
            "VALUES (?, ?, ?, 4, ?)",
            (char_id, session_id, json.dumps(char_data, ensure_ascii=False), now)
        )

        # 若指定了全局世界，复制其档案条目到 world_archives
        if req.world_id:
            archive_rows = await (await db.execute(
                "SELECT * FROM world_archive_entries WHERE world_id=?", (req.world_id,)
            )).fetchall()
            for ar in archive_rows:
                ar_dict = dict(ar)
                new_ar_id = str(uuid.uuid4())
                # 用每条目原始ID作为 world_key，避免 UNIQUE(session_id, world_key) 冲突
                entry_world_key = f"tpl_{ar_dict['id']}"
                await db.execute(
                    "INSERT OR IGNORE INTO world_archives (id, session_id, title, content, archive_type, trigger_keywords, world_key, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_ar_id, session_id, ar_dict["title"],
                     ar_dict["content"], ar_dict["archive_type"],
                     ar_dict.get("trigger_keywords", ""), entry_world_key, now, now)
                )

        chapter_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO chapters (id, session_id, is_consolidated, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
            (chapter_id, session_id, now, now)
        )
        await db.commit()

    try:
        from ...extensions.plugin import plugin_registry as _plugin_reg
        _plugin = _plugin_reg.get(req.world_plugin)
        if _plugin:
            init_state: dict = {
                "session_id": session_id, "world_plugin": req.world_plugin,
                "mode": "play", "character_data": req.character_data or {},
            }
            _patched = _plugin.on_session_init(init_state)
            if _patched.get("character_data") and _patched["character_data"] != (req.character_data or {}):
                async with get_db() as db2:
                    await db2.execute(
                        "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
                        (json.dumps(_patched["character_data"], ensure_ascii=False), now, session_id)
                    )
                    await db2.commit()
    except Exception:
        pass

    await bus.publish(BusEvent(type=EventType.SESSION_STARTED, session_id=session_id,
                               data={"world_plugin": req.world_plugin, "agent_profile": req.agent_profile}))
    # 重新读取最终 character 数据（插件可能已修改）
    async with get_db() as _char_db:
        _char_row = await (await _char_db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,)
        )).fetchone()
    character_out = json.loads(_char_row["data_json"]) if _char_row else char_data

    return {
        "session_id": session_id,
        "title": req.title or f"Session {session_id[:8]}",
        "world_plugin": req.world_plugin,
        "agent_profile": req.agent_profile,
        "current_mode": "play",
        "created_at": datetime.fromtimestamp(now).isoformat(),
        "status": "active",
        "character": character_out,
        "chapter_id": chapter_id,
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    async with get_db() as db:
        row = await db.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
        session = await row.fetchone()
        if not session:
            raise HTTPException(404, "Session not found")
        data = dict(session)

        cnt_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id=? AND status != 'deleted'",
            (session_id,),
        )
        cnt = await cnt_row.fetchone()
        data["message_count"] = cnt["cnt"] if cnt else 0

        ch_row = await db.execute(
            "SELECT id, title, is_consolidated, created_at FROM chapters "
            "WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        ch = await ch_row.fetchone()
        if ch:
            ch_dict = dict(ch)
            ch_dict["chapter_id"] = ch_dict.pop("id")
            data["current_chapter"] = ch_dict
        else:
            data["current_chapter"] = None

        return data


@router.get("/sessions")
async def list_sessions(
    status: str = "active",
    limit: int = 20,
    cursor: Optional[str] = None,
    world_plugin: Optional[str] = None,
):
    """列出会话（游标分页），支持 world_plugin 过滤。"""
    import base64

    cursor_ts: Optional[float] = None
    if cursor:
        try:
            cursor_ts = float(base64.b64decode(cursor).decode())
        except Exception:
            cursor_ts = None

    async with get_db() as db:
        params: list = []
        where_clauses = []

        if status != "all":
            where_clauses.append("status=?")
            params.append(status)
        if world_plugin:
            where_clauses.append("world_plugin=?")
            params.append(world_plugin)
        if cursor_ts is not None:
            where_clauses.append("created_at < ?")
            params.append(cursor_ts)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # total count（不含游标约束）
        count_params = [p for p in params if p not in ([cursor_ts] if cursor_ts else [])]
        count_where_clauses = [c for c in where_clauses if "created_at" not in c]
        count_where_sql = ("WHERE " + " AND ".join(count_where_clauses)) if count_where_clauses else ""
        count_row = await db.execute(
            f"SELECT COUNT(*) as cnt FROM sessions {count_where_sql}", count_params
        )
        total = (await count_row.fetchone())["cnt"]

        params.append(limit + 1)
        rows = await db.execute(
            f"SELECT id, title, world_plugin, mode, status, created_at, updated_at "
            f"FROM sessions {where_sql} ORDER BY created_at DESC LIMIT ?",
            params
        )
        items = [dict(r) for r in await rows.fetchall()]

    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    next_cursor: Optional[str] = None
    if has_more and items:
        last_ts = items[-1]["created_at"]
        import base64 as _b64
        next_cursor = _b64.b64encode(str(last_ts).encode()).decode()

    return {"items": items, "next_cursor": next_cursor, "has_more": has_more, "total": total}


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, req: PatchSessionRequest):
    """更新会话元数据（当前支持 title 重命名）。"""
    now = datetime.now().timestamp()
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        if req.title is not None:
            await db.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                (req.title.strip(), now, session_id)
            )
        await db.commit()
    await bus.publish(BusEvent(
        type=EventType.SESSION_STARTED,
        session_id=session_id,
        data={"event": "session.updated", "title": req.title},
    ))
    return {"ok": True, "session_id": session_id, "title": req.title}


@router.patch("/sessions/{session_id}/mode")
async def change_mode(session_id: str, req: ModeChangeRequest):
    """切换会话模式，发布 session.mode_changed SSE 事件，返回 previous_mode 和 active_tools。"""
    if req.mode not in ("play", "plan", "review"):
        raise HTTPException(400, f"Invalid mode: {req.mode}")
    now = datetime.now().timestamp()
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT mode FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        previous_mode = row["mode"]
        await db.execute("UPDATE sessions SET mode=?, updated_at=? WHERE id=?",
                         (req.mode, now, session_id))
        await db.commit()

    # 获取新模式下的 active_tools，并重新应用 WorldPlugin overlay（设计 §10.7.2）
    active_tools: list[str] = []
    try:
        from ...agents.permission import profile_registry, PermissionAction, apply_plugin_overlay
        from ...extensions import plugin_registry as ext_registry

        # 查询会话所属的 world_plugin
        async with get_db() as db:
            s_row = await (await db.execute(
                "SELECT world_plugin FROM sessions WHERE id=?", (session_id,)
            )).fetchone()
        world_plugin_key: str = (s_row["world_plugin"] if s_row else None) or ""

        # 基础 Profile
        base_profile = profile_registry.get(req.mode)

        # 如果有 WorldPlugin 且其 permission_overlay 非空，构建叠加副本
        effective_profile = base_profile
        if world_plugin_key:
            try:
                plugin = ext_registry.get(world_plugin_key)
                overlay_for_mode = (plugin.permission_overlay or {}).get(req.mode, {})
                if overlay_for_mode:
                    # 将 str → PermissionAction 转换后应用叠加层
                    typed_overlay = {
                        pat: PermissionAction(val) if isinstance(val, str) else val
                        for pat, val in overlay_for_mode.items()
                    }
                    effective_profile = apply_plugin_overlay(base_profile, typed_overlay)
            except Exception:
                pass  # WorldPlugin 不存在或 overlay 为空时使用基础 Profile

        # 缓存会话级有效 Profile（供 tool_loop / ask_handler 使用）
        profile_registry.set_session_profile(session_id, effective_profile)

        if effective_profile.active_tools is not None:
            active_tools = list(effective_profile.active_tools)
        else:
            from ...tools.registry import tool_registry
            active_tools = [
                t for t in tool_registry._tools
                if effective_profile.check_tool(t) != PermissionAction.DENY
            ]
    except Exception:
        pass

    await bus.publish(BusEvent(
        type=EventType.SESSION_MODE_CHANGED,
        session_id=session_id,
        data={"mode": req.mode, "previous_mode": previous_mode, "active_tools": active_tools},
    ))
    return {
        "ok": True,
        "session_id": session_id,
        "mode": req.mode,
        "previous_mode": previous_mode,
        "active_tools": active_tools,
    }


@router.post("/sessions/{session_id}/mode")
async def change_mode_post(session_id: str, req: ModeChangeRequest):
    """POST 别名 — 与 PATCH /mode 功能完全相同。

    设计文档（03-agent-system.md）使用 POST 动词；实现以 PATCH 为主，
    此别名保持与设计文档的 HTTP 动词一致性。
    """
    return await change_mode(session_id, req)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """软删除会话（标记 status=deleted）。"""
    now = datetime.now().timestamp()
    async with get_db() as db:
        result = await db.execute(
            "UPDATE sessions SET status='deleted', updated_at=? WHERE id=? AND status!='deleted'",
            (now, session_id)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Session not found")
        await db.commit()


@router.post("/sessions/{session_id}/fork")
async def fork_session(session_id: str, req: ForkRequest):
    """Fork 当前会话为分支。"""
    branch_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    async with get_db() as db:
        original = await (await db.execute("SELECT * FROM sessions WHERE id=?", (session_id,))).fetchone()
        if not original:
            raise HTTPException(404, "Session not found")

        cutoff_ts: Optional[float] = None
        fork_msg_id = req.fork_from_message_id
        if fork_msg_id:
            fork_msg = await (await db.execute(
                "SELECT created_at FROM messages WHERE id=? AND session_id=?",
                (fork_msg_id, session_id)
            )).fetchone()
            if not fork_msg:
                raise HTTPException(404, f"fork_from_message_id '{fork_msg_id}' 不存在于当前会话")
            cutoff_ts = fork_msg["created_at"]

        await db.execute(
            "INSERT INTO sessions (id, world_plugin, agent_profile, mode, branch_of, branch_label, "
            "fork_from_msg, title, state_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_id, original["world_plugin"], original["agent_profile"],
             original["mode"], session_id, req.branch_label, fork_msg_id,
             f"[分支] {req.branch_label}", original["state_json"], now, now)
        )

        if cutoff_ts is not None:
            msg_rows = await (await db.execute(
                "SELECT * FROM messages WHERE session_id=? AND status!='deleted' AND created_at<=? ORDER BY created_at",
                (session_id, cutoff_ts)
            )).fetchall()
        else:
            msg_rows = await (await db.execute(
                "SELECT * FROM messages WHERE session_id=? AND status!='deleted' ORDER BY created_at",
                (session_id,)
            )).fetchall()

        old_to_new_msg: dict[str, str] = {}
        for msg in msg_rows:
            new_msg_id = str(uuid.uuid4())
            old_to_new_msg[msg["id"]] = new_msg_id
            await db.execute(
                "INSERT INTO messages (id, session_id, role, turn_index, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_msg_id, branch_id, msg["role"],
                 msg["turn_index"], msg["status"], msg["created_at"], now)
            )

        for old_msg_id, new_msg_id in old_to_new_msg.items():
            part_rows = await (await db.execute(
                "SELECT * FROM message_parts WHERE message_id=?", (old_msg_id,)
            )).fetchall()
            for p in part_rows:
                ptype = p.get("type", "narrative")
                pcontent = p.get("content", "{}")
                await db.execute(
                    "INSERT OR IGNORE INTO message_parts "
                    "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), new_msg_id, branch_id,
                     ptype, pcontent, p["status"], p.get("agent", ""),
                     p["created_at"], now)
                )

        char_data_json: Optional[str] = None
        if cutoff_ts is not None:
            snap_row = await (await db.execute(
                "SELECT snapshot_json FROM character_snapshots "
                "WHERE session_id=? AND created_at<=? ORDER BY created_at DESC LIMIT 1",
                (session_id, cutoff_ts)
            )).fetchone()
            if snap_row:
                char_data_json = snap_row["snapshot_json"]

        if not char_data_json:
            c_row = await (await db.execute(
                "SELECT data_json FROM character_cards "
                "WHERE session_id=? ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if c_row:
                char_data_json = c_row["data_json"]

        if char_data_json:
            await db.execute(
                "INSERT OR IGNORE INTO character_cards "
                "(id, session_id, data_json, schema_version, updated_at) "
                "VALUES (?, ?, ?, '4.0', ?)",
                (str(uuid.uuid4()), branch_id, char_data_json, now)
            )
            await db.execute(
                "INSERT INTO character_snapshots "
                "(id, session_id, snapshot_json, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), branch_id, char_data_json, now)
            )

        npc_rows = await (await db.execute(
            "SELECT * FROM npc_profiles WHERE session_id=?", (session_id,)
        )).fetchall()
        for npc in npc_rows:
            await db.execute(
                "INSERT OR IGNORE INTO npc_profiles "
                "(id, session_id, key, name, profile_json, world_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), branch_id,
                 npc["key"], npc.get("name", npc["key"]), npc["profile_json"],
                 npc.get("world_key", ""), npc["created_at"], now)
            )

        await db.commit()

    return {
        "new_session_id": branch_id,
        "parent_session_id": session_id,
        "branch_label": req.branch_label,
        "forked_from_message_id": fork_msg_id,
        "created_at": datetime.fromtimestamp(now).isoformat(),
        "messages_copied": len(old_to_new_msg),
    }


# ── 消息 / Parts ──────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    limit: int = 50,
    cursor: Optional[str] = None,
    include_parts: bool = False,
):
    """
    列出会话消息历史（cursor 分页，11-api-design.md §messages）。
    - cursor：base64(turn_index) 游标，翻页用
    - include_parts：True 时内联每条消息的 Part 数据
    """
    import base64

    cursor_turn: Optional[int] = None
    if cursor:
        try:
            cursor_turn = int(base64.b64decode(cursor).decode())
        except Exception:
            cursor_turn = None

    async with get_db() as db:
        params: list = [session_id]
        where_extra = ""
        if cursor_turn is not None:
            where_extra = "AND m.turn_index > ?"
            params.append(cursor_turn)

        params.append(limit + 1)
        rows = await (await db.execute(
            f"SELECT m.id, m.session_id, m.role, m.turn_index, m.status, m.phase, "
            f"m.content, m.message_type, m.created_at "
            f"FROM messages m "
            f"WHERE m.session_id=? AND m.status='active' {where_extra} "
            f"ORDER BY m.turn_index ASC LIMIT ?",
            params
        )).fetchall()

        items = [dict(r) for r in rows]
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        if include_parts and items:
            msg_ids = [m["id"] for m in items]
            placeholders = ",".join("?" * len(msg_ids))
            part_rows = await (await db.execute(
                f"SELECT id, message_id, type, content, created_at, metadata "
                f"FROM message_parts WHERE message_id IN ({placeholders}) "
                f"ORDER BY created_at ASC",
                msg_ids
            )).fetchall()
            # 按 message_id 分组
            parts_by_msg: dict[str, list] = {}
            for pr in part_rows:
                pd = dict(pr)
                try:
                    pd["content"] = json.loads(pd["content"])
                except Exception:
                    pass
                parts_by_msg.setdefault(pd["message_id"], []).append(pd)
            for m in items:
                m["parts"] = parts_by_msg.get(m["id"], [])
        else:
            for m in items:
                m["parts"] = []

        # 格式化：对齐 11-api-design.md 响应形状
        for m in items:
            m["message_id"] = m.pop("id")

    next_cursor: Optional[str] = None
    if has_more and items:
        last_turn = items[-1]["turn_index"]
        next_cursor = base64.b64encode(str(last_turn).encode()).decode()

    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.get("/sessions/{session_id}/parts")
async def get_parts(
    session_id: str,
    message_id: Optional[str] = None,
    part_type: Optional[str] = None,
    limit: int = 100,
    cursor: Optional[str] = None,
):
    """
    获取会话的所有 Parts（cursor 分页，11-api-design.md §parts）。
    游标基于 created_at 时间戳（base64 编码）。
    """
    import base64

    cursor_ts: Optional[float] = None
    if cursor:
        try:
            cursor_ts = float(base64.b64decode(cursor).decode())
        except Exception:
            cursor_ts = None

    async with get_db() as db:
        where = ["session_id=?"]
        params: list = [session_id]
        if message_id:
            where.append("message_id=?")
            params.append(message_id)
        if part_type:
            where.append("type=?")
            params.append(part_type)
        if cursor_ts is not None:
            where.append("created_at > ?")
            params.append(cursor_ts)

        params.append(limit + 1)
        rows = await (await db.execute(
            f"SELECT id, message_id, type, content, created_at, metadata "
            f"FROM message_parts WHERE {' AND '.join(where)} "
            f"ORDER BY created_at ASC LIMIT ?",
            params
        )).fetchall()

        items = [dict(r) for r in rows]
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        for d in items:
            try:
                d["content"] = json.loads(d["content"])
            except Exception:
                pass
            d["part_id"] = d.pop("id")

    next_cursor: Optional[str] = None
    if has_more and items:
        last_ts = items[-1]["created_at"]
        next_cursor = base64.b64encode(str(last_ts).encode()).decode()

    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


@router.post("/sessions/{session_id}/revert")
async def revert_to_message(session_id: str, req: RevertRequest):
    """完整回退到指定消息之前的状态。"""
    async with get_db() as db:
        target_row = await (await db.execute(
            "SELECT turn_index, created_at FROM messages WHERE id=? AND session_id=?",
            (req.message_id, session_id)
        )).fetchone()
        if not target_row:
            raise HTTPException(404, "Message not found")
        turn_idx = target_row["turn_index"]
        target_ts = target_row["created_at"]

        now = datetime.now().timestamp()

        await db.execute(
            "UPDATE messages SET status='reverted', updated_at=? "
            "WHERE session_id=? AND turn_index>? AND status!='reverted'",
            (now, session_id, turn_idx)
        )

        snap_row = await (await db.execute(
            "SELECT snapshot_json FROM character_snapshots "
            "WHERE session_id=? AND (message_id=? OR created_at<=?) "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id, req.message_id, target_ts)
        )).fetchone()
        char_restored = False
        if snap_row:
            try:
                await db.execute(
                    "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
                    (snap_row["snapshot_json"], now, session_id)
                )
                char_restored = True
            except Exception as e:
                logger.warning(f"[revert] character restore failed: {e}")

        try:
            await db.execute(
                "DELETE FROM memory_entries "
                "WHERE session_id=? AND tier='episodic' AND created_at>?",
                (session_id, target_ts)
            )
        except Exception as e:
            logger.debug(f"[revert] memory cleanup: {e}")

        await db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        await db.commit()

    await bus.publish(BusEvent(
        type=EventType.SESSION_STARTED,
        session_id=session_id,
        data={
            "type": "reverted", "to_message_id": req.message_id,
            "turn_index": turn_idx, "character_restored": char_restored,
        }
    ))
    return {"reverted_to": req.message_id, "turn_index": turn_idx, "character_restored": char_restored}


# ── 角色卡 ────────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/character")
async def get_character(session_id: str):
    async with get_db() as db:
        row = await db.execute("SELECT * FROM character_cards WHERE session_id=?", (session_id,))
        char = await row.fetchone()
        if not char:
            raise HTTPException(404, "Character not found")
        return {"character": json.loads(char["data_json"]), "schema_version": char["schema_version"]}


@router.patch("/sessions/{session_id}/character")
async def patch_character(session_id: str, req: PatchCharacterRequest):
    """更新角色卡：patches 走 TavernCommand DSL，raw_json 直接覆写。"""
    async with get_db() as db:
        row = await db.execute(
            "SELECT id, data_json FROM character_cards WHERE session_id=?", (session_id,)
        )
        char = await row.fetchone()
        if not char:
            raise HTTPException(404, "Character not found")

        current = json.loads(char["data_json"])

        if req.raw_json is not None:
            updated = req.raw_json
        elif req.patches:
            from ...engine.vm import TavernCommandProcessor
            proc = TavernCommandProcessor()
            updated = proc.apply_patches(req.patches, current)
        else:
            raise HTTPException(400, "Provide patches or raw_json")

        validation_warnings: list = []
        try:
            from ...db.character_v4 import validate_character
            validate_character(updated)
        except Exception as ve:
            validation_warnings = [str(ve)]

        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
            (json.dumps(updated, ensure_ascii=False), now, session_id)
        )
        await db.commit()

    await bus.publish(BusEvent(
        type=EventType.PART_DONE,
        session_id=session_id,
        data={"type": "character_updated", "character": updated}
    ))
    return {"character": updated, "validation_warnings": validation_warnings}


# ── Ask 权限交互 ──────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/asks")
async def list_pending_asks(session_id: str):
    from ...agents.ask_handler import ask_manager
    return {"asks": ask_manager.list_pending(session_id)}


@router.post("/sessions/{session_id}/asks/{ask_id}")
async def resolve_ask(session_id: str, ask_id: str, req: AskDecisionRequest):
    from ...agents.ask_handler import ask_manager
    if req.decision not in ("allow", "deny"):
        raise HTTPException(400, "decision must be 'allow' or 'deny'")
    ok = ask_manager.resolve(ask_id, req.decision)
    if not ok:
        raise HTTPException(404, "ask not found or already resolved")
    return {"ask_id": ask_id, "decision": req.decision}


# ── 章节管理 ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/chapters")
async def get_chapters(session_id: str):
    """返回章节嵌套树（children 递归）。若章节无 parent_id 则挂载于根层。"""
    async with get_db() as db:
        rows = await db.execute(
            "SELECT id, session_id, parent_chapter_id AS parent_id, title, branch_label, is_consolidated, "
            "start_message_id, end_message_id, created_at, updated_at "
            "FROM chapters WHERE session_id=? ORDER BY created_at",
            (session_id,)
        )
        raw = [dict(r) for r in await rows.fetchall()]

    # 构建 id→node 字典，并改 id → chapter_id
    node_map: dict = {}
    for r in raw:
        node = {
            "chapter_id": r["id"],
            "parent_id": r.get("parent_id"),
            "title": r.get("title"),
            "branch_label": r.get("branch_label"),
            "is_consolidated": bool(r.get("is_consolidated")),
            "message_range": {
                "from": r.get("start_message_id"),
                "to": r.get("end_message_id"),
            },
            "created_at": r.get("created_at"),
            "children": [],
        }
        node_map[r["id"]] = node

    roots = []
    for node in node_map.values():
        parent_id = node.get("parent_id")
        if parent_id and parent_id in node_map:
            node_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return {"session_id": session_id, "chapters": roots}


@router.get("/sessions/{session_id}/chapters/{chapter_id}/summary")
async def get_chapter_summary(session_id: str, chapter_id: str):
    async with get_db() as db:
        row = await db.execute(
            "SELECT id, session_id, summary, is_consolidated, turn_count, "
            "start_message_id, end_message_id, created_at, updated_at "
            "FROM chapters WHERE id=? AND session_id=?",
            (chapter_id, session_id),
        )
        chapter = await row.fetchone()
        if not chapter:
            raise HTTPException(404, "Chapter not found")
        result = dict(chapter)
        result["has_summary"] = bool(result.get("summary"))
        return result


@router.post("/sessions/{session_id}/chapters/consolidate")
async def manual_consolidate(session_id: str, req: ConsolidateRequest = ConsolidateRequest()):
    """手动触发当前章节的固化。可传入 title/summary 覆盖 LLM 自动生成值。"""
    from ...agents.chronicler_agent import chronicler_agent_node
    from ...agents.state import TurnContext

    ctx = TurnContext(session_id=session_id, user_input="[manual consolidate]",
                      world_plugin="crossover", mode="plan")
    if req.title:
        ctx.extra_context = {"override_title": req.title}
    if req.summary:
        if not hasattr(ctx, "extra_context") or not ctx.extra_context:
            ctx.extra_context = {}
        ctx.extra_context["override_summary"] = req.summary

    try:
        await chronicler_agent_node(ctx)
    except Exception as e:
        raise HTTPException(500, f"Consolidation failed: {e}")

    # 取固化后的章节信息返回
    async with get_db() as db:
        ch_row = await db.execute(
            "SELECT id, title, is_consolidated, summary, updated_at "
            "FROM chapters WHERE session_id=? AND is_consolidated=1 ORDER BY updated_at DESC LIMIT 1",
            (session_id,)
        )
        ch = await ch_row.fetchone()

    if ch:
        return {
            "chapter_id": ch["id"],
            "title": req.title or ch["title"],
            "is_consolidated": True,
            "summary": req.summary or ch["summary"],
            "consolidated_at": datetime.fromtimestamp(ch["updated_at"]).isoformat() if ch["updated_at"] else None,
        }
    return {"status": "consolidated"}


@router.post("/sessions/{session_id}/chapters/{chapter_id}/rollback")
async def rollback_to_chapter(session_id: str, chapter_id: str,
                               req: ChapterRollbackRequest = ChapterRollbackRequest()):
    """将会话状态回滚到指定章节末尾。confirm=true 时才执行删除。"""
    if not req.confirm:
        raise HTTPException(400, "confirm must be true to execute rollback")
    snap = None
    deleted_chapters: list[str] = []
    async with get_db() as db:
        row = await db.execute(
            "SELECT end_message_id, created_at FROM chapters WHERE id=? AND session_id=?",
            (chapter_id, session_id)
        )
        chapter = await row.fetchone()
        if not chapter:
            raise HTTPException(404, "Chapter not found")

        chapter_created_at = chapter["created_at"]
        now = datetime.now().timestamp()

        await db.execute(
            "UPDATE messages SET status='reverted', updated_at=? "
            "WHERE session_id=? AND created_at>? AND status!='reverted'",
            (now, session_id, chapter_created_at)
        )
        ch_rows = await db.execute(
            "SELECT id FROM chapters WHERE session_id=? AND created_at>? AND status!='reverted'",
            (session_id, chapter_created_at)
        )
        deleted_chapters = [r["id"] for r in await ch_rows.fetchall()]
        await db.execute(
            "UPDATE chapters SET status='reverted', updated_at=? "
            "WHERE session_id=? AND created_at>? AND status!='reverted'",
            (now, session_id, chapter_created_at)
        )
        await db.commit()

    try:
        async with get_db() as db:
            snap = await (await db.execute(
                "SELECT snapshot_json FROM character_snapshots "
                "WHERE session_id=? AND chapter_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id, chapter_id)
            )).fetchone()
            if not snap:
                snap = await (await db.execute(
                    "SELECT snapshot_json FROM character_snapshots "
                    "WHERE session_id=? AND created_at<=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (session_id, chapter_created_at)
                )).fetchone()
            if snap:
                now2 = datetime.now().timestamp()
                await db.execute(
                    "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
                    (snap["snapshot_json"], now2, session_id)
                )
                await db.commit()
    except Exception:
        pass

    rollback_result: dict = {}
    try:
        from ...memory.rollback import memory_rollback
        rollback_result = await memory_rollback.rollback_chapter(
            novel_id=session_id,
            chapter_id=chapter_id,
            chapter_created_at=str(chapter_created_at),
        ) or {}
    except Exception as _rb_err:
        import logging as _log_mod
        _log_mod.getLogger(__name__).error(
            "[rollback_to_chapter] memory_rollback failed for session=%s chapter=%s: %s",
            session_id, chapter_id, _rb_err
        )
        raise HTTPException(500, f"记忆回滚失败: {_rb_err}") from _rb_err

    new_branch_id: str | None = None
    if req.create_branch:
        # 创建分支：fork 出新会话，以当前章节状态为起点
        new_branch_id = str(uuid.uuid4())
        branch_now = datetime.now().timestamp()
        async with get_db() as branch_db:
            orig_row = await (await branch_db.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            )).fetchone()
            if orig_row:
                orig = dict(orig_row)
                branch_title = f"{orig.get('title', session_id)}_branch_{new_branch_id[:8]}"
                await branch_db.execute(
                    "INSERT INTO sessions (id, title, world_plugin, agent_profile, current_mode, "
                    "created_at, updated_at, status, forked_from) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_branch_id, branch_title,
                     orig.get("world_plugin", ""), orig.get("agent_profile", "play"),
                     "play", branch_now, branch_now, "active", session_id)
                )
                # 复制角色卡
                char_row = await (await branch_db.execute(
                    "SELECT data_json FROM character_cards WHERE session_id=? "
                    "ORDER BY updated_at DESC LIMIT 1", (session_id,)
                )).fetchone()
                if char_row:
                    await branch_db.execute(
                        "INSERT INTO character_cards (id, session_id, data_json, schema_version, updated_at) "
                        "VALUES (?,?,?,4,?)",
                        (str(uuid.uuid4()), new_branch_id, char_row["data_json"], branch_now)
                    )
                # 创建初始章节
                branch_chapter_id = str(uuid.uuid4())
                await branch_db.execute(
                    "INSERT INTO chapters (id, session_id, is_consolidated, created_at, updated_at) "
                    "VALUES (?,?,0,?,?)",
                    (branch_chapter_id, new_branch_id, branch_now, branch_now)
                )
                await branch_db.commit()

    return {
        "session_id": session_id,
        "rolled_back_to": chapter_id,
        "deleted_chapters": deleted_chapters,
        "new_branch_id": new_branch_id,
        "character_state_restored": snap is not None,
        "memory_rollback": rollback_result,
    }


# ── 会话文风配置 ───────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/writing-styles")
async def get_session_writing_styles(session_id: str):
    """读取会话已选文风（存于 sessions.state_json.writing_styles）。"""
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT state_json FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    try:
        state = json.loads(row["state_json"] or "{}")
    except Exception:
        state = {}
    return {"writing_styles": state.get("writing_styles", [])}


@router.put("/sessions/{session_id}/writing-styles")
async def set_session_writing_styles(session_id: str, req: dict):
    """写入会话已选文风列表（覆盖）。body: {"writing_styles": ["网文", "节奏大师", ...]}"""
    styles = req.get("writing_styles", [])
    if not isinstance(styles, list):
        raise HTTPException(400, "writing_styles must be a list")
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT state_json FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        try:
            state = json.loads(row["state_json"] or "{}")
        except Exception:
            state = {}
        state["writing_styles"] = styles
        await db.execute(
            "UPDATE sessions SET state_json=?, updated_at=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False), datetime.now().timestamp(), session_id)
        )
        await db.commit()
    return {"ok": True, "writing_styles": styles}


# ── 世界档案 / NPC ─────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/world-archives")
async def get_world_archives(session_id: str):
    async with get_db() as db:
        rows = await db.execute(
            "SELECT * FROM world_archives WHERE session_id=? ORDER BY updated_at DESC",
            (session_id,)
        )
        archives = []
        for r in await rows.fetchall():
            d = dict(r)
            try:
                d["content"] = json.loads(d["content"])
            except Exception:
                pass
            archives.append(d)
        return {"archives": archives, "count": len(archives)}


@router.post("/sessions/{session_id}/world-archives")
async def create_world_archive(session_id: str, req: CreateArchiveRequest):
    archive_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO world_archives (id, session_id, title, content, archive_type, trigger_keywords, world_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (archive_id, session_id, req.title,
             json.dumps(req.content, ensure_ascii=False), req.archive_type,
             req.trigger_keywords, req.archive_type, now, now)
        )
        await db.commit()
    return {"archive_id": archive_id, "title": req.title}


@router.get("/sessions/{session_id}/npcs")
async def list_npcs(session_id: str, world_key: Optional[str] = None):
    """
    列出 NPC 档案。
    - 默认按 session_id 查询（会话内 NPC）。
    - ?world_key=xxx 时同时返回该 world_key 的全局模板 NPC（06-data-model.md §3.2）。
    """
    async with get_db() as db:
        if world_key:
            rows = await (await db.execute(
                "SELECT id, key, name, profile_json, world_key, created_at, updated_at "
                "FROM npc_profiles "
                "WHERE session_id=? OR (world_key=? AND world_key!='') "
                "ORDER BY created_at DESC",
                (session_id, world_key)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT id, key, name, profile_json, world_key, created_at, updated_at "
                "FROM npc_profiles WHERE session_id=? ORDER BY created_at DESC",
                (session_id,)
            )).fetchall()
    return {
        "npcs": [
            {
                "id": r["id"], "key": r["key"], "name": r["name"],
                "world_key": r["world_key"],
                "profile": json.loads(r["profile_json"]),
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    }


@router.post("/sessions/{session_id}/npcs")
async def create_npc(session_id: str, req: dict):
    """
    创建 NPC 档案。支持 world_key 字段将 NPC 声明为全局模板（06-data-model.md §3.2）。
    - world_key 非空时：(world_key, key) 全局唯一，可跨会话引用
    - world_key 为空时：仅在本 session 内可见
    """
    name = req.get("name", "未知 NPC")
    key = req.get("key") or name.lower().replace(" ", "_")[:32]
    world_key = req.get("world_key", "")
    profile = req.get("profile", {"role": "minor", "traits": [], "faction": "", "status": "alive"})
    npc_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO npc_profiles "
            "(id, session_id, key, name, world_key, profile_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (npc_id, session_id, key, name, world_key,
             json.dumps(profile, ensure_ascii=False), now, now)
        )
        await db.commit()
    return {"npc_id": npc_id, "key": key, "name": name, "world_key": world_key}


@router.patch("/sessions/{session_id}/npcs/{npc_key}")
async def update_npc(session_id: str, npc_key: str, req: dict):
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT id, profile_json, world_key FROM npc_profiles WHERE session_id=? AND key=?",
            (session_id, npc_key)
        )).fetchone()
        if not row:
            raise HTTPException(404, f"NPC '{npc_key}' not found")
        profile = json.loads(row["profile_json"])
        profile.update(req.get("profile", {}))
        name = req.get("name") or profile.get("name", npc_key)
        world_key = req.get("world_key", row["world_key"])
        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE npc_profiles SET name=?, world_key=?, profile_json=?, updated_at=? WHERE id=?",
            (name, world_key, json.dumps(profile, ensure_ascii=False), now, row["id"])
        )
        await db.commit()
    return {"ok": True, "key": npc_key, "world_key": world_key, "profile": profile}


@router.delete("/sessions/{session_id}/npcs/{npc_key}")
async def delete_npc(session_id: str, npc_key: str):
    async with get_db() as db:
        await db.execute("DELETE FROM npc_profiles WHERE session_id=? AND key=?", (session_id, npc_key))
        await db.commit()
    return {"ok": True, "deleted_key": npc_key}


# ── 记忆 API ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/memory")
async def search_memory(session_id: str, q: str = "", top_k: int = 10,
                        tier: Optional[str] = None):
    from ...memory.adapter import memory_adapter
    from ...db import MemoryEntry

    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT world_plugin FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
    world_plugin = sess["world_plugin"] if sess else "crossover"

    results_text = await memory_adapter.recall(
        session_id=session_id,
        world_plugin=world_plugin,
        query_text=q,
        top_k=top_k,
    )

    async with get_db() as db:
        where = ["session_id=?"]
        params: list = [session_id]
        if tier:
            where.append("tier=?")
            params.append(tier)
        params.append(top_k)
        rows = await db.execute(
            f"SELECT * FROM memory_entries WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT ?",
            params
        )
        entries = [MemoryEntry.from_row(dict(r)).to_dict() for r in await rows.fetchall()]

    return {"results": results_text, "entries": entries, "full_mode": memory_adapter.is_full_mode}


@router.post("/sessions/{session_id}/memory")
async def add_memory(session_id: str, req: AddMemoryRequest):
    from ...memory.adapter import memory_adapter

    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT world_plugin FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
    world_plugin = sess["world_plugin"] if sess else "crossover"

    ok = await memory_adapter.add_memory(
        session_id=session_id,
        world_plugin=world_plugin,
        content=req.content,
        node_type=req.node_type,
        chapter_id=req.chapter_id,
        metadata=req.metadata,
    )
    return {"added": ok}


@router.post("/sessions/{session_id}/memory/consolidate")
async def memory_consolidate(session_id: str):
    """触发记忆固化（将 episodic 记忆压缩为 semantic）。"""
    from ...memory.adapter import memory_adapter
    try:
        result = await memory_adapter.consolidate_session(session_id)
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(500, f"Memory consolidation failed: {e}")


@router.post("/sessions/{session_id}/memory/rollback")
async def memory_rollback_endpoint(session_id: str, req: MemoryRollbackRequest):
    """回滚记忆条目到指定时间点或章节。"""
    from ...memory.rollback import memory_rollback
    try:
        if req.chapter_id:
            async with get_db() as db:
                ch_row = await (await db.execute(
                    "SELECT created_at FROM chapters WHERE id=? AND session_id=?",
                    (req.chapter_id, session_id)
                )).fetchone()
            if not ch_row:
                raise HTTPException(404, f"Chapter {req.chapter_id} not found")
            result = await memory_rollback.rollback_chapter(
                novel_id=session_id,
                chapter_id=req.chapter_id,
                chapter_created_at=str(ch_row["created_at"]),
            )
        elif req.since_iso:
            result = await memory_rollback.rollback_by_time(
                novel_id=session_id,
                since_iso=req.since_iso,
            )
        else:
            raise HTTPException(400, "Provide chapter_id or since_iso")
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Memory rollback failed: {e}")


# ── 骰子历史 ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/dice-history")
async def get_dice_history(session_id: str, limit: int = 20):
    async with get_db() as db:
        rows = await db.execute(
            "SELECT id, pool, threshold, rolls, net, verdict, attribute, skill, reason, created_at "
            "FROM dice_log WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)
        )
        result = []
        for r in await rows.fetchall():
            d = dict(r)
            try:
                d["rolls"] = json.loads(d["rolls"])
            except Exception:
                pass
            result.append(d)
        return {"history": result, "count": len(result)}


# ── 统计 / 重放 / 压缩 ────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/stats")
async def get_session_stats(session_id: str):
    async with get_db() as db:
        msg_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id=? AND role='user'",
            (session_id,),
        )
        msg_cnt = (await msg_row.fetchone())["cnt"]

        dice_row = await db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN verdict IN ('success','critical_success') THEN 1 ELSE 0 END) as passed "
            "FROM dice_log WHERE session_id=?",
            (session_id,),
        )
        dice_data = await dice_row.fetchone()
        dice_total = dice_data["total"] or 0
        dice_passed = dice_data["passed"] or 0

        mem_row = await db.execute(
            "SELECT tier, COUNT(*) as cnt FROM memory_entries WHERE session_id=? GROUP BY tier",
            (session_id,),
        )
        mem_by_tier = {r["tier"]: r["cnt"] for r in await mem_row.fetchall()}

        ch_row = await db.execute(
            "SELECT COUNT(*) as total, SUM(is_consolidated) as consolidated "
            "FROM chapters WHERE session_id=?",
            (session_id,),
        )
        ch_data = await ch_row.fetchone()
        ch_total = ch_data["total"] or 0
        ch_consolidated = ch_data["consolidated"] or 0

        npc_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM npc_profiles WHERE session_id=?",
            (session_id,),
        )
        npc_cnt = (await npc_row.fetchone())["cnt"]

    # 当前 narrator 使用的模型名（供前端顶栏展示）
    narrator_model = ""
    try:
        from ...agents.llm import load_agent_config
        cfg = load_agent_config("narrator")
        provider = cfg.get("provider", "")
        model = cfg.get("model", "")
        narrator_model = f"{provider}/{model}".strip("/")
    except Exception:
        pass

    return {
        "session_id": session_id,
        "turns": msg_cnt,
        "model": narrator_model,
        "dice": {
            "total": dice_total,
            "passed": dice_passed,
            "pass_rate": round(dice_passed / dice_total, 2) if dice_total else 0.0,
        },
        "memory": {"total": sum(mem_by_tier.values()), "by_tier": mem_by_tier},
        "chapters": {"total": ch_total, "consolidated": ch_consolidated},
        "npcs": npc_cnt,
    }


@router.get("/sessions/{session_id}/replay")
async def replay_session(
    session_id: str,
    from_message_id: Optional[str] = None,
    speed: float = 1.0,
):
    """历史重放：将会话 Parts 按时间顺序以 SSE 重新推送。"""
    import asyncio

    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT id FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not sess:
            raise HTTPException(404, "Session not found")

        start_ts: float = 0.0
        if from_message_id:
            msg_row = await (await db.execute(
                "SELECT created_at FROM messages WHERE id=? AND session_id=?",
                (from_message_id, session_id)
            )).fetchone()
            if msg_row:
                start_ts = msg_row["created_at"]

        q = (
            "SELECT mp.id, mp.type, mp.content, mp.agent, mp.created_at, m.role "
            "FROM message_parts mp "
            "JOIN messages m ON mp.message_id = m.id "
            "WHERE mp.session_id=? AND mp.status='done' "
            + (f"AND mp.created_at >= {start_ts} " if start_ts else "")
            + "ORDER BY mp.created_at ASC"
        )
        rows = await (await db.execute(q, (session_id,))).fetchall()
        parts_data = [dict(r) for r in rows]

    async def sse_generator():
        yield f"data: {json.dumps({'type': 'replay.start', 'total': len(parts_data)})}\n\n"

        prev_ts: Optional[float] = None
        for part in parts_data:
            curr_ts = part.get("created_at", 0)
            if speed > 0 and prev_ts is not None and curr_ts > prev_ts:
                delay = (curr_ts - prev_ts) / speed
                await asyncio.sleep(min(delay, 3.0))
            prev_ts = curr_ts

            try:
                content = json.loads(part.get("content", "{}"))
            except Exception:
                content = {}

            event = {
                "type": "replay.part",
                "part_id": part["id"],
                "part_type": part["type"],
                "content": content,
                "agent": part.get("agent", ""),
                "role": part.get("role", ""),
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'replay.done', 'replayed': len(parts_data)})}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/compact")
async def manual_compact(session_id: str):
    """手动触发上下文压缩（章节固化 + 记忆归纳）。"""
    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT id FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not sess:
            raise HTTPException(404, "Session not found")

    from ...agents.state import TurnContext
    from ...agents.chronicler_agent import chronicler_agent_node

    ctx = TurnContext(session_id=session_id, message_id="manual_compact")

    try:
        ctx = await chronicler_agent_node(ctx)
        summary = getattr(ctx, "chapter_summary", "") or ""
    except Exception as e:
        raise HTTPException(500, f"压缩失败: {e}")

    async with get_db() as db:
        cnt_row = await (await db.execute(
            "SELECT COUNT(*) as cnt FROM chapters WHERE session_id=? AND is_consolidated=1",
            (session_id,)
        )).fetchone()
        consolidated = cnt_row["cnt"] if cnt_row else 0

    return {"ok": True, "summary": summary, "consolidated_chapters": consolidated}
