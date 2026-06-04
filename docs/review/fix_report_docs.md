# 设计文档对齐修复报告（fix_report_docs）

> 日期：2026-06 ｜ 范围：仅 `docs/design/02-*.md` ~ `docs/design/12-*.md`
> 依据：`docs/DESIGN_CONFORMANCE_2026-06.md` + `docs/review/conf_b02.md`~`conf_b12.md` 的「处置：补/改设计文档」
> 决策原则 D0：**代码为准**——设计与实现冲突且偏离属「有意/良性实现选择」时，改设计文档对齐实现；**确属待修复缺陷者不改文档迁就现状**，仅在文档内以 ⚠️/🔴 标注并登记于此。
> 每篇被改文档顶部均已加注：`> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。`

## 修复汇总表

| design_doc | sections_updated | note |
|---|---|---|
| `02-system-architecture.md` | 头部状态 + 顶部「实现对齐总览」（扩展点位置/hooks 层/入口端点 /message·/events/回合拓扑/文件命名 vm.py·无 SQLAlchemy·无 migrations/技术选型 自研向量·jieba·litellm/依赖文件 pyproject） | 全部为「文档滞后」，已对齐实现；依赖声明缺口（jinja2/watchdog/pluggy/Ruff/mypy/Playwright/mcp/PyYAML）标为待补实现 |
| `03-agent-system.md` | 头部 + 顶部「实现对齐总览」（节点集合 9 节点 dm_gate/dice/options/parallel_nw、并行为单节点 gather、Narrator P1 简化 + P3/P4 变量职责倒置、tool_loop MAX_ITER=10、agents.json 全 deepseek、AgentNode 契约精简） | 偏离多为文档滞后；§8.2 shield、§8.3 外部 MCP Agent、narrative_hook/info_matrix 标为待补实现 |
| `04-extension-system.md` | 头部 + 顶部「实现对齐总览」（Hook 接口弱类型 ctx dict、HookEvent 20 值、WorldPlugin dataclass、manifest 三套 schema、扫描算法 API 修正、内置世界文件清单） | 文档滞后已对齐；🔴 标注真缺陷：4/5 世界 hooks 永不注册（BaseHook/hook_registry 不存在）、11/20 hook 死事件、冲突 5 细则/PromptFragment/Rules on_demand/MCP schema 缺口 |
| `05-prompt-architecture.md` | 头部 + 顶部「实现对齐总览」（priority 区间 0-29/100/200/450、无 token_estimate/AgentState、相位枚举混用、get_rules_skills、build_system_prompt 主路径、文风经 Skill on_demand） | 文档滞后已对齐；🔴 标注真缺口：condition AST 白名单沙箱未实现（裸 eval）、SKILL.md 格式简化、8 个预置 Skill 目录不存在 |
| `06-data-model.md` | 头部 + sessions/messages/message_parts/character_cards/character_snapshots/world_archives/npc_profiles/session_npc_states/memory_entries/vector_index_meta/dice_log 各表实现对齐注 + §2.1 角色卡 v4 注 + §8 Alembic→MIGRATION_PATCHES_SQL 注 | 列名/默认/取值偏离已对齐（schema_version、data_json、hp_overall INT/0、entry_count、dim 1536、created_at、npc key+session_id、world_archives 条目化、mode play/plan/review）；🔴 角色卡 v4 实为 v3 简化卡、node_sync_status 表缺失 = 待补实现，**保留完整 v4 设计不下调** |
| `07-tool-registry.md` | 头部状态「设计稿待实现」→「已实现（部分偏离）」+ 顶部「实现对齐总览」（ToolContext 无 ask_permission 回调、ToolResult 形同虚设 dict 模型、ToolDef id→name·handler·dict schema、AgentProfile glob 模型、执行链双层双重权限、play 放宽、§3.6+ web 工具、MCPBridge config-driven aiohttp、无 unregister、超时常量） | play 放宽按 D0 采纳为现状（产品取向）；deny 安全底线/MCP 重试/unregister/超时分级/测试标为待补 |
| `08-memory-system.md` | 头部状态 + 顶部「实现对齐总览」（无 MemoryManager/MemoryConfig、tier core 无 procedural、向量经 Chroma、词法分级匹配非 BM25、公式时序分桶、viewer 枚举 chronicler/dm/planner/...、混合公式） | 命名/结构偏离已对齐；🔴 标注真缺陷：默认环境四层仅 1 层生效（缺 chromadb）、生产写入链路断裂（LLM extractor/图/向量从不触发）、embed_batch 缺失、get_db 误用、node_sync_status 缺表、双 consolidator/回滚护栏——均待补实现 |
| `09-event-bus-sse.md` | 头部撤「待实现」+ §2.2 样例标过时并补 EventBus/Subscription 说明 + §3.1 to_sse 嵌套 data + EVENT_TYPES 补 4 新类型（session.idle/mode_changed/turn.complete/chapter.consolidated）+ §3.2 字段名 agent/content + §7.2 event_log 列名（id/session_id/type/data_json/created_at，无 size_bytes）+ §7.3 EventLogWriter 实际逐条 task | 单进程链路全实现，偏离皆文档滞后已对齐；Redis 三缺陷 + 前端 connection.failed/4xx + §10 测试为代码缺陷（其他分片/报告范畴，未在设计文档内改） |
| `10-permission-modes.md` | 头部 + §2/§3 矛盾基准裁定 + §2 补 allowed_groups + §3.1 play allow-by-default + §3.4 get fallback + §4 overlay 置顶/deny 返回 dict + §6.3 ask 超时=deny(fail-closed) + §7.4 校验现状 | play=allow 按 D0 采纳；🔴 **plan 允许 roll_*** 与 **review style/purity 误 deny（NEW-B10-01）** 判为待修复缺陷，**保留 §3.2/§3.3 设计意图不改写**；deny 上调 allow 安全底线、switched_at、dm_note Part 标为待补 |
| `11-api-design.md` | 头部 + 顶部「实现对齐总览」（POST /sessions 返回 character+chapter_id、GET/PATCH /character 字段、engine/roll threshold/verdict/rolls、PATCH /sessions/{id} 补登记、422 native + 410 gone）+ 文末「实现已有未记端点」清单（约 75 个） | 28 端点全实现；字段命名/包装偏离与未记端点均文档滞后，已补登记 |
| `12-frontend-architecture.md` | 头部 + 顶部「实现对齐总览」（Tailwind v3、无 shadcn/ui、原生 IndexedDB、lib/ 无 types/hooks、右侧 8-Tab 布局、Store 结构差异、state_patch 有 UI、useSSE 内联、DiceRollPart、prompts 下沉后端）+ §3.5「四 store 孤儿」警告更新为「已全部接线」 | 结构性偏离皆文档滞后已对齐；NarrativePart store.subscribe 细粒度订阅、IndexedDB LRU 驱逐标为可选补实现 |

## 诚实声明：保留设计意图、未改文档迁就现状的项（判为待修复缺陷，非「doc lag」）

按 D0「仅当偏离属有意/良性实现选择时才改文档」，以下项的偏离属**实现缺陷/真功能缺口**，文档内仅以 ⚠️/🔴 标注并指明修复方向，**未**将设计降级为现状：

- **06**：角色卡 v4 实为 v3 简化卡（缺 energy_pools/loadout/identity/achievements/OCEAN/badges/tier、4 部位 hp_ratio）；`node_sync_status` 表缺失。
- **08**：默认环境四层召回仅 1 层生效（缺 chromadb）；生产从不写图/向量（LLM extractor 死代码）；`embed_batch` 缺失、`get_db()` 误用、双 consolidator 死代码、回滚无 confirm 护栏。
- **05**：condition AST 白名单沙箱未实现（裸 eval）；SKILL.md 完整格式 + 8 个预置 Skill 目录缺失。
- **04**：4/5 内置世界 hooks 永不注册（BaseHook/hook_registry 不存在）；11/20 hook 为死事件；冲突 5 细则 / PromptFragment / Rules on_demand 缺失。
- **10**：plan 模式违规允许 `roll_*` 掷骰；review 模式 `style_check`/`purity_check` 被 `*→deny` 误拒（NEW-B10-01）；`extensions/plugin.py` overlay 就地污染全局 Profile；deny 不可上调 allow 的安全底线未强制。
- **07**：ToolResult 标准契约未落地（dict 返回）；deny 安全底线可被 overlay 覆盖；MCP 重试 / `unregister` / 分级超时常量 / 工具链测试缺失。
- **03**：`asyncio.shield` 隔离、外部 MCP 子 Agent、narrative_hook / info_matrix 写入缺失。
- **09**：Redis 多进程分支三缺陷（EventType 误当 Enum、续传锚点错位、pubsub 泄漏/计数 -1）；前端 connection.failed/4xx 终止重连缺失；§10 零丢失回归测试缺失。
- **02**：jinja2/watchdog/pluggy/Ruff/mypy/Playwright/mcp/PyYAML 依赖声明缺失；IndexedDB 离线缓存（前端）未实现。

## 基准裁定记录（文档自身曾自相矛盾，已裁定）

- **10-permission-modes** §2「实现差异对照」 vs §3「原始设计意图」（play=allow vs play=ask）：按 D0 裁定——数据结构/算法形态及 play 默认权限以**实现**为准；plan roll_*、review style/purity 的偏离判为**缺陷**，§3 保留为应然目标。
- **09-event-bus-sse** §2.1 接口（同步 `get_subscriber_count`）vs §2.2 样例（异步）：以 §2.1 + 实现为准，§2.2 样例标记为过时草案；§3.1 `to_sse` 展开 data vs 实现嵌套：以**嵌套 data** 为准。

## 未能确定/未处理项

- 无「不确定哪一侧权威」而搁置的条目：所有 conf_b* 的「改设计文档」处置均已落实为对齐编辑；所有「补实现」处置均在文档内标注为待修复并集中登记于本报告，未改动任何代码 / 后端 / 前端 / 其他 docs。
- 本次仅编辑 `docs/design/02~12`；`docs/FIX_VERIFICATION_2026-06.md` 按要求未触碰。
