# def_c11 · 工具层代码缺陷复审（C11）

> 复审范围：`backend/tools/builtin_tools.py`、`registry.py`、`skill_loader.py`、`mcp_bridge.py`
> 复审基准日期：2026-06-03 · 只读复审，行级证据以当前文件为准。

---

## 一、旧报告条目复核

### D-10 · generate_action_options 失败回落到占位「行动选项 A/B/C」
- 状态：⚠️仍存在（已降为兜底）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:602-604`
- 证据：LLM 现为主路径（`:590-601` 真调用 `llm_complete`），但 `except:` 分支仍 `options = [{"label": labels[i], "text": f"行动选项 {labels[i]}"}]`，LLM 失败时给玩家无意义占位项。
- 修复方向：LLM 失败时返回 `{"ok": False, "error": ...}` 让上层重试，而非伪造选项；或至少在 text 中带场景上下文。

### D-11 · open_shop 失败回落到固定「普通长剑/生命药水」
- 状态：⚠️仍存在（已降为兜底）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:867-873`
- 证据：`except Exception as e:` → `items = [{"name":"普通长剑"...},{"name":"生命药水"...}]`，与世界设定（如科幻/现代）完全脱节。
- 修复方向：兜底时返回空货架 + error，或依 `world_plugin`/`shop_type` 选预设货架，禁止跨世界硬编码奇幻道具。

### D-12 · evaluate_item 失败回落到品质倍率公式估价
- 状态：⚠️仍存在（已降为兜底）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:916-923`
- 证据：`except:` → `quality_mult = {"common":1,"rare":5,...}` 后 `min/max/fair = 50/200/100 * mult`，与物品实际无关的纯倍率公式。
- 修复方向：估价失败时返回 error 标记不可估，由叙事层处理，而非给出貌似真实的伪价格。

### D-13 · get_npc_knowledge_scope 无档案 → 硬编码 knows/doesnt_know
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:306-309, 324, 326`
- 证据：`default_scope = {"knows":["当前场景发生的公开事件"], "doesnt_know":["玩家内心状态","其他NPC的私密信息"]}`，无档案或档案缺 `knowledge_scope` 字段时直接返回该硬编码值。
- 修复方向：无档案应返回 `found: False` 让 Agent 知晓信息缺口，而非伪装出一份通用边界（违反信息不对称约束）。

### D-14 · check_skill_trigger 仅关键词匹配，非真实规则引擎
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:396-400`
- 证据：注释自承「简单关键词匹配」，逻辑 `if skill_name.lower() in action_lower: triggered.append(...)`，仅按技能名出现在行动文本中触发，无条件/前置/语义判定。
- 修复方向：引入技能 `trigger_condition`（关键词组/属性阈值/状态门控）并由 RulesAgent 二次裁决，而非纯子串包含。

### D-15 · roll_check 读档失败 → 默认 pool=2
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/builtin_tools.py:230, 245-246`
- 证据：`pool = 2  # 默认最低骰池`；读取角色卡的 `try` 块 `except Exception: pass`，读档失败时静默沿用 pool=2，掩盖了「角色卡缺失/属性名错误」问题。
- 修复方向：读档失败应返回 error 或在结果中标注 `pool_source: "fallback"`，让上层感知数据缺失而非静默骰 2d。

### D-16 · registry 权限检查失败 fail-open → 是否已改 fail-closed
- 状态：✅已修复（ask 交互路径），但存在残留 fail-open
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/tools/registry.py:265-267`（已修）；`registry.py:234-242`（残留）
- 证据：`_wait_for_permission` 的 `except` 分支现为 `logger.warning("...fail-closed")` + `return False  # fail-closed`，ask-handler 异常时**拒绝**执行——已 fail-closed。✅ 但 `_resolve_permission` 的 `except: pass` 仍 `return tool.permission_required`，而绝大多数工具声明 `permission_required="allow"`（见 builtin_tools 全表），即 profile 子系统一旦抛错则回落到工具自带默认（多为 allow）——这是 profile 解析层的残留 fail-open。
- 修复方向：保留 ask 路径 fail-closed；将 `_resolve_permission` 异常回落改为 `"ask"` 或 `"deny"`，不应静默回落到工具自带 allow。

### D-17 · mcp_bridge 无 aiohttp / HTTP 失败 → return []
- 状态：🔄已变化（部分改善）
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/tools/mcp_bridge.py:60-61, 71-73`（fetch 仍 []）；`:117-118, 128-134`（call_tool 改返回 error）
- 证据：`fetch_tool_list` 无 aiohttp / 异常仍 `return []`，但 `discover()`（`:97-99`）已对空列表回落静态 `server.get("tools", [])`，属设计内降级；`call_tool` 现返回显式 `{"error": "aiohttp 未安装..."}` / `{"error": "HTTP {status}..."}` 而非 []。
- 修复方向：`fetch_tool_list` 的"无 aiohttp"分支可加一次性 warning 日志，避免 MCP 静默不可用。

### R-M06 · skill_loader 单文件注册失败静默 pass
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/tools/skill_loader.py:47-54`
- 证据：`_register_file` 整体 `try: ... except Exception: pass`，单个 SKILL.md 解析/读取失败时静默跳过，无任何日志，使用户无从发现技能丢失。
- 修复方向：`except` 中加 `logger.warning(f"skill register failed {path}: {e}")`，并在 discover 末尾汇报成功/失败计数。

---

## 二、新增发现（NEW-C11-xx）

### NEW-C11-01 · spawn_npc 与 query_npc_profile 存储位置不一致，spawned NPC 不可查
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`builtin_tools.py:540`（写 `npc_profiles` 表）vs `:268`（查 `world_archives`）+ `:284-296`（回退查 `character_cards.npc_profiles`）
- 证据：`spawn_npc` `INSERT ... INTO npc_profiles`；而 `query_npc_profile` 主查 `world_archives(archive_type='npc')`，回退查 `character_cards.data_json.npc_profiles`，**两条路径都不读 `npc_profiles` 表**——经 `spawn_npc` 创建的 NPC 永远 `found: False`。`get_npc_knowledge_scope` 同样只读 world_archives，对 spawned NPC 必返回硬编码 default（叠加放大 D-13）。
- 修复方向：统一 NPC 单一存储（建议 `npc_profiles` 表），让 query/scope/spawn/edit 四个工具读写同一处。

### NEW-C11-02 · update_npc_state 写 world_archives，edit_npc_state 写 npc_profiles 表（同实体双存储）
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟡降级
- 位置：`builtin_tools.py:337-363`（update_npc_state → world_archives）vs `:740-756`（edit_npc_state → npc_profiles 表）
- 证据：两个"更新 NPC 状态"工具写入不同的表，彼此修改互不可见，DM/RulesAgent 调用哪个取决于偶然，造成 NPC 状态分裂。
- 修复方向：合并为单一更新工具或统一目标表，与 NEW-C11-01 一并治理。

### NEW-C11-03 · _wait_for_permission/PLAY_PROFILE 文档与代码自相矛盾（声称 fail-open，实为 fail-closed/deny）
- 状态：🆕新发现
- 类别：dead（陈旧文档）
- 严重度：🟢次要
- 位置：`registry.py:252-255`（docstring "超时后默认允许（fail-open）"）vs `:267`（`return False`）；`permission.py:110`（注释 "60s 超时自动允许"）vs `ask_handler.py:34-35`（超时 `_decision = "deny"`）
- 证据：注释/docstring 仍描述旧的 fail-open 行为，与实际 fail-closed/deny 代码相反，易误导后续维护者改回 allow。
- 修复方向：同步注释与 docstring，统一表述为"超时/异常一律 deny"。

### NEW-C11-04 · generate_action_options 硬编码 provider/model="deepseek"，忽略会话 LLM 配置
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`builtin_tools.py:595`
- 证据：`provider="deepseek", model="deepseek-chat"` 直接写死，未走 `load_agent_config()`（对比 `outline_chapter:1121` 用 `cfg = load_agent_config("narrator")`）。用户若配置其他 provider，此工具仍强行打 deepseek，可能直接走兜底占位（叠加 D-10）。
- 修复方向：改用 `load_agent_config()` 读取 provider/model，与其它叙事工具一致。

### NEW-C11-05 · 两套 llm_complete 来源并存（..agents.llm vs ..llm.client），调用不一致
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`builtin_tools.py:564, 1088, 1352`（`from ..agents.llm import llm_complete`）vs `:832, 886`（`from ..llm.client import llm_complete`）
- 证据：同文件内不同工具从两个不同模块导入同名 `llm_complete`，open_shop/evaluate_item 与 generate_action_options/outline_chapter/fetch_web_lore 走不同客户端，行为（重试/配置/默认 provider）可能分叉。
- 修复方向：统一为单一 LLM 客户端入口，消除双实现风险。

### NEW-C11-06 · roll_check 接收 difficulty 参数但从不使用（死参数）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟡降级
- 位置：`builtin_tools.py:218`（形参 `difficulty: int = 1`）、`:248`（`RollRequest(pool=pool, threshold=8, ...)`）；schema 注册 `:1638`
- 证据：`difficulty` 在 schema 中向 LLM 暴露（"难度级别"），但函数体内 `threshold=8` 写死，`difficulty` 从未参与计算——LLM 传入的难度被静默丢弃。
- 修复方向：将 difficulty 映射到 threshold（或骰池惩罚），或从 schema 中移除该参数。

### NEW-C11-07 · generate_action_options 发布的 Part SSE message_id 与入库 message_id 不一致
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`builtin_tools.py:619-624`（DB 用解析出的 `msg_id`）vs `:638`（SSE 发布用 `_msg_id or "unknown"`）
- 证据：当 `_msg_id` 为空时，DB 行的 `message_id` 取自数据库最新消息（真实 id），但 `publish_part_created` 传的是字面 `"unknown"`，前端 `addPart` 可能挂到错误/不存在的消息上，导致选项卡渲染丢失。
- 修复方向：DB 与 SSE 复用同一个已解析的 `msg_id` 变量。

### NEW-C11-08 · skill_loader.evaluate_condition 对 SKILL.md frontmatter 执行 eval()
- 状态：🆕新发现
- 类别：degradation（安全）
- 严重度：🟡降级
- 位置：`skill_loader.py:167-176`
- 证据：`eval(skill.condition, {"__builtins__": {}}, {"state": state})` 执行技能文件中的任意表达式。虽屏蔽内置，但 eval 对第三方/扩展技能文件仍是攻击面（可读 state 任意字段，或借对象属性链逃逸）。
- 修复方向：改用受限表达式解析器（如 `simpleeval`）或显式 AST 白名单，禁止裸 `eval`。

### NEW-C11-09 · MCP 静态注册路径用通用 `{args:object}` 包装 schema，与 MCP 工具真实入参不符
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟢次要
- 位置：`mcp_bridge.py:160-169`
- 证据：`register_to_registry`（静态 mcp.json 路径）给所有工具统一 `properties:{args:{type:object}}`，LLM 看到的入参与 MCP 工具实际参数无关；而 `register_plugin_mcp_servers:223-227` 已用真实 `inputSchema`。静态路径会让 LLM 无法正确填参。
- 修复方向：静态路径也优先 `fetch_tool_list` 拿真实 `inputSchema`，或在 mcp.json 中要求声明每工具 schema。

---

## 三、小计

| 分类 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 1 | D-16（ask 路径 fail-closed） |
| 🔄已变化 | 1 | D-17 |
| ⚠️仍存在 | 6 | D-10, D-11, D-12, D-13, D-14, D-15, R-M06 |
| 🆕新发现 | 9 | NEW-C11-01 ~ 09 |

> 注：⚠️仍存在实为 7 条（含 R-M06）。
> 严重度分布：🔴 0 · 🟡 11 · 🟢 6。
> 工具层无"完全空壳"桩，旧 D-10~D-15 均已转为"LLM/DB 优先 + 兜底降级"形态，主要风险集中在**兜底伪造数据掩盖真实失败**与**NPC 三处存储不一致**（NEW-C11-01/02）。
