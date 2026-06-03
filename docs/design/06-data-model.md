# 数据模型完整设计文档

**文档版本**：v1.0  
**创建日期**：2026-05-31  
**归属系统**：zero-arsenal / AI-VN 互动叙事引擎  

---

## 目录

1. [Session/Message/Part 三层模型](#1-sessionmessagepart-三层模型)
2. [角色卡 v4 Schema](#2-角色卡-v4-schema)
3. [世界档案 Schema](#3-世界档案-schema)
4. [章节树结构](#4-章节树结构)
5. [记忆表](#5-记忆表)
6. [骰子日志](#6-骰子日志)
7. [系统配置表](#7-系统配置表)
8. [数据迁移策略](#8-数据迁移策略)

---

## 1. Session/Message/Part 三层模型

### 1.1 设计来源

参考 opencode 的 `session/message.ts` 三层结构，将对话历史建模为：

```
Session（会话）
  └── Message（消息）× N
        └── Part（消息片段）× M
```

这一分层设计的核心优势：
- **Part 类型化**：不同类型的内容（叙事/骰子/状态变更）可分别查询和处理
- **流式友好**：Part 有 `status` 字段，支持 streaming 过程中的增量更新
- **可审计**：每个 Part 有独立 ID，可追踪每次骰子、每次状态变更的来源

### 1.2 建表 SQL（aiosqlite 风格）

```sql
-- =====================================================
-- 会话表
-- =====================================================
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    -- 激活的 WorldPlugin 名称（如 wuxia_jianghu / crossover_mla）
    world_plugin    TEXT NOT NULL,
    -- 激活的 AgentProfile（play / plan / review / 自定义）
    agent_profile   TEXT NOT NULL DEFAULT 'play',
    -- 游戏模式：play（交互）/ sandbox（沙盒）/ replay（回放）
    mode            TEXT NOT NULL DEFAULT 'play',
    -- 分支来源（来自 pi JSONL 树的分支概念）
    branch_of       TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    -- 分支标签（NULL = 主线）
    branch_label    TEXT,
    -- 会话标题（由 Chronicler 自动生成或用户设置）
    title           TEXT,
    -- 创建时间（Unix 时间戳，浮点）
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 最后更新时间
    updated_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 会话级持久状态（选定文风、已激活插件、配置项等）
    state_json      TEXT NOT NULL DEFAULT '{}',
    -- 是否已归档
    is_archived     INTEGER NOT NULL DEFAULT 0,
    -- 角色卡 ID（外键到 character_cards 表）
    character_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_world_plugin ON sessions(world_plugin);
CREATE INDEX IF NOT EXISTS idx_sessions_branch_of ON sessions(branch_of);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);


-- =====================================================
-- 消息表
-- =====================================================
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    -- 消息角色：user / assistant / system / tool
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    -- 回合索引（同一回合可有多条消息，如 P1/P3/P4 分开存储）
    turn_index      INTEGER NOT NULL DEFAULT 0,
    -- 执行阶段：p1 / p3 / p4 / meta
    phase           TEXT CHECK(phase IN ('p1', 'p3', 'p4', 'meta')),
    -- 产生该消息的 Agent ID
    agent_id        TEXT,
    -- 消息软删除状态（active=正常，reverted=已回滚软删除）
    -- 注意：流式状态机（streaming/done/error）在 message_parts.status 维护，
    --       messages.status 专门用于回滚/软删除标记
    status          TEXT NOT NULL DEFAULT 'active',
    -- 创建时间
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 完成时间（streaming 完成后更新）
    completed_at    REAL,
    -- 最后更新时间
    updated_at      REAL,
    -- 该消息消耗的 token 数（事后填入）
    tokens_used     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(session_id, role);
CREATE INDEX IF NOT EXISTS idx_messages_phase ON messages(session_id, phase);


-- =====================================================
-- Part 表（消息片段）
-- =====================================================
CREATE TABLE IF NOT EXISTS message_parts (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    -- 冗余 session_id 方便直接查询
    session_id      TEXT NOT NULL,
    -- Part 类型（见下方枚举说明）
    type            TEXT NOT NULL,
    -- 内容（JSON 字符串，结构由 type 决定）
    content         TEXT NOT NULL DEFAULT '{}',
    -- 流式状态
    status          TEXT NOT NULL DEFAULT 'streaming' CHECK(status IN ('streaming', 'done', 'error')),
    -- 在消息内的排序索引
    sort_order      INTEGER NOT NULL DEFAULT 0,
    -- 创建时间
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 额外元数据（JSON，用于扩展字段，不进入主 content 结构）
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_parts_message_id ON message_parts(message_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_parts_session_type ON message_parts(session_id, type);
CREATE INDEX IF NOT EXISTS idx_parts_session_id ON message_parts(session_id, created_at DESC);
```

### 1.3 Part 类型枚举与 Content JSON 结构

每种 Part 类型对应一个固定的 `content` JSON Schema。

```python
# backend/db/schema.py（实际实现，共 17 种）
class PartType:
    # ── 核心类型（原始设计，11 种）────────────────────────────────────
    NARRATIVE       = "narrative"       # 叙事正文（流式）
    DM_NOTE         = "dm_note"         # DM 内部注记（玩家不可见）
    DICE_ROLL       = "dice_roll"       # 骰子请求与结果
    STATE_PATCH     = "state_patch"     # 角色/世界状态变更
    SYSTEM_GRANT    = "system_grant"    # 系统赋予（穿越/奖励/解锁）
    NPC_ACTION      = "npc_action"      # NPC 行为记录
    WORLD_EVENT     = "world_event"     # 世界事件（非角色直接行为）
    SKILL_LOAD      = "skill_load"      # Skill 加载记录
    CHAPTER_END     = "chapter_end"     # 章节结束信号
    PERMISSION_ASK  = "permission_ask"  # 请求玩家确认（敏感操作）
    COMPACTION      = "compaction"      # 上下文压缩摘要

    # ── 实现扩展类型（实现阶段新增，6 种）────────────────────────────
    ACTION_OPTIONS  = "action_options"  # LLM 生成的行动选项（回合结束后）
    REASONING       = "reasoning"       # Agent 推理过程（plan/review 模式可见）
    TEXT            = "text"            # 纯文本 Part（系统提示等）
    TOOL_CALL       = "tool_call"       # 工具调用记录（调用前 emit）
    TOOL_RESULT     = "tool_result"     # 工具返回结果（调用后 emit）
    VAR_DIFF        = "var_diff"        # 变量差分（VarAgent 结算后 emit）
```

#### 各 Part 类型的 Content JSON 结构

**`narrative`** — 叙事正文

```json
{
  "text": "string",              // 叙事正文（Markdown 格式）
  "word_count": 850,             // 字数统计
  "scene_type": "combat",        // daily_grind / combat / emotional / transition / ...
  "writing_styles_used": [       // 实际使用的文风 ID
    "网文",
    "节奏大师"
  ]
}
```

**`dm_note`** — DM 内部注记

```json
{
  "text": "string",              // 注记内容
  "note_type": "planning",       // planning / observation / foreshadow / warning
  "tags": ["combat", "foreshadow"]
}
```

**`dice_roll`** — 骰子请求与结果

```json
{
  "roll_id": "roll_abc123",      // 骰子日志 ID（关联 dice_log 表）
  "pool": 6,                     // 骰池大小
  "difficulty": 3,               // 难度阈值
  "attribute": "DEX",            // 使用的属性/技能
  "modifier": 1,                 // 额外修正
  "dice_values": [1, 3, 4, 6, 6, 2],   // 实际骰子面值
  "successes": 3,                // 成功数
  "verdict": "success",          // success / failure / botch / critical
  "reason": "尝试躲避毒箭"        // 判定原因
}
```

**`state_patch`** — 状态变更

```json
{
  "target": "character",         // character / world / npc:<npc_id>
  "patches": [
    {
      "path": "body_parts.torso.hp_current",
      "op": "delta",             // delta（增量）/ set（覆盖）/ push（追加到列表）
      "value": -15,
      "reason": "被毒箭命中躯干"
    },
    {
      "path": "body_parts.torso.status_effects",
      "op": "push",
      "value": "poisoned",
      "reason": "毒箭附带中毒效果"
    },
    {
      "path": "energy_pools.0.current",
      "op": "delta",
      "value": -20,
      "reason": "施展轻功消耗内力"
    }
  ],
  "applied": false               // 是否已由 Calibrator 实际应用
}
```

**`system_grant`** — 系统赋予

```json
{
  "grant_type": "world_traverse",  // world_traverse / skill_unlock / item_grant / points
  "payload": {
    "world_from": "muv_luv_1998",
    "world_to": "gundam_seed_ce71",
    "character_snapshot": {}       // 穿越时的角色快照
  },
  "triggered_by": "chapter_end",   // 触发来源
  "auto_applied": true
}
```

**`npc_action`** — NPC 行为

```json
{
  "npc_id": "npc_lacus_clyne",
  "npc_name": "拉克丝·克莱因",
  "action_type": "dialogue",       // dialogue / attack / move / item_use
  "content": "她轻声说：'你是协调者？'",
  "intent": "试探主角真实身份",    // DM 的意图标注（玩家不可见）
  "affinity_delta": 5              // 本次行动带来的好感度变化
}
```

**`world_event`** — 世界事件

```json
{
  "event_id": "bloody_valentine_ce70",
  "event_type": "canon",           // canon（原作事件）/ derived（推演事件）
  "title": "血色情人节",
  "description": "联合国核攻击 PLANT，引发 CE70 战争",
  "impact": "大规模战争开始，ZAFT 与联合国进入全面战争状态",
  "time_point": "CE70-02-14",
  "is_background": true            // true = 背景事件，false = 玩家可直接感知
}
```

**`skill_load`** — Skill 加载记录

```json
{
  "skill_id": "combat-narration",
  "skill_version": "1.3.0",
  "loaded_at": 1748706000.0,
  "token_cost": 850,
  "reason": "检测到战斗状态 active=true"
}
```

**`chapter_end`** — 章节结束

```json
{
  "chapter_id": "chap_20260531_001",
  "reason": "主角离开了天权城，本章剧情告一段落",
  "summary_hint": "主角在天权城完成了武器鉴定，获得了铁匠铺的信任",
  "auto_consolidate": true         // 是否自动触发记忆固化
}
```

**`permission_ask`** — 请求玩家确认

```json
{
  "action": "world_traverse",
  "description": "即将穿越到高达SEED世界（CE71年）。此操作不可撤销。",
  "confirm_text": "确认穿越",
  "cancel_text": "取消",
  "status": "pending",             // pending / confirmed / cancelled
  "response_message_id": null      // 玩家确认后填入
}
```

**`compaction`** — 上下文压缩

```json
{
  "summary": "string",             // Chronicler 生成的章节摘要
  "messages_covered": 120,         // 被压缩的消息数量
  "turns_covered": 40,             // 被压缩的回合数
  "date_range": ["2026-05-01 10:00", "2026-05-31 22:00"],
  "key_events": [
    "主角加入天剑门",
    "首次使用ESP",
    "击败玄铁剑阵"
  ]
}
```

---

#### 实现扩展类型（6 种）

**`action_options`** — 回合结束后行动选项

```json
{
  "options": [
    {"id": "A", "text": "向前冲锋，拔剑迎敌"},
    {"id": "B", "text": "后退绕行，寻找掩体"},
    {"id": "C", "text": "大声呼喊，吸引援军"}
  ],
  "context": "string"              // 生成选项时使用的叙事上下文片段
}
```

**`reasoning`** — Agent 推理过程（plan/review 模式下对用户可见）

```json
{
  "agent": "dm_gate",              // 产出此推理的 Agent 名称
  "phase": "p1",
  "text": "string",                // 推理文本（流式拼接）
  "visible_in_modes": ["plan", "review"]
}
```

**`text`** — 纯文本 Part

```json
{
  "text": "string"                 // 纯文本内容
}
```

**`tool_call`** — 工具调用记录（工具执行前 emit）

```json
{
  "tool_name": "roll_dice",
  "args": {"pool": 6, "threshold": 8, "attribute": "DEX"},
  "call_id": "call_abc123",        // 与 tool_result 关联
  "agent": "rules"
}
```

**`tool_result`** — 工具返回结果（工具执行后 emit）

```json
{
  "tool_name": "roll_dice",
  "call_id": "call_abc123",        // 与 tool_call 关联
  "result": {},                    // 工具返回的原始 dict
  "error": "",                     // 非空表示执行失败
  "duration_ms": 12.5
}
```

**`var_diff`** — 变量差分（VarAgent 结算后 emit）

```json
{
  "updates": [
    {
      "path": "resources.hp.current",
      "before": 7,
      "after": 5,
      "delta": -2,
      "reason": "战斗受伤"
    }
  ],
  "source": "narrator_p4"          // narrator_p4 | world_event | dm_modify
}
```

### 1.4 Python ORM（aiosqlite）

```python
import uuid
import time
import json
import aiosqlite
from dataclasses import dataclass, field, asdict
from typing import Any


def new_id() -> str:
    """生成新的唯一 ID"""
    return str(uuid.uuid4())


def now() -> float:
    """返回当前 Unix 时间戳"""
    return time.time()


@dataclass
class Session:
    world_plugin: str
    agent_profile: str = "play"
    mode: str = "play"
    branch_of: str | None = None
    branch_label: str | None = None
    title: str | None = None
    state_json: dict = field(default_factory=dict)
    character_id: str | None = None
    id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    is_archived: int = 0

    async def save(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            INSERT OR REPLACE INTO sessions
            (id, world_plugin, agent_profile, mode, branch_of, branch_label,
             title, created_at, updated_at, state_json, is_archived, character_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.id, self.world_plugin, self.agent_profile, self.mode,
                self.branch_of, self.branch_label, self.title,
                self.created_at, self.updated_at,
                json.dumps(self.state_json, ensure_ascii=False),
                self.is_archived, self.character_id,
            )
        )
        await db.commit()

    @classmethod
    async def get(cls, db: aiosqlite.Connection, session_id: str) -> "Session | None":
        async with db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state_json"] = json.loads(d["state_json"])
        return cls(**d)


@dataclass
class Message:
    session_id: str
    role: str
    turn_index: int = 0
    phase: str | None = None
    agent_id: str | None = None
    status: str = "active"  # active | reverted（设计草案曾为"done"，已对齐 DB schema）
    tokens_used: int = 0
    id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=now)
    completed_at: float | None = None

    async def save(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            INSERT OR REPLACE INTO messages
            (id, session_id, role, turn_index, phase, agent_id,
             status, created_at, completed_at, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.id, self.session_id, self.role, self.turn_index,
                self.phase, self.agent_id, self.status,
                self.created_at, self.completed_at, self.tokens_used,
            )
        )
        await db.commit()


@dataclass
class MessagePart:
    message_id: str
    session_id: str
    type: str
    content: dict = field(default_factory=dict)
    status: str = "streaming"
    sort_order: int = 0
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=now)

    async def save(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            """
            INSERT OR REPLACE INTO message_parts
            (id, message_id, session_id, type, content, status,
             sort_order, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.id, self.message_id, self.session_id, self.type,
                json.dumps(self.content, ensure_ascii=False),
                self.status, self.sort_order, self.created_at,
                json.dumps(self.metadata, ensure_ascii=False),
            )
        )
        await db.commit()

    async def set_done(self, db: aiosqlite.Connection) -> None:
        self.status = "done"
        await db.execute(
            "UPDATE message_parts SET status = 'done' WHERE id = ?", (self.id,)
        )
        await db.commit()

    @classmethod
    async def list_by_message(
        cls, db: aiosqlite.Connection, message_id: str
    ) -> list["MessagePart"]:
        async with db.execute(
            "SELECT * FROM message_parts WHERE message_id = ? ORDER BY sort_order",
            (message_id,)
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["content"] = json.loads(d["content"])
            d["metadata"] = json.loads(d["metadata"])
            result.append(cls(**d))
        return result
```

---

## 2. 角色卡 v4 Schema

### 2.1 完整 JSON Schema 定义

角色卡 v4 是本系统的核心数据结构，统合了系统、战斗、心理、经济等所有维度。

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://zero-arsenal.local/schemas/character-card-v4.json",
  "title": "CharacterCard",
  "description": "AI-VN 互动叙事引擎角色卡 v4（统合版）",
  "type": "object",
  "required": ["meta", "identity", "attributes", "body_parts", "energy_pools",
               "loadout", "psychology", "economy"],
  "properties": {

    "meta": {
      "description": "卡片元数据",
      "type": "object",
      "required": ["schema_version", "world_plugin"],
      "properties": {
        "schema_version": {
          "description": "Schema 版本，用于迁移检查",
          "type": "string",
          "pattern": "^\\d+\\.\\d+\\.\\d+$",
          "example": "4.0.0"
        },
        "world_plugin": {
          "description": "角色当前所在世界的插件 ID",
          "type": "string",
          "example": "wuxia_jianghu"
        },
        "card_id": {
          "description": "卡片唯一 ID",
          "type": "string"
        },
        "created_at": {
          "type": "number",
          "description": "创建时间（Unix 时间戳）"
        },
        "updated_at": {
          "type": "number",
          "description": "最后更新时间"
        }
      }
    },

    "identity": {
      "description": "角色身份信息",
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {
          "description": "角色名称",
          "type": "string",
          "example": "林朔"
        },
        "aliases": {
          "description": "别名列表",
          "type": "array",
          "items": { "type": "string" }
        },
        "age": {
          "description": "年龄（可以是字符串如 '约17岁'）",
          "type": ["number", "string"]
        },
        "gender": {
          "type": "string",
          "enum": ["male", "female", "other", "unknown"]
        },
        "origin_world": {
          "description": "角色原世界（穿越者的来源）",
          "type": "string",
          "example": "real_world_2026"
        },
        "current_world": {
          "description": "当前所在世界",
          "type": "string",
          "example": "muv_luv_1998"
        },
        "cycle_count": {
          "description": "穿越次数（0 = 未穿越）",
          "type": "integer",
          "minimum": 0,
          "default": 0
        },
        "appearance": {
          "description": "外貌描述",
          "type": "object",
          "properties": {
            "hair_color": { "type": "string" },
            "hair_style": { "type": "string" },
            "eye_color": { "type": "string" },
            "height_cm": { "type": "number" },
            "build": {
              "type": "string",
              "enum": ["slim", "athletic", "muscular", "heavy", "petite", "average"]
            },
            "distinctive_features": {
              "type": "array",
              "items": { "type": "string" }
            },
            "typical_outfit": { "type": "string" }
          }
        }
      }
    },

    "attributes": {
      "description": "基础属性（由 WorldPlugin 定义维度，支持多种体系）",
      "type": "object",
      "properties": {
        "schema": {
          "description": "属性体系类型",
          "type": "string",
          "enum": ["standard_10d", "cultivation_8d", "custom"],
          "default": "standard_10d"
        },
        "values": {
          "description": "属性键值对，键名由 WorldPlugin 定义",
          "type": "object",
          "additionalProperties": { "type": "number" }
        }
      },
      "examples": [
        {
          "schema": "standard_10d",
          "values": {
            "STR": 3, "DEX": 5, "STA": 4,
            "INT": 4, "WIS": 3, "CHA": 4,
            "PER": 5, "WIL": 4, "LCK": 3, "ESP": 0
          }
        },
        {
          "schema": "cultivation_8d",
          "values": {
            "body_refining": 80,
            "qi_control": 45,
            "spiritual_sense": 30,
            "combat_instinct": 55,
            "comprehension": 70,
            "constitution": 60,
            "mind_purity": 40,
            "luck": 35
          }
        }
      ]
    },

    "body_parts": {
      "description": "六部位身体状态（来自 ai-vn-game-system 部位伤害系统）",
      "type": "object",
      "required": ["head", "torso", "left_arm", "right_arm", "left_leg", "right_leg"],
      "properties": {
        "head": { "$ref": "#/definitions/BodyPart" },
        "torso": { "$ref": "#/definitions/BodyPart" },
        "left_arm": { "$ref": "#/definitions/BodyPart" },
        "right_arm": { "$ref": "#/definitions/BodyPart" },
        "left_leg": { "$ref": "#/definitions/BodyPart" },
        "right_leg": { "$ref": "#/definitions/BodyPart" }
      }
    },

    "energy_pools": {
      "description": "能量池列表（可多个，如内力 + 体力 + 特殊能量）",
      "type": "array",
      "items": { "$ref": "#/definitions/EnergyPool" },
      "minItems": 1
    },

    "loadout": {
      "description": "技能与装备配置",
      "type": "object",
      "properties": {
        "passive_abilities": {
          "description": "被动技能列表",
          "type": "array",
          "items": { "$ref": "#/definitions/Ability" }
        },
        "power_sources": {
          "description": "能量来源（内功心法/魔法体系/科技装置）",
          "type": "array",
          "items": { "$ref": "#/definitions/PowerSource" }
        },
        "application_techniques": {
          "description": "主动技能/武技列表",
          "type": "array",
          "items": { "$ref": "#/definitions/ApplicationTechnique" }
        },
        "equipped": {
          "description": "已装备物品",
          "type": "array",
          "items": { "$ref": "#/definitions/EquippedItem" }
        }
      }
    },

    "psychology": {
      "description": "心理模型（来自 psyche_model_json 设计）",
      "type": "object",
      "properties": {
        "ocean": {
          "description": "OCEAN 五维人格（0-100 分）",
          "type": "object",
          "properties": {
            "openness":          { "type": "number", "minimum": 0, "maximum": 100 },
            "conscientiousness": { "type": "number", "minimum": 0, "maximum": 100 },
            "extraversion":      { "type": "number", "minimum": 0, "maximum": 100 },
            "agreeableness":     { "type": "number", "minimum": 0, "maximum": 100 },
            "neuroticism":       { "type": "number", "minimum": 0, "maximum": 100 }
          }
        },
        "stress": {
          "description": "当前压力值（0-100）",
          "type": "number", "minimum": 0, "maximum": 100, "default": 0
        },
        "morale": {
          "description": "士气（0-100）",
          "type": "number", "minimum": 0, "maximum": 100, "default": 80
        },
        "clarity": {
          "description": "神志清醒度（0-100，受伤/中毒/恐惧时降低）",
          "type": "number", "minimum": 0, "maximum": 100, "default": 100
        },
        "emotion_state": {
          "description": "当前主导情绪",
          "type": "string",
          "enum": ["calm", "anxious", "angry", "joyful", "fearful",
                   "grieving", "determined", "numb", "elated", "despair"],
          "default": "calm"
        },
        "traumas": {
          "description": "心理创伤列表",
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": { "type": "string" },
              "description": { "type": "string" },
              "severity": { "type": "integer", "minimum": 1, "maximum": 5 },
              "trigger_keywords": { "type": "array", "items": { "type": "string" } },
              "acquired_at": { "type": "string" }
            }
          }
        },
        "beliefs": {
          "description": "核心信念列表（影响行为决策）",
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "belief": { "type": "string" },
              "strength": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },
        "core_values": {
          "description": "核心价值观（用于 NPC 行为一致性检查）",
          "type": "array",
          "items": { "type": "string" },
          "maxItems": 3
        },
        "behavior_patterns": {
          "description": "典型行为模式描述（1-2句）",
          "type": "string"
        },
        "emotional_triggers": {
          "description": "情绪触发点（什么情况下脱离常规反应）",
          "type": "string"
        }
      }
    },

    "economy": {
      "description": "经济状态（来自 anti-feat 星级系统）",
      "type": "object",
      "properties": {
        "points": {
          "description": "系统积分",
          "type": "integer", "minimum": 0, "default": 0
        },
        "badges": {
          "description": "徽章数量（用于开启精准词条池）",
          "type": "integer", "minimum": 0, "default": 0
        },
        "tier": {
          "description": "Anti-Feat 星级（1-10）",
          "type": "integer", "minimum": 0, "maximum": 10, "default": 0
        },
        "tier_sub": {
          "description": "星级子段位",
          "type": "string", "enum": ["L", "M", "U", ""], "default": ""
        },
        "cash": {
          "description": "世界内货币（键为货币单位，值为数量）",
          "type": "object",
          "additionalProperties": { "type": "number" }
        }
      }
    },

    "relationships": {
      "description": "关系网络",
      "type": "array",
      "items": {
        "type": "object",
        "required": ["npc_id", "name"],
        "properties": {
          "npc_id":   { "type": "string" },
          "name":     { "type": "string" },
          "type": {
            "type": "string",
            "enum": ["ally", "friend", "neutral", "rival", "hostile",
                     "mentor", "student", "romantic", "family"]
          },
          "affinity": {
            "description": "好感度 -100 到 +100",
            "type": "integer", "minimum": -100, "maximum": 100, "default": 0
          },
          "trust": {
            "description": "信任度 0-100",
            "type": "integer", "minimum": 0, "maximum": 100, "default": 50
          },
          "tags": {
            "description": "关系标签（如 known_true_identity / saved_life）",
            "type": "array",
            "items": { "type": "string" }
          },
          "last_interaction_turn": { "type": "integer" }
        }
      }
    },

    "achievements": {
      "description": "已解锁成就列表",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id":          { "type": "string" },
          "name":        { "type": "string" },
          "description": { "type": "string" },
          "unlocked_at": { "type": "number" }
        }
      }
    }
  },

  "definitions": {
    "BodyPart": {
      "type": "object",
      "required": ["hp_max", "hp_current"],
      "properties": {
        "hp_max":         { "type": "integer", "minimum": 0 },
        "hp_current":     { "type": "integer", "minimum": 0 },
        "armor":          { "type": "integer", "minimum": 0, "default": 0 },
        "status_effects": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    },
    "EnergyPool": {
      "type": "object",
      "required": ["name", "current", "max"],
      "properties": {
        "name":           { "type": "string" },
        "current":        { "type": "number", "minimum": 0 },
        "max":            { "type": "number", "minimum": 0 },
        "regen_per_turn": { "type": "number", "default": 0 },
        "type": {
          "type": "string",
          "enum": ["qi", "mana", "stamina", "tech_charge", "custom"]
        }
      }
    },
    "Ability": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":           { "type": "string" },
        "name":         { "type": "string" },
        "description":  { "type": "string" },
        "tier":         { "type": "integer" },
        "tier_sub":     { "type": "string" },
        "source":       { "type": "string", "description": "ACG 出处" },
        "proficiency":  { "type": "integer", "minimum": 0, "maximum": 100 }
      }
    },
    "ApplicationTechnique": {
      "allOf": [
        { "$ref": "#/definitions/Ability" },
        {
          "properties": {
            "energy_cost":  { "type": "object", "additionalProperties": { "type": "number" } },
            "cooldown":     { "type": "integer", "description": "冷却回合数" },
            "range":        { "type": "string", "enum": ["melee", "ranged", "self", "aoe"] },
            "hax_type":     { "type": "string", "description": "Hax 类型标注" }
          }
        }
      ]
    },
    "PowerSource": {
      "type": "object",
      "required": ["id", "name"],
      "properties": {
        "id":           { "type": "string" },
        "name":         { "type": "string" },
        "description":  { "type": "string" },
        "energy_pool":  { "type": "string", "description": "关联的能量池 name" },
        "proficiency":  { "type": "integer", "minimum": 0, "maximum": 100 }
      }
    },
    "EquippedItem": {
      "type": "object",
      "required": ["id", "name", "slot"],
      "properties": {
        "id":     { "type": "string" },
        "name":   { "type": "string" },
        "slot":   { "type": "string", "enum": ["weapon_main", "weapon_off", "armor",
                                                "accessory_1", "accessory_2", "special"] },
        "tier":   { "type": "integer" },
        "effects":{ "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### 2.2 角色卡存储表

```sql
CREATE TABLE IF NOT EXISTS character_cards (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    version         TEXT NOT NULL DEFAULT '4.0.0',
    -- 完整角色卡 JSON（通过 JSON1 扩展可部分查询）
    card_json       TEXT NOT NULL,
    -- 常用字段提升为列，方便快速查询
    character_name  TEXT NOT NULL,
    world_plugin    TEXT NOT NULL,
    tier            INTEGER DEFAULT 0,
    tier_sub        TEXT DEFAULT '',
    points          INTEGER DEFAULT 0,
    hp_overall      REAL DEFAULT 1.0,    -- 综合HP%
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    updated_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE INDEX IF NOT EXISTS idx_cards_session ON character_cards(session_id);
CREATE INDEX IF NOT EXISTS idx_cards_name ON character_cards(character_name);

-- 角色卡快照（每章结束时保存，用于回溯）
CREATE TABLE IF NOT EXISTS character_snapshots (
    id              TEXT PRIMARY KEY,
    card_id         TEXT NOT NULL REFERENCES character_cards(id) ON DELETE CASCADE,
    chapter_id      TEXT,
    snapshot_json   TEXT NOT NULL,
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
```

---

## 3. 世界档案 Schema

### 3.1 完整 JSON 结构

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WorldArchive",
  "description": "会话世界档案，记录当前世界的完整状态",
  "type": "object",

  "world_key": "wuxia_jianghu",
  "world_name": "武侠江湖",

  "current_location": {
    "id": "loc_tianquan_city",
    "name": "天权城",
    "description": "西域第一大城，商贸繁盛，帮派林立",
    "region": "西域",
    "is_safe_zone": false,
    "ambient_danger": 3
  },

  "time": {
    "year": 322,
    "month": 4,
    "day": 15,
    "clock": "14:30",
    "era": "玄元历",
    "season": "spring"
  },

  "elapsed_seconds": 1209600,
  "time_flow_ratio": 1.0,

  "peak_tier": "5★U",

  "world_rules": [
    {
      "id": "rule_qi_system",
      "title": "内功体系",
      "content": "内力是武侠世界核心能量，境界：炼气→筑基→金丹→元婴→化神",
      "is_active": true
    }
  ],

  "power_systems": [
    {
      "id": "ps_inner_qi",
      "name": "内功修炼",
      "description": "以呼吸吐纳聚敛天地灵气，转化为内力储存于丹田",
      "tiers": ["炼气期", "筑基期", "金丹期", "元婴期", "化神期"],
      "source_worlds": ["wuxia_jianghu"]
    }
  ],

  "npcs": [
    {
      "id": "npc_blacksmith_wang",
      "name": "王铁匠",
      "current_location": "loc_tianquan_city",
      "is_present": true,
      "affinity": 15,
      "trust": 40,
      "relationship_type": "neutral",
      "knowledge_of_protagonist": ["姓名", "粗通武艺", "修炼不足十年"],
      "last_seen_turn": 42,
      "profile_ref": "npc_profiles/npc_blacksmith_wang.json"
    }
  ],

  "world_identity": {
    "technology_level": "medieval_fantasy",
    "magic_prevalence": "common",
    "political_structure": "city_states",
    "major_factions": ["天剑门", "血刀帮", "朝廷西域都护府"],
    "current_conflicts": ["血刀帮与天剑门领地争夺"],
    "known_threats": ["妖兽南侵", "血刀帮扩张"]
  },

  "active_events": [
    {
      "id": "event_weapons_fair",
      "title": "天权城兵器大会",
      "status": "ongoing",
      "deadline_day": 330,
      "description": "每十年一届，各方势力携宝器参展竞技",
      "protagonist_involvement": "已报名鉴器环节"
    }
  ],

  "log": [
    {
      "turn_index": 42,
      "time": "322-04-15 14:00",
      "event": "主角拜访王铁匠，鉴定玄铁剑，好感度 +5"
    }
  ]
}
```

### 3.2 世界档案存储表

```sql
CREATE TABLE IF NOT EXISTS world_archives (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    world_key       TEXT NOT NULL,
    archive_json    TEXT NOT NULL,
    -- 提升常用字段
    current_location_id   TEXT,
    world_time_str        TEXT,
    elapsed_seconds       REAL DEFAULT 0,
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    updated_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

-- NPC 档案独立存储（便于全局复用）
CREATE TABLE IF NOT EXISTS npc_profiles (
    id              TEXT PRIMARY KEY,
    world_key       TEXT NOT NULL,
    npc_name        TEXT NOT NULL,
    -- 完整 NPC 档案（psyche_model_json + 外貌 + 能力）
    profile_json    TEXT NOT NULL,
    created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    updated_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_world_name ON npc_profiles(world_key, npc_name);

-- 会话-NPC 关系状态（session 级别的动态状态，与全局 NPC 档案分离）
CREATE TABLE IF NOT EXISTS session_npc_states (
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    npc_id          TEXT NOT NULL,
    affinity        INTEGER DEFAULT 0,
    trust           INTEGER DEFAULT 50,
    relationship_type TEXT DEFAULT 'neutral',
    knowledge_of_protagonist TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    last_seen_turn  INTEGER DEFAULT 0,
    state_json      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (session_id, npc_id)
);
```

---

## 4. 章节树结构

### 4.1 设计来源

参考 pi 的 JSONL 消息树结构（每条消息有 `parent_id`，形成树形历史）和 SQLite 持久化方案，将章节建模为有向无环图（DAG），支持：

- **主线推进**：`parent_chapter_id` 链式连接
- **分支探索**：`branch_label` 标记分支，可从任意章节分叉
- **记忆固化**：`is_consolidated` 标记已经摘要化的章节

### 4.2 建表 SQL

```sql
-- =====================================================
-- 章节树
-- =====================================================
CREATE TABLE IF NOT EXISTS chapters (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    -- 父章节（NULL 表示该会话的第一章）
    parent_chapter_id   TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    -- 分支标签（NULL = 主线，非 NULL = 分支名）
    branch_label        TEXT,
    -- 章节在主线/分支中的序号（从 1 开始）
    chapter_index       INTEGER NOT NULL DEFAULT 1,
    -- 章节包含的消息范围
    start_message_id    TEXT REFERENCES messages(id),
    end_message_id      TEXT REFERENCES messages(id),
    -- 章节摘要（由 Chronicler Agent 生成）
    summary             TEXT,
    -- 关键事件列表（JSON 数组）
    key_events          TEXT NOT NULL DEFAULT '[]',
    -- 是否已固化（固化后该章节消息可被摘要替代）
    is_consolidated     INTEGER NOT NULL DEFAULT 0,
    -- 世界时间范围
    world_time_start    TEXT,
    world_time_end      TEXT,
    created_at          REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    consolidated_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_chapters_session ON chapters(session_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_chapters_parent ON chapters(parent_chapter_id);
CREATE INDEX IF NOT EXISTS idx_chapters_branch ON chapters(session_id, branch_label);
```

### 4.3 章节树操作

```python
class ChapterTreeManager:
    """章节树的创建、查询、固化操作"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create_chapter(
        self,
        session_id: str,
        parent_chapter_id: str | None = None,
        branch_label: str | None = None,
    ) -> "Chapter":
        """创建新章节"""
        # 计算 chapter_index
        if parent_chapter_id is None:
            index = 1
        else:
            async with self.db.execute(
                "SELECT MAX(chapter_index) FROM chapters WHERE session_id = ? AND branch_label IS ?",
                (session_id, branch_label)
            ) as cur:
                row = await cur.fetchone()
                index = (row[0] or 0) + 1

        chapter = Chapter(
            session_id=session_id,
            parent_chapter_id=parent_chapter_id,
            branch_label=branch_label,
            chapter_index=index,
        )
        await chapter.save(self.db)
        return chapter

    async def get_lineage(self, chapter_id: str) -> list["Chapter"]:
        """获取从根章节到当前章节的完整血统链（主线章节列表）"""
        lineage = []
        current_id = chapter_id
        while current_id is not None:
            chapter = await Chapter.get(self.db, current_id)
            if chapter is None:
                break
            lineage.insert(0, chapter)
            current_id = chapter.parent_chapter_id
        return lineage

    async def consolidate(
        self,
        chapter_id: str,
        chronicler_agent: "ChroniclerAgent",
    ) -> str:
        """
        固化章节：
        1. 召唤 Chronicler Agent 生成摘要
        2. 将摘要写入 chapter.summary
        3. 将章节消息写入 memory_entries（episodic 层）
        4. 标记 is_consolidated = 1
        """
        chapter = await Chapter.get(self.db, chapter_id)
        if chapter is None or chapter.is_consolidated:
            return chapter.summary if chapter else ""

        # 获取章节消息
        messages = await self._get_chapter_messages(chapter)

        # 生成摘要
        summary = await chronicler_agent.summarize(messages, chapter)

        # 写入摘要和 key_events
        key_events = await chronicler_agent.extract_key_events(messages)
        await self.db.execute(
            """
            UPDATE chapters
            SET summary = ?, key_events = ?, is_consolidated = 1, consolidated_at = ?
            WHERE id = ?
            """,
            (summary, json.dumps(key_events, ensure_ascii=False), now(), chapter_id)
        )
        await self.db.commit()

        return summary
```

---

## 5. 记忆表

### 5.1 四层记忆架构

参考 HippoRAG 的分层记忆模型，将记忆分为四层：

| 层 | 名称 | 特征 | 存储方式 |
|----|------|------|----------|
| **episodic** | 情节记忆 | 具体事件，带时间戳，细节丰富 | 向量 + BM25 |
| **semantic** | 语义记忆 | 抽象知识，无时间戳，跨场景通用 | 向量 + 图节点 |
| **core** | 核心记忆 | 永不遗忘的关键事实，始终注入 | 直接注入（不参与召回） |
| **working** | 工作记忆 | 当前场景的短期记忆，最多保留 10 条 | 内存（不持久化） |

### 5.2 建表 SQL

```sql
-- =====================================================
-- 记忆条目表
-- =====================================================
CREATE TABLE IF NOT EXISTS memory_entries (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id          TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    -- 记忆内容文本
    content             TEXT NOT NULL,
    -- 向量嵌入（float32 序列化为 bytes）
    embedding           BLOB,
    -- BM25 索引用的 Bigram Token 列表（JSON 数组）
    bigram_tokens       TEXT NOT NULL DEFAULT '[]',
    -- 图数据库关联节点（JSON，用于 GraphRAG）
    graph_nodes         TEXT NOT NULL DEFAULT '[]',
    -- 记忆层
    tier                TEXT NOT NULL DEFAULT 'episodic'
                            CHECK(tier IN ('episodic', 'semantic', 'core', 'working')),
    -- 认知分区（来自哪个视角）
    cognitive_partition TEXT NOT NULL DEFAULT 'objective_global'
                            CHECK(cognitive_partition IN (
                                'character_pov',    -- 主角主观视角
                                'objective_global', -- 客观全知视角
                                'npc_pov'           -- NPC 视角
                            )),
    -- 重要性分数（0.0-1.0，影响召回优先级）
    importance          REAL NOT NULL DEFAULT 0.5,
    -- 关联的 NPC ID 列表（JSON 数组，用于过滤）
    related_npcs        TEXT NOT NULL DEFAULT '[]',
    -- 关联的地点 ID
    related_location    TEXT,
    -- 关联的世界时间
    world_time          TEXT,
    -- 创建时间
    created_at          REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 固化时间（working → episodic 时填入）
    consolidated_at     REAL,
    -- 访问次数（衰减计算用）
    access_count        INTEGER NOT NULL DEFAULT 0,
    -- 最后访问时间
    last_accessed_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_entries(session_id, tier);
CREATE INDEX IF NOT EXISTS idx_memory_chapter ON memory_entries(chapter_id);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_entries(session_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_partition ON memory_entries(session_id, cognitive_partition);

-- 向量索引元数据（实际向量搜索由 Python 侧 FAISS/Annoy 管理）
CREATE TABLE IF NOT EXISTS vector_index_meta (
    session_id          TEXT PRIMARY KEY,
    index_type          TEXT DEFAULT 'faiss_flat',  -- faiss_flat / annoy / sqlite_vss
    dimension           INTEGER DEFAULT 768,
    total_vectors       INTEGER DEFAULT 0,
    index_path          TEXT,
    last_rebuilt_at     REAL
);
```

### 5.3 记忆召回实现（P2 RAG 阶段）

```python
class MemoryRecaller:
    """
    混合检索：向量相似度 + BM25 关键词 + 图节点扩展。
    P2 阶段由 LangGraph 节点自动调用。
    """

    def __init__(self, db: aiosqlite.Connection, vector_store):
        self.db = db
        self.vector_store = vector_store

    async def recall(
        self,
        session_id: str,
        query: str,
        top_k: int = 5,
        tier_filter: list[str] | None = None,
        partition_filter: str | None = None,
    ) -> list[dict]:
        """
        混合召回主入口。

        1. 向量检索（语义相似度）
        2. BM25 检索（关键词匹配）
        3. 结果融合（RRF Reciprocal Rank Fusion）
        4. 图扩展（找相关节点）
        5. 重排序（importance × relevance）
        """
        # Step 1：向量检索
        query_embedding = await self._embed(query)
        vector_results = await self.vector_store.search(
            session_id, query_embedding, top_k=top_k * 2
        )

        # Step 2：BM25 检索
        bm25_results = await self._bm25_search(session_id, query, top_k=top_k * 2)

        # Step 3：RRF 融合
        fused = self._reciprocal_rank_fusion(vector_results, bm25_results)

        # Step 4：过滤
        if tier_filter:
            fused = [r for r in fused if r["tier"] in tier_filter]
        if partition_filter:
            fused = [r for r in fused if r["cognitive_partition"] == partition_filter]

        # Step 5：更新访问计数
        top_results = fused[:top_k]
        await self._update_access_counts([r["id"] for r in top_results])

        return top_results

    async def add(
        self,
        session_id: str,
        content: str,
        tier: str = "episodic",
        chapter_id: str | None = None,
        related_npcs: list[str] | None = None,
        importance: float = 0.5,
        world_time: str | None = None,
    ) -> str:
        """添加新记忆条目"""
        embedding = await self._embed(content)
        bigrams = self._compute_bigrams(content)

        entry = MemoryEntry(
            session_id=session_id,
            chapter_id=chapter_id,
            content=content,
            embedding=embedding,
            bigram_tokens=json.dumps(bigrams, ensure_ascii=False),
            tier=tier,
            importance=importance,
            related_npcs=json.dumps(related_npcs or [], ensure_ascii=False),
            world_time=world_time,
        )
        await entry.save(self.db)

        # 更新向量索引
        await self.vector_store.add(session_id, entry.id, embedding)

        return entry.id

    @staticmethod
    def _reciprocal_rank_fusion(
        list_a: list[dict], list_b: list[dict], k: int = 60
    ) -> list[dict]:
        """RRF 融合两个排序列表"""
        scores: dict[str, float] = {}
        all_items: dict[str, dict] = {}

        for rank, item in enumerate(list_a):
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (k + rank + 1)
            all_items[item["id"]] = item

        for rank, item in enumerate(list_b):
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (k + rank + 1)
            all_items[item["id"]] = item

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [all_items[id_] for id_ in sorted_ids]
```

---

## 6. 骰子日志

### 6.1 建表 SQL

```sql
-- =====================================================
-- 骰子日志（双写：SQLite + JSONL 文件）
-- =====================================================
CREATE TABLE IF NOT EXISTS dice_log (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    -- 产生骰子的消息 Part ID（关联 message_parts 表）
    part_id         TEXT REFERENCES message_parts(id),
    -- 判定时间
    timestamp       REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    -- 判定输入（属性/技能/修正值等完整上下文）
    input_json      TEXT NOT NULL,
    -- 判定结果（骰池详情）
    result_json     TEXT NOT NULL,
    -- 最终判定结论
    verdict         TEXT NOT NULL CHECK(verdict IN ('success', 'failure', 'botch', 'critical')),
    -- 执行判定的 Agent
    agent_id        TEXT,
    -- 是否已被叙事引用
    referenced      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dice_session ON dice_log(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dice_verdict ON dice_log(session_id, verdict);
```

### 6.2 Input/Result JSON 结构定义

**`input_json`**（判定输入）：

```json
{
  "character_id": "char_linsuo_001",
  "character_name": "林朔",
  "attribute": "DEX",
  "attribute_value": 5,
  "skill": "轻功",
  "skill_level": 3,
  "modifiers": [
    { "source": "地形优势", "value": 1 },
    { "source": "内力耗尽", "value": -2 }
  ],
  "final_pool": 7,
  "difficulty": 3,
  "reason": "试图从屋顶跳跃逃离追兵",
  "context": "CE天权城战斗，第3回合",
  "target_npc": null
}
```

**`result_json`**（判定结果）：

```json
{
  "dice_values": [1, 2, 4, 5, 6, 6, 3],
  "raw_successes": 3,
  "ones_count": 1,
  "net_successes": 2,
  "is_botch": false,
  "is_critical": false,
  "thresholds_met": {
    "difficulty_3": true,
    "difficulty_5": false
  },
  "roll_formula": "7d10 vs 难度3",
  "rng_seed": "abc123def456"
}
```

### 6.3 JSONL 双写（可审计）

```python
import aiofiles
from pathlib import Path
from datetime import datetime


class DiceLogger:
    """
    骰子双写器：同时写入 SQLite 和 JSONL 文件。
    JSONL 文件作为不可篡改的审计日志。
    """

    def __init__(self, db: aiosqlite.Connection, log_dir: Path):
        self.db = db
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def log(
        self,
        session_id: str,
        input_data: dict,
        result_data: dict,
        verdict: str,
        part_id: str | None = None,
        agent_id: str | None = None,
    ) -> str:
        """记录一次骰子判定"""
        entry_id = new_id()
        ts = now()

        # 1. 写入 SQLite
        await self.db.execute(
            """
            INSERT INTO dice_log
            (id, session_id, part_id, timestamp, input_json, result_json, verdict, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id, session_id, part_id, ts,
                json.dumps(input_data, ensure_ascii=False),
                json.dumps(result_data, ensure_ascii=False),
                verdict, agent_id,
            )
        )
        await self.db.commit()

        # 2. 写入 JSONL 文件（按日期分割）
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        jsonl_path = self.log_dir / f"rolls_{date_str}.jsonl"

        record = {
            "id": entry_id,
            "session_id": session_id,
            "timestamp": ts,
            "input": input_data,
            "result": result_data,
            "verdict": verdict,
        }

        async with aiofiles.open(jsonl_path, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return entry_id

    async def get_session_stats(self, session_id: str) -> dict:
        """获取会话骰子统计"""
        async with self.db.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'success' THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN verdict = 'failure' THEN 1 ELSE 0 END) as failures,
                SUM(CASE WHEN verdict = 'botch' THEN 1 ELSE 0 END) as botches,
                SUM(CASE WHEN verdict = 'critical' THEN 1 ELSE 0 END) as criticals
            FROM dice_log WHERE session_id = ?
            """,
            (session_id,)
        ) as cur:
            row = dict(await cur.fetchone())
        total = row["total"] or 1
        row["success_rate"] = round(row["successes"] / total, 3)
        return row
```

---

## 7. 系统配置表

### 7.1 agents.json（LLM 路由配置）

来源：ai-vn-system-backend Agent 路由机制

```json
{
  "$schema": "https://zero-arsenal.local/schemas/agents-config.json",
  "version": "1.0.0",
  "default_provider": "openai",

  "providers": {
    "openai": {
      "type": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "timeout_seconds": 60
    },
    "anthropic": {
      "type": "anthropic",
      "base_url": "https://api.anthropic.com",
      "api_key_env": "ANTHROPIC_API_KEY",
      "timeout_seconds": 60
    },
    "local_ollama": {
      "type": "openai_compatible",
      "base_url": "http://localhost:11434/v1",
      "api_key_env": null,
      "timeout_seconds": 120
    }
  },

  "agents": {
    "dm_agent": {
      "description": "DM Agent，负责规划和工具调用（P1阶段）",
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "temperature": 0.3,
      "max_tokens": 4096,
      "streaming": false,
      "tool_choice": "auto",
      "fallback": {
        "provider": "openai",
        "model": "gpt-4o"
      }
    },
    "narrator_agent": {
      "description": "Narrator Agent，负责叙事生成（P3阶段）",
      "provider": "anthropic",
      "model": "claude-opus-4-5",
      "temperature": 0.85,
      "max_tokens": 8192,
      "streaming": true,
      "fallback": {
        "provider": "openai",
        "model": "gpt-4o"
      }
    },
    "calibrator_agent": {
      "description": "Calibrator Agent，负责数值结算（P4阶段）",
      "provider": "openai",
      "model": "gpt-4o-mini",
      "temperature": 0.1,
      "max_tokens": 2048,
      "streaming": false,
      "response_format": { "type": "json_object" }
    },
    "chronicler_agent": {
      "description": "Chronicler Agent，负责章节摘要",
      "provider": "openai",
      "model": "gpt-4o-mini",
      "temperature": 0.3,
      "max_tokens": 2048,
      "streaming": false
    },
    "shopkeeper_agent": {
      "description": "商店 Agent，负责经济交互",
      "provider": "local_ollama",
      "model": "llama3.1:8b",
      "temperature": 0.5,
      "max_tokens": 1024,
      "streaming": false
    }
  },

  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "dimension": 1536,
    "batch_size": 100
  },

  "cost_tracking": {
    "enabled": true,
    "alert_threshold_usd": 5.0,
    "log_path": "data/cost_log.jsonl"
  }
}
```

### 7.2 mcp.json（MCP 服务配置）

```json
{
  "$schema": "https://zero-arsenal.local/schemas/mcp-config.json",
  "version": "1.0.0",

  "servers": {
    "novel_system": {
      "description": "小说系统核心 MCP 服务（查询角色/记忆/设定）",
      "type": "stdio",
      "command": "python",
      "args": ["system/backend/mcp_server.py"],
      "env": {
        "NOVEL_DB": "${WORKSPACE}/system/backend/data/novel_system.db",
        "PYTHONPATH": "${WORKSPACE}"
      },
      "tools": [
        "get_working_memory",
        "query_character",
        "search_lore",
        "add_lore",
        "update_info_matrix",
        "earn_battle_rewards"
      ],
      "auto_start": true,
      "restart_on_failure": true
    },
    "web_search": {
      "description": "联网搜索（world lore 查询降级使用）",
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY_ENV": "BRAVE_API_KEY"
      },
      "tools": ["brave_web_search"],
      "auto_start": false
    },
    "filesystem": {
      "description": "文件系统访问（提示词热更新监控）",
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem",
               "${WORKSPACE}/prompts",
               "${WORKSPACE}/skills",
               "${WORKSPACE}/writing-styles"],
      "tools": ["read_file", "list_directory"],
      "auto_start": true
    }
  },

  "tool_routing": {
    "get_working_memory":    "novel_system",
    "query_character":       "novel_system",
    "search_lore":           "novel_system",
    "add_lore":              "novel_system",
    "brave_web_search":      "web_search",
    "read_file":             "filesystem"
  }
}
```

### 7.3 配置加载与验证

```python
import json
from pathlib import Path
from typing import Any
import jsonschema


class ConfigLoader:
    """系统配置加载器，支持环境变量替换和 JSON Schema 验证"""

    CONFIG_FILES = {
        "agents":   "config/agents.json",
        "mcp":      "config/mcp.json",
    }

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self._cache: dict[str, dict] = {}

    def load(self, config_name: str) -> dict:
        """加载并缓存配置，自动替换 ${WORKSPACE} 占位符"""
        if config_name in self._cache:
            return self._cache[config_name]

        config_path = self.workspace_root / self.CONFIG_FILES[config_name]
        raw = config_path.read_text(encoding="utf-8")

        # 替换 ${WORKSPACE}
        raw = raw.replace("${WORKSPACE}", str(self.workspace_root).replace("\\", "/"))

        config = json.loads(raw)
        self._cache[config_name] = config
        return config

    def get_agent_config(self, agent_id: str) -> dict:
        agents_cfg = self.load("agents")
        if agent_id not in agents_cfg["agents"]:
            raise ValueError(f"未知 Agent ID: {agent_id}")
        cfg = agents_cfg["agents"][agent_id].copy()
        provider = cfg.pop("provider")
        cfg["provider_config"] = agents_cfg["providers"][provider]
        return cfg

    def invalidate_cache(self) -> None:
        """热更新：清除缓存，下次访问时重新加载"""
        self._cache.clear()
```

---

## 8. 数据迁移策略

### 8.1 Alembic 迁移配置

```
zero-arsenal/
├── alembic.ini                    # Alembic 主配置
├── alembic/
│   ├── env.py                     # 迁移环境配置
│   ├── script.py.mako             # 迁移脚本模板
│   └── versions/
│       ├── 001_initial_schema.py  # 初始 Schema
│       ├── 002_add_npc_trust.py   # 新增 NPC 信任度字段
│       └── ...
└── system/backend/data/
    └── zero_arsenal.db            # 主数据库
```

**`alembic.ini`**（核心配置）：

```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:///%(here)s/system/backend/data/zero_arsenal.db

[loggers]
keys = root,sqlalchemy,alembic

[logger_alembic]
level = INFO
handlers =
qualname = alembic
```

**`alembic/env.py`**（aiosqlite 适配）：

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

# 支持环境变量覆盖数据库路径
db_path = os.getenv("ZERO_ARSENAL_DB", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_path)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,  # 使用 raw SQL，不依赖 SQLAlchemy ORM
            render_as_batch=True,  # SQLite 的 ALTER TABLE 支持
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

### 8.2 迁移脚本示例

**`versions/001_initial_schema.py`**：

```python
"""初始 Schema 创建

Revision ID: 001
Revises: -
Create Date: 2026-05-31
"""
from alembic import op

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              TEXT PRIMARY KEY,
            world_plugin    TEXT NOT NULL,
            agent_profile   TEXT NOT NULL DEFAULT 'play',
            mode            TEXT NOT NULL DEFAULT 'play',
            branch_of       TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            branch_label    TEXT,
            title           TEXT,
            created_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
            updated_at      REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
            state_json      TEXT NOT NULL DEFAULT '{}',
            is_archived     INTEGER NOT NULL DEFAULT 0,
            character_id    TEXT
        )
    """)
    # ... 其余表创建语句


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    # ... 其余表删除语句
```

**`versions/002_add_npc_trust.py`**：

```python
"""为 session_npc_states 添加 trust 字段

Revision ID: 002
Revises: 001
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'


def upgrade() -> None:
    # SQLite 的 ALTER TABLE 通过 render_as_batch=True 支持
    with op.batch_alter_table('session_npc_states') as batch_op:
        batch_op.add_column(
            sa.Column('trust', sa.Integer(), nullable=False, server_default='50')
        )


def downgrade() -> None:
    with op.batch_alter_table('session_npc_states') as batch_op:
        batch_op.drop_column('trust')
```

### 8.3 向后兼容升级策略

#### 原则

1. **只增不删**：新版本只添加字段/表，不删除现有字段（删除留到 MAJOR 版本）
2. **默认值安全**：所有新增字段必须有合理的 `DEFAULT`，避免旧数据查询出错
3. **Schema 版本字段**：角色卡 JSON 有 `meta.schema_version`，加载时检查并自动迁移
4. **测试必覆盖**：每个迁移脚本必须有对应的 `downgrade` 和单元测试

#### 角色卡 JSON 内联迁移

```python
class CharacterCardMigrator:
    """
    角色卡 JSON 格式版本迁移器。
    在加载旧版角色卡时自动升级到最新版本。
    """

    CURRENT_VERSION = "4.0.0"

    MIGRATIONS: dict[str, callable] = {
        "3.0.0": "_migrate_3_to_4",
        "3.1.0": "_migrate_3_1_to_4",
    }

    @classmethod
    def migrate(cls, card_json: dict) -> dict:
        version = card_json.get("meta", {}).get("schema_version", "1.0.0")

        if version == cls.CURRENT_VERSION:
            return card_json

        migration_fn_name = cls.MIGRATIONS.get(version)
        if migration_fn_name is None:
            raise ValueError(
                f"无法从版本 {version} 迁移到 {cls.CURRENT_VERSION}。"
                f"支持的迁移版本：{list(cls.MIGRATIONS.keys())}"
            )

        migrated = getattr(cls, migration_fn_name)(card_json)
        migrated["meta"]["schema_version"] = cls.CURRENT_VERSION
        return migrated

    @staticmethod
    def _migrate_3_to_4(card: dict) -> dict:
        """v3 → v4：拆分 inventory 为 loadout；添加 body_parts"""
        card_v4 = dict(card)

        # 旧的 inventory 字段迁移到新的 loadout 结构
        old_inventory = card_v4.pop("inventory", [])
        card_v4["loadout"] = {
            "passive_abilities": [],
            "power_sources": [],
            "application_techniques": [],
            "equipped": old_inventory,
        }

        # 新增 body_parts 字段（默认满血）
        default_part = {"hp_max": 100, "hp_current": 100, "armor": 0, "status_effects": []}
        card_v4["body_parts"] = {
            "head":      dict(default_part, hp_max=60, hp_current=60),
            "torso":     dict(default_part, hp_max=100, hp_current=100),
            "left_arm":  dict(default_part, hp_max=70, hp_current=70),
            "right_arm": dict(default_part, hp_max=70, hp_current=70),
            "left_leg":  dict(default_part, hp_max=80, hp_current=80),
            "right_leg": dict(default_part, hp_max=80, hp_current=80),
        }

        return card_v4
```

### 8.4 数据库初始化与连接管理

```python
import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager


DB_PATH = Path(__file__).parent / "data" / "zero_arsenal.db"

PRAGMAS = [
    "PRAGMA journal_mode=WAL",       # 写前日志，提高并发读性能
    "PRAGMA synchronous=NORMAL",     # 平衡性能与安全性
    "PRAGMA foreign_keys=ON",        # 强制外键约束
    "PRAGMA cache_size=-32000",      # 32MB 缓存
    "PRAGMA temp_store=MEMORY",      # 临时表存内存
]


@asynccontextmanager
async def get_db(db_path: Path = DB_PATH):
    """
    数据库连接上下文管理器。
    自动应用性能 PRAGMA 并启用 row_factory。
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for pragma in PRAGMAS:
            await db.execute(pragma)
        yield db


async def init_db(db_path: Path = DB_PATH) -> None:
    """
    初始化数据库：运行所有 DDL 语句。
    幂等操作，可安全多次调用。
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")
```

---

*文档结束。最后更新：2026-05-31*
