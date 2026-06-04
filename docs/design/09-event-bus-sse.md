# 09 — 事件总线与 SSE 推送设计（Event Bus & SSE）

> **版本**：v1.1（2026-06 对齐实现）  
> **参考来源**：opencode `bus/` + `server/routes/event.ts`（先订阅再返回 Response 防丢事件）、pi TUI 差分渲染思想  
> **状态**：已实现（InMemory 单进程链路全量落地并接线生效；Redis 多进程分支有已知缺陷见 conf_b09）
>
> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。原「设计稿，待实现」横幅已撤销——`backend/bus/`、`backend/api/routers/stream.py`、`frontend/src/lib/sse.ts` 的单进程全链路（先订阅后响应、SSE 端点、续传、内存+DB 持久化、7 天清理）均已实现。下文若干样例与字段名已按实现修正。

---

## 目录

1. [设计来源与核心思想](#1-设计来源与核心思想)
2. [Bus 接口设计](#2-bus-接口设计)
3. [BusEvent 完整类型定义](#3-busevent-完整类型定义)
4. [SSE 端点完整实现](#4-sse-端点完整实现)
5. [前端 SSE 客户端 TypeScript 实现](#5-前端-sse-客户端-typescript-实现)
6. [流式正文差分渲染](#6-流式正文差分渲染)
7. [事件持久化策略](#7-事件持久化策略)
8. [Heartbeat 机制](#8-heartbeat-机制)
9. [错误处理与断线重连](#9-错误处理与断线重连)
10. [测试策略](#10-测试策略)

---

## 1. 设计来源与核心思想

### 1.1 来源

本设计直接参考 opencode 的事件总线架构（`bus/index.ts` + `server/routes/event.ts`）：

- **核心设计**：**先订阅，再返回 HTTP Response**——这解决了一个竞态问题：如果先返回 Response 再订阅，Agent 在建立订阅之前发出的事件将永久丢失。
- **实现模式**：每个 session 维护一个订阅者列表（`asyncio.Queue` 列表），`publish` 时向所有订阅者广播（fan-out）。

### 1.2 竞态问题说明

```
❌ 错误顺序（会丢失事件）：
   Client → GET /events → [返回 StreamingResponse] → [建立订阅]
                                                        ↑
                                          Agent 在这里发出的事件丢失！

✅ 正确顺序（来自 opencode）：
   Client → GET /events → [建立订阅] → [返回 StreamingResponse]
                           ↑
                   订阅在 Response 返回前建立，保证零丢失
```

### 1.3 整体数据流

```
AgentRunner
    │
    │ bus.publish(session_id, event)
    ▼
EventBus（内存中）
    │ fan-out broadcast
    ├──► Queue[subscriber_1]  ──► SSE 连接 1（主浏览器标签）
    ├──► Queue[subscriber_2]  ──► SSE 连接 2（调试面板）
    └──► EventLog Writer      ──► SQLite event_log 表（持久化）
                                       │
                                       └──► 断线重连时通过 Last-Event-ID 补偿
```

---

## 2. Bus 接口设计

### 2.1 接口定义

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from backend.bus.event_types import BusEvent


class IEventBus(ABC):
    """
    事件总线接口，支持 InMemory（asyncio.Queue）和 Redis 两种实现。

    ⚠️ 实现说明（与早期草案的差异）：
    - `publish(event)` —— session_id 内嵌于 BusEvent，无需单独传参（草案为 publish(session_id, event)）
    - `unsubscribe(session_id, queue)` —— 第二参数为 queue 对象，非 subscriber_id 字符串
    - `get_subscriber_count()` —— 非 abstractmethod，IEventBus 提供默认实现（返回 -1），
      具体实现（EventBus）返回精确值
    """

    @abstractmethod
    async def publish(self, event: BusEvent) -> None:
        """
        发布事件到 event.session_id 的所有订阅者。
        session_id 内嵌于 BusEvent，调用更简洁。
        """
        ...

    @abstractmethod
    async def subscribe(self, session_id: str) -> "Subscription":
        """
        创建订阅并返回 Subscription 对象。

        关键：此方法必须在 HTTP handler 返回 Response 之前调用。
        订阅者从调用时刻开始接收后续所有事件（历史事件通过补偿机制处理）。
        """
        ...

    @abstractmethod
    async def unsubscribe(self, session_id: str, queue: object) -> None:
        """注销订阅（通常在 SSE 连接断开时通过 Subscription.close() 间接调用）。"""
        ...

    def get_subscriber_count(self, session_id: str) -> int:
        """
        返回当前 session 的活跃订阅者数量（用于监控/健康检查）。
        默认返回 -1（未知），EventBus 实现中提供精确值。
        """
        return -1
```

### 2.2 InMemoryEventBus 实现

> ⚠️ **过时样例（2026-06）**：下方代码块为早期草案，与实现**不一致**，仅作历史参考。
> 实际实现见 `backend/bus/event_bus.py`：
> - 类名为 **`EventBus`**（非 `InMemoryEventBus`）；
> - 订阅对象为 **`Subscription`**（非 `BusSubscriber`，且**无 `subscriber_id`**）；`unsubscribe(session_id, queue)` 第二参为 queue 对象，`Subscription.close()` 间接调用；
> - `publish(event)` 签名（session_id 内嵌于 BusEvent），非草案的 `publish(session_id, event)`；
> - **心跳由 `Subscription.__aiter__` 在 `queue.get()` 空闲超时 10s 时就地 yield `heartbeat`**，而非草案的「哨兵 None 退出 + 独立心跳协程」；
> - `get_subscriber_count` 为同步方法（见 §2.1，下方草案误写为 `async`）；
> - `EventBus` 另实现了 §2「接口扩展」中的 `get_events_after()/get_events_after_from_db()`（断线续传）与 `publish_part_created/_delta/_done/_agent/_session_done` 语义化快捷发布方法（设计接口表应一并登记）。

```python
# 【过时草案，保留供对照；实际以 backend/bus/event_bus.py 的 EventBus/Subscription 为准】
import asyncio
import uuid
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncIterator


logger = logging.getLogger(__name__)


@dataclass
class BusSubscriber:
    """单个 SSE 连接对应的订阅者。"""
    subscriber_id: str
    session_id: str
    queue: asyncio.Queue
    created_at: float = field(default_factory=time.time)

    async def __aiter__(self) -> AsyncIterator["BusEvent"]:
        """支持 async for event in subscriber: 语法。"""
        while True:
            event = await self.queue.get()
            if event is None:  # 哨兵值，表示订阅结束
                break
            yield event
            self.queue.task_done()


class InMemoryEventBus(IEventBus):
    """
    基于 asyncio.Queue 的内存事件总线。

    适用于单进程部署。多进程/多实例需切换为 RedisPubSubEventBus。

    每个 session 维护：
    - 一个订阅者字典 {subscriber_id: BusSubscriber}
    - 每个订阅者有独立的 asyncio.Queue（fan-out 模式）
    """

    def __init__(self, max_queue_size: int = 1000):
        # {session_id: {subscriber_id: BusSubscriber}}
        self._subscribers: dict[str, dict[str, BusSubscriber]] = defaultdict(dict)
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, event: "BusEvent") -> None:
        """
        广播事件到 session 的所有订阅者。

        - 如果某订阅者的 Queue 已满（slow consumer），跳过该订阅者并记录警告
        - publish 本身不阻塞
        """
        subscribers = self._subscribers.get(session_id, {})

        if not subscribers:
            return  # 无订阅者，静默丢弃

        dropped = []
        for sub_id, subscriber in list(subscribers.items()):
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "订阅者 %s (session=%s) 队列已满，事件 %s 被丢弃",
                    sub_id, session_id, event.type,
                )
                dropped.append(sub_id)

        # 清理明显滞后的订阅者（队列满通常意味着连接已死）
        if dropped:
            async with self._lock:
                for sub_id in dropped:
                    self._subscribers[session_id].pop(sub_id, None)

    async def subscribe(self, session_id: str) -> BusSubscriber:
        """
        创建订阅者。

        ⚠️ 必须在 HTTP handler 返回 StreamingResponse 之前调用此方法。
        """
        subscriber_id = str(uuid.uuid4())
        subscriber = BusSubscriber(
            subscriber_id=subscriber_id,
            session_id=session_id,
            queue=asyncio.Queue(maxsize=self._max_queue_size),
        )

        async with self._lock:
            self._subscribers[session_id][subscriber_id] = subscriber

        logger.debug("新增订阅者 %s (session=%s)", subscriber_id, session_id)
        return subscriber

    async def unsubscribe(self, session_id: str, subscriber_id: str) -> None:
        """注销订阅者，向其 Queue 放入哨兵值 None 使 async for 退出。"""
        async with self._lock:
            subscriber = self._subscribers[session_id].pop(subscriber_id, None)

        if subscriber:
            await subscriber.queue.put(None)  # 哨兵值
            logger.debug("注销订阅者 %s (session=%s)", subscriber_id, session_id)

    async def get_subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, {}))

    async def close_session(self, session_id: str) -> None:
        """关闭 session 的所有订阅（session 结束时调用）。"""
        async with self._lock:
            subscribers = self._subscribers.pop(session_id, {})

        for subscriber in subscribers.values():
            await subscriber.queue.put(None)


# 全局单例
_bus_instance: InMemoryEventBus | None = None


def get_event_bus() -> InMemoryEventBus:
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = InMemoryEventBus()
    return _bus_instance
```

---

## 3. BusEvent 完整类型定义

### 3.1 基础事件结构

```python
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class BusEvent:
    """所有 SSE 事件的基础结构。"""

    type: str                           # 事件类型（见 EVENT_TYPES）
    session_id: str                     # 归属 session
    data: dict                          # 事件数据（类型安全见下方各事件定义）

    # 自动生成字段
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """序列化为 SSE 格式字符串。

        ⚠️ 实现（2026-06 对齐）：`data` 字段**嵌套**而非展开到顶层。
        实际载荷为 {"type", "session_id", "timestamp", "data": self.data}，
        前端按 `event.data.xxx` 读取（见 §5 / frontend/src/lib/sse.ts 与 bindSSEToStores.ts）。
        """
        import json
        payload = {
            "type": self.type,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "data": self.data,   # 嵌套，不展开
        }
        return f"id: {self.id}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 全部事件类型枚举
EVENT_TYPES = Literal[
    # 会话生命周期
    "session.started",      # 会话初始化完成
    "session.done",         # 会话全部处理完毕（最终事件）
    "session.error",        # 会话级错误
    "session.idle",         # （2026-06 新增）一轮处理完毕、等待下一轮；不关流（多回合常驻）
    "session.mode_changed", # （2026-06 新增）模式切换（play/plan/review）广播

    # Agent 生命周期
    "agent.started",        # Agent 开始处理
    "agent.ended",          # Agent 处理结束
    "agent.error",          # Agent 运行时错误

    # 对话轮次
    "turn.started",         # 新一轮 LLM 推理开始
    "turn.ended",           # 本轮 LLM 推理结束（含所有 tool_call）
    "turn.complete",        # （2026-06 新增）回合 anchor 写入完成（与 turn.ended 语义区分）

    # 章节
    "chapter.consolidated", # （2026-06 新增）章节固化完成

    # Part 生命周期（最高频事件）
    "part.created",         # Part 创建（叙事/工具结果/状态变更等）
    "part.updated",         # Part 流式更新（streaming token）
    "part.done",            # Part 完整输出完成
    "part.error",           # Part 生成失败

    # 权限流程
    "permission.ask",       # 工具请求用户授权
    "permission.granted",   # 用户授权
    "permission.denied",    # 用户拒绝

    # 系统事件
    "heartbeat",            # 心跳（每 10 秒，保持连接）
    "server.connected",     # SSE 连接建立确认（第一个事件）
    "replay.start",         # 断线重连历史回放开始
    "replay.end",           # 断线重连历史回放结束
]
```

### 3.2 各事件类型的 data 字段定义

> ⚠️ **字段名对齐（2026-06）**：实现的语义化发布方法（`backend/bus/interface.py`）与下列早期草案的字段命名不同，前后端一致采用实现版：
> - `part.created` data = `{part_id, part_type, message_id, agent}` —— 用 **`agent`**（非 `agent_name`），且不含 `content`/`is_streaming`；
> - `part.done` data = `{part_id, content}` —— 用 **`content`**（非 `final_content`），不含 `metadata`/`should_memorize`；
> - `part.updated` data = `{part_id, delta}` —— 用 `delta`（`full_content` 未发送）。
>
> 下方草案注释保留供对照，实际以上述实现字段为准。

```python
# ── session.started ──────────────────────────────────────────────────
# data: {
#   "novel_id": str,
#   "session_config": dict,     # 会话配置快照
#   "protagonist": str,         # 主角名
#   "current_chapter": str,     # 当前章节 ID
# }

# ── session.done ─────────────────────────────────────────────────────
# data: {
#   "final_message_id": str,
#   "total_turns": int,
#   "total_tokens": int,
# }

# ── agent.started ────────────────────────────────────────────────────
# data: {
#   "agent_name": str,          # "dm" | "npc.alice" | "narrator" | "world"
#   "turn_id": str,
#   "trigger": str,             # 触发原因（"user_input" | "tool_result" | "scheduled"）
# }

# ── agent.ended ──────────────────────────────────────────────────────
# data: {
#   "agent_name": str,
#   "turn_id": str,
#   "parts_generated": int,
#   "tokens_used": int,
#   "duration_ms": int,
# }

# ── turn.started ─────────────────────────────────────────────────────
# data: {
#   "turn_id": str,
#   "agent_name": str,
#   "message_id": str,
# }

# ── turn.ended ───────────────────────────────────────────────────────
# data: {
#   "turn_id": str,
#   "finish_reason": str,       # "stop" | "tool_calls" | "length" | "error"
#   "tool_calls_count": int,
# }

# ── part.created ─────────────────────────────────────────────────────
# data: {
#   "part_id": str,
#   "message_id": str,
#   "part_type": str,           # "narrative" | "tool_result" | "roll_result" | ...
#   "agent_name": str,
#   "content": str | dict,      # 初始内容（流式 Part 为空字符串）
#   "is_streaming": bool,       # True=流式输出中，False=一次性输出
# }

# ── part.updated ─────────────────────────────────────────────────────
# data: {
#   "part_id": str,
#   "delta": str,               # 本次新增的文本 token（仅流式 Part 有此字段）
#   "full_content": str,        # 截至本次的完整内容（可选，用于重建）
# }

# ── part.done ────────────────────────────────────────────────────────
# data: {
#   "part_id": str,
#   "part_type": str,
#   "final_content": str | dict,
#   "metadata": dict,
#   "should_memorize": bool,
# }

# ── part.error ───────────────────────────────────────────────────────
# data: {
#   "part_id": str,
#   "error": str,
#   "recoverable": bool,        # True=可以重试，False=需要用户干预
# }

# ── permission.ask ───────────────────────────────────────────────────
# data: {
#   "request_id": str,          # 权限请求唯一 ID（用于 grant/deny 回调）
#   "tool_id": str,
#   "agent_name": str,
#   "reason": str,              # 人类可读的授权原因
#   "args_preview": dict,       # 参数预览（敏感参数脱敏）
#   "expires_at": float,        # 请求过期时间戳（用于前端倒计时）
# }

# ── permission.granted / permission.denied ───────────────────────────
# data: {
#   "request_id": str,
#   "tool_id": str,
#   "decided_by": str,          # "user" | "auto_policy"
# }

# ── heartbeat ────────────────────────────────────────────────────────
# data: {
#   "server_time": float,
#   "session_active": bool,
#   "agent_running": bool,
# }
```

---

## 4. SSE 端点完整实现

```python
import asyncio
import json
import logging
import time
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import AsyncIterator

from zero_arsenal.events.bus import get_event_bus, BusSubscriber
from zero_arsenal.events.types import BusEvent
from zero_arsenal.db import get_db_conn

router = APIRouter()
logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 10     # 秒
CLIENT_RECONNECT_WINDOW = 60  # 保留最近 60 秒的事件用于补偿


@router.get("/api/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    """
    SSE 事件流端点。

    关键设计：先订阅，再返回 StreamingResponse。
    这是防止事件丢失的核心手段（来自 opencode event.ts 的经验）。
    """
    # 验证 session 存在
    db = get_db_conn()
    session = await db.fetch_one(
        "SELECT id, status FROM sessions WHERE id=?", (session_id,)
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    bus = get_event_bus()

    # ⚠️ 关键步骤：先订阅，再返回 Response
    subscriber = await bus.subscribe(session_id)

    # 处理断线重连：补偿 last_event_id 之后的历史事件
    missed_events: list[BusEvent] = []
    if last_event_id:
        missed_events = await get_events_after(session_id, last_event_id, db)
        logger.info(
            "SSE 重连 [session=%s]，Last-Event-ID=%s，补偿 %d 个事件",
            session_id, last_event_id, len(missed_events),
        )

    async def event_generator() -> AsyncIterator[str]:
        """异步生成器：产生 SSE 格式的事件流。"""

        # 第一个事件：连接确认
        connected_event = BusEvent(
            type="server.connected",
            session_id=session_id,
            data={"server_time": time.time(), "reconnected": bool(last_event_id)},
        )
        yield connected_event.to_sse()

        # 补偿历史事件（重连时）
        if missed_events:
            replay_start = BusEvent(
                type="replay.start",
                session_id=session_id,
                data={"count": len(missed_events)},
            )
            yield replay_start.to_sse()

            for event in missed_events:
                yield event.to_sse()

            replay_end = BusEvent(
                type="replay.end",
                session_id=session_id,
                data={"count": len(missed_events)},
            )
            yield replay_end.to_sse()

        # 主事件循环
        heartbeat_task = None
        try:
            # 启动心跳协程
            heartbeat_task = asyncio.create_task(
                _send_heartbeats(session_id, bus)
            )

            async for event in subscriber:
                # 检查客户端是否已断开
                if await request.is_disconnected():
                    logger.info("客户端断开 [session=%s]", session_id)
                    break

                yield event.to_sse()

                # 会话结束事件：关闭流
                if event.type == "session.done":
                    logger.info("Session 完成，关闭 SSE 流 [session=%s]", session_id)
                    break

                # 会话级错误：关闭流
                if event.type == "session.error":
                    logger.error("Session 错误，关闭 SSE 流 [session=%s]", session_id)
                    break

        except asyncio.CancelledError:
            logger.info("SSE 生成器被取消 [session=%s]", session_id)
        except Exception as e:
            logger.exception("SSE 生成器异常 [session=%s]: %s", session_id, e)
            error_event = BusEvent(
                type="session.error",
                session_id=session_id,
                data={"error": str(e), "recoverable": True},
            )
            yield error_event.to_sse()
        finally:
            # 清理：注销订阅者，取消心跳任务
            await bus.unsubscribe(session_id, subscriber.subscriber_id)
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",      # 禁止 Nginx 缓冲（关键！否则事件会被批量发送）
            "Access-Control-Allow-Origin": "*",
        },
    )


async def _send_heartbeats(session_id: str, bus: "InMemoryEventBus"):
    """
    心跳协程：每 HEARTBEAT_INTERVAL 秒向 session 发布一个 heartbeat 事件。
    在 event_generator 的 finally 中取消。
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        heartbeat = BusEvent(
            type="heartbeat",
            session_id=session_id,
            data={
                "server_time": time.time(),
                "session_active": True,
                "agent_running": False,  # 可从 AgentRunner 状态读取
            },
        )
        await bus.publish(session_id, heartbeat)


async def get_events_after(
    session_id: str,
    last_event_id: str,
    db_conn,
) -> list[BusEvent]:
    """
    从持久化日志中查询 last_event_id 之后的事件（用于断线补偿）。

    只返回最近 CLIENT_RECONNECT_WINDOW 秒内的事件，避免大量回放。
    """
    cutoff_time = time.time() - CLIENT_RECONNECT_WINDOW

    rows = await db_conn.fetch_all(
        """
        SELECT event_id, event_type, data, timestamp
        FROM event_log
        WHERE session_id=?
          AND timestamp > ?
          AND rowid > (
              SELECT rowid FROM event_log WHERE event_id=? LIMIT 1
          )
        ORDER BY timestamp ASC
        LIMIT 200
        """,
        (session_id, cutoff_time, last_event_id),
    )

    return [
        BusEvent(
            id=r["event_id"],
            type=r["event_type"],
            session_id=session_id,
            data=json.loads(r["data"]),
            timestamp=r["timestamp"],
        )
        for r in rows
    ]
```

---

## 5. 前端 SSE 客户端 TypeScript 实现

```typescript
import { useSessionStore } from "@/stores/session";
import { useAgentStore } from "@/stores/agent";
import { useNarrativeStore } from "@/stores/narrative";

// ── 事件类型定义 ─────────────────────────────────────────────────────

interface BusEventBase {
  type: string;
  session_id: string;
  timestamp: number;
}

interface PartCreatedEvent extends BusEventBase {
  type: "part.created";
  part_id: string;
  message_id: string;
  part_type: string;
  agent_name: string;
  content: string | Record<string, unknown>;
  is_streaming: boolean;
}

interface PartUpdatedEvent extends BusEventBase {
  type: "part.updated";
  part_id: string;
  delta: string;
  full_content?: string;
}

interface PartDoneEvent extends BusEventBase {
  type: "part.done";
  part_id: string;
  part_type: string;
  final_content: string | Record<string, unknown>;
  metadata: Record<string, unknown>;
}

interface PermissionAskEvent extends BusEventBase {
  type: "permission.ask";
  request_id: string;
  tool_id: string;
  agent_name: string;
  reason: string;
  args_preview: Record<string, unknown>;
  expires_at: number;
}

type AnyBusEvent = BusEventBase & Record<string, unknown>;

// ── SSEClient 类 ──────────────────────────────────────────────────────

interface SSEClientOptions {
  sessionId: string;
  baseUrl?: string;
  maxRetries?: number;
  initialRetryDelay?: number;
  maxRetryDelay?: number;
  heartbeatTimeout?: number;  // 超过此时间无事件则重连（毫秒）
}

export class SSEClient {
  private readonly sessionId: string;
  private readonly baseUrl: string;
  private readonly maxRetries: number;
  private readonly initialRetryDelay: number;
  private readonly maxRetryDelay: number;
  private readonly heartbeatTimeout: number;

  private eventSource: EventSource | null = null;
  private lastEventId: string | null = null;
  private retryCount: number = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private isManualClose: boolean = false;

  // 事件路由表：event.type → handler
  private handlers: Map<string, Array<(event: AnyBusEvent) => void>> = new Map();

  constructor(options: SSEClientOptions) {
    this.sessionId = options.sessionId;
    this.baseUrl = options.baseUrl ?? "";
    this.maxRetries = options.maxRetries ?? 10;
    this.initialRetryDelay = options.initialRetryDelay ?? 1000;   // 1秒
    this.maxRetryDelay = options.maxRetryDelay ?? 30000;           // 30秒上限
    this.heartbeatTimeout = options.heartbeatTimeout ?? 30000;    // 30秒无事件则重连
  }

  // ── 连接管理 ────────────────────────────────────────────────────────

  connect(): void {
    if (this.eventSource?.readyState === EventSource.OPEN) {
      return; // 已连接
    }

    this.isManualClose = false;
    this._openConnection();
  }

  disconnect(): void {
    this.isManualClose = true;
    this._cleanup();
  }

  private _openConnection(): void {
    const url = this._buildUrl();
    this.eventSource = new EventSource(url);

    this.eventSource.onopen = () => {
      console.log(`[SSE] 连接成功 session=${this.sessionId}`);
      this.retryCount = 0;
      this._resetHeartbeatTimer();
    };

    this.eventSource.onmessage = (rawEvent: MessageEvent) => {
      // 更新 Last-Event-ID
      if (rawEvent.lastEventId) {
        this.lastEventId = rawEvent.lastEventId;
      }

      this._resetHeartbeatTimer();

      try {
        const event = JSON.parse(rawEvent.data) as AnyBusEvent;
        this._routeEvent(event);
      } catch (e) {
        console.error("[SSE] 事件解析失败:", rawEvent.data, e);
      }
    };

    this.eventSource.onerror = (error) => {
      console.warn(`[SSE] 连接错误 session=${this.sessionId}`, error);
      this._cleanup();

      if (!this.isManualClose) {
        this._scheduleReconnect();
      }
    };
  }

  private _buildUrl(): string {
    const url = new URL(
      `${this.baseUrl}/api/sessions/${this.sessionId}/events`
    );
    if (this.lastEventId) {
      url.searchParams.set("last_event_id", this.lastEventId);
    }
    return url.toString();
  }

  // ── 心跳超时重连 ─────────────────────────────────────────────────────

  private _resetHeartbeatTimer(): void {
    if (this.heartbeatTimer) {
      clearTimeout(this.heartbeatTimer);
    }
    this.heartbeatTimer = setTimeout(() => {
      console.warn(`[SSE] ${this.heartbeatTimeout}ms 无事件，触发重连`);
      this._cleanup();
      if (!this.isManualClose) {
        this._scheduleReconnect();
      }
    }, this.heartbeatTimeout);
  }

  // ── 指数退避重连 ─────────────────────────────────────────────────────

  private _scheduleReconnect(): void {
    if (this.retryCount >= this.maxRetries) {
      console.error(`[SSE] 超过最大重试次数 (${this.maxRetries})，放弃重连`);
      this._routeEvent({
        type: "connection.failed",
        session_id: this.sessionId,
        timestamp: Date.now() / 1000,
      });
      return;
    }

    // 指数退避：delay = min(initialDelay * 2^retryCount + jitter, maxDelay)
    const jitter = Math.random() * 1000;
    const delay = Math.min(
      this.initialRetryDelay * Math.pow(2, this.retryCount) + jitter,
      this.maxRetryDelay,
    );

    console.log(
      `[SSE] ${delay.toFixed(0)}ms 后第 ${this.retryCount + 1} 次重连...`
    );

    this.retryTimer = setTimeout(() => {
      this.retryCount++;
      this._openConnection();
    }, delay);
  }

  private _cleanup(): void {
    if (this.heartbeatTimer) {
      clearTimeout(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  // ── 事件路由 ─────────────────────────────────────────────────────────

  on<T extends AnyBusEvent>(
    eventType: string,
    handler: (event: T) => void
  ): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, []);
    }
    this.handlers.get(eventType)!.push(handler as (e: AnyBusEvent) => void);

    // 返回取消订阅函数
    return () => {
      const handlers = this.handlers.get(eventType) ?? [];
      const idx = handlers.indexOf(handler as (e: AnyBusEvent) => void);
      if (idx !== -1) handlers.splice(idx, 1);
    };
  }

  private _routeEvent(event: AnyBusEvent): void {
    // 路由到精确类型处理器
    const typeHandlers = this.handlers.get(event.type) ?? [];
    for (const handler of typeHandlers) {
      try {
        handler(event);
      } catch (e) {
        console.error(`[SSE] 事件处理器异常 [type=${event.type}]:`, e);
      }
    }

    // 路由到通配处理器
    const wildcardHandlers = this.handlers.get("*") ?? [];
    for (const handler of wildcardHandlers) {
      try {
        handler(event);
      } catch (e) {
        console.error(`[SSE] 通配处理器异常:`, e);
      }
    }
  }
}

// ── Zustand Store 绑定 ───────────────────────────────────────────────

/**
 * 将 SSEClient 的事件路由到对应的 Zustand store。
 *
 * 在 session 初始化时调用一次，session 结束时 disconnect。
 */
export function bindSSEToStores(client: SSEClient): void {
  const sessionStore = useSessionStore.getState();
  const agentStore = useAgentStore.getState();
  const narrativeStore = useNarrativeStore.getState();

  // Part 创建：在 Narrative Store 中预创建 Part 条目
  client.on<PartCreatedEvent>("part.created", (event) => {
    narrativeStore.createPart({
      partId: event.part_id,
      messageId: event.message_id,
      partType: event.part_type,
      agentName: event.agent_name,
      content: typeof event.content === "string" ? event.content : JSON.stringify(event.content),
      isStreaming: event.is_streaming,
    });
  });

  // Part 流式更新：直接 DOM 操作（见 §6，避免 React re-render）
  client.on<PartUpdatedEvent>("part.updated", (event) => {
    narrativeStore.appendPartDelta(event.part_id, event.delta);
  });

  // Part 完成：最终化内容
  client.on<PartDoneEvent>("part.done", (event) => {
    narrativeStore.finalizePart(event.part_id, event.final_content, event.metadata);
  });

  // Agent 状态
  client.on("agent.started", (event) => {
    agentStore.setRunning(event.agent_name as string, true);
  });

  client.on("agent.ended", (event) => {
    agentStore.setRunning(event.agent_name as string, false);
    agentStore.recordTurnStats({
      agentName: event.agent_name as string,
      tokensUsed: event.tokens_used as number,
      durationMs: event.duration_ms as number,
    });
  });

  // 权限询问：弹出确认对话框
  client.on<PermissionAskEvent>("permission.ask", (event) => {
    sessionStore.addPermissionRequest({
      requestId: event.request_id,
      toolId: event.tool_id,
      agentName: event.agent_name,
      reason: event.reason,
      argsPreview: event.args_preview,
      expiresAt: event.expires_at,
    });
  });

  // 会话结束
  client.on("session.done", () => {
    sessionStore.setStatus("done");
    client.disconnect();
  });

  // 心跳：更新连接状态
  client.on("heartbeat", (event) => {
    sessionStore.updateHeartbeat({
      serverTime: event.server_time as number,
      agentRunning: event.agent_running as boolean,
    });
  });
}
```

---

## 6. 流式正文差分渲染

### 6.1 问题背景

流式 LLM 输出每次只产生几个 token，如果每个 `part.updated` 事件都触发 React 重新渲染，100 token/秒的输出会造成 100 次/秒的 re-render，严重影响性能。

**来自 pi TUI 的差分思想**：使用 `useRef` 持有 DOM 节点，通过 `textContent` 直接 append，完全绕过 React 虚拟 DOM diffing。

### 6.2 NarrativePart 组件实现

```tsx
import React, { useRef, useEffect, useCallback, memo } from "react";
import { useNarrativeStore } from "@/stores/narrative";
import { marked } from "marked";

interface NarrativePartProps {
  partId: string;
  initialContent?: string;
  isStreaming?: boolean;
  agentName?: string;
}

/**
 * 流式叙事 Part 组件。
 *
 * 核心优化：
 * 1. streaming=true 时，使用 ref 直接操作 DOM，不触发 re-render
 * 2. streaming=false（或 done）时，才用 React state 更新（Markdown 渲染）
 * 3. 使用 memo 防止父组件 re-render 时无谓的子组件渲染
 */
export const NarrativePart = memo(function NarrativePart({
  partId,
  initialContent = "",
  isStreaming = true,
  agentName = "narrator",
}: NarrativePartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const streamBufferRef = useRef<string>(initialContent);
  const isDoneRef = useRef<boolean>(!isStreaming);

  // 订阅 Part 完成事件（只在 done 时触发一次 re-render）
  const finalContent = useNarrativeStore(
    useCallback((state) => state.parts[partId]?.finalContent, [partId])
  );

  // 注册 delta append 处理器（直接 DOM 操作，零 re-render）
  useEffect(() => {
    if (!isStreaming) return;

    const unsubscribe = useNarrativeStore.subscribe(
      (state) => state.parts[partId]?.lastDelta,
      (delta: string | undefined) => {
        if (!delta || isDoneRef.current) return;

        // 直接操作 DOM，不经过 React
        const container = containerRef.current;
        if (container) {
          streamBufferRef.current += delta;
          // 使用 textContent 进行纯文本追加（最快）
          // 若需要实时 Markdown 渲染，改用 innerHTML + marked.parseInline(delta)
          const lastTextNode = container.lastChild;
          if (lastTextNode && lastTextNode.nodeType === Node.TEXT_NODE) {
            lastTextNode.textContent = (lastTextNode.textContent ?? "") + delta;
          } else {
            container.appendChild(document.createTextNode(delta));
          }
        }
      }
    );

    return unsubscribe;
  }, [partId, isStreaming]);

  // Part 完成：用最终内容替换流式缓冲区（触发一次 re-render + Markdown 渲染）
  useEffect(() => {
    if (finalContent !== undefined && !isDoneRef.current) {
      isDoneRef.current = true;

      // 清空容器，用完整渲染的 Markdown 替换
      const container = containerRef.current;
      if (container) {
        const htmlContent = marked.parse(
          typeof finalContent === "string"
            ? finalContent
            : JSON.stringify(finalContent, null, 2)
        ) as string;
        container.innerHTML = htmlContent;
      }
    }
  }, [finalContent]);

  // 初始渲染：显示占位符或已有内容
  return (
    <div
      className={`narrative-part narrative-part--${agentName} ${isStreaming ? "is-streaming" : ""}`}
      data-part-id={partId}
    >
      <div
        ref={containerRef}
        className="narrative-part__content"
        aria-live="polite"
        aria-atomic={false}
      >
        {/* 初始内容由 ref 管理，React 不干预此 div 内部 */}
        {initialContent}
      </div>
      {isStreaming && (
        <span className="narrative-part__cursor" aria-hidden="true">▋</span>
      )}
    </div>
  );
});

// ── Zustand Store slice（配合组件使用）────────────────────────────────

interface PartState {
  partId: string;
  messageId: string;
  partType: string;
  agentName: string;
  content: string;
  isStreaming: boolean;
  lastDelta?: string;
  finalContent?: string | Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

interface NarrativeSlice {
  parts: Record<string, PartState>;
  createPart: (part: Omit<PartState, "lastDelta" | "finalContent" | "metadata">) => void;
  appendPartDelta: (partId: string, delta: string) => void;
  finalizePart: (
    partId: string,
    finalContent: string | Record<string, unknown>,
    metadata: Record<string, unknown>
  ) => void;
}

// Zustand store 实现（使用 immer）
export const createNarrativeSlice = (set: any): NarrativeSlice => ({
  parts: {},

  createPart: (part) =>
    set((state: any) => {
      state.parts[part.partId] = { ...part };
    }),

  appendPartDelta: (partId, delta) =>
    set((state: any) => {
      if (state.parts[partId]) {
        state.parts[partId].lastDelta = delta;
        state.parts[partId].content += delta;
      }
    }),

  finalizePart: (partId, finalContent, metadata) =>
    set((state: any) => {
      if (state.parts[partId]) {
        state.parts[partId].isStreaming = false;
        state.parts[partId].finalContent = finalContent;
        state.parts[partId].metadata = metadata;
        state.parts[partId].lastDelta = undefined;
      }
    }),
});
```

### 6.3 性能对比

| 方案 | 100 token/秒时的 re-render 次数 | 内存分配 | 首字延迟 |
|---|---|---|---|
| `useState` 直接更新 | ~100 次/秒 | 高（每次创建新字符串） | 低 |
| `useRef` + DOM 直操 | 0 次（streaming 期间） | 极低 | 极低 |
| `useRef` + requestAnimationFrame 批处理 | ~60 次/秒 | 低 | 极低 |

**推荐**：使用 `useRef` + DOM 直操（方案二），streaming 期间零 re-render，`part.done` 时执行一次完整 Markdown 渲染。

---

## 7. 事件持久化策略

### 7.1 设计目标

- **页面刷新重建**：刷新后通过重放历史事件恢复 UI 状态
- **精确补偿**：断线重连时只补发 `Last-Event-ID` 之后的事件
- **存储效率**：不永久保存所有事件，按时间窗口清理

### 7.2 数据库表结构

> ⚠️ **实现列名对齐（2026-06）**：实际表（`backend/db/schema.py`）列名与下列草案不同，且**无 `size_bytes`**。
> 以下为实现版（读写代码 `event_bus.py` 与之自洽）：

```sql
-- 实现版（backend/db/schema.py）
CREATE TABLE IF NOT EXISTS event_log (
    id          TEXT PRIMARY KEY,    -- = BusEvent.id（UUID）
    session_id  TEXT NOT NULL,
    type        TEXT NOT NULL,       -- 事件类型（草案曾名 event_type）
    data_json   TEXT,                -- JSON 序列化的 event.data（草案曾名 data）
    created_at  REAL NOT NULL        -- 事件时间戳（草案曾名 timestamp）
    -- 无 size_bytes 字段
);

CREATE INDEX idx_eventlog_session ON event_log (session_id, created_at);

-- 自动清理：保留最近 7 天的事件
-- 实现位置：backend/main.py 的 _event_log_cleanup_loop（每天 04:00 DELETE，见 §7.3 注）
```

### 7.3 事件持久化写入器

> ⚠️ **实现差异（2026-06）**：实际**无独立 `EventLogWriter` 批量写入器**。`EventBus.publish` 内对每个事件 `asyncio.create_task(self._persist_event(event))` 逐条 `INSERT OR IGNORE`（无批处理，失败静默吞掉）；7 天清理由 `backend/main.py` 的 `_event_log_cleanup_loop` 后台循环执行（非下方静态方法）；`SKIP_TYPES` 实际仅 `{heartbeat}`（`server.connected`/`replay.*` 因从不经 `bus.publish` 故也不会持久化，结果等效）。下方为草案，保留供对照。

```python
class EventLogWriter:
    """
    监听 EventBus，将所有事件持久化到 SQLite。

    作为特殊的"订阅者"接入 EventBus，不影响正常 SSE 推送。
    """

    # 不持久化的事件类型（频率高但无状态重建价值）
    SKIP_TYPES = {"heartbeat", "server.connected", "replay.start", "replay.end"}

    def __init__(self, db_conn, bus: InMemoryEventBus):
        self._db = db_conn
        self._bus = bus
        self._write_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._worker_task: asyncio.Task | None = None

    async def start(self, session_id: str):
        """开始监听指定 session 的事件并异步写入 DB。"""
        subscriber = await self._bus.subscribe(session_id)
        self._worker_task = asyncio.create_task(
            self._write_worker(subscriber)
        )

    async def _write_worker(self, subscriber: BusSubscriber):
        """后台写入协程：批量写入，减少 DB 操作次数。"""
        batch: list[BusEvent] = []
        BATCH_SIZE = 20
        FLUSH_INTERVAL = 1.0  # 最多等待 1 秒

        async for event in subscriber:
            if event.type in self.SKIP_TYPES:
                continue

            batch.append(event)

            if len(batch) >= BATCH_SIZE:
                await self._flush_batch(batch)
                batch = []

        # 处理剩余批次
        if batch:
            await self._flush_batch(batch)

    async def _flush_batch(self, events: list[BusEvent]):
        """批量写入事件到 DB。"""
        rows = [
            (
                e.id,
                e.session_id,
                e.type,
                json.dumps(e.data, ensure_ascii=False),
                e.timestamp,
                len(json.dumps(e.data).encode()),
            )
            for e in events
        ]
        await self._db.executemany(
            """
            INSERT OR IGNORE INTO event_log
                (event_id, session_id, event_type, data, timestamp, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    @staticmethod
    async def cleanup_old_events(db_conn, max_age_days: int = 7):
        """清理过期事件（由定时任务调用）。"""
        cutoff = time.time() - max_age_days * 86400
        result = await db_conn.execute(
            "DELETE FROM event_log WHERE timestamp < ?",
            (cutoff,),
        )
        return result.rowcount
```

### 7.4 页面刷新后的状态重建

```typescript
/**
 * 页面刷新后，从服务端重建 UI 状态。
 *
 * 策略：连接 SSE 时服务端发送 "replay.start" → 历史事件 → "replay.end"，
 * 前端 SSEClient 按正常路由处理，自动重建 Zustand store 状态。
 */
async function rebuildSessionState(sessionId: string): Promise<void> {
  const client = new SSEClient({
    sessionId,
    // lastEventId 为 null → 服务端从头回放（仅最近 60 秒）
    // lastEventId 为已知值 → 只补发增量
  });

  return new Promise((resolve) => {
    const unsubscribe = client.on("replay.end", () => {
      unsubscribe();
      resolve();
    });

    client.on("session.done", () => {
      unsubscribe();
      resolve();
    });

    bindSSEToStores(client);
    client.connect();
  });
}
```

---

## 8. Heartbeat 机制

### 8.1 设计

| 参数 | 值 | 说明 |
|---|---|---|
| 服务端发送间隔 | 10 秒 | `HEARTBEAT_INTERVAL = 10` |
| 前端无事件超时 | 30 秒 | `heartbeatTimeout = 30000` |
| 超时后动作 | 立即重连（带 Last-Event-ID） | 指数退避 |

### 8.2 Heartbeat 事件内容

```python
# 服务端每 10 秒推送
heartbeat_event = BusEvent(
    type="heartbeat",
    session_id=session_id,
    data={
        "server_time": time.time(),
        "session_active": True,
        "agent_running": agent_runner.is_running(session_id),
        # 可选：添加轻量级状态摘要
        "current_chapter": await get_current_chapter(session_id),
        "active_agent": agent_runner.get_active_agent(session_id),
    },
)
```

### 8.3 前端心跳超时处理

```typescript
// 在 SSEClient 内部（见 §5 实现）
private _resetHeartbeatTimer(): void {
  clearTimeout(this.heartbeatTimer!);
  this.heartbeatTimer = setTimeout(() => {
    // 30 秒无任何事件（包括心跳）→ 连接已死，触发重连
    console.warn("[SSE] Heartbeat timeout, reconnecting...");
    this._cleanup();
    this._scheduleReconnect();  // 带指数退避
  }, this.heartbeatTimeout);
}

// 每收到任何事件（含心跳）都重置计时器
this.eventSource.onmessage = (rawEvent) => {
  this._resetHeartbeatTimer();  // ← 这里重置
  // ...处理事件
};
```

---

## 9. 错误处理与断线重连

### 9.1 错误分类与处理策略

| 错误场景 | 前端表现 | 处理策略 |
|---|---|---|
| 网络短暂中断（<30s） | 心跳超时，自动重连 | 指数退避，Last-Event-ID 补偿 |
| 服务器重启 | EventSource.onerror | 延迟重连，通知用户 |
| Session 不存在 | HTTP 404 | 停止重连，跳转到错误页 |
| 超过最大重试次数 | connection.failed 事件 | 显示"连接失败"提示，提供手动重连按钮 |
| 服务端 session.error 事件 | 显示错误提示 | 根据 recoverable 决定是否自动重连 |

### 9.2 重连时序图

```
Client                    Server
  │                          │
  │──── GET /events ─────────►│ (连接 A，正常工作)
  │◄─── SSE 流 ───────────────│
  │◄─── event: id=100 ────────│
  │◄─── event: id=101 ────────│
  │                          │
  │  [网络中断]               │ (id=102 发出但客户端未收到)
  │  ×──────────────────────× │
  │                          │
  │──── GET /events ─────────►│ (重连，带 Last-Event-ID: 101)
  │    Last-Event-ID: 101     │
  │◄─── replay.start ─────────│
  │◄─── event: id=102 ────────│ (补偿丢失事件)
  │◄─── replay.end ───────────│
  │◄─── 继续新事件 ────────────│
```

---

## 10. 测试策略

### 10.1 EventBus 单元测试

```python
import pytest
import asyncio


@pytest.mark.asyncio
async def test_publish_before_subscribe_safety():
    """验证先发布后订阅不会收到旧事件（正确行为）。"""
    bus = InMemoryEventBus()

    # 先发布
    event = BusEvent(type="test", session_id="s1", data={"msg": "before"})
    await bus.publish("s1", event)

    # 再订阅
    subscriber = await bus.subscribe("s1")

    # 新事件
    new_event = BusEvent(type="test", session_id="s1", data={"msg": "after"})
    await bus.publish("s1", new_event)

    received = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
    assert received.data["msg"] == "after"  # 不应收到 "before"


@pytest.mark.asyncio
async def test_subscribe_before_publish_no_loss():
    """验证先订阅后发布零丢失（核心保证）。"""
    bus = InMemoryEventBus()
    subscriber = await bus.subscribe("s1")

    events = [BusEvent(type="test", session_id="s1", data={"i": i}) for i in range(5)]
    for e in events:
        await bus.publish("s1", e)

    received = []
    for _ in range(5):
        e = await asyncio.wait_for(subscriber.queue.get(), timeout=1.0)
        received.append(e.data["i"])

    assert received == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_fan_out_to_multiple_subscribers():
    """验证 fan-out：多个订阅者都能收到事件。"""
    bus = InMemoryEventBus()
    sub1 = await bus.subscribe("s1")
    sub2 = await bus.subscribe("s1")

    event = BusEvent(type="test", session_id="s1", data={"msg": "hello"})
    await bus.publish("s1", event)

    e1 = await asyncio.wait_for(sub1.queue.get(), timeout=1.0)
    e2 = await asyncio.wait_for(sub2.queue.get(), timeout=1.0)

    assert e1.data["msg"] == "hello"
    assert e2.data["msg"] == "hello"
```

### 10.2 SSE 端点集成测试

```python
@pytest.mark.asyncio
async def test_sse_subscribe_before_response():
    """
    验证 SSE handler 在返回 Response 之前已建立订阅。

    使用 httpx AsyncClient 发送并发请求：
    1. 请求 SSE 端点
    2. 立即触发 Agent（会发布事件）
    3. 验证 SSE 流收到了所有事件
    """
    from httpx import AsyncClient

    async with AsyncClient(app=app, base_url="http://test") as client:
        # 建立 SSE 连接（后台）
        sse_task = asyncio.create_task(
            collect_sse_events(client, "/api/sessions/test-001/events", timeout=5.0)
        )

        # 短暂等待（确保连接建立）
        await asyncio.sleep(0.05)

        # 触发事件
        await get_event_bus().publish("test-001", BusEvent(
            type="test.event",
            session_id="test-001",
            data={"value": 42},
        ))
        await get_event_bus().publish("test-001", BusEvent(
            type="session.done",
            session_id="test-001",
            data={},
        ))

        events = await sse_task

    event_types = [e["type"] for e in events]
    assert "server.connected" in event_types
    assert "test.event" in event_types
    assert "session.done" in event_types
```
