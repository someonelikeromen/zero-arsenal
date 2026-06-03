# Zero-Arsenal 设计符合度审计报告（2026-06）

> 复审基准日期：**2026-06-03**
> 设计权威：`docs/design/02~12`（`docs/design/00-README.md` 声明为「唯一需求与架构权威来源」）
> 审计方式：11 个只读子代理（B02~B12），每个文档一代理，逐条核对「设计要求 → 实现状态（完整/部分/缺失/偏离）+ 行级证据」。
> 分片明细：`docs/review/conf_b02.md` ~ `conf_b12.md`
>
> 配套报告：`docs/REVIEW_2026-06.md`（代码缺陷）、`docs/REVIEW_TODO_2026-06.md`（P0~P3 清单）

---

## 一、总览：各设计文档符合度

| 文档 | 主题 | 整体符合度 | 主要结论 |
|---|---|---|---|
| 02 | 系统架构 | ~55% | 能力实装 ~80%，文档契约 ~45%；目录/命名/端点/技术选型大面积偏离，**设计文档严重滞后** |
| 03 | Agent 系统 | ~66% | 三层骨架与主链路落地；图拓扑（npc/world 压成单节点）、Narrator 四阶段变量职责、AgentNode/Profile 契约偏离 |
| 04 | 扩展系统 | ~58% | 八类扩展点 7 类有入口；**18 类 hook 仅 9 类被 fire**；**4/5 世界 hooks 永不注册** |
| 05 | Prompt 架构 | ~62% | Layer4 数据流逐字落地；condition 缺 AST 白名单沙箱、SKILL.md 格式严重简化、8 个预置 Skill 目录不存在 |
| 06 | 数据模型 | ~50% | 表骨架基本对齐；**角色卡 v4 严重偏离**（实为 v3 简化卡）、`node_sync_status` 表缺失、普遍缺 CHECK/外键 |
| 07 | 工具注册表 | ~70% | 核心机制落地、工具数超设计；ToolResult 形同虚设、play 权限系统性放宽、超时/重试未对齐 |
| 08 | 记忆系统 | ~35% | **四层召回默认只生效 1 层**；向量/图层因缺依赖+生产从不写入而空跑；运行期硬伤多 |
| 09 | 事件总线/SSE | ~70% | 单进程链路完整且有增强；多数偏离是文档滞后；Redis 分支 3+1 缺陷使多进程能力名存实亡 |
| 10 | 权限模式 | ~60% | 交互链路完整；**三种内置模式权限规则均偏离设计**（play 放宽 / plan 违规掷骰 / review 误 deny 审校工具） |
| 11 | API 设计 | ~88% | **28 个设计端点全部实现**；5 个字段命名偏离；约 75 个已实现端点未进文档 |
| 12 | 前端架构 | ~62% | 核心运行链路齐备且超设计；结构性偏离（services→lib、无 shadcn/types/hooks）、流式优化/LRU 未做 |

**总体平均 ≈ 61%**。

---

## 二、核心判断

### 1. 「偏离」绝大多数 = 设计文档滞后于实现，而非实现缺陷
实现普遍**优于/超出**设计文档描述（端点更多、工具更多、扩展点更完整、SSE 有 IndexedDB 续传等增强）。多个设计文档头部仍标「设计稿/待实现」（07/09），目录树/端点命名/技术选型（02）、四 store 孤儿警告（12 §3.5）等均已**过时**。
→ **处置主线应为「补/改设计文档」**，使 `docs/design/` 重新成为可信的权威来源。

### 2. 少数「缺失/偏离」是真实功能缺口（需补实现）
集中在记忆系统（08）、扩展 Hook（04）、数据模型（06）三块，与缺陷报告的 P0/P1 高度重合：

| 设计承诺 | 实际 | 来源 |
|---|---|---|
| 四层混合召回（向量65%+Bigram35%+图扩散+认知权重） | 默认环境仅「认知权重」1 层生效（缺 chromadb + 生产从不写图/向量） | conf_b08 / def_c5 |
| 18 类生命周期 hook | 仅 9 类被 fire；session/var/narrative/style/memory/npc/part 共 11 类为死事件 | conf_b04 |
| 5 个内置世界 hooks 自动注册 | 4/5（muv_luv/gundam_seed/infinite_arsenal/crossover）因 `BaseHook`/`hook_registry` 不存在永久 ImportError | conf_b04 / def_c9 |
| 角色卡 v4（meta/identity/energy_pools/loadout/psychology(OCEAN)/economy(badges/tier)/achievements/6部位body_parts） | 实为 v3 简化卡（5 维属性、4 部位 hp_ratio、缺 energy_pools/loadout/identity/achievements/OCEAN/badges/tier） | conf_b06 |
| `node_sync_status` 三套存储同步表 | 代码 DELETE/UPDATE 该表，但**全仓无建表** | conf_b06 / conf_b08 |
| condition AST 白名单沙箱（防注入） | 裸 `eval(__builtins__={})` | conf_b05 / def_c11 |
| play 消费类工具 ask 确认 / plan 禁掷骰 / review 审校 allow | play 全 allow、plan 允许 roll_*、review 误 deny style/purity_check | conf_b10 / conf_b07 |
| LLM 提取 + embedding + 图关联写入流水线 | 生产走 SQLite 正则启发式，LLM extractor 为死代码 | conf_b08 / def_c5 |

### 3. 设计文档自身存在内部矛盾（需先裁定基准）
- **10-permission-modes**：§2「实现差异对照」与 §3「原始设计意图」自相矛盾（play=allow vs play=ask）。
- **09-event-bus-sse**：§2.1 接口（同步 get_subscriber_count）与 §2.2 样例（异步）矛盾；§3.1 to_sse（展开 data）与实现（嵌套 data）不一致。
→ 修文档前需先确定 play 默认权限、to_sse 载荷结构等的**权威定义**。

---

## 三、按文档分章 · 设计要求 → 实现状态 → 差距

> 完整逐条矩阵见各分片 `conf_b0X.md`。下列为每文档的关键差距摘要。

### B02 系统架构（~55%）
- ✅ 完整：七层架构、回合管线（rules→dm_gate→dice→parallel_nw→narrator→style→var→chronicler）、八类扩展能力、四阶段叙事、并行/串行约束、核心后端栈。
- 偏离（改文档）：八类扩展点位置（每插件一目录 vs 按类型）、独立 `hooks/` 层未入设计目录树、入口端点 `/turn→/message` `/stream→/events`、`var_executor.py→vm.py`、DB 用裸 aiosqlite 非 SQLAlchemy、无 migrations 目录。
- 偏离（技术选型）：向量未用 SQLite-vec/Chroma（自研+sentence-transformers，且未声明 chromadb）、BM25 未用 rank-bm25（jieba 自研）、Hook 非 pluggy（自研）、LLM 网关实为 litellm。
- 需补实现：IndexedDB（已用原生）、watchdog/jinja2/Ruff/mypy/Playwright 依赖声明。

### B03 Agent 系统（~66%）
- ✅ NPCAgent、AgentState（6 数据类）、子 Session 并发、选型对比。
- 偏离：图节点集合（dm→dm_gate、npc+world→单 `parallel_nw` 节点 asyncio.gather、多出 dice/options 节点）、Narrator P1 schema 大幅简化、**P3/P4 变量职责与设计相反**（P3 内联 `{{SET}}` 而非 P4 专责 `<VariableBlock>`）、TavernCommand 未真正产出、AgentProfile 全 deepseek-chat（无多模型分工）、tool_loop MAX_ITER=10（设计20）。
- 缺失：§8.3 外部 MCP 子 Agent（`call_external_agent`）、§8.2 `asyncio.shield` 隔离。

### B04 扩展系统（~58%）
- ✅ 三级目录优先级、热加载、注册表生成、工具/Agent 扩展、扫描算法、Hook 枚举定义（20 个）。
- **缺失（真缺口）**：4/5 世界 hooks 永不注册（见二.2）、11/20 hook 为死事件、§1.2 同名合并规则、§3.2 冲突 5 细则、§2.5 PromptFragment 独立文件机制未启用。
- 偏离：§2.8 Hook 接口由强类型改弱类型 ctx dict、Hook 双重注册路径、manifest schema 三套不统一。

### B05 Prompt 架构（~62%）
- ✅ PromptFragment 字段、Registry 核心方法、5 层架构、Layer0 Core 内容、**Layer4 BackendDataStream（18 轴逐字落地）**。
- **缺失/偏离（真缺口）**：condition 缺 AST 白名单沙箱（裸 eval）、SKILL.md frontmatter 缺 id/role/source/version、正文五节结构无文件遵循、设计 8 个预置 Skill 目录不存在、`backend/skills/` 无任何 SKILL.md。
- 偏离（改文档）：priority 区间（实现 0-29/100/200/450 vs 设计 0-9/10-19/...）、token_estimate 改运行时估算、无 AgentState 类、相位枚举命名混用。

### B06 数据模型（~50%）
- ✅ sessions/messages/message_parts/chapters 表、PartType 枚举（17 种）、§8.3 只增不删向后兼容。
- **角色卡 v4 严重偏离（最高优先级）**：见二.2。
- **缺失**：`node_sync_status` 表（代码引用无建表）。
- 偏离：character_cards 列名（version→schema_version、card_json→data_json、hp_overall REAL/1.0→INT/0）、vector_index_meta（total_vectors→entry_count、768→1536）、dice_log（timestamp→created_at）、npc_profiles（npc_name→key+session_id）、world_archives 改条目化、memory GraphRAG 平行架构、9 张超 06 额外表、Alembic→手写 MIGRATION_PATCHES_SQL。普遍缺 CHECK 约束与外键 ON DELETE。
- C6 关注核实：`sessions.mode`/`sessions.branch_of`/`npc_profiles.key` **三列均存在**（无缺列），唯 `node_sync_status` 表缺失。

### B07 工具注册表（~70%）
- ✅ 并发分组、ask SSE 流程、14 设计工具 + 大量扩展工具、MCP 注册接线。
- 偏离：文档头「待实现」过时、ToolContext/ToolDef 字段改名、**ToolResult 形同虚设**（handler 返回纯 dict）、**play 权限矩阵系统性放宽**（edit/earn/purchase/fork/mcp_* 被 `*→allow` 覆盖）、超时常量（15/10/60/5 vs 设计 30/120/15/300）与 MCP 重试未对齐、**deny 安全底线未强制**（overlay 可覆盖 deny）、§8 测试缺失、缺 `unregister`（MCP 热卸载）。

### B08 记忆系统（~35%）
- ✅ 认知分区权重、§7 Schema（文档已对齐）。
- **核心缺口（见二.2）**：四层默认仅 1 层生效、LLM 提取链生产从不触发、`embed_batch` 缺失、`get_db()` 误用、`node_sync_status` 缺表、缺 chromadb 依赖。
- 偏离：tier 用 core 取代 semantic 且无 procedural、viewer_agent 视角枚举与设计完全不同且退化为布尔可见性、无 MemoryManager/MemoryConfig 类、混合得分公式细节不同。
- 部分：固化（两个冲突 consolidator 单例，一个死代码）、回滚（图层可用，SQLite/同步表失效）、GET /memory 不传 viewer_agent、回滚无 confirm 护栏。

### B09 事件总线/SSE（~70%）
- ✅ 先订阅后响应、接口签名、20 事件类型全集、SSE 端点、续传、前端心跳/退避/路由、7 天清理、心跳间隔。
- **需补代码**：Redis 缺陷1（EventType 当 Enum→连 Redis 全丢事件）、Redis 锚点错位、pubsub 泄漏、计数 -1；前端 connection.failed/4xx 终止重连缺失；§10 零丢失回归测试缺失；指数退避无 jitter。
- 偏离（改文档）：to_sse 嵌套 data、字段名 agent/content、心跳由迭代器空闲自产、event_log 列名、EventLogWriter 改逐条 task、§2.2 样例过时、4 个新增事件类型未登记。

### B10 权限模式（~60%）
- ✅ AgentProfile 结构、ask 交互流程、超时 deny、模式切换 API、C8 default_permission 加载、前端组件。
- **偏离（真缺口）**：play 系统性放宽（消费类 allow）、plan 允许 roll_*（违反「绝不掷骰」）、**review style_check/purity_check 被 `*→deny` 误拒（NEW-B10-01）**、`extensions/plugin.py:183` overlay 就地污染全局 Profile。
- 偏离（改文档/裁定）：§2 与 §3 自相矛盾需先定基准、get 未注册名 fallback 到 play、deny 返回 error dict 而非抛异常、匹配无「精确优先」仅靠顺序、§7.4 模式校验硬编码字面量。

### B11 API 设计（~88%，符合度最高）
- ✅ **28 个设计端点全部实现（缺失 0）**、/api 前缀、统一错误格式、cursor 分页、24 项完整。
- 偏离（字段命名）：`POST /sessions` 返回完整 character（设计示例 null）+ 多 chapter_id、`GET/PATCH /character` 外层包装与字段名不符、`POST /engine/roll` 字段名（threshold/verdict/rolls vs difficulty/outcome/detail）、`PATCH /sessions/{id}` 设计未记、422 details 用 FastAPI 原生结构。
- 反向缺口：约 **75 个已实现端点未进设计文档 11**（会话扩展/引擎/全局模板管理），需补章节或交叉引用。

### B12 前端架构（~62%）
- ✅ React19/TS5.5/Vite6/Zustand5/SSE 自实现/TanStack Router、响应式三栏、四 store 接线、PartRenderer 分派、Part 类型联合、SSE 客户端、ChapterTree。
- **缺失**：shadcn/ui（全手写 Tailwind）、前端 `prompts/` 模块（下沉后端）。
- 偏离：Tailwind v3（设计 v4）、原生 indexedDB（非 idb 库）、目录结构（services→lib、无 types/hooks）、布局改右侧 8-Tab、CharacterStore/uiStore 重塑、state_patch 有 UI（设计 null）、useSSE hook 内联、DiceRollPart 字段。
- 部分：NarrativePart 未做 store.subscribe 细粒度订阅、IndexedDB 用时间过期代 LRU。
- ⚠️ §3.5「四 store 孤儿」警告已过时，应优先更新。

---

## 四、「设计了但未实现 / 已偏离」汇总清单

**A. 设计了但实现缺失（需补实现或删设计）：**
1. `node_sync_status` 表（06/08）— 代码引用无建表。
2. 18 类 hook 中 11 类 fire（04）— session/var/narrative/style/memory/npc/part。
3. 4/5 世界 hooks 注册（04/09 def_c9）。
4. condition AST 白名单沙箱（05）。
5. SKILL.md 完整格式 + 8 个预置 Skill 目录（05）。
6. 角色卡 v4 完整结构（06）— energy_pools/loadout/identity/achievements/OCEAN/badges/tier/6部位。
7. LLM 记忆提取 + embedding + 图写入生产链路（08）。
8. viewer_agent 五视角隔离（08）。
9. MemoryConfig 集中配置 / OpenAI embedding 降级 / min_score 过滤（08）。
10. 外部 MCP 子 Agent `call_external_agent`（03）。
11. ToolResult 标准返回契约（07）。
12. MCP 重试指数退避 + `unregister`（07）。
13. 前端 connection.failed/4xx 终止重连 + §10 SSE 零丢失测试（09）。
14. shadcn/ui + 前端 prompts 模块（12）。
15. NarrativePart store.subscribe 细粒度订阅 + IndexedDB LRU 驱逐（12）。

**B. 已偏离设计意图（需裁定后补实现 or 改设计）：**
1. play/plan/review 三模式权限规则（10/07）。
2. Narrator P3/P4 变量职责倒置（03）。
3. 图拓扑 npc/world 单节点 gather（03）。
4. to_sse 嵌套 data / 字段命名（09）。
5. AgentProfile 多模型角色映射（03）。

**C. 设计文档严重滞后（主要改文档）：**
02 目录/端点/技术栈、03 节点集合/agents.json、04 manifest schema、05 priority 区间、06 列名/额外表、07 文档头「待实现」、09 §2.2 样例、11 约 75 个未记端点、12 目录结构/四 store 孤儿警告。

---

> 详细逐条证据（文件:行号）见 `docs/review/conf_b02.md` ~ `conf_b12.md`。可执行修复清单见 `docs/REVIEW_TODO_2026-06.md`。
