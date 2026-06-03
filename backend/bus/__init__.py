"""
ZeroArsenal 事件总线入口。

默认使用进程内 asyncio.Queue 实现（EventBus）。
若环境变量 REDIS_URL 已设置，自动切换到 RedisEventBus（需安装 redis[hiredis]）。

多实例部署时设置：
    REDIS_URL=redis://your-redis-host:6379/0
"""
import os

from .event_bus import BusEvent, EventType, Subscription
from .interface import IEventBus

if os.getenv("REDIS_URL"):
    try:
        from .redis_bus import RedisEventBus
        from .event_bus import EventBus  # 保持向后兼容
        bus: IEventBus = RedisEventBus(os.getenv("REDIS_URL", ""))
    except Exception:
        # redis 未安装时降级为本地实现
        from .event_bus import EventBus, bus as _bus  # type: ignore[assignment]
        bus = _bus
        EventBus = EventBus  # noqa: F811
else:
    from .event_bus import EventBus, bus as _bus  # type: ignore[assignment]
    bus = _bus

__all__ = ["EventBus", "IEventBus", "BusEvent", "EventType", "Subscription", "bus"]
