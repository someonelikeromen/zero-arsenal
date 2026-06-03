"""
RedisEventBus — IEventBus 的 Redis Pub/Sub 实现。
设计文档 09-event-bus-sse.md §8 扩展性设计。

状态：已实现 publish/subscribe/get_events_after_from_db。
需要 Redis 服务；未连接时自动降级为进程内队列（单节点模式）。

切换到此实现：
    在 backend/bus/__init__.py 将 `bus = EventBus()` 改为：
        from .redis_bus import RedisEventBus
        bus = RedisEventBus(redis_url=os.environ["REDIS_URL"])

依赖安装（待激活时取消注释）：
    pip install redis>=5.0
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from .event_bus import BusEvent, EventType, Subscription
from .interface import IEventBus

logger = logging.getLogger(__name__)


class RedisEventBus(IEventBus):
    """
    基于 Redis Pub/Sub 的多进程/多节点事件总线。

    架构说明：
      - publish()  → redis.publish(channel=session_id, message=json)
      - subscribe() → redis.subscribe(channel=session_id) → asyncio.Queue
      - event_log  → Redis ZSET（score=timestamp）替代 SQLite event_log 表
      - 断点续传   → ZRANGEBYSCORE(session_id:events, last_ts, +inf)

    注意：此实现桩未填充，需要部署 Redis 后激活。
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._redis: object | None = None   # redis.asyncio.Redis instance (lazy init)
        self._pubsub: object | None = None
        # 本地 fallback 队列（未连接 Redis 时降级为进程内队列）
        self._local_queues: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "[RedisEventBus] 初始化，将在首次 publish/subscribe 时连接 %s", redis_url
        )

    # ── 连接管理 ──────────────────────────────────────────────────────────────

    async def _ensure_connected(self) -> None:
        """延迟初始化 Redis 连接（首次 publish/subscribe 时调用）。"""
        if self._redis is not None:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
            self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)
            logger.info(f"[RedisEventBus] 已连接 {self._redis_url}")
        except ImportError:
            logger.error("[RedisEventBus] 未安装 redis 包，请 pip install redis>=5.0")
        except Exception as e:
            logger.error(f"[RedisEventBus] 连接失败: {e}")

    # ── IEventBus 抽象方法实现（桩）───────────────────────────────────────────

    async def publish(self, event: BusEvent) -> None:
        """
        发布事件到 Redis Pub/Sub channel（session:{session_id}）。
        同时写入 ZSET（session:{session_id}:events）供断线重连重放。
        Redis 不可用时降级为进程内队列。
        """
        import time
        await self._ensure_connected()
        event_json = json.dumps({
            "type": event.type.value if hasattr(event.type, "value") else str(event.type),
            "session_id": event.session_id,
            "data": event.data,
        }, ensure_ascii=False)

        if self._redis is not None:
            try:
                score = time.time()
                zset_key = f"session:{event.session_id}:events"
                # 写入 ZSET 供重放，保留最近 200 条（通过 ZREMRANGEBYRANK 裁剪）
                await self._redis.zadd(zset_key, {event_json: score})
                await self._redis.zremrangebyrank(zset_key, 0, -201)
                await self._redis.expire(zset_key, 3600)  # 1h TTL
                await self._redis.publish(f"session:{event.session_id}", event_json)
                return
            except Exception as e:
                logger.warning(f"[RedisEventBus] publish failed: {e}, falling back to local queue")

        # 降级到本地队列
        async with self._lock:
            for q in self._local_queues.get(event.session_id, []):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass

    async def subscribe(self, session_id: str) -> Subscription:
        """
        订阅 session 事件。
        Redis 可用时走 Pub/Sub；否则降级到进程内队列。
        """
        await self._ensure_connected()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._local_queues.setdefault(session_id, []).append(q)

        if self._redis is not None:
            # 启动后台任务从 Redis Pub/Sub 转发到本地 queue
            asyncio.create_task(
                self._redis_to_queue(f"session:{session_id}", q),
                name=f"redis_sub_{session_id[:8]}"
            )

        return Subscription(session_id=session_id, queue=q, bus=self)  # type: ignore[arg-type]

    async def _redis_to_queue(self, channel: str, q: asyncio.Queue) -> None:
        """从 Redis Pub/Sub 读取消息并转发到本地 asyncio.Queue。"""
        try:
            pubsub = self._redis.pubsub()  # type: ignore[union-attr]
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    try:
                        raw = message["data"]
                        data = json.loads(raw)
                        bus_event = BusEvent(
                            type=EventType(data["type"]) if "type" in data else EventType.SESSION_STARTED,
                            session_id=data.get("session_id", ""),
                            data=data.get("data", {}),
                        )
                        try:
                            q.put_nowait(bus_event)
                        except asyncio.QueueFull:
                            pass
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[RedisEventBus] redis_to_queue error on {channel}: {e}")

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._local_queues.get(session_id, [])
            if queue in subs:
                subs.remove(queue)

    def get_events_after(self, session_id: str, last_event_id: str) -> list[BusEvent]:
        """
        同步查询（供非 async 调用者使用）。
        Redis 未连接时返回空列表（降级为单进程模式无历史重放）。
        """
        # 同步包装：在有 Redis 时使用 asyncio.run_coroutine_threadsafe 或直接返回空
        # 注：async 版请用 get_events_after_from_db
        return []

    async def get_events_after_from_db(
        self, session_id: str, last_event_id: str, limit: int = 50
    ) -> list[BusEvent]:
        """
        从 Redis ZSET 取出 last_event_id（时间戳）之后的事件，用于 SSE 断线重连时历史重放。

        last_event_id 格式：浮点时间戳字符串（如 "1717340000.123"）；
        若为空或无法解析，返回最近 limit 条。
        """
        if self._redis is None:
            await self._ensure_connected()
        if self._redis is None:
            logger.debug("[RedisEventBus] Redis 不可用，跳过历史重放（单进程模式）")
            return []

        try:
            import time
            try:
                min_score = float(last_event_id) if last_event_id else "-inf"
            except (ValueError, TypeError):
                min_score = time.time() - 3600  # 回溯 1h

            zset_key = f"session:{session_id}:events"
            raw_items: list[str] = await self._redis.zrangebyscore(
                zset_key,
                min_score,
                "+inf",
                start=0,
                num=limit,
            )
            events: list[BusEvent] = []
            for raw in raw_items:
                try:
                    d = json.loads(raw)
                    events.append(BusEvent(
                        type=EventType(d["type"]),
                        session_id=d.get("session_id", session_id),
                        data=d.get("data", {}),
                    ))
                except Exception:
                    pass
            return events
        except Exception as e:
            logger.warning("[RedisEventBus] get_events_after_from_db 失败: %s", e)
            return []
