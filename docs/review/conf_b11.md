# conf_b11 · 维度 B 设计符合度审计 — API 设计（11-api-design.md）

> 复审基准日期：2026-06-03
> 设计权威：`docs/design/11-api-design.md`
> 实现位置：`backend/api/routers/*.py`（聚合于 `backend/api/routes.py`，统一 `prefix="/api"`）
> 审计范围：设计文档第 2~9 节列出的全部 REST + SSE 端点 + 错误码规范

---

## 0. 端点对照清单（设计 → 实现）

设计文档共定义 **28 个对外端点**（27 REST + 1 SSE）。逐一比对结果如下：

| # | 设计端点（方法 + 路径，去 /api 前缀） | 实现状态 | 证据（routers 相对路径:行号） |
|---|------|------|------|
| 1 | `POST /sessions` | 偏离 | `backend/api/routers/sessions.py:92` |
| 2 | `GET /sessions/{id}` | 完整 | `sessions.py:208` |
| 3 | `DELETE /sessions/{id}` | 完整 | `sessions.py:412`（204 软删除） |
| 4 | `GET /sessions` | 完整 | `sessions.py:240`（cursor 分页 + world_plugin 过滤） |
| 5 | `POST /sessions/{id}/mode` | 部分 | `sessions.py:402`（POST 别名）+ `:325`（PATCH 主实现） |
| 6 | `POST /sessions/{id}/fork` | 完整 | `sessions.py:426` |
| 7 | `POST /sessions/{id}/message` | 完整 | `stream.py:30`（202 Accepted） |
| 8 | `GET /sessions/{id}/events`（SSE） | 完整 | `stream.py:307` |
| 9 | `GET /sessions/{id}/messages` | 完整 | `sessions.py:552` |
| 10 | `GET /sessions/{id}/parts` | 完整 | `sessions.py:631` |
| 11 | `POST /sessions/{id}/revert` | 完整 | `sessions.py:693` |
| 12 | `GET /sessions/{id}/character` | 偏离 | `sessions.py:756`（响应外层字段不符） |
| 13 | `PATCH /sessions/{id}/character` | 偏离 | `sessions.py:766`（请求体字段名不符） |
| 14 | `GET /sessions/{id}/world-archives` | 完整 | `sessions.py:1102` |
| 15 | `GET /sessions/{id}/asks` | 完整 | `sessions.py:812` |
| 16 | `POST /sessions/{id}/asks/{ask_id}` | 完整 | `sessions.py:818` |
| 17 | `GET /sessions/{id}/chapters` | 完整 | `sessions.py:831` |
| 18 | `POST /sessions/{id}/chapters/consolidate` | 完整 | `sessions.py:889` |
| 19 | `POST /sessions/{id}/chapters/{chap_id}/rollback` | 完整 | `sessions.py:929` |
| 20 | `POST /engine/roll` | 偏离 | `engine.py:22`（请求/响应字段名不符） |
| 21 | `GET /engine/skills` | 完整 | `engine.py:191` |
| 22 | `GET /engine/extensions` | 完整 | `engine.py:198` |
| 23 | `POST /mcp/connect` | 完整 | `config.py:174` |
| 24 | `DELETE /mcp/{name}` | 完整 | `config.py:195`（路径参数名 `server_id`） |
| 25 | `GET /config/world-plugins` | 完整 | `config.py:92` |
| 26 | `GET /config/agent-profiles` | 完整 | `config.py:116` |
| 27 | `GET /config/writing-styles` | 完整 | `config.py:134` |
| 28 | `PUT /config/llm-routes` | 完整 | `config.py:233` |

**结论：28 个设计端点全部存在实现，缺失 0 个。** 其中 4 个存在请求/响应模型偏离，1 个（mode）动词/字段部分不符。

---

## 1. 设计原则与全局约定

### §1 版本前缀 `/api`（不使用 `/api/v1/`）
- 设计要求：所有接口以 `/api/` 开头；`routes.py` 内部已设 `prefix="/api"`，各子 router 无额外前缀。
- 实现状态：完整
- 证据：`backend/api/routes.py:27` `router = APIRouter(prefix="/api")`，各子 router 直接 `@router.post("/sessions")` 无重复前缀。
- 差距：无。
- 处置：无需动作。

### §1.3 统一错误响应格式 `{error, message, details}`
- 设计要求：所有 4xx/5xx 统一返回 `error`（snake_case 码）+ `message` + `details`。
- 实现状态：完整
- 证据：`backend/main.py:356-380` 全局 `StarletteHTTPException` handler 输出 `{"error","message","details"}`；`:329` `_STATUS_TO_ERROR_CODE` 映射；`:342` `_MSG_FRAGMENT_TO_CODE` 语义化映射 `session_not_found`/`chapter_not_found` 等。
- 差距：无（格式与第 9 节完全对齐）。
- 处置：无需动作。

### §1.4 分页约定（cursor-based `{items, next_cursor, has_more}`）
- 设计要求：列表接口统一 cursor 分页。
- 实现状态：完整
- 证据：`sessions.py:240` list_sessions 用 base64 游标，返回 `items/next_cursor/has_more/total`（`:248-291`）。
- 差距：无。
- 处置：无需动作。

---

## 2. 会话管理

### §2 `POST /sessions` — 创建会话
- 设计要求：响应 201，字段含 `session_id/title/world_plugin/agent_profile/current_mode/created_at/status`，且示例 `"character": null`。
- 实现状态：偏离
- 证据：`sessions.py:195-205` 返回 `character`（**完整角色对象，非 null**）+ 额外 `chapter_id`；且未显式声明 201（默认 200）。`:193` `character_out = json.loads(...)`。
- 差距：① 创建即生成默认/模板角色卡并整体返回，与设计示例 `character: null` 不符（属功能增强：MVP 阶段角色随会话初始化）；② 多出 `chapter_id` 字段未记于设计；③ 状态码非 201。
- 处置：补/改设计文档（将 `character` 字段改为「创建时即返回完整角色卡」并补 `chapter_id`），状态码可不强求。
- 对应已知项：「create_session 返回 character 是否符合设计」——**结论：不完全符合**，实现返回完整角色而非设计示例的 `null`，属合理增强，建议改文档。

### §2 `GET /sessions/{id}`
- 设计要求：返回 `message_count`/`current_chapter{chapter_id,title,is_consolidated}`/`status` 等。
- 实现状态：完整
- 证据：`sessions.py:217-235` 计算 `message_count`、组装 `current_chapter`（含 `chapter_id`）。
- 差距：响应直接平铺 DB 行（含 `mode` 而非 `current_mode` 命名），字段命名轻微不一致。
- 处置：补/改设计文档（统一 `mode`/`current_mode` 命名）。

### §2 `PATCH /sessions/{id}` — 元数据更新（重命名）
- 设计要求：**设计文档未记录此端点**。
- 实现状态：偏离（代码有、设计无）
- 证据：`sessions.py:303-322` patch_session，支持 `title` 重命名，返回 `{ok, session_id, title}`。
- 差距：C14 报告称「PATCH /sessions/{id} 疑似缺失」——**核实结果：已存在并实现**，C14「已修复」属实。但设计文档第 2 节缺此端点说明。
- 处置：补/改设计文档（新增 `PATCH /sessions/{id}` 重命名端点）。

### §2 `POST /sessions/{id}/mode` — 切换模式
- 设计要求：响应 `{session_id, previous_mode, current_mode, active_tools, switched_at}`。
- 实现状态：部分
- 证据：`sessions.py:325` PATCH 主实现 + `:402` POST 别名；返回 `{ok, session_id, mode, previous_mode, active_tools}`（`:393-399`）。
- 差距：① 主动词为 PATCH，POST 仅别名（设计为 POST）——已对齐；② 响应用 `mode` 而非 `current_mode`，**缺 `switched_at` 字段**；③ 多 `ok` 字段。
- 处置：补/改设计文档或补 `switched_at`/`current_mode` 字段（建议统一字段名）。

### §2 `POST /sessions/{id}/fork`
- 设计要求：201，返回 `new_session_id/parent_session_id/branch_label/forked_from_message_id`。
- 实现状态：完整
- 证据：`sessions.py:426` fork_session。
- 差距：未抽查响应字段全等，按入参 `ForkRequest` 对齐。
- 处置：无需动作（建议后续抽查响应字段命名）。

---

## 3. 消息与对话

### §3 `POST /sessions/{id}/message`
- 设计要求：202 Accepted，返回 `{message_id, session_id, status:"processing", stream_url}`；触发 Agent 管线。
- 实现状态：完整
- 证据：`stream.py:30` `status_code=202`，`:69-74` 返回完全一致的 4 字段；`:68` 后台任务触发 `_run_agent_pipeline`。
- 差距：会话删除返回 410（设计第 9 节无 410，但语义合理）。
- 处置：补/改设计文档（错误码表补 410 gone）。

### §3 `GET /sessions/{id}/events`（SSE）
- 设计要求：`text/event-stream`，事件类型 `part.created/part.updated/part.done/permission.ask/session.mode_changed/session.idle/session.error/chapter.consolidated`，支持 `Last-Event-ID`。
- 实现状态：完整
- 证据：`stream.py:307` events 端点。事件类型由 `bus`（`publish_part_created/done`、`SESSION_MODE_CHANGED` 等）驱动，与设计事件全表对齐。
- 差距：未在本次抽查中逐一核对 `Last-Event-ID` 断线重连实现细节（建议 C-stream 切片确认）。
- 处置：无需动作（事件命名一致）。

### §3 `GET /sessions/{id}/messages` / `GET /sessions/{id}/parts` / `POST /sessions/{id}/revert`
- 设计要求：消息历史分页、Part 列表（type/message_id 过滤）、回滚返回 `reverted_to_message_id` 等。
- 实现状态：完整
- 证据：`sessions.py:552`（messages）、`:631`（parts）、`:693`（revert）。
- 差距：未抽查响应字段全等。
- 处置：无需动作。

---

## 4. 角色与状态

### §4 `GET /sessions/{id}/character`
- 设计要求：响应外层 `{session_id, character_version, snapshot_message_id, data:{...}}`。
- 实现状态：偏离
- 证据：`sessions.py:763` 返回 `{"character": <角色JSON>, "schema_version": ...}`。
- 差距：外层包装字段名不符（`character` vs `data`；`schema_version` vs `character_version`；**缺 `session_id`/`snapshot_message_id`**）。角色内层 schema 为 v4，与设计示例（扁平 attributes/skills/resources）也有结构差异。
- 处置：补/改设计文档（对齐 v4 角色卡 schema 与外层包装字段）。

### §4 `PATCH /sessions/{id}/character`
- 设计要求：请求体 `{commands:[{op,path,value,reason}], message_id}`，op ∈ set/increment/append/remove/merge；响应返回更新后完整角色卡。
- 实现状态：偏离
- 证据：`sessions.py:52-54` `PatchCharacterRequest` 字段为 `patches: list[dict]` + `raw_json`（**无 `commands`/`message_id` 字段**）；`:781-784` 走 `TavernCommandProcessor.apply_patches`；`:807` 返回 `{character, validation_warnings}`。
- 差距：① 请求字段名 `patches` 而非设计的 `commands`，且支持 `raw_json` 整体覆写（设计未提）；② 缺 `message_id`；③ 响应多 `validation_warnings`。底层 TavernCommand DSL 一致。
- 处置：补/改设计文档（请求字段名统一为 `patches` 或代码改名 `commands`，并补 `raw_json`/`validation_warnings` 说明）。

### §4 `GET /sessions/{id}/world-archives` / `GET /sessions/{id}/asks` / `POST /sessions/{id}/asks/{ask_id}`
- 设计要求：world-archives 列表；asks 列出 pending；按 `ask_id` resolve（设计 §4 已注明采用 ask_id 模式）。
- 实现状态：完整
- 证据：`sessions.py:1102`（world-archives）、`:812`（asks 列表）、`:818`（resolve_ask，decision ∈ allow/deny，`:821-826`）。
- 差距：无（ask_id 模式设计已声明对齐）。
- 处置：无需动作。

---

## 5. 章节管理

### §5 `GET /sessions/{id}/chapters` / `consolidate` / `{chap_id}/rollback`
- 设计要求：章节嵌套树（children 递归、message_range）；consolidate 触发归档返回 `hooks_registered/memory_entries_added`；rollback 支持 `create_branch`。
- 实现状态：完整
- 证据：`sessions.py:831-865`（树构建，`message_range{from,to}`）、`:889`（consolidate）、`:929`（rollback）。
- 差距：`get_chapters` 节点缺设计示例的 `created_at` 顶层一致性（实现含）；未抽查 consolidate 响应字段全等。
- 处置：无需动作。

---

## 6. 引擎接口

### §6 `POST /engine/roll`
- 设计要求：请求 `{pool, difficulty, reroll_tens, label}`；响应 `{pool, difficulty, successes, outcome, detail, reroll_detail, label, rolled_at}`。
- 实现状态：偏离
- 证据：`engine/dice.py:27-37` `RollRequest` 用 `threshold`（非 `difficulty`）、`reason`（非 `label`），**无 `reroll_tens`**；`:39-53` `DiceRollResult` 用 `rolls`（非 `detail`）、`verdict`（非 `outcome`），**无 `reroll_detail`/`label`/`rolled_at`**；`successes` 字段一致。
- 差距：核心计算一致，但请求/响应字段命名与设计示例系统性不符。
- 处置：补/改设计文档（按 WtA 实际实现的 `threshold/verdict/rolls` 命名重写示例），或代码补别名。

### §6 `GET /engine/skills` / `GET /engine/extensions`
- 设计要求：列出 Skill / 已加载扩展。
- 实现状态：完整
- 证据：`engine.py:191`（skills）、`:198`（extensions）。
- 差距：未抽查响应字段全等。
- 处置：无需动作。

### §6 `POST /mcp/connect` / `DELETE /mcp/{name}`
- 设计要求：动态挂载/断开 MCP；connect 返回 201 + `{name,status,tools,connected_at}`；delete 204。
- 实现状态：完整
- 证据：`config.py:174`（connect）、`:195`（disconnect，路径参数 `server_id`）。
- 差距：DELETE 路径参数名 `server_id`（设计写 `name`），仅命名差异，功能一致。
- 处置：补/改设计文档（统一参数名）或无需动作。

---

## 7. 配置接口

### §7 `GET /config/world-plugins` / `agent-profiles` / `writing-styles` / `PUT /config/llm-routes`
- 设计要求：列出世界插件 / Profile / 文风；更新 LLM 路由。
- 实现状态：完整
- 证据：`config.py:92`（world-plugins）、`:116`（agent-profiles）、`:134`（writing-styles）、`:233`（PUT llm-routes）。
- 差距：未抽查响应字段全等；实现另有 `GET /config/llm-routes`（`:219`）配套读取，设计仅记 PUT。
- 处置：补/改设计文档（补 GET llm-routes）。

---

## 9. 错误码规范
- 设计要求：通用错误码表（`invalid_request`/`session_not_found`/`permission_denied`/`validation_error`/`agent_error`/`llm_unavailable` 等）+ 422 验证错误结构 + 403 权限拒绝结构。
- 实现状态：部分
- 证据：`main.py:329-353` 落地了 `invalid_request/unauthorized/permission_denied/conflict/validation_error/rate_limited/agent_error/llm_unavailable` 及 `session_not_found/message_not_found/chapter_not_found/invalid_mode/invalid_message_type/chapter_already_consolidated/session_processing`。
- 差距：① 422 验证错误 `details` 直接放 `exc.errors()`（FastAPI 原生结构），与设计的 `{errors:[{field,value,hint}]}` 自定义结构不同；② 403 权限拒绝未见统一注入 `{tool,current_mode,permission,hint}` 详情（依赖各端点自填 dict detail，`main.py:361` 透传）；③ 设计无 410/`session_deleted`/`confirm_required`，实现额外引入。
- 处置：补/改设计文档（对齐 422 details 结构、补 410 等码），或补实现统一 403 details。

---

## 反向清单 — 代码有、设计文档（11）未记的端点

设计仅覆盖 28 个；实现路由共约 **103 个**，**超出约 75 个**。其中部分属其他设计文档范畴（全局模板管理），但 11 号文档作为「API 设计规范」未交叉引用，统一标注「需补文档」：

**会话域扩展（sessions.py，设计未记）：**
- `GET /sessions/{id}/chapters/{chap_id}/summary`（:872）
- `GET/PUT /sessions/{id}/writing-styles`（:1059/:1075）
- `POST /sessions/{id}/world-archives`（:1120，设计仅有 GET）
- `GET/POST /sessions/{id}/npcs`、`PATCH/DELETE /sessions/{id}/npcs/{npc_key}`（:1136/:1171/:1196/:1218）
- `GET/POST /sessions/{id}/memory`、`POST .../memory/consolidate`、`.../memory/rollback`（:1228/:1264/:1285/:1296）
- `GET /sessions/{id}/dice-history`（:1330）、`GET /sessions/{id}/stats`（:1351）、`GET /sessions/{id}/replay`（:1416）、`POST /sessions/{id}/compact`（:1487）

**流式域（stream.py）：** `POST /sessions/{id}/opening`（:222）、`DELETE /sessions/{id}/stream`（:291，中止流）

**引擎域（engine.py）：** `POST /engine/combat`（:60）、`GET /engine/economy/{session_id}`（:146）、`GET /engine/rules`（:206）、`POST /engine/rules/{rule_id}/activate`（:216）、`GET /prompts/fragments`（:231）、`GET /agents/profiles`（:240）、`GET /agents/profiles/{profile_name}/check`（:247）、`GET /tools`（:257）、`POST /tools/{tool_name}`（:266）

**配置/系统域（config.py）：** `GET /hooks`（:32）、`GET /system/info`（:42）、`GET /system/memory-health`（:63）、`GET /mcp/servers`（:159）、`GET /config/llm-routes`（:219）、`GET/PUT /config/api-keys`（:267/:281）

**全局模板管理（属其他设计文档，11 号未交叉引用）：**
- `worlds.py` 15 个（`/worlds`、`/worlds/{wid}/archives`、`/worlds/{wid}/fetch-lore`、`/worlds/{wid}/parse-document`、`/worlds/{wid}/confirm-lore`、`/scraper-rules*`）
- `characters.py` 9 个（`/characters*`、`import-png`、`export-png`、`generate*`）
- `assets.py` 10 个（`/assets/npcs*`、`/assets/items*`、`grant`、`import`）
- `prompts.py` 5 个（`/prompts*`、`reset`）

**处置：** 在 `11-api-design.md` 增设「会话扩展接口 / 引擎扩展接口 / 全局模板接口」章节或交叉引用相应设计文档，避免 API 规范文档与实现严重脱节。

---

## 符合度小计

针对**设计文档 11 显式定义的 28 个端点 + 4 项全局约定/错误码**（共 32 个审计项）：

| 状态 | 计数 | 条目 |
|------|------|------|
| 完整 | 24 | 21 个端点 + §1 前缀 + §1.3 错误格式 + §1.4 分页 |
| 部分 | 2 | `POST /mode`（缺 switched_at）、§9 错误码（details 结构/403 详情） |
| 偏离 | 5 | `POST /sessions`、`GET /character`、`PATCH /character`、`POST /engine/roll`、`PATCH /sessions/{id}`(设计未记) |
| 缺失 | 1* | （§9 中的 422 details 自定义结构，归入「部分」；端点层面缺失 0） |

> *端点维度缺失 = **0**。32 审计项中「偏离/部分」均为字段命名或响应包装差异，无功能缺口。

**整体符合度估计：约 88%。**
- 端点覆盖率 100%（28/28 实现）。
- 字段/契约级符合度约 80%（角色 GET/PATCH、engine/roll、create_session、mode、422 details 存在系统性命名/结构偏离）。
- 主要扣分项：① 设计示例与 v4 角色 schema / WtA 骰子字段名脱节；② 约 75 个已实现端点未进入 API 设计文档。

**关键已知项核实结论：**
- `PATCH /sessions/{id}`：**已实现**（`sessions.py:303`），C14「已修复」属实，但需补设计文档。
- `create_session` 返回 `character`：**返回完整角色对象（非设计示例的 null）**，属合理增强，建议改文档对齐。
