"""
SQLite 数据库 Schema — Session / Message / Part / Character / Chapter / Memory / DiceLog
参考设计文档 06-data-model.md
"""

CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- ── 会话表 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    world_plugin    TEXT NOT NULL DEFAULT 'crossover',
    agent_profile   TEXT NOT NULL DEFAULT 'play',
    mode            TEXT NOT NULL DEFAULT 'play',  -- play | plan | review
    branch_of       TEXT REFERENCES sessions(id),  -- 分支来源（NULL=主线）
    branch_label    TEXT,                          -- 分支显示名称（NULL=主线）
    fork_from_msg   TEXT REFERENCES messages(id),  -- 分叉起点消息 ID
    title           TEXT,
    status          TEXT NOT NULL DEFAULT 'active', -- active | deleted | archived
    is_archived     INTEGER NOT NULL DEFAULT 0,    -- 0=正常 1=已归档
    character_id    TEXT,                          -- 关联的 character_card id
    state_json      TEXT DEFAULT '{}',             -- 会话级配置（文风、开关等）
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_world_plugin ON sessions(world_plugin);
CREATE INDEX IF NOT EXISTS idx_sessions_branch_of ON sessions(branch_of);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);

-- ── 消息表 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,      -- user | assistant | system | tool
    turn_index      INTEGER NOT NULL DEFAULT 0,
    phase           TEXT DEFAULT '',    -- 产出阶段：dm/npc/world/narrator/style/var
    agent_id        TEXT DEFAULT '',    -- 产出本消息的 agent 标识
    tokens_used     INTEGER DEFAULT 0,  -- 本消息消耗 token 数（估算）
    completed_at    REAL,               -- 消息流式完成时间戳
    status          TEXT NOT NULL DEFAULT 'active', -- active | reverted
    created_at      REAL NOT NULL,
    updated_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(session_id, role);
CREATE INDEX IF NOT EXISTS idx_messages_phase ON messages(session_id, phase);

-- ── Part 表（来自 opencode Part 概念）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS message_parts (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL,
    type            TEXT NOT NULL,      -- 见 PartType 枚举
    content         TEXT DEFAULT '{}', -- JSON
    status          TEXT NOT NULL DEFAULT 'streaming', -- streaming | done | error
    agent           TEXT DEFAULT '',   -- 产出本 Part 的 Agent 名称
    sort_order      INTEGER DEFAULT 0,  -- 同消息内排序（越小越前）
    metadata        TEXT DEFAULT '{}', -- 扩展元数据 JSON（token_count/latency_ms 等）
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parts_message ON message_parts(message_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_parts_session_type ON message_parts(session_id, type);

-- ── 角色卡表 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS character_cards (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    schema_version  TEXT NOT NULL DEFAULT '4.0',
    data_json       TEXT NOT NULL DEFAULT '{}',
    character_name  TEXT DEFAULT '',   -- 反范式：角色名（避免解析 JSON 过滤）
    tier            INTEGER DEFAULT 1, -- 反范式：Anti-Feat 星级
    points          INTEGER DEFAULT 0, -- 反范式：当前积分/SP（方便直接查询）
    updated_at      REAL NOT NULL
);

-- ── 世界档案表 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS world_archives (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '{}',   -- JSON
    archive_type    TEXT NOT NULL DEFAULT 'lore', -- lore | npc | rule | setting
    world_key       TEXT DEFAULT '',
    time_flow_ratio REAL NOT NULL DEFAULT 1.0,
    created_at      REAL,
    updated_at      REAL NOT NULL
);

-- ── 章节树（支持分支，来自 pi JSONL 树思路）──────────────────────────────
CREATE TABLE IF NOT EXISTS chapters (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    parent_chapter_id   TEXT REFERENCES chapters(id),  -- NULL=主线第一章
    branch_label        TEXT,                           -- NULL=主线，否则=分支名
    chapter_index       INTEGER NOT NULL DEFAULT 0,     -- 本会话内的章节序号（1-based）
    start_message_id    TEXT REFERENCES messages(id),
    end_message_id      TEXT REFERENCES messages(id),
    summary             TEXT DEFAULT '',                -- ChroniclerAgent 生成的摘要
    key_events          TEXT DEFAULT '[]',              -- JSON 关键事件列表
    is_consolidated     INTEGER NOT NULL DEFAULT 0,     -- 是否已固化记忆
    turn_count          INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active', -- active | reverted
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapters_session ON chapters(session_id);

-- ── 记忆条目表 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_entries (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id          TEXT REFERENCES chapters(id),
    content             TEXT NOT NULL,
    embedding           BLOB,           -- 向量（float32 bytes）
    bigram_tokens       TEXT DEFAULT '[]',  -- JSON array
    graph_nodes         TEXT DEFAULT '[]',  -- JSON array（关联实体）
    tier                TEXT NOT NULL DEFAULT 'episodic',
                        -- episodic | semantic | core | working
    cognitive_partition TEXT NOT NULL DEFAULT 'objective_global',
                        -- character_pov | objective_global | world_state | relationship
    source_agent        TEXT DEFAULT '',
    importance          REAL NOT NULL DEFAULT 0.5,    -- 重要度 [0,1]，越高越优先召回
    access_count        INTEGER NOT NULL DEFAULT 0,   -- 被召回次数（遗忘曲线）
    last_accessed_at    REAL,                         -- 最近被召回的时间戳
    related_npcs        TEXT DEFAULT '[]',            -- JSON array：关联 NPC key 列表
    related_location    TEXT DEFAULT '',              -- 关联地点标识
    world_time          TEXT DEFAULT '',              -- 世界内时间（如"第3年春"）
    created_at          REAL NOT NULL,
    consolidated_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_entries(session_id, tier);

-- ── 骰子日志（结构化 + JSONL 文件双写）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS dice_log (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    message_id      TEXT,
    part_id         TEXT REFERENCES message_parts(id),  -- 关联的 Part（可 NULL）
    agent_id        TEXT DEFAULT '',                    -- 触发骰子的 Agent 名称
    pool            INTEGER NOT NULL,
    threshold       INTEGER NOT NULL DEFAULT 8,
    rolls           TEXT NOT NULL DEFAULT '[]',  -- JSON
    net             INTEGER NOT NULL,
    verdict         TEXT NOT NULL,               -- success|failure|botch|critical
    attribute       TEXT DEFAULT '',
    skill           TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    input_json      TEXT DEFAULT '{}',           -- 调用时的原始参数 JSON
    result_json     TEXT NOT NULL DEFAULT '{}',  -- 完整 DiceRollResult JSON
    referenced      INTEGER NOT NULL DEFAULT 0,  -- 是否被叙事引用（0/1）
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dice_session ON dice_log(session_id);

-- ── 事件日志（SSE Last-Event-ID 补偿）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_log (
    id              TEXT PRIMARY KEY,   -- BusEvent.id（UUID）
    session_id      TEXT NOT NULL,
    type            TEXT NOT NULL,
    data_json       TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventlog_session ON event_log(session_id, created_at);

-- ── 角色快照（分支保存点）— 06-data-model.md §3.3 ─────────────────────────
CREATE TABLE IF NOT EXISTS character_snapshots (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id      TEXT REFERENCES messages(id),
    chapter_id      TEXT REFERENCES chapters(id),
    snapshot_json   TEXT NOT NULL DEFAULT '{}',  -- 角色卡完整 JSON 快照
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_session ON character_snapshots(session_id, created_at);

-- ── NPC 角色档案（跨章节复用）— 06-data-model.md §4 ──────────────────────
CREATE TABLE IF NOT EXISTS npc_profiles (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,               -- 唯一标识符，如 "shopkeeper_a"
    name            TEXT NOT NULL,
    profile_json    TEXT NOT NULL DEFAULT '{}',  -- 完整 NPC 描述（外观/性格/关系）
    world_key       TEXT NOT NULL DEFAULT '',    -- 世界键（全局模板 NPC，06-data-model.md §4）
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_session_key ON npc_profiles(session_id, key);
-- 全局 NPC 模板唯一约束（world_key + key），仅对非空 world_key 生效（06-data-model.md §3.2）
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_world_key ON npc_profiles(world_key, key) WHERE world_key != '';

-- ── NPC 状态（会话内动态变化）— 06-data-model.md §4.2 ────────────────────
CREATE TABLE IF NOT EXISTS session_npc_states (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    npc_id          TEXT NOT NULL REFERENCES npc_profiles(id) ON DELETE CASCADE,
    state_json      TEXT NOT NULL DEFAULT '{}',  -- 当前血量/好感度等动态状态
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_state_session ON session_npc_states(session_id, npc_id);

-- ── 向量索引元数据 — 06-data-model.md §5.4 ───────────────────────────────
CREATE TABLE IF NOT EXISTS vector_index_meta (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    index_type      TEXT NOT NULL DEFAULT 'flat',  -- flat | hnsw | ivf
    dimension       INTEGER NOT NULL DEFAULT 1536,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    last_rebuilt_at REAL,
    created_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vector_meta_session ON vector_index_meta(session_id);

-- ── 章节锚点表 — 每回合写入 turn_summary + state_delta（02-system-architecture.md §8）─
CREATE TABLE IF NOT EXISTS chapter_anchors (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id      TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    turn_index      INTEGER NOT NULL DEFAULT 0,
    turn_summary    TEXT NOT NULL DEFAULT '',        -- 本回合叙事摘要（≤100字）
    state_delta     TEXT NOT NULL DEFAULT '{}',      -- 本回合状态变化 JSON
    narrative_text  TEXT NOT NULL DEFAULT '',        -- 本回合完整叙事（冗余，供回放）
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anchors_session ON chapter_anchors(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_anchors_chapter ON chapter_anchors(chapter_id);

-- ── 迁移版本记录表 — 记录每条 MIGRATION_PATCHES_SQL 的执行状态 ──────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,  -- 单调递增，1-based
    description     TEXT NOT NULL DEFAULT '',
    applied_at      REAL NOT NULL,
    checksum        TEXT DEFAULT ''       -- 补丁 SQL 的 MD5（可选校验）
);

-- ── 全局世界模板（不绑定 session）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worlds (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    world_plugin TEXT NOT NULL DEFAULT 'crossover',
    description  TEXT DEFAULT '',
    created_at   REAL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worlds_plugin ON worlds(world_plugin);

-- ── 世界档案条目（属于全局世界，不绑定 session）─────────────────────────────
CREATE TABLE IF NOT EXISTS world_archive_entries (
    id           TEXT PRIMARY KEY,
    world_id     TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    title        TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '{}',
    archive_type TEXT NOT NULL DEFAULT 'lore',
    created_at   REAL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_entries_world ON world_archive_entries(world_id);

-- ── 全局人物模板（不绑定 session）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS character_templates (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    world_plugin   TEXT NOT NULL DEFAULT 'crossover',
    data_json      TEXT NOT NULL DEFAULT '{}',
    schema_version TEXT NOT NULL DEFAULT '4',
    created_at     REAL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_char_templates_plugin ON character_templates(world_plugin);

-- ── 全局 NPC 模板（不绑定 session）──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS npc_templates (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    key          TEXT NOT NULL UNIQUE,
    world_plugin TEXT NOT NULL DEFAULT 'crossover',
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at   REAL,
    updated_at   REAL NOT NULL
);

-- ── 全局物品模板（不绑定 session）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS item_templates (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    item_type    TEXT NOT NULL DEFAULT 'equipment',
    world_plugin TEXT NOT NULL DEFAULT 'crossover',
    data_json    TEXT NOT NULL DEFAULT '{}',
    created_at   REAL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_templates_type ON item_templates(item_type);

-- ── 全局提示词模板（分 Agent 管理）──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompt_templates (
    id         TEXT PRIMARY KEY,
    agent      TEXT NOT NULL,
    label      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_agent ON prompt_templates(agent);

-- ── GraphRAG 记忆节点三套存储同步状态（memory/extractor.py 写入补偿）──────────
CREATE TABLE IF NOT EXISTS node_sync_status (
    novel_id        TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    sqlite_written  INTEGER NOT NULL DEFAULT 0,
    graph_written   INTEGER NOT NULL DEFAULT 0,
    vector_written  INTEGER NOT NULL DEFAULT 0,
    synced          INTEGER NOT NULL DEFAULT 0,   -- 1=三套存储均落地
    retry_count     INTEGER NOT NULL DEFAULT 0,
    updated_at      REAL,
    PRIMARY KEY (novel_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_node_sync_pending ON node_sync_status(novel_id, synced);
"""

# ── 迁移补丁（ALTER TABLE 兼容已存在数据库）─────────────────────────────────
MIGRATION_PATCHES_SQL = [
    # sessions 表新字段
    "ALTER TABLE sessions ADD COLUMN branch_label TEXT",
    "ALTER TABLE sessions ADD COLUMN fork_from_msg TEXT",
    "ALTER TABLE sessions ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN character_id TEXT",
    # messages 表新字段
    "ALTER TABLE messages ADD COLUMN phase TEXT DEFAULT ''",
    "ALTER TABLE messages ADD COLUMN agent_id TEXT DEFAULT ''",
    "ALTER TABLE messages ADD COLUMN tokens_used INTEGER DEFAULT 0",
    "ALTER TABLE messages ADD COLUMN completed_at REAL",
    # message_parts 表新字段
    "ALTER TABLE message_parts ADD COLUMN sort_order INTEGER DEFAULT 0",
    "ALTER TABLE message_parts ADD COLUMN metadata TEXT DEFAULT '{}'",
    # chapters 表新字段
    "ALTER TABLE chapters ADD COLUMN chapter_index INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chapters ADD COLUMN key_events TEXT DEFAULT '[]'",
    "ALTER TABLE chapters ADD COLUMN title TEXT DEFAULT ''",
    # memory_entries 表新字段（08-memory-system.md 高级字段）
    "ALTER TABLE memory_entries ADD COLUMN importance REAL NOT NULL DEFAULT 0.5",
    "ALTER TABLE memory_entries ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE memory_entries ADD COLUMN last_accessed_at REAL",
    "ALTER TABLE memory_entries ADD COLUMN related_npcs TEXT DEFAULT '[]'",
    "ALTER TABLE memory_entries ADD COLUMN related_location TEXT DEFAULT ''",
    "ALTER TABLE memory_entries ADD COLUMN world_time TEXT DEFAULT ''",
    # dice_log 表新字段（06-data-model.md 审计字段）
    "ALTER TABLE dice_log ADD COLUMN part_id TEXT",
    "ALTER TABLE dice_log ADD COLUMN agent_id TEXT DEFAULT ''",
    "ALTER TABLE dice_log ADD COLUMN input_json TEXT DEFAULT '{}'",
    "ALTER TABLE dice_log ADD COLUMN referenced INTEGER NOT NULL DEFAULT 0",
    # character_cards 反范式查询列
    "ALTER TABLE character_cards ADD COLUMN character_name TEXT DEFAULT ''",
    "ALTER TABLE character_cards ADD COLUMN tier INTEGER DEFAULT 1",
    "ALTER TABLE character_cards ADD COLUMN points INTEGER DEFAULT 0",
    # npc_profiles 全局化：world_key 列（允许 NPC 跨 session 共享，06-data-model.md §4）
    # session_id 保留（会话内覆写优先），world_key 提供全局模板键
    "ALTER TABLE npc_profiles ADD COLUMN world_key TEXT DEFAULT ''",
    # memory_entries cognitive_partition 列（08-memory-system.md §2.4 认知分区）
    "ALTER TABLE memory_entries ADD COLUMN cognitive_partition TEXT DEFAULT 'objective_local'",
    # npc_profiles 全局唯一索引（world_key != '' 时，world_key+key 唯一，06-data-model.md §3.2）
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_world_key ON npc_profiles(world_key, key) WHERE world_key != ''",
    # messages 消息类型与内容字段（11-api-design.md §3 对齐，N44/差距009/013）
    "ALTER TABLE messages ADD COLUMN content TEXT DEFAULT ''",
    "ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'player_action'",
    # chapter_anchors 表（02-system-architecture.md §8，S2 每回合 anchor 写入，N66）
    """CREATE TABLE IF NOT EXISTS chapter_anchors (
        id              TEXT PRIMARY KEY,
        session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        chapter_id      TEXT REFERENCES chapters(id) ON DELETE SET NULL,
        message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
        turn_index      INTEGER NOT NULL DEFAULT 0,
        turn_summary    TEXT NOT NULL DEFAULT '',
        state_delta     TEXT NOT NULL DEFAULT '{}',
        narrative_text  TEXT NOT NULL DEFAULT '',
        created_at      REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_anchors_session ON chapter_anchors(session_id, turn_index)",
    "CREATE INDEX IF NOT EXISTS idx_anchors_chapter ON chapter_anchors(chapter_id)",

    # ── character_cards 缺失列（06-data-model.md §2.2，N80）──────────────────
    "ALTER TABLE character_cards ADD COLUMN world_plugin TEXT DEFAULT ''",
    "ALTER TABLE character_cards ADD COLUMN tier_sub TEXT DEFAULT 'M'",
    "ALTER TABLE character_cards ADD COLUMN hp_overall INTEGER DEFAULT 0",
    "ALTER TABLE character_cards ADD COLUMN created_at REAL",
    # character_cards 查询索引
    "CREATE INDEX IF NOT EXISTS idx_cards_session ON character_cards(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_cards_name ON character_cards(character_name)",

    # ── session_npc_states 关系字段（06-data-model.md §3.2 §8.2，N81）─────────
    "ALTER TABLE session_npc_states ADD COLUMN affinity REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE session_npc_states ADD COLUMN trust REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE session_npc_states ADD COLUMN relationship_type TEXT DEFAULT 'neutral'",
    "ALTER TABLE session_npc_states ADD COLUMN knowledge_of_protagonist TEXT DEFAULT '{}'",
    "ALTER TABLE session_npc_states ADD COLUMN last_seen_turn INTEGER DEFAULT 0",

    # ── chapters 时间字段（06-data-model.md §4.2，N82）──────────────────────
    "ALTER TABLE chapters ADD COLUMN world_time_start TEXT DEFAULT ''",
    "ALTER TABLE chapters ADD COLUMN world_time_end TEXT DEFAULT ''",
    "ALTER TABLE chapters ADD COLUMN consolidated_at REAL",
    # chapters 查询索引
    "CREATE INDEX IF NOT EXISTS idx_chapters_parent ON chapters(parent_chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_branch ON chapters(session_id, branch_label)",

    # ── vector_index_meta 缺失列（06-data-model.md §5.2，N83）───────────────
    "ALTER TABLE vector_index_meta ADD COLUMN index_path TEXT DEFAULT ''",

    # ── 缺失复合/分析索引（06-data-model.md §1.2 §5.2 §6.1，N84）────────────
    "CREATE INDEX IF NOT EXISTS idx_parts_session_created ON message_parts(session_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_chapter ON memory_entries(chapter_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_entries(session_id, importance DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_partition ON memory_entries(session_id, cognitive_partition)",
    "CREATE INDEX IF NOT EXISTS idx_dice_verdict ON dice_log(session_id, verdict)",

    # ── 全局世界/人物/资产/提示词表（首页枢纽系统）──────────────────────────
    """CREATE TABLE IF NOT EXISTS worlds (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        world_plugin TEXT NOT NULL DEFAULT 'crossover',
        description  TEXT DEFAULT '',
        created_at   REAL,
        updated_at   REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_worlds_plugin ON worlds(world_plugin)",
    """CREATE TABLE IF NOT EXISTS world_archive_entries (
        id           TEXT PRIMARY KEY,
        world_id     TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
        title        TEXT NOT NULL DEFAULT '',
        content      TEXT NOT NULL DEFAULT '{}',
        archive_type TEXT NOT NULL DEFAULT 'lore',
        created_at   REAL,
        updated_at   REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_world_entries_world ON world_archive_entries(world_id)",
    """CREATE TABLE IF NOT EXISTS character_templates (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        world_plugin   TEXT NOT NULL DEFAULT 'crossover',
        data_json      TEXT NOT NULL DEFAULT '{}',
        schema_version TEXT NOT NULL DEFAULT '4',
        created_at     REAL,
        updated_at     REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_char_templates_plugin ON character_templates(world_plugin)",
    """CREATE TABLE IF NOT EXISTS npc_templates (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        key          TEXT NOT NULL UNIQUE,
        world_plugin TEXT NOT NULL DEFAULT 'crossover',
        profile_json TEXT NOT NULL DEFAULT '{}',
        created_at   REAL,
        updated_at   REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS item_templates (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        item_type    TEXT NOT NULL DEFAULT 'equipment',
        world_plugin TEXT NOT NULL DEFAULT 'crossover',
        data_json    TEXT NOT NULL DEFAULT '{}',
        created_at   REAL,
        updated_at   REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_item_templates_type ON item_templates(item_type)",
    """CREATE TABLE IF NOT EXISTS prompt_templates (
        id         TEXT PRIMARY KEY,
        agent      TEXT NOT NULL,
        label      TEXT NOT NULL,
        content    TEXT NOT NULL DEFAULT '',
        enabled    INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at REAL,
        updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_prompt_templates_agent ON prompt_templates(agent)",
]


# messages.phase 枚举（06-data-model.md §2.2，与 03-agent-system.md 四阶段对齐）
class MessagePhase:
    """messages 表 phase 列的合法值（字符串枚举，SQLite 不强制，代码约定）。"""
    P1   = "p1"    # DM/Rules/NPC/World 决策阶段（输入分析、骰子判断、NPC 响应）
    P3   = "p3"    # Narrator 叙事生成阶段（流式正文输出）
    P4   = "p4"    # Var/Chronicler 结算阶段（变量变更、章节归档）
    META = "meta"  # 系统元消息（compaction 摘要、章节标记、权限事件等）

    ALL = (P1, P3, P4, META)


# Part 类型枚举（供代码引用）
class PartType:
    NARRATIVE       = "narrative"        # 正文叙事（流式）
    DM_NOTE         = "dm_note"          # DM 校验注释
    DICE_ROLL       = "dice_roll"        # 骰子结果
    STATE_PATCH     = "state_patch"      # 变量变化（TavernCommand / VM）
    SYSTEM_GRANT    = "system_grant"     # 系统奖励
    NPC_ACTION      = "npc_action"       # NPC 行为
    WORLD_EVENT     = "world_event"      # 世界演变
    SKILL_LOAD      = "skill_load"       # 技能按需加载记录
    CHAPTER_END     = "chapter_end"      # 章节固化标记
    PERMISSION_ASK  = "permission_ask"   # 权限询问（ask 模式）
    COMPACTION      = "compaction"       # 会话压缩摘要
    ACTION_OPTIONS  = "action_options"   # LLM 生成的行动选项（review 模式）
    # P3 新增（03-agent-system.md / 07-tool-registry.md）
    REASONING       = "reasoning"        # Agent 推理过程（plan/review 模式可见）
    TEXT            = "text"             # 纯文本 Part（TextPart，设计文档要求）
    TOOL_CALL       = "tool_call"        # 工具调用记录（调用前 emit）
    TOOL_RESULT     = "tool_result"      # 工具返回结果（调用后 emit）
    VAR_DIFF        = "var_diff"         # 变量差分（VarAgent 结算后 emit）
