# conf_b05 — 维度 B 设计符合度审计 · Prompt 架构

> 审计子代理：B05
> 设计权威：`docs/design/05-prompt-architecture.md`
> 复审基准日期：2026-06-03
> 审计范围：`backend/prompts/`、`backend/engine/prompt_assembler.py`、`backend/engine/runtime_data_stream.py`、`backend/skills/`、`backend/tools/skill_loader.py`、`backend/extensions/plugin.py`、扩展内 `*/skills/*.md`

说明：设计文档第 2 节本身附有"设计草案 vs 实现差异对照"表（`05` 第 76–87 行），明确以**实现字段名为准**。本审计据此区分「实现遵循已被认可的差异」与「设计要求仍未落地的真缺口」。

---

## 2. PromptFragment Registry

### 2.1 PromptFragment Dataclass（字段对齐）
- 设计要求：`05:89-190` 定义 Fragment 字段；§2.1 差异表（`05:76-87`）规定实现字段名为 `phase`/`inject_as`(system|user)/`layer`(core/agent/world/skill/runtime)/`content: str`。
- 实现状态：完整
- 证据：`backend/prompts/registry.py:33-52`（`@dataclass PromptFragment`，字段 `id/layer/phase/content/priority/inject_as/condition/trigger/agent_filter/depth/enabled`，含 `matches_phase`/`matches_agent`）
- 差距：完全吻合差异表所述"实现版"字段；`layer` 取代 `source`，`phase` 为 `list[str]`，`inject_as` 承担 system/user 语义，`content` 仅 str。与已认可差异一致。
- 处置：无需动作

### 2.1b token_estimate 字段缺失
- 设计要求：`05:188-189` Fragment 带 `token_estimate: int`，用于 §7 预算控制按片段累计裁剪。
- 实现状态：缺失（偏离）
- 证据：`backend/prompts/registry.py:33-52`（PromptFragment 无 `token_estimate` 字段）；裁剪改为运行时对 `frag.content` 现场估算 `backend/prompts/registry.py:187-202`
- 差距：差异表未列此项为"已认可差异"；实现用 `TokenBudget.estimate_tokens(content)` 代替声明式 token_estimate，功能等价但与设计字段不一致；SKILL.md frontmatter 的 `token_estimate`（`05:999`）也无承接。
- 处置：补/改设计文档（标注 token_estimate 由运行时估算替代）

### 2.2 AgentState 结构
- 设计要求：`05:194-234` 定义 `AgentState` dataclass，作为 condition 求值与动态 content 的运行时状态快照（含 `to_dict()`）。
- 实现状态：缺失（偏离）
- 证据：全仓无 `class AgentState`（grep 无命中）；condition 求值直接接收普通 `dict`，注入为 `{"state": state}` —— `backend/prompts/registry.py:125-131`、`backend/engine/prompt_assembler.py:108-109`（`state={"world_plugin":..., "mode":...}`）
- 差距：无统一的 AgentState 数据类；调用方各自传任意 dict，condition 表达式约定 `state[...]` 访问。功能可用但缺少设计约定的结构化快照与 18 字段契约。
- 处置：补/改设计文档（声明 state 为松散 dict）或补实现 AgentState

### 2.3 PromptFragmentRegistry — condition 沙箱（AST 白名单）
- 设计要求：`05:262-360` 要求 condition 在"受限沙箱中求值，仅允许白名单 AST 节点（`_ALLOWED_AST_NODES`），防止任意代码执行"。
- 实现状态：偏离（安全降级）
- 证据：`backend/prompts/registry.py:125-131` `_evaluate_condition` 仅 `eval(condition, {"__builtins__": {}}, {"state": state})`，**无 AST 解析/白名单校验**；`skill_loader.py:157-176` 同样为裸 `eval`。全仓无 `_ALLOWED_AST_NODES`（grep 无命中）。
- 差距：设计核心安全机制（AST 节点白名单）未实现，仅靠清空 `__builtins__`。condition 来自扩展 .md frontmatter，存在表达式注入风险（虽弱化）。
- 处置：补实现（按 `05:262-269` 加 AST 白名单校验）

### 2.3b Registry 核心方法（注册/过滤/排序/runtime/审计）
- 设计要求：`05:248-260` 职责：注册去重、Phase 过滤、Agent 过滤、condition 求值、priority 排序、token 预算、组装消息。
- 实现状态：完整
- 证据：注册去重 `registry.py:74-90`（同 id 覆盖）；runtime 层 `registry.py:92-123`；过滤流水线 `registry.py:133-204`（enabled/on_demand/phase/layer/inject_as/agent/condition）；priority 升序 `registry.py:185`；token 裁剪 `registry.py:187-202`；审计落盘 `registry.py:322-346`
- 差距：基本职责齐备；`build()` 路径未接 token 裁剪（仅 `get_for_phase` 支持），见下文 5.3。
- 处置：无需动作

---

## 3. 五层提示词架构

### 3.0 层级数量（6 层 → 5 层）
- 设计要求：§3 图（`05:484-498`）画 Layer 0–5 共 6 层（Core/Agent/WorldPlugin/Skills/Runtime/Writing Style）；§2.1 差异表注明"层级从 6 层压缩为 5 层：core/agent/world/skill/runtime"。
- 实现状态：完整（按差异表）
- 证据：`backend/prompts/registry.py:28` `VALID_LAYERS=("core","agent","world","skill","runtime")`；优先级区间 `registry.py:5-6,60-61`
- 差距：与已认可差异一致；Writing Style 不作独立 registry 层，归入 skill 体系（见 3.5）。
- 处置：无需动作

### 3.1 Layer 0 Core（HARD-GATE 始终注入）
- 设计要求：`05:500-585` Core 层含输出格式协议/CoT/骰子约束/OOC，role=system，trigger=always，priority 0–9。
- 实现状态：完整（priority 区间偏离）
- 证据：`backend/prompts/core_prompts.py:18-98` 注册 `core.identity/output_format/dice_contract/output_purity/ooc_boundary/cot_template`，phase=["all"]，inject_as 默认 system
- 差距：内容齐备（含骰子铁律、OOC、纯净度、CoT）；但 priority 用 0–25（`core_prompts.py:212` 注释自承 0-29），超出设计 0–9 区间。CoT 限定 phase=["dm","p1","rules"]（`core_prompts.py:92`）而非全相位，属合理细化。
- 处置：补/改设计文档（priority 区间 0–29）

### 3.2 Layer 1 Agent System Prompt
- 设计要求：`05:589-642` 每 Agent 独立 system prompt，role=system，trigger=always(仅对应 Agent)，priority 10–19；文件路径 `prompts/agents/*.md`。
- 实现状态：部分
- 证据：代码内联片段 `core_prompts.py:104-203`（`agent.rules/dm_gate/narrator_p1/narrator_p3/narrator_p4/style`，priority 100）；另有 `.md` 文件 `backend/prompts/agents/{dm_system,narrator_p1,narrator_p3,narrator_p4,rules_system,style_system}.md`
- 差距：(1) priority 用 100（对齐 registry `agent(100-199)` 实现区间，但偏离设计 10–19）；(2) Agent 片段未用 `agent_filter` 限定，而是用 `phase` 区分（phase=["dm"] 等），与设计"trigger=always 仅对应 Agent"机制不同；(3) `.md` 文件存在但 `core_prompts.py` 内联硬编码同名内容，二者关系/优先未在代码体现（疑重复源）。
- 处置：补/改设计文档（priority 区间 + phase 取代 agent_filter 的机制）

### 3.3 Layer 2 WorldPlugin Rules
- 设计要求：`05:646-734` WorldPlugin 声明 `get_rules_fragments()`/`get_skills_catalog()`，session_init 时注入，role=system，priority 20–49。
- 实现状态：部分（偏离）
- 证据：`backend/extensions/plugin.py:142-161` `apply_to_registry()` 将 `system_prompt_fragments` 注入 world 层，priority `200+i`；`plugin.py:134-136` `get_rules_skills()`（非 `get_rules_fragments`）；调用点 `dm_agent.py:104-105`、`narrator_agent.py:49`、`rules_agent.py:60`、`prompt_assembler.py:188-190`
- 差距：(1) 接口名为 `get_rules_skills()` 返回路径列表，非设计的 `get_rules_fragments()` 返回 Fragment；规则 Fragment 经 `system_prompt_fragments` 注入。(2) priority 200+（对齐 registry world 区间 200–299，偏离设计 20–49）。(3) WorldPlugin 为 `@dataclass`（`plugin.py:55`）而非设计的 ABC 抽象类。(4) `apply_to_registry` 在每次 agent 构建时调用（非仅 session_init），存在重复注册（幂等覆盖，无害但偏离时机）。
- 处置：补/改设计文档（接口名、priority 区间、dataclass 形态、注入时机）

### 3.4 Layer 3 Skills（按需加载）
- 设计要求：`05:738-790` Skills role=user/inject_as=prefix，trigger=on_demand，priority 50–79，经 `load_skill` 工具触发；文件 `skills/<id>.md`。
- 实现状态：部分
- 证据：`load_skill` 工具已实现并注册 `backend/tools/builtin_tools.py:451,1650-1664`；技能发现 `main.py:62-75`（扫描 `backend/skills` 及 `extensions/*/skills`）；SkillRegistry `tools/skill_loader.py:30-228`；实际技能文件位于 `extensions/*/skills/*.md`（如 `crossover/skills/combat_crossover.md`）
- 差距：(1) `_load_skill` 注入为 runtime 层片段（`builtin_tools.py:472` 注释"注入 runtime Prompt 层"）而非 Layer 3 skill 层 priority 50–79；(2) 设计的 `skills/combat/combat-narration.md` 等预置目录（`05:781-790` 8 个 Skill）**不存在**，实际仅扩展内若干（combat_crossover/wuxia_cultivation/arsenal_* 等）；(3) `backend/skills/` 目录无任何 SKILL.md，仅 watcher.py/writing_styles.py，SKILLS_DIR 扫描基本为空。
- 处置：补实现（落地预置 Skill 目录 + 注入层级对齐）或补/改设计文档

### 3.5 Layer 4 Runtime Dynamic
- 设计要求：`05:794-823` Runtime 每回合重建，role=user/inject_as=prefix，priority 80–99，内容由动态 content 函数产生（BackendDataStream）。
- 实现状态：完整（priority 偏离）
- 证据：`register_runtime()` `registry.py:92-123`（默认 priority 450，对齐 runtime 区间 400+）；BackendDataStream 注入 `prompt_assembler.py:122-141`、`dm_agent.py:128+`；动态内容 `runtime_data_stream.py:204-217`
- 差距：内容动态生成、仅 dm/p3/narrator 相位注入、user 前缀包裹 `<backend_data_stream>` 均落地；priority 450（实现 runtime 区间）偏离设计 80–99（已认可差异）。设计的"动态 content 函数挂在 Fragment 上"由 `register_runtime` + 直接拼接代替（content 仍 str）。
- 处置：无需动作

### 3.5b Layer 5 Writing Style（文风层）
- 设计要求：`05:827-888` 文风 role=user/inject_as=standalone，trigger=always(会话配置决定)，priority 100+，agent_filter=narrator_agent，phase=p3，扫描 `writing-styles/` 37+ 文件。
- 实现状态：部分（偏离）
- 证据：`backend/skills/writing_styles.py:29-60` 扫描 `data/writing-styles/*.md` 注册为 `SkillMeta`，`trigger="on_demand"`、`phases=["p3"]`、`inject_as="user"`、`priority=200`；文件实存约 37 个（`backend/data/writing-styles/`）
- 差距：(1) 文风作为 Skill（SkillMeta）而非独立 Registry Fragment 层；(2) `trigger=on_demand` 而非设计 `always`（须显式加载才注入）；(3) 无 `agent_filter=["narrator_agent"]` 限定（SkillMeta 无 agent_filter 字段）；(4) 设计的 `load_writing_styles()` 函数与按会话配置 priority 递增机制未实现。
- 处置：补/改设计文档（文风经 Skill 体系 on_demand 注入）

---

## 4. Phase 过滤

### 4.1 四阶段定义（P1/P2/P3/P4）
- 设计要求：`05:894-903` 四阶段 P1 规划(DM)/P2 RAG(非LLM)/P3 叙事(Narrator)/P4 结算(Calibrator)。
- 实现状态：偏离
- 证据：`registry.py:29` `VALID_PHASES=("all","p1","p2","p3","p4","dm")`；实际相位用 agent 命名 `dm/rules/p1/p3/p4/style`（`core_prompts.py:92,108,124,144,160,176,190`）；SKILL.md 用 `narrator/dm`（`combat_crossover.md:5`、`wuxia_cultivation.md:5`）
- 差距：实现相位粒度比设计 4 阶段更细且命名混用（按 agent：dm/rules/style/narrator + 按阶段 p1/p3/p4）。`narrator` 相位未列入 registry `VALID_PHASES`（仅 skill_loader 不校验时可用）。设计的 P1=DM 单一规划阶段被拆为 rules/dm/p1 多节点。
- 处置：补/改设计文档（实际相位枚举与 agent-相位映射）

### 4.2 各层 Phase 可见性矩阵
- 设计要求：`05:907-915` 矩阵规定各层在 P1/P3/P4 的可见性（如 Writing Style 仅 P3）。
- 实现状态：部分
- 证据：Core phase=["all"]（全相位）`core_prompts.py:21`；文风 phases=["p3"] `writing_styles.py:50`；过滤逻辑 `registry.py:153-172`
- 差距：可见性靠各 Fragment 的 `phase` 列表 + `get_for_phase` 过滤实现，方向正确；但因相位命名偏离（4.1），矩阵无法逐格对应（设计 P1 ↔ 实现 dm/rules/p1 三者）。Layer 0 Core 设计 P1/P3/P4 可见、P2 不可见，实现 phase=["all"]（P2 无 LLM 故无影响）。
- 处置：补/改设计文档

### 4.3 Phase 过滤实现 / 4.4 Phase 间数据传递
- 设计要求：`05:919-957` `registry.build(phase, agent_id, state, base_messages)` 按相位构建；`PhaseContext` 在阶段间传递。
- 实现状态：部分
- 证据：`registry.build()` `registry.py:252-320`（签名 `phase, agent_id, state, extra_vars, session_id, audit_log`，无 `base_messages`）；阶段间传递经 `TurnContext`（`agents/state.py`）而非 `PhaseContext`
- 差距：`build()` 无 `base_messages` 参数（不注入历史消息，仅产出 system+user 两条）；无 `PhaseContext` dataclass，改用 TurnContext 贯穿。属实现选型差异。
- 处置：补/改设计文档

---

## 5. SKILL.md 完整格式规范

### 5.1 Frontmatter 字段
- 设计要求：`05:965-1017` 必填 `id/name/phases/trigger/priority/role/inject_as/source`；选填 `condition/agent_filter/token_estimate/version/description/requires/conflicts/tags`。
- 实现状态：偏离（重缺口）
- 证据：解析器 `skill_loader.py:56-92` 仅读取 `name/description/trigger/phases/priority/condition/inject_as/applicable_worlds`，**键为 `name` 非 `id`**，无 `role/source/token_estimate/version/requires/conflicts/tags`；实际文件 `combat_crossover.md:1-7` 仅 5 字段（name/description/trigger/phases/priority），`wuxia_cultivation.md:1-7` 同。
- 差距：(1) 设计必填的 `id/role/source` 在解析与文件中均缺失（用 `name` 兼任 id）；(2) `requires/conflicts/tags/version` 依赖管理与版本字段完全未实现；(3) 新增 `applicable_worlds`（设计未定义）。
- 处置：补实现（解析 id/role/source/version/requires/conflicts）或补/改设计文档至实际最小集

### 5.2 正文五节结构（决策图/铁律/执行流程/集成说明/禁词）
- 设计要求：`05:1019-1078` SKILL.md 正文须含决策图(Mermaid)/铁律[HARD-GATE]/执行流程/集成说明/禁词与风格约束五节。
- 实现状态：缺失
- 证据：实际技能文件无此结构 —— `combat_crossover.md:9-38`（战斗轮次/伤害类型/逃跑/属性表）、`wuxia_cultivation.md:9-45`（境界/内力/学习/骰子/风格），均无 Mermaid 决策图、无 `[HARD-GATE]` 铁律节
- 差距：正文结构规范未被任何实际 SKILL.md 遵循；加载器也不校验正文结构。
- 处置：补实现（模板化 + 校验）或补/改设计文档（降为推荐）

### 5.3 prompt 组装流程（build / assemble）
- 设计要求：`05:376-466,919-935` `registry.build()` 组装并返回 messages；§3 组装为主路径。
- 实现状态：部分（偏离）
- 证据：`registry.build()` 存在 `registry.py:252-320`，但**实际 agent 不调用 `build()`**，改用 `build_system_prompt()`（str）—— `dm_agent.py:106`、`narrator_agent.py:50,220`、`rules_agent.py:62`、`style_agent.py:132`；`prompt_assembler.assemble_messages()` `prompt_assembler.py:144-169` 拼 system + user(数据流) 两条消息
- 差距：(1) 设计的 `build()`（按 inject_as 分组合并）虽实现却近乎死代码，主链路走 `build_system_prompt()` + `assemble_with_data_stream()`；(2) 设计的 prefix/standalone/append 组合（`05:177-183`）从未落地（差异表已认可）；(3) `build()` 不接 token 裁剪（裁剪仅在 `get_for_phase`，而 build 调 get_for_phase 未传 token_budget）。
- 处置：补/改设计文档（明确主路径为 build_system_prompt + assemble_messages，build 为备用）

---

## 6. Backend Data Stream 格式（18 轴）
- 设计要求：`05:1217-1411` 18 轴数据结构 + `RuntimeDataStreamBuilder.build()` 序列化为 `<backend_data_stream>` Markdown，仅 Agent 可见。
- 实现状态：完整
- 证据：`backend/engine/runtime_data_stream.py:148-189`（BackendDataStream 18 轴全字段）；支撑类 HPStatus/BodyPartHP/EnergyPool/RelationshipSnapshot/CombatSnapshot/EnemySnapshot/MemorySnippet/QuestSnapshot/HookSnapshot/EconomySnapshot `runtime_data_stream.py:35-143`；`_render` `runtime_data_stream.py:626-736`（输出 `<backend_data_stream>` + "仅 Agent 可见"注释）；注入 `prompt_assembler.py:122-141`
- 差距：高度吻合，结构与序列化几乎逐字对应 §6.2/§6.3；额外提供 `build_async`/`build_from_dict` 与 DB 兜底（增强非偏离）。
- 处置：无需动作

---

## 7. Token 预算分配
- 设计要求：`05:1416-1469` `TokenBudgetManager`(HARD_BUDGET=8000/RESERVED_OUTPUT/HISTORY_MAX)，`trim_history`/`prioritize_skills`；§7.3 compaction。
- 实现状态：部分（偏离）
- 证据：`backend/prompts/token_budget.py:35-126` `TokenBudget` 提供 `estimate_tokens`/`check_budget`(按 agent 的 DEFAULT_BUDGETS + profile 倍率)/`compress_context`；registry 裁剪 `registry.py:187-202`
- 差距：(1) 类名/API 不同：实现为 per-agent 输出预算（DEFAULT_BUDGETS `token_budget.py:12-23`）+ `compress_context`，无设计的 `HARD_BUDGET=8000`/`prioritize_skills`/`trim_history` 同名方法；(2) §7.3 compaction 设计已自承实现差异（`05:1475-1513` 对照 `agents/compaction.py`），属文档已记录差异。
- 处置：补/改设计文档（Token 预算 API 实测对照）

---

## 8. 提示词版本管理
- 设计要求：`05:1519-1662` 文件路径规范、热更新 `PromptFileLoader`(mtime 缓存)、SKILL `version` 语义化、审计日志 `prompt_log.jsonl`。
- 实现状态：部分
- 证据：审计日志已实现 `registry.py:322-346`（写 `data/logs/prompt_log.jsonl`，env `ZERO_ARSENAL_PROMPT_AUDIT` 开关 `registry.py:24`）；热更新经扩展 watcher `skills/watcher.py`（watchfiles 监视 .py/.md）；`prompts/template_loader.py` 存在
- 差距：(1) 设计的 `PromptFileLoader`(mtime 缓存 + `load_skill` 解析)未按 `05:1560-1614` 实现，热更新走扩展 watcher 整模块 reload；(2) SKILL `version` 字段及 `## 变更历史` 节未实现（见 5.1/5.2）；(3) 审计日志字段（ts/phase/agent/session/frags/chars）较设计 `PromptBuildLog`(turn_index/fragments_skipped/total_token_estimate)简化，无 skipped/turn_index。
- 处置：补/改设计文档 + 视需补 version 追踪

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 6 | 2.1, 2.3b, 3.0, 3.1(内容), 3.5(Runtime), 6 |
| 部分 | 9 | 3.2, 3.3, 3.4, 3.5b, 4.2, 4.3/4.4, 5.3, 7, 8 |
| 偏离 | 5 | 2.1b, 2.2, 2.3(沙箱), 4.1, 5.1 |
| 缺失 | 1 | 5.2 |

> 注：3.1 计为完整（priority 区间偏离单列说明）；统计共 21 个核对条目。

**整体符合度估计：约 62%**

- 强项：Layer 4 BackendDataStream（§6）几乎逐字落地；Registry 字段/过滤/runtime/审计核心机制齐备；Layer 0 Core HARD-GATE 内容完整。
- 真缺口（非"已认可差异"）：
  1. **condition AST 白名单沙箱未实现**（`registry.py:128`、`skill_loader.py:169` 裸 eval）— 设计明列的安全机制（🔴 建议补实现）。
  2. **SKILL.md 格式严重简化**：缺 `id/role/source/version/requires/conflicts/tags`，正文五节结构（决策图/铁律/集成/禁词）无任何文件遵循（§5.1/§5.2）。
  3. **设计预置 8 个 Skill 目录不存在**，`backend/skills/` 无 SKILL.md（§3.4）。
- 多数 priority 区间偏离（0-29/100/200/450）实为对齐 §2.1 差异表的"实现版区间"，属已认可；但 §3 各层小节仍写旧区间（0-9/10-19/20-49/50-79/80-99），建议统一到差异表口径。
- 处置倾向：安全沙箱(2.3)建议补实现；其余以**补/改设计文档**对齐实测为主（设计文档已建立差异表惯例，应延伸覆盖 token_estimate/AgentState/相位枚举/SKILL 最小字段集）。
