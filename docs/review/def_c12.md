# Prompts + Skills 代码缺陷复审 — def_c12.md

> 子代理 C12 · 范围：`backend/prompts/`（registry.py / template_loader.py / core_prompts.py / token_budget.py / __init__.py）+ `backend/skills/`（watcher.py / writing_styles.py）
> 复审基准日期：2026-06-03 · 只读复审 · 行级证据 · 维度 A 格式

---

## 一、旧报告条目逐条判定

### R-D13 · registry condition eval 失败时默认注入（return True）
- 状态：✅已修复
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/prompts/registry.py:125-131`
- 证据：`except Exception: logger.warning("...condition eval failed: %s — skipping fragment", condition); return False`（L130-131），注释「条件求值失败时跳过，不注入」——旧的 `return True`（偏多注入）已改为 `return False`，fail-safe 方向正确。
- 修复方向：无需动作。

### R-D14 · TokenBudget 不可用则不裁剪
- 状态：⚠️仍存在（低风险）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/prompts/registry.py:201-202`
- 证据：`except Exception: pass  # TokenBudget 不可用时退化为无裁剪`——导入/裁剪异常时静默退化为不裁剪。但 `from .token_budget import TokenBudget`（L190）为同包导入，实际几乎不会失败；真正问题是**无任何调用方传入 token_budget**（见 NEW-C12-02），整个裁剪路径在生产中从不触发。
- 修复方向：与 NEW-C12-02 合并处理——让调用方实际传入预算；异常分支至少 `logger.warning` 而非纯 `pass`。

### R-D15 · template_loader 无 jinja2/无模板文件时 return ""
- 状态：⚠️仍存在（影响被低估）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/prompts/template_loader.py:51-55`（无 jinja2）/ `:60-62`（文件不存在）/ `:75-77`（渲染异常）
- 证据：三处均 `logger.warning(...); return ""`，渲染结果直接变空串。`render_prompt` 被 `dm_agent.py:60-61`、`world_agent.py:31-39` 实际调用；jinja2 仍**未列入硬依赖**（参见 def_c4 R-D09），标准安装下 L51-55 恒触发 → 这两个 Agent 的模板注入恒为空串。所幸调用方有内联兜底（如 `world_agent.py:44 return WORLD_SYSTEM_PROMPT`），故不致灾难，但 .j2 模板（`templates/dm_gate.j2`、`world.j2`、`narrator_p3.j2`）实际从未生效。
- 修复方向：把 jinja2 列为硬依赖；或在缺失时让调用方明确感知（返回 None 触发兜底，而非空串）。

### R-M04 · watcher 无 watchfiles 时直接 return（热加载禁用）
- 状态：⚠️仍存在（可接受）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/skills/watcher.py:116-121`
- 证据：`try: from watchfiles import awatch, Change except ImportError: logger.info("...watchfiles 未安装，扩展热加载已禁用..."); return`——缺失依赖时仅 info 日志后静默返回。热加载是**仅开发模式**功能（`_should_watch()` 生产环境本就跳过），降级可接受且有清晰日志。
- 修复方向：无需动作（保持现状）。

### R-M05 · writing_styles 目录不存在 return 0
- 状态：⚠️仍存在（可接受）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/skills/writing_styles.py:34-35`
- 证据：`if not styles_dir.exists(): return 0`——目录缺失时静默不注册任何风格、无日志。降级合理但缺告警，运维难以察觉「0 风格」是缺目录还是空目录。
- 修复方向：缺目录时补一条 `logger.warning`，便于诊断。

### R-M10 · prompt_assembler 无 jinja2 警告但不阻断（关联项）
- 状态：⚠️仍存在（C4 territory，交叉引用）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/engine/prompt_assembler.py:206-208`（`_render_jinja2`）
- 证据：`if not _HAS_JINJA2: logger.warning(...); return template_str`——未渲染原文直出，与 def_c4 R-D09 重复。属 `engine/` 切片，此处仅记录与 prompts 层的关联：prompts 层 `template_loader` 走 return ""，engine 层 `prompt_assembler` 走 return 原文，**两套 jinja2 缺失行为不一致**（空串 vs 脏占位符）。
- 修复方向：统一两层 jinja2 缺失策略；以 def_c4 R-D09 为主处置。

---

## 二、新增问题（NEW-C12-xx）

### NEW-C12-01 · Layer1 agent 片段双源定义、启动时被静默覆盖（core_prompts 内容变死代码）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`backend/prompts/core_prompts.py:104-203` 与 `backend/prompts/agents/*.md` + `backend/main.py:162-163`
- 证据：`core_prompts.py` 硬编码注册 `agent.rules` / `agent.dm_gate` / `agent.narrator_p1/p3/p4` / `agent.style`（import 时经 L212 `init_core_prompts()` 注册）；`prompts/agents/*.md` 用**完全相同的 id**（如 `rules_system.md:2 id: agent.rules`）再次定义，且 `main.py:162-163` lifespan 调用 `load_agent_prompts()` 在 import 之后执行，`registry.register()`（registry.py:75）按 id 覆盖 → **agents/*.md 版本覆盖 core_prompts 硬编码版本**。二者内容已分叉：`core_prompts.py:178-185` 的 narrator_p4 用 `{{SET: ...}}` TavernCommand 格式，而 `agents/narrator_p4.md:10-13` 用 JSON 数组 `[{"cmd":"SET",...}]` 格式——下游解析依赖哪套取决于谁后注册（当前是 .md 胜出）。core_prompts 的 6 个 Layer1 片段实为死代码。
- 修复方向：删除其一（建议保留文件化 agents/*.md，删 core_prompts Layer1 硬编码），或在 `register()` 检测 id 冲突并告警。

### NEW-C12-02 · TokenBudget 裁剪已接线进 API 但无调用方传入预算（裁剪路径死）
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/prompts/registry.py:188-202` / 调用方 `dm_agent.py:106`、`narrator_agent.py:50,220`、`rules_agent.py:62`、`style_agent.py:132`、`engine/prompt_assembler.py:192`
- 证据：`build_system_prompt(..., token_budget)` 支持裁剪，但**所有实际调用方均未传 token_budget**（默认 None），`get_for_phase` 的 `if token_budget is not None and token_budget > 0`（L188）恒为假 → prompt 片段从不被预算裁剪。`token_budget.py` 的 `TokenBudget` 全套估算/裁剪能力仅在测试外不被消费。
- 修复方向：在各 Agent 调用处按 `DEFAULT_BUDGETS[agent]` 传入预算，或明确文档说明裁剪由 `compress_context` 在 LLM 层另行完成、删除 registry 内的裁剪分支以免误导。

### NEW-C12-03 · VALID_PHASES/LAYERS/TRIGGERS 常量从不校验且内容过时
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/prompts/registry.py:28-30`
- 证据：`VALID_LAYERS`/`VALID_PHASES`/`VALID_TRIGGERS` 三个元组定义后在全代码库**无任何引用**（grep 仅命中定义处）；`register()`/`register_from_dict()` 对 layer/phase/trigger **不做合法性校验**。且 `VALID_PHASES = ("all","p1","p2","p3","p4","dm")` 漏掉了实际在用的 `"rules"` 与 `"style"` 相位（core_prompts.py:107、191；rules_agent.py:63、style_agent.py:133），常量既死又错。
- 修复方向：要么在 `register()` 中实际用这些元组做校验并补全 `rules`/`style`，要么删除误导性常量。

### NEW-C12-04 · PromptRegistry.build()（设计 §5.3 规范入口）无人调用
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`backend/prompts/registry.py:252-320`
- 证据：`build()` 注释标明「设计文档 05-prompt-architecture.md §5.3」为规范 messages 构建入口，但全代码库无 `registry.build(`/`_pr.build(` 调用——所有 Agent 走 `build_system_prompt()`（registry.py:206）。`build()` 同时**不支持 token_budget**，与 `build_system_prompt` 能力分叉，实现了设计文档的规范 API 却处于死代码状态。
- 修复方向：让 Agent 改用 `build()`（对齐设计），或删除 `build()` 并更新设计文档说明实际入口为 `build_system_prompt()`。

### NEW-C12-05 · watcher 热重载只刷新 ToolRegistry，文档声称的 Hook/Agent 注册表未刷新
- 状态：🆕新发现
- 类别：stub
- 严重度：🟢次要
- 位置：`backend/skills/watcher.py:73-108`（模块 docstring `:3-4`）
- 证据：模块头 `:3-4` 声称「自动重新加载对应扩展模块并刷新 Tool/Hook/Agent 注册表」，但 `_reload_extension` 仅在 L96-108 刷新 `ToolRegistry`（`registry.register(tool_def)`），**未刷新 Hook 注册表与 Agent 注册表**。热改 Hook/Agent 的扩展在开发模式下不会生效，与文档承诺不符。
- 修复方向：补刷新 Hook/Agent 注册表，或修正 docstring 仅声明刷新 Tool。

### NEW-C12-06 · token_budget 裁剪 off-by-one 过量包含
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/prompts/registry.py:193-200`
- 证据：裁剪循环先 `kept.append(frag); remaining -= est`（L198-199），再于下一轮顶部 `if remaining <= 0: break`（L196）——使「跨过预算线的那一片段」仍被保留，实际产出可超预算约一个片段的 token 量。
- 修复方向：append 前先判断 `if est > remaining: break`（或允许但记账），保证不越界。

### NEW-C12-07 · writing_styles 直写 skill_registry._skills 私有字典且无重名保护
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/skills/writing_styles.py:56-58`
- 证据：`skill_registry._skills[name] = skill`——绕过 SkillRegistry 公开方法直接写私有 `_skills`（注释自称「公开接口」实为下划线私有），且 `name = md_file.stem` 与既有同名 skill 冲突时**静默覆盖**，无去重/告警。
- 修复方向：改用 SkillRegistry 的公开注册方法；注册前检测 name 冲突并告警。

### NEW-C12-08 · _evaluate_condition 使用 eval，扩展来源条件存在注入面
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/prompts/registry.py:125-131`（条件来源 `template_loader.py:181-189` load_prompt_fragment_file）
- 证据：`eval(condition, {"__builtins__": {}}, {"state": state})`（L128）——空 builtins 沙箱并不能完全阻断恶意表达式；而 `condition` 可来自第三方扩展 .md（`load_prompt_fragment_file` 解析 `fm.get("condition")`，main.py:144-146 注册），半受信输入进入 eval 存在表达式注入面。
- 修复方向：改用受限表达式求值器（如简单 AST 白名单/`simpleeval`），或仅允许内置可信片段使用 condition。

---

## 三、core_prompts Layer0 / Layer1 注册完整性确认

- **Layer 0（HARD-GATE，priority 0-29）**：6 片段齐全且 `phase=["all"]`（仅 `core.cot_template` 限 `["dm","p1","rules"]`），覆盖 identity/output_format/dice_contract/output_purity/ooc_boundary/cot_template，对所有相位生效——**完整**。
- **Layer 1（agent，priority 100）**：core_prompts 注册 6 个（rules/dm/p1/p3/p4/style），但全部被 agents/*.md 同 id 覆盖（见 NEW-C12-01），**有效 Layer1 = agents/*.md 文件版**。
- **缺口**：① `agent.narrator_p4`（phase=p4）两版均**无消费者**——`var_agent.py` 仅用 registry 做 `clear_runtime`（L136-137），从不 `build_system_prompt(phase="p4")`，是孤儿片段；② `npc_agent` / `world_agent` / `chronicler_agent` 在 Layer1 **无任何片段**，world_agent 走 `world.j2`+内联 `WORLD_SYSTEM_PROMPT` 绕过 5 层架构。故 Layer1 相对完整管线**不完整**（npc/world/var/chronicler 未纳入 PromptFragment 体系）。

---

## 四、小计

| 类别 | 数量 | 条目 |
|------|:----:|------|
| ✅ 已修复 | 1 | R-D13 |
| ⚠️ 仍存在 | 5 | R-D14, R-D15, R-M04, R-M05, R-M10 |
| 🆕 新发现 | 8 | NEW-C12-01(🟡), -02(🟡), -03(🟢), -04(🟡), -05(🟢), -06(🟢), -07(🟢), -08(🟢) |

> 严重度分布（新发现）：🔴×0 / 🟡×3 / 🟢×5。
> 重点关注：NEW-C12-01（Layer1 双源覆盖、narrator_p4 输出格式分叉）与 NEW-C12-02（TokenBudget 裁剪从未真正生效）。
