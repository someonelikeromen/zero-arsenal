# def_c10 · 数据文件利用情况复审（子代理 C10）

> 复审基准日期：2026-06-03 ｜ 只读复审，未改动任何代码
> 范围：`backend/extensions/*/data/*.json`、`backend/extensions/__registry__.json`、`backend/data/sys_config/*.json`、各扩展 `manifest.json`
> 判定方法：Read 每个 JSON 看内容丰富度 + Grep 文件名/加载函数在 backend 中确认是否真被读取（给行号证据）。

---

## 维度 A — 代码缺陷复审

### T-D29 · pool-catalog.json 已真正被加载（不再是内联 _POOL_CATALOG）
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/infinite_arsenal/tools.py:200-232`、`backend/api/routers/engine.py:173`
- 证据：`_POOL_CATALOG: dict = _load_pool_catalog()`（tools.py:232），`_load_pool_catalog()` 实际 `json.loads(catalog_path.read_text())` 读 `data/pool-catalog.json`（:203-219）；内联 dict 仅作 `except` 兜底（:222-230）。经济接口也走 `_load_extension_json(world_plugin, "pool-catalog.json")`（engine.py:173）。
- 修复方向：无需动作；旧报告"内联未读文件"已不成立。

### T-D30 · acg-source-registry.json 已真正被加载（不再是内联 _ACG_ITEMS）
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/infinite_arsenal/agents.py:24-65`
- 证据：`_ACG_ITEMS: dict = _load_acg_items()`（:65），`_load_acg_items()` 读 `data/acg-source-registry.json` 并按 `sources`/`tier_caps` 建索引（:27-46）；内联种子库仅 `except` 兜底（:48-60）。`_pick_item` 消费 `_ACG_ITEMS`（:68-89）。
- 修复方向：无需动作。

### T-D31 · shop-catalog.json 已被 open_shop 读取（固定兜底已改为读文件）
- 状态：✅已修复
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/extensions/crossover/tools.py:109-136`、`backend/api/routers/engine.py:174`
- 证据：`_open_shop` 读 `data/shop-catalog.json` 并展开 `categories[].items`（:115-132）；失败时兜底为**空商店** `{items:[], total:0}`（:136），而非旧报告所说的硬编码固定物品列表。经济接口同样 `_load_extension_json(..., "shop-catalog.json")`（engine.py:174）。
- 修复方向：无需动作。

### T-D32 · wuxia sects-catalog.json 已有查询实现
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/wuxia/tools.py:113-131`、工具注册 `:305`
- 证据：`query_sects()` 读 `data/sects-catalog.json`（:117 `catalog_path = .../"sects-catalog.json"`，:118 `read_text`），并以 `query_sects` 工具名注册（:305 description "读取 sects-catalog.json"）。
- 修复方向：无需动作；旧报告"无查询实现"已不成立。

### T-D33 · wuxia techniques-catalog.json 已有查询实现
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/extensions/wuxia/tools.py:137-158`、工具注册 `:321`
- 证据：`query_techniques()` 读 `data/techniques-catalog.json`（:141、:142 `read_text`），消费 `inner_techniques`/`outer_techniques`；以 `query_techniques` 工具注册（:321）。
- 修复方向：无需动作。

### T-D34 / T-M17 · agents.json 的 memory_extract 配置项为死配置
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/data/sys_config/agents.json:66-72`、`backend/memory/extractor.py:237`
- 证据：记忆提取唯一调用处 `llm.chat_json(..., role="dm", ...)`（extractor.py:237 注释"使用逻辑推理模型"）；`role` 经 `load_agent_config(role)` 选模型（llm_client.py:38-39）。全 backend 仅 extractor 用到提取逻辑，且用的是 `"dm"`——`extract_queue.py` 内无任何 `role=`/`chat_json`/`memory_extract` 调用（grep 0 命中）。因此 `agents.json` 的 `memory_extract` 块永不被读取。
- 修复方向：要么把 extractor 改为 `role="memory_extract"`，要么删掉 agents.json 中该死配置块。

### T-M16 · __registry__.json 中 muv_luv 缺 display_name
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/extensions/__registry__.json:47-59`、`backend/extensions/muv_luv/manifest.json:2-5`
- 证据：muv_luv 注册项只有 `key/path/priority/tier/has_*/description/version`，**无 `display_name` 字段**（:47-59）；根因是其 manifest 用 `"name": "MUV-LUV Alternative"`（manifest.json:3）而非 `display_name`，registry_builder 拷贝 `display_name` 时取不到。前端世界选择若按 display_name 渲染会落到 key 或空。
- 修复方向：manifest.json 增 `"display_name"`，或 registry_builder 在缺失时回落 `name`/`key`。

### NEW-C10-01 · character-template.json 从未被任何代码读取（死数据文件）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`backend/extensions/crossover/data/character-template.json`、`backend/extensions/plugin.py:138-140`
- 证据：基类 `get_character_template()` 直接 `return {}`（plugin.py:138-140）；crossover 插件**未覆写**该方法（grep `get_character_template|character-template` 在 crossover 目录 0 命中）。会话初始化用的是 DB `character_templates` 表（sessions.py:106-110）/全局模板，与此 JSON 无关。该文件（含 7 维属性、SP=1000、psychology 等丰富内容）完全悬空。
- 修复方向：让 crossover 插件覆写 `get_character_template()` 读此 JSON，或删除该文件并改在 design 文档说明。

### NEW-C10-02 · world-registry.json 从未被任何代码读取（死数据文件）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`backend/extensions/crossover/data/world-registry.json`
- 证据：全仓 grep `world-registry|world_registry` 仅命中 `docs/STUB_ANALYSIS.md`、`docs/design/04-extension-system.md`，**backend 代码 0 命中**。文件含 5 个可穿越世界（naruto/one_piece/demon_slayer/fma/my_hero，带 danger_tier、entry_options、sp_reward_base 等）但无加载入口、无"选择穿越世界"接口消费它。
- 修复方向：实现"世界选择/跨界穿越"端点读取此注册表，或迁移到 lore/DB 后删除。

---

## JSON 利用情况对照清单

| JSON 文件 | 内容丰富度 | 代码是否读取 | 读取证据（行号） | 影响 |
|---|---|---|---|---|
| `infinite_arsenal/data/pool-catalog.json` | 高（3 池+tier/category 权重+档位描述） | ✅ 是 | tools.py:203-219 / engine.py:173 | 正常生效 |
| `infinite_arsenal/data/acg-source-registry.json` | 高（10 来源+tier_caps+示例物品） | ✅ 是 | agents.py:27-46 | 正常生效 |
| `crossover/data/shop-catalog.json` | 高（4 类目+约 14 商品） | ✅ 是 | tools.py:115-132 / engine.py:174 | 正常生效 |
| `crossover/data/character-template.json` | 高（7 维属性+meta+psychology） | ❌ 否 | 基类 plugin.py:138-140 `return {}`，无覆写 | **死文件** |
| `crossover/data/world-registry.json` | 高（5 世界+危险等级+SP 奖励） | ❌ 否 | 全 backend 0 命中 | **死文件** |
| `wuxia/data/sects-catalog.json` | 高（5 门派+加成） | ✅ 是 | tools.py:117 + 注册 :305 | 正常生效 |
| `wuxia/data/techniques-catalog.json` | 高（4 内功+5 外功） | ✅ 是 | tools.py:141 + 注册 :321 | 正常生效 |
| `backend/extensions/__registry__.json` | 中（5 扩展元数据） | ✅ 是 | registry_builder.py:86-89 加载 | 生效，但 muv_luv 缺 display_name（T-M16） |
| `backend/data/sys_config/agents.json` | 中（9 agent+2 provider） | ⚠️ 部分 | llm.py:120/153 按 role 读取 | 文件被读；`memory_extract` 块为死配置（T-D34/T-M17） |
| `backend/data/sys_config/mcp.json` | 中（3 server） | ✅ 是 | mcp_bridge.py:25-49 / main.py:88 | 生效（注：3 个 server 均 `enabled:false`，运行时不注册任何工具——配置正确读取，属设计状态非缺陷） |
| `backend/data/sys_config/scraper_rules.json` | 高（7 站点规则+模板） | ✅ 是 | web_scraper.py:21-49 加载+热重载 | 正常生效 |
| `extensions/*/manifest.json`（×5） | 中（扩展声明） | ✅ 是 | extension_loader.py:81 | 正常生效（muv_luv 用 `name` 非 `display_name`，见 T-M16） |

---

## 小计

| 维度 | 计数 |
|---|---|
| ✅ 已修复 | 5（T-D29 / T-D30 / T-D31 / T-D32 / T-D33） |
| ⚠️ 仍存在 | 2（T-D34=T-M17 死配置；T-M16 muv_luv 缺 display_name） |
| 🆕 新发现 | 2（NEW-C10-01 character-template.json 死文件；NEW-C10-02 world-registry.json 死文件） |

**完全未被代码读取的 JSON 数据文件：2 个** —— `crossover/data/character-template.json`、`crossover/data/world-registry.json`。
另：`agents.json` 文件本身被读取，但其中 `memory_extract` 配置块属"读不到的死子项"（提取器实际用 `role="dm"`）。
