# conf_b04 — 设计符合度审计 · 维度 B · 扩展系统

> 审计分片：B04「扩展系统」
> 设计权威：`docs/design/04-extension-system.md`（v0.1.0）
> 实现范围：`backend/extensions/**` + `backend/hooks/**`
> 复审基准日期：2026-06-03 · 只读审计

---

## 0. 关键结论速览

1. **八类扩展点**：7 类有实现入口（工具/Agent/技能/WorldPlugin/MCP/规则/Hook），1 类（PromptFragment 独立 `prompts/*.md`）仅在 loader 有扫描钩子但**无任何内置扩展使用、无消费端真正生效** → 部分。
2. **18 类 hook**：`HookEvent` 枚举层面**定义齐全（实为 20 个枚举值）**，但管线中**实际 fire 触发的仅 9 类**，另 11 类只定义不触发（死事件）。
3. **🔴 严重缺陷**：5 个内置世界中有 **4 个的 `hooks.py`（crossover / infinite_arsenal / gundam_seed / muv_luv）在模块顶层 `from ..hook_protocol import BaseHook` + `from ..registry import hook_registry`，而 `BaseHook` 与 `hook_registry` 在代码库中根本不存在** → 这 4 个世界 Hook 在两条加载路径下都 ImportError，全部静默失败、永不注册。只有 `wuxia/hooks.py`（协议式、无顶层相对导入）真正生效。
4. **manifest.json 字段不统一**：crossover/infinite_arsenal 遵循设计 schema；gundam_seed/muv_luv 偏离（缺 `type`/`min_engine_version`，muv_luv 用 `name` 而非 `display_name`）。

---

## 1. 设计目标与三级目录（§1）

### §1.2 优先级三级目录（内置 < 用户 < 项目）
- 设计要求：`backend(zero_arsenal)/extensions` < `~/.zero-arsenal/extensions` < `.zero-arsenal/extensions`，高优先级覆盖低优先级。
- 实现状态：完整
- 证据：`backend/extensions/extension_loader.py:23-40`（`_BUILTIN_EXT_DIR`/`_USER_EXT_DIR`/`_PROJECT_EXT_DIR`，priority 0/1/2），`discover_extensions()` `:92-101` 按优先级升序取 `candidates[-1]` 最高优先级。
- 差距：实现额外支持 `ZERO_ARSENAL_EXTENSIONS_OVERRIDE` 环境变量追加搜索路径（设计未提，属增强）。
- 处置：补/改设计文档（记录 OVERRIDE 环境变量）。

### §1.2 同名冲突合并规则（data/ 合并、SKILL append）
- 设计要求：WorldPlugin 同名时 `data/` 目录做合并；SKILL `inject_as=append` 追加而非替换。
- 实现状态：缺失
- 证据：`extension_loader.py:92-107` 仅做"整目录取最高优先级"覆盖，无 `data/` 合并逻辑；无 SKILL `append` 合并实现。`registry_builder.py` 注释虽提冲突，但 `discover_extensions` 不实现细粒度合并。
- 差距：设计 §1.2/§3.2 的 5 条细粒度冲突规则（data 合并、SKILL append、Tool/Node/Rule 同 id 替换并保留可追溯记录）均未实现，只有粗粒度整包覆盖。
- 处置：补实现 或 降级设计文档为"整包覆盖（不做合并）"。

### §1.1 可热加载（开发模式修改免重启）
- 设计要求：开发模式下修改扩展文件无需重启。
- 实现状态：完整
- 证据：`backend/main.py:183-189` 调用 `skills.watcher.start_extension_watcher()`（watchfiles），受 `ZERO_ARSENAL_HOT_RELOAD` 控制。
- 差距：无。
- 处置：无需动作。

### §1.3 目录结构总览（含 __registry__.json 自动生成）
- 设计要求：`extensions/` 下各世界目录 + `__registry__.json`（自动生成，勿手编）。
- 实现状态：完整
- 证据：`backend/extensions/__registry__.json`（5 个扩展，`generated_at` 时间戳），`registry_builder.build_registry()` `:26-82` 启动时由 `main.py:191-195` 生成；`registry_builder` 已统一委托 `discover_extensions()` 消除双轨。
- 差距：设计示例目录名为 `crossover/wuxia/infinite_arsenal`，实际还有 `gundam_seed`/`muv_luv`/`web_scraper`/`_template`（属扩充，合理）。
- 处置：补/改设计文档（补列新增世界）。

---

## 2. 八类扩展类型（§2）

### §2.1 工具扩展（Tool Extension）
- 设计要求：`extensions/<name>/tools.py` 暴露 `TOOLS=[ToolDef(...)]`，字段用实现名 `name/handler/permission_required/execution_mode/tags/group/before_hooks/after_hooks`。
- 实现状态：完整
- 证据：`backend/tools/registry.py:60-82` `ToolDef` 字段与设计实现版完全一致（含 `execution_mode`、`before_hooks`、`after_hooks`）；`extension_loader.py:150-156` 读取 `TOOLS`；`main.py:107-111` 注册到 `tool_registry`。各世界 `tools.py` 存在（crossover/wuxia/infinite_arsenal/gundam_seed/muv_luv/web_scraper）。
- 差距：无（字段名对照表已对齐）。
- 处置：无需动作。

### §2.2 Agent 节点扩展（Agent Extension）
- 设计要求：`agents.py` 内 `register_node(MyNode())` 模块级副作用注册，`AgentNode` 含 `name/display_name/insert_after/replace/tools` 与 `execute(ctx: TurnContext)`；`inject_registered_nodes(builder)` 注入图。
- 实现状态：完整
- 证据：`backend/agents/agent_node.py:88-124` `list_registered_nodes`/`inject_registered_nodes`（支持 replace 与 insert_after 重连边）；`backend/agents/graph.py:52,244` `inject_registered_nodes(builder, main_edge_map)`；`infinite_arsenal/agents.py:92-186` `GachaAgent(AgentNode)` + `AGENT_NODES` + `register_node(GachaAgent())`。
- 差距：`extension_loader.py:159-163` 读取 `AGENT_NODES` 列表，而设计正文主推"导入即副作用注册"；infinite_arsenal 两者都做（模块顶层 `register_node` + `AGENT_NODES`），与 `main.py:113-115` 的 `register_node(_node)` 叠加 → GachaAgent 可能被注册两次（`register_node` 内部应去重，需关注）。
- 处置：补/改设计文档明确单一注册路径；核实 `register_node` 去重。

### §2.3 技能扩展（Skill Extension）
- 设计要求：`extensions/<name>/skills/*.md`，SKILL.md frontmatter（id/version/trigger/condition/inject_as/phases/priority/applicable_worlds/requires…），按 trigger 激活。
- 实现状态：部分
- 证据：`extension_loader.py:184-191` 扫描 `skills/*.md` 填入 `loaded.skills`；各世界存在 skills 文件（如 `crossover/skills/infinite_flow_rules.md`、`wuxia/skills/wuxia_cultivation.md`）。
- 差距：`main.py` 扩展加载循环（:105-152）**未见**将 `loaded.skills` 注入任何 SkillRegistry/active_skills；技能注入实际由 WorldPlugin.get_rules_skills 与 prompts 链路承担，独立 SKILL.md frontmatter 的 trigger/condition/inject_as 字段是否被解析消费未在本分片证实。
- 处置：补实现（接线 skills 消费）或补/改设计文档说明实际技能注入路径。

### §2.4 世界插件扩展（WorldPlugin）
- 设计要求：`plugin.py` 提供 `WorldPlugin`（key/name/description/attribute_schema/item_types/economy_config/permission_overlay/mcp_servers + on_session_init/on_turn_start/on_turn_end/get_rules_skills/get_character_template/get_effective_attributes）。
- 实现状态：完整
- 证据：`backend/extensions/plugin.py:55-187` 与设计实现版逐字段对齐（含 `AttributeDef`/`ItemType`/`EconomyConfig`、三个生命周期钩子、`get_effective_attributes`、`apply_permission_overlay`、`apply_to_registry`）；`main.py:126-135` 注册到 `plugin_registry`。
- 差距：设计 §6.1 最小示例用 `class ModernCityPlugin(WorldPlugin)` 子类 + 类属性 `name/display_name`，而实现是 `@dataclass` 需实例化 `PLUGIN = WorldPlugin(key=..., name=...)`；设计示例 `from core.world_plugin import` 路径与实际 `backend.extensions.plugin` 不符。
- 处置：补/改设计文档（统一 §6.1 示例为 dataclass 实例化 + 正确 import 路径）。

### §2.5 提示词片段扩展（PromptFragment）
- 设计要求：`extensions/<name>/prompts/` 下 Markdown，frontmatter `fragment_id/inject_into/position/condition/priority`。
- 实现状态：缺失（事实上未启用）
- 证据：`extension_loader.py:184-191` 扫描 `prompts/**/*.md`，`main.py:136-151` 用 `load_prompt_fragment_file` 注册到 PromptRegistry；但 `__registry__.json` 全部 `has_prompts: false`，**无任一内置扩展含 `prompts/` 目录**，loader 扫描结果恒为空。
- 差距：接线存在但无数据；提示词实际通过 `WorldPlugin.system_prompt_fragments`（plugin.py:142-161）注入，与 §2.5 设计的独立 `prompts/*.md` 文件机制并行存在、未统一。
- 处置：补/改设计文档（注明片段优先走 WorldPlugin.system_prompt_fragments）或补一个 prompts/ 示例验证链路。

### §2.6 MCP 服务扩展
- 设计要求：`plugin.py` 的 `mcp_servers` 字段声明，加载 WorldPlugin 时自动启动并合并工具到 ToolRegistry。
- 实现状态：部分
- 证据：`plugin.py:96` `mcp_servers` 字段存在；`plugin.py:194-204` `WorldPluginRegistry.register` 调用 `mcp_bridge.register_plugin_mcp_servers(plugin.key, plugin.mcp_servers)`。
- 差距：设计示例字段为 `MCPConfig(server_id/command/args/env)`（stdio 进程），实现注释格式为 `{"name","url","enabled"}`（HTTP URL），两套配置 schema 不一致；且无内置扩展实际声明 mcp_servers，端到端"自动启动+工具合并+权限继承"未证实。
- 处置：补/改设计文档统一 MCP 配置 schema；补实现端到端验证。

### §2.7 规则扩展（Rules Extension）
- 设计要求：`extensions/<name>/rules/*.md`，frontmatter `rule_id/trigger/applicable_agents/priority/description`，always 预置、on_demand API 激活。
- 实现状态：部分
- 证据：`backend/extensions/rules_loader.py:18-40` `RuleEntry`/`RuleRegistry`，扫描 `extensions/*/rules/*.md`；`main.py:168-173` 启动加载；各世界存在 rules（如 `crossover/rules/economy_rules.md`、`infinite_arsenal/rules/weapon_rules.md`）。
- 差距：`RuleEntry` 字段为 `rule_id/extension_key/trigger/applicable_agents/priority/enabled`，**无设计要求的 `on_demand` 激活 API**（设计 §2.7 表列 `activate_rule(rule_id)`）；on_demand 触发链路缺失。
- 处置：补实现 on_demand 激活 API 或降级设计文档。

### §2.8 Hook 扩展（接口定义）
- 设计要求：`extensions/<name>/hooks.py`，实现 `ExtensionHooks` Protocol，富类型签名（`before_tool_call(tool_call, state, agent_name) -> BeforeToolAction` 等）。
- 实现状态：偏离
- 证据：`backend/extensions/hook_protocol.py:13-100` `ExtensionHooks` Protocol 统一改为 `async def xxx(self, ctx: dict) -> dict` 单 ctx 字典签名（非设计的多参数+强类型返回 `BeforeToolAction/AfterToolAction/VarUpdate/NPCResponse`）。
- 差距：放弃了设计的强类型 Hook 契约（block/terminate/replace_result/返回 None 跳过等语义），改为弱类型 ctx dict + `allow`/`skip` 约定；`HookManager.fire`（hook_manager.py:169-193）也只做 `context.update(result)`，**不实现 block 短路/terminate 终止**逻辑。
- 处置：补/改设计文档（§2.8/§5 改为 ctx-dict 协议）或补实现短路语义。

---

## 3. 扩展发现机制（§3）

### §3.1 目录扫描算法（以 manifest.json 为标识）
- 设计要求：扫描三级目录，仅含 `manifest.json` 的目录识别为扩展，`load_extension` 加载 plugin/tools/agents/hooks + 扫描 skills/rules/prompts。
- 实现状态：完整
- 证据：`extension_loader.py:67-110` `discover_extensions`（要求 manifest.json、跳过 `_` 前缀目录）；`:124-201` `load_extension` 加载 5 类组件 + 3 类文件资产，与设计伪代码结构一致。
- 差距：设计伪代码用 `importlib.import_module_from_path`（不存在的 API），实现用 `importlib.util.spec_from_file_location`（正确）；实现额外支持 `PLUGIN` 缺失时自动实例化 `*Plugin` 子类、`HOOKS` 缺失时自动找 `*Hooks` 类（增强）。
- 处置：补/改设计文档（修正伪代码 API）。

### §3.2 冲突解决规则（5 条细则）
- 设计要求：ToolDef/AgentNode/WorldPlugin/SKILL/Rules 同 id 的差异化冲突处理（含 data 合并、SKILL append、可追溯替换记录）。
- 实现状态：缺失
- 证据：`extension_loader.py:92-107` 仅记录"被覆盖"日志，取最高优先级整包；无 5 条细则的差异化合并/追溯实现。
- 处置：补实现 或 降级设计文档。

---

## 4. 内置扩展目录结构（§4）

### §4 目录结构规范（manifest/plugin/tools/agents/hooks/skills/rules/data）
- 设计要求：每个内置世界含 manifest.json + plugin.py + tools.py + (agents.py) + hooks.py + skills/ + rules/ + data/。
- 实现状态：部分
- 证据：crossover 含 manifest/plugin/tools/hooks/skills/rules/data（缺 agents.py，设计标注为"可选"）；infinite_arsenal 含 agents.py（GachaAgent）；wuxia/gundam_seed/muv_luv 结构有出入（gundam_seed/muv_luv 只有 rules 单文件，无 data/，hooks 损坏见 §5）。
- 差距：设计 §4.1 列举的 skills 文件名（world-rules/dice-protocol/shop-evaluation/combat-tactics/purity-check）与实际文件名（infinite_flow_rules/combat_crossover 等）**不一致**；§4.1 列的 `data/world-registry.json`/`shop-catalog.json` 存在，但 rules 文件名（dice-protocol/capability-realism）与实际（economy_rules.md）不符。
- 处置：补/改设计文档（更新为实际文件清单）。

### §4 属性体系（crossover 10 维 / wuxia 8 维）
- 设计要求：crossover `attribute_schema` 10 维（STR…LCK），wuxia 8 维（FLESH…FORTUNE）。
- 实现状态：完整（需以实际 plugin.py 为准，本分片未逐字段比对数值）
- 证据：`crossover/plugin.py`、`wuxia/plugin.py` 存在 attribute_schema；`__registry__.json` 描述"10 维属性"/"8 维属性"。
- 差距：数值上限/default 未逐条核对（建议 B 维度其他分片或后续核）。
- 处置：无需动作（结构层面符合）。

---

## 5. Hook 点全览（§5）— 18 类 hook 实测

### §5 Hook 事件定义齐全度
- 设计要求：§5 表列 14 个 hook 方法；文档头/工程语境称"18 类生命周期事件"。
- 实现状态：完整（定义层）
- 证据：`backend/hooks/hook_manager.py:29-64` `HookEvent` 枚举定义 **20 个枚举值**（含设计 14 类 + `before_turn`/`after_turn`/`on_roll_check`/`on_part_done`/`on_error`/`on_chapter_end` 等扩充），另含 `before_agent`/`after_agent` 两个别名。
- 差距：枚举层超出设计（设计 14，实现 20），属能力增强。
- 处置：补/改设计文档（§5 表补齐到 ~18-20 类）。

### §5 Hook 实际触发（fire）接线度 — 🔴 核心
- 设计要求：18 类 hook 在管线对应位置被触发并影响流程。
- 实现状态：部分（仅 9/18 真正 fire）
- 证据：全仓 `hook_manager.fire(HookEvent.*)` 仅 9 处：
  - `before_turn` → `api/routers/stream.py:149`
  - `after_turn` → `stream.py:184`
  - `on_error` → `stream.py:179`
  - `before_agent_node`（别名 before_agent）→ `agents/agent_span.py:33`
  - `after_agent_node`（别名 after_agent）→ `agent_span.py:53`
  - `on_chapter_end` → `agents/graph.py:124`
  - `before_tool_call` → `agents/tool_loop.py:345`
  - `after_tool_call` → `tool_loop.py:393`
  - `on_roll_check` → `agents/rules_agent.py:278`
- 差距：**以下 11 类只在枚举/映射表中存在、管线中无任何 fire 调用（死事件）**：`on_session_start`、`on_session_end`、`on_session_error`、`before_var_update`、`after_var_update`、`before_npc_response`、`after_npc_response`、`after_narrative_generated`、`after_style_applied`、`before_memory_compress`、`on_part_done`。其中 session/var/narrative/style/memory 系是设计 §5 表中明列且标注了执行位置的 hook，却无触发点。
- 处置：补实现（在 session 生命周期、VarAgent、Narrator/Style、Chronicler 压缩、NPCAgent 处补 fire 调用）。

### §5 内置世界 Hook 加载 — 🔴 严重缺陷
- 设计要求：`extensions/*/hooks.py` 实现协议方法即被自动注册（discover_and_register_hooks）。
- 实现状态：缺失（4/5 世界 Hook 永不注册）
- 证据：
  - `crossover/hooks.py:11-12`、`infinite_arsenal/hooks.py:15-16`、`gundam_seed/hooks.py:11-12`、`muv_luv/hooks.py:11-12` 均在**模块顶层**写 `from ..hook_protocol import BaseHook`（+ 部分 `HookEvent`）与 `from ..registry import hook_registry`。
  - 但 `hook_protocol.py` 只定义 `ExtensionHooks`，**无 `BaseHook`/`HookEvent`**；全仓 Grep `BaseHook|hook_registry` 仅命中这 4 个文件本身，**无 `backend/registry.py`、无 `hook_registry` 定义**。
  - `_template/hooks.py:5-8` 明确警告"禁止在模块顶层使用相对导入（from ..xxx import yyy 会失败）"，正坐实这 4 个文件的导入会失败。
  - 两条加载路径均失败：`extension_loader.load_extension:167-181`（spec 导入无包上下文 → ImportError → `loaded.hooks=None` → `main.py:119` 跳过）与 `hook_protocol.discover_and_register_hooks:146-187`（导入即抛错 → except 静默跳过）。
  - 仅 `wuxia/hooks.py:15` `class WuxiaHooks`（无顶层相对导入、协议式）能被 discover_and_register_hooks 正常注册（on_roll_check / before_tool_call）。
- 差距：4 个世界的全部 Hook（跨界事件、武器损耗、MS/TSF 损伤结算等）实际**从未运行**；这些 hooks.py 还各自定义了从不被调用的 `register_hooks()` 函数（引用同样不存在的 `hook_registry`）。
- 处置：补实现（将 4 个 hooks.py 改为 wuxia 同款无顶层相对导入的协议式纯类，删除 `BaseHook`/`hook_registry` 依赖与 `register_hooks()`）。

### §5 Hook 双重注册（次要）
- 设计要求：每个 hook 注册一次。
- 实现状态：偏离
- 证据：`main.py:118-122` `register_extension_hooks`（id=`ext.{key}.{method}`）与 `main.py:177-178` `discover_and_register_hooks`（id=`ext.{key}.{class}.{method}`）对生效的 wuxia hooks **各注册一次、ID 不同 → 不互相覆盖** → wuxia 的 on_roll_check 等每次会被执行两次。
- 处置：补实现（去重或合并两条注册路径）。

---

## 6. manifest.json 字段规范（§6.1）

### §6.1 manifest 必填字段（id/display_name/version/description/type/min_engine_version/author）
- 设计要求：上述 7 字段。
- 实现状态：偏离（跨扩展不统一）
- 证据：
  - `crossover/manifest.json` / `infinite_arsenal/manifest.json`：含全部 7 字段 + `tags`/`entry_points`（符合）。
  - `gundam_seed/manifest.json:1-16`：缺 `type`、`min_engine_version`；新增非规范字段 `world_keys`/`capabilities`/`default_mode`/`required_extensions`。
  - `muv_luv/manifest.json:1-21`：**用 `name` 而非 `display_name`**（故 `__registry__.json:57` muv_luv 无 display_name），缺 `type`/`min_engine_version`；新增 `world_keys`/`provides`/`requires`/`settings`。
- 差距：四个 manifest 三种 schema，`discover_extensions` 只读 `id`/`display_name`/`description`/`version`，对其余字段无校验，导致漂移无人发现。
- 处置：补/改设计文档统一 manifest schema，并补 manifest 校验（缺字段告警）。

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 8 | §1.2 三级目录、§1.1 热加载、§1.3 注册表、§2.1 工具、§2.2 Agent、§2.4 WorldPlugin、§3.1 扫描算法、§5 Hook 定义齐全 |
| 部分 | 6 | §2.3 技能、§2.6 MCP、§2.7 规则、§4 目录结构、§4 属性体系、§5 Hook 实际 fire（9/18） |
| 缺失 | 4 | §1.2 同名合并、§2.5 PromptFragment 未启用、§3.2 冲突细则、§5 内置世界 Hook（4/5 永不注册） |
| 偏离 | 4 | §2.8 Hook 接口弱类型化、§5 双重注册、§6.1 manifest schema、（§2.2 双重注册路径计入§2.2部分） |

- 条目合计：22
- 整体符合度估计：**约 58%**（完整 8 全计 + 部分 6 折半 = 11/19 有效项 ≈ 58%；缺失/偏离扣分集中在 Hook 触发与内置世界 Hook 加载两处核心缺陷）。

### 核心风险（按严重度）
1. 🔴 4/5 内置世界 `hooks.py` 因 `BaseHook`/`hook_registry` 不存在而永久 ImportError 失败，世界专属结算逻辑（跨界/武器/MS/TSF）全部空转（§5）。
2. 🔴 18 类 hook 仅 9 类被 fire 触发，session/var/narrative/style/memory/npc/part 共 11 类为死事件（§5）。
3. 🟡 manifest schema 三套不统一、PromptFragment/MCP/Rules on_demand 接线缺失（§2.5/§2.6/§2.7/§6.1）。
