"""
流式通信路由：消息发送 + SSE 事件流。
对应设计文档 11-api-design.md §3 / 09-event-bus-sse.md
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...bus import bus, BusEvent, EventType
from ...bus.sse_adapter import make_sse_response
from ...db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class SendMessageRequest(BaseModel):
    content: str
    message_type: str = "player_action"
    metadata: dict = {}


@router.post("/sessions/{session_id}/message", status_code=202)
async def send_message(session_id: str, req: SendMessageRequest, background_tasks: BackgroundTasks):
    """
    发送玩家输入，触发完整 Agent 管线（异步后台执行）。
    返回 202 Accepted + {message_id, status: "processing"}，
    前端通过 SSE /events 订阅后续流式输出。
    """
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    message_id = str(uuid.uuid4())
    now = datetime.now().timestamp()

    try:
        async with get_db() as db:
            session_row = await (await db.execute(
                "SELECT id, status FROM sessions WHERE id=?", (session_id,)
            )).fetchone()
            if not session_row:
                raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
            if session_row["status"] == "deleted":
                raise HTTPException(status_code=410, detail="会话已被删除")

            cnt_row = await (await db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE session_id=?", (session_id,)
            )).fetchone()
            cnt = cnt_row["cnt"] if cnt_row else 0
            await db.execute(
                "INSERT INTO messages (id, session_id, role, turn_index, content, message_type, created_at) "
                "VALUES (?, ?, 'user', ?, ?, ?, ?)",
                (message_id, session_id, cnt, req.content, req.message_type, now)
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"消息写入失败: {e}")

    background_tasks.add_task(_run_agent_pipeline, session_id, message_id, req.content)
    return {
        "message_id": message_id,
        "session_id": session_id,
        "status": "processing",
        "stream_url": f"/api/sessions/{session_id}/events",
    }


async def _run_agent_pipeline(session_id: str, message_id: str, content: str) -> None:
    """Agent 管线入口 — 接入 LangGraph 图。"""
    from ...agents import TurnContext, get_graph
    from ...agents.cancellation import clear_cancel

    # 新回合开始：清除上一回合可能残留的取消标记
    clear_cancel(session_id)

    await bus.publish(BusEvent(
        type=EventType.TURN_STARTED, session_id=session_id,
        data={"message_id": message_id}
    ))

    character_data: dict = {}
    mode = "play"
    plugin_key = "crossover"
    try:
        async with get_db() as db:
            sess = await (await db.execute("SELECT * FROM sessions WHERE id=?", (session_id,))).fetchone()
            if sess:
                mode = sess["mode"]
                plugin_key = sess["plugin_key"]
            char = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1", (session_id,)
            )).fetchone()
            if char:
                character_data = json.loads(char["data_json"])
    except Exception as _e:
        logger.warning("[stream] 加载角色数据失败: %s", _e)

    _plugin_obj = None
    try:
        from ...extensions.plugin import plugin_registry as _plug_reg
        _plugin_obj = _plug_reg.get(plugin_key)
        if _plugin_obj:
            turn_state = {
                "session_id": session_id, "message_id": message_id,
                "plugin_key": plugin_key, "mode": mode,
                "character_data": character_data,
            }
            character_data = _plugin_obj.on_turn_start(turn_state).get("character_data", character_data)
    except Exception as _e:
        logger.warning("[stream] on_turn_start 失败: %s", _e)

    turn_index = 0
    try:
        async with get_db() as db:
            ti_row = await (await db.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE session_id=? AND role='user'",
                (session_id,)
            )).fetchone()
            turn_index = ti_row["cnt"] if ti_row else 1
    except Exception as _e:
        logger.warning("[stream] 获取 turn_index 失败: %s", _e)

    ctx = TurnContext(
        session_id=session_id,
        message_id=message_id,
        user_input=content,
        character_data=character_data,
        plugin_key=plugin_key,
        mode=mode,
        turn_index=turn_index,
        novel_id=session_id,   # 03-agent-system.md §4：novel_id = session_id
    )

    hook_ctx: dict = {
        "session_id": session_id, "message_id": message_id,
        "user_input": content, "mode": mode, "plugin_key": plugin_key,
    }
    try:
        from ...hooks import hook_manager, HookEvent
        # conf_b04：会话生命周期 on_session_start 在管线开始前触发
        await hook_manager.fire(HookEvent.on_session_start, hook_ctx)
        await hook_manager.fire(HookEvent.before_turn, hook_ctx)
    except Exception as _e:
        logger.warning("[stream] on_session_start / before_turn hook 失败: %s", _e)

    from ...agents.cancellation import TurnCancelled, clear_cancel as _clear_cancel
    pipeline_error: str = ""
    try:
        graph = get_graph()
        await graph.ainvoke(ctx)
        await bus.publish(BusEvent(
            type=EventType.SESSION_IDLE, session_id=session_id,
            data={"message_id": message_id}
        ))
    except TurnCancelled:
        # 玩家主动取消：优雅结束，不报错
        _clear_cancel(session_id)
        await bus.publish(BusEvent(
            type=EventType.SESSION_IDLE, session_id=session_id,
            data={"message_id": message_id, "cancelled": True}
        ))
    except Exception as e:
        pipeline_error = str(e)
        await bus.publish(BusEvent(
            type=EventType.SESSION_ERROR, session_id=session_id,
            data={"error": pipeline_error, "message_id": message_id, "recoverable": True}
        ))

    try:
        from ...hooks import hook_manager, HookEvent
        if pipeline_error:
            # conf_b04：异常路径同时触发 on_error 与会话级 on_session_error
            err_ctx = {**hook_ctx, "error": pipeline_error, "agent": "pipeline"}
            await hook_manager.fire(HookEvent.on_error, err_ctx)
            await hook_manager.fire(HookEvent.on_session_error, err_ctx)
        else:
            after_ctx = {**hook_ctx, "narrative": getattr(ctx, "narrative_text", "")}
            await hook_manager.fire(HookEvent.after_turn, after_ctx)
            # conf_b04：成功路径触发会话级 on_session_end
            await hook_manager.fire(HookEvent.on_session_end, after_ctx)
    except Exception as _e:
        logger.warning("[stream] after_turn / on_error / on_session_* hook 失败: %s", _e)

    try:
        if _plugin_obj:
            async with get_db() as db:
                char_row = await (await db.execute(
                    "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1",
                    (session_id,)
                )).fetchone()
                if char_row:
                    character_data = json.loads(char_row["data_json"])

            end_state = {
                "session_id": session_id, "message_id": message_id,
                "plugin_key": plugin_key, "mode": mode,
                "character_data": character_data,
            }
            result_state = _plugin_obj.on_turn_end(end_state)
            new_char = result_state.get("character_data") if isinstance(result_state, dict) else None
            if new_char and new_char != character_data:
                now_ts = datetime.now().timestamp()
                async with get_db() as db:
                    await db.execute(
                        "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
                        (json.dumps(new_char, ensure_ascii=False), now_ts, session_id)
                    )
                    await db.commit()
    except Exception as _e:
        logger.warning("[stream] on_turn_end 失败: %s", _e)

    await bus.publish(BusEvent(
        type=EventType.TURN_ENDED, session_id=session_id,
        data={"message_id": message_id, "error": pipeline_error or None}
    ))


@router.post("/sessions/{session_id}/opening", status_code=202)
async def generate_opening(session_id: str, background_tasks: BackgroundTasks):
    """
    生成开场叙事。仅当会话尚无任何叙事内容时触发。
    汇集世界 opening_scene 档案 + 角色 first_message 作为开场上下文，
    走完整 Agent 管线（不插入玩家可见的 user 消息）。
    """
    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT id, status FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not sess:
            raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
        if sess["status"] == "deleted":
            raise HTTPException(status_code=410, detail="会话已被删除")

        # 已有助手消息则不重复生成开场
        assist_row = await (await db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id=? AND role='assistant'",
            (session_id,)
        )).fetchone()
        if assist_row and assist_row["cnt"] > 0:
            return {"status": "skipped", "reason": "already_has_narrative"}

        # 收集开场上下文：角色 first_message + 世界 opening_scene 档案
        opening_bits: list[str] = []
        char = await (await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1", (session_id,)
        )).fetchone()
        if char:
            try:
                cdata = json.loads(char["data_json"] or "{}")
                fm = cdata.get("first_message") or cdata.get("meta", {}).get("first_message")
                if fm:
                    opening_bits.append(f"角色开场独白参考：{fm}")
            except Exception:
                pass
        # 优先专用的 opening_scene 档案；其次 setting/lore
        scene_rows = await (await db.execute(
            "SELECT title, content FROM world_archives WHERE session_id=? AND archive_type='opening_scene' "
            "ORDER BY created_at ASC LIMIT 2", (session_id,)
        )).fetchall()
        for r in scene_rows:
            opening_bits.append(f"开场情境 · {r['title']}：{(r['content'] or '')[:400]}")
        arch_rows = await (await db.execute(
            "SELECT title, content FROM world_archives WHERE session_id=? AND archive_type IN ('setting','lore') "
            "ORDER BY created_at ASC LIMIT 3", (session_id,)
        )).fetchall()
        for r in arch_rows:
            opening_bits.append(f"{r['title']}：{(r['content'] or '')[:200]}")

    context = "\n".join(opening_bits) if opening_bits else "（无额外设定，按世界与角色背景自由开场）"
    directive = (
        "【开场叙事】这是冒险的第一幕，玩家尚未行动。"
        "请根据以下世界设定与角色背景，生成一段引人入胜的开场情境，"
        "交代时间、地点、主角当前处境，并以一个可供玩家自由行动的悬念收尾。\n\n"
        f"{context}"
    )

    message_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    async with get_db() as db:
        cnt_row = await (await db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id=?", (session_id,)
        )).fetchone()
        cnt = cnt_row["cnt"] if cnt_row else 0
        await db.execute(
            "INSERT INTO messages (id, session_id, role, turn_index, content, message_type, phase, created_at) "
            "VALUES (?, ?, 'assistant', ?, ?, 'opening', 'opening', ?)",
            (message_id, session_id, cnt, directive, now),
        )
        await db.commit()
    background_tasks.add_task(_run_agent_pipeline, session_id, message_id, directive)
    return {
        "message_id": message_id,
        "session_id": session_id,
        "status": "processing",
        "stream_url": f"/api/sessions/{session_id}/events",
    }


@router.delete("/sessions/{session_id}/stream")
async def cancel_stream(session_id: str):
    """
    请求取消当前正在进行的生成。
    登记取消标记 → Agent 管线在下一个节点边界中断 → 发布 SESSION_IDLE 解除前端等待。
    """
    from ...agents.cancellation import request_cancel
    request_cancel(session_id)
    # 立即解除前端 sending 状态（管线会在边界处真正停止）
    await bus.publish(BusEvent(
        type=EventType.SESSION_IDLE, session_id=session_id,
        data={"cancelled": True}
    ))
    return {"ok": True, "session_id": session_id, "cancelled": True}


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
):
    """
    SSE 事件流端点（09-event-bus-sse.md §4）。
    支持 Last-Event-ID 断点续传（Header 优先，query param 兜底）。
    SSE 逻辑统一由 bus/sse_adapter.py 的 make_sse_response() 处理。
    """
    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT id, status FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
    if not sess:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    if sess["status"] == "deleted":
        raise HTTPException(status_code=410, detail="会话已被删除")

    last_event_id = last_event_id or request.query_params.get("last_event_id")
    return await make_sse_response(session_id, last_event_id, bus, request=request)
