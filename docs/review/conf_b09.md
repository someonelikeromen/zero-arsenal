# 设计符合度审计 · B09 — 事件总线 / SSE

> 审计对象：`docs/design/09-event-bus-sse.md`（标注「设计稿，待实现」）
> 核对实现：`backend/bus/*`、`backend/api/routers/stream.py`、`frontend/src/lib/sse.ts`、`frontend/src/lib/bindSSEToStores.ts`
> 复审基准日期：2026-06-03
> **总体结论**：文档虽标「待实现」，实则**核心链路已全量落地并接线生效**（先订阅后响应、SSE 端点、前端续传、内存+DB 持久化、7 天清理）。主要差距集中在 **(a) 设计文档自身前后不一致（§2.1 接口 vs §2.2 样例）**、**(b) `to_sse` 载荷结构（嵌套 data） / 字段命名（agent / content）全栈一致地偏离设计**、**(c) Redis 实现存在 3 处实质缺陷使多进程能力名存实亡**。

---

## §1 设计来源与核心思想（先订阅，再返回 Response）

### §1.2 竞态：先订阅再返回 StreamingResponse
- 设计要求：「订阅在 Response 返回前建立，保证零丢失」。
- 实现状态：完整
- 证据：`backend/bus/sse_adapter.py:78`（`subscription = await bus.subscribe(...)` 在构造 `_generator()` 与返回 `StreamingResponse` 之前执行）；`sse_adapter.py:129-134`。
- 差距：无。
- 处置：无需动作。

---

## §2 Bus 接口设计（IEventBus）

### §2.1 `publish(event)`（session_id 内嵌 BusEvent）
- 设计要求：`publish(event)`，session_id 内嵌于 BusEvent（非 `publish(session_id, event)`）。
- 实现状态：完整
- 证据：`backend/bus/interface.py:37` `async def publish(self, event: "BusEvent")`；`event_bus.py:45` 同签名，`event.session_id` 路由（:56）。
- 差距：无。
- 处置：无需动作。

### §2.1 `subscribe(session_id) -> Subscription`
- 设计要求：返回 Subscription 对象，必须在 Response 前调用。
- 实现状态：完整
- 证据：`interface.py:42`；`event_bus.py:106-117` 返回 `Subscription`。
- 差距：无。
- 处置：无需动作。

### §2.1 `unsubscribe(session_id, queue)`（第二参为 queue 对象）
- 设计要求：第二参数为 queue 对象，非 subscriber_id 字符串。
- 实现状态：完整
- 证据：`interface.py:50` `unsubscribe(self, session_id, queue: object)`；`event_bus.py:119` `queue: asyncio.Queue`，`Subscription.close()` 调用（:218-220）。
- 差距：无。
- 处置：无需动作。

### §2.1 `get_subscriber_count()` 非 abstract，默认 -1，具体实现返回精确值
- 设计要求：IEventBus 默认返回 -1（同步方法），EventBus 返回精确值。
- 实现状态：完整
- 证据：`interface.py:56-62`（默认 `return -1`，非 abstract）；`event_bus.py:125-130`（`return len(self._subscribers.get(...))`）。
- 差距：无。注意设计 §2.2 样例把它写成 `async def get_subscriber_count`（异步），与 §2.1 矛盾；实现取 §2.1 的同步版（正确）。
- 处置：补/改设计文档（删除 §2.2 过时异步样例）。

### §2 接口新增的 abstract 方法（设计未列出）
- 设计要求：§2.1 接口仅含 publish/subscribe/unsubscribe/get_subscriber_count。
- 实现状态：偏离（向上扩展）
- 证据：`interface.py:64-74` 新增 **abstract** `get_events_after()` 与 `get_events_after_from_db()`；:78-120 新增默认实现的语义化快捷方法 `publish_part_created/_delta/_done/_agent/_session_done`。
- 差距：实现的接口比设计宽；扩展本身合理（续传/便捷发布），但设计文档未登记，导致「设计权威」与代码不一致。
- 处置：补/改设计文档（把续传与语义化发布方法纳入 §2 接口）。

### §2.2 InMemoryEventBus 样例代码（类名 / BusSubscriber / 心跳协程）
- 设计要求：类名 `InMemoryEventBus`、订阅者为 `BusSubscriber`（含 subscriber_id、哨兵 None 退出）、`publish(session_id, event)`。
- 实现状态：偏离
- 证据：实现类名为 `EventBus`（`event_bus.py:29`），订阅对象为 `Subscription`（:196，无 subscriber_id）；`Subscription.__aiter__` 用 `wait_for(timeout=10)` 在空闲时**自产 heartbeat**（:205-216），而非哨兵 None。
- 差距：§2.2 整段样例与实际实现签名/类名/退出机制均不符（§2.2 自身还与 §2.1 矛盾，如 `publish(session_id, event)`）。实现以 §2.1 为准，§2.2 属过时草案。
- 处置：补/改设计文档（重写或删除 §2.2 样例，统一到实现）。

---

## §3 BusEvent 类型定义

### §3.1 BusEvent 基础字段（type/session_id/data/id/timestamp）
- 设计要求：dataclass 含 type、session_id、data、自动 id(uuid)、timestamp。
- 实现状态：完整
- 证据：`backend/bus/event_types.py:43-50`，字段与默认工厂一致（timestamp 用 `datetime.now().timestamp()`，设计用 `time.time()`，等价）。
- 差距：无实质差距。
- 处置：无需动作。

### §3.1 `to_sse()` 载荷结构（扁平 vs 嵌套 data）
- 设计要求：`payload = {"type", "session_id", "timestamp", **self.data}`（data 字段**展开到顶层**）。
- 实现状态：偏离（全栈一致地改为嵌套）
- 证据：`event_types.py:57-66` 用 `"data": self.data`（**嵌套**，不展开）；前端 `sse.ts:6-9` `BusEvent { type; data }` 与 `bindSSEToStores.ts:68` `e.data as {...}` 均按嵌套读取。
- 差距：后端发、前端收都用嵌套，自洽且能工作；但与设计 §3.1（后端展开）和 §5（前端读 `event.part_id` 顶层）双双不符。
- 处置：补/改设计文档（§3.1 to_sse 与 §5 前端类型统一为嵌套 `data`）。

### §3.1 EVENT_TYPES 全集逐一对照
- 设计要求：20 个类型（session.started/done/error、agent.started/ended/error、turn.started/ended、part.created/updated/done/error、permission.ask/granted/denied、heartbeat、server.connected、replay.start/end）。
- 实现状态：完整（全覆盖）+ 扩展
- 证据：`event_types.py:16-40` 逐一核对：设计 20 个类型**全部存在**。额外新增 4 个：`session.idle`(:20)、`session.mode_changed`(:22)、`chapter.consolidated`(:35)、`turn.complete`(:36)。
- 差距：仅多不少。`turn.complete` 与 `turn.ended` 并存（语义区分：anchor 写入 vs 回合结束），设计未登记新增的 4 个类型。
- 处置：补/改设计文档（把 4 个新增类型补入 §3.1 枚举）。

### §3.2 各事件 data 字段命名（agent / content 等）
- 设计要求：part.created data 含 `agent_name`、`content`、`is_streaming`；part.done 含 `final_content`、`metadata`、`should_memorize`；part.updated 含 `full_content`。
- 实现状态：偏离
- 证据：`interface.py:84-87` `publish_part_created` 发 `{part_id, part_type, message_id, agent}`（用 **`agent`** 非 `agent_name`，无 content/is_streaming）；:98-105 `publish_part_done` 发 `{part_id, content}`（用 **`content`** 非 `final_content`，无 metadata/should_memorize）；前端 `bindSSEToStores.ts:68/88` 按 `agent`、`content` 读取（与实现自洽）。
- 差距：字段命名与设计 §3.2 不一致（agent↔agent_name、content↔final_content），且省略了 is_streaming / metadata / should_memorize 等设计字段；前后端一致工作。
- 处置：补/改设计文档（§3.2 字段名对齐实现）。

---

## §4 SSE 端点实现

### §4 server.connected 首事件
- 设计要求：第一个事件为 `server.connected`（含 id: 行作为续传基线）。
- 实现状态：完整
- 证据：`sse_adapter.py:82-86` 首先 `yield BusEvent(type=SERVER_CONNECTED,...).to_sse()`。
- 差距：设计的 `data:{server_time, reconnected}` 实现为空 `data:{}`（:85）。轻微。
- 处置：补实现（可选，补 server_time/reconnected 字段）。

### §4 断线补偿（replay.start → 事件 → replay.end）
- 设计要求：last_event_id 命中后发 replay.start、逐条重放、replay.end。
- 实现状态：完整
- 证据：`sse_adapter.py:31-59`（内存 `get_events_after`(:41) 未命中再 DB `get_events_after_from_db`(:43)，包 replay.start/end）。
- 差距：无实质差距（设计 §4 仅查内存 missed，实现额外加了 DB fallback，更强）。
- 处置：无需动作。

### §4 Last-Event-ID（Header + query 兜底）
- 设计要求：`Last-Event-ID` Header 读取。
- 实现状态：完整（超设计）
- 证据：`stream.py:311` `Header(None, alias="Last-Event-ID")`；:327 `last_event_id or request.query_params.get("last_event_id")`（query 兜底，因 EventSource 无法设自定义 Header，必要补强）。
- 差距：无。
- 处置：无需动作。

### §4 session.done / session.error / 客户端断开 → 关流
- 设计要求：session.done 关流、session.error 关流、`request.is_disconnected()` 关流。
- 实现状态：完整（精化）
- 证据：`sse_adapter.py:106` done 关流；:109-111 session.error 仅当 `recoverable=False` 关流（比设计「任何 error 关流」更细，与 stream.py:173 发 `recoverable:True` 配套）；:97-102 断开检测。`session.idle` 不关流（:75 注释，等待下一轮），符合多回合常驻设计。
- 差距：与设计 §4 略有精化（error 按 recoverable 决定），属合理增强。
- 处置：补/改设计文档（说明 recoverable 关流策略）。

### §4 心跳：独立 `_send_heartbeats` 协程 vs 订阅迭代器超时自产
- 设计要求：`asyncio.create_task(_send_heartbeats)` 每 10s 向 bus.publish heartbeat，finally 取消。
- 实现状态：偏离
- 证据：实现**无** `_send_heartbeats` 协程；改由 `Subscription.__aiter__` 在 `queue.get()` 超时 10s 时**就地 yield heartbeat**（`event_bus.py:208-216`）。
- 差距：效果近似（无事件即每 10s 心跳），但语义不同——设计向全体订阅者广播心跳，实现仅在该订阅者队列空闲时本地产生（更省、无 fan-out 浪费），不经 bus.publish 故不入 event_log。
- 处置：补/改设计文档（§4/§8 改述为「订阅迭代器空闲超时自产心跳」）。

### §4 SSE 响应头
- 设计要求：`Cache-Control:no-cache`、`Connection:keep-alive`、`X-Accel-Buffering:no`、`Access-Control-Allow-Origin:*`。
- 实现状态：部分
- 证据：`sse_adapter.py:24-28` 含前三项，**缺** `Access-Control-Allow-Origin`。
- 差距：CORS 头缺失（大概率由全局 CORSMiddleware 统一处理，但未在此显式声明）。
- 处置：补实现（如确需，显式补 ACAO）或补设计文档说明 CORS 走中间件。

### §4 get_events_after DB 查询（窗口/锚点定位）
- 设计要求：`rowid > (subquery by event_id)` + timestamp 窗口 + LIMIT 200。
- 实现状态：完整（等价实现）
- 证据：`event_bus.py:150-190` 先查锚点 `created_at`，再取 `created_at > anchor AND <= anchor+60s` ORDER BY ASC LIMIT。
- 差距：用时间窗口替代 rowid 子查询，语义等价；同 created_at 的并发事件存在边界细节但风险低。
- 处置：无需动作。

---

## §5 前端 SSE 客户端

### §5 EventSource + 续传 URL
- 设计要求：EventSource 连接，断线带 Last-Event-ID 重连。
- 实现状态：完整（超设计）
- 证据：`sse.ts:70` `new EventSource(url)`；:60-66 query param 携带 lastEventId；:41-51/72-79 额外用 IndexedDB 持久化/恢复 lastEventId（刷新续传，超出设计）。
- 差距：无（增强）。
- 处置：无需动作。

### §5 指数退避（jitter / 上限 / 最大重试）
- 设计要求：`delay = min(initial*2^retry + jitter, maxDelay)`，maxRetries=10，maxDelay=30000。
- 实现状态：部分
- 证据：`sse.ts:95` `Math.min(30000, 1000 * 2 ** retryCount)`（**无 jitter**）；:22 `maxRetry = 8`（设计 10）。
- 差距：缺 jitter（多客户端可能同步重连惊群）；maxRetry 8 vs 10（轻微）。
- 处置：补实现（加 jitter）或补/改设计文档（确认参数）。

### §5 心跳超时 30s 触发重连
- 设计要求：`heartbeatTimeout=30000`，任何事件重置计时器，超时重连。
- 实现状态：完整
- 证据：`sse.ts:14` `HEARTBEAT_TIMEOUT_MS=30_000`；:81 `onmessage` 重置；:114-125 超时 `_connect()`。
- 差距：无。
- 处置：无需动作。

### §5 超过最大重试 → connection.failed 事件
- 设计要求：超 maxRetries 时 `_routeEvent({type:"connection.failed"})` 供 UI 提示「手动重连」。
- 实现状态：缺失
- 证据：`sse.ts:94` 条件 `retryCount < maxRetry` 不满足时**直接静默停止**，无 connection.failed 派发，无 UI 通知。
- 差距：连接彻底失败后用户无提示/无手动重连入口（设计 §9 表列明此场景）。
- 处置：补实现（达上限时派发 connection.failed 事件 + UI Toast/重连按钮）。

### §5 事件路由（精确类型 + 通配 `*`）
- 设计要求：`on(type, handler)` + `*` 通配处理。
- 实现状态：完整
- 证据：`sse.ts:30-39`（on/onAny）；:107-112 `_dispatch` 先精确后通配。
- 差距：无。
- 处置：无需动作。

### §5 bindSSEToStores（事件→Store 绑定）
- 设计要求：`bindSSEToStores(client)` 内部 `client.on(...)` 绑定 part.created/updated/done、permission.ask、agent.started/ended、session.done、heartbeat 到 Zustand store。
- 实现状态：部分 / 偏离（结构不同）
- 证据：实现为 `createSSEHandler(deps)` 工厂返回 `onEvent` switch（`bindSSEToStores.ts:53-196`），依赖注入而非直接 import store。覆盖 part.created/updated/done(:67-123)、permission.ask/granted/denied(:126-137)、agent.started/ended(:140-149)、session.idle/error/mode_changed(:152-176)、turn.complete(:179)、chapter.consolidated(:185)。
- 差距：(1) 函数名/形态与设计不同（工厂 vs 直接绑定）；(2) **未处理 `session.done`**（实现用 `session.idle` 解除 sending，:152），也未处理 `heartbeat`（心跳由 SSEClient 内部消费）；(3) 设计的 agent.ended 记录 token/duration 统计在实现中未做（仅清 activeAgent）。
- 处置：补/改设计文档（§5 改述为 createSSEHandler 工厂 + session.idle 语义）；按需补 session.done 处理。

---

## §6 流式正文差分渲染（NarrativePart useRef DOM 直操）

### §6.2 streaming 期间零 re-render（ref 直接 append）
- 设计要求：NarrativePart 用 `useRef`+`textContent` 直接 append delta，绕过 React diff，done 时一次性 Markdown 渲染。
- 实现状态：部分（本分片范围外，仅证实数据通路存在）
- 证据：`bindSSEToStores.ts:81-85` `part.updated → appendDelta(part_id, delta)`，:76 `streamBuffer` 仅 narrative 维护；NarrativePart 组件本身不在本分片审计文件清单内（属 §B 其他前端分片）。
- 差距：delta→store 通路已通；DOM 直操优化是否落地需由前端组件分片核实。
- 处置：移交前端组件分片核实 `NarrativePart` 的 useRef 实现。

---

## §7 事件持久化策略

### §7.2 event_log 表结构（列名 / size_bytes）
- 设计要求：列 `event_id, session_id, event_type, data, timestamp, size_bytes` + 两个索引。
- 实现状态：偏离（列名不同，内部自洽）
- 证据：`backend/db/schema.py:159-166` 实际列为 `id, session_id, type, data_json, created_at`（**无 size_bytes**），索引 `idx_eventlog_session(session_id, created_at)`；写入 `event_bus.py:91-93` 与之一致。
- 差距：列名全部不同于设计（event_id→id、event_type→type、data→data_json、timestamp→created_at），缺 size_bytes 容量监控字段；实现 schema 与读写代码自洽。
- 处置：补/改设计文档（§7.2 schema 对齐实现列名）。

### §7.3 EventLogWriter 批量异步写入
- 设计要求：独立 `EventLogWriter` 作为特殊订阅者，批量（BATCH_SIZE=20 / FLUSH_INTERVAL=1s）写 DB。
- 实现状态：偏离
- 证据：实现**无** EventLogWriter；改为 `publish` 内对每个事件 `asyncio.create_task(self._persist_event(event))`（`event_bus.py:82-83`），逐条 `INSERT OR IGNORE`（:85-104），无批处理。
- 差距：高频事件下每事件一个 task + 一次 DB 写，无批量合并；失败静默吞掉（:103-104）。功能达成（持久化生效）但效率/形态偏离设计。
- 处置：补/改设计文档，或按需补实现批量写入。

### §7.3 / §7.2 7 天清理
- 设计要求：保留最近 7 天事件，定时清理。
- 实现状态：完整（位置不同）
- 证据：`backend/main.py:248-275` `_event_log_cleanup_loop` 每天 04:00 `DELETE FROM event_log WHERE created_at < cutoff`（7 天）；内存日志另裁剪至 1000 条（`event_bus.py:53`）。
- 差距：设计写成 `EventLogWriter.cleanup_old_events` 静态方法，实现改为 main.py 后台循环——位置不同但目标达成。
- 处置：补/改设计文档（清理实现位置）。

### §7.1 SKIP_TYPES（不持久化类型）
- 设计要求：跳过 `{heartbeat, server.connected, replay.start, replay.end}`。
- 实现状态：部分（等效）
- 证据：`event_bus.py:26` `_NO_PERSIST_TYPES = {HEARTBEAT}` 仅含 heartbeat。
- 差距：server.connected/replay.* 未列入跳过表，但这些事件在 `sse_adapter` 内直接 yield、从不经 `bus.publish`，故实际也不会被持久化；心跳由订阅迭代器自产同样不经 publish。结果等效。
- 处置：无需动作（或补设计文档说明这些事件不入 bus）。

---

## §8 Heartbeat 机制

### §8.1 间隔参数（服务端 10s / 前端 30s）
- 设计要求：服务端 10s 发、前端 30s 超时重连。
- 实现状态：完整
- 证据：服务端 `event_bus.py:208` `wait_for(..., timeout=10.0)` 触发心跳；前端 `sse.ts:14` 30s。
- 差距：无。
- 处置：无需动作。

### §8.2 Heartbeat 事件内容（session_active / agent_running / 状态摘要）
- 设计要求：heartbeat data 含 `server_time, session_active, agent_running`（+ 可选 current_chapter/active_agent）。
- 实现状态：部分
- 证据：`event_bus.py:212-216` heartbeat data 仅 `{server_time}`，**缺 session_active / agent_running / 状态摘要**。
- 差距：前端无法从心跳感知 agent 运行态（设计 §5 `updateHeartbeat({agentRunning})` 无数据来源）。
- 处置：补实现（心跳注入 agent_running 等）或补/改设计文档下调心跳内容。

---

## §9 错误处理与断线重连

### §9.1 错误分类处理（404 / recoverable / 超限）
- 设计要求：Session 不存在→404 停重连；session.error 按 recoverable；超限→connection.failed。
- 实现状态：部分
- 证据：`stream.py:322-325` 404/410；`sse_adapter.py:109-111` recoverable 关流；前端超限处理**缺失**（见 §5 connection.failed 条）。
- 差距：超限分支无 connection.failed/UI 提示；404 在 EventSource 下会触发 onerror 持续重试（前端无法读 HTTP 状态码，将盲目退避重连到 maxRetry），与设计「停止重连跳错误页」不符。
- 处置：补实现（前端区分 4xx 终止重连 + 超限派发 connection.failed）。

---

## §10 测试策略

### §10.1/§10.2 EventBus 单测 + SSE 集成测试
- 设计要求：`test_publish_before_subscribe_safety`、`test_subscribe_before_publish_no_loss`、`test_fan_out_to_multiple_subscribers`、`test_sse_subscribe_before_response`。
- 实现状态：缺失
- 证据：`tests/` 下检索 `subscribe|EventBus|make_sse` 无任何匹配（仅 design 文档自身含这些样例）。
- 差距：核心「零丢失/先订阅」保证无回归测试守护。
- 处置：补实现（落地 §10 四个用例）。

---

## Redis 多进程能力（设计承诺 vs 实际 + C7 复核）

### Redis publish/subscribe/ZSET 续传 基础结构
- 设计要求：§1.3/§8 多进程经 Redis Pub/Sub fan-out + ZSET 续传。
- 实现状态：部分（结构在，连真 Redis 即失效）
- 证据：`backend/bus/redis_bus.py` 全文已实现 `publish`(:70) / `subscribe`(:112) / `_redis_to_queue`(:131) / `get_events_after_from_db`(:170)，并经 `__init__.py:15-23` 在 `REDIS_URL` 存在时自动启用、import 失败降级。文件头声称「已实现」，但类 docstring `:39` 仍写「此实现桩未填充」（自相矛盾，与基线事实一致）。
- 差距：见以下三条实质缺陷。
- 处置：补实现（修三处缺陷）+ 改 docstring。

### 缺陷 1 · EventType 误当 Enum，Redis 模式事件全丢（🔴 新发现/超 C7）
- 设计要求：Redis 转发的消息应能还原成 BusEvent 并推送。
- 实现状态：偏离（连 Redis 后广播实际失效）
- 证据：`event_types.py:16` `EventType` 是**普通类**（非 Enum），但 `redis_bus.py:142` `EventType(data["type"])`、:205 `EventType(d["type"])` 把它当 Enum 调用——`EventType("part.created")` 抛 TypeError，被 :150 `except: pass` / :209 静默吞掉。同理 publish 的 `event.type.value`(:80) 永远走 `str(event.type)` 分支。
- 差距：一旦真正连上 Redis，`_redis_to_queue` 每条消息构造 BusEvent 即抛错被吞 → 订阅者**收不到任何事件**；`get_events_after_from_db` 同样返回空。多进程 fan-out 名存实亡。
- 处置：补实现（去掉 `EventType(...)` 调用，直接用字符串 type 构造 BusEvent）。

### 缺陷 2 · 断线续传锚点错位（last_event_id UUID vs 时间戳）（🔴 复核 C7 成立）
- 设计要求：用 Last-Event-ID 精确补发其后事件。
- 实现状态：偏离
- 证据：前端 lastEventId = SSE `id:` 行 = `BusEvent.id`（UUID，`event_types.py:66`）；但 `redis_bus.py:188` `min_score = float(last_event_id)` 期望浮点时间戳，UUID 解析失败 → except 回退「`time.time()-3600`」(:190)，返回最近 1h 而非锚点之后。ZSET 用 `time.time()` 当 score 存入（:86）也不等于 `event.timestamp`，且存的 json 不含 `id`，无法按事件精确定位。
- 差距：Redis 模式下断点续传退化为「粗略回放最近 1h」，可能重复/遗漏，违背 §7「精确补偿」。
- 处置：补实现（ZSET member 内嵌 event.id 与 timestamp，按 id 定位锚点 score 再 ZRANGEBYSCORE）。

### 缺陷 3 · pubsub 泄漏 + 订阅者计数恒 -1（🔴 复核 C7 成立）
- 设计要求：订阅生命周期可回收；get_subscriber_count 监控用。
- 实现状态：偏离
- 证据：`redis_bus.py:124-127` 每次 subscribe 起一个 `_redis_to_queue` 后台 task 并 `pubsub.subscribe`，但 `unsubscribe`(:155-159) **只移除本地 queue，不取消该 task、不 `pubsub.unsubscribe/close`** → 连接/协程泄漏。RedisEventBus **未覆盖** `get_subscriber_count`，继承 `interface.py:56` 默认 `-1`（即便 `_local_queues` 可计数也未用）。
- 差距：长运行多进程下 pubsub 订阅与 task 持续累积（内存/连接泄漏）；监控始终拿到 -1。
- 处置：补实现（subscribe 记录 task+pubsub 句柄，unsubscribe 时取消/关闭；覆盖 get_subscriber_count 返回 `len(_local_queues[...])`）。

---

## 符合度小计

| 状态 | 计数 | 说明 |
|---|---|---|
| 完整 | 18 | 先订阅后响应、接口签名四项、事件类型全集、SSE 端点核心、续传、前端续传/心跳/路由、7 天清理、心跳间隔等 |
| 部分 | 8 | SSE 头缺 ACAO、指数退避无 jitter、bindSSEToStores 结构差异、心跳内容缺字段、§9 前端错误分类、SKIP_TYPES、§6 通路、Redis 基础结构 |
| 缺失 | 3 | connection.failed/UI 提示、§10 测试、Redis 缺陷1 致事件全丢（功能性缺失） |
| 偏离 | 11 | to_sse 嵌套 data、字段命名 agent/content、心跳协程→迭代器、接口扩展、§2.2 样例、event_log 列名、EventLogWriter、Redis 锚点错位、Redis pubsub 泄漏、Redis 计数 -1、§3.1 枚举扩展 |

**整体符合度估计：约 70%**

- **核心契约（先订阅后响应 / SSE 端点 / 前端续传 / 持久化 / 清理）已完整落地并接线生效**，单进程链路可用且较设计有增强（IndexedDB 续传、DB fallback、recoverable 关流、query 兜底）。
- **「偏离」多为设计文档自身滞后**（§2.2 样例、§3 字段名/载荷结构、§7 schema/Writer）——前后端实现自洽，建议**反向更新设计文档**而非改代码（占整体差距过半）。
- **真正需补代码的高优先级**：① Redis 缺陷 1（EventType 误用，连 Redis 即全丢事件，多进程能力名存实亡）；② Redis 锚点错位 + pubsub 泄漏 + 计数 -1（C7 三项复核全部成立）；③ 前端 connection.failed/4xx 终止重连缺失；④ §10 零丢失回归测试缺失。
- 文档标注「待实现」**已严重过时**：除 Redis 分支带缺陷外，InMemory 全链路均已实现。
