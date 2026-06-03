# conf_b03 — 维度 B 设计符合度审计 · 「Agent 系统」

> 审计基准日期：2026-06-03
> 设计权威：`docs/design/03-agent-system.md`（v0.1.0）
> 证据范围：`backend/agents/**`（全部）、`backend/data/sys_config/agents.json`
> 审计子代理：B03

---

## §1. 三层 Agent 架构总览

### 1.1 三层架构落地（LangGraph + tool_use loop + Part 状态机）
- 设计要求：外层 LangGraph Pipeline（谁先谁后/并行）+ 内层 pi 风格 tool_use loop（节点内工具循环）+ 输出层 opencode Part 状态机（streaming→done→error）。"三层各司其职，互不侵犯。"
- 实现状态：部分
- 证据：`backend/agents/graph.py:191-250`（LangGraph 外层）、`backend/agents/tool_loop.py:44-199`（内层工具循环）、`backend/agents/narrator_agent.py:306-337` + `backend/bus`（Part 通过 `bus.publish_part_created/delta/done` 流转）
- 差距：外层与内层均落地；但"Part 状态机"并非设计描绘的独立类型化状态机（无 `streaming→done→error` 的统一 Part 对象/转移定义），而是散布在各 Agent 内的 `publish_part_*` Bus 调用，`error` 态仅在 narrator P3 异常时零散发布（`narrator_agent.py:352-360`）。
- 处置：补/改设计文档（将"Part 状态机"明确为 Bus 事件约定）或补实现统一 Part 状态机抽象。

---

## §2. LangGraph 图设计

### 2.1 节点集合（设计 §2.2 builder.add_node 清单）
- 设计要求：8 个节点 `rules / dm / npc / world / narrator / style / var / chronicler`，入口 `rules`，`chronicler→END`。
- 实现状态：偏离
- 证据：`backend/agents/graph.py:198-206` 注册 9 个节点：`rules / dm_gate / dice / parallel_nw / narrator / style / var / chronicler / options`
- 差距：①`dm`→重命名为 `dm_gate`；②`npc`+`world` 不是独立图节点，被合并进单一 `parallel_nw` 节点（见 2.3）；③**多出** `dice` 节点（设计中无独立骰子节点，骰子是 RulesAgent 的 `roll_dice` 工具，§3.1）；④**多出** `options` 节点（chronicler 后生成行动选项，设计图完全未提）。
- 处置：补/改设计文档（补 `dice`/`options`/`parallel_nw` 节点与改名说明），或调整实现以对齐。

### 2.2 路由/条件边（设计 §2.2 rules_router / dm_router）
- 设计要求：`rules_router` 依 `dice_results.hard_block` → `end_block`/`dm`；`dm_router` 依 `dm_decision.verdict` → `end_reject`/`parallel_narrative`（两分支）。
- 实现状态：部分
- 证据：`backend/agents/graph.py:59-77`（`_route_after_rules` 依 `rules_verdict in (block,hard_block)`；`_route_after_dm` 依 `dm_verdict` 三分支 reject/needs_roll/parallel_nw），`graph.py:211-232`
- 差距：rules 路由语义一致（判据字段从 `dice_results.hard_block` 改为 `rules_verdict`）；dm 路由**多出 `needs_roll→dice` 分支**，比设计的二分支多一路；`dm_router` 还兼容旧 `block`/`allow`。
- 处置：补/改设计文档（补 needs_roll 路由）。

### 2.3 并行叙事层拓扑（设计 §2.1/§2.2 fan-out 边）
- 设计要求：`add_conditional_edges("dm", dm_router, {... "parallel_narrative": ["npc","world"]})` + `add_edge(["npc","world"], "narrator")`——由 LangGraph 原生 fan-out/fan-in 实现 npc 与 world 并行。
- 实现状态：偏离
- 证据：`backend/agents/graph.py:82-106` 单节点 `parallel_npc_world_node` 内用 `asyncio.gather(npc_agent_node, world_agent_node)` 手动并行，各收 `copy.deepcopy(ctx)`；`graph.py:201,235-247` 仅 `parallel_nw→narrator` 一条边。
- 差距：并发结果正确（功能等价），但**拓扑实现方式与设计相反**——设计明确以"LangGraph fan-out 边 + TypedDict 共享状态"表达并行，实现却退回"单节点内 asyncio.gather + 深拷贝合并"，恰是设计 §1.1 批评纯 tool_use loop 时所说"自己手写 asyncio 协调，谁先谁后藏在代码里无法可视化"。npc/world 在图层面不可见。
- 处置：补/改设计文档（说明出于 LangGraph 并发写冲突而采用单节点 gather），或重构为真正的图 fan-out。

---

## §3. 各 Agent 详细职责

### 3.1 RulesAgent — 门禁层·规则校验
- 设计要求：工具 `roll_dice / check_skill_trigger / query_world_rules`；输出 `dice_results`；硬性违反→`hard_block=True` 路由 END；Doom Loop 防护。
- 实现状态：部分
- 证据：`backend/agents/rules_agent.py:143`（工具 `check_skill_trigger / query_world_rules / read_character`）、`rules_agent.py:189-201`（needs_check/hard_block）、`rules_agent.py:235-334`（`_pre_roll_check` 直接调 `engine.dice` 而非 `roll_dice` 工具）
- 差距：①无 `roll_dice` 工具，改为节点内直接调 `compute_roll_request`；②多出 `read_character` 工具与 `needs_check` 三态；③hard_block✓，doom 防护由 tool_loop 提供✓；④输出字段为 `rules_verdict/rules_roll` 而非设计的 `dice_results`。
- 处置：补/改设计文档（工具清单与 verdict 枚举）。

### 3.2 DMAgent — 门禁层·行动合法性
- 设计要求：工具 `query_npc_profile / query_world_state / check_consistency`；输出 `dm_decision{verdict,reason,modified_action}`，verdict ∈ pass/modify/reject。
- 实现状态：部分
- 证据：`backend/agents/dm_agent.py:176`（工具 `read_character / get_world_state / search_memory`）、`dm_agent.py:260-281`（verdict pass/reject/modify/needs_roll，含旧版 allow/block 映射）
- 差距：工具名全部不同（无 `check_consistency`）；verdict 多一态 `needs_roll`；`dm_decision` 经 `state.py:184-192` 属性兼容组装。核心职责（合法性裁决+改写+骰请求）一致。
- 处置：补/改设计文档（工具清单与 needs_roll）。

### 3.3 NPCAgent — 并行叙事层·NPC 响应
- 设计要求：取 `dm_decision.involved_npcs`；**每 NPC 独立 tool_loop（asyncio.gather）**；工具 `query_npc_profile / update_npc_state / get_npc_knowledge_scope`；知识范围约束。
- 实现状态：完整
- 证据：`backend/agents/npc_agent.py:22`（`NPC_TOOLS` 含三工具+search_memory）、`npc_agent.py:186-190`（`asyncio.gather` 并发每 NPC）、`npc_agent.py:41-103`（`_run_single_npc` 独立 tool_loop + OCEAN 心理注入 + 知识边界提示）
- 差距：NPC 来源是 `character_data.relationships` + `npc_profiles` 表，而非 `dm_decision.involved_npcs`（设计字段未被使用）；其余高度对齐，并额外集成 psyche 模型（增强）。
- 处置：无需动作（或补设计文档说明 involved_npcs 未启用）。

### 3.4 WorldAgent — 并行叙事层·世界推演
- 设计要求：工具 `query_world_state / update_economy / trigger_faction_event`；输出 `world_events`（含 `impact_scope / variable_deltas_preview`）。
- 实现状态：部分
- 证据：`backend/agents/world_agent.py:130-179`（单次 `llm_complete`，无 tool_loop/工具调用）、`world_agent.py:46-94`（关键词 + 每 5 轮触发门控）、`world_agent.py:166-175`（事件仅 `event_type/description/affects`）
- 差距：①无任何工具（`update_economy / trigger_faction_event` 缺失）；②无 tool_loop；③事件结构缺 `impact_scope` 与 `variable_deltas_preview`（与 `WorldEvent` 数据类 `state.py:64-70` 不一致，实际产 dict 用 `affects`）。
- 处置：补实现（工具/字段）或改设计文档对齐精简版。

### 3.5 NarratorAgent — 输出层·叙事主生成
- 设计要求：四阶段；输出 `narrative_text` + `tavern_commands`；P2 纯 Python 不调 LLM。
- 实现状态：部分（详见 §6 逐阶段）
- 证据：`backend/agents/narrator_agent.py:492-579`（P1→P4 主流程）、`narrator_agent.py:567`（`narrative_text` 输出）
- 差距：`tavern_commands` 字段未由 narrator 产出（产 `state_patches` dict，`narrator_agent.py:576-577`）；详见 §6。
- 处置：见 §6 各条。

### 3.6 StyleAgent — 输出层·文风润色
- 设计要求：工具 `check_banned_words / apply_style_template / purity_check`；输出 `polished_narrative / purity_score`；<0.7 自动重写最多 2 次，超限发 `style_warning`。
- 实现状态：部分
- 证据：`backend/agents/style_agent.py:50-79`（程序化禁词扫描，无工具）、`style_agent.py:159-177`（purity_score + 重度 <0.5 全文替换 / 中度 0.5~0.7 段落重写 max 2 轮）、`style_agent.py:147-153`（LLM 审查）
- 差距：①无设计列出的三个工具（以程序化禁词表 + LLM 实现）；②重写阈值由设计的"<0.7 重写"细化为 <0.5 全文 / 0.5~0.7 段落；③超限未发 `style_warning` Bus 事件（只存 `ctx.style_warnings`）。核心 purity 检查与润色✓。
- 处置：补/改设计文档（阈值分级与工具实现方式）。

### 3.7 VarAgent — 输出层·变量结算
- 设计要求：解析 `tavern_commands` 的 `UpdateVariable`；对照 `attribute_schema` 校验范围；工具 `apply_attribute_delta / grant_item / update_relationship / credit_points`；以 `asyncio.shield` 子 Session 隔离（§8.2）。
- 实现状态：部分
- 证据：`backend/agents/var_agent.py:33-141`（读 `tavern_commands` 回落 `state_patches`，调 `engine.vm.execute_state_change`）、`var_agent.py:65-78`（快照回滚点）、`var_agent.py:22-30`（try/except 外层兜底）
- 差距：①无四个结算工具，统一走 `engine/vm.py`；②未见 `attribute_schema` 范围校验；③隔离用 try/except 兜底而非设计的 `asyncio.shield`；④commands 实为 `{cmd,key,value,delta}` patch 而非 `TavernCommand` 对象。失败不阻断叙事✓。
- 处置：补/改设计文档（结算实现走 VM、隔离方式），或补 schema 校验/shield。

### 3.8 ChroniclerAgent — 归档层
- 设计要求：工具 `write_chapter_anchor / compress_memory / register_narrative_hook / update_info_matrix`；`turn_index` 为 **5 的倍数**时压缩最旧 5 轮记忆。
- 实现状态：部分
- 证据：`backend/agents/chronicler_agent.py:50-126`（每轮写 `chapter_anchors`）、`chronicler_agent.py:19,32-47`（`CHAPTER_TURN_THRESHOLD=20`，按未固化消息数触发）、`chronicler_agent.py:199-263`（生成摘要+memory_entries+consolidator）
- 差距：①压缩触发阈值为 **20 条消息**（非设计的"每 5 轮压缩最旧 5 轮"）；②无 `register_narrative_hook`（叙事伏笔注册）与 `update_info_matrix`（信息矩阵同步）实现——`info_matrix_updates` 字段（`state.py:164`）未被 chronicler 写入；③`write_chapter_anchor`/`compress_memory` 以内联 SQL+consolidator 实现而非具名工具。
- 处置：补实现（narrative_hook / info_matrix）或改设计文档；统一压缩阈值口径。

### 3.x GachaAgent（用户任务点名核对）
- 设计要求：`03-agent-system.md` **未定义任何 gacha Agent**（§3 仅 8 个 Agent）。
- 实现状态：完整（相对于设计：设计无此 Agent，实现也无此 Agent）
- 证据：`backend/agents/` 无 gacha 文件；抽卡以工具实现 `backend/agents/tool_loop.py:409-418`（`draw_gacha` 结果写入 `ctx.gacha_pending`），状态字段 `backend/agents/state.py:156-157`（`gacha_pending/gacha_granted`）
- 差距：gacha 是"内层工具 + 状态字段"而非独立 Agent 节点，符合"无 gacha Agent"的设计现状；但 03 文档完全未提及无限武库/抽卡在 Agent 系统中的位置。
- 处置：补设计文档（说明 gacha 由 tool_loop 工具承载，不设独立节点）。

---

## §4. AgentState 定义
- 设计要求：`AgentState(TypedDict)` + 6 个数据类（DiceResult/DMDecision/NPCResponse/WorldEvent/TavernCommand/VarUpdate）；`mode ∈ play/plan/review`；并标注了 player_input→user_input、dm_decision 拆分、memory_context dict→str 等实现差异。
- 实现状态：完整
- 证据：`backend/agents/state.py:32-92`（6 数据类全部定义）、`state.py:96-175`（`TurnContext` dataclass 覆盖设计字段）、`state.py:178-209`（`player_input/dm_decision/npc_responses` 兼容属性）、`state.py:112`（`mode play|plan|review`）
- 差距：以 `dataclass + Annotated[_keep_last] reducer` 替代 `TypedDict`（LangGraph 1.x 并发写要求），差异均已在设计 §4 与 state.py docstring 双向标注。
- 处置：无需动作。

---

## §5. 内层 tool_use loop

### 5.1 tool_loop 主循环
- 设计要求：`DOOM_LOOP_THRESHOLD=3`、`MAX_ITERATIONS=20`；同签名连续调用达阈值终止并记 `warnings`；流式发 Part；`before_hook/after_hook` 形参（block/modify/replace/terminate）。
- 实现状态：部分
- 证据：`backend/agents/tool_loop.py:36-37`（`_DOOM_THRESHOLD=3`，`_DEFAULT_MAX_ITER=10`）、`tool_loop.py:266-273`（doom 检测）、`tool_loop.py:44-52`（签名仅 `on_delta`，无 before/after hook 形参）、`tool_loop.py:325-407`（改以全局 `hook_manager` + `tool_def.before_hooks/after_hooks` 实现钩子）
- 差距：①`MAX_ITERATIONS` 为 **10**（设计 20）；②doom 命中后直接 break/返回，不写 `state["warnings"]`（设计要求记 `doom_loop:` 警告）；③钩子机制从"函数形参 before_hook/after_hook"改为"全局 hook_manager + 工具级 hooks"，能力相近但接口不同。
- 处置：补/改设计文档（迭代上限、钩子接口形态），可选补 doom warning 落 state。

### 5.2 Hook 接口（BeforeToolAction / AfterToolAction）
- 设计要求：`BeforeToolAction(block,reason,modified_args)`、`AfterToolAction(replace_result,terminate)` 数据类。
- 实现状态：偏离
- 证据：`backend/agents/tool_loop.py:336-353`（before 用 dict `hook_ctx{allow,args}`）、`tool_loop.py:384-397`（after 用 dict `{result}`）
- 差距：无 `BeforeToolAction/AfterToolAction` 数据类；`terminate`（钩子终止循环）能力未实现，仅支持 block/改 args/改 result。
- 处置：补实现数据类与 terminate，或改设计文档为 dict 协议。

---

## §6. NarratorAgent 四阶段管线

### 6.1 P1 规划（非流式 JSON）
- 设计要求：temperature=0.3、强制 JSON；输出 `outline{scene_type,estimated_length,key_beats,tone} / log_query_terms / req_char_update / req_world_state / style_directives / variable_block_preview`。
- 实现状态：偏离
- 证据：`backend/agents/narrator_agent.py:24-79`（`_p1_plan`，temp 来自 cfg 0.3✓），输出 schema 仅 `{scene_goal,tone,focus,pov}`
- 差距：P1 输出结构**大幅简化**——无 `key_beats/log_query_terms/req_char_update/req_world_state/style_directives/variable_block_preview`，导致 P2 无法用 P1 的检索词、P4 无法用 `variable_block_preview` 做缺项重试。
- 处置：补实现（扩展 P1 JSON）或改设计文档对齐精简版。

### 6.2 P2 检索（纯 Python，不调 LLM）
- 设计要求：纯 Python 并发 `asyncio.gather`：hybrid RAG + 角色批量 + 世界状态批量 + 战斗实体匹配。
- 实现状态：部分
- 证据：`backend/agents/narrator_agent.py:86-179`（`_p2_context` 并发 4 路：记忆 recall / lore / 角色快照 / 章节摘要，纯 Python✓）
- 差距：未用 P1 的 `log_query_terms`（用 `user_input[:200]` 提词）；无"战斗实体匹配"分支（`combat_entities`）；其余并发检索精神一致。
- 处置：补/改设计文档（检索来源差异），可选补 combat 分支。

### 6.3 P3 叙事生成（流式 + 长度重试）
- 设计要求：temperature=0.75、stream=True、min/max tokens；长度不足追加续写最多 3 次；**严禁 P3 输出任何 UpdateVariable 指令（由 P4 专门处理）**。
- 实现状态：部分（含职责冲突）
- 证据：`backend/agents/narrator_agent.py:241-371`（`_p3_write` 流式、`_P3_MIN_CHARS=100`、`_P3_MAX_RETRY=2` 即合计 3 次✓、temp 0.85）、`narrator_agent.py:210-213`（P3 基础系统提示反而要求"文末用 `{{SET: key=value}}`/`{{ADD: key=+N}}` 标记状态变化"）
- 差距：①temperature 0.85（设计 0.75）；②**与设计直接冲突**：设计要求 P3 严禁输出变量指令、由 P4 专责，实现却在 P3 提示里主动要求输出 `{{SET/ADD}}` 标记，P4 仅做正则抽取（见 6.4）；变量职责实际落在 P3。
- 处置：补/改设计文档（明确变量标记由 P3 内联产出 + P4 抽取的实际分工），或改实现回归 P4 专责。

### 6.4 P4 变量块（结构化标签）
- 设计要求：temperature=0.1；输出 `<VariableBlock><UpdateAttribute.../><GrantItem.../>...` XML 标签块；解析为 `TavernCommand` 列表；缺项重试最多 3 次（依 `variable_block_preview.expected_updates`）。
- 实现状态：偏离
- 证据：`backend/agents/narrator_agent.py:376-392`（`_extract_patches` 正则匹配 `{{SET|ADD|MUL|DIV|PUSH|POP: key=val}}`）、`narrator_agent.py:416-487`（`_p4_llm_extract` 兜底，temp 0.1✓，输出 `[{cmd,key,value,delta}]` JSON 数组）
- 差距：①输出格式为 `{{CMD:key=val}}` 文本/JSON 数组，**非** `<VariableBlock>/<UpdateAttribute>` XML；②产物是 patch dict 而非 `TavernCommand` 对象（`TavernCommand` 数据类 `state.py:73-82` 定义但 P4 未产出）；③无"依 expected_updates 缺项重试 3 次"机制（P1 无该字段）。
- 处置：补/改设计文档（统一变量格式约定），或补实现 TavernCommand 化与缺项重试。

---

## §7. Agent 扩展接口

### 7.1 AgentNode 抽象基类
- 设计要求：`AgentNode` 含 `name/display_name/system_prompt_id/profile(AgentProfile)/insert_after/replace/tools/before_tool_call/after_tool_call/execute/on_load/on_unload`。
- 实现状态：部分
- 证据：`backend/agents/agent_node.py:35-73`（`AgentNode` 含 `name/display_name/insert_after/replace/tools/execute/__call__`）、`agent_node.py:76-147`（`register_node` + `inject_registered_nodes` 支持 replace/insert_after 注入）
- 差距：**缺** `system_prompt_id`、`profile`(AgentProfile)、`before_tool_call/after_tool_call` 钩子方法、`on_load/on_unload` 生命周期；注入主链路边由 `graph.py:235-247` 配合实现✓。
- 处置：补实现缺失成员，或改设计文档精简 AgentNode 契约。

### 7.2 AgentProfile（权限/LLM 角色配置）
- 设计要求：`AgentProfile{llm_role, tool_permissions, max_tokens, temperature, timeout_seconds, retry_limit}`，来自 `agents.json → roles.*`，各角色用不同模型（GPT-4o-mini / Claude 3.5 Sonnet / Claude Opus / Haiku 等）。
- 实现状态：偏离
- 证据：`backend/agents/llm.py:119-153`（`load_agent_config` 读 `agents.json → agents.*`）、`backend/data/sys_config/agents.json:2-73`（键为 `rules/dm/npc/...` 而非 `roles.rules_checker/...`，且**全部 deepseek-chat**，无多模型分工）；权限 Profile 另在 `backend/agents/permission.py`（`profile_registry`，play/plan/review）
- 差距：①配置结构 `agents` 而非设计的 `roles`；②设计的"各角色差异化模型"未落地（统一 deepseek-chat）；③`AgentProfile` 的 `llm_role/tool_permissions/timeout/retry` 字段未与 LLM 配置整合，权限 Profile 与 LLM 配置是两套独立体系。
- 处置：补/改设计文档（agents.json 实际结构与单模型现状），或补多模型角色映射。

---

## §8. 子 Agent 机制

### 8.1 进程内子 Session（NPC 并发）
- 设计要求：低隔离、`asyncio.gather` 多 NPC 子 Session。
- 实现状态：完整
- 证据：`backend/agents/npc_agent.py:186-190`（每 NPC 独立 tool_loop + gather）、`graph.py:90-94`（npc/world gather）
- 差距：无（命名为节点内并发，非 `create_sub_state` 命名，但机制一致）。
- 处置：无需动作。

### 8.2 独立工具调用隔离（VarAgent / Chronicler）
- 设计要求：中等隔离，`asyncio.shield` 保护变量结算即使取消也完成。
- 实现状态：偏离
- 证据：`backend/agents/var_agent.py:22-30`（try/except 外层兜底，**无 `asyncio.shield`**）
- 差距：用异常兜底替代 `asyncio.shield`；取消传播场景下无"保证完成结算"语义。
- 处置：补实现 shield 或改设计文档。

### 8.3 外部 MCP Agent
- 设计要求：最高隔离，经 MCP stdio 调用外部 Agent（`call_external_agent`）。
- 实现状态：缺失
- 证据：`backend/agents/**` 未见 `call_external_agent` / MCP 子 Agent 调用（grep 无匹配）。
- 处置：补实现（若需要）或改设计文档标注为未来项。

---

## §9. Agent 选型对比
- 设计要求：纯对比表（LangGraph / Part 状态机 / pi loop 三层互补论述）。
- 实现状态：完整（纯论述，无需代码落地；三层均有对应实现见 §1.1）
- 证据：`backend/agents/graph.py`、`tool_loop.py`、`bus`
- 差距：无（概念性章节）。
- 处置：无需动作。

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 5 | §3.3 NPCAgent、§3.x Gacha(相对设计)、§4 AgentState、§8.1 子Session、§9 选型对比 |
| 部分 | 11 | §1.1 三层架构、§2.2 路由、§3.1 Rules、§3.2 DM、§3.4 World、§3.5 Narrator总览、§3.6 Style、§3.7 Var、§3.8 Chronicler、§5.1 tool_loop、§6.2 P2、§6.3 P3、§7.1 AgentNode（注：含13项，下表以主条目计） |
| 偏离 | 7 | §2.1 节点集合、§2.3 并行拓扑、§5.2 Hook接口、§6.1 P1、§6.4 P4、§7.2 AgentProfile、§8.2 shield隔离 |
| 缺失 | 1 | §8.3 外部 MCP Agent |

> 逐条精确计数（共 24 条）：完整 5 · 部分 11 · 偏离 7 · 缺失 1
>
> **整体符合度估计 ≈ 66%**：核心三层骨架（LangGraph 外层 + tool_loop 内层 + Bus/Part 输出）与门禁→叙事→结算→归档主链路均已落地且可运行；扣分集中在 ——
> 1. **图拓扑表达**：npc/world 并行被压成单节点 gather、多出 dice/options 节点、dm 改名，图层面与设计不一致（设计图已过时）。
> 2. **NarratorAgent 四阶段**：P1 输出 schema 大幅简化、P3/P4 变量职责与设计相反（P3 内联 `{{SET}}` 而非 P4 专责 `<VariableBlock>`）、TavernCommand 未真正产出。
> 3. **扩展契约**：AgentNode 缺 profile/system_prompt_id/钩子/生命周期；AgentProfile 多模型角色映射未落地（全 deepseek-chat）。
> 4. **隔离与外部 Agent**：asyncio.shield 与 MCP 子 Agent 未实现。
>
> 多数偏离属"实现先行、设计文档滞后"，建议优先回写设计文档（节点集合/并行拓扑/Narrator 变量分工/agents.json 结构），再择机补齐 narrative_hook、info_matrix、TavernCommand 化等功能缺口。
