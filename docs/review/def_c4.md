# 引擎层代码缺陷复审 — def_c4.md

> 子代理 C4 · 范围：`backend/engine/{vm, prompt_assembler, runtime_data_stream, combat, dice, psyche}.py`
> 复审基准日期：2026-06-03 · 只读复审 · 行级证据

---

## 旧报告条目逐条判定

### STUB-R03 · prompt_assembler Registry 构建失败时改为抛错
- 状态：✅已修复
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/engine/prompt_assembler.py:197-199`
- 证据：`except Exception as e: logger.error(...); raise RuntimeError(f"PromptAssembler failed for phase={phase}") from e` — 旧的 `return ""` 灾难性空 system prompt 已替换为 fail-fast 抛错；docstring（L182-183）仍写"失败时返回空字符串"与实现不符（注释陈旧，非功能缺陷）。
- 修复方向：仅需更新 `_build_from_registry` docstring 与实现一致。

### STUB-R04 · VariableVM 无 RestrictedPython 时直接返回原 state
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/engine/vm.py:119-127`
- 证据：`if not self._rp_available: logger.warning(...); return state` — 仍是静默返回原 state，LLM 生成的 `vm_code` 被丢弃且上层 `var_agent` 无任何错误信号。缓解项：`RestrictedPython>=7.0` 已列入 `pyproject.toml:28` 依赖，正常安装下走沙箱路径。
- 修复方向：fallback 分支应返回错误标记（如 `{"_vm_skipped": True}`）或抛异常，让 `var_agent` 记录到 `var_errors`，避免状态变更静默丢失。

### STUB-R09 · runtime_data_stream active_quests/active_hooks 写死 []
- 状态：✅已修复
- 类别：stub
- 严重度：🟡降级
- 位置：`backend/engine/runtime_data_stream.py:267-359, 438-456`
- 证据：不再硬编码 `[]`，现按 `ctx.active_quests` → `char["quests"/"active_quests"]` → DB `character_cards` 三级回退（`_extract_stream` L275-308、`_extract_stream_async` L335-348），并构造 `QuestSnapshot/HookSnapshot`。
- 修复方向：无需动作（见 NEW-C4-04 关于 sync 路径 DB 回退的遗留问题）。

### R-M15 · combat.py CombatRoundResult 定义但全项目无引用
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/engine/combat.py:78-88`
- 证据：grep 全仓 `CombatRoundResult` 仅命中 `combat.py:79`（定义）与 `docs/STUB_ANALYSIS.md:488`（旧报告），无任何生产代码引用；`CombatEngine` 仅暴露 `apply_damage/apply_heal/apply_turn_effects`，整轮战斗结算 API 仍未暴露/未接线。
- 修复方向：实现 `CombatEngine.resolve_round()` 返回 `CombatRoundResult` 并由 rules_agent/dm_agent 调用，或删除该 dataclass。

### R-D09 · prompt_assembler 无 jinja2 时 return template_str 原文
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/engine/prompt_assembler.py:206-208`
- 证据：`if not _HAS_JINJA2: logger.warning(...); return template_str` — 未渲染原文直出，模板占位符 `{{...}}` 会原样进入 system prompt。加重项：`jinja2` **未列入** `pyproject.toml` 依赖（仅 L22-26 `try import` 软依赖），故标准安装下此降级路径恒定触发。`TemplateError` 兜底（L214-216）同样吐原文。
- 修复方向：将 `jinja2` 加入依赖，或在缺失/渲染失败时抛错而非返回未渲染原文（避免脏占位符污染提示词）。

### R-D10 · runtime_data_stream 无 world_events 时占位"未知时间/地点"
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/engine/runtime_data_stream.py:426-435`
- 证据：现已遍历 `world_events` 提取 `world_time/location`（L426-431），且 `world_events` 已被 world_agent 真实填充（`graph.py:104`、`world_agent.py:167`）。但仍保留 `meta` 回退后落到 `"未知时间"/"未知地点"`（L433、L435）。占位仍可能出现，且存在键不匹配（见 NEW-C4-02）。
- 修复方向：见 NEW-C4-02；占位字符串本身可保留为最终兜底。

---

## 新发现问题

### NEW-C4-01 · RestrictedPython 沙箱缺少 guard 函数，赋值/下标恒失败
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/engine/vm.py:142-150`
- 证据：`glb` 仅含 `safe_globals + __builtins__=safe_builtins + state`，未注入 RestrictedPython 必需的 `_write_`/`_getitem_`/`_getiter_`/`_getattr_` guard。`compile_restricted` 会把 `state['x']=1` 编译为依赖 `_write_(...)` 的字节码，运行时 `NameError`，被 `execute` 的 `except`（L137-139）吞掉后返回原 state——即使 RestrictedPython 已安装，任何状态变更脚本也会静默失效。
- 修复方向：引入 `RestrictedPython.Guards`（`safer_getattr`、`guarded_setattr`）并提供 `_write_`/`_getitem_`/`_getiter_`，或显式 import `safe_globals` 中的 guards 字典。

### NEW-C4-02 · world_events 键不匹配，world_time/location 永不来自 world_agent
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/engine/runtime_data_stream.py:426-435` × `backend/agents/world_agent.py:167-175`
- 证据：`_extract_from_dict` 只读 `ev["world_time"]` / `ev["location"]`（L428、L431），而 world_agent 产出的事件字典键为 `event_type/description/affects`（`world_agent.py:169-171`），二者无交集。结果世界时间/地点恒走 `meta` 回退或占位，DM 数据流轴 12-13 实际从未被 world_agent 驱动。
- 修复方向：统一约定（world_agent 输出 `world_time/location` 字段，或 runtime 从 `meta`/专用 ctx 字段读取并解析 `affects`）。

### NEW-C4-03 · dice.py 减值读取 schema 与系统其余部分不一致
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/engine/dice.py:136-155`
- 证据：`_effective_attr` 从 `char_data["body_parts"]`（L136）和 `char_data["psychology"]["state"]`（L149）读取部位/心理减值；而 combat 引擎写入 `attributes.hp.parts`（`combat.py:132`），runtime/psyche 用 `char["psyche"]`（`runtime_data_stream.py:374`）。schema 错位导致伤势/压力骰池减值在真实角色卡上恒为 0（除非调用方另行喂入 `body_parts`/`psychology` 结构）。
- 修复方向：将 `_effective_attr` 对齐 `attributes.hp.parts` + `psyche`（或 `attributes.stress/morale`）的统一 schema。

### NEW-C4-04 · 同步 DB 回退在事件循环运行时为 fire-and-forget 空操作
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/engine/runtime_data_stream.py:298-304`
- 证据：`loop.is_running()` 分支创建 `asyncio.ensure_future(_db_fetch())` 后既不 await 也不取结果（注释自承"跳过等待"），该 Task 结果被丢弃、`active_quests/active_hooks` 不变——纯 no-op 且制造游离 Task。注释已建议 async 上下文改用 `build_async`。
- 修复方向：删除该 fire-and-forget 分支（依赖调用方走 `build_async`），避免误导与游离 Task。

---

## 完整实现确认（无占位）

- **`dice.py`**：d10 骰池/重骰/抵消/botch、种子可复现、JSONL 归档均为完整实现，无桩。唯一缺陷为 NEW-C4-03 的 schema 错位（非占位）。
- **`psyche.py`**：OCEAN 档案、`compute_action_bias`（sigmoid 加权）、`apply_drift`（事件→漂移映射 + 钳位 + 历史）、`describe`、CLI 入口全部完整实现，**无占位/无 stub/无 TODO**。

---

## 小计

| 分类 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 2 | STUB-R03、STUB-R09 |
| ⚠️仍存在 | 3 | STUB-R04、R-M15、R-D09 |
| 🔄已变化 | 1 | R-D10 |
| 🆕新发现 | 4 | NEW-C4-01 ~ NEW-C4-04 |

- 严重度分布：🔴核心 0（活跃）｜🟡降级 6｜🟢次要 2
- `dice.py` / `psyche.py` 已明确标注无占位实现。
