# 代码缺陷复审 — 分片 C2「叙事 Agent」（维度 A）

> 复审基准日期：2026-06-03
> 范围：`backend/agents/{npc,world,narrator,style,chronicler}_agent.py`
> 基线：`docs/STUB_ANALYSIS.md` D-03~D-08，逐条行级核实

---

### D-03 · npc_agent tool_loop 失败 → 固定台词「沉默地看着你」
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/npc_agent.py:109-128`、`:198-200`
- 证据：异常分支已改为 `bus.publish(... type="error" ...)` + `return {"response": None, "error": str(e)}`，且 `_npc_impl` 对 `result.get("error")` 执行 `continue` 过滤，不再注入固定台词；旧报告所述「失败→固定台词」在异常路径上已不成立。
- 修复方向：保留现状；残留问题见 NEW-C2-01（成功但空文本仍回退固定台词）。

### D-04 · world_agent 无触发词且非第5轮 → 跳过 LLM
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/world_agent.py:130-133`、门控 `:65-94`
- 证据：`if not _should_invoke_world_agent(ctx): ctx.world_events = []; return ctx`；门控仍为「关键词 OR 每5轮」，仅新增 `plot_pressure` 插件恒触发（`:78-80`）与扩充关键词表作缓解。非触发普通轮次仍完全跳过世界演变 LLM。
- 修复方向：可接受的成本优化，但建议对长时间无世界事件的会话降低 `% 5` 间隔或引入轻量启发式，避免世界长期静止。

### D-05 · world_agent LLM/JSON 失败 → world_events=[]
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/world_agent.py:178-179`
- 证据：`except Exception: ctx.world_events = []`，整段 LLM 调用与 JSON 解析的所有异常被吞掉，世界事件静默清空。
- 修复方向：世界事件本属可选，可接受；但应补 `logger.warning`/SSE error 以便排障（见 NEW-C2-05）。

### D-06 · style_agent 审查 JSON 失败 → 原文透传
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/style_agent.py:165-168`
- 证据：`except Exception as e: logger.warning(...); return ctx` — 审查 JSON 解析失败时直接返回，原文不经任何文风处理透传。程序化禁词扫描（`_program_purity_scan`）仅在 `pre_score < 0.4` 时独立兜底（`:101`），其余区间一旦 LLM 失败即放弃。
- 修复方向：失败时至少落地程序化扫描结果（见 NEW-C2-02），并按 pre_score 决定是否触发轻量润色。

### D-07 · chronicler_agent 摘要 LLM 失败 → return ""
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/chronicler_agent.py:297-302`
- 证据：`except Exception` 不再返回空串，改为 `lines = ...; preview = " ".join(lines[:5])[:200]; return f"[自动摘要] {preview}…"`，保证章节记录有降级内容；旧报告「失败→空串→摘要丢失」已不成立。
- 修复方向：无需动作。

### D-08 · narrator_agent P4 state_patch 提取失败 → return []
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/narrator_agent.py:485-487`、`:407-409`
- 证据：`_p4_llm_extract` 末尾 `except Exception: logger.debug(...); return []`；`_p4_settle` 亦 `except ...: patches = []`。当正文无显式 `{{CMD}}` 标记且 LLM 兜底提取失败时，本轮状态变更完全丢失。
- 修复方向：此为「兜底的兜底」，正文标记是主路径，可接受；建议失败时发 SSE/审计标记，避免状态静默不更新无感知。

---

### NEW-C2-01 · NPC tool_loop 成功但空文本仍回退固定台词
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/npc_agent.py:106`
- 证据：`"response": text or f"{npc_name}沉默地看着你。"` — tool_loop 未抛异常但 `text` 为空（LLM 返回空串/纯工具调用无终文）时，固定占位台词被当作真实 `dialogue`/`intention` 写入 `npc_action` Part 并喂给 Narrator（`:201-206`、`:217-234`），造成 NPC 行为与剧情脱节。
- 修复方向：空文本时与异常路径一致——发 error part 并跳过该 NPC，而非注入占位台词。

### NEW-C2-02 · style 审查失败时丢弃已算出的程序化纯净度结果
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/style_agent.py:98` vs `:165-168`
- 证据：`pre_score, pre_warnings = _program_purity_scan(...)` 已在 `:98` 算出，但当 `0.4 ≤ pre_score < 1.0` 且 LLM 解析抛异常时，`except` 分支直接 `return ctx`，从未将 `ctx.purity_score = pre_score` / `ctx.style_warnings = pre_warnings` 落地，程序化检测到的俗套警告被静默丢弃，下游 dm_note 文风报告缺失。
- 修复方向：`except` 分支先 `ctx.purity_score = pre_score; ctx.style_warnings = pre_warnings`，再返回。

### NEW-C2-03 · chronicler 每过阈值后逐轮重复固化（start_message_id 永不写入）
- 状态：🆕新发现
- 类别：dead / degradation
- 严重度：🔴核心
- 位置：`backend/agents/chronicler_agent.py:36-45`（`should_consolidate`）、`:183-197`（固化写入）
- 证据：`should_consolidate` 的子查询为 `SELECT start_message_id FROM chapters WHERE ... AND start_message_id IS NOT NULL`；但全代码库从无任何 `UPDATE/INSERT` 写 `start_message_id`（grep 仅 schema 定义 `db/schema.py:99` 与 sessions.py 读取展示）。子查询恒为空集 → `NOT IN (空)` 命中全部 messages → 会话消息数一旦达 20 即**每回合**返回 True；而固化分支仅把唯一 `is_consolidated=0` 章节转为已固化，之后无未固化章节 → 每轮 `INSERT` 一条新已固化章节，触发重复 LLM 摘要与章节膨胀。
- 修复方向：固化时写入本章 `start_message_id`/`end_message_id` 边界，并以「未固化章节内的消息数」而非全会话计数判定阈值。

### NEW-C2-04 · 章节摘要取「最近20条 narrative」不按固化边界，导致跨章重叠
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/agents/chronicler_agent.py:269-281`（`_get_recent_narratives`）、调用处 `:140-145`
- 证据：函数注释（`:140`）声称「取自上次固化后的所有 narrative Parts」，但 SQL 为 `WHERE session_id=? AND type='narrative' AND status='done' ORDER BY created_at DESC LIMIT 20`，无任何排除已固化区间的条件。连续固化会反复纳入同批旧叙事，章节摘要内容重叠/重复。
- 修复方向：按 chapter_anchors / 章节边界过滤未固化叙事，或与 NEW-C2-03 的 `start_message_id` 边界统一。

### NEW-C2-05 · world_agent 异常吞噬零日志，排障盲区
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/agents/world_agent.py:178-179`、`:230-231`
- 证据：LLM/JSON 分支 `except Exception: ctx.world_events = []` 与 Part 发布分支 `except Exception: pass` 均无 `logger`、无 SSE error；对比 narrator P3 失败会 `publish(PART_ERROR)`（`narrator_agent.py:353-360`），world 侧任何失败完全无痕，难以区分「克制不输出」与「调用崩溃」。
- 修复方向：两处 `except` 补 `logger.warning`，必要时发 part.error。

---

## 小计

| 状态 | 计数 | 条目 |
|------|:----:|------|
| ✅已修复 | 1 | D-07 |
| ⚠️仍存在 | 4 | D-04, D-05, D-06, D-08 |
| 🔄已变化 | 1 | D-03 |
| 🆕新发现 | 5 | NEW-C2-01~05 |
| **合计** | **11** | — |

严重度分布：🔴核心 ×1（NEW-C2-03）/ 🟡降级 ×6 / 🟢次要 ×4
