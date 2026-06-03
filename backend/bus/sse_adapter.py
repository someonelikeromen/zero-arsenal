"""
SSE 适配器 — 将 EventBus 订阅转换为 FastAPI StreamingResponse。
从 api/routers/stream.py 抽离，供多个路由复用（主流、调试流、回放流）。

参考设计文档 09-event-bus-sse.md §4 SSE 端点实现。

用法示例（在路由中）：
    from ...bus.sse_adapter import make_sse_response
    return await make_sse_response(session_id, last_event_id, bus)
"""
from __future__ import annotations

import json
import logging
from typing import Optional, AsyncIterator

from fastapi.responses import StreamingResponse

from .event_types import BusEvent, EventType

logger = logging.getLogger(__name__)

# SSE 响应头（禁用缓存，关闭 Nginx 缓冲）
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


async def _replay_missed_events(
    bus,
    session_id: str,
    last_event_id: str,
) -> AsyncIterator[str]:
    """
    断点续传：尝试从内存日志重放 last_event_id 之后的事件，
    内存未命中时 fallback 到 DB。
    按设计文档 §9 错误处理：先发 replay.start，逐条重发，再发 replay.end。
    """
    missed = bus.get_events_after(session_id, last_event_id)
    if not missed:
        missed = await bus.get_events_after_from_db(session_id, last_event_id)

    if missed:
        replay_start = BusEvent(
            type=EventType.REPLAY_START,
            session_id=session_id,
            data={"count": len(missed)},
        )
        yield replay_start.to_sse()
        for ev in missed:
            yield ev.to_sse()
        replay_end = BusEvent(
            type=EventType.REPLAY_END,
            session_id=session_id,
            data={},
        )
        yield replay_end.to_sse()


async def make_sse_stream(
    session_id: str,
    last_event_id: Optional[str],
    bus,
    request=None,
) -> AsyncIterator[str]:
    """
    核心 SSE 生成器：先订阅（防止丢事件），再：
      1. 发送 server.connected 首事件（含 id: 行）
      2. 重放 last_event_id 之后的遗漏事件（若有）
      3. 实时推送后续 BusEvent
         - session.done → 关闭（会话永久结束）
         - session.error 且 recoverable=False → 关闭
         - 客户端断开（request.is_disconnected）→ 关闭
         - session.idle → 不关闭，保持连接等待下一轮
    """
    subscription = await bus.subscribe(session_id)

    async def _generator() -> AsyncIterator[str]:
        # 首事件：标准 id: 行，前端 Last-Event-ID 基线从此建立
        yield BusEvent(
            type=EventType.SERVER_CONNECTED,
            session_id=session_id,
            data={},
        ).to_sse()

        # 断点续传
        if last_event_id:
            async for chunk in _replay_missed_events(bus, session_id, last_event_id):
                yield chunk

        # 实时事件流
        try:
            async for event in subscription:
                # 客户端断开检测
                if request is not None:
                    try:
                        if await request.is_disconnected():
                            break
                    except Exception:
                        pass

                yield event.to_sse()

                if event.type == EventType.SESSION_DONE:
                    break
                # 不可恢复的 session.error 也关闭流
                if event.type == EventType.SESSION_ERROR:
                    if not event.data.get("recoverable", True):
                        break
        finally:
            await subscription.close()

    return _generator()


async def make_sse_response(
    session_id: str,
    last_event_id: Optional[str],
    bus,
    request=None,
) -> StreamingResponse:
    """
    构建 FastAPI StreamingResponse（SSE）。
    必须在返回 Response 之前完成订阅（opencode 先订阅再响应原则，
    防止 Agent 在建立订阅前发出的事件丢失）。
    """
    stream = await make_sse_stream(session_id, last_event_id, bus, request=request)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
