# 代码缺陷复审 — 切片 C7（中间件 + 总线 + DB）

> 复审基准：2026-06-03 ｜ 只读复审 ｜ 行级证据以当前文件实际内容为准
> 范围：`backend/api/middleware/`、`backend/bus/`、`backend/db/`

---

## 一、旧报告条目复核

### STUB-01 / STUB-12 / M-05 / R-M07 · redis_bus.py 真实实现度
- 状态：🔄已变化（文档自相矛盾，代码实际已实现）
- 类别：stub（残留文案）/ degradation（功能有缺陷）
- 严重度：🟡降级
- 位置：`backend/bus/redis_bus.py:5-7`（头声称"已实现"）vs `:39`、`:68`（仍写"此实现桩未填充 / 桩"）
- 证据：`publish`(`:70-110`) 真写入 `redis.zadd`/`zremrangebyrank`/`expire`/`publish`；`subscribe`(`:112-129`)+`_redis_to_queue`(`:131-153`) 走真实 `pubsub.subscribe`/`listen` 转发；`get_events_after_from_db`(`:170-214`) 真查 `zrangebyscore`。**全部三方法均有实质实现，非桩**。
- 结论：① 多进程广播=**可用**（Redis 连接成功时 publish→channel、subscribe→pubsub.listen 跨进程转发）；② 断线续传=**部分可用**（ZSET 重放存在，但锚点语义错位，见 NEW-C7-05）；③ Redis 不可用时降级为进程内队列（单节点，无历史重放，`:97-110`/`:179-183`）。
- 修复方向：删除 `:39`、`:68` 残留"桩未填充"字样统一为"已实现"；修复 NEW-C7-05 锚点问题后即可视为生产可用。

### R-D01 · auth.py 未配置 token 时完全放行所有 /api/*
- 状态：⚠️仍存在（设计为"开发模式"故意行为，但确为完全放行）
- 类别：degradation
- 严重度：🔴核心（生产误配即裸奔）
- 位置：`backend/api/middleware/auth.py:36-44`、`:51-53`
- 证据：`self._token = os.environ.get("ZERO_ARSENAL_API_TOKEN","").strip()`；`if not self._token: return await call_next(request)` —— 未设环境变量则 dispatch 第一行直接放行，仅打印 WARNING 横幅。
- 修复方向：保留开发放行，但增加 `ZERO_ARSENAL_ENV=prod` 时 token 缺失直接拒绝启动（fail-closed），避免静默裸奔。

### R-M01 · rate_limit.py 令牌桶进程内存、多 worker 不共享
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/middleware/rate_limit.py:76-79`
- 证据：`self._buckets: dict[str, _TokenBucket] = defaultdict(...)` 注释明写"内存状态；单进程单机适用"。多 uvicorn worker / 多实例各自独立计数，真实限速 = 配置值 × worker 数。
- 修复方向：多实例部署改用 Redis 令牌桶（`INCR`+`EXPIRE` 或 Lua 脚本），或在网关层（Nginx/Envoy）限速。

### R-M03 · db/connection.py 迁移/索引失败 pass 静默
- 状态：⚠️仍存在（且范围比旧报告更广）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/db/connection.py:54`、`:65-66`、`:112-113`、`:136-137`
- 证据：`:53-54` `else: pass  # 其他非致命错误静默忽略` —— 该分支吞掉**所有**非 "no such column"/"already exists" 错误（含 CREATE TABLE 语法错误）；`:65-66`、`:113`、`:137` 三处 `except Exception: pass` 均无日志。建表失败后服务照常启动，运行期才以晦涩报错暴露。
- 修复方向：对非预期异常至少 `logger.warning(...)` 并区分"列已存在"白名单；致命建表失败应中止启动。

### R-M16 · bus/interface.py get_subscriber_count 默认 -1
- 状态：⚠️仍存在（且 RedisEventBus 未覆写）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/bus/interface.py:56-62`
- 证据：基类 `get_subscriber_count` `return -1`。`EventBus` 已覆写为真实值（`event_bus.py:125-130`），但 `RedisEventBus` **未覆写**，故 Redis 模式下监控/健康检查恒返回 -1（见 NEW-C7-06）。
- 修复方向：RedisEventBus 实现 `get_subscriber_count`（统计本地转发队列数或查 Redis 订阅者）。

### R-M17 · bus/event_bus.py event_log DB 持久化失败 pass
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/bus/event_bus.py:103-104`
- 证据：`_persist_event` 末 `except Exception: pass  # 持久化失败不影响实时推送`。持久化全程静默失败，将导致服务重启后 Last-Event-ID DB fallback（`:150-190`）查不到事件，断线续传失效且无任何告警。
- 修复方向：失败时 `logger.warning`，并暴露持久化失败计数指标。

### R-M14 · db/character_v4.py CHARACTER_V4_SCHEMA 未用 jsonschema 校验
- 状态：⚠️仍存在
- 类别：dead（schema 字典装饰性）
- 严重度：🟡降级
- 位置：`backend/db/character_v4.py:12-123`（schema 定义）vs `:177-224`（validate_character 手写校验）
- 证据：全仓 `jsonschema` 零引用（grep 无命中）；`validate_character` 为手写规则，**漏校验**：`physical_state.body_parts.*.hp_ratio` 边界、`skills` 值 ≥0、`inventory[]` 必填项/数量、`economy.points` ≥0、`additionalProperties=False` 等 schema 已声明约束均未执行。schema 字典实质为死数据。
- 修复方向：引入 `jsonschema.validate(data, CHARACTER_V4_SCHEMA)`，或在 validate_character 中补齐缺失校验项。

---

## 二、新增发现（NEW-C7-xx）

### NEW-C7-01 · rate_limit 令牌桶字典无淘汰，内存无限增长
- 状态：🆕新发现
- 类别：optimize / degradation
- 严重度：🟡降级
- 位置：`backend/api/middleware/rate_limit.py:77-79`、`:101-102`
- 证据：`_buckets` 为 `defaultdict`，每个新 client_ip 创建一个常驻 `_TokenBucket` 且**永不清理**。配合 NEW-C7-02 的 IP 伪造，可构造海量伪 IP 撑爆内存（DoS）。
- 修复方向：定期清理满桶/陈旧条目（LRU 或基于 last_refill 的 TTL 扫描）。

### NEW-C7-02 · rate_limit 无条件信任 X-Forwarded-For，限速可被绕过
- 状态：🆕新发现
- 类别：degradation（安全）
- 严重度：🟡降级
- 位置：`backend/api/middleware/rate_limit.py:82-87`
- 证据：`xff = request.headers.get("X-Forwarded-For",""); if xff: return xff.split(",")[0].strip()` —— 直接取客户端可伪造的首段 IP 作为限速键。攻击者每请求换一个伪造 IP 即获独立桶，限速形同虚设。
- 修复方向：仅在受信任反向代理后启用 XFF，并通过可信代理列表/`X-Real-IP` 取真实对端，否则回退 `request.client.host`。

### NEW-C7-03 · auth token 明文非常量时间比较
- 状态：🆕新发现
- 类别：degradation（安全）
- 严重度：🟢次要
- 位置：`backend/api/middleware/auth.py:73-78`
- 证据：`if provided_token != self._token:` 普通字符串比较，存在理论上的时序侧信道。
- 修复方向：改用 `hmac.compare_digest(provided_token, self._token)`。

### NEW-C7-04 · RedisEventBus 后台转发任务/pubsub 泄漏
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/bus/redis_bus.py:124-127`（create_task）、`:131-153`（_redis_to_queue）、`:155-159`（unsubscribe）
- 证据：每次 `subscribe` 都 `asyncio.create_task(self._redis_to_queue(...))`，该协程内 `pubsub.subscribe` 后 `async for ... in pubsub.listen()` 永久阻塞；`unsubscribe` 只从 `_local_queues` 移除队列，**既不取消该 task 也不关闭 pubsub**。每个 SSE 断连都遗留一个常驻协程 + Redis 订阅连接 → 连接/协程泄漏。
- 修复方向：在 Subscription 中持有 task 句柄，close 时 `task.cancel()` 并 `await pubsub.unsubscribe/close()`。

### NEW-C7-05 · Redis 路径丢失事件 id/timestamp，导致 Last-Event-ID 锚点错位
- 状态：🆕新发现
- 类别：degradation
- 严重度：🔴核心（断线续传精度）
- 位置：`backend/bus/redis_bus.py:78-82`（publish 序列化不含 id/timestamp）、`:140-145`（重建 BusEvent 用默认新 uuid/timestamp）、`:186-199`（按 float 时间戳锚点查询）
- 证据：publish 写入的 `event_json` 仅含 `type/session_id/data`，**无 id、无 timestamp**；`_redis_to_queue` 重建 BusEvent 时 id/timestamp 走 dataclass 默认工厂 → 每个订阅者收到的同一事件 id 各不相同。而前端 `Last-Event-ID` 取自 SSE `id:` 行（`event_types.py:66` 为 uuid），`get_events_after_from_db` 却 `float(last_event_id)`（`:188`）解析失败 → 落到 `except` 回溯 1h（`:190`），无法精确从断点续传，且会重放整段历史。
- 修复方向：publish 序列化携带 `id` 与 `timestamp`，ZSET score 用事件 timestamp，重建时还原 id/timestamp；断点锚点改用一致的 id 或 timestamp 体系。

### NEW-C7-06 · Redis 模式下 get_subscriber_count 恒为 -1
- 状态：🆕新发现（R-M16 的 Redis 侧具体表现）
- 类别：unwired
- 严重度：🟢次要
- 位置：`backend/bus/__init__.py:15-19`（REDIS_URL 时实例化 RedisEventBus）+ `redis_bus.py` 全文无 `get_subscriber_count`
- 证据：RedisEventBus 未覆写该方法，继承基类 `-1`。一旦设置 `REDIS_URL`，所有依赖订阅者计数的监控/健康端点失真。
- 修复方向：见 R-M16 修复方向。

### NEW-C7-07 · schema_version 基于列表下标编号，迁移补丁增删即错位
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/db/connection.py:123-135` + `backend/db/schema.py:312-465`
- 证据：`for idx, patch_sql in enumerate(MIGRATION_PATCHES_SQL, start=1)` 用列表下标当版本号并记入 `schema_version`。若未来在列表中间**插入/删除/重排**补丁，已记录的 version→SQL 映射全部错位：旧库会因 `idx in applied_versions` 跳过本应执行的新 SQL（虽 ALTER 失败也被 pass 吞，但 CREATE TABLE/INDEX 类会漏建）。
- 修复方向：为每条补丁赋显式稳定 ID（如内容哈希或硬编码版本号），不依赖下标顺序。

### NEW-C7-08 · init_db 吞掉 CREATE TABLE 语法/致命错误且无日志
- 状态：🆕新发现（R-M03 的更严重子项）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/db/connection.py:47-54`
- 证据：Phase 1 仅对 "no such column"+"CREATE INDEX" 延后、对 "already exists"/"duplicate" 忽略，`else: pass` 把建表 SQL 的语法错误、约束冲突等**致命错误**也静默丢弃，服务带残缺 schema 启动。
- 修复方向：`else` 分支 `logger.error` 并对建表失败抛出/中止启动。

### NEW-C7-09 · _persist_event 每事件新开 DB 连接 + fire-and-forget 丢失风险
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/bus/event_bus.py:82-104`
- 证据：每个非 heartbeat 事件 `asyncio.create_task(self._persist_event(event))`，内部 `async with get_db()` 每次 `aiosqlite.connect`（`connection.py:23`）新建连接、无连接池；高频事件下连接抖动明显，且任务未被等待，进程关闭/异常时在途事件直接丢失（叠加 R-M17 静默）。
- 修复方向：批量/队列化持久化，复用单写连接；关闭时 flush 在途任务。

### NEW-C7-10 · auth 文档与实现的排除路径不一致
- 状态：🆕新发现
- 类别：dead（文档误导）
- 严重度：🟢次要
- 位置：`backend/api/middleware/auth.py:13-14`（声称排除 `/api/openapi.json`）vs `:28`（`_SKIP_PREFIXES` 仅 `/docs /redoc /openapi /health`）
- 证据：`/api/openapi.json` 以 `/api` 开头、不以 `/openapi` 开头，实际**会被要求鉴权**，与文档"无论 token 是否配置均不校验"矛盾。
- 修复方向：将 `/api/openapi.json` 加入 `_SKIP_PREFIXES`，或修正文档。

---

## 三、小计

| 分类 | 数量 | 条目 |
|---|---|---|
| ✅已修复 | 0 | — |
| 🔄已变化 | 1 | STUB-01/12·M-05·R-M07（redis_bus 已实现，仅文案残留） |
| ⚠️仍存在 | 6 | R-D01、R-M01、R-M03、R-M16、R-M17、R-M14 |
| 🆕新发现 | 10 | NEW-C7-01 ~ NEW-C7-10 |

**严重度分布**：🔴核心 2（R-D01、NEW-C7-05）｜🟡降级 11｜🟢次要 4

**redis_bus 真实实现度结论**：publish/subscribe/get_events_after_from_db **均已实质实现**（非桩），Redis 连通时可跨进程广播，断线续传 ZSET 重放存在；但 ① 文件内 `:39`/`:68` 仍保留"桩未填充"过时文案，② 断线续传锚点因 publish 不携带事件 id/timestamp 而错位（NEW-C7-05，replay 退化为回溯 1h），③ 后台转发任务/pubsub 泄漏（NEW-C7-04），④ 监控计数恒 -1（NEW-C7-06）。即"已实现但带 4 处缺陷，未达生产就绪"。
