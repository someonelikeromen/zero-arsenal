# Fix Report — Cross-boundary Cleanup / Wiring Pass

> 范围：六个前置子代理完成主体后，剩余的跨边界接线与清理项。
> 完成日期：2026-06-04 ｜ 不修改 `docs/FIX_VERIFICATION_2026-06.md`。

---

## 1. 结果汇总表

| # | 项目 | 状态 | 证据（file:line） | 备注 |
|---|---|---|---|---|
| 1 | 生命周期 Hook 接线（conf_b04）：`on_session_start/end/error` | ✅ | `backend/api/routers/stream.py`（`hook_manager.fire(HookEvent.on_session_start)` 管线前；`on_session_end` 成功后；`on_error`+`on_session_error` 异常分支） | 复用 agents 子代理的 `hook_manager.fire(event, ctx)` API |
| 1 | `on_part_done` 接线 | ✅ | `backend/bus/interface.py` `publish_part_done()` 内懒导入 `hook_manager` 后 fire | 集中在 Part 发布唯一出口，懒导入 + try/except 保持 bus 独立性 |
| 2 | redis_bus pubsub/task 泄漏 + 订阅计数 | ✅ | `backend/bus/redis_bus.py`（`_sub_meta` 跟踪 task/pubsub；`unsubscribe` 取消 task；`_redis_to_queue` finally 关闭 pubsub；`get_subscriber_count` 按本地队列计数） | 镜像 `event_bus.py` 的幂等关闭 / 回收 task |
| 3 | character_v4 校验覆盖所有写入路径 | ✅ | `backend/api/routers/characters.py` `_normalize_to_v4()` 应用于 create/update/import-png/generate | 校验失败记 warning，不硬阻断（回退默认） |
| 3 | 世界扩展默认卡适配 v4 | ✅ | `backend/extensions/crossover/plugin.py` `on_session_init`（填充 `economy.points/badges/tier`，兼容旧 `meta.crossover_points`） | wuxia/infinite_arsenal/gundam_seed/muv_luv 默认卡经 `_normalize_to_v4` 统一迁移 |
| 4 | 前端 v4 schema 适配 | ✅ | `frontend/src/components/CharacterEditor.tsx`（identity / OCEAN 心理 / 4 部位 hp / economy / energy_pools / loadout / achievements） | `CharacterCreator` 委托 `CharacterEditor` 编辑字段 |
| 5 | TokenBudget 接线 | ✅ | `backend/prompts/token_budget.py` 新增 `SYSTEM_PROMPT_BUDGETS` + `system_prompt_budget()`；各 agent 调用 `build_system_prompt(..., token_budget=_spb(...))` | rules/dm/narrator/style + prompt_assembler |
| 5 | `registry.build` 主路径 / `build_system_prompt` | ✅ | `backend/prompts/registry.py`：`build_system_prompt` 委托 `build()`，修复裁剪 off-by-one，`except:pass`→warning | `build()` 成为权威装配入口 |
| 5 | prompt 文件 watcher | ✅ | `backend/skills/watcher.py` `_reload_extension` 扩展刷新 Hook/Agent/PromptFragment（原仅 ToolRegistry） | 镜像 `main.py` 注册逻辑 |
| 6 | M-09 不可达 return | ✅ | `backend/agents/graph.py`（前置会话已删，含注释） | 复核确认已修 |
| 6 | `agents.json` `memory_extract` 残留 | ✅ | `backend/data/sys_config/agents.json`（已移除块） | 确认无消费者 |
| 6 | 两个死数据文件 | ✅ | 删除 `backend/extensions/crossover/data/character-template.json`、`world-registry.json` | 全仓无引用 |
| 6 | `_template` 目录泄漏（工具发现） | ✅ | `backend/tools/builtin_tools.py` `_discover_extension_tools`：`if ext_name.startswith("_"): continue` | 对齐 extension_loader |
| 6 | 未用常量 `VALID_PHASES/VALID_LAYERS/VALID_TRIGGERS` | ✅ | `backend/prompts/registry.py`（已移除） | grep 确认无引用 |
| 6 | `agents/state.py` 冗余 import | ✅ | 移除 `import operator` / `_last` | — |
| 7 | `stub` marker 注册（T-M12） | ✅ | `pytest.ini:5` + `backend/pyproject.toml:48-49`（前置已注册，复核存在） | — |
| 7 | t1_~t7_ 命名（NEW-C15-01） | ✅ | `tests/test_round10_quick.py`（全部改 `test_*` + `pytestmark = pytest.mark.stub`） | 静态源码桩，标 stub |
| 7 | infinite_arsenal `?query=`（T-D26） | ✅ | `tests/e2e/test_infinite_arsenal.py:203` `?q=长剑&top_k=5`（后端参数名为 `q`/`top_k`，`sessions.py:1257`） | — |
| 7 | 429 限流当通过（T-D27） | ✅ | `tests/e2e/test_browser_e2e.py:348/353/378-379`（429 改 `ok=False`） | 限流不再掩盖端点不可用 |
| 7 | Playwright 缺失干净跳过（T-D28） | ✅ | `test_homepage_hub.py` / `test_infinite_arsenal.py` / `test_browser_e2e.py`：`ImportError → pytest.skip()` | 区分"跳过"与"通过" |
| 7 | STUB-T10 测试内重写业务逻辑 | ✅ | 抽取 `backend/memory/extract_queue.py` `determine_tier()`；`backend/tests/test_round10.py` 改为 `from memory.extract_queue import determine_tier` | 测试现验证真实分层逻辑（运行通过） |
| 7 | NEW-C15-02 静态桩未标 stub | ✅ | `tests/unit/test_p2_extension_loader.py`（两条静态源码用例加 `@pytest.mark.stub`） | — |
| 7 | M-09/T-M13 `test_p3_parttype.py` 软跳过 | ✅ | 静态用例标 `@pytest.mark.stub`；play.yaml 缺失改 `assert exists()`（不再软跳过） | — |
| 7 | T-M12 `test_live_generation.py` | ✅ | 加 `pytestmark = pytest.mark.stub`；helper `test_save_and_confirm`→`_save_and_confirm`（避免被收集为用例） | CI `-m "not stub"` 下不再连接报错 |
| 8 | redis_bus "待实现" 残留注释 | ✅ | `backend/bus/redis_bus.py`（grep 无 `待实现`，前置任务已清） | 复核确认 |
| 8 | T-D07 超时语义注释漂移 | ✅ | `backend/tools/registry.py:231/314/327`、`backend/agents/permission.py:128`（均已写"超时视为 deny / fail-closed"） | 复核确认已修 |
| 8 | 冗余 import（NEW-C5-06） | ✅ | `backend/memory/consolidator.py:141`（删除重复 `from memory.vector import vector_manager`） | 第 79 行已导入 |
| 8 | 硬编码 deepseek 注释（NEW-C11-04） | ✅ | `backend/tools/builtin_tools.py` `generate_action_options`（加注释说明未走 load_agent_config） | 仅注释，不改行为 |
| 8 | roll_check 死参注释（NEW-C11-06） | ✅ | `backend/tools/builtin_tools.py` `_roll_check`（`difficulty` 形参 + docstring 注明当前未参与计算） | 仅注释 |
| 8 | MCP schema 注释 | ✅ | `backend/tools/mcp_bridge.py` `register_to_registry`（注释说明静态配置用通用 args 占位，真实 schema 走动态发现路径） | 仅注释 |
| 9 | 删除 `_smoke_init.py` / `_smoke_char.py` | ✅ | 仓库根（已删除两文件） | — |

---

## 2. 验证结果

| 检查 | 命令 | 结果 |
|---|---|---|
| py_compile（全部编辑 .py，21 个） | `python -m py_compile <files>` | `EXIT=0` |
| 导入冒烟 | `python -c "import backend.api.routers.stream, backend.bus.redis_bus, backend.bus.interface, backend.api.routers.characters, backend.memory.extract_queue, backend.memory.consolidator, backend.tools.mcp_bridge, backend.tools.builtin_tools, backend.prompts.registry, backend.prompts.token_budget, backend.skills.watcher, backend.agents.state"` | `IMPORT_SMOKE_OK` / `EXIT=0` |
| pytest 收集（全量） | `python -m pytest tests backend/tests --collect-only -q` | **`61 tests collected in 0.13s` / EXIT=0** |
| pytest 收集（CI 口径） | `python -m pytest tests backend/tests --collect-only -q -m "not stub"` | `10/61 tests collected (51 deselected)` / EXIT=0 |
| STUB-T10 运行 | `python -m pytest backend/tests/test_round10.py::test_extract_queue_tier_logic -m stub -q` | `1 passed` / EXIT=0 |
| 前端构建 | `npm run build`（frontend/） | **`built in 1.56s` / EXIT=0** |

### 关键结果行

```
pytest --collect-only:  61 tests collected in 0.13s   (EXIT=0)
                        -m "not stub": 10/61 collected (51 deselected)
npm run build:          ✓ built in 1.56s              (EXIT=0)
```

> 构建告警（chunk > 500kB、idb.ts 动态/静态混合导入）为既有项，非本次引入。

---

## 3. 诚实说明（部分 / 决策）

- **on_part_done 接线点选择**：未放在 `event_bus.py`/`redis_bus.py`，而是 `bus/interface.py` 的 `publish_part_done()` 唯一出口，懒导入 `hook_manager` + try/except，避免 bus 反向耦合 hook 系统。语义上所有 Part 结束都会触发，与上游 agent 无关。
- **character_v4 校验为"软校验"**：失败仅 `logger.warning` 并回退规范化默认值，不硬阻断创建/更新，避免坏输入直接 500。
- **前端 v4 适配落在 `CharacterEditor.tsx`**：`CharacterCreator.tsx` 是向导流且把字段编辑委托给 `CharacterEditor`，故 v4 字段编辑统一在 Editor 实现；`loadout.equipped` 为只读展示（编辑装备需走库存交互，超出本次范围）。
- **STUB-T10**：通过把 tier 判定逻辑抽成 `extract_queue.determine_tier()` 并让测试导入真实函数解决；其余 `test_round10.py` 用例仍是静态源码子串检查，故整文件保留 `stub` 标注。
- **t1_~t7_ / 静态桩**：按"显式归类为脚本/标 stub"处理（改 `test_*` 命名使其可被发现，但 `stub` marker 让 CI `-m "not stub"` 排除），未强行改写为运行时断言以免引入脆弱依赖。
- **task 8 注释项**：`redis_bus 待实现`、`T-D07` 在前置任务中已修复，本次为复核确认；新改动为 `consolidator` 冗余 import（删除）+ `builtin_tools`（deepseek / roll_check）+ `mcp_bridge`（schema）三处注释，均"仅注释/安全删冗余 import"，不改运行时行为。

可选重依赖（playwright / requests / aiohttp / simpleeval 等）保持惰性导入与降级路径，未在模块顶层强制要求。
