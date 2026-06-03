"""
事件总线 — asyncio.Queue 实现，参考 opencode bus/ 设计。
核心原则：先订阅，再返回 SSE Response，避免丢事件。

实现 IEventBus（interface.py）；多实例/多进程场景可切换为 RedisEventBus（redis_bus.py）。

EventType 常量和 BusEvent 数据类已抽离到 bus/event_types.py，
此处重新导出保持向后兼容（旧代码 from .event_bus import EventType 仍可用）。
"""
import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, Optional

from .interface import IEventBus  # noqa: E402
# 重新导出（向后兼容）
from .event_types import EventType, BusEvent  # noqa: F401


# ── EventBus ─────────────────────────────────────────────────────────────────

# 每个订阅者队列最大容量（超出后丢弃最旧事件，保护 publish 不被慢消费者阻塞）
_QUEUE_MAX_SIZE = 200

# 不写 DB 的事件类型（heartbeat 频率高，无需持久化）
_NO_PERSIST_TYPES = frozenset({EventType.HEARTBEAT})


class EventBus(IEventBus):
    """
    进程内事件总线（asyncio.Queue 实现）。
    实现 IEventBus 接口（见本文件 IEventBus 类）。
    每个 session 维护一个订阅者队列列表，publish 时广播给所有订阅者。
    背压策略：有界 Queue（maxsize=200）+ put_nowait；队列满时丢弃最旧事件并继续。

    多实例场景：使用 RedisEventBus（bus/redis_bus.py）替代。
    """

    def __init__(self) -> None:
        # session_id -> list of asyncio.Queue
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._event_log: list[BusEvent] = []   # 内存日志，供 Last-Event-ID 补偿
        self._lock = asyncio.Lock()

    async def publish(self, event: BusEvent) -> None:
        """
        向指定 session 的所有订阅者广播事件。
        使用 put_nowait：队列满时先丢弃队头最旧事件，再放新事件，
        确保 publish 不阻塞 Agent pipeline。
        """
        self._event_log.append(event)
        # 内存日志裁剪（保留最近 1000 条，避免无限增长）
        if len(self._event_log) > 1000:
            self._event_log = self._event_log[-1000:]

        queues = list(self._subscribers.get(event.session_id, []))
        dead_queues: list[asyncio.Queue] = []
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 丢弃最旧事件，腾出位置给新事件
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    # 已无法放入，视为死亡订阅者
                    dead_queues.append(q)

        # 清理死亡订阅者
        if dead_queues:
            async with self._lock:
                subs = self._subscribers.get(event.session_id, [])
                for dq in dead_queues:
                    if dq in subs:
                        subs.remove(dq)

        # 异步持久化到 DB（heartbeat 等高频事件跳过，失败不影响实时推送）
        if event.type not in _NO_PERSIST_TYPES:
            asyncio.create_task(self._persist_event(event))

    async def _persist_event(self, event: BusEvent) -> None:
        """把 BusEvent 持久化到 event_log 表，支持服务重启后的 Last-Event-ID 补偿。"""
        try:
            from ..db import get_db
            async with get_db() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO event_log "
                    "(id, session_id, type, data_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.session_id,
                        event.type,
                        json.dumps(event.data, ensure_ascii=False),
                        event.timestamp,
                    ),
                )
                await db.commit()
        except Exception:
            pass  # 持久化失败不影响实时推送

    async def subscribe(self, session_id: str) -> "Subscription":
        """
        创建订阅。必须在返回 SSE Response 之前调用，
        确保不丢失订阅后、Response 发出前的事件。
        使用有界 Queue（maxsize=_QUEUE_MAX_SIZE）防止慢消费者无限积压。
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            self._subscribers[session_id].append(q)
        return Subscription(session_id=session_id, queue=q, bus=self)

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._subscribers.get(session_id, [])
            if queue in subs:
                subs.remove(queue)

    def get_subscriber_count(self, session_id: str) -> int:
        """
        返回当前 session 的活跃订阅者数量（用于监控/健康检查）。
        设计文档 09-event-bus-sse.md §2.1 要求的监控接口。
        """
        return len(self._subscribers.get(session_id, []))

    def get_events_after(self, session_id: str, last_event_id: str) -> list[BusEvent]:
        """
        内存优先返回 last_event_id 之后的事件（断点续传）。
        内存未命中时返回空列表（由调用方触发 DB fallback）。
        """
        found = False
        result = []
        for ev in self._event_log:
            if ev.id == last_event_id:
                found = True
                continue
            if found and ev.session_id == session_id:
                result.append(ev)
        return result

    # 断点续传时间窗口（秒），与设计文档 09 §7 CLIENT_RECONNECT_WINDOW 对齐
    _REPLAY_WINDOW_SECONDS: int = 60

    async def get_events_after_from_db(self, session_id: str, last_event_id: str,
                                       limit: int = 200) -> list[BusEvent]:
        """
        DB fallback：服务重启后内存日志清空时，从 event_log 表查询历史事件。
        设计文档 09-event-bus-sse.md §7 断点续传策略。
        仅返回锚点后 60s 内的事件（CLIENT_RECONNECT_WINDOW），防止超大量回放。
        """
        import time
        try:
            from ..db import get_db
            async with get_db() as db:
                # 先查锚点的 created_at
                anchor_row = await (await db.execute(
                    "SELECT created_at FROM event_log WHERE id=?", (last_event_id,)
                )).fetchone()
                if not anchor_row:
                    return []
                anchor_ts = anchor_row["created_at"]
                window_end = anchor_ts + self._REPLAY_WINDOW_SECONDS
                rows = await (await db.execute(
                    "SELECT id, session_id, type, data_json, created_at FROM event_log "
                    "WHERE session_id=? AND created_at > ? AND created_at <= ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (session_id, anchor_ts, window_end, limit)
                )).fetchall()
                result = []
                for r in rows:
                    try:
                        data = json.loads(r["data_json"])
                    except Exception:
                        data = {}
                    result.append(BusEvent(
                        id=r["id"],
                        type=r["type"],
                        session_id=r["session_id"],
                        data=data,
                        timestamp=r["created_at"],
                    ))
                return result
        except Exception:
            return []

    # publish_part_created / publish_part_delta / publish_part_done /
    # publish_agent / publish_session_done 继承自 IEventBus 的默认实现。


class Subscription:
    """单个 SSE 连接的订阅对象。"""

    def __init__(self, session_id: str, queue: asyncio.Queue, bus: EventBus) -> None:
        self.session_id = session_id
        self.queue = queue
        self._bus = bus
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[BusEvent]:
        while not self._closed:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=10.0)
                yield event
            except asyncio.TimeoutError:
                # 发送 heartbeat（含服务器时间，前端用于连接保活检测）
                yield BusEvent(
                    type=EventType.HEARTBEAT,
                    session_id=self.session_id,
                    data={"server_time": datetime.now().timestamp()},
                )

    async def close(self) -> None:
        self._closed = True
        await self._bus.unsubscribe(self.session_id, self.queue)


# ── 全局单例 ─────────────────────────────────────────────────────────────────

bus = EventBus()
