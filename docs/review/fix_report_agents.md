# Agents Pipeline + Hooks 修复报告

> 执行日期：2026-06-04 · 范围：`backend/agents/**`、`backend/extensions/{hooks.py,hook_protocol,rules_loader,extension_loader,plugin}.py`、`backend/prompts/**`、变量 VM（`backend/engine/vm.py`）、战斗模块（`backend/engine/combat.py`）
> 验证：全部编辑文件 `python -m py_compile` 通过；导入冒烟通过；功能抽检（hook 去重 / 配置解析 / plan 权限 / resolve_llm）通过。
> 不修改：`backend/memory/**`、`utils/llm_client.py`、`db/**`、`tools/registry.py`、`extensions/*/tools.py`、`bus/redis_bus.py`、frontend、docs（本报告除外）、pyproject。

---

## 结果总表

| # | 项 | 状态 | 证据（file:line） | 说明 |
|---|---|---|---|---|
| 1 | conf_b04 接线 11 个死 hook | ✅ | `var_agent.py:42,108`、`npc_agent.py:188,213`、`narrator_agent.py:580`、`style_agent.py:198,~210`、`compaction.py:55` | 在管线内补 fire：before/after_var_update、before/after_npc_response、after_narrative_generated、after_style_applied、before_memory_compress。before/after_agent_node 与 on_turn_start/end 本就由 `agent_span.py:33,53` / `stream.py` 触发。详见下「scope 限制」。 |
| 2 | NEW-C8-03/C9-04 去重 + 死 register_* | ✅ | `hook_protocol.py`（hook_id=`ext.{key}.{method}`）、`extension_loader.py:66`（新增 `key` 属性，修 NEW-C8-08） | 两条注册路径产生相同 id → 覆盖去重；功能抽检 dups=[]。4 个扩展 hooks.py 中的 `BaseHook/hook_registry/register_hooks()` 已在先前会话清除（grep 无残留）。 |
| 3 | NEW-C8-04 三级目录发现 | ✅ | `hook_protocol.py`（discover_and_register_hooks 改用 `discover_extensions()`）、`rules_loader.py:133`（`_iter_rules_dirs`） | hook/rules 改为复用三级 bundle 路径，user/project 级扩展生效；天然跳过 `_template`（NEW-C8-02）；只实例化 `*Hook(s)`/HOOKS（NEW-C8-06）；附带修 NEW-C8-07（`enabled:false` bool 强制）。 |
| 4 | NEW-C4-01 VM RestrictedPython guards | ✅ | `engine/vm.py` `_build_restricted_globals` | 注入 `_getitem_/_getiter_/_write_/_inplacevar_/_getattr_/_unpack_sequence_/_iter_unpack_sequence_` + safe_builtins；脚本不再静默 NameError。`RestrictedPython` 为可选依赖，import 在函数内。 |
| 5 | NEW-C4-02 world_events 键对齐 | ✅ | `world_agent.py`（输出 world_time/location）、`runtime_data_stream.py`（轴 12-13 读取，兼容 new_time/new_location 别名） | 解决世界时间/地点恒走 meta 回退。 |
| 6 | NEW-C4-03 骰子减值 schema 对齐 | ✅ | `engine/dice.py` `_read_body_parts`/`_read_psyche`/`_effective_attr` | 优先读 combat 引擎 `attributes.hp.parts{current/max}` 与 `psyche`，回退旧 `body_parts{hp/max_hp}`/`psychology.state`。 |
| 7 | R-M15 CombatRoundResult | ✅(移除) | `engine/combat.py:~78` | 全仓无生产者/消费者（战斗按单次 `DamageResult`/`HealResult` 结算，经 `apply_damage` 工具与 `/engine/combat` 路由）。判定为死结构，删除并留注释说明。 |
| 8 | D2 plan.yaml 去除 roll_* | ✅ | `profiles/plan.yaml`（移除 active_tools 的 `roll_check` 与 `roll_*: allow`）、`permission.py` PLAN_PROFILE 仍含但 YAML 覆盖生效 | 抽检：plan 的 active_tools 不含 roll_check；roll_* 落到 `*`→ask。⚠️见下注。 |
| 9 | D3 overlay 深拷贝不污染全局 | ✅ | `permission.py:apply_plugin_overlay`（已 deepcopy）、`extensions/plugin.py:apply_permission_overlay`（改为 deepcopy+重注册，原为 `insert(0)` 就地改单例） | 修复启动期 overlay 永久污染模块级 PLAY/PLAN/REVIEW 单例的真实 bug。 |
| 10 | D12 MAX_ITER=20 | ✅ | `tool_loop.py:37` `_DEFAULT_MAX_ITER = 20` | — |
| 11 | D11 多模型角色映射 | ✅ | `llm.py:load_agent_config`（分层：硬编码<统一默认<角色专属<env 覆盖）、`permission.py:AgentProfile.resolve_llm`+`llm_role`/`llm_overrides`+YAML 解析 | 缺省退化单模型；支持 `agents.json` 的 `default/_default` 与 env `ZERO_ARSENAL_LLM_PROVIDER/MODEL`。抽检通过。 |
| 12 | D13 call_external_agent + shield | ✅ | `agents/external_agent.py` | 独立 task + `asyncio.shield`，父回合取消不撕裂在途外部调用；`wait_for` 硬超时（默认 300s，对齐 D19，可 env 覆盖）；复用 `tools/mcp_bridge`。 |
| 13 | NEW-C3-02 ask 超时清理 | ✅ | `ask_handler.py:discard` + `check_permission_and_ask` 调用 | wait() 返回后无条件回收 `_pending`，杜绝僵尸项/泄漏。 |
| 13 | NEW-C3-03 compaction 实际裁剪 | ✅ | `compaction.py`（摘要 + 保留尾部 `COMPACT_KEEP_TAIL_CHARS`，丢弃被覆盖历史，记录 token 前后） | 由「追加致净增」改为「替换致净降」。 |
| 13 | NEW-C3-04 tool_loop 异常显式化 | ✅ | `tool_loop.py:run_tool_loop`（ERROR+exc_info）、`_run`（FC 失败自动降级文本解析重试） | 致命错误不再静默压空；FC 不支持自动降级（兼修 D-22 缺口）。附修 NEW-C3-06 冗余 import。 |
| 14 | D9 Narrator P4 专责 VariableBlock | ✅ | `narrator_agent.py:_get_write_system`（P3 prompt 移除 `{{SET/ADD}}` 指令） | 变量结算唯一来源为 P4（`_p4_settle`/`_p4_llm_extract`）；P3 只产正文。 |
| 15 | D18 eval → simpleeval | ✅ | `prompts/registry.py:_evaluate_condition` | 优先 `simpleeval.simple_eval`；未安装时降级受限 eval 并告警（不静默放行）。`tools/skill_loader.py` 另一处 eval 属 out-of-scope。 |
| 16 | 降级补日志 | ✅ | `world_agent.py`（NEW-C2-05 两处 except）、`style_agent.py`（解析失败持久化 pre_score）、`npc_agent.py`（part 发布 except）、`graph.py`（T-D09 options→warning；M-09 删不可达 return） | R-D02/03/04/08、T-D09/11 覆盖；T-D11 `agent_node.py` 本就 warning。 |

---

## Scope 限制与诚实说明

- **on_session_start/end/error 未在本次接线**：会话生命周期的 fire 点位于 `api/routers/stream.py` / `sessions.py`（与 before_turn/after_turn/on_error 同处，conf_b04 §5 证据 `stream.py:149/179/184`），属本次**不可编辑范围**。`ExtensionHooks` 协议与 `_EVENT_MAP` 已定义这些事件，接线只差 router 侧一行 fire——建议在 stream/sessions 修复批次补齐。
- **on_part_done 未接线**：fire 点应在 `bus`（`publish_part_done`），`bus/redis_bus.py` 在不可编辑范围。
- **D2 采用「移除」而非「显式 deny」**：按指令字面移除 roll_* 于 active_tools/permissions；移除后 roll_* 落到末尾 `*`→ask（且骰子工具不再注入给 LLM）。如需绝对禁止可改为显式 `roll_*: deny`，本次按指令保持移除。`permission.py` 内置 PLAN_PROFILE 仍保留 roll_* allow，但 `profiles/plan.yaml` 在加载时覆盖内置（`permission.py:300-302`），运行时以 YAML 为准（抽检确认 roll_check 不在 active_tools）。
- **NEW-C9-01（4 个扩展 hooks.py 损坏）**：本次复核发现 crossover/infinite_arsenal/gundam_seed/muv_luv 的 `hooks.py` 已为协议式纯类（无 `BaseHook`/`hook_registry`/`register_hooks()`），先前会话已修；本次仅确保发现/注册路径正确接纳它们（singular `*Hook` 经 discover 路径注册，单次）。

## 验证记录

- `python -m py_compile <21 个编辑文件>` → EXIT=0。
- 导入冒烟 `import backend.agents.graph, tool_loop, world_agent, engine.dice, engine.vm, extensions.plugin, permission, llm, external_agent, var_agent, npc_agent, style_agent, narrator_agent, compaction, ask_handler, engine.combat, runtime_data_stream, extensions.hook_protocol, extension_loader, rules_loader, prompts.registry` → `IMPORT_SMOKE_OK`。
- 功能抽检：`discover_and_register_hooks()` 注册 12、总 14、**dups=[]**；`load_agent_config` 角色解析 + 未知角色回退正常；plan profile `roll_check` 不可见；`AgentProfile.resolve_llm('rules')` → deepseek-chat。
- 可选重依赖（`RestrictedPython`/`simpleeval`/`aiohttp`）均在函数内 import 且有降级路径，未在模块顶层强制要求。
