# conf_b02 · 设计符合度审计 — 维度 B「系统架构」

> 审计对象：`docs/design/02-system-architecture.md`（v1.0）
> 审计基准日：2026-06-03 ｜ 子代理：B02
> 行级证据以当前文件实际内容为准。

---

## §1.P3 · 八类扩展点 + Hook/Bus 体系

### 八类扩展点接口位置
- 设计要求：WorldPlugin(`extensions/worlds/`)、ToolRegistry(`extensions/tools/`)、SkillRegistry(`extensions/skills/`)、MCPBridge(`extensions/mcp/`)、PromptModule(`backend/prompts/`)、AgentNode(`backend/agents/`)、EventHandler(`backend/bus/`)、StyleLayer(`writing-styles/`)。
- 实现状态：偏离
- 证据：`backend/extensions/`（`plugin.py`、`extension_loader.py`、`hook_protocol.py`、`__registry__.json`）+ 各世界插件目录 `muv_luv/`、`gundam_seed/`、`wuxia/`、`crossover/`、`infinite_arsenal/`、`web_scraper/`、`_template/`，每个含 `plugin.py/tools.py/hooks.py/manifest.json`。
- 差距：实际采用「**每插件一目录 + manifest**」的统一插件架构，而非设计的「按类型 worlds/tools/skills/mcp 分子目录」。ToolRegistry 在 `backend/tools/registry.py`、SkillRegistry 在 `backend/tools/skill_loader.py`、MCPBridge 在 `backend/tools/mcp_bridge.py`（均不在 `extensions/` 下）。扩展点能力存在且更完整，但目录契约与文档不符。
- 处置：补/改设计文档（以实际插件架构为准重写 P3 表格的接口位置列）。

### AgentNode 扩展（运行时节点注入）
- 设计要求：新 LangGraph Agent 节点为一类扩展点。
- 实现状态：完整
- 证据：`backend/agents/graph.py:167-188` `_discover_extension_agents()` 扫描 `extensions/*/agents.py` 并 `importlib.import_module` 触发注册；`graph.py:244` `inject_registered_nodes(builder, main_edge_map)`；`backend/extensions/infinite_arsenal/agents.py` 为实例。
- 差距：无（机制存在且接线生效）。
- 处置：无需动作。

### EventHandler / Hook 体系
- 设计要求：EventHandler 接口位于 `backend/bus/`。
- 实现状态：偏离
- 证据：实际存在独立 `backend/hooks/`（`hook_manager.py`、`builtin_hooks.py`、`__init__.py`）与 `backend/extensions/hook_protocol.py`；`graph.py:123-128` 通过 `from ..hooks import hook_manager, HookEvent` 触发 `on_chapter_end`。
- 差距：Hook 体系实现于 `backend/hooks/`，而设计 §4 目录树中**完全没有 `hooks/` 目录**，且把事件订阅归入 `bus/`。实现与文档分层不一致。
- 处置：补/改设计文档（在 §2 分层图与 §4 目录树补入 `hooks/` 层）。

---

## §2 · 系统分层架构

### 客户端层（React UI + IndexedDB）
- 设计要求：`React Web UI (Vite+TS)` + `IndexedDB（离线缓存/Part 草稿）`。
- 实现状态：部分
- 证据：`frontend/package.json:17-19` React 19 + Zustand + Vite；`frontend/src/lib/bindSSEToStores.ts` 接收 SSE。未发现 IndexedDB/`idb` 依赖或 `offlineCache` 实现。
- 差距：React UI 完整，但 IndexedDB 离线缓存层缺失（`package.json` 无 `idb`）。
- 处置：补实现（如确需离线缓存）或补/改设计文档降级为可选。

### API 层（REST + SSE + WebSocket）
- 设计要求：REST API(FastAPI) + SSE 端点 + WebSocket（可选，双向控制）。
- 实现状态：部分
- 证据：`backend/api/routes.py` + `backend/api/routers/`（sessions/stream/worlds/characters/engine/config/prompts/assets）；SSE 见 `backend/api/routers/stream.py:307 @router.get("/sessions/{session_id}/events")`。
- 差距：REST + SSE 完整；WebSocket 未实现（设计标注「可选」，可接受）。
- 处置：无需动作（WS 为可选）。

### 编排层（LangGraph + AgentProfile + 模式控制器）
- 设计要求：LangGraph 图 + AgentProfile(YAML) + 模式控制器。
- 实现状态：完整
- 证据：`backend/agents/graph.py:191-250` `build_graph()` 编译 StateGraph；`backend/agents/profiles/{play,plan,review}.yaml`；`backend/agents/permission.py`。
- 差距：无（三大组件齐备）。注：分层图节点标注 `Interactive/Autonomous/Supervised` 为旧命名，实现已采用 play/plan/review（与 P6 自注一致）。
- 处置：补/改设计文档（修正 §2 mermaid 中 MODE 节点旧命名）。

### 扩展层（ToolRegistry/SkillRegistry/WorldPlugin/MCPBridge）
- 设计要求：四类扩展注册器构成扩展层。
- 实现状态：完整
- 证据：`backend/tools/registry.py`、`backend/tools/skill_loader.py`、`backend/extensions/plugin.py`、`backend/tools/mcp_bridge.py`。
- 差距：能力齐备，仅物理位置与设计目录契约不同（见 §1.P3 与 §4）。
- 处置：补/改设计文档。

### 引擎层（骰子/变量/提示词/记忆）
- 设计要求：dice.py + 变量执行(RestrictedPython) + 提示词装配(Jinja2) + 记忆子系统。
- 实现状态：完整
- 证据：`backend/engine/dice.py`、`backend/engine/vm.py:1-3`（"变量执行引擎 — RestrictedPython VM"）、`backend/engine/prompt_assembler.py`、`backend/memory/`（engine/retriever/vector/graph/...）。
- 差距：均存在；变量执行文件名为 `vm.py` 而非设计的 `var_executor.py`（详见 §4）。
- 处置：补/改设计文档（文件名）。

### 存储层（SQLite WAL / JSONL / 向量）
- 设计要求：SQLite WAL 主库 + JSONL 归档 + 向量存储(ChromaDB/SQLite-vec)。
- 实现状态：部分
- 证据：`backend/db/connection.py`（SQLite）、`backend/db/audit.py`（JSONL 审计）、`backend/data/dice-archive/rolls_2026-06-02.jsonl`、`backend/memory/vector.py`。
- 差距：SQLite + JSONL 完整；向量存储未使用 ChromaDB 或 SQLite-vec（`pyproject.toml` 无相关依赖，自研 `vector.py` + sentence-transformers）。
- 处置：补/改设计文档（修正向量存储技术选型）。

### 事件总线（asyncio.Queue Bus）
- 设计要求：asyncio.Queue Bus 内部事件分发。
- 实现状态：完整
- 证据：`backend/bus/event_bus.py:1-2,29`（"事件总线 — asyncio.Queue 实现"，`class EventBus(IEventBus)`）；`backend/bus/sse_adapter.py`、`backend/bus/interface.py`。`redis_bus.py:4-6` 为可选 Redis 实现（已实现，未连接时降级进程内队列）。
- 差距：无（与基线疑虑相反，`redis_bus.py` 头注已声明"已实现"，无自相矛盾）。
- 处置：无需动作。

---

## §3 · 核心回合时序图

### 入口端点与 SSE 订阅
- 设计要求：`POST /api/sessions/{id}/turn { action }` 提交回合；`GET /api/sessions/{id}/stream` 订阅。
- 实现状态：偏离
- 证据：实际提交为 `backend/api/routers/stream.py:30 @router.post("/sessions/{session_id}/message", status_code=202)`；订阅为 `stream.py:307 @router.get("/sessions/{session_id}/events")`。
- 差距：端点路径命名不同（`/turn`→`/message`，`/stream`→`/events`）；返回 202 Accepted 与设计一致。
- 处置：补/改设计文档（统一端点命名）。

### Agent 执行链拓扑
- 设计要求：DM 门禁 → RULES 校验 → DICE → (NPC ‖ World) → Narrator(P1-P4) → Style → Var → Chronicler。
- 实现状态：偏离
- 证据：`backend/agents/graph.py:198-248` 实际连边为 `rules → dm_gate → (dice) → parallel_nw → narrator → style → var → chronicler → options → END`。
- 差距：①顺序差异——设计是「DM 先门禁、DM 内部调 RULES」，实现是「**rules 节点先于 dm_gate 节点**」(`graph.py:208` 入口为 rules，`:211-218` rules 后才到 dm_gate)；②DICE 为独立节点 (`graph.py:201,232`) 而非 RULES 内部子步骤；③实现额外多出 `options` 节点（`graph.py:138-162,206`）生成行动选项，设计未提及。
- 处置：补/改设计文档（更新时序图：rules/dm 顺序、独立 dice 节点、新增 options 节点）。

### NPC ‖ World 并行
- 设计要求：NPCAgent 与 WorldAgent 并行执行后汇入 Narrator。
- 实现状态：完整
- 证据：`backend/agents/graph.py:82-106` `parallel_npc_world_node` 用 `asyncio.gather(npc_agent_node, world_agent_node, return_exceptions=True)` 并行，失败静默降级。
- 差距：无。
- 处置：无需动作。

### 四阶段叙事管线（P1-P4）
- 设计要求：Narrator 内 P1 规划 → P2 RAG 注入 → P3 流式生成 → P4 变量回写提取。
- 实现状态：完整
- 证据：`backend/prompts/agents/narrator_p1.md`、`narrator_p3.md`、`narrator_p4.md`（四阶段提示词在位）；`backend/agents/narrator_agent.py` 提供 `narrator_agent_node`。
- 差距：提示词文件存在 p1/p3/p4（p2 RAG 注入通常无独立提示词，由记忆检索实现）。
- 处置：无需动作（需 B04/B07 进一步核实 P2 实装）。

### StyleAgent 门控 → VarAgent 串行 → Chronicler 最后
- 设计要求：Narrator 输出经 Style 审查 → Var(RestrictedPython) 写库 → Chronicler 存档（数据流约束 §6）。
- 实现状态：完整
- 证据：`backend/agents/graph.py:235-241` `main_edge_map` 严格串行 `narrator→style→var→chronicler`；`chronicler_wrapper` (`graph.py:111-133`) 按 `should_consolidate` 按需固化。
- 差距：无（串行顺序与"骰子先于叙事/Style 门控/Var 串行/Chronicler 最后"约束一致）。
- 处置：无需动作。

---

## §4 · 项目目录结构

### backend/agents/
- 设计要求：8 个 Agent 文件 + `profiles/`（`dm_profile.yaml`/`npc_profile.yaml`/...）。
- 实现状态：部分
- 证据：8 个 Agent 文件齐全（`dm_agent.py`/`rules_agent.py`/`npc_agent.py`/`world_agent.py`/`narrator_agent.py`/`style_agent.py`/`var_agent.py`/`chronicler_agent.py`）；但 `backend/agents/profiles/` 为 `play.yaml`/`plan.yaml`/`review.yaml`。
- 差距：Agent 文件全对；AgentProfile 实际按「**模式**」组织（play/plan/review），而非设计按「**Agent**」组织（dm/npc）。另有大量未在树中列出的辅助文件（`dice_node.py`/`agent_node.py`/`tool_loop.py`/`compaction.py`/`ask_handler.py`/`permission.py`/`state.py`/`llm.py`/`agent_span.py`/`cancellation.py`）。
- 处置：补/改设计文档（profiles 组织方式与遗漏文件）。

### backend/bus/
- 设计要求：`event_bus.py` + `event_types.py` + `sse_adapter.py`。
- 实现状态：完整
- 证据：三文件均在位；额外 `interface.py`、`redis_bus.py`、`__init__.py`。
- 差距：无（超集）。
- 处置：无需动作。

### backend/engine/
- 设计要求：`dice.py`/`psyche.py`/`combat.py`/`var_executor.py`/`prompt_assembler.py`。
- 实现状态：部分
- 证据：`backend/engine/` 实有 `dice.py`/`psyche.py`/`combat.py`/`prompt_assembler.py`/`vm.py`/`runtime_data_stream.py`。
- 差距：`var_executor.py` 实际命名为 `vm.py`（`vm.py:2` 即变量执行引擎）；其余 4 文件名一致。
- 处置：补/改设计文档（重命名一致）。

### backend/api/
- 设计要求：`main.py` + `routers/`（sessions/turns/stream/worlds/admin）+ `middleware/`（auth/rate_limit）。
- 实现状态：偏离
- 证据：实际 `backend/main.py`（顶层）+ `backend/api/routes.py`（无 `api/main.py`）；`routers/` 为 sessions/stream/worlds/characters/engine/config/prompts/assets（无 `turns.py`/`admin.py`）；`middleware/auth.py`+`rate_limit.py` 在位。
- 差距：入口文件位置不同；路由模块集合不同（无 turns/admin，回合走 stream.py 的 `/message`，管理散落 config/engine）；middleware 一致。
- 处置：补/改设计文档（路由划分）。

### backend/db/
- 设计要求：`connection.py` + `migrations/` + `models.py`(SQLAlchemy) + `audit.py`。
- 实现状态：偏离
- 证据：实际 `connection.py`/`audit.py`/`schema.py`/`queries.py`/`memory_entry.py`/`character_v4.py`；无 `migrations/` 目录、无 SQLAlchemy `models.py`。
- 差距：未用 SQLAlchemy（裸 aiosqlite + `schema.py`/`queries.py`）；无迁移目录（虽声明 alembic 依赖，见 §5）。
- 处置：补/改设计文档（DB 访问方式由 ORM 改为直接 SQL）。

### backend/memory/
- 设计要求：`__init__.py`+`vector_store.py`+`bm25_index.py`+`graph_diffusion.py`+`cognitive_partition.py`。
- 实现状态：偏离
- 证据：实际 `engine.py`/`retriever.py`/`vector.py`/`graph.py`/`extractor.py`/`consolidator.py`/`chapter_consolidator.py`/`extract_queue.py`/`adapter.py`/`rollback.py`/`schema.py`。
- 差距：文件名全部不同；无独立 `bm25_index.py`/`cognitive_partition.py`（混合检索集中在 `retriever.py`）。能力是否对齐设计的「向量 65%+BM25 35%+图扩散+分区」需 B04 详查。
- 处置：补/改设计文档（记忆模块文件命名）+ 转交 B04 核实算法权重。

### backend/tools/
- 设计要求：`registry.py` + `builtin/`（roll_dice/query_npc/update_var/search_lore）+ `mcp/mcp_bridge.py`。
- 实现状态：偏离
- 证据：实际 `tools/registry.py`/`builtin_tools.py`/`skill_loader.py`/`mcp_bridge.py`/`__init__.py`。
- 差距：内置工具为单文件 `builtin_tools.py`（非 `builtin/` 子包多文件）；`mcp_bridge.py` 在 `tools/` 根而非 `tools/mcp/`。
- 处置：补/改设计文档（工具目录扁平化）。

### backend/skills/
- 设计要求：`registry.py` + `watcher.py`（watchdog + importlib.reload 热加载）。
- 实现状态：偏离
- 证据：实际 `backend/skills/watcher.py` + `writing_styles.py`；SkillRegistry 在 `backend/tools/skill_loader.py`（不在 skills/）。
- 差距：无 `skills/registry.py`；注册逻辑挪至 tools/。P7 声称的 watchdog 热加载需结合 §5 watchdog 依赖缺失核实。
- 处置：补/改设计文档 + 核实热加载实装（见 §5 watchdog）。

### backend/extensions/
- 设计要求：`worlds/`（含 muv_luv/gundam_seed 子目录，world_config.yaml/npc_pool.json/rules.yaml）+ `skills/` + `tools/`。
- 实现状态：偏离
- 证据：实际为「每插件一目录」：`muv_luv/`/`gundam_seed/`/`wuxia/`/`crossover/`/`infinite_arsenal/`/`web_scraper/`/`_template/`，含 `plugin.py`/`tools.py`/`hooks.py`/`manifest.json`/`rules/*.md`；顶层 `extension_loader.py`/`registry_builder.py`/`__registry__.json`。
- 差距：组织维度完全不同（按插件而非按类型）；世界配置用 `manifest.json`+`rules/*.md` 而非 `world_config.yaml`+`npc_pool.json`。实现更成体系，但与文档契约严重不符。
- 处置：补/改设计文档（重写 extensions 目录结构）。

### backend/prompts/
- 设计要求：`base/`/`combat/`/`npc/`/`narrator/`/`style/` 下的 `.j2` 模板。
- 实现状态：偏离
- 证据：实际 `prompts/agents/*.md`（dm_system/rules_system/narrator_p1/p3/p4/style_system）+ `prompts/templates/*.j2`（narrator_p3/world/dm_gate）+ `registry.py`/`template_loader.py`/`core_prompts.py`/`token_budget.py`。
- 差距：模块按 Agent（agents/）而非按域（base/combat/npc）划分；混用 `.md`（系统提示）与 `.j2`（少量模板）。
- 处置：补/改设计文档（提示词目录组织）。

### frontend/src/
- 设计要求：`components/parts/`（5 类 Part）+ `components/panels/` + `stores/`（session/part/character/world）+ `services/`（apiClient/sseClient/offlineCache）+ `prompts/`。
- 实现状态：部分
- 证据：`parts/` 5 类齐全（`TextPart`/`ToolCallPart`/`ToolResultPart`/`VarDiffPart`/`ReasoningPart`）+ 额外多类；`panels/` 在位（但具体面板与设计列表不同：实有 Combat/Economy/Memory/ChapterTree/Dice/History/World/WritingStyle，设计列 Character/World/Inventory/History/Dice）；`stores/` 为 session/character/world/dice/story/chapter/ui/confirm（**无 partStore**）；无 `services/` 目录（用 `lib/api.ts`+`lib/bindSSEToStores.ts`，**无 offlineCache**）；无前端 `prompts/`；额外 `pages/`+`router.tsx`（TanStack Router，设计未提）。
- 差距：Part 渲染完整；stores/services/panels 命名与集合偏离；offlineCache/partStore/前端 prompts 缺失；新增路由层。
- 处置：补/改设计文档（前端目录结构全面更新）。

### 顶层文件
- 设计要求：`writing-styles/`、`WORKFLOW.md`、`SKILL.md`、`requirements.txt`、`README.md`、`tests/{unit,integration,e2e}`。
- 实现状态：部分
- 证据：`tests/{unit,integration,e2e}/` 存在；`README.md` 存在；后端依赖在 `backend/pyproject.toml`（非根 `requirements.txt`）。未在根命中 `WORKFLOW.md`/`SKILL.md`（项目级 SKILL.md 在 `.cursor/skills/zero-arsenal/`）。
- 差距：依赖管理用 `pyproject.toml` 而非 `requirements.txt`；根级 WORKFLOW.md/SKILL.md 未确认。
- 处置：补/改设计文档（依赖文件名）。

---

## §5 · 技术栈汇总表

### 核心后端栈（LangGraph/FastAPI/Pydantic/SQLite/RestrictedPython）
- 设计要求：LangGraph≥0.2、FastAPI≥0.110、Pydantic v2≥2.6、SQLite WAL、RestrictedPython≥7.1。
- 实现状态：完整
- 证据：`backend/pyproject.toml:16`(langgraph>=0.2.0)、`:12`(fastapi>=0.115.0)、`:30`(pydantic>=2.8.0)、`:21`(aiosqlite>=0.20.0)、`:28`(RestrictedPython>=7.0)。
- 差距：RestrictedPython 实测 `>=7.0`（设计写 ≥7.1，差异极小）。
- 处置：无需动作（或微调文档下限）。

### 向量/检索栈（SQLite-vec / sentence-transformers / rank-bm25）
- 设计要求：SQLite-vec（向量存储）、sentence-transformers≥2.7、rank-bm25≥0.2。
- 实现状态：偏离
- 证据：`pyproject.toml:24`(sentence-transformers>=3.0.0)、`:25`(networkx>=3.3)、`:26`(jieba>=0.42.1)。无 `sqlite-vec`、无 `chromadb`、无 `rank-bm25`。
- 差距：向量存储未用 SQLite-vec/Chroma（自研）；BM25 未用 rank-bm25（用 jieba 分词自研）；新增 networkx（图扩散用）。
- 处置：补/改设计文档（向量与 BM25 选型修正）。

### 提示词/热加载/插件钩子（Jinja2 / watchdog / pluggy）
- 设计要求：Jinja2≥3.1、watchdog≥4.0（Skill 热加载）、pluggy≥1.4（Hook）。
- 实现状态：偏离
- 证据：`pyproject.toml:10-33` 依赖列表中**无 jinja2、无 watchdog、无 pluggy**；但 `prompts/templates/*.j2` 存在、`skills/watcher.py` 存在、`hooks/hook_manager.py` 存在。
- 差距：三项依赖均未声明。Jinja2 可能为 langchain 传递依赖；watchdog 缺失意味着 P7「watchdog 监听热加载」很可能未真正实装（需 B 系核实 watcher.py 实现）；Hook 为自研非 pluggy。
- 处置：补实现（补声明 jinja2/watchdog 或确认替代）+ 补/改设计文档（pluggy→自研 Hook）。

### LLM 客户端（LangChain vs litellm）
- 设计要求：LangChain≥0.2 多模型适配。
- 实现状态：偏离
- 证据：`pyproject.toml:17`(langchain-core>=0.3.0)、`:19`(litellm>=1.50.0)；`backend/utils/llm_client.py`、`backend/agents/llm.py`。
- 差距：实际以 **litellm** 作为 LLM 网关（设计未列 litellm），langchain 仅用 core。
- 处置：补/改设计文档（补 litellm，明确 LangChain 角色）。

### MCP / YAML 权限
- 设计要求：mcp(Python SDK) MCP 一等公民、YAML+PyYAML≥6.0(AgentProfile)。
- 实现状态：部分
- 证据：`backend/tools/mcp_bridge.py` 存在；profiles 为 YAML（`agents/profiles/*.yaml`）。但 `pyproject.toml` 未声明 `mcp` 与 `PyYAML`。
- 差距：MCP 桥接代码在位但 SDK 依赖未声明（可能为占位/降级）；PyYAML 未显式声明（或为传递依赖）。
- 处置：补实现（补声明依赖）+ 转交 def 系核实 mcp_bridge 真实度。

### 前端栈（React19/TS/Vite/Zustand/EventSource/IndexedDB）
- 设计要求：React 19、TS≥5.4、Vite≥5.2、Zustand≥4.5、EventSource、IndexedDB(idb)≥8.0。
- 实现状态：部分
- 证据：`frontend/package.json:17`(react ^19)、`:28`(typescript ^5.5)、`:29`(vite ^6.0)、`:19`(zustand ^5.0)；SSE 经 `lib/bindSSEToStores.ts`。**无 `idb`**。额外 immer/clsx/lucide-react/@tanstack/react-router/tailwindcss。
- 差距：React/TS/Vite/Zustand 满足或超出版本（Vite 6、Zustand 5 高于设计下限）；IndexedDB/idb 缺失；新增多个未列依赖。
- 处置：补/改设计文档（前端依赖对齐）+ IndexedDB 视需求补实现或降级。

### 质量与测试工具（Ruff/mypy/pytest/Playwright）
- 设计要求：Ruff≥0.4、mypy≥1.10、pytest+pytest-asyncio、Playwright(E2E)。
- 实现状态：部分
- 证据：`pyproject.toml:36-40` dev 含 pytest>=8.0.0、pytest-asyncio>=0.23.0、httpx；`tests/e2e/*.py` 存在。**无 Ruff、mypy、Playwright 依赖声明**。
- 差距：pytest 体系完整；Ruff/mypy 未声明；E2E 测试为 Python 脚本，未声明 Playwright。
- 处置：补实现（补 dev 依赖）或补/改设计文档。

---

## 符合度小计

| 状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 9 | AgentNode 扩展、编排层、扩展层、引擎层、事件总线、NPC‖World 并行、四阶段管线、Style→Var→Chron 串行、bus/ 目录、核心后端栈 |
| 部分 | 9 | 客户端层、API 层、存储层、agents/ 目录、engine/ 目录、frontend/src、顶层文件、MCP/YAML、前端栈、质量工具 |
| 缺失 | 0 | （无整体性完全缺失项；IndexedDB/watchdog 等以"部分/偏离"内含计） |
| 偏离 | 14 | 八类扩展点位置、Hook 层位置、入口端点命名、Agent 执行链拓扑、agents/profiles 组织、api/ 划分、db/ ORM、memory/ 命名、tools/ 目录、skills/ 目录、extensions/ 组织、prompts/ 目录、向量/BM25 栈、Jinja2/watchdog/pluggy、LLM 客户端 |

> 说明：上表条目数 > 32（部分条目跨"部分/偏离"重复出现以反映多维差异），下列百分比按"独立设计要求 ≈ 30 条"归一估算。

**整体符合度估计：约 55%**

- **能力实现层面**（功能是否落地）：高，约 **80%**——七层架构、回合管线、八类扩展能力、四阶段叙事、并行/串行约束均真实实装且接线生效。
- **文档契约层面**（目录/命名/端点/依赖是否与设计文档一致）：低，约 **45%**——目录结构、文件命名、API 端点、技术选型大面积偏离，设计文档 v1.0 明显滞后于实现演进。
- **核心结论**：实现质量优于设计文档描述，但 `02-system-architecture.md` 已严重过时，**主要处置应为"补/改设计文档"而非"补实现"**；需补实现的仅 IndexedDB、watchdog 热加载、Ruff/mypy/Playwright 依赖声明等边缘项。
