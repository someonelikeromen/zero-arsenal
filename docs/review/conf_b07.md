# conf_b07 — 维度 B 设计符合度审计：工具注册表

> 复审基准日期：2026-06-03
> 设计权威：`docs/design/07-tool-registry.md`（v1.0，头部标 "设计稿，待实现"）
> 实现范围：`backend/tools/`（registry.py / builtin_tools.py / mcp_bridge.py / skill_loader.py / __init__.py）+ `backend/agents/permission.py` + `backend/agents/tool_loop.py` + `backend/agents/ask_handler.py`
> 行级证据以当前文件实际内容为准。

---

## 0. 文档状态前置判定

### 文档头部 "状态：设计稿，待实现"

- 设计要求：`07-tool-registry.md:6` 标 "状态：设计稿，待实现"。
- 实现状态：偏离（文档自相矛盾，已实现度远高于"待实现"）
- 证据：`backend/tools/registry.py:1-314` 全量实现；`builtin_tools.py:2223` `_register_all()` 已注册 30+ 工具；`mcp_bridge.py:245` 已实例化；同时文档自身 §3.3 `07-tool-registry.md:466-475` 与 §3.6 `07-tool-registry.md:667-753` 已补录"实现名称对照表"和"第二十八轮补录"，明显反映已落地实现。
- 差距：头部 "待实现" 与文档正文（含实现差异对照）及实际代码严重不符。整体核心机制已实现到 ~80%。
- 处置：补/改设计文档（将头部状态改为 "已实现（部分偏离）"）。

---

## 1. 核心数据结构

### 1.1 ToolContext

- 设计要求：`07-tool-registry.md:37-61` — 字段 `session_id / message_id / turn_id / agent_name / state / bus / ask_permission(Callable) / abort_signal / extra`。
- 实现状态：偏离
- 证据：`backend/tools/registry.py:15-46` — 实现字段为 `session_id / message_id / agent_name / profile_name / turn_index / metadata / turn_ctx / bus / abort_signal`。
- 差距：(a) 设计的 `state` 用 `turn_ctx` + `state_snapshot` 属性替代（registry.py:31-46，语义近似、明确对齐 04 文档）；(b) `turn_id`→`turn_index`(int)；(c) `extra`→`metadata`；(d) **关键缺失** 设计的 `ask_permission` 回调不在 ctx 上 —— 权限交互改由 `ToolRegistry._wait_for_permission`/`ask_handler` 集中处理（registry.py:244-267）。
- 处置：补/改设计文档（将 ctx.ask_permission 回调模型改写为"由 Registry 集中调用 ask_handler"的实际架构）。

### 1.2 ToolResult

- 设计要求：`07-tool-registry.md:79-99` — `content(str|dict) / metadata / part_type / error=None / should_memorize=True / needs_continuation=True`，为所有工具的"标准返回值"。
- 实现状态：偏离（结构存在但形同虚设）
- 证据：`backend/tools/registry.py:49-57` 定义了 `ToolResult`（字段为 `content / data / part_type / should_memorize=False / needs_continuation=False / error=""`），但**所有内置工具 handler 返回纯 dict**（如 `builtin_tools.py:57` 返回 `{"ok": True,...}`），`ToolRegistry.execute` 也返回 dict（registry.py:219-221）。`ToolResult` 在执行链中未被任何 handler 构造或消费。
- 差距：(a) `metadata`→`data`；(b) 默认值反转（`should_memorize` 设计 True / 实现 False，`needs_continuation` 同）；(c) 标准化返回契约未落地，工具返回随意 dict，`part_type`/`should_memorize`/`needs_continuation` 信息实际由 handler 自行发 Part（如 `_write_narrative` builtin_tools.py:683-684）而非通过 ToolResult。
- 处置：补实现（统一 handler 返回 ToolResult）或补/改设计文档（承认实际为 "dict 返回 + handler 自发 Part" 模型）。

### 1.3 ToolDef

- 设计要求：`07-tool-registry.md:114-153` — `id / description / parameters(type[BaseModel]) / default_permission(Literal) / execution_mode / before_hooks / after_hooks / execute(Callable) / group / timeout_seconds / tags`。
- 实现状态：部分（字段齐全但多处改名/放宽）
- 证据：`backend/tools/registry.py:60-101`。
- 差距：(a) `id`→`name`(registry.py:62)；(b) `parameters` 放宽为 `Union[dict, Type]`，dict=JSON Schema 直传（registry.py:68，所有内置工具用 dict 格式），`schema()`/`validate_args()` 兼容两路（registry.py:84-115）；(c) `default_permission`→`permission_required:str`，无 Literal 约束（registry.py:70）；(d) `execute`→`handler`，且签名为 `handler(**args)->dict` 而非设计的 `execute(args, ctx)->ToolResult`（registry.py:69 + execute 调用 registry.py:216）；(e) `timeout_seconds` 默认 15.0（设计 None→全局 30s，registry.py:72）；(f) 多出冗余字段 `requires_permission:bool`（registry.py:74，全代码未见消费，疑似死字段）；(g) `before_hooks/after_hooks/group/tags` 一致存在。
- 处置：补/改设计文档（同步字段命名与 dict-schema 双格式）；可清理 `requires_permission` 死字段。

### 1.4 AgentProfile

- 设计要求：`07-tool-registry.md:163-171` — `agent_name / mode / allowed_groups / permission_overrides(dict[str,str])`。
- 实现状态：偏离（实现更丰富，结构不同）
- 证据：`backend/agents/permission.py:33-90` — `name / description / permissions(list[ToolPermission] glob 规则) / visible_part_types / max_tokens_per_turn / active_tools / allowed_groups / default_permission`。
- 差距：设计的 `permission_overrides` 字典被 glob 模式 `ToolPermission` 列表替代（permission.py:24-31, 51-54），`mode` 由 `name` 承担；新增 `active_tools`（LLM 可见白名单）、`visible_part_types`、`default_permission`。`allowed_groups` 与设计一致并已接线（permission.py:67-89）。
- 处置：补/改设计文档（采用 glob-pattern 权限模型 + active_tools 的实际设计）。

---

## 2. 工具执行链（完整流程）

### 2.1 流程总览（8 步）

- 设计要求：`07-tool-registry.md:179-229` — [1]参数验证 → [2]权限 → [3]before_hooks → [4]execute(超时) → [5]after_hooks → [6]DB写入 → [7]EventBus发布 → [8]返回 runner。
- 实现状态：部分（步骤齐全但拆分在两处、顺序微调）
- 证据：链路实际分布于 `tool_loop._execute_one`（agents/tool_loop.py:247-421）与 `ToolRegistry.execute`（tools/registry.py:163-227）。
- 差距：
  - [1]/[2] 顺序与设计相反：`registry.execute` 先做权限（registry.py:182-198）再 `validate_args`（registry.py:203）；设计要求验证在权限前。且权限实际在 `tool_loop` 已先做一次门控（tool_loop.py:277-323），存在**双重权限检查**（registry 内再查一次，registry.py:184）。
  - [3]before_hooks / [5]after_hooks 在 `tool_loop._execute_one`（tool_loop.py:325-333, 399-407）执行，而非设计描述的 `ToolRegistry.execute` 内部；`registry.execute` 本身**不跑 hooks**。
  - [4]execute+超时 ✓（registry.py:215-218）。
  - [6]DB写入：设计交给 AgentRunner；实现中部分工具自写 Part（如 `_write_narrative` builtin_tools.py:675-682、`_generate_action_options` builtin_tools.py:627-634），Registry 不写 DB（与设计注释 07:1202 一致）。
  - [7]EventBus：`tool_loop` 发 `tool_call`/`tool_result` Part（tool_loop.py:362-381）✓。
- 处置：补/改设计文档（将执行链归位到 tool_loop + registry 双层，标注 validate/permission 实际顺序与双重门控）。

### 2.2 并发执行策略（execution_mode 分组）

- 设计要求：`07-tool-registry.md:233-257` — parallel 工具 `asyncio.gather`，sequential 工具按序执行。
- 实现状态：完整（实现更细致，保序）
- 证据：`backend/agents/tool_loop.py:206-244` `_execute_batch` 按 `execution_mode` 分批，连续 parallel 合并 `asyncio.gather`（tool_loop.py:232-237），sequential 逐个 await（tool_loop.py:240-242），并保持原始顺序。
- 差距：基本无；实现额外保证了批次相对顺序，优于设计示例。注意：所有内置工具未显式设 `execution_mode`，默认 "parallel"（registry.py:75），写操作工具（如 update_character_state）仍按 parallel 处理，存在并发副作用风险（设计意图是写操作 sequential）。
- 处置：补实现（为写类工具显式标 `execution_mode="sequential"`）。

### 2.3 权限询问的 SSE 流程

- 设计要求：`07-tool-registry.md:259-274` — publish `permission.ask` → 前端确认 → POST grant → 回调返回 True。
- 实现状态：完整
- 证据：`backend/agents/ask_handler.py:83-140` `check_permission_and_ask` 发布 `PERMISSION_ASK` 事件（ask_handler.py:109-118），阻塞 `ask.wait()`（ask_handler.py:120）后发 `PERMISSION_GRANTED/DENIED`（ask_handler.py:124-136）；`AskManager.resolve` 由前端 grant 接口触发（ask_handler.py:63-69）。
- 差距：超时值 60s（ask_handler.py:16），设计 §7.2 规定 `PERMISSION_ASK_TIMEOUT=300.0`（07:1243）。且超时语义为 deny（ask_handler.py:35），与 registry.py:266 fail-closed 一致，但 registry.execute 的注释 registry.py:255 写"超时后默认允许（fail-open）"与代码 registry.py:267 `return False` 矛盾（注释陈旧）。
- 处置：对齐超时常量（60→300 或更新文档）；修正 registry.py:255 陈旧注释。

---

## 3. 内置工具完整清单

### 3.1–3.5 设计原始工具（14 个）逐一对照

- 设计要求：`07-tool-registry.md:280-663` 列出 engine(roll_check/load_skill/search_lore)、narrative(write_narrative/spawn_npc/generate_action_options)、character(query_character/edit_character/earn_reward)、economy(open_shop/evaluate_item/purchase_item)、chapter(fork_chapter/consolidate_chapter)。
- 实现状态：完整（含已声明的改名）
- 证据：`builtin_tools.py` 注册 — roll_check(:1630)、load_skill(:1651)、search_lore(:1611)、write_narrative(:1731)、spawn_npc(:1669)、generate_action_options(:1690)、read_character(:1454，对应设计 query_character)、update_character_state(:1469，对应设计 edit_character)、earn_reward(:1709)、open_shop(:1887)、evaluate_item(:1906)、purchase_item(:1925)、fork_chapter(:2027)、consolidate_chapter(:2047)。改名已在 `07-tool-registry.md:466-475` 对照表声明。
- 差距：(a) `evaluate_item` 语义偏离 —— 设计为"三轮物理定星评估"（07:582-597），实现为"LLM 物品市价评估（铜币）"（builtin_tools.py:877-924），文档 §3.6 07:677 已坦白此语义差异；(b) `fork_chapter`/`consolidate_chapter`/`edit_character` 参数 schema 与设计草案不同（已在 07:728-729 标注 "schema 已变"）；(c) `roll_check` 实现为 d10 骰池而非设计的 d20/d100（builtin_tools.py:214-258），且 should_memorize=False 行为通过不发记忆 Part 实现，非 ToolResult 标志。
- 处置：无需动作（文档已声明大部分差异）；`roll_check` 骰制差异建议在 §3.1 加注。

### 3.6 扩展工具清单（第二十八轮补录）

- 设计要求：`07-tool-registry.md:667-753` 列出 query_character_summary / check_skill_trigger / search_memory / get_chapter_summaries / write_journal / get_world_state / update_world_state / query_world_rules / edit_npc_state / query_npc_profile / get_npc_knowledge_scope / update_npc_state / style_check / purity_check / read_chapter / outline_chapter / roll_dice / apply_damage / apply_heal / get_combat_status / roll_hit_location 等。
- 实现状态：完整
- 证据：全部已注册 — query_character_summary(:1748)、check_skill_trigger(:1851)、search_memory(:1497)、get_chapter_summaries(:1514)、write_journal(:1591)、get_world_state(:1547)、update_world_state(:1562)、query_world_rules(:1867)、edit_npc_state(:1762)、query_npc_profile(:1793)、get_npc_knowledge_scope(:1810)、update_npc_state(:1827)、style_check(:1965)、purity_check(:1985)、read_chapter(:1945)、outline_chapter(:2005)、roll_dice(:1530)、apply_damage(:2069)、apply_heal(:2094)、get_combat_status(:2113)、roll_hit_location(:2129)。
- 差距：仅个别 group 标注不一致 —— 文档 §3.6 将 spawn_npc/update_npc_state 等归 group="npc"，但实现中 `query_npc_profile`(:1807)/`get_npc_knowledge_scope`(:1824)/`update_npc_state`(:1845) 标 group="npc"，而 `spawn_npc`(:1668-1685) 与 `edit_npc_state`(:1762-1789) **未设 group**（默认 "general"）；`check_skill_trigger`/`query_world_rules` 标 group="engine"（builtin_tools.py:1864,1881）而非文档默认值。
- 处置：补实现（统一 spawn_npc/edit_npc_state group="npc"）或更新文档 group 标注。

### 3.6+ 文档未涵盖的额外实现工具

- 设计要求：（无 —— 文档未列）
- 实现状态：偏离（正向扩展，文档缺失）
- 证据：`fetch_web_lore`（builtin_tools.py:2147，group="lore"）与 `list_scraper_rules`（builtin_tools.py:2169，group="lore"）已注册，但 §3 全文未提及；另有扩展自动发现机制 `_discover_extension_tools`（builtin_tools.py:2189-2219）扫描 `extensions/*/tools.py` 的 `TOOLS` 列表。
- 差距：两个 Web 爬虫工具 + 扩展自动发现机制为设计外新增。
- 处置：补/改设计文档（在 §3 增列 web/lore 工具与扩展自动发现）。

---

## 4. MCP 工具桥接

### 4.1 MCPToolBridge 类

- 设计要求：`07-tool-registry.md:770-907` — `__init__(mcp_server_url, auth_token)` + httpx；`fetch_tool_list`(POST /tools/list)；`_jsonschema_to_pydantic`；`_build_execute_fn`；`get_tool_defs()` 生成 `id=f"mcp.{name}"`, `default_permission="ask"`, `group="mcp"`；`close()`。
- 实现状态：部分（功能等价，实现路径明显不同）
- 证据：`backend/tools/mcp_bridge.py:28-245`。
- 差距：(a) 改为 **配置驱动**：`__init__` 读 `data/sys_config/mcp.json`（mcp_bridge.py:34-51），而非传入单 URL；(b) `fetch_tool_list` 用 **GET** /tools/list（mcp_bridge.py:66）而非设计 POST；(c) 用 `aiohttp` 而非 httpx（mcp_bridge.py:12-16）；(d) **无 `_jsonschema_to_pydantic`** —— 直接用原始 inputSchema dict 作 parameters（mcp_bridge.py:223-233）；(e) 工具名 `mcp_{server}_{tool}`（下划线，mcp_bridge.py:149）而非设计 `mcp.{name}`（点号）；(f) `default_permission="ask"` ✓（mcp_bridge.py:171,234）但 **group 未设为 "mcp"**（默认 general）；(g) 无 `get_tool_defs()`/`close()`，改用 `register_to_registry()`（mcp_bridge.py:136）/`discover()`（mcp_bridge.py:75）/`register_plugin_mcp_servers()`（mcp_bridge.py:180）；(h) `call_tool` POST 体为 `{"tool", "arguments"}`（mcp_bridge.py:115）而非设计 `{"name", "arguments"}`（07:834）。
- 处置：补/改设计文档（采用 config-driven + aiohttp + 下划线命名的实际桥接设计）；可考虑将 MCP 工具 group 设为 "mcp"。

### 4.2 MCP 工具注册流程（接线验证）

- 设计要求：`07-tool-registry.md:909-930` — 启动时遍历 mcp_servers，bridge.get_tool_defs → registry.register。
- 实现状态：完整（已接线）
- 证据：`backend/main.py:86-92` 启动时 `MCPToolBridge(mcp_config).discover()` + `register_to_registry(tool_registry)`；`api/routers/config.py:179-188` 提供运行时重注册；`extensions/plugin.py:199-201` 为 WorldPlugin 调 `register_plugin_mcp_servers`。
- 差距：连接失败优雅降级（mcp_bridge.py:71-73 返回空列表，回落静态配置 mcp_bridge.py:97-99）✓，符合设计 07:927-928 容错意图；设计 §7.1 的"MCP 网络错误重试 3 次指数退避"（07:1235）**未实现**（call_tool 失败直接返回 error，mcp_bridge.py:132-134）。
- 处置：补实现（MCP 调用重试）或下调设计要求。

---

## 5. 工具权限矩阵

### 5.1 逐工具×模式权限对照

- 设计要求：`07-tool-registry.md:936-952` 矩阵 + §6 mode_rules（07:1031-1053）。
- 实现状态：偏离（play 模式系统性放宽）
- 证据：`backend/agents/permission.py:95-187` 三个内置 Profile。
- 差距：
  - `roll_check` review=deny ✓（review "*"→deny permission.py:181，且不在 active_tools permission.py:163-168）。
  - `write_narrative` play=allow / plan=ask / review=deny ✓（play "*"→allow:114；plan write_*→ask:143；review "*"→deny:181）。
  - **`edit_character`/update_character_state**：设计 play=ask（07:945 "属性修改始终需确认"），**实现 play=ALLOW**（permission.py:109 显式 ALLOW）→ 偏离。
  - **`earn_reward`**：设计 play=ask（07:946），实现 play→"*"=allow（permission.py:114）→ 偏离（§3.6 07:717 已将其登记为 allow）。
  - **`purchase_item`**：设计 play=ask（07:949），实现 play→allow→ 偏离。
  - **`fork_chapter`**：设计 play=ask（07:950），实现 ToolDef permission_required="ask"（builtin_tools.py:2041）但 play profile "*"→allow 覆盖为 allow → 偏离。
  - **`consolidate_chapter`**：设计 play=ask（07:951），实现 permission_required="allow"（builtin_tools.py:2062）+ play allow → 偏离。
  - `spawn_npc`：设计 play=allow ✓；plan/review 经 active_tools 过滤 ✓。
  - `mcp.*`：设计 ask/ask/deny；实现 mcp 工具 permission="ask"，但 play "*"→allow 会把 ask 覆盖为 allow（mcp 工具名 `mcp_*` 不匹配任何 ALLOW 白名单前缀，落到 "*"→ALLOW）→ play 下变 allow，偏离设计 ask。
- 根因：`PLAY_PROFILE` 采用 `default_permission=ALLOW` + 末位 `"*"→ALLOW`（permission.py:98,114），刻意"尽量不打扰"，导致设计矩阵中 play 模式的多处 ask 被统一放行。plan/review 模式与设计基本吻合。
- 处置：补实现（play 模式对 edit/earn/purchase/fork/consolidate/mcp_* 补 ASK 规则）或补/改设计文档（承认 play 模式全 allow 的产品取向）。

### 5.2 权限优先级规则

- 设计要求：`07-tool-registry.md:954-957` — overrides > 模式 > default；**deny 不可被覆盖为 allow（安全底线）**。
- 实现状态：部分
- 证据：`permission.py:46-54` 首个匹配的 glob 规则胜出，无匹配落 `default_permission`；插件 overlay 插入列表头部最高优先级（permission.py:307-323）。
- 差距：(a) "首个匹配胜出 + 头插 overlay" 实现了 overrides>默认的等价优先级 ✓；(b) **"deny 不可上调为 allow" 的安全底线未强制** —— `apply_plugin_overlay`（permission.py:317-322）将 overlay 规则前插，若 overlay 给出 `"*"→ALLOW` 即可覆盖原本的 deny，无任何保护逻辑。
- 处置：补实现（在 overlay/resolve 层加 deny 锁定保护）。

---

## 6. ToolRegistry 类

- 设计要求：`07-tool-registry.md:974-1218` — 单例 `get_registry()`；`register/unregister/get`；`get_tools_for_agent`；`_get_effective_permission`；`to_llm_schema`；`execute`（完整链路）。
- 实现状态：部分
- 证据：`backend/tools/registry.py:118-314`。
- 差距：(a) 单例改为 `ToolRegistry.get_instance()` + 模块级 `tool_registry`（registry.py:121-131, 314），无设计的 `get_registry()` 函数名；(b) `register` ✓（registry.py:136），但**无 `unregister`**（设计 07:994 用于 MCP 断开，registry.py 缺失）；(c) 设计 `get_tools_for_agent(agent, profile)` **不在 Registry**，等价能力由 `AgentProfile.filter_tools`（permission.py:60-90）实现；(d) `_get_effective_permission`→`_resolve_permission`（registry.py:229-242，委托 profile.resolve）；(e) `to_llm_schema`→`to_openai_functions`（registry.py:288-310），并额外剥离 session_id/viewer_agent 注入参数（registry.py:269-286，优于设计）；(f) `execute` 实现权限+验证+超时（registry.py:163-227）但**不含 before/after_hooks 与并发分组**（这些在 tool_loop）。
- 处置：补实现（补 `unregister` 以支持 MCP 热卸载）；补/改设计文档（Registry 与 tool_loop 职责切分）。

---

## 7. 错误处理与超时策略

### 7.1 错误分级

- 设计要求：`07-tool-registry.md:1227-1235` — 7 类错误处理，MCP 网络错误重试 3 次指数退避。
- 实现状态：部分
- 证据：`registry.py:179-227`（tool not found / 参数校验软失败 / 超时 / 通用异常）+ `tool_loop.py:287-323`（权限 deny / ask 拒绝 / 权限异常 fail-closed）+ `ask_handler.py`（ask 拒绝）。
- 差距：(a) 参数验证失败**不返回错误给 LLM**，而是 `validate_args` 静默原样返回（registry.py:113-115），与设计"返回错误让 LLM 修正"相悖；(b) before_hook 失败仅 debug 记录不中止（tool_loop.py:332-333），设计要求"中止返回错误"（07:1231）；(c) MCP 重试 3 次指数退避**未实现**（mcp_bridge.py:132-134 直接返回 error）；(d) 超时/异常处理 ✓。
- 处置：补实现（参数校验失败回传错误、before_hook 失败中止、MCP 重试）。

### 7.2 全局超时配置

- 设计要求：`07-tool-registry.md:1239-1244` — GLOBAL=30 / LONG_RUNNING=120 / MCP=15 / PERMISSION_ASK=300。
- 实现状态：偏离
- 证据：ToolDef `timeout_seconds` 默认 15.0（registry.py:72）；MCP `_timeout` 默认 10（mcp_bridge.py:46）；ASK 超时 60（ask_handler.py:16）；fetch_tool_list 硬编码 5s（mcp_bridge.py:64）。
- 差距：四个常量值全部与设计不符，且无集中式 `GLOBAL_TOOL_TIMEOUT/LONG_RUNNING_TIMEOUT` 常量（设计 07:1240-1241）；耗时工具如 consolidate_chapter 仍用默认 15s（builtin_tools.py:2047-2065 未设 timeout_seconds），低于设计 LONG_RUNNING=120。
- 处置：补实现（引入分级超时常量并为耗时工具设 timeout）或更新文档数值。

---

## 8. 测试策略

- 设计要求：`07-tool-registry.md:1248-1291` — roll_check 单测、sequential 顺序锁验证、permission.ask SSE 到达、MCP 降级、review 全写入 deny。
- 实现状态：缺失（本分片未发现对应测试）
- 证据：`backend/tools/` 内无测试文件；设计示例引用的 `zero_arsenal.tools.engine.create_roll_check_tool`（07:1261）在实现中不存在（工具用 `_register_all` dict 注册，无 engine 子模块）。
- 差距：未见针对工具注册表执行链/权限/MCP 的单元或集成测试（不排除位于仓库其他测试目录，本分片范围未覆盖）。
- 处置：补实现（按 §8 补工具链测试）或在文档标注测试现状。

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 6 | 2.2 并发分组、2.3 SSE询问、3.1-3.5 设计工具、3.6 扩展工具、4.2 MCP注册接线、（5.1 plan/review 部分） |
| 部分 | 7 | 1.3 ToolDef、2.1 执行链、4.1 MCPBridge、5.2 优先级、6 Registry、7.1 错误分级、8 测试 |
| 缺失 | 1 | 8 测试（无对应测试文件，列入缺失） |
| 偏离 | 7 | 0 文档状态、1.1 ToolContext、1.2 ToolResult、1.4 AgentProfile、3.6+ 额外工具、5.1 权限矩阵(play)、7.2 超时 |

> 注：§8 同时具"部分/缺失"特征，按主判定计入缺失；§5.1 整体判偏离（play 模式系统性放宽）。

**整体符合度估计：约 70%。**
- 核心机制（工具注册、按 Agent 过滤、execution_mode 并发、权限 ask SSE、MCP 桥接接线、内置/扩展工具清单）**已完整落地**，工具数量远超设计草案。
- 主要扣分项集中在 **接口契约偏离**（ToolDef/ToolContext/ToolResult 命名与 ToolResult 形同虚设）、**play 模式权限矩阵系统性放宽**、**超时常量与 MCP 重试未对齐**、**deny 安全底线未强制**、**测试缺失**。
- **文档健康度**：设计文档头部 "待实现" 已严重过时（§0），但正文 §3.3/§3.6 的实现对照表维护良好，说明文档已部分跟进实现 —— 建议优先修订头部状态与 §1/§2/§4 的接口/流程描述以匹配代码。
