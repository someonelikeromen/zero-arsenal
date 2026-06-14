# Zero-Arsenal 复审 · 修复总清单（2026-06）

> ✅ **修复执行已完成（2026-06-04）**：基于本清单 + 24 条裁定的修复 plan 已全部执行。
> 逐点核查结论见 **`docs/FIX_VERIFICATION_2026-06.md`**（权威台账，含 file:line 证据与收尾验证）。
> 结论：P0 + 全部 24 条裁定项均已实现并核查为 ✅。**2026-06-04 第二轮**（放行第三方依赖）已清零此前 2 项部分实现：
> ①路由侧降级补日志 R-D02/03/04/08 已全部 except pass→warning；②前端引入 react-virtuoso 完成真·虚拟滚动 windowing + conf_b12 流式细粒度订阅。**全清单无遗留 ⚠️/❌。**
> 收尾验证：`pytest --collect-only`=61(EXIT0)、`-m "not stub"`=4 passed/6 skipped、前端 `npm run build` EXIT0、init_db CHECK/FK 通过、记忆引擎 full mode。
>
> 复审基准日期：**2026-06-03**
> 来源：`docs/REVIEW_2026-06.md`（代码缺陷）+ `docs/DESIGN_CONFORMANCE_2026-06.md`（设计符合度）
> 证据明细：`docs/review/def_c1~c16.md`、`conf_b02~b12.md`
>
> 每条格式：`[ ] 描述 — 文件:行号（类别 · 来源条目号）`
> 优先级：**P0 运行期崩溃/安全/核心空转** → **P1 核心功能缺口** → **P2 降级与质量** → **P3 文档与优化**。
> 无上限清单，按需逐项勾选。

---

## P0 · 立即修复（运行期崩溃 / 安全裸奔 / 核心机制空转）

### 运行期崩溃
- [x] `fork_session` 对 `aiosqlite.Row` 调 `.get()` → 改用列访问/dict 转换；有 parts/NPC 的会话 fork 必崩 — `api/routers/sessions.py:483-489,534`（stub · NEW-C6-01）
- [x] 章节回滚 `create_branch=true` 分支 INSERT 用了不存在列 `current_mode`/`forked_from` → 改 `mode`/`branch_of` — `api/routers/sessions.py:1019-1026`（stub · NEW-C6-02）
- [x] fork 复制 messages 丢失 `content`/`message_type`/`phase` → 补齐复制列 — `api/routers/sessions.py:471-476`（stub · NEW-C6-03）
- [x] 4 个世界 hooks 顶层 import 不存在的 `BaseHook`/`hook_registry` → 崩溃即空转，需补这两个符号或改正导入 — `extensions/{muv_luv,gundam_seed,infinite_arsenal,crossover}/hooks.py`（stub · NEW-C9-01 / conf_b04）
- [x] `load_agent_config` 警告路径调用未定义 `logger` → 未配置 agent 名触发 NameError，补 logger 定义 — `agents/llm.py:126,139`（stub · NEW-C3-01）
- [x] `emb_client.embed_batch()` 不存在（仅 `embed`）→ 补该方法或改调用 — `memory/extractor.py:330`（stub · NEW-C5-01）
- [x] 把 `get_db()`（asynccontextmanager）当对象调 `upsert_node_sync/_exec/mark_node_synced`（均不存在）→ 改 `async with` + 实装方法 — `memory/extractor.py`、`memory/rollback.py`（stub · NEW-C5-02）
- [x] `node_sync_status` 表代码 DELETE/UPDATE 但全仓无 CREATE TABLE → 补建表 DDL — `db/schema.py`（引用见 `memory/rollback.py:67,154`、`extractor.py:341`）（stub · node_sync_status / conf_b06 / conf_b08）

### 安全裸奔 / 门禁 fail-open
- [x] 未配置 `ZERO_ARSENAL_API_TOKEN` 时完全放行所有 /api/（仅 WARNING）→ 生产改 fail-closed 或显式 require — `api/middleware/auth.py:36-44`（degradation · R-D01）
- [x] rules/dm verdict 字段缺失/未知值回落 `pass` → 改 fail-closed（语义缺失也 block）— `agents/rules_agent.py:186`、`agents/dm_agent.py:260`（degradation · NEW-C1-01）
- [x] `_resolve_permission` 异常回落工具自带默认（多 allow）= 残留 fail-open → 异常一律 deny/ask — `tools/registry.py:234-242`（degradation · D-16 残留 / conf_b07）
- [x] review 模式 `style_check`/`purity_check` 落到 `*→deny` → 补 allow pattern，否则审校核心工具被自禁 — `agents/permission.py:159-187`、`profiles/review.yaml`（degradation · NEW-B10-01）

### 核心机制空转
- [x] chronicler `start_message_id` 从不写入 → 阈值后每回合重复固化+章节膨胀，需持久化游标 — `agents/chronicler_agent.py:36-45,183-197`（stub · NEW-C2-03）
- [x] LLM 图谱提取链（extractor.py）生产路径从未触发，队列走 SQLite 正则启发式 → 接通生产调用 — `memory/engine.py`、`memory/extract_queue.py`（unwired · NEW-C5-03 / conf_b08）

### Redis 模式专属（设置 REDIS_URL 时）
- [x] `EventType` 被当 Enum 调用（实为普通类）→ 连真 Redis 后构造事件抛错被吞，订阅者零事件 → 修正构造方式 — `bus/redis_bus.py:142,205`（stub · B09 缺陷1）
- [x] publish 不携带 event id/timestamp → Last-Event-ID 锚点错位，续传退化为回溯 1h 全量重放 — `bus/redis_bus.py`（degradation · NEW-C7-05）

---

## P1 · 核心功能缺口（设计承诺未兑现 / 重建子系统）

### 记忆系统（四层召回 / 提取链）
- [x] 重建向量+图写入链路：生产从不写图/向量 → 召回默认仅「认知权重」1 层生效 — `memory/*`（unwired · conf_b08）
- [x] 声明 `chromadb`（或 sentence-transformers）为依赖并接通向量层；缺依赖时显式降级而非空跑 — `pyproject.toml` / `memory/vector.py`（degradation · STUB-02 / conf_b08）
- [x] `adapter.add_memory` 向量写入路径属性/方法/构造参数全错被吞 → 全链路对齐 — `memory/adapter.py`（stub · NEW-C5-05）
- [x] retriever 补词法-only 兜底（向量层缺失时仍可召回）— `memory/retriever.py`（degradation · NEW-C5-04）
- [x] viewer_agent 五视角隔离落地（当前退化为布尔可见性）— `memory/*`（degradation · conf_b08）
- [x] GET /memory 传入 viewer_agent 参数 — `api/routers/*`（unwired · conf_b08）

### 扩展 Hook 系统
- [x] 18 类 hook 中 11 类（session/var/narrative/style/memory/npc/part）从未被 fire → 接通触发点 — `extensions/*` + 管线（unwired · conf_b04）
- [x] 内置钩子双重注册去重 — `agents/*`、`extensions/*`（dead · NEW-C8-03 / NEW-C9-04）
- [x] hook/rules 扫描覆盖 user/project 三级目录（当前只扫内置）— `extensions/extension_loader.py`（unwired · NEW-C8-04）

### 引擎（变量/战斗/骰子）
- [x] vm 缺 guard 函数 → 状态变更脚本恒静默失效（即便装了 RestrictedPython），补 `_getitem_`/`_write_` 等 guard — `engine/vm.py`（stub · NEW-C4-01）
- [x] world_events 键错位（world_time/location 永不来自 world_agent）→ 对齐键名 — `engine/runtime_data_stream.py`（stub · NEW-C4-02）
- [x] dice 减值 schema 错位（伤势/压力减值恒 0）→ 对齐字段 — `engine/dice.py`（stub · NEW-C4-03）
- [x] `CombatRoundResult` 全项目无引用 → 接线整轮战斗结算或移除 — `engine/combat.py`（dead · R-M15）
- [x] jinja2 列为依赖（.j2 模板当前恒不生效、原文直出）— `pyproject.toml` / `engine/prompt_assembler.py`（degradation · R-D09 / NEW-C12 jinja2）

### 权限模式对齐（需先裁定基准，见 10-permission-modes §2/§3 矛盾）
- [x] play 消费类工具（edit/earn/purchase/fork/mcp_*）由 `*→allow` 覆盖 → 按设计改 ask 确认 — `profiles/play.yaml` / `tools/registry.py`（degradation · conf_b07 / conf_b10）
- [x] plan 模式允许 `roll_*`（违反「绝不掷骰」）→ 禁止 — `profiles/plan.yaml`（degradation · conf_b10）
- [x] deny 安全底线强制不可被 overlay 覆盖 — `tools/registry.py` / `extensions/plugin.py:183`（degradation · conf_b07 / conf_b10）
- [x] overlay 就地污染全局 Profile → 改为副本合并 — `extensions/plugin.py:183`（degradation · conf_b10）

### 数据模型（角色卡 v4）
- [x] 角色卡升级到 v4：补 meta/identity/energy_pools/loadout/psychology(OCEAN)/economy(badges/tier)/achievements/6 部位 body_parts（当前为 v3 简化卡）— `db/schema.py` / 角色卡装配（stub · conf_b06）
- [x] character_v4 用 jsonschema 校验落地 — `api/*`（degradation · R-M14）

### NPC 存储一致性
- [x] NPC 三处存储统一（spawn 的 NPC 查不到）→ 收敛单一存储 — `tools/builtin_tools.py`（stub · NEW-C11-01/02）

### 中间件 / 总线鲁棒性
- [x] RedisEventBus pubsub/task 泄漏 → 退订与任务回收 — `bus/redis_bus.py`（degradation · NEW-C7-04）
- [x] 限流令牌桶字典无淘汰（DoS）→ 加过期淘汰 — `api/middleware/*`（optimize · NEW-C7-01）
- [x] 无条件信任 X-Forwarded-For（限速可绕过）→ 仅信任可信代理 — `api/middleware/*`（degradation · NEW-C7-02）
- [x] init_db 吞建表致命错误 → 致命错误应 fail-loud — `db/*`（degradation · NEW-C7-08）

### 前端 P0-UX 收尾
- [x] Hub 会话 Tab 合并「列表+创建」（当前创建在「会话」Tab、历史在「存档」Tab，IA 割裂）— `frontend/src/pages/*`（unwired · P0-5）
- [x] 发送后 10s 无条件解锁输入 → 改为按生成完成事件解锁（长生成并发重发风险）— `frontend/src/components/*`（degradation · NEW-C14-02）

---

## P2 · 降级与质量（补日志 / 死代码 / 测试 / 死字段）

### 降级补日志/可观测
- [x] world_agent 零日志排障盲区补日志 — `agents/world_agent.py`（degradation · NEW-C2-05）
- [x] options 失败仅 DEBUG、注入节点缺失静默跳过 → 升级日志级别 — `agents/*`（degradation · T-D09/T-D11）
- [x] NPC 空文本回退固定台词 / style 失败丢弃纯净度结果 → 补日志告警 — `agents/{npc,style}_agent.py`（degradation · NEW-C2-01/02）
- [x] 各类静默降级补日志：兜底默认卡/空列表/except pass/0 条提炼 — `characters.py`/`engine.py`/`sessions.py`/`worlds.py`（degradation · R-D02/03/04/08；2026-06-04 全部 except pass→warning）
- [x] D-04/D-05/D-06/D-08 叙事降级补日志 — `agents/*`（degradation · D-04~D-08）：D-05 world_agent 已补 warning（NEW-C2-05）、D-08 `narrator_agent.py:416` P4 提取失败已 warning；D-04（无触发词跳过 LLM，成本优化）/D-06（style 审查失败原文透传）按 def_c2 裁定「可接受/无需动作」

### 死代码 / 死配置清理
- [x] M-07/M-09 死代码清理 — `agents/*`（dead · M-07/M-09）
- [x] 两个死数据文件清理或接线：`crossover/data/character-template.json`、`crossover/data/world-registry.json`（dead · NEW-C10-01/02）
- [x] agents.json `memory_extract` 死配置（提取器实际用 `role="dm"`）→ 对齐 — `data/sys_config/agents.json`（dead · T-D34/T-M17）
- [x] `_template` 工具/钩子泄漏进运行时 → 排除模板目录 — `extensions/extension_loader.py`（dead · NEW-C8-01/02）
- [x] 盲目实例化模块内所有类 / 无默认值插件自动实例化必失败 → 加筛选 — `extensions/plugin.py`（stub · NEW-C8-05/06）
- [x] `enabled:false` 回退失效修正 — `extensions/*`（degradation · NEW-C8-07）
- [x] VALID_PHASES 等死常量清理并补 rules/style — `prompts/*`（dead · NEW-C12-03）
- [x] `registry.build()` 规范入口无人调用 → 接线或移除 — `prompts/registry.py`（dead/unwired · NEW-C12-04）
- [x] TokenBudget 裁剪无调用方传预算从未生效 → 接线 — `prompts/*`（unwired · NEW-C12-02）
- [x] watcher 只刷 Tool 不刷 Hook/Agent → 补热加载 — `prompts/*`（unwired · NEW-C12-05）

### 前端死字段 / 裸 fetch
- [x] 清理/接线 13 项死字段与 action：`character.activeSkills`、3 个快照 action、world store `loadNpcs/npcs/addArchive`、`api.listNpcs/createNpc/updateNpc/deleteNpc`、`api.getChapters/getParts` — `frontend/src/stores/*`、`lib/*`（dead/unwired · T-M03 / T-D18 / NEW-C13-01/02/04）
- [x] stores 多处裸 fetch 统一走 apiFetch — `frontend/src/stores/*`（degradation · NEW-C13-03）
- [x] PromptManager 按 sort_order 排序 — `frontend/src/components/*`（degradation · NEW-C14-03）
- [x] WorldModal 支持对已有世界重跑抓取（当前仅 worldId=null 创建）— `frontend/src/components/*`（degradation · NEW-C14-04）

### 测试质量
- [x] `test_live_generation` 加 stub marker + 无后端跳过（CI `-m "not stub"` 会被收集报错）— `tests/*`（stub · T-M12）
- [x] `test_round10_quick.py` `t1_~t7_` 命名永不被收集（死测试）→ 改命名 — `tests/test_round10_quick.py`（dead · NEW-C15-01）
- [x] `test_p2_extension_loader` 静态检查标 stub marker — `tests/*`（stub · NEW-C15-02）
- [x] infinite_arsenal 测试 `?query=` 参数错配修正、429 不应当通过 — `tests/*`（stub · T-D26/T-D27）
- [x] STUB-T10 测试内重写业务逻辑 → 改为调用真实实现 — `tests/*`（stub · STUB-T10）
- [x] Playwright 缺失致假绿 → 补依赖或显式 skip — `tests/*`（stub · T-D28）

### 其他降级
- [x] compaction 只追加摘要不裁剪反增 token → 实装裁剪 — `agents/compaction.py`（degradation · NEW-C3-03）
- [x] tool_loop 顶层吞异常产空文本 → 显式错误 — `agents/tool_loop.py`（degradation · NEW-C3-04）
- [x] ask 超时 PendingAsk 泄漏 → 清理 — `agents/ask_handler.py`（degradation · NEW-C3-02）
- [x] 角色快照恢复静默 pass → fail-loud — `api/routers/sessions.py`（degradation · NEW-C6-04）
- [x] `create_world_archive` 把 world_key 误写为 archive_type → 修正 — `api/routers/sessions.py`（stub · NEW-C6-05）
- [x] token 非常量时间比较 → 改 `secrets.compare_digest` — `api/middleware/auth.py`（degradation · NEW-C7-03）
- [x] skill/prompt condition 裸 eval → AST 白名单沙箱 — `tools/skill_loader.py`、`prompts/*`（degradation · NEW-C11-08 / NEW-C12-08 / conf_b05）
- [x] 每事件新开 DB 连接 → 复用连接池 — `bus/*`（optimize · NEW-C7-09）
- [x] ToolResult 标准返回契约落地（handler 返回纯 dict）— `tools/registry.py`（degradation · conf_b07）
- [x] MCP 重试指数退避 + `unregister` 热卸载 — `tools/mcp_bridge.py`（degradation · conf_b07）
- [x] 前端 connection.failed/4xx 终止重连 + §10 SSE 零丢失回归测试 — `frontend/src/lib/*` + `tests/*`（degradation · conf_b09）

---

## P3 · 文档同步与优化（设计文档大面积滞后）

### 设计文档更新（实然优于应然，主改文档）
- [x] `docs/STUB_ANALYSIS.md` 标注「历史快照（Phase 0A 前）」，后续以本次报告为准
- [x] 02-system-architecture：更新目录树（每插件一目录 / 独立 hooks 层）、端点命名（/message、/events）、`vm.py`、技术选型（aiosqlite/litellm/自研向量与 BM25/自研 Hook）、补依赖声明（watchdog/jinja2/Ruff/mypy/Playwright/chromadb）
- [x] 03-agent-system：更新图节点集合（dm_gate、parallel_nw 单节点 gather、dice/options 节点）、agents.json 单模型现状、裁定 Narrator P3/P4 变量职责基准
- [x] 04-extension-system：统一 manifest schema（三套）、补 §1.2 同名合并/§3.2 冲突 5 细则、登记弱类型 ctx dict Hook 接口
- [x] 05-prompt-architecture：更新 priority 区间（0-29/100/200/450）、token 运行时估算、补/删 8 个预置 Skill 目录、登记 SKILL.md 实际 frontmatter
- [x] 06-data-model：更新列名（schema_version/data_json/created_at/entry_count）、登记 9 张额外表与 GraphRAG 平行架构、手写 MIGRATION_PATCHES_SQL（非 Alembic）、补 CHECK/外键设计或注明从简
- [x] 07-tool-registry：移除文档头「待实现」、更新 ToolContext/ToolDef 字段名、超时常量（15/10/60/5）
- [x] 08-memory-system：登记 core 取代 semantic、布尔可见性现状、混合得分公式细节（待 P1 重建后回填）
- [x] 09-event-bus-sse：移除「待实现」、修 §2.1/§2.2 同步/异步矛盾、更新 to_sse 嵌套 data 与字段名、登记 4 个新增事件类型、修 §3.1 to_sse 载荷
- [x] 10-permission-modes：消解 §2/§3 自相矛盾（裁定 play 默认权限）、登记 get fallback、deny 返回结构、匹配顺序规则
- [x] 11-api-design：补登约 75 个已实现端点（会话扩展/引擎/全局模板管理）、对齐 5 处字段命名差异（character 包装、roll 字段、422 details）
- [x] 12-frontend-architecture：更新目录（lib 取代 services、无 types/hooks）、Tailwind v3、原生 indexedDB、8-Tab 布局、移除 §3.5「四 store 孤儿」过时警告

### 注释漂移 / 文案
- [x] redis_bus 移除 `:39/:68` 残留「此实现桩未填充」过时文案 — `bus/redis_bus.py`（dead · STUB-01/12 残留）
- [x] T-D07/NEW-C1-02 注释漂移修正（超时实为 deny；rules 对同步 `log_roll` 误用 await）— `agents/*`（dead · T-D07）
- [x] 各处冗余 import 清理 — `agents/*`、`memory/*`（dead · NEW-C3-06 / NEW-C5-06）
- [x] 硬编码 deepseek 模型名收敛到配置 — `tools/*`、`agents/*`（optimize · NEW-C11-04）
- [x] roll_check `difficulty` 死参数清理、SSE message_id 一致化 — `tools/builtin_tools.py`（dead · NEW-C11-06/07）
- [x] MCP 静态注册 schema 失真 → 动态拉取 — `tools/mcp_bridge.py`（degradation · NEW-C11-09）

### 优化
- [x] NarrativePart 改 store.subscribe 细粒度订阅 — `frontend/src/components/parts/{NarrativePart,ReasoningPart}.tsx` + `stores/story.ts` streamBuffers map（optimize · conf_b12；2026-06-04）
- [x] IndexedDB 改 LRU 驱逐（当前时间过期）— `frontend/src/lib/*`（optimize · conf_b12）
- [x] 虚拟滚动实现 — `frontend/src/components/MessageThread.tsx` 引入 `react-virtuoso` windowing（optimize · T-M15；2026-06-04 第二轮）
- [x] 自动滚底不仅依赖 parts.length — `frontend/src/components/*`（optimize · NEW-C14-05）
- [x] tool_loop MAX_ITER 与设计（20）对齐或更新文档 — `agents/tool_loop.py`（optimize · conf_b03）
- [x] 外部 MCP 子 Agent `call_external_agent` + `asyncio.shield` 隔离（设计 §8.2/8.3）— `agents/*`（unwired · conf_b03）

---

## 统计概要

| 优先级 | 条目数（约） | 主题 |
|---|---|---|
| P0 | 17 | 运行期崩溃 8 · 安全/门禁 4 · 核心空转 2 · Redis 2 |
| P1 | 27 | 记忆重建 · Hook 接线 · 引擎修复 · 权限对齐 · 角色卡 v4 · 前端 UX |
| P2 | 35 | 降级补日志 · 死代码清理 · 测试标注 · 前端死字段 |
| P3 | 26 | 12 份设计文档同步 · 注释漂移 · optimize |

> 勾选进度建议：先清 P0（阻断性），再按子系统推进 P1（记忆→Hook→引擎→权限→数据模型），P2/P3 可并入日常迭代。
