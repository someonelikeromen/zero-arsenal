"""
IEventBus — 事件总线抽象接口
设计文档 09-event-bus-sse.md §11 可替换后端

当前实现：asyncio.Queue（进程内，单机）
预留实现：Redis Pub/Sub（多进程 / 多实例水平扩展）

接口约定：
  - publish(event)         : 向指定 session 广播一个事件
  - subscribe(session_id)  : 创建订阅，返回可异步迭代的 Subscription 对象
  - unsubscribe(...)       : 移除订阅（Subscription.close() 内部调用）
  - get_events_after(...)  : 内存断点续传
  - publish_part_created() / publish_part_delta() / ... : 语义化快捷发布方法
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from .event_bus import BusEvent, Subscription


class IEventBus(abc.ABC):
    """
    事件总线抽象基类。
    具体实现需继承此类并实现所有 @abstractmethod。

    设计意图：将 `EventBus`（asyncio.Queue 实现）与 `RedisEventBus`（多实例实现）
    统一到同一接口，上层代码（agents / api routers）只依赖 IEventBus，
    运行时通过依赖注入或模块级 `bus` 单例切换。
    """

    # ── 核心发布 / 订阅 ─────────────────────────────────────────────────────

    @abc.abstractmethod
    async def publish(self, event: "BusEvent") -> None:
        """向 event.session_id 的所有订阅者广播事件（非阻塞，背压保护）。"""
        ...

    @abc.abstractmethod
    async def subscribe(self, session_id: str) -> "Subscription":
        """
        为指定 session 创建一个订阅。
        必须在返回 SSE Response 之前调用，确保不丢失创建期间的事件。
        """
        ...

    @abc.abstractmethod
    async def unsubscribe(self, session_id: str, queue: object) -> None:
        """移除订阅（由 Subscription.close() 调用，勿直接调用）。"""
        ...

    # ── 断点续传 ────────────────────────────────────────────────────────────

    def get_subscriber_count(self, session_id: str) -> int:
        """
        返回当前 session 的活跃订阅者数量（用于监控/健康检查）。
        设计文档 09-event-bus-sse.md §2.1。
        默认实现返回 -1（未知），子类应按需覆盖。
        """
        return -1

    @abc.abstractmethod
    def get_events_after(self, session_id: str, last_event_id: str) -> "list[BusEvent]":
        """内存优先：返回 last_event_id 之后的事件列表（用于 SSE 重连补偿）。"""
        ...

    @abc.abstractmethod
    async def get_events_after_from_db(
        self, session_id: str, last_event_id: str, limit: int = 50
    ) -> "list[BusEvent]":
        """DB fallback：服务重启后从持久化存储查询历史事件。"""
        ...

    # ── 语义化快捷方法（提供默认实现，子类可按需覆盖）──────────────────────

    async def publish_part_created(
        self, session_id: str, part_id: str, part_type: str,
        message_id: str, agent: str,
    ) -> None:
        from .event_bus import BusEvent, EventType
        await self.publish(BusEvent(
            type=EventType.PART_CREATED, session_id=session_id,
            data={"part_id": part_id, "part_type": part_type,
                  "message_id": message_id, "agent": agent},
        ))

    async def publish_part_delta(
        self, session_id: str, part_id: str, delta: str,
    ) -> None:
        from .event_bus import BusEvent, EventType
        await self.publish(BusEvent(
            type=EventType.PART_UPDATED, session_id=session_id,
            data={"part_id": part_id, "delta": delta},
        ))

    async def publish_part_done(
        self, session_id: str, part_id: str, content: "dict | str",
    ) -> None:
        from .event_bus import BusEvent, EventType
        await self.publish(BusEvent(
            type=EventType.PART_DONE, session_id=session_id,
            data={"part_id": part_id, "content": content},
        ))
        # conf_b04：每个 Part 结束时触发 on_part_done hook（懒导入，失败不影响发布）
        try:
            from ..hooks import hook_manager, HookEvent
            await hook_manager.fire(HookEvent.on_part_done, {
                "session_id": session_id,
                "part_id": part_id,
                "content": content,
            })
        except Exception:
            pass

    async def publish_agent(
        self, session_id: str, agent: str, started: bool,
    ) -> None:
        from .event_bus import BusEvent, EventType
        etype = EventType.AGENT_STARTED if started else EventType.AGENT_ENDED
        await self.publish(BusEvent(
            type=etype, session_id=session_id, data={"agent": agent},
        ))

    async def publish_session_done(self, session_id: str) -> None:
        from .event_bus import BusEvent, EventType
        await self.publish(BusEvent(
            type=EventType.SESSION_DONE, session_id=session_id,
        ))
