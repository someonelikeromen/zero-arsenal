# C6 · API 路由层代码缺陷复审

> 复审基准日期：2026-06-03
> 范围：`backend/api/routers/{sessions,worlds,characters,stream,engine,config,prompts,assets}.py` + `backend/api/routes.py`
> 列名核对依据：`backend/db/schema.py`、`backend/db/connection.py`（`row_factory = aiosqlite.Row`）
> 维度 A 格式，行级证据，只读复审。

---

## 一、旧报告条目逐条判定

### STUB-R01 · fork_session 插入 NPC 列名
- 状态：✅已修复
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/api/routers/sessions.py:529-536`
- 证据：INSERT 列已是 `(id, session_id, key, name, profile_json, world_key, created_at, updated_at)`，与 `schema.py:180-189` 的 `npc_profiles.key` 列一致；不再使用旧报告所称的 `npc_key`。
- 修复方向：已修复。但同一段存在新的 `.get()` 调用崩溃（见 NEW-C6-01），需另行处理。

### STUB-R02 · ChapterRollbackRequest.create_branch 未用 / new_branch_id 恒 None
- 状态：🔄已变化
- 类别：unwired
- 严重度：🔴核心
- 位置：`backend/api/routers/sessions.py:1007-1045`
- 证据：`if req.create_branch:` 现已接线（创建分支会话+复制角色卡+建初始章节），`new_branch_id` 不再恒 None；但分支 INSERT 的列名 `current_mode`/`forked_from`（1020-1021）在 `sessions` 表中不存在（schema 为 `mode`/`branch_of`），会触发 SQL 错误（见 NEW-C6-02）。
- 修复方向：把 INSERT 列名改为 `mode`/`branch_of`，否则 create_branch=true 必失败。

### STUB-T02 · PATCH /sessions/{id} 重命名端点
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/api/routers/sessions.py:303-322`
- 证据：`@router.patch("/sessions/{session_id}")` 已实现，`PatchSessionRequest.title`（39-40）可更新 `sessions.title` 并发布 `session.updated` 事件，满足前端 SessionManager 重命名需求。
- 修复方向：无需动作。

### R-D02 · characters.py LLM 解析失败 → questions=[] / create_default_character()
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/characters.py:306-311`、`340-347`
- 证据：`generate_questions` 解析失败时 `questions = []` 静默返回（无 error 事件）；`generate_character` 失败时回落 `create_default_character(...)`，前端无法区分"成功生成"与"兜底默认卡"。
- 修复方向：解析失败时额外推送 `{type:'error'}` 或在 done 事件加 `fallback:true` 标记。

### R-D03 · engine.py rules_loader 缺失返回空列表
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/api/routers/engine.py:206-213`
- 证据：`list_extension_rules` 捕获 `ImportError` 返回 `{"rules": [], "count": 0, "note": "rules_loader not initialized"}`，调用方无法判定是"无规则"还是"模块缺失"。（`activate_rule` 217-226 已改为 503，相对合理。）
- 修复方向：保留 note 即可；如需更明确可改为返回 503 + degraded 标记。

### R-D04 · sessions.py on_session_init / overlay / active_tools 失败 except pass
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/sessions.py:182-183`、`371-372`、`385-386`
- 证据：`create_session` 的 `on_session_init` 块整体 `except Exception: pass`（182-183）；`change_mode` 的 overlay 应用 `except Exception: pass`（371-372），active_tools 计算 `except Exception: pass`（385-386）——插件/权限错误全部被吞，active_tools 可能静默退化为 `[]`。
- 修复方向：至少 `logger.warning` 记录；overlay/active_tools 失败应在响应里带 `degraded` 提示。

### R-D05 · create_session 响应 character 恒 None
- 状态：✅已修复
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/sessions.py:187-203`
- 证据：响应前重新查询 `character_cards` 取 `data_json` 反序列化为 `character_out`，并在响应体 `"character": character_out`（203）返回真实角色卡，不再是 None。
- 修复方向：无需动作。

### R-D06 · 章节回滚 memory_rollback 失败 pass
- 状态：✅已修复
- 类别：degradation
- 严重度：🔴核心
- 位置：`backend/api/routers/sessions.py:999-1005`
- 证据：`memory_rollback.rollback_chapter` 失败时已改为 `logger.error(...)` + `raise HTTPException(500, ...)` fail-loud，不再静默 pass。
- 修复方向：无需动作。注意角色快照恢复仍是静默 pass（见 NEW-C6-04）。

### R-D07 · stream.py 管线各阶段异常 pass 吞掉
- 状态：🔄已变化
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/stream.py:104-105`、`118-119`、`150-151`、`169-174`、`185-186`、`213-214`
- 证据：核心 graph 异常已发布 `SESSION_ERROR`（169-174，前端可见）；但 `on_turn_start`/`on_turn_end`/`before_turn`/`after_turn` hook 及角色加载失败仅 `logger.warning` 后继续（不再裸 pass，但仍对用户不可见）。
- 修复方向：插件/hook 失败可通过 SSE 推送 degraded 提示，避免静默状态漂移。

### R-D08 · worlds.py LLM 提炼失败 entries=[]
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/worlds.py:93-100`
- 证据：`_extract_lore_sse` JSON 解析失败时 `entries = []`，仍推送 `{type:'done', entries:[]}`（100），前端会显示"提炼完成 0 条"而非失败。（LLM 调用本身异常走 101-102 的 error 事件，相对合理。）
- 修复方向：解析失败时改推 `{type:'error'}` 或 done 事件附 `parse_failed:true`。

### R-M02 · config.py has_lifecycle_hooks 恒 True
- 状态：✅已修复
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/api/routers/config.py:105-111`
- 证据：改为动态检测 `type(plug).__dict__[m] is not _BasePlugin.__dict__.get(m)`，仅当插件类真正覆写 `on_session_init/on_turn_start/on_turn_end` 时才为 True，不再硬编码。
- 修复方向：无需动作（细节：仅查直接类 `__dict__`，多层继承覆写会漏判，可选优化）。

---

## 二、新增发现

### NEW-C6-01 · fork_session 对 aiosqlite.Row 调用 .get() 必崩溃
- 状态：🆕新发现
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/api/routers/sessions.py:483-484`、`489`、`534-535`
- 证据：`p.get("type",...)`/`p.get("content",...)`/`p.get("agent",...)` 与 `npc.get("name",...)`/`npc.get("world_key","")` 作用于 `aiosqlite.Row`（`connection.py:24`），而 `sqlite3.Row` 无 `.get` 方法 → `AttributeError`；只要被 fork 会话有任意 message_parts 或 npc_profiles，fork 即崩溃。
- 修复方向：改用下标访问（`p["type"]`）或 `dict(p).get(...)`。

### NEW-C6-02 · rollback create_branch 分支 INSERT 列名不存在
- 状态：🆕新发现
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/api/routers/sessions.py:1019-1026`
- 证据：INSERT 写入 `current_mode` 与 `forked_from`，但 `sessions` 表（schema.py:12-27）实际列为 `mode` 与 `branch_of`，且无 `current_mode`/`forked_from` → `OperationalError: no such column`；此 INSERT 未被 try 包裹，会在已完成回滚后抛 500。
- 修复方向：列名改为 `mode`/`branch_of`（并补 `branch_label`/`fork_from_msg` 如需）。

### NEW-C6-03 · fork_session 复制消息时丢失 messages.content / message_type
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/sessions.py:471-476`
- 证据：复制 messages 仅写 `(id, session_id, role, turn_index, status, created_at, updated_at)`，未复制 `content`/`message_type`/`phase`（schema.py:354-355 / 38）；fork 后用户消息文本丢失，`get_messages` 读 `m.content`（585行附近）将返回空。
- 修复方向：INSERT 增加 `content, message_type, phase` 列并从源 Row 拷贝。

### NEW-C6-04 · 章节回滚角色快照恢复失败静默 pass
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/api/routers/sessions.py:966-989`
- 证据：角色快照恢复整段 `try ... except Exception: pass`（988-989）；与同函数已 fail-loud 的 memory_rollback（999-1005）不一致——快照恢复失败会导致角色状态未回滚却仍返回成功（`character_state_restored` 依赖 snap 是否查到，而非 UPDATE 是否成功）。
- 修复方向：捕获后 `logger.warning` 并在响应中反映恢复失败，或一并 fail-loud。

### NEW-C6-05 · create_world_archive 把 world_key 误写为 archive_type
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟢次要
- 位置：`backend/api/routers/sessions.py:1126-1131`
- 证据：INSERT 列 `(..., trigger_keywords, world_key, ...)` 对应值传入 `req.trigger_keywords, req.archive_type`（1130），即 `world_key` 被赋成 archive_type（如 "lore"），使所有同类型档案共享同一 world_key，语义错误。
- 修复方向：world_key 应留空或单独入参，而非复用 archive_type。

---

## 三、小计

| 维度 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 5 | STUB-R01, STUB-T02, R-D05, R-D06, R-M02 |
| ⚠️仍存在 | 4 | R-D02, R-D03, R-D04, R-D08 |
| 🔄已变化 | 2 | STUB-R02, R-D07 |
| 🆕新发现 | 5 | NEW-C6-01 ~ NEW-C6-05 |

**核心结论**：旧报告 11 条中 5 条已修复、2 条改善但引入新缺陷、4 条降级仍在。新发现 5 条，其中 2 条 🔴 核心（fork 的 `.get()` 崩溃、rollback 分支 INSERT 列名错误）会直接导致接口运行时报错。
