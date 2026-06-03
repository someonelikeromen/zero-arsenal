"""
agent_span — 异步上下文管理器，自动发布 agent.started / agent.ended SSE。
各 Agent 节点函数通过 `async with agent_span(ctx, "rules"):` 包裹核心逻辑。
"""
from __future__ import annotations
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator


@asynccontextmanager
async def agent_span(ctx, agent_name: str) -> AsyncIterator[None]:
    """
    发布 agent.started → 执行体 → agent.ended（含耗时 ms）。
    任何异常透传，ended 事件仍发送（带 error 字段）。
    """
    from ..bus import bus, BusEvent, EventType
    from .cancellation import is_cancelled, TurnCancelled

    # 节点边界检查：玩家若已请求取消，则中断后续管线
    if is_cancelled(ctx.session_id):
        raise TurnCancelled(f"session {ctx.session_id} cancelled by user")

    started_at = time.monotonic()
    try:
        await bus.publish_agent(ctx.session_id, agent_name, started=True)
    except Exception:
        pass

    # 触发 before_agent Hook
    try:
        from ..hooks import hook_manager, HookEvent
        await hook_manager.fire(HookEvent.before_agent, {
            "session_id": ctx.session_id,
            "agent": agent_name,
            "turn_index": getattr(ctx, "turn_index", 0),
        })
    except Exception:
        pass

    error_msg: str = ""
    try:
        yield
    except Exception as exc:
        error_msg = str(exc)
        raise
    finally:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)

        # 触发 after_agent Hook（含耗时和可能的错误信息）
        try:
            from ..hooks import hook_manager, HookEvent
            await hook_manager.fire(HookEvent.after_agent, {
                "session_id": ctx.session_id,
                "agent": agent_name,
                "elapsed_ms": elapsed_ms,
                "error": error_msg or None,
            })
        except Exception:
            pass

        try:
            data: dict = {"agent": agent_name, "elapsed_ms": elapsed_ms}
            if error_msg:
                data["error"] = error_msg
            await bus.publish(BusEvent(
                type=EventType.AGENT_ENDED,
                session_id=ctx.session_id,
                data=data,
            ))
            # 错误时额外发布 agent.error 事件（设计文档 09 §3）
            if error_msg:
                await bus.publish(BusEvent(
                    type=EventType.AGENT_ERROR,
                    session_id=ctx.session_id,
                    data={"agent": agent_name, "error": error_msg, "elapsed_ms": elapsed_ms},
                ))
        except Exception:
            pass
