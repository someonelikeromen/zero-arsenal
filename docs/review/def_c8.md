# def_c8 · 扩展框架代码缺陷复审（维度 A）

> 复审基准日期：2026-06-03　子代理 C8　只读复审
> 范围：`backend/extensions/{plugin,registry_builder,rules_loader,hook_protocol,extension_loader}.py` + `backend/extensions/_template/*`
> 方法：逐文件通读 + 跨文件行级核实消费方/注册路径

---

## 旧报告条目逐条判定

### STUB-09 · WorldPlugin 基类 get_rules_skills / get_character_template 返回空
- 状态：🔄已变化
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/plugin.py:134-140`
- 证据：`get_rules_skills` 基类 `return []`，但已被真实插件覆写（`infinite_arsenal/plugin.py:44`、`wuxia/plugin.py:29`、`crossover/plugin.py:41`）并被消费（`agents/rules_agent.py:89 world_rules = plugin2.get_rules_skills()`）；而 `get_character_template`（plugin.py:138-140 `return {}`）**无任何插件覆写、无任何消费方**（`characters.py:181` 的同名函数是无关 API 路由）。
- 修复方向：`get_rules_skills` 部分已修复无需动作；`get_character_template` 要么接入会话初始化角色卡生成、要么删除该死接口。

### M-01 · registry_builder `_scan_extension_dir` 恒 return []
- 状态：✅已修复
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/extensions/registry_builder.py:99-101`
- 证据：`build_registry` 已改为委托 `discover_extensions()`（registry_builder.py:36-37），`_scan_extension_dir` 全仓库无任何调用方，仅作废弃签名保留 `return []`，不再影响注册表生成。
- 修复方向：可直接删除该死函数以消除误导；不删亦无功能风险。

### M-02 / R-M11 · plugin.py 权限 overlay 失败 `pass`
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/plugin.py:186-187`
- 证据：`apply_permission_overlay` 末尾 `except Exception: pass`，任何 import/profile 解析错误被静默吞掉；调用方 `main.py:207` 在 try 外层亦只 `_log` 不抛，配置错误无法暴露。附带：`main.py:206` 每次启动对 play/plan/review 三档 `insert(0,...)`，热重载场景会重复堆叠权限规则（plugin.py:183）。
- 修复方向：至少 `logger.warning(...)` 记录异常；overlay 应幂等（按 pattern 去重后再插入）。

### M-07 · hook_protocol Protocol 方法体为 `...`
- 状态：✅已修复（设计可接受）
- 类别：stub
- 严重度：🟢次要
- 位置：`backend/extensions/hook_protocol.py:22-100`
- 证据：`ExtensionHooks` 为 `@runtime_checkable Protocol`，18 个方法体 `...` 属接口声明的正确写法，实现由各扩展 hooks.py 提供（`wuxia/hooks.py` 等）。
- 修复方向：无需动作。

### T-D01 · rules_loader on_demand 规则永不注入
- 状态：🔄已变化
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/rules_loader.py:65-91`
- 证据：`build_injection_block` 已新增 `on_demand_ids` 入参并能拼入 `trigger=on_demand` 规则（rules_loader.py:77-85），但**全部三个调用方都不传该参数**：`rules_agent.py:98 build_injection_block("rules")`、`dm_agent.py:122 build_injection_block("dm")`、`prompt_assembler.py:78 build_injection_block(phase)`。因此 on_demand 规则在实际管线中仍永不注入。
- 修复方向：在 RulesAgent/编排层根据玩家行动或 LLM 请求计算 `on_demand_ids` 并透传，否则 `trigger=on_demand` 形同虚设。

### T-D02 · rules_loader YAML 未加载 default_permission，始终 DENY
- 状态：✅已修复（条目不适用本文件）
- 类别：—
- 严重度：🟢次要
- 位置：`backend/extensions/rules_loader.py:107-161`
- 证据：现行 rules_loader **完全不涉及 AgentProfile / default_permission / DENY 逻辑**；frontmatter 仅解析 `trigger/applicable_agents/priority/enabled/title`（rules_loader.py:142-155）。原条目所述机制在本文件不存在（疑误挂载或已迁出）。相关真实隐患见 NEW-C8-07（`enabled` 降级解析）。
- 修复方向：无需动作（核实归属后可关闭该条）。

### T-D03 · PyYAML 不可用时简易 key:value 解析
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/rules_loader.py:117-124`
- 证据：`except Exception:` 降级为逐行 `partition(":")`，丢失类型与结构：`applicable_agents: [rules, dm]` 会被存成裸字符串 `"[rules, dm]"`（后续 split 得到 `["[rules"," dm]"]`），`enabled: false` 被存成字符串 `"false"`（真值 → 规则无法被禁用，见 NEW-C8-07）。
- 修复方向：将 PyYAML 列为硬依赖并去掉脆弱回退；或回退分支显式处理 list / bool / int。

---

## 新发现问题

### NEW-C8-01 · `_template` 示例工具泄漏进运行时
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:2203` × `backend/extensions/_template/tools.py:28-42`
- 证据：`_discover_extension_tools` 用 `ext_root.glob("*/tools.py")` 扫描，**未过滤 `_` 前缀目录**，会命中 `_template/tools.py` 并把演示工具 `template_example` 注册进全局 `tool_registry`。这与 `extension_loader.discover_extensions`（loader.py:79 跳过 `_` 且要求 manifest）行为不一致——骨架工具被当成生产工具暴露给 Agent。
- 修复方向：glob 后过滤 `parent.name.startswith("_")`，或统一改用 `discover_extensions()` 的发现结果。

### NEW-C8-02 · `_template` 钩子泄漏进运行时
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/hook_protocol.py:146` × `backend/extensions/_template/hooks.py:33-45`
- 证据：`discover_and_register_hooks` 用 `ext_root.glob("*/hooks.py")`（hook_protocol.py:146）同样不过滤 `_` 目录，会实例化 `TemplateHooks()` 并把 `on_turn_end` 注册为真实生命周期钩子，每回合空转执行骨架代码。
- 修复方向：同 NEW-C8-01，发现阶段过滤 `_` 前缀目录。

### NEW-C8-03 · 内置扩展钩子被双重注册
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/main.py:119-122` 与 `backend/main.py:177-178`
- 证据：启动时两条独立路径都注册扩展钩子——`load_all_extensions()` → `hook_manager.register_extension_hooks`（hook_id=`ext.{key}.{method}`，hook_manager.py:157）与 `discover_and_register_hooks()`（hook_id=`ext.{key}.{cls}.{method}`，hook_protocol.py:172）。两者 id 不同故 HookManager 不会去重，**同一内置扩展（如 wuxia）的同一钩子方法会被触发两次**。
- 修复方向：二选一保留单一注册路径（建议统一走 tier-aware 的 `load_all_extensions`），删除 `discover_and_register_hooks` 调用。

### NEW-C8-04 · hook_protocol / rules_loader 只扫描内置目录，忽略 user/project 三级覆盖
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/hook_protocol.py:112` 与 `backend/extensions/rules_loader.py:129`
- 证据：两者均硬编码 `ext_root = Path(__file__).parent`（仅 `backend/extensions/`），与 `extension_loader._get_search_paths`（loader.py:28-40 含 `~/.zero-arsenal`、`.zero-arsenal`、override）的三级发现机制不一致。结果：用户级/项目级扩展的 `hooks.py`、`rules/*.md` 永不加载。
- 修复方向：让 hook/rules 扫描复用 `discover_extensions()` 的 bundle 路径，统一三级优先级。

### NEW-C8-05 · 插件自动实例化兜底对无默认值的 WorldPlugin 必然失败
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/extension_loader.py:141-145` × `backend/extensions/plugin.py:71-73`
- 证据：当扩展未导出 `PLUGIN` 时，loader 退化为遍历 `name.endswith("Plugin")` 并 `obj()` 无参实例化。但 `WorldPlugin` 是 dataclass 且 `key/name/description` 无默认值（plugin.py:71-73），`obj()` 必抛 `TypeError`；且该匹配还会先扫到被 import 进命名空间的基类 `WorldPlugin` 本身。该兜底路径对“类定义型”插件不可用。
- 修复方向：兜底匹配排除基类、要求子类提供可无参构造或要求字段默认值；或在 README/模板中强制 `PLUGIN = ...` 导出（当前模板已正确导出，故现网插件未触发）。

### NEW-C8-06 · hook 发现盲目实例化模块内所有类
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/extensions/hook_protocol.py:159-166`
- 证据：`for attr_name in dir(module): ... obj()` 会对 hooks.py 中**任何**类尝试无参实例化（含 import 进来的第三方类），失败仅 `except: continue`。逻辑能工作但有副作用风险（实例化带副作用的类）与噪声。
- 修复方向：约定仅扫描类名以 `Hooks` 结尾、或显式读取 `HOOKS` 导出（与 extension_loader 一致）。

### NEW-C8-07 · 简易 frontmatter 回退使 `enabled: false` 失效
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/rules_loader.py:120-122,154`
- 证据：PyYAML 缺失时 `meta[k]=v.strip()` 得到字符串；`RuleEntry(enabled=meta.get("enabled", True))`（行 154）拿到 `"false"`（非空字符串恒真），导致被标记停用的规则仍被当作 enabled 注入。
- 修复方向：回退分支显式将 `"true"/"false"` 转 bool（int 同理已用 `int(...)` 包裹 priority，但 enabled 未处理）。

### NEW-C8-08 · main.py 用 LoadedExtension 不存在的 `.key` 取扩展键
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/main.py:121` × `backend/extensions/extension_loader.py:52-64`
- 证据：`getattr(_ext, "key", "")` 中 `LoadedExtension` 只有 `ext_id` 字段（loader.py:55），无 `key`，故恒取空串回退到 `__module__`，导致钩子 ext_key 标注不准（不影响功能，仅影响 hook_id 可读性/去重判断）。
- 修复方向：改为 `_ext.ext_id`。

---

## `_template` 骨架可用性评估
- **结论：可直接复制使用**。manifest.json 字段完整、README 说明清晰、plugin/tools 采用 `try 相对导入 / except backend.* 绝对导入` 双路兜底（plugin.py:12-15、tools.py:13-16），hooks.py 自包含且无参可实例化、显式导出 `HOOKS`/`PLUGIN`/`TOOLS`，符合 loader 约定。
- **唯一隐患**：骨架本身被 glob 型发现路径误加载（NEW-C8-01/02）——这是发现端缺陷而非骨架缺陷，骨架内容无需修改。

---

## 小计

| 维度 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 3 | M-01、M-07、T-D02 |
| 🔄已变化 | 2 | STUB-09、T-D01 |
| ⚠️仍存在 | 2 | M-02/R-M11、T-D03 |
| 🆕新发现 | 8 | NEW-C8-01 ~ NEW-C8-08 |

- 🔴核心：0　🟡降级：7（STUB-09、M-02、T-D01、NEW-C8-01~05）　🟢次要：8
- 关键风险集中在「glob 型发现路径与 tier-aware loader 行为漂移」：`_template` 工具/钩子泄漏（C8-01/02）、内置钩子双注册（C8-03）、user/project 层钩子与规则丢失（C8-04）。
