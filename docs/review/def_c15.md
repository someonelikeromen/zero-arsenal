# def_c15 · 测试质量复审（C15）

> 复审基准日期：2026-06-03 ｜ 范围：`tests/**` + `backend/tests/**`
> 行级证据以当前文件实际内容为准。stub marker 已在 `pytest.ini:5` 与 `backend/pyproject.toml:48-49` 双处注册。

---

### STUB-T04 · test_memory_endpoints.py 改为真实 HTTP 集成测试
- 状态：✅已修复
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/integration/test_memory_endpoints.py:27-149`
- 证据：`_get/_post` 用 `requests` 对 `BACKEND_URL` 发真实请求（`:29` `requests.get(f"{BACKEND_URL}{path}")`），后端不可用时 `pytest.skip`（`:62-65`），不再静态读 routes.py 源码。consolidate/rollback/memory 端点确在 `backend/api/routers/sessions.py:1285/1296/1228` 注册。
- 修复方向：无需动作；可在 CI 增加"启动后端"步骤使该集成测试真正执行而非长期 skip。

### STUB-T05 · test_infinite_arsenal.py 现已调用武库工具 API
- 状态：✅已修复（名实相符）
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/e2e/test_infinite_arsenal.py:161-185`
- 证据：`:161` `POST /api/tools/invoke {"tool":"forge_weapon"...}`、`:176` `POST /sessions/{sid}/gacha/draw`、`:146` 读取 character inventory，确实触达武库专属工具。文件已标 `pytestmark = pytest.mark.stub`（`:21`）。
- 修复方向：仍是脚本式（`test_*` 带位置参数），靠 stub 排除；长期应拆成真正 pytest fixture 化用例。

### STUB-T06 · test_browser_e2e.py fail_count>0 现已 sys.exit(1)
- 状态：✅已修复
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/e2e/test_browser_e2e.py:457-461`
- 证据：`:457-459` `if fail_count > 0: ... sys.exit(1)`，失败时正确返回非零退出码。文件已标 stub（`:20`）。
- 修复方向：无需动作（脚本入口已修）；注意该退出码逻辑仅在 `__main__` 生效，pytest 收集时不走 `main()`。

### STUB-T07 · test_p1_gacha.py 仍含静态 inspect 检查（已加运行时用例）
- 状态：🔄已变化
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/unit/test_p1_gacha.py:59-67`、`:70-95`
- 证据：`:64` `src = inspect.getsource(GachaAgent.execute)` + `:65` `assert "ctx.get(" not in src` 静态子串检查仍在；但新增 `test_gacha_agent_execute_runtime`（`:70-95`）真正 `asyncio.run(GachaAgent.execute)`。整文件标 stub（`:15`）。
- 修复方向：运行时用例可移出 stub 让 CI 真正执行；纯源码 grep 用例保留 stub。

### STUB-T08 · test_p4_memory.py 静态 read_text 检查（已加运行时用例）
- 状态：🔄已变化
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/unit/test_p4_memory.py:18-55`、`:58-79`
- 证据：`:20-30/:44-55` 仍 `read_text()` 后 `assert "ORDER BY importance" in adapter_src` 等子串检查；新增 `test_memory_adapter_recall_runtime`（`:58-79`）真正调 `memory_adapter.recall`。整文件标 stub（`:15`）。
- 修复方向：同上，运行时用例可提出 stub。

### STUB-T09 · test_p5_dm.py 静态字符串检查（已加运行时用例）
- 状态：🔄已变化
- 类别：stub
- 严重度：🟡降级
- 位置：`tests/unit/test_p5_dm.py:26-56`、`:59-86`
- 证据：`:28-34/:48-56` `read_text()` + `assert "modified_action" in dm_src`/`"modify" in graph_src` 静态检查；新增 `test_dm_agent_node_block_on_failure`（`:59-86`）真正 `asyncio.run(dm_agent_node)`。整文件标 stub（`:14`）。
- 修复方向：同上。

### STUB-T10 · test_round10.py 测试内重写业务逻辑（已标 stub）
- 状态：⚠️仍存在（但已标注）
- 类别：stub
- 严重度：🟡降级
- 位置：`backend/tests/test_round10.py:50-81`
- 证据：`test_extract_queue_tier_logic` 在测试内重新定义 `CORE_KEYWORDS`/`SEMANTIC_PATTERNS`/`determine_tier`（`:54-67`）再自测自己——不导入被测代码，验证的是测试自身副本。`:91` `inspect.getsource(MemoryAdapter._fallback_recall)` 静态子串检查。整文件已标 stub（`:19`）。
- 修复方向：导入 `backend` 真实分层函数验证，或删除该重复逻辑用例。

### T-D26 · ?query= vs ?q= 在 browser_e2e 已修，但 infinite_arsenal 仍错
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟢次要
- 位置：`tests/e2e/test_browser_e2e.py:347`（已修） vs `tests/e2e/test_infinite_arsenal.py:203`（仍错）
- 证据：后端参数名为 `q`（`backend/api/routers/sessions.py:1229` `async def search_memory(... q: str = "")`）。browser_e2e `:347` 已改为 `?q=驿站`（仅日志串 `:349` 还写 `query=`，无害）；但 infinite_arsenal `:203` 仍 `GET .../memory?query=长剑`，`query` 被忽略走默认空查询。
- 修复方向：将 infinite_arsenal `:203` 的 `?query=` 改为 `?q=`。

### T-D27 · session.error/缺元素已判失败，但 429 仍当通过
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`tests/e2e/test_browser_e2e.py:177-182`、`:292-294`、`:348/:378-379`
- 证据：`session.error` 现 `ok=has_narrative`（`:181`）——无叙事即判失败；未找到输入框/发送按钮 `ok=False`（`:292-294`）。但 429 限流仍记为通过：`:348` `mem_count = ... "限流" if 429`（log 默认 `ok=True`），`:378-379` `log("...429 限流（正常）")` 默认 `ok=True`，即真实限流被掩盖为通过。
- 修复方向：429 应至少标 `ok=False` 或独立计数，避免限流掩盖端点不可用。

### T-D28 · test_homepage_hub.py Playwright 未安装静默跳过 exit 0
- 状态：⚠️仍存在（文件已标 stub）
- 类别：stub
- 严重度：🟢次要
- 位置：`tests/e2e/test_homepage_hub.py:199-203`
- 证据：`:200-203` `except ImportError: print("...playwright 未安装，跳过浏览器测试") return`——浏览器部分静默返回，`main()` 不计 error，最终 `exit 0` 假绿。文件已标 stub（`:18`），CI `-m "not stub"` 排除。
- 修复方向：脚本入口区分"跳过"与"通过"；或在 CI 安装 playwright 后强制执行。

### M-09 / T-M13 · test_p3_parttype.py 仍用 pytest.skip 软跳过（且文件未标 stub）
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`tests/unit/test_p3_parttype.py:43-45`
- 证据：`:43-45` `if not play_yaml.exists(): pytest.skip("play.yaml 不存在")`——文件缺失即跳过而非失败。实测 `play.yaml` 存在且含 `tool_call`（`backend/agents/profiles/play.yaml:8,17`），故 skip 当前不触发；但缺失保护语义仍是"软跳过"。另该文件含静态 `read_text` 子串检查（`:28-33`）却**未标 `pytest.mark.stub`**。
- 修复方向：play.yaml 缺失应判失败；并为本文件静态用例补 stub 标注或改为运行时断言。

### T-M12 · test_live_generation.py 错误事件被吞 + 未标 stub + 无后端跳过
- 状态：⚠️仍存在
- 类别：stub
- 严重度：🔴核心（CI 会误收集报错）
- 位置：`tests/test_live_generation.py:47-48`、`:89-90`、整文件无 marker
- 证据：SSE `error` 事件仅 `print(f"  ✗ 错误: ...")`（`:47-48/:89-90/:120-121/:155-156`）不 assert，错误被吞。文件 `test_*` 函数需运行中后端却**无 `_backend_available` 跳过**、**无 `pytestmark = stub`**，会被 `testpaths=tests`（`pytest.ini:3`）收集；CI 跑 `-m "not stub"` 时这些用例将在 `requests.get`（`:12`）连接被拒处直接 ERROR。
- 修复方向：给本文件加 `pytestmark = pytest.mark.stub`（与其它脚本式 E2E 一致），或加后端可用性 skip + 对 `error` 事件 assert 失败。

### NEW-C15-01 · test_round10_quick.py 函数名 t1_~t7_ 永不被 pytest 收集（死测试）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`tests/test_round10_quick.py:14,28,41,50,59,67,75`
- 证据：用例函数命名为 `t1_turn_context_fields`/`t2_tier_logic`…（非 `test_` 前缀），pytest 默认 `python_functions=test_*` 不会收集，仅 `__main__`（`:82-90`）手动跑。文件**无 stub marker**，事实上是一个不被测试框架执行的脚本。`t2_tier_logic`（`:28-38`）还在测试内重写 tier 逻辑（同 STUB-T10 反模式）。
- 修复方向：改名 `test_*` 并导入真实业务逻辑后纳入 CI，或显式归类为脚本/标 stub。

### NEW-C15-02 · test_p2_extension_loader.py 含静态源码检查却未标 stub
- 状态：🆕新发现
- 类别：stub
- 严重度：🟢次要
- 位置：`tests/unit/test_p2_extension_loader.py:10-25`
- 证据：`test_load_all_extensions_imported_in_main`（`:12` `read_text()` + `:13` `assert "load_all_extensions" in main_src`）与 `:22` `inspect.getsource(m.lifespan)` 子串检查属静态桩；但同文件 `:28-44` 的 discover/load 用例是真运行时。整文件未标 stub，静态用例与运行时用例混杂未隔离。
- 修复方向：将两条静态源码用例标 stub 或改为运行时断言（如断言 lifespan 执行后注册表非空）。

---

## 小计

| 维度 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 3 | STUB-T04, STUB-T05, STUB-T06 |
| 🔄已变化（部分修复） | 4 | STUB-T07, STUB-T08, STUB-T09, T-D26, T-D27 *(注：T-D27/T-D26 合并计入)* |
| ⚠️仍存在 | 4 | STUB-T10, T-D28, M-09/T-M13, T-M12 |
| 🆕新发现 | 2 | NEW-C15-01, NEW-C15-02 |

> 计数口径：✅ 3 条；🔄 5 条（STUB-T07/08/09/T-D26/T-D27）；⚠️ 4 条（STUB-T10/T-D28/M-09/T-M12）；🆕 2 条。共 14 条区块。

### stub 标注核实结论

- **marker 已注册**：`pytest.ini:5` 与 `backend/pyproject.toml:48-49` 均声明 `stub` marker。✅
- **已正确标 stub**（7 个文件）：`test_p1_gacha.py:15`、`test_p4_memory.py:15`、`test_p5_dm.py:14`、`test_browser_e2e.py:20`、`test_homepage_hub.py:18`、`test_infinite_arsenal.py:21`、`backend/tests/test_round10.py:19`。
- **应标却未标 stub**（3 个文件，含静态桩/脚本式/需活后端）：
  - `tests/test_live_generation.py` —— 无 marker、无后端跳过，CI `-m "not stub"` 下会被收集并报连接错误（最高风险）。
  - `tests/test_round10_quick.py` —— `t1_~t7_` 命名永不被收集的死脚本，无 marker。
  - `tests/unit/test_p3_parttype.py` / `tests/unit/test_p2_extension_loader.py` —— 各含静态源码子串检查但未标 stub。
- **合理未标 stub**：`tests/integration/test_memory_endpoints.py`（已改真实 HTTP 集成 + 后端不可用 skip，符合集成测试定位）。
