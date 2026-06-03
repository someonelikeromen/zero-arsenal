# conf_b10 · 设计符合度审计 — 维度 B「权限模式」

> 设计权威：`docs/design/10-permission-modes.md`
> 复审基准日期：2026-06-03
> 审计范围：`backend/agents/permission.py` + `ask_handler.py` + `tools/registry.py` + `extensions/plugin.py` + `extensions/rules_loader.py` + `agents/profiles/*.yaml` + 前端 `PermissionDialog.tsx` / `ModeSelector.tsx`

> ⚠️ 重要前提：设计文档 10 自身存在**内部不一致**。§2「设计草案 vs 实现差异对照」是对实现的**逆向描述**（line 80/108 称 play=ALLOW、plan=ASK），而 §3.1/§3.2/§3.3 仍是**原始设计意图**（dict 形式 `tool_permissions`，play 默认 ask、plan/review 白名单 deny）。本审计以 §3 的设计意图为「设计要求」基准，§2 视为已被实现改写的草案。

---

## 2. `AgentProfile` 数据结构

- 设计要求：`permissions: list[ToolPermission]`（有序列表，glob 首次匹配）+ `default_permission` + `active_tools` + `visible_part_types` + `max_tokens_per_turn`；overlay 通过 `apply_plugin_overlay(profile, overlay)` 深拷贝注入，不污染全局 Profile。
- 实现状态：完整
- 证据：`backend/agents/permission.py:24-58`（`ToolPermission.matches` 用 `fnmatch`；`check_tool` 顺序匹配 + 退到 `default_permission`），`permission.py:307-323`（`apply_plugin_overlay` 用 `copy.deepcopy` 返回独立副本）
- 差距：结构与 §2 完全一致。实现额外新增 `allowed_groups` 字段（`permission.py:42`，07-tool-registry §3 用），设计 §2 未列出该字段。
- 处置：补/改设计文档（在 §2 字段表补 `allowed_groups`）

---

## 3.1 `play` 模式（正常跑团）— ⚠️ B07 重点

- 设计要求（§3.1）：play 默认 `default_permission="ask"`；`edit_character: ask`、`purchase_item: ask`（消费/不可逆操作保留确认），其余叙事/只读工具 allow。
- 实现状态：偏离（确认 B07）
- 证据：`backend/agents/permission.py:95-118` 与 `backend/agents/profiles/play.yaml:21-67`：`default_permission: allow`、catch-all `* → allow`、`purchase_* → allow`(yaml:48)、`update_character_state → allow`(yaml:41)、`earn_*/award_* → allow`(yaml:43-46)。play 模式下唯一保留 ask 的仅 `delete_*`/`reset_*`/`draw_gacha`(yaml:55-61)。
- 差距：设计 §3.1 要求 `ask` 的「消费类操作」（purchase / 角色大改）被系统性放宽为 `allow`，且兜底从 `ask` 改为 `allow`。与设计「消费类操作需玩家确认」的安全阀意图不符；YAML 注释「60s 超时自动允许」(yaml:54) 又与实际 ask 超时→deny 行为(`ask_handler.py:33-36`)矛盾。
- 处置：补实现（恢复 `purchase_*`/角色大改为 `ask`）或补/改设计文档（§3.1 显式声明 play 已改为 allow-by-default、放弃消费确认）——二选一，需产品决策。

---

## 3.2 `plan` 模式（策划 / 只读分析）

- 设计要求（§3.2）：白名单策略，`"*": "deny"` + `default_permission=deny` 双重保险；仅开放 `search_lore`/`query_character`/`load_skill`/`outline_chapter`；**绝不能触发骰点或写入正文**。
- 实现状态：偏离
- 证据：`backend/agents/permission.py:120-157` 与 `profiles/plan.yaml:37-77`：`default_permission: ask`、catch-all `* → ask`（非 deny）；`roll_* → allow`(yaml:50-51) 且 `roll_check` 在 active_tools(yaml:31)；写操作 `write_*/update_*/add_* → ask`。
- 差距：(1) 兜底由设计的 `deny` 双保险改为 `ask`，丧失白名单语义；(2) **plan 允许 `roll_*`（掷骰），直接违反设计「绝不能触发骰点」**；(3) 写操作设计应被白名单挡掉，实现改为可 ask 放行。
- 处置：补实现（plan 改 deny-by-default 白名单、移除 roll_* allow）或补/改设计（承认 plan 改为 ask-gated 而非纯只读）。

---

## 3.3 `review` 模式（审校）— 🆕 新发现 NEW-B10-01

- 设计要求（§3.3）：白名单只读，`read_chapter`/`style_check`/`purity_check` allow，其余 `* → deny`，`default_permission=deny`。
- 实现状态：偏离（核心审校工具被误 deny）
- 证据：`backend/agents/permission.py:159-187` 与 `profiles/review.yaml:36-56`：allow 模式为 `read_*`/`get_*`/`list_*`/`search_*`/`query_*`/`check_*`/`generate_action_options`，末尾 `* → deny`，`default_permission=deny`。`style_check`/`purity_check` 同时被列入 active_tools(`permission.py:167-168`、yaml 缺这两项)。
- 差距：`style_check`、`purity_check` **不匹配任何 allow pattern**（`check_*` 要求以 `check_` 开头，而 `style_check`/`purity_check` 以 `style`/`purity` 开头），因此落到 `* → deny`，被静默拒绝。即 review 模式两个核心审校工具被自身权限规则禁掉，与设计 §3.3 直接冲突。另：内置 Python Profile 的 active_tools 含 `style_check`/`purity_check`，但 `review.yaml`(yaml:24-34) 的 active_tools **不含**这两项，YAML 覆盖内置后二者甚至不会注入 LLM。
- 处置：补实现（在 review permissions 显式加 `style_check → allow`、`purity_check → allow`，并在 review.yaml active_tools 补回 read_chapter/style_check/purity_check）。

---

## 3.4 内置模式注册表

- 设计要求（§3.4）：`AgentProfileRegistry` 注册 play/plan/review；`get(name)` 对未注册名 `raise KeyError`。
- 实现状态：偏离
- 证据：`backend/agents/permission.py:250-298`：`ProfileRegistry`（实例而非 ClassVar）注册三模式后再用 YAML 覆盖；`get()`(`permission.py:260-261`) 对未注册名**返回 `PLAY_PROFILE`** 而非抛 `KeyError`。
- 差距：类名/结构不同（实例 vs 类方法，设计接受差异）；`get` 容错语义相反（静默 fallback 到 play，可能掩盖错误模式名）。
- 处置：补/改设计文档（说明 get 改为 fallback 容错）；模式切换 API 已另做 400 校验，风险有限。

---

## 4. 权限匹配算法（优先级与 glob）

- 设计要求（§4.1/§4.4）：`精确匹配 > overlay > 通配符 > default`，精确匹配优先于通配符。
- 实现状态：部分（偏离精确优先语义）
- 证据：`backend/agents/permission.py:46-54`（`check_tool` 纯按列表顺序首次匹配，无「精确 > 通配」的分级，仅靠 `*` 排在列表末尾近似实现）；`permission.py:322`（overlay 插入列表**头部 = 最高优先级**）。
- 差距：(1) 无显式「精确优先于通配」逻辑，依赖作者把具体规则排在 `*` 之前——若 YAML 顺序写错会失效；(2) overlay 在实现中优先级**高于一切**，而设计 §4.4 要求 overlay **低于精确匹配**。语义偏离。
- 处置：补/改设计文档（明确改为「列表顺序优先 + overlay 置顶」），或补实现（overlay 插在精确规则之后）。

- 设计要求（§4.2 `check_and_gate`）：deny → 抛 `PermissionDeniedError`；ask → emit `permission.ask` 挂起。
- 实现状态：偏离
- 证据：`backend/tools/registry.py:186-198`：deny 返回 `{"error": ...}` 字典而非抛异常；ask 走 `_wait_for_permission`→`ask_handler.check_permission_and_ask`(`ask_handler.py:83-140`)。
- 差距：deny 不抛 `PermissionDeniedError`，改为返回错误结果（行为等价但不符设计的异常契约）。
- 处置：补/改设计文档（deny 改为返回 error dict）。

---

## 6. `ask` 权限交互流程

- 设计要求（§6.1）：tool ask → emit `permission.ask` BusEvent → SSE 推前端 → PermissionDialog → `POST /asks/{id}` allow/deny → 恢复/取消。
- 实现状态：完整
- 证据：后端 `ask_handler.py:107-118`（create_ask + publish `PERMISSION_ASK`），`bus/event_types.py:32-34`（`permission.ask/granted/denied`）；前端 `lib/bindSSEToStores.ts:126-137`（消费 permission.ask → addPendingAsk，granted/denied → remove），`pages/SessionPage.tsx:538-546`（渲染 PermissionDialog），`components/PermissionDialog.tsx:22-31`（调用 `api.resolveAsk`），后端 `sessions.py:818-826`（`POST /asks/{ask_id}` resolve）。
- 差距：链路完整闭环。设计 §6.1「deny 时写入 dm_note Part」未实现——仅 publish permission.denied，无 dm_note Part 落库。
- 处置：补实现（deny 时追加 dm_note Part）或补/改设计（移除该要求）。

- 设计要求（§6.3）：等待用户决策，超时 60s 自动 `deny`。
- 实现状态：完整（含一处文档矛盾）
- 证据：`ask_handler.py:16`（`ASK_TIMEOUT_SECONDS = 60`），`ask_handler.py:30-36`（`asyncio.wait_for` 超时 → `_decision = "deny"`）。
- 差距：行为符合设计（超时 deny）。但 `tools/registry.py:255` 注释「超时后默认允许（fail-open）」与 `play.yaml:54` 注释「60s 超时自动允许」均与实际 deny 行为矛盾，属误导性注释。
- 处置：补实现（修正两处误导注释为「超时 deny」）。

---

## 5. WorldPlugin 自定义 AgentProfile（overlay）

- 设计要求（§5.1）：overlay 不替换整个 Profile，运行时叠加且**保持基础 Profile 不变**。
- 实现状态：部分（双实现，其一污染全局）
- 证据：✅ `permission.py:307-323` `apply_plugin_overlay` 深拷贝，模式切换调用此函数（`sessions.py:345,370`），不污染全局；❌ `extensions/plugin.py:163-187` `WorldPlugin.apply_permission_overlay` 直接 `profile.permissions.insert(0, ...)` **就地修改全局注册的 Profile**。
- 差距：存在两条 overlay 路径，`plugin.apply_permission_overlay` 会污染全局基础 Profile，违反设计「基础 Profile 不变」；且重复应用会不断在头部堆积规则。
- 处置：补实现（让 `apply_permission_overlay` 也走深拷贝 + set_session_profile，或废弃该方法统一用 `apply_plugin_overlay`）。

---

## 7. 模式切换 API

- 设计要求（§7.1/§7.3）：`PATCH /api/sessions/{id}/mode`，重应用 overlay，持久化，发布 `session.mode_changed`，返回 previous_mode + active_tools。
- 实现状态：完整
- 证据：`sessions.py:325-399`（PATCH /mode：UPDATE mode、重建 overlay 副本、`set_session_profile`、publish `SESSION_MODE_CHANGED`、返回 previous_mode/active_tools），`sessions.py:402-409`（POST 别名）。
- 差距：响应缺 §7 示例中的 `switched_at` 字段（次要）。
- 处置：补实现（返回体补 switched_at）或补/改设计（删除该字段）。

- 设计要求（§7.4）：非注册模式名返回 400，body 含 `available_modes`。
- 实现状态：部分
- 证据：`sessions.py:328-329`：`if req.mode not in ("play","plan","review"): raise HTTPException(400, f"Invalid mode: {req.mode}")`。
- 差距：返回 400 正确，但 body 是纯文本 detail，缺设计要求的结构化 `{error, message, details.available_modes}`；且合法模式名为硬编码字面量，未读注册表（新增 YAML 自定义模式无法通过校验）。
- 处置：补实现（改为查 `profile_registry.list_profiles()` 校验 + 结构化错误体）。

---

## C8 相关：rules_loader 加载 default_permission

- 设计要求：YAML Profile 应正确解析 `default_permission`（未知值兜底 DENY），C8 防回归。
- 实现状态：完整（但归属文件与任务描述不符）
- 证据：`backend/extensions/rules_loader.py` **不加载 AgentProfile**——仅扫描 `extensions/*/rules/*.md` 生成 `RuleEntry`（`rules_loader.py:18-161`），无 default_permission 概念。AgentProfile 的 YAML 加载实际在 `backend/agents/permission.py:195-232` 的 `_load_profile_from_yaml`：`permission.py:214-219` 正确读取 `default_permission`，未知值 catch `ValueError` 兜底 `DENY`，`permission.py:228` 传入 Profile。三个 YAML 均显式声明 default_permission（play.yaml:67、plan.yaml:77、review.yaml:56）。
- 差距：功能完整；任务描述把 AgentProfile 加载归到 `rules_loader.py` 有误，真实加载点在 `permission.py`。
- 处置：无需动作（C8 已正确实现）；建议复审任务表更正文件归属。

---

## 前端组件接线

- 设计要求：PermissionDialog 弹窗决策 + ModeSelector 三模式切换。
- 实现状态：完整
- 证据：`PermissionDialog.tsx:19-98`（工具名/原因/参数预览 + 允许/拒绝按钮 → `api.resolveAsk`），已接线 SSE→store→渲染（见 §6 证据链）；`ModeSelector.tsx:15-40`（play/plan/review 三按钮，tooltip 文案与各模式描述一致）。
- 差距：无明显缺口。ModeSelector tooltip（plan「写操作需确认」、review「严格只读」）与后端实际行为一致。
- 处置：无需动作

---

## 符合度小计

| 状态 | 计数 | 条目 |
|------|------|------|
| 完整 | 5 | §2 结构、§6 ask 流程、§6.3 超时、§7.1 切换 API、C8 default_permission、前端组件 |
| 部分 | 4 | §4 匹配优先级、§5 overlay 双实现、§7.4 非法模式校验、（§6 deny 缺 dm_note 归入部分）|
| 缺失 | 0 | — |
| 偏离 | 5 | §3.1 play（B07）、§3.2 plan（含掷骰）、§3.3 review（NEW-B10-01 核心工具被 deny）、§3.4 get 容错、§4.2 deny 不抛异常 |

> 注：「完整 6 / 部分 4 / 偏离 5」按上表条目计（C8 与前端各计入完整，共 6 项完整）。

**整体符合度估计 ≈ 60%**：核心交互链路（ask 流程、模式切换 API、前端接线、数据结构、C8）实现完整且闭环；但**三种内置模式的权限规则均与设计 §3 意图偏离**——play 被系统性放宽（B07 证实）、plan 违规允许掷骰、review 两个核心审校工具被自身规则误 deny（NEW-B10-01）。设计文档 §2 与 §3 自相矛盾，需先裁定权威基准再决定「补实现 or 改设计」。

### 新发现 / 关键偏离清单
- **NEW-B10-01**（🔴核心）：review 模式 `style_check`/`purity_check` 被 `*→deny` 拦截，审校无法执行（`permission.py:173-181`）。
- **B07 证实**（🔴核心）：play 模式 catch-all 与消费类工具被放宽为 allow，default=allow，丧失消费确认安全阀（`play.yaml:48,63,67`）。
- plan 模式允许 `roll_*` 掷骰，违反设计「绝不触发骰点」（`plan.yaml:50-51`）。
- `extensions/plugin.py:183` overlay 就地修改全局 Profile，污染基础 Profile。
