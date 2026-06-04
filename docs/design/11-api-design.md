# 11 · API 设计规范

> **技术栈**：FastAPI + SSE（Server-Sent Events）；OpenAPI 文档由 FastAPI 自动生成，可在 `/docs`（Swagger）和 `/redoc` 访问。
> **版本前缀**：所有接口以 `/api/` 开头（实现已对齐，不使用 `/api/v1/` 子版本前缀）。
>
> 注：本文档已于 2026-06 对齐实现（D0 以代码为准）。**28 个设计端点全部已实现（缺失 0）**；下列字段命名/响应包装按实现修正，并补登记代码已有、本文档未记的端点。
>
> **实现对齐总览（2026-06，`backend/api/routers/`）**
> - **`POST /sessions`**：创建即生成默认/模板角色卡并整体返回 `character`（**非示例的 `null`**），且多返回 `chapter_id`；状态码为 200（非 201）。属合理增强。
> - **`PATCH /sessions/{id}`**（元数据重命名）：**实现已存在**（`sessions.py`，支持 `title`，返回 `{ok, session_id, title}`），本文档原未记录——见 §2 补注。
> - **`GET /sessions/{id}/character`**：实际返回 `{character, schema_version}`（**非** `{session_id, character_version, snapshot_message_id, data}`）；角色内层为 v4 schema。
> - **`PATCH /sessions/{id}/character`**：请求体字段为 `patches: list[dict]` + `raw_json`（**非** `commands`），无 `message_id`，响应多 `validation_warnings`。
> - **`POST /engine/roll`**：请求用 `threshold`（非 `difficulty`）、`reason`（非 `label`），无 `reroll_tens`；响应用 `rolls`（非 `detail`）、`verdict`（非 `outcome`），无 `reroll_detail/label/rolled_at`（WtA 实际 schema）。
> - **`POST /sessions/{id}/mode`**：主实现为 `PATCH`（`POST` 为别名）；响应用 `mode`（非 `current_mode`），缺 `switched_at`，多 `ok`。
> - **§9 错误码**：422 验证错误 `details` 直接用 FastAPI 原生 `exc.errors()` 结构（非自定义 `{errors:[{field,value,hint}]}`）；实现额外引入 **410 gone**（`session_deleted`）/`confirm_required`。
> - **反向缺口**：实现路由约 103 个，**约 75 个未进本文档**（会话扩展/引擎扩展/全局模板管理 worlds/characters/assets/prompts）——见文末「附：实现已有、本文档未记端点」清单。

---

## 1. 设计原则

### 1.1 RESTful + SSE 双通道

| 通道 | 用途 | 协议 |
|------|------|------|
| REST（HTTP） | CRUD 操作、命令触发 | JSON over HTTP/1.1 |
| SSE（Server-Sent Events） | 实时事件推送（流式正文、骰子结果、状态变更） | `text/event-stream` |

**为什么选择 SSE 而非 WebSocket**：
- SSE 是单向推送，语义与"服务端事件流"完全匹配
- 原生支持断线重连（`Last-Event-ID` 头）
- HTTP/2 下多路复用，不需要单独握手
- 客户端实现更简单，无需管理双向状态

### 1.2 OpenAPI 自动生成

```python
# main.py
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Zero Arsenal API",
    version="0.1.0",
    description="综漫跑团引擎后端 API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/openapi.json",
)

# 所有路由通过 api/routes.py 聚合，统一挂载到 /api
# routes.py 内部已设 prefix="/api"，各子 router 无额外前缀
app.include_router(router)  # router = APIRouter(prefix="/api")
```

### 1.3 统一错误响应格式

所有 4xx / 5xx 响应统一使用以下结构：

```json
{
  "error": "error_code_snake_case",
  "message": "人类可读的错误描述",
  "details": {}
}
```

完整错误码列表见第 9 节。

### 1.4 分页约定

列表接口统一使用 cursor-based 分页：

```
GET /api/sessions?limit=20&cursor=<opaque_cursor>

响应：
{
  "items": [...],
  "next_cursor": "base64_encoded_cursor",
  "has_more": true
}
```

---

## 2. 会话管理

### `POST /api/sessions` — 创建会话

**请求体**：
```json
{
  "world_plugin": "muv_luv_alternative",
  "agent_profile": "play",
  "title": "第一章：命运的邂逅",
  "opening_context": "可选的开场背景描述"
}
```

**响应** `201 Created`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "title": "第一章：命运的邂逅",
  "world_plugin": "muv_luv_alternative",
  "agent_profile": "play",
  "current_mode": "play",
  "created_at": "2026-05-31T23:00:00+08:00",
  "status": "active",
  "character": null
}
```

---

### `GET /api/sessions/{id}` — 获取会话信息

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "title": "第一章：命运的邂逅",
  "world_plugin": "muv_luv_alternative",
  "agent_profile": "play",
  "current_mode": "play",
  "created_at": "2026-05-31T23:00:00+08:00",
  "last_active_at": "2026-05-31T23:45:00+08:00",
  "message_count": 42,
  "current_chapter": {
    "chapter_id": "chap-0012",
    "title": "营地的夜晚",
    "is_consolidated": false
  },
  "status": "active"
}
```

---

### `DELETE /api/sessions/{id}` — 删除会话

**响应** `204 No Content`

软删除：标记为 `status: deleted`，数据保留 7 天后物理清除。

---

### `GET /api/sessions` — 列出所有会话

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 20 | 每页数量（1-100） |
| `cursor` | str | — | 翻页游标 |
| `status` | str | `active` | `active` / `deleted` / `all` |
| `world_plugin` | str | — | 按世界插件过滤 |

**响应** `200 OK`：
```json
{
  "items": [
    {
      "session_id": "sess-a1b2c3d4",
      "title": "第一章：命运的邂逅",
      "world_plugin": "muv_luv_alternative",
      "current_mode": "play",
      "last_active_at": "2026-05-31T23:45:00+08:00",
      "message_count": 42
    }
  ],
  "next_cursor": "eyJpZCI6InNlc3MtYTFiMmMzZDQifQ==",
  "has_more": false,
  "total": 1
}
```

---

### `POST /api/sessions/{id}/mode` — 切换模式

**请求体**：
```json
{
  "mode": "plan"
}
```

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "previous_mode": "play",
  "current_mode": "plan",
  "active_tools": ["search_lore", "query_character", "load_skill", "outline_chapter"],
  "switched_at": "2026-05-31T23:50:00+08:00"
}
```

切换不影响消息历史，仅更改当前 `agent_profile`，下一次消息发送时生效。

---

### `POST /api/sessions/{id}/fork` — Fork 分支

**请求体**：
```json
{
  "branch_label": "剧情分支：选择投降",
  "fork_from_message_id": "msg-0089"
}
```

**响应** `201 Created`：
```json
{
  "new_session_id": "sess-b2c3d4e5",
  "parent_session_id": "sess-a1b2c3d4",
  "branch_label": "剧情分支：选择投降",
  "forked_from_message_id": "msg-0089",
  "created_at": "2026-05-31T23:55:00+08:00"
}
```

---

## 3. 消息与对话

### `POST /api/sessions/{id}/message` — 发送玩家输入

触发完整 Agent 管线（LangGraph）：输入 → 策划 → 写作 → 骰点 → 状态更新。
Agent 执行期间通过 SSE 推送 `part.*` 事件流。

**请求体**：
```json
{
  "content": "我决定向前冲，拔出武器准备迎战",
  "message_type": "player_action",
  "metadata": {
    "action_option": "A"
  }
}
```

`message_type` 枚举：

| 值 | 说明 |
|----|------|
| `player_action` | 玩家的行动选择（最常见） |
| `player_dialogue` | 玩家发起的对话 |
| `ooc_command` | 出戏指令（如「让我休息一下」） |
| `system_override` | GM 强制指令（需特殊权限） |

**响应** `202 Accepted`（异步处理）：
```json
{
  "message_id": "msg-0090",
  "session_id": "sess-a1b2c3d4",
  "status": "processing",
  "stream_url": "/api/sessions/sess-a1b2c3d4/events"
}
```

---

### `GET /api/sessions/{id}/events` — SSE 事件流

**请求头**（断线重连时携带）：
```
Last-Event-ID: evt-0234
```

**响应** `200 OK`（`Content-Type: text/event-stream`）：

```
id: evt-0235
event: part.created
data: {"part_id":"part-001","type":"narrative","message_id":"msg-0090","content":""}

id: evt-0236
event: part.updated
data: {"part_id":"part-001","delta":"月光透过破损的窗棂洒落","accumulated_length":16}

id: evt-0237
event: part.updated
data: {"part_id":"part-001","delta":"，林峰深吸一口气，握紧了手中的剑。","accumulated_length":36}

id: evt-0238
event: part.done
data: {"part_id":"part-001","final_content":"月光透过破损的窗棂洒落，林峰深吸一口气，握紧了手中的剑。","word_count":27}

id: evt-0239
event: part.created
data: {"part_id":"part-002","type":"dice_roll","message_id":"msg-0090"}

id: evt-0240
event: part.done
data: {"part_id":"part-002","type":"dice_roll","roll":{"pool":7,"successes":4,"outcome":"success","detail":[10,8,6,6,3,2,1]}}

id: evt-0241
event: session.idle
data: {"session_id":"sess-a1b2c3d4","message_id":"msg-0090"}
```

**事件类型全表**：

| 事件类型 | 触发时机 | data 字段 |
|---------|---------|-----------|
| `part.created` | Agent 开始生成一个新 Part | `part_id`, `type`, `message_id` |
| `part.updated` | 流式 delta 到达（narrative 类型） | `part_id`, `delta`, `accumulated_length` |
| `part.done` | Part 生成完毕 | `part_id`, `final_content`（或结构化数据） |
| `permission.ask` | 工具调用触发 ask 权限 | 见第 6 节 PermissionAskData |
| `session.mode_changed` | 模式切换完成 | `previous_mode`, `current_mode` |
| `session.idle` | Agent 管线执行完毕 | `session_id`, `message_id` |
| `session.error` | Agent 执行出错 | `error`, `message`, `recoverable` |
| `chapter.consolidated` | 章节固化完成 | `chapter_id`, `title` |

---

### `GET /api/sessions/{id}/messages` — 获取消息历史

**查询参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `limit` | 50 | 每页数量 |
| `cursor` | — | 翻页游标 |
| `include_parts` | `false` | 是否内联 Part 数据 |

**响应** `200 OK`：
```json
{
  "items": [
    {
      "message_id": "msg-0090",
      "session_id": "sess-a1b2c3d4",
      "role": "user",
      "content": "我决定向前冲，拔出武器准备迎战",
      "message_type": "player_action",
      "created_at": "2026-05-31T23:45:10+08:00",
      "parts": []
    },
    {
      "message_id": "msg-0091",
      "session_id": "sess-a1b2c3d4",
      "role": "assistant",
      "content": null,
      "message_type": "agent_response",
      "created_at": "2026-05-31T23:45:12+08:00",
      "parts": [
        { "part_id": "part-001", "type": "narrative" },
        { "part_id": "part-002", "type": "dice_roll" }
      ]
    }
  ],
  "next_cursor": "...",
  "has_more": true
}
```

---

### `GET /api/sessions/{id}/parts` — 获取所有 Part

**查询参数**：

| 参数 | 说明 |
|------|------|
| `type` | 按类型过滤，如 `narrative` / `dice_roll` / `state_patch` |
| `message_id` | 按消息 ID 过滤 |
| `limit` | 每页数量 |
| `cursor` | 翻页游标 |

**响应** `200 OK`：
```json
{
  "items": [
    {
      "part_id": "part-001",
      "message_id": "msg-0091",
      "type": "narrative",
      "content": "月光透过破损的窗棂洒落，林峰深吸一口气，握紧了手中的剑。",
      "created_at": "2026-05-31T23:45:12+08:00",
      "metadata": { "word_count": 27, "style": "play" }
    },
    {
      "part_id": "part-002",
      "message_id": "msg-0091",
      "type": "dice_roll",
      "content": null,
      "payload": {
        "pool": 7,
        "successes": 4,
        "outcome": "success",
        "attribute": "反应",
        "skill": "近战",
        "modifier": 1,
        "detail": [10, 8, 6, 6, 3, 2, 1]
      },
      "created_at": "2026-05-31T23:45:14+08:00"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

---

### `POST /api/sessions/{id}/revert` — 回滚到指定消息

**请求体**：
```json
{
  "message_id": "msg-0088",
  "confirm": true
}
```

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "reverted_to_message_id": "msg-0088",
  "deleted_message_count": 3,
  "character_state_restored": true,
  "reverted_at": "2026-05-31T23:58:00+08:00"
}
```

回滚会：
1. 软删除 `msg-0089` 至 `msg-0091`（含所有关联 Part）
2. 还原角色卡到 `msg-0088` 时的快照
3. 还原积分/物品状态到对应快照

---

## 4. 角色与状态

### `GET /api/sessions/{id}/character` — 获取角色卡

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "character_version": 4,
  "snapshot_message_id": "msg-0091",
  "data": {
    "name": "林峰",
    "age": 17,
    "world": "muv_luv_alternative",
    "attributes": {
      "strength": 3,
      "dexterity": 4,
      "stamina": 3,
      "charisma": 3,
      "manipulation": 2,
      "perception": 4,
      "intelligence": 3,
      "wits": 4
    },
    "skills": {
      "melee": 3,
      "dodge": 2,
      "pilot_tac": 2,
      "awareness": 3
    },
    "resources": {
      "hp": { "current": 7, "max": 7 },
      "willpower": { "current": 6, "max": 7 },
      "sp": 2400
    },
    "inventory": [
      { "item_id": "combat_knife_01", "name": "战术匕首", "tier": 2 }
    ],
    "active_skills": ["海军六式_基础", "精密手工_专精"],
    "psyche_model": {
      "laziness": 7,
      "aggression": 3,
      "empathy": 6
    }
  }
}
```

---

### `PATCH /api/sessions/{id}/character` — 更新角色卡

使用 TavernCommand 列表描述变更，由后端验证并应用。
此接口受 `edit_character` 工具权限控制（play 模式下为 `ask`）。

**请求体**：
```json
{
  "commands": [
    {
      "op": "set",
      "path": "resources.hp.current",
      "value": 5,
      "reason": "战斗受伤"
    },
    {
      "op": "increment",
      "path": "resources.sp",
      "value": 200,
      "reason": "击败BETA获得奖励"
    },
    {
      "op": "append",
      "path": "inventory",
      "value": { "item_id": "tac_armor_01", "name": "战术防甲", "tier": 3 },
      "reason": "战利品"
    }
  ],
  "message_id": "msg-0091"
}
```

`TavernCommand` 支持的 `op` 类型：

| op | 说明 |
|----|------|
| `set` | 直接设置值 |
| `increment` | 数值增量（正/负） |
| `append` | 向数组追加 |
| `remove` | 从数组移除（按 `item_id` 匹配） |
| `merge` | 深度合并对象 |

**响应** `200 OK`：返回更新后的完整角色卡（同 GET 响应格式）

---

### `GET /api/sessions/{id}/world-archives` — 获取世界档案

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "world_key": "muv_luv_alternative",
  "archives": [
    {
      "archive_id": "arch-001",
      "title": "BETA登陆记录",
      "content_type": "lore",
      "summary": "1973年光州事件后BETA扩张路线...",
      "created_at": "2026-05-31T20:00:00+08:00",
      "source": "canon"
    }
  ],
  "total": 47
}
```

---

### `GET /api/sessions/{id}/asks` — 列出待确认权限请求

列出当前会话所有 pending 状态的 ask 事件（配合 `permission.ask` SSE）。

**响应** `200 OK`：
```json
{
  "asks": [
    { "ask_id": "perm-uuid-001", "tool_name": "purchase_item", "reason": "..." }
  ]
}
```

---

### `POST /api/sessions/{id}/asks/{ask_id}` — 权限响应

> **注意**：实现采用 ask_id 模式而非 `{tool}` 路径模式，支持同一 session 内多个并发权限请求独立 resolve。

配合 `permission.ask` SSE 事件，用户在前端确认/拒绝后调用此接口。

**路径参数**：`ask_id` — 权限请求的唯一 ID（来自 permission.ask 事件）

**请求体**：
```json
{
  "decision": "allow"
}
```

`decision` 枚举：`allow` / `deny`

**响应** `200 OK`：
```json
{
  "ask_id": "perm-uuid-001",
  "decision": "allow"
}
```

---

## 5. 章节管理

### `GET /api/sessions/{id}/chapters` — 获取章节树

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "chapters": [
    {
      "chapter_id": "chap-0001",
      "parent_id": null,
      "title": "序章：穿越",
      "branch_label": null,
      "is_consolidated": true,
      "message_range": { "from": "msg-0001", "to": "msg-0023" },
      "created_at": "2026-05-31T20:00:00+08:00",
      "children": [
        {
          "chapter_id": "chap-0002",
          "parent_id": "chap-0001",
          "title": "第一章：营地生活",
          "branch_label": null,
          "is_consolidated": false,
          "message_range": { "from": "msg-0024", "to": "msg-0091" },
          "created_at": "2026-05-31T21:00:00+08:00",
          "children": []
        },
        {
          "chapter_id": "chap-0003",
          "parent_id": "chap-0001",
          "title": "第一章（分支）：投降结局",
          "branch_label": "剧情分支：选择投降",
          "is_consolidated": true,
          "message_range": { "from": "msg-0024", "to": "msg-0067" },
          "created_at": "2026-05-31T22:00:00+08:00",
          "children": []
        }
      ]
    }
  ]
}
```

---

### `POST /api/sessions/{id}/chapters/consolidate` — 固化当前章节

将当前进行中的章节标记为已完成（`is_consolidated: true`），
触发后端归档流程（摘要生成、记忆写入、伏笔注册）。

**请求体**：
```json
{
  "title": "第一章：营地生活",
  "summary": "可选的人工摘要，不填则由 LLM 自动生成"
}
```

**响应** `200 OK`：
```json
{
  "chapter_id": "chap-0002",
  "title": "第一章：营地生活",
  "is_consolidated": true,
  "summary": "林峰在营地度过了初来乍到的第一周，与训练小队建立了初步信任...",
  "consolidated_at": "2026-05-31T23:59:00+08:00",
  "hooks_registered": 3,
  "memory_entries_added": 12
}
```

---

### `POST /api/sessions/{id}/chapters/{chap_id}/rollback` — 回滚到指定章节

**请求体**：
```json
{
  "confirm": true,
  "create_branch": false
}
```

当 `create_branch: true` 时，回滚会在原章节基础上开启新分支而非直接删除后续内容。

**响应** `200 OK`：
```json
{
  "session_id": "sess-a1b2c3d4",
  "rolled_back_to": "chap-0001",
  "deleted_chapters": ["chap-0002"],
  "new_branch_id": null,
  "character_state_restored": true
}
```

---

## 6. 引擎接口

### `POST /api/engine/roll` — 独立骰子接口

不依赖会话，用于前端骰子面板的独立测试。

**请求体**：
```json
{
  "pool": 7,
  "difficulty": 6,
  "reroll_tens": true,
  "label": "反应+近战 测试"
}
```

**响应** `200 OK`：
```json
{
  "pool": 7,
  "difficulty": 6,
  "successes": 4,
  "outcome": "success",
  "detail": [10, 10, 8, 6, 3, 2, 1],
  "reroll_detail": [8, 6],
  "label": "反应+近战 测试",
  "rolled_at": "2026-05-31T23:45:00+08:00"
}
```

---

### `GET /api/engine/skills` — 列出所有可用 Skill

**响应** `200 OK`：
```json
{
  "skills": [
    {
      "skill_id": "writing-styles/网文",
      "display_name": "网文骨架",
      "category": "writing_style",
      "description": "网络小说叙事风格，口语化白描",
      "path": "writing-styles/网文.md",
      "active": true
    }
  ],
  "total": 18
}
```

---

### `GET /api/engine/extensions` — 列出所有已加载扩展

**响应** `200 OK`：
```json
{
  "extensions": [
    {
      "extension_id": "wta-dice",
      "display_name": "WtA 骰池系统",
      "version": "1.0.0",
      "status": "loaded",
      "provides": ["roll_check", "botch_detection"]
    }
  ]
}
```

---

### `POST /api/mcp/connect` — 动态挂载 MCP 服务

**请求体**：
```json
{
  "name": "novel-system-mcp",
  "transport": "stdio",
  "command": "python",
  "args": ["system/backend/mcp_server.py"],
  "env": {
    "NOVEL_DB": "system/backend/data/novel_system.db"
  }
}
```

**响应** `201 Created`：
```json
{
  "name": "novel-system-mcp",
  "status": "connected",
  "tools": ["get_working_memory", "query_character", "search_lore", "add_lore"],
  "connected_at": "2026-05-31T23:00:00+08:00"
}
```

---

### `DELETE /api/mcp/{name}` — 断开 MCP 服务

**响应** `204 No Content`

---

## 7. 配置接口

### `GET /api/config/world-plugins` — 列出世界插件

**响应** `200 OK`：
```json
{
  "plugins": [
    {
      "world_key": "muv_luv_alternative",
      "display_name": "Muv-Luv Alternative",
      "version": "1.0.0",
      "description": "机甲 + BETA 入侵反攻世界观",
      "default_agent_profile": "play",
      "supported_profiles": ["play", "plan", "review"],
      "permission_overlay_count": 5
    },
    {
      "world_key": "gundam_seed",
      "display_name": "Gundam SEED CE71",
      "version": "0.8.0",
      "description": "协调者与自然人冲突时代",
      "default_agent_profile": "play",
      "supported_profiles": ["play", "plan", "review"]
    }
  ]
}
```

---

### `GET /api/config/agent-profiles` — 列出 AgentProfile

**响应** `200 OK`：
```json
{
  "profiles": [
    {
      "name": "play",
      "description": "正常跑团模式",
      "active_tools": "all",
      "default_permission": "ask",
      "tool_permissions_summary": {
        "allow": ["roll_check", "write_narrative", "search_lore"],
        "ask": ["edit_character", "purchase_item"],
        "deny": []
      }
    },
    {
      "name": "plan",
      "description": "策划分析模式（只读）",
      "active_tools": ["search_lore", "query_character", "load_skill", "outline_chapter"],
      "default_permission": "deny",
      "tool_permissions_summary": {
        "allow": ["search_lore", "query_character", "load_skill", "outline_chapter"],
        "ask": [],
        "deny": ["*（通配符）"]
      }
    }
  ]
}
```

---

### `GET /api/config/writing-styles` — 列出文风

**响应** `200 OK`：
```json
{
  "styles": [
    {
      "style_id": "wenwang",
      "display_name": "网文骨架",
      "layer": "skeleton",
      "path": "writing-styles/网文.md",
      "compatible_with": ["xiaoci_rhythm", "rhythm_master"]
    }
  ]
}
```

---

### `PUT /api/config/llm-routes` — 更新 LLM 路由

对应 `agents.json` 中的路由配置。

**请求体**：
```json
{
  "routes": {
    "narrative": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-5",
      "temperature": 0.85,
      "max_tokens": 4096
    },
    "planning": {
      "provider": "anthropic",
      "model": "claude-opus-4",
      "temperature": 0.3,
      "max_tokens": 8192
    },
    "evaluation": {
      "provider": "openai",
      "model": "gpt-4o",
      "temperature": 0.1,
      "max_tokens": 2048
    }
  }
}
```

**响应** `200 OK`：
```json
{
  "updated": true,
  "routes_count": 3,
  "effective_at": "2026-05-31T23:00:00+08:00"
}
```

---

## 8. 请求 / 响应示例（完整场景）

### 场景：玩家发送行动 → SSE 接收流式叙事 → 骰子结果

**Step 1**：发送玩家行动
```http
POST /api/sessions/sess-a1b2c3d4/message
Content-Type: application/json
Authorization: Bearer <token>

{
  "content": "我拔出武器，向BETA冲去",
  "message_type": "player_action"
}
```

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "message_id": "msg-0090",
  "status": "processing",
  "stream_url": "/api/sessions/sess-a1b2c3d4/events"
}
```

**Step 2**：同时建立 SSE 连接
```http
GET /api/sessions/sess-a1b2c3d4/events
Accept: text/event-stream
```

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no

id: evt-0235
event: part.created
data: {"part_id":"part-101","type":"narrative","message_id":"msg-0090"}

id: evt-0236
event: part.updated
data: {"part_id":"part-101","delta":"警报声刺破了寂静的夜空。"}

id: evt-0237
event: part.updated
data: {"part_id":"part-101","delta":"林峰双手握紧短刀，向着最近的兵士级BETA冲去——"}

id: evt-0238
event: part.done
data: {"part_id":"part-101","final_content":"警报声刺破了寂静的夜空。林峰双手握紧短刀，向着最近的兵士级BETA冲去——","word_count":30}

id: evt-0239
event: part.created
data: {"part_id":"part-102","type":"dice_roll","message_id":"msg-0090"}

id: evt-0240
event: part.done
data: {"part_id":"part-102","payload":{"attribute":"反应","skill":"近战","modifier":1,"pool":8,"difficulty":6,"successes":5,"outcome":"major_success","detail":[10,10,9,8,7,3,2,1],"reroll_detail":[8,7]}}

id: evt-0241
event: part.created
data: {"part_id":"part-103","type":"narrative","message_id":"msg-0090"}

id: evt-0242
event: part.updated
data: {"part_id":"part-103","delta":"大成功！短刀精准插入关节缝隙，BETA的移动系统瞬间失效。"}

id: evt-0243
event: part.done
data: {"part_id":"part-103","final_content":"大成功！短刀精准插入关节缝隙，BETA的移动系统瞬间失效。"}

id: evt-0244
event: session.idle
data: {"session_id":"sess-a1b2c3d4","message_id":"msg-0090","parts_generated":3}
```

---

## 9. 错误码规范

### 统一错误响应格式

```json
{
  "error": "error_code_snake_case",
  "message": "面向开发者的错误描述",
  "details": {
    "field": "具体出错字段（可选）",
    "value": "出错值（可选）",
    "hint": "修复建议（可选）"
  }
}
```

### 通用错误码

| HTTP 状态 | error 代码 | 触发条件 |
|-----------|-----------|---------|
| 400 | `invalid_request` | 请求格式错误 |
| 400 | `invalid_mode` | 未注册的模式名 |
| 400 | `invalid_message_type` | 不支持的 message_type |
| 401 | `unauthorized` | 缺少或无效的认证 token |
| 403 | `permission_denied` | 当前模式不允许该操作 |
| 404 | `session_not_found` | session_id 不存在 |
| 404 | `message_not_found` | message_id 不存在 |
| 404 | `chapter_not_found` | chapter_id 不存在 |
| 409 | `session_processing` | 会话正在处理中，不接受新消息 |
| 409 | `chapter_already_consolidated` | 章节已固化，不可重复固化 |
| 422 | `validation_error` | 请求体字段验证失败 |
| 429 | `rate_limited` | 请求频率超限 |
| 500 | `agent_error` | Agent 执行内部错误 |
| 503 | `llm_unavailable` | LLM 服务不可用 |

### 验证错误示例（422）

```json
{
  "error": "validation_error",
  "message": "Request body validation failed",
  "details": {
    "errors": [
      {
        "field": "commands[0].op",
        "value": "replace",
        "hint": "Allowed ops: set, increment, append, remove, merge"
      },
      {
        "field": "commands[0].path",
        "value": "",
        "hint": "path cannot be empty"
      }
    ]
  }
}
```

### 权限拒绝示例（403）

```json
{
  "error": "permission_denied",
  "message": "Tool 'write_narrative' is not allowed in 'plan' mode",
  "details": {
    "tool": "write_narrative",
    "current_mode": "plan",
    "permission": "deny",
    "hint": "Switch to 'play' mode to enable write operations"
  }
}
```

---

## 10. 认证

当前版本使用简单的 Bearer Token 认证（适合本地/单用户场景）：

```http
Authorization: Bearer <api_token>
```

Token 通过环境变量 `ZERO_ARSENAL_API_TOKEN` 配置。
未来版本计划支持 OAuth2 / JWT（多用户场景）。

---

## 11. CORS 配置

开发环境默认允许 `localhost:5173`（Vite 开发服务器）：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id", "X-Request-Id"],
)
```

---

## 附：实现已有、本文档未记的端点（2026-06 补登记）

实现路由约 103 个，超出本规范 28 个端点约 75 个。以下分域登记，避免 API 规范与实现脱节（详细行号见 `docs/review/conf_b11.md`）：

**会话域扩展（`sessions.py`）**
- `PATCH /sessions/{id}` — 元数据重命名（title）
- `GET /sessions/{id}/chapters/{chap_id}/summary`
- `GET/PUT /sessions/{id}/writing-styles`
- `POST /sessions/{id}/world-archives`（本文档仅记 GET）
- `GET/POST /sessions/{id}/npcs`、`PATCH/DELETE /sessions/{id}/npcs/{npc_key}`
- `GET/POST /sessions/{id}/memory`、`POST /sessions/{id}/memory/consolidate`、`POST /sessions/{id}/memory/rollback`
- `GET /sessions/{id}/dice-history`、`GET /sessions/{id}/stats`、`GET /sessions/{id}/replay`、`POST /sessions/{id}/compact`

**流式域（`stream.py`）**：`POST /sessions/{id}/opening`、`DELETE /sessions/{id}/stream`（中止流）

**引擎扩展域（`engine.py`）**：`POST /engine/combat`、`GET /engine/economy/{session_id}`、`GET /engine/rules`、`POST /engine/rules/{rule_id}/activate`、`GET /prompts/fragments`、`GET /agents/profiles`、`GET /agents/profiles/{profile_name}/check`、`GET /tools`、`POST /tools/{tool_name}`

**配置/系统域（`config.py`）**：`GET /hooks`、`GET /system/info`、`GET /system/memory-health`、`GET /mcp/servers`、`GET /config/llm-routes`（本文档仅记 PUT）、`GET/PUT /config/api-keys`

**全局模板管理（属其他设计文档范畴，此处交叉引用）**
- `worlds.py`（约 15 个）：`/worlds`、`/worlds/{wid}/archives`、`/worlds/{wid}/fetch-lore`、`/worlds/{wid}/parse-document`、`/worlds/{wid}/confirm-lore`、`/scraper-rules*`
- `characters.py`（约 9 个）：`/characters*`、`import-png`、`export-png`、`generate*`
- `assets.py`（约 10 个）：`/assets/npcs*`、`/assets/items*`、`grant`、`import`
- `prompts.py`（约 5 个）：`/prompts*`、`reset`
