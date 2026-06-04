# Zero-Arsenal 修复核查台账（2026-06）

> 配套：修复 plan / `docs/REVIEW_TODO_2026-06.md`
> 用途：每个修复点一行，记录「是否真实实现」的核查结论。
> 状态图例：✅ 真实实现 · ⚠️ 部分实现 · ❌ 未实现/无效 · ⏳ 待核查
>
> 凡 ⚠️/❌ 项保留在 `REVIEW_TODO_2026-06.md` 未勾选，并在本表「备注」给出原因与后续动作。

## Phase 1 · P0

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| NEW-C6-01 | fork_session Row 改列访问 | ✅ | `sessions.py:468,483,529` | 三处循环 `row=dict(row)` 后用 .get()；py_compile 通过 |
| NEW-C6-02 | 章节回滚分支列名 mode/branch_of | ✅ | `sessions.py:1029-1034` | current_mode→mode、forked_from→branch_of，均存在于 schema |
| NEW-C6-03 | fork 补 content/message_type/phase | ✅ | `sessions.py:472-480` | messages INSERT 补 phase/content/message_type（schema 确有此三列） |
| NEW-C9-01 | 4 世界 hooks 导入修复 | ✅ | `extensions/{muv_luv,gundam_seed,infinite_arsenal,crossover}/hooks.py` | 改用 wuxia 纯类模式（删 BaseHook/hook_registry import 与死 register_hooks）；discover 实测注册 muv_luv×2/gundam×2/infinite×3/crossover×3 |
| NEW-C3-01 | agents/llm.py logger | ✅ | `agents/llm.py:7,11` | 补 `import logging` + `logger = logging.getLogger(__name__)`；AST 解析通过 |
| NEW-C5-01 | embed_batch | ✅ | `utils/llm_client.py:111` | 新增 `_EmbeddingClient.embed_batch`，不可用时返回等长空向量 |
| NEW-C5-02 | get_db() 误用 + node_sync 方法 | ✅ | `memory/extractor.py:31-78,313-345,420-460` | 删 `db=get_db()` 误用，新增 `_upsert_node_sync/_mark_node_synced/_bump_retry` 协程（async with + 原生 SQL）；affinity 改写 session_npc_states 真实 schema |
| node_sync_status | 建表 DDL | ✅ | `db/schema.py:310` | 加入 CREATE TABLE + 索引；init_db 实测建表 + UPSERT 通过 |
| R-D01(D4) | auth 无 token fail-closed | ✅ | `api/middleware/auth.py:46-90` | 无 token 仅放行回环(127.0.0.1/::1)，远程 403；并改 hmac.compare_digest 常量时间比较 |
| NEW-C1-01 | verdict 缺失 fail-closed | ✅ | `agents/rules_agent.py:185-194`、`agents/dm_agent.py:259-272` | rules 白名单外→block，dm 白名单外→reject |
| D-16残留 | _resolve_permission 异常 deny | ✅ | `tools/registry.py:240-246`、注释 175/253、`permission.py:110` | 异常→降级 ask（非工具默认 allow）；修正三处 fail-open 误导注释 |
| NEW-B10-01 | review 放行审校工具 | ✅ | `agents/profiles/review.yaml:33-58`、`permission.py:168` | YAML+Python 均加 style_check/purity_check allow；实测 resolve=allow |
| NEW-C2-03 | chronicler start_message_id 游标 | ✅ | `agents/chronicler_agent.py:32-71,150-205` | 改按「上次固化 end_message 之后」计数；固化时写 start/end_message_id；narrative 按边界过滤（兼修 C2-04） |
| NEW-C5-03 | LLM 提取链生产接通 | ✅ | `memory/extract_queue.py:100-221`、`agents/var_agent.py:125` | P1 记忆子代理完成：队列轨道A 跑 LLM 图谱提取，var_agent 每回合入队带 messages/novel_id/world_key |
| B09缺陷1 | EventType 误当 Enum | ✅ | `bus/redis_bus.py:84-95,148,200-235` | 去除 `EventType(...)` 调用，统一字符串 type + `_bus_event_from_payload` 还原 |
| NEW-C7-05 | publish 携带 id/timestamp | ✅ | `bus/redis_bus.py:90-96,主体` | event_json 内嵌 id/timestamp，score=event.timestamp；续传支持按 UUID 定位锚点（兼修缺陷2） |

## Phase 2 · P1

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D5-deps | chromadb 依赖+向量层 | ✅ | `pyproject.toml`、`memory/extract_queue.py:225` | 声明 chromadb/sentence-transformers；修 get_extract_queue 后引擎切 full mode（`get_engine_status→{mode:full}`） |
| D5-pipeline | LLM 提取+embedding+图写入 | ✅ | `memory/extract_queue.py:100-221`、`memory/adapter.py:393-449`、生产调用 `agents/var_agent.py:125` | 队列双轨：轨道A LLM 图谱提取，每回合 var_agent 入队携带 messages/novel_id/world_key（兼 C5-03） |
| NEW-C5-05 | adapter.add_memory 全链 | ✅ | `memory/adapter.py:357-405,340-348` | 模块级 graph/vector 单例；MemoryNode 字段名修正；embed→vector_manager.upsert，缺向量时跳过 |
| NEW-C5-04 | retriever 词法兜底 | ✅ | `memory/retriever.py:295-363,430-447` | 向量空时 Bigram 词法独立召回 + 图扩散种子，无 embedding 可召回 |
| D6 | viewer_agent 五视角 | ✅ | `memory/retriever.py:69-150,451-491,340-360` | 5 分区 character_pov/objective_global/world_state/relationship/objective_local，每视角白名单+乘数 |
| conf_b08-viewer | GET /memory 应用 viewer | ✅ | `api/routers/sessions.py:1237-1287` | 新增 viewer_agent query，透传 recall + 结构化 entries 按分区白名单过滤 |
| conf_b04-hooks | 11 类 hook fire | ✅ | `agents/graph.py`（7 类）+ `api/routers/stream.py`（session_start/end/error）+ `bus/interface.py:publish_part_done`（on_part_done） | 全 11 类已接线 |
| NEW-C8-03/C9-04 | 去双重注册 | ✅ | `extensions/*`（LoadedExtension 加稳定 key） | 统一 hook ID 使两条注册路径去重；实测 dups=[] |
| NEW-C8-04 | hook/rules 扫三级目录 | ✅ | `extensions/extension_loader.py`（discover_extensions 三级） | 跳过 _template、仅 *Hook(s)/HOOKS、修 enabled:false |
| NEW-C4-01 | vm guard | ✅ | `engine/vm.py` | 补 RestrictedPython _getiter_/_getitem_/_write_/_inplacevar_ 等 guard |
| NEW-C4-02 | world_events 键对齐 | ✅ | `agents/world_agent.py` | world_time/location 键与 world hooks 对齐 |
| NEW-C4-03 | dice 减值 schema | ✅ | `engine/dice.py` | 读 combat attributes.hp.parts/psyche schema |
| R-M15 | CombatRoundResult 接线 | ✅ | （删除，无生产者/消费者） | 战斗按逐次命中结算，移除死类型 |
| R-D09 | jinja2 依赖 | ✅ | `pyproject.toml` | 列入 dependencies（jinja2>=3.1） |
| D2 | plan.yaml 去 roll_* | ✅ | `agents/profiles/plan.yaml` | 移除 roll_*（落 *→ask 且 LLM 不暴露骰子工具） |
| D3 | overlay 副本合并 | ✅ | `extensions/plugin.py` | deep-copy + 重注册，修就地污染全局 Profile 单例 |
| D7-schema | 角色卡 v4 schema | ✅ | `db/character_v4.py`、`db/schema.py` | v4 全字段 + MIGRATION_PATCHES_SQL；init_db 实测 |
| D7-migration | v3→v4 迁移 | ✅ | `db/character_v4.py` | v3→v4 迁移函数，迁移卡通过校验 |
| D7-frontend | 前端适配 v4 | ✅ | `frontend/src/components/CharacterEditor.tsx` | identity/OCEAN/4 部位 hp/economy/energy_pools/loadout/achievements；CharacterCreator 委托 Editor；build 通过 |
| D7-ext | 各扩展适配 v4 | ✅ | `extensions/crossover/plugin.py:on_session_init` 等 | 各世界默认卡经 _normalize_to_v4 统一迁移 |
| R-M14 | character_v4 jsonschema | ✅ | `db/character_v4.py` | jsonschema 校验，坏卡拒绝（5 errors） |
| D8 | 全表 CHECK/外键 | ✅ | `db/schema.py` | 全表 CHECK+FK；init_db smoke foreign_keys=1，CHECK 拒坏值 |
| NEW-C11-01/02 | NPC 单一存储 | ✅ | `tools/builtin_tools.py:263` | 归一到 npc_profiles；get_npc_knowledge_scope 无则 found:False 不编造 |
| NEW-C7-04 | pubsub/task 回收 | ✅ | `bus/event_bus.py` + `bus/redis_bus.py`（_sub_meta/unsubscribe/finally close） | event_bus + redis_bus 均幂等关闭、回收 task、计数修正 |
| NEW-C7-01 | 令牌桶淘汰 | ✅ | `api/middleware/rate_limit.py` | 空闲桶淘汰，避免无界增长 |
| NEW-C7-02 | X-Forwarded-For 信任 | ✅ | `api/middleware/rate_limit.py` | 仅信任受信代理 XFF |
| NEW-C7-08 | init_db fail-loud | ✅ | `db/connection.py` | 真错误抛出/记录，仅容忍 already-exists |
| P0-5 | Hub 会话 Tab 合并 | ✅ | `frontend/src`（HomePage/Hub） | 列表+创建合并，删独立存档 tab |
| NEW-C14-02 | 输入按事件解锁 | ✅ | `frontend/src`（SSE idle/done） | 按生成完成事件解锁 + 30s idle 看门狗，替换固定 10s |

## Phase 3 · P2

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| 降级日志 | 叙事/路由降级补日志 | ✅ | `agents/{world,style,npc}_agent.py`+`graph.py`；`routers/characters.py:343/379`、`engine.py:212`、`sessions.py:186/375/389`、`worlds.py:96` | 叙事侧已补；路由侧 R-D02(characters questions/默认卡)、R-D03(engine rules_loader)、R-D04(sessions on_session_init/overlay/active_tools)、R-D08(worlds entries) 全部由 except pass→warning |
| 死代码 | 死代码/死配置清理 | ✅ | `graph.py`(M-09)、`agents.json`、删 2 死数据文件、`builtin_tools.py`(_template)、`registry.py`(VALID_*)、`state.py`(冗余 import) | 均 grep 确认无引用后删 |
| prompt 接线 | TokenBudget/registry.build/watcher | ✅ | `prompts/token_budget.py`、`prompts/registry.py:build`、`skills/watcher.py` | TokenBudget 接入各 agent；build 为权威装配；watcher 刷新 Hook/Agent/Fragment |
| 前端死字段 | activeSkills/快照/world store | ✅ | `frontend/src/stores/*` | 删 activeSkills/snapshot actions/world npcs·loadNpcs·addArchive/重复 NPC CRUD |
| NEW-C13-03 | 裸 fetch 统一 apiFetch | ✅ | `frontend/src/stores/*`、`lib/api.ts` | stores 改走 apiFetch/typed api |
| 前端杂项 | PromptManager 排序/WorldModal | ✅ | `PromptManager.tsx`、`WorldManager.tsx` | sort_order 排序+▲▼；WorldModal 既有世界补抓取 |
| 测试 | marker/命名/query/skip | ✅ | `pytest.ini:5`、`tests/test_round10_quick.py`、`tests/e2e/*`、`memory/extract_queue.py:determine_tier` | stub marker 注册；t1_~t7_→test_*；?q=/top_k；429→ok=False；Playwright ImportError→skip；STUB-T10 抽真实逻辑。collect-only=61 EXIT0 |
| NEW-C3-03 | compaction 裁剪 | ✅ | `agents/compaction.py` | 实装裁剪 |
| NEW-C3-04 | tool_loop 异常显式 | ✅ | `agents/tool_loop.py` | 异常显式化 + FC 自动降级 |
| NEW-C3-02 | ask 泄漏清理 | ✅ | `agents/ask_handler.py` | ask 超时清理 PendingAsk |
| NEW-C6-04 | 快照恢复 fail-loud | ✅ | `api/routers/sessions.py:979` | 坏快照抛错，返回真实 character_state_restored |
| NEW-C6-05 | create_world_archive 字段 | ✅ | `api/routers/sessions.py:1152` | 不再把 archive_type 当 world_key |
| NEW-C7-03 | token 常量时间比较 | ✅ | `api/middleware/auth.py:9,76` | 随 R-D01 一并改 hmac.compare_digest |
| D18 | simpleeval 替换 eval | ✅ | `agents`（condition eval） | 裸 eval→simpleeval（已声明依赖） |
| NEW-C7-09 | 复用 DB 连接 | ✅ | `bus/event_bus.py` | 批量持久化单连接复用 |
| conf_b07-toolresult | ToolResult 契约 | ✅ | `tools/registry.py` | ToolDef kwargs + ToolResult 标准契约 + unregister |
| conf_b07-mcp | MCP 重试/unregister | ✅ | `tools/mcp_bridge.py` | 重试退避 + unregister |
| conf_b09-reconnect | 前端 4xx 终止重连 | ✅ | `frontend/src`（useSSE） | 4xx 终止重连 + connection.failed UI + jitter |

## Phase 4 · P3 + 实现型裁定

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D12 | MAX_ITER=20 | ✅ | `agents/tool_loop.py` | MAX_ITER=20 |
| D11 | 多模型映射 | ✅ | `agents/llm.py`（resolve_llm） | AgentProfile 多模型角色映射，未设回退单模型 |
| D13 | 外部 MCP 子 Agent | ✅ | `agents/external_agent.py` | call_external_agent + asyncio.shield |
| D16 | 8 预置 Skill | ✅ | `backend/skills/*/*.md` | 8 个真实可用 Skill（非桩），实跑 discover 全注册 |
| D17 | SKILL.md 完整格式 | ✅ | `backend/skills/*/*.md` | frontmatter + 正文五节（决策图/铁律/流程/集成/禁词） |
| D19 | 超时常量 30/120/15/300 | ✅ | `backend/timeouts.py`、`tools/registry.py`(30)、`agents/llm.py`(120)、`tools/mcp_bridge.py`(15)、`agents/ask_handler.py`(300) | 新建集中分级常量模块；实测 ASK=300/tool=30/MCP=15/LLM=120 |
| D21 | Tailwind v4 | ✅ | `frontend`（postcss/index.css/config/package） | @tailwindcss/postcss + @import "tailwindcss"；build 通过 |
| D22 | IndexedDB LRU | ✅ | `frontend/src/lib/idb.ts` | 按 last-access LRU 驱逐 |
| D9 | Narrator P4 VariableBlock | ✅ | `agents`（P3 prompt/P4） | P3 不再发变量标记，P4 专责 VariableBlock |
| 前端优化 | 订阅/滚底/虚拟滚动 | ✅ | `frontend/src/components/MessageThread.tsx`（react-virtuoso）、`stores/story.ts`（streamBuffers）、`parts/{NarrativePart,ReasoningPart}.tsx` | T-M15：react-virtuoso 窗口化+followOutput 跟随；conf_b12：流式 delta 写入独立 streamBuffers map（不改 parts 引用），NarrativePart/ReasoningPart 订阅自身缓冲直写 DOM，列表不随 delta 重渲染；build EXIT0 |

## Phase 5 · 文档同步

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D0-docsync | design 02~12 对齐 | ✅ | `docs/design/02~12-*.md` | 11 篇全部对齐实现（D0 代码为准），真缺陷以 🔴 标注未降级设计 |
| 注释漂移 | redis_bus/T-D07/import 等 | ✅ | `redis_bus.py`、`tools/registry.py:231/314/327`、`permission.py:128`、`consolidator.py:141`、`builtin_tools.py`、`mcp_bridge.py` | redis 残留/T-D07 超时语义/冗余 import/deepseek/roll_check/MCP schema 注释全部对齐 |

## 未完全实现汇总（核查后回填）

> 收尾阶段把所有 ⚠️/❌ 项汇总到此处，作为下一轮迭代输入。

全部 P0 + 24 条裁定项均已实现并核查（✅）。**2026-06-04 第二轮**（用户放行第三方依赖）已清零此前 2 项 ⚠️ 部分实现：

1. ✅ **降级日志（路由侧）** — R-D02（`characters.py` questions/默认卡兜底）、R-D03（`engine.py` rules_loader 缺失）、R-D04（`sessions.py` on_session_init/overlay/active_tools 三处 except pass）、R-D08（`worlds.py` entries=[]）全部由静默 `except: pass`/空降级改为 `logger.warning`。T-D09/T-D11 此前已由 agents 子代理覆盖。
2. ✅ **前端性能（T-M15 + conf_b12）** — 引入 `react-virtuoso` 完成列表窗口化（`followOutput` 贴底跟随）；并将流式 delta 拆入 store 独立 `streamBuffers` map（不改 `parts` 引用），`NarrativePart`/`ReasoningPart` 订阅各自缓冲直写 DOM，实现 conf_b12 细粒度订阅，列表不再随每个 delta 重渲染。

> 结论：复审清单 + 24 条裁定项已**全部 ✅ 实现**，无遗留 ⚠️/❌ 项。

### 收尾验证（Phase 6）

| 检查 | 结果 |
|---|---|
| 全量编辑文件 `py_compile` | EXIT=0（各子代理 + parent 复核） |
| 后端导入冒烟（stream/bus/redis_bus/characters/tools/prompts/memory/agents） | IMPORT_SMOKE_OK |
| `pytest --collect-only`（tests + backend/tests） | 61 collected，EXIT=0 |
| `pytest --collect-only -m "not stub"` | 10/61（51 deselected），EXIT=0 |
| 前端 `npm run build` | ✓ built，EXIT=0（Tailwind v4） |
| init_db smoke（CHECK/FK/node_sync_status） | foreign_keys=1，0 违规，CHECK 拒坏值 |
| ToolDef 加载（world_plugin/display_name） | 59 工具，无 Failed-to-load |
| 记忆引擎状态 | mode=full（chromadb 在位） |
| D19 分级超时 | ASK=300/tool=30/MCP=15/LLM=120 |
