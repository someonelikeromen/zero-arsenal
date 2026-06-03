# 代码缺陷复审 — 分片 C9（6 个世界扩展）

> 复审基准日期：2026-06-03
> 范围：`backend/extensions/{muv_luv,gundam_seed,wuxia,crossover,infinite_arsenal,web_scraper}`
> 方法：逐文件通读 plugin.py / tools.py / hooks.py / agents.py / manifest.json，行级证据；只读复审。

---

## 一、旧报告条目复核

### STUB-04 · muv_luv：PromptFragment 与 apply_to_registry dict 不兼容；无 tools/hooks/agents
- 状态：✅已修复（PromptFragment 部分）/ 🔄已变化（组件部分）
- 类别：stub
- 严重度：🟢次要
- 位置：`backend/extensions/plugin.py:145-161`、`backend/extensions/muv_luv/plugin.py:89-112`
- 证据：基类 `apply_to_registry` 现已分支处理 `isinstance(frag_data, PromptFragment)` 直接注册，dict 走兼容路径；muv_luv 改为导出 `PLUGIN = WorldPlugin(...)` dataclass 实例，兼容问题消除。tools.py / hooks.py 已新增（hooks 见 NEW-C9-01），agents.py 仍不存在（可接受）。
- 修复方向：无需动作（仅 hooks 死代码另行处理）。

### STUB-05 · gundam_seed：同 STUB-04 + manifest 用 plugin_id 非 id + get_skill_catalog 扫描不存在的 skills/ 恒返回 []
- 状态：🔄已变化（拆为三项）
- 类别：stub / dead
- 严重度：🟡降级
- 位置：`backend/extensions/gundam_seed/manifest.json:2`、`backend/extensions/gundam_seed/plugin.py:47-57`
- 证据：①PromptFragment 兼容已修复（同 STUB-04）；②manifest 现为 `"id": "gundam_seed"`（非 plugin_id）✅；③`get_skill_catalog()` 仍 `glob("skills/*.json")`，而 gundam_seed 目录下**无 skills/ 子目录**（仅 rules/），恒返回 `[]` —— 该子项⚠️仍存在（死方法）。
- 修复方向：删除 get_skill_catalog 或补 skills/ 目录；plugin 类属性 `plugin_id/display_name` 与基类 `key/name` 命名不一致，建议统一。

### STUB-06 · infinite_arsenal/agents.py 硬编码 _ACG_ITEMS
- 状态：✅已修复
- 类别：stub
- 严重度：🟢次要
- 位置：`backend/extensions/infinite_arsenal/agents.py:24-65`
- 证据：`_load_acg_items()` 从 `data/acg-source-registry.json` 读取并按 category 索引；硬编码字典降为加载失败时的兜底种子库。
- 修复方向：注意 `estimated_tier = min(3, max_tier)`（agents.py:38）把所有条目默认压到 3 星，非 3 星落点只能走模糊/随机匹配，建议按 tier_caps 分布。

### STUB-07 · infinite_arsenal/draw_gacha 只生成落点框架
- 状态：✅已修复（设计如此且已接线）
- 类别：unwired→已接线
- 严重度：🟢次要
- 位置：`backend/extensions/infinite_arsenal/tools.py:280-295`、`backend/agents/tool_loop.py:409-416`、`backend/agents/state.py:156`
- 证据：draw_gacha 返回 results 落点；tool_loop 在 after_tool_call 后将 `result["results"]` 写入 `ctx.turn_ctx.gacha_pending`；GachaAgent.execute 消费 gacha_pending 并发货写库。链路完整。
- 修复方向：无需动作。

### STUB-08 · infinite_arsenal/_POOL_CATALOG 内联未读 pool-catalog.json
- 状态：✅已修复
- 类别：stub
- 严重度：🟢次要
- 位置：`backend/extensions/infinite_arsenal/tools.py:200-232`
- 证据：`_load_pool_catalog()` 从 `data/pool-catalog.json` 读取 pools，内联 dict 降为加载失败兜底。
- 修复方向：无需动作。

### STUB-10 / STUB-11 · crossover / infinite_arsenal 无 hooks.py
- 状态：🔄已变化（文件已建但失效，见 NEW-C9-01）
- 类别：stub / dead
- 严重度：🔴核心
- 位置：`backend/extensions/crossover/hooks.py:11-12`、`backend/extensions/infinite_arsenal/hooks.py:15-16`
- 证据：两文件已新增，但顶部 `from ..hook_protocol import BaseHook` / `from ..registry import hook_registry` 均为不存在的符号/模块，导入即崩溃 → 钩子永不注册（详见 NEW-C9-01）。
- 修复方向：见 NEW-C9-01。

### STUB-13 / STUB-14 · muv_luv / gundam_seed 无 tools/agents/hooks
- 状态：🔄已变化
- 类别：stub / dead
- 严重度：🟡降级
- 位置：`backend/extensions/muv_luv/tools.py:139`、`backend/extensions/gundam_seed/tools.py:126`、各 `hooks.py`
- 证据：两者 tools.py 均已实现并暴露 `TOOLS`（muv_luv: query_tsf_status/beta_threat_assessment；gundam_seed: coordinator_check/query_ms_status），经 `_discover_extension_tools()` 自动注册可用；hooks.py 已新增但失效（NEW-C9-01）；agents.py 仍不存在（可接受）。
- 修复方向：修复 hooks 导入即可。

### T-D14 · web_scraper：无 session_id/world_id 时不写库但返回 ok:True
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/web_scraper/tools.py:78-103,117-123`
- 证据：`_one()` 仅在 `world_id` 或 `session_id` 非空时写库，二者皆空时 `written=0` 但仍 `return {"url":..., "ok": True, ...}`，顶层亦 `return {"ok": True, ...}` —— 抓取+LLM 提炼成本已花费却静默丢弃，调用方误以为成功。
- 修复方向：二者皆空时返回 `ok:False` 或顶层标记 `persisted:false` 警告。

### T-D18 · crossover/tools.py 预设 15 条事件 random.choice 非 LLM
- 状态：🔄已变化（LLM 优先 + 预设兜底）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/crossover/tools.py:139-173`
- 证据：`_random_crossover_event` 先调 `llm_complete` 生成情境事件（generated_by="llm"），异常时才 `random.choice(_CROSSOVER_EVENTS)`（generated_by="preset"）。15 条预设降为兜底。
- 修复方向：无需动作（注：hooks.py 内的 `_CROSSOVER_EVENTS` 仍是纯 random，但该 hook 已死，见 NEW-C9-01）。

### T-D19 · infinite_arsenal 锻造固定材料映射 + random
- 状态：⚠️仍存在（LLM 路径已加但失效）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/infinite_arsenal/tools.py:74`
- 证据：`_forge_weapon` 已加 LLM 优先分支，但其导入写作 `from ....agents.llm import llm_complete`（**4 个点**），模块以 `backend.extensions.infinite_arsenal.tools` 加载时 4 点越过顶层包 → `ImportError`，被 `except` 吞掉，**每次都降级到 `_MATERIAL_TO_TYPE` 固定映射 + `random.randint`**。详见 NEW-C9-02。
- 修复方向：改为 3 个点 `from ...agents.llm import llm_complete`（与 crossover/tools.py:145 一致）。

### T-D20 · wuxia spar_challenge 直接接受 outcome 参数无骰子
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/wuxia/tools.py:177-190,236-238`
- 证据：`outcome` 为空时执行 `player_roll=randint(1,20)` 对 `opponent_roll=randint(1, opponent_level*2)` 的骰子判定，结果含 `dice` 字段。保留 outcome 参数供 DM/LLM 显式裁定（合理）。
- 修复方向：无需动作。

### STUB-T11 · web_scraper 是否在 __registry__.json 中注册
- 状态：⚠️仍存在（注册表遗漏，但工具可用）
- 类别：unwired
- 严重度：🟢次要
- 位置：`backend/extensions/__registry__.json:4-74`、`backend/extensions/web_scraper/`（无 manifest.json）
- 证据：__registry__.json 仅列 crossover/gundam_seed/infinite_arsenal/muv_luv/wuxia 五项，**无 web_scraper**。因 `discover_extensions()` 以 manifest.json 为扩展标识，而 web_scraper 目录无 manifest.json，故被注册表忽略。但其 tools 经 `builtin_tools._discover_extension_tools()`（按 `*/tools.py` 扫描）仍可注册可用。
- 修复方向：补 `web_scraper/manifest.json`，使其纳入统一注册/治理体系。

---

## 二、新增问题（NEW-C9-xx）

### NEW-C9-01 · 4 个世界 hooks.py 因错误导入全部失效（死钩子）
- 状态：🆕新发现
- 类别：dead / unwired
- 严重度：🔴核心
- 位置：`backend/extensions/muv_luv/hooks.py:11-12`、`gundam_seed/hooks.py:11-12`、`infinite_arsenal/hooks.py:15-16`、`crossover/hooks.py:11-12`
- 证据：四者均 `from ..hook_protocol import BaseHook[, HookEvent]` 与 `from ..registry import hook_registry`，但 `hook_protocol.py` 只导出 `ExtensionHooks`（无 BaseHook/HookEvent），且 `backend/extensions/registry.py` **不存在** → 模块导入即 `ImportError`。`discover_and_register_hooks()`（main.py:178）逐文件 import 时被 `except` 跳过，extension_loader 路径也因导入失败得 `loaded.hooks=None`。结果：TSF 损伤、MS 的 PS 装甲耗尽、武器耐久损耗、跨界事件 SP 结算等机制**全部不生效**。仅 `wuxia/hooks.py` 实现正确（class WuxiaHooks 实现 ExtensionHooks 协议、无错误导入）。
- 修复方向：将基类改为 `from ..hook_protocol import ExtensionHooks`（或定义真实 BaseHook），删除 `..registry` 导入与未被调用的 `register_hooks()`；类名改为以 `Hooks` 结尾或导出 `HOOKS=实例`，使 extension_loader 也能发现。

### NEW-C9-02 · infinite_arsenal/forge_weapon 的 LLM 导入相对层级错误（4 点越界）
- 状态：🆕新发现
- 类别：degradation / dead
- 严重度：🟡降级
- 位置：`backend/extensions/infinite_arsenal/tools.py:74`
- 证据：`from ....agents.llm import llm_complete` 共 4 个点，`backend.extensions.infinite_arsenal.tools`（深度 3）再上溯 4 级越过顶层包，触发 “attempted relative import beyond top-level package” → 锻造的 LLM 生成分支永不命中，始终用固定映射表（即 T-D19 实质未修复）。同文件其余导入用 3 点正确；crossover/tools.py:145 亦为 3 点。
- 修复方向：改为 `from ...agents.llm import llm_complete`。

### NEW-C9-03 · muv_luv manifest.json 的 provides 标志与实际文件矛盾
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/extensions/muv_luv/manifest.json:8-13`
- 证据：`"provides": {"tools": false, "agents": false, "hooks": false}`，但目录内 tools.py、hooks.py 均存在且 tools 已生效。加载器/注册表均以**文件是否存在**判定（registry_builder.py:49-53），不读 provides，故该字段为误导性死元数据。
- 修复方向：更正 provides 或删除该块；gundam_seed/wuxia 等用 `entry_points`，建议统一 manifest schema。

### NEW-C9-04 · wuxia 钩子可能被双重注册
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/main.py:119-124` 与 `backend/main.py:177-178`
- 证据：wuxia/hooks.py 的 `WuxiaHooks`（类名以 Hooks 结尾）会被 extension_loader 自动实例化为 `loaded.hooks` 并经 `register_extension_hooks` 注册（路径 a）；同时 `discover_and_register_hooks()` 又扫描 `*/hooks.py` 再注册一次（路径 b）。on_roll_check/before_tool_call 有重复触发风险（如 threshold 被减两次）。
- 修复方向：两条注册路径择一，或在 hook_manager 内按 hook_id 去重。

### NEW-C9-05 · muv_luv/gundam_seed 插件存在并行死代码（旧式接口未被加载器使用）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/extensions/muv_luv/plugin.py:20-78`、`backend/extensions/gundam_seed/plugin.py:15-67`
- 证据：加载器仅取模块级 `PLUGIN`（WorldPlugin dataclass）。`MuvLuvWorldPlugin` 类、`get_plugin()`、`GundamSeedWorldPlugin.describe()` 等旧式 API 均无调用方（`get_world_rules/get_world_context` 仅被同模块用于填充 PLUGIN 的 fragment content）。属冗余双轨实现，易与 dataclass 漂移。
- 修复方向：保留方法作为内容来源即可，删除 get_plugin / 未用 describe，减少双轨。

### NEW-C9-06 · 各扩展 register_tools()/register_hooks() 为无调用方死函数
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/extensions/muv_luv/tools.py:174`、`gundam_seed/tools.py:176`、四个 hooks.py 的 `register_hooks()`
- 证据：tools 经 `TOOLS` 自动发现、hooks 经协议扫描注册，全仓无任何处调用 `register_tools()`/`register_hooks()`（grep 仅见定义）。为遗留兼容桩。
- 修复方向：删除或在文档注明为兼容占位。

### NEW-C9-07 · muv_luv/gundam_seed 缺 data/ 目录，专属工具走内联兜底
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/muv_luv/tools.py:78-90`、`gundam_seed/tools.py`（无 data/）
- 证据：muv_luv `beta_threat_assessment` 读 `data/beta-catalog.json`，该目录不存在 → 走内联 5 种 BETA 兜底（功能正常但数据未外置，与 wuxia/crossover/infinite_arsenal 的 data/ 化做法不一致）。gundam_seed 同样无 data/。
- 修复方向：补 data/*.json 外置数据，统一数据驱动风格（参 09-db-data-quality 模板）。

---

## 三、小计

| 维度 | 计数 |
|---|---|
| ✅已修复 | 6（STUB-04, STUB-06, STUB-07, STUB-08, T-D20；STUB-05 的 manifest+Fragment 子项） |
| 🔄已变化 | 4（STUB-05, STUB-10/11, STUB-13/14, T-D18） |
| ⚠️仍存在 | 4（T-D14, T-D19, STUB-T11, STUB-05 的 get_skill_catalog 子项） |
| 🆕新发现 | 7（NEW-C9-01 ~ NEW-C9-07） |

**核心风险（🔴）：NEW-C9-01 / STUB-10/11** —— muv_luv、gundam_seed、infinite_arsenal、crossover 四个世界的 hooks 因错误导入整体失效，机甲损伤、耐久、SP 结算等核心机制形同未实现。
