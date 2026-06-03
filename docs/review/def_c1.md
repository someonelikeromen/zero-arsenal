# 代码缺陷复审 · 切片 C1「Agent 安全门禁」（维度 A）

> 复审基准日期：2026-06-03
> 复审范围：`backend/agents/rules_agent.py`、`backend/agents/dm_agent.py`、`backend/agents/permission.py`、`backend/agents/ask_handler.py`、`backend/agents/dice_node.py`、`backend/tools/registry.py`（D-16 关联）
> 结论速览：三道核心门禁（rules / dm / parse-fail）已全部改为 **fail-closed（安全）**；但仍存在一条 **P0 fail-open 漏洞**（verdict 缺失/未知时默认放行）。

---

### STUB-03 · rules_agent LLM 不可用时是否仍硬编码放行
- 状态：✅已修复
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/agents/rules_agent.py:171-173`
- 证据：`llm_complete` 失败的 except 分支现写 `result_text = '{"verdict":"block","reason":"LLM不可用，安全拦截"}'`，不再硬编码放行。基线"默认放行桩已消失"得到确认 → 现为 **block（fail-closed）**。
- 修复方向：无需动作，已安全。

### D-01 · dm_agent JSON 解析失败 → allow？
- 状态：✅已修复
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/agents/dm_agent.py:282-285`（解析失败）、`:226-231`（LLM 调用失败）
- 证据：解析 except 分支 `ctx.dm_verdict = "block"; ctx.dm_note = "[DM parse error, blocked for safety: ...]"`；LLM 调用 except 同样 `ctx.dm_verdict = "block"`。两条失败路径均 fail-closed。
- 修复方向：无需动作，已安全。

### D-02 · rules_agent 解析失败 → pass？
- 状态：✅已修复
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/agents/rules_agent.py:206-211`
- 证据：except 分支 `ctx.rules_verdict = "block"; ctx.rules_reason = "规则校验结果解析失败，已安全拦截"`，路由 `_route_after_rules`（graph.py:59-61）对 `block` 返回 END。fail-closed。
- 修复方向：无需动作，已安全。

### D-16 · tools/registry 权限检查失败是否 fail-open
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/registry.py:234-242`
- 证据：`_resolve_permission` 在 profile 解析抛异常时 `except: pass` 后 `return tool.permission_required`，而 `ToolDef.permission_required` 默认值为 `"allow"`（registry.py:70）。即权限子系统异常时回落到工具自带默认（多为 allow）= **fail-open**。
- 修复方向：异常分支应回落到 `"deny"` 或 `"ask"`，而非工具默认 allow。

### T-D06 · permission.filter_tools 导入失败 → _tool_groups={}
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/permission.py:71-77`、`:85-88`
- 证据：`from ..tools import tool_registry` 失败时 `_tool_groups = {}`；后续 `t_group = _tool_groups.get(t, "general")` 使所有工具被判为 group `"general"`。当 profile 设了 `allowed_groups` 且不含 `"general"` 时，全部工具被过滤掉（过度限制，方向上 fail-closed，但属功能降级）。
- 修复方向：导入失败应记 warning 并跳过 group 过滤（保持原行为），而非把全部工具归入单一默认组。

### T-D07 · 注释"60s 超时自动允许"与 ask_handler 实际 DENY 的文档漂移
- 状态：⚠️仍存在
- 类别：stub（文档/注释漂移）
- 严重度：🟢次要
- 位置：注释侧 `backend/tools/registry.py:175`、`:254`、`backend/agents/permission.py:110`；实际侧 `backend/agents/ask_handler.py:30-36`
- 证据：registry 文档写"等待前端确认（超时 60s 默认允许）"与 `_wait_for_permission` docstring"超时后默认允许（fail-open）"；PLAY_PROFILE 注释"60s 超时自动允许"。但 `PendingAsk.wait()` 超时设 `self._decision = "deny"`（ask_handler.py:35），`_wait_for_permission` 异常分支亦 `return False  # fail-closed`（registry.py:267）。实际行为是 **超时 DENY（fail-closed）**，与注释相反。
- 修复方向：更新三处注释为"超时视为 deny（fail-closed）"，消除误导。

### NEW-C1-01 · verdict 字段缺失/未知值时两道门禁默认放行（fail-open）
- 状态：🆕新发现
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/agents/rules_agent.py:186`、`backend/agents/dm_agent.py:260`、路由 `backend/agents/graph.py:59-77`
- 证据：rules `verdict = result.get("verdict", "pass")`、dm `raw_verdict = result.get("verdict", "pass")`。当 LLM 返回**合法 JSON 但缺 verdict 键**（如 `{}`）或返回**未知 verdict**（如 `"maybe"`）时：rules 落入 else 分支按原值/`pass` 处理 → `_route_after_rules` 非 block 即放行进 dm_gate；dm 未知 verdict → `_route_after_dm` 非 reject/block/needs_roll → 返回 `parallel_nw`（继续叙事）。两道门禁在"可解析但语义缺失"路径上 **fail-open**，与 D-01/D-02 修好的"解析失败 fail-closed"形成缺口。
- 修复方向：缺失或不在白名单 `{pass,block,hard_block,needs_check}`/`{pass,reject,modify,needs_roll}` 内的 verdict 一律视为 block/reject。

### NEW-C1-02 · rules_agent 对同步函数 log_roll 误用 await，预检定骰子归档静默失效
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/agents/rules_agent.py:295-298`
- 证据：`await log_roll(roll_result, ...)`，但 `engine/dice.py:221` 的 `def log_roll(...) -> None` 为**同步函数**返回 None；`await None` 抛 `TypeError`，被紧邻的 `except: pass` 吞掉 → rules 预检定（needs_check 门禁）的骰子永不写入 `rolls_*.jsonl` 归档。对照 `dice_node.py:21` 是正确的同步调用 `log_roll(result, ...)`。
- 修复方向：去掉 `await`，改为 `log_roll(roll_result, ...)`（与 dice_node 一致）。

---

## 小计

| 状态 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 3 | STUB-03, D-01, D-02 |
| ⚠️仍存在 | 3 | D-16, T-D06, T-D07 |
| 🆕新发现 | 2 | NEW-C1-01, NEW-C1-02 |
| **合计** | **8** | — |

**P0 / 🔴核心**：4 条（STUB-03 ✅、D-01 ✅、D-02 ✅ 三条已修复并确认 fail-closed；**NEW-C1-01 ⚠️ 仍为 fail-open，唯一未修复的 P0 漏洞**）。

**总体判定**：rules / dm 门禁在「LLM 不可用」「JSON 解析失败」两类故障上已正确 **fail-closed（安全）**；ask 超时实际为 **DENY（安全）**（仅注释漂移）。剩余风险集中在 **NEW-C1-01**——verdict 缺失/未知值时回落到 `pass`/继续，属 fail-open，建议优先收口。
