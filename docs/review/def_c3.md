# 代码缺陷复审 — 分片 C3「Agent 基础设施」

> 复审基准日期：2026-06-03 · 子代理 C3 · 只读复审
> 范围：`backend/agents/` 下 graph / state / llm / tool_loop / agent_node / agent_span / ask_handler / cancellation / compaction
> 维度 A 格式，行级证据以当前文件实际内容为准。

---

## 一、旧报告条目复核

### STUB-T01 · gacha_pending/gacha_granted 字段是否仍是孤岛
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/agents/tool_loop.py:409-418`、`backend/extensions/infinite_arsenal/agents.py:99-138`
- 证据：`tool_loop.py:416` 在 `draw_gacha` 成功后 `ctx.turn_ctx.gacha_pending.extend(result["results"])` 写入；`infinite_arsenal/agents.py:104` 的 `GachaAgent`（`insert_after="var"`）读取 `ctx.gacha_pending`、`:137-138` 清空并写 `gacha_granted`，链路完整。
- 修复方向：已闭环。仅需注意 `graph.py` 核心图无 gacha 节点，依赖 `_discover_extension_agents()` 成功导入 `infinite_arsenal`；扩展未加载时字段重新沦为孤岛（与 T-D10 关联）。

### D-09 · compaction 压缩失败静默跳过
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/compaction.py:78-79`
- 证据：`maybe_compact` 顶层 `except Exception as exc: logger.error("[Compaction] 压缩失败: %s", exc, exc_info=True)`，已带堆栈日志而非裸 `pass`；子函数 `:110`、`:133`、`:171` 亦记 warning。
- 修复方向：日志层面已不再静默；但功能上仍然吞掉异常返回原 ctx（用户侧无感知）。可按需向 Bus 推送一条降级提示。

### D-22 · tool_loop function calling 不可用 → 文本解析
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/tool_loop.py:120-157`、`:428-478`
- 证据：`:121` `use_fc = bool(agent_config.get("functions", True)) and bool(openai_tools)`；`:150-157` 非 fc 分支调用 `_parse_tool_calls_from_text`，支持 `<tool_call>` 与 ```json``` 两种格式（`:438`、`:460`）。
- 修复方向：回退已实现且可用。遗留缺口：回退**仅在配置显式 `functions:false` 时触发**，运行期 litellm 因 provider 不支持 FC 抛错时不会自动降级（会被 `run_tool_loop` 外层吞成 `("",[])`，见 NEW-C3-04）。建议在 FC 调用异常时自动切文本解析。

### T-D04/T-D05 · llm.py 找不到 agents.json/未配置 agent 时硬编码默认；仅处理 deepseek/openai
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/llm.py:38-44`、`:119-145`
- 证据：`:121` `_default` 硬编码 deepseek-chat；`:124-130`/`:136-144` 现已在缺文件/缺 agent 时通过 `_AGENT_CONFIG_WARNED` 去重 warning 后再返回默认（不再纯静默）；`_build_model_str:38-44` 仍仅识别 deepseek/openai，其它 provider 返回裸 model 名。
- 修复方向：警告化方向正确，但**警告语句本身崩溃**（`logger` 未定义，见 NEW-C3-01），实际触发时反而抛 NameError；另 provider 白名单仍需扩展或改 litellm provider 前缀透传。

### T-D08 · graph.py 并行子 Agent 异常静默
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/graph.py:90-104`
- 证据：`parallel_npc_world_node` 用 `asyncio.gather(..., return_exceptions=True)`，`:97`/`:102` 对异常 `_log.warning("parallel npc_agent failed...")`，已记录而非纯静默；但 npc/world 结果丢弃后主链路继续，用户侧不可见。
- 修复方向：保留降级，建议把失败计入 `ctx.warnings` 以便前端提示。

### T-D09 · options_node 失败仅日志
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/graph.py:159-160`
- 证据：`except Exception as e: _log.debug("[options_node] generate_action_options skipped: %s", e)`，仅 DEBUG 级，生产默认日志级别下等同静默吞错。
- 修复方向：行动选项缺失影响 play 体验，至少提升到 warning 或回退一组静态选项。

### T-D10 · 扩展 agents.py 导入失败仅 warning
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/graph.py:167-188`
- 证据：`_discover_extension_agents` 先试 `importlib.import_module(absolute)`，ImportError 时再试相对导入（`:183-184`），二次失败 `_log.debug`（`:186`），其它异常 `_log.warning`（`:188`）。
- 修复方向：可用的优雅降级；但 ImportError 二次失败仅 DEBUG，扩展加载失败在生产几乎不可见（与 STUB-T01 闭环依赖耦合）。建议统一 warning。

### T-D11 · agent_node insert_after 目标缺失
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/agent_node.py:132-135`
- 证据：`if next_node is None: _log.warning("insert_after target '%s' not in edge_map, skipping ...") ; continue`，目标缺失时**静默跳过整个扩展节点**，扩展功能被丢弃且仅 warning。
- 修复方向：节点被丢弃属功能性缺失，建议显式 raise 或将丢弃节点记入可查询的注入报告供运维核对。

### M-07 · state.py `_last=operator.attrgetter` 定义未使用
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/agents/state.py:24`
- 证据：`_last = operator.attrgetter  # 仅用于注释可读性`，全文件无任何引用 `_last`（reducer 实际用的是 `:25` 的 `_keep_last`）。
- 修复方向：删除该死变量及随附 `import operator`（若无其它用途）。

### M-08 · graph.py on_chapter_end hook 失败 pass
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/graph.py:129-130`
- 证据：`except Exception as e: _log.warning("[chronicler] on_chapter_end hook failed: %s", e)`，已由裸 pass 改为 warning 日志。
- 修复方向：无需动作。

### M-09 · chronicler_wrapper 不可达 return
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/agents/graph.py:133`
- 证据：`async with agent_span(...)` 块内 `:131 return result` 与 `:132 return ctx` 已覆盖两条分支并均在 with 内返回，函数末尾 `:133 return ctx` 永不可达。
- 修复方向：删除 `:133` 死代码（或将其作为 with 外兜底前移逻辑，但当前无意义）。

### M-10 · llm.py dotenv 缺失 except pass
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/llm.py:24-25`
- 证据：`except ImportError: pass` —— python-dotenv 缺失时静默跳过 .env 加载。
- 修复方向：属可接受的可选依赖降级；建议至少 `logging.debug` 一行说明未加载 .env（且需先修 NEW-C3-01 让 logger 可用）。

---

## 二、新增问题

### NEW-C3-01 · llm.py 使用未定义的 `logger` → 警告路径 NameError
- 状态：🆕新发现
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/agents/llm.py:126`、`:139`
- 证据：文件无 `import logging` 亦无 `logger =`（全文件 grep 无匹配），但 `load_agent_config` 在“agents.json 未找到”与“agent 未配置”两条分支调用 `logger.warning(...)`，命中即抛 `NameError: name 'logger' is not defined`。任意未在 `agents.json` 列出的 agent 名（如扩展自定义 agent、拼写错误）都会把本应优雅返回默认配置的路径变成硬崩溃。
- 修复方向：在文件顶部加 `import logging; logger = logging.getLogger(__name__)`。

### NEW-C3-02 · ask_handler 超时后 PendingAsk 永不回收（泄漏 + 残留挂起项）
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/ask_handler.py:30-36`、`:63-69`
- 证据：`PendingAsk.wait()` 超时仅设 `self._decision="deny"` 返回，不触发清理；只有外部 API 调 `AskManager.resolve()` 才会 `del self._pending[ask_id]`（`:68`）。ASK 超时（60s 自动 deny）的请求永远留在 `_pending` 字典中，`list_pending`（`:71-77`）会持续返回这些僵尸项，长会话累积内存泄漏并向前端展示已失效的待确认请求。
- 修复方向：`check_permission_and_ask` 在 `ask.wait()` 返回后无论结果都从 `ask_manager._pending` 移除（或在 `wait` 超时分支内回调清理）。

### NEW-C3-03 · compaction 只前缀摘要不裁剪原历史，可能不降反增 token
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/agents/compaction.py:66-71`
- 证据：触发压缩后仅把 `[历史摘要]\n{summary}` 前缀拼到 `ctx.memory_context`，未对源 narrative parts 或 memory_context 中既有内容做截断/替换。设计目标（文件头“压缩历史对话”）是降 token，实际是在原内容基础上**追加**摘要，单轮净增 token。
- 修复方向：压缩时应同步标记/截断被摘要覆盖的历史段，或让下游 prompt 组装在存在摘要时跳过对应原始 parts。

### NEW-C3-04 · run_tool_loop 顶层吞所有异常 → LLM/网络错误静默产出空文本
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/tool_loop.py:62-68`
- 证据：`try: return await _run(...) except Exception as e: logger.warning(...); return "", []`，litellm 调用失败（超时/限流/provider 不支持 FC）一律被压成空文本返回，调用方无法区分“模型没说话”与“调用失败”，且与 D-22 自动降级缺口叠加。
- 修复方向：区分可恢复错误（FC 不支持 → 转文本解析重试）与致命错误（向上抛或在返回结构中带 error 标记），避免静默空输出污染叙事。

### NEW-C3-05 · state.py dm_verdict 默认值 "allow" 与 DMDecision 字面量不一致
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/agents/state.py:121`、`:47`、`:186-187`
- 证据：`dm_verdict` 默认 `"allow"`，而 `DMDecision.verdict` 的 Literal 仅 `"pass"/"reject"/"modify"`（`:47`）；`dm_decision` property 用 `verdict_map={"allow":"pass",...}`（`:186`）兜底转换。默认值游离于声明的枚举之外，依赖隐式映射，易在新增分支时遗漏。
- 修复方向：将 `dm_verdict` 默认改为 `"pass"` 并统一全链路 verdict 取值；`_route_after_dm` 已兼容（`graph.py:72-77`），改动安全。

### NEW-C3-06 · tool_loop `_execute_one` 重复导入未使用的 BusEvent/EventType
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/agents/tool_loop.py:360`、`:374`
- 证据：两处 `from ..bus import bus, BusEvent, EventType`，但该函数体内仅用到 `bus`（`publish_part_created`/`publish_part_done`），`BusEvent`/`EventType` 未使用。
- 修复方向：精简为 `from ..bus import bus`。

---

## 小计

| 分类 | 计数 | 条目 |
|---|---|---|
| ✅ 已修复 | 2 | STUB-T01, M-08 |
| 🔄 已变化 | 5 | D-09, D-22, T-D04/T-D05, T-D08, T-D10 |
| ⚠️ 仍存在 | 5 | T-D09, T-D11, M-07, M-09, M-10 |
| 🆕 新发现 | 6 | NEW-C3-01(🔴), NEW-C3-02(🟡), NEW-C3-03(🟢), NEW-C3-04(🟡), NEW-C3-05(🟢), NEW-C3-06(🟢) |

> 最高优先级：**NEW-C3-01**（llm.py `logger` 未定义，警告路径直接 NameError，且恰好削弱了 T-D04/T-D05 的“警告化”修复）。
