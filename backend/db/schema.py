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
    plugin_key      TEXT NOT NULL DEFAULT 'crossover',   -- 驱动行为的插件键
    world_id        TEXT REFERENCES worlds(id) ON DELETE SET NULL,  -- 关联的世界内容（可空）
    agent_profile   TEXT NOT NULL DEFAULT 'play',
    mode            TEXT NOT NULL DEFAULT 'play'
                        CHECK(mode IN ('play', 'plan', 'review')),  -- play | plan | review
    branch_of       TEXT REFERENCES sessions(id) ON DELETE SET NULL,  -- 分支来源（NULL=主线）
    branch_label    TEXT,                          -- 分支显示名称（NULL=主线）
    fork_from_msg   TEXT REFERENCES messages(id) ON DELETE SET NULL,  -- 分叉起点消息 ID
    title           TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'deleted', 'archived')), -- active | deleted | archived
    is_archived     INTEGER NOT NULL DEFAULT 0
                        CHECK(is_archived IN (0, 1)),  -- 0=正常 1=已归档
    character_id    TEXT,                          -- 关联的 character_card id
    state_json      TEXT NOT NULL DEFAULT '{}',    -- 会话级配置（文风、开关等）
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_plugin_key ON sessions(plugin_key);
CREATE INDEX IF NOT EXISTS idx_sessions_world_id ON sessions(world_id);
CREATE INDEX IF NOT EXISTS idx_sessions_branch_of ON sessions(branch_of);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);

-- ── 消息表 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL
                        CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    turn_index      INTEGER NOT NULL DEFAULT 0,
    phase           TEXT DEFAULT '',    -- 产出阶段：dm/npc/world/narrator/style/var
    agent_id        TEXT DEFAULT '',    -- 产出本消息的 agent 标识
    tokens_used     INTEGER DEFAULT 0,  -- 本消息消耗 token 数（估算）
    completed_at    REAL,               -- 消息流式完成时间戳
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'reverted')), -- active | reverted
    content         TEXT DEFAULT '',
    message_type    TEXT DEFAULT 'player_action',
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
    content         TEXT NOT NULL DEFAULT '{}', -- JSON
    status          TEXT NOT NULL DEFAULT 'streaming'
                        CHECK(status IN ('streaming', 'done', 'error')), -- streaming | done | error
    agent           TEXT DEFAULT '',   -- 产出本 Part 的 Agent 名称
    sort_order      INTEGER DEFAULT 0,  -- 同消息内排序（越小越前）
    metadata        TEXT NOT NULL DEFAULT '{}', -- 扩展元数据 JSON（token_count/latency_ms 等）
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parts_message ON message_parts(message_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_parts_session_type ON message_parts(session_id, type);
CREATE INDEX IF NOT EXISTS idx_parts_session_created ON message_parts(session_id, created_at DESC);

-- ── 角色卡表 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS character_cards (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    schema_version  TEXT NOT NULL DEFAULT '4.0',
    data_json       TEXT NOT NULL DEFAULT '{}',
    character_name  TEXT NOT NULL DEFAULT '',  -- 反范式：角色名
    plugin_key      TEXT NOT NULL DEFAULT '',  -- 反范式：所属插件键
    tier            INTEGER NOT NULL DEFAULT 1
                        CHECK(tier >= 0 AND tier <= 10),
    tier_sub        TEXT NOT NULL DEFAULT 'M'
                        CHECK(tier_sub IN ('L', 'M', 'U', '')),
    points          INTEGER NOT NULL DEFAULT 0
                        CHECK(points >= 0),
    hp_overall      REAL NOT NULL DEFAULT 1.0,
    created_at      REAL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_session ON character_cards(session_id);
CREATE INDEX IF NOT EXISTS idx_cards_name ON character_cards(character_name);

-- ── 世界档案表 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS world_archives (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '{}',   -- JSON
    archive_type    TEXT NOT NULL DEFAULT 'lore'
                        CHECK(archive_type IN ('lore', 'npc', 'rule', 'setting', 'opening_scene')),
    world_key       TEXT NOT NULL DEFAULT '',
    time_flow_ratio REAL NOT NULL DEFAULT 1.0,
    trigger_keywords TEXT DEFAULT '',
    created_at      REAL,
    updated_at      REAL NOT NULL
);

-- ── 章节树（支持分支，来自 pi JSONL 树思路）──────────────────────────────
CREATE TABLE IF NOT EXISTS chapters (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    parent_chapter_id   TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    branch_label        TEXT,
    chapter_index       INTEGER NOT NULL DEFAULT 0,
    start_message_id    TEXT REFERENCES messages(id) ON DELETE SET NULL,
    end_message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    title               TEXT DEFAULT '',
    summary             TEXT DEFAULT '',
    key_events          TEXT DEFAULT '[]',
    is_consolidated     INTEGER NOT NULL DEFAULT 0
                            CHECK(is_consolidated IN (0, 1)),
    turn_count          INTEGER NOT NULL DEFAULT 0,
    world_time_start    TEXT DEFAULT '',
    world_time_end      TEXT DEFAULT '',
    consolidated_at     REAL,
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active', 'reverted')),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chapters_session ON chapters(session_id);
CREATE INDEX IF NOT EXISTS idx_chapters_parent ON chapters(parent_chapter_id);
CREATE INDEX IF NOT EXISTS idx_chapters_branch ON chapters(session_id, branch_label);

-- ── 记忆条目表 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_entries (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id          TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    content             TEXT NOT NULL,
    embedding           BLOB,
    bigram_tokens       TEXT DEFAULT '[]',
    graph_nodes         TEXT DEFAULT '[]',
    tier                TEXT NOT NULL DEFAULT 'episodic'
                        CHECK(tier IN ('episodic', 'semantic', 'core', 'working')),
    cognitive_partition TEXT NOT NULL DEFAULT 'objective_global',
    source_agent        TEXT DEFAULT '',
    importance          REAL NOT NULL DEFAULT 0.5,
    access_count        INTEGER NOT NULL DEFAULT 0,
    last_accessed_at    REAL,
    related_npcs        TEXT DEFAULT '[]',
    related_location    TEXT DEFAULT '',
    world_time          TEXT DEFAULT '',
    created_at          REAL NOT NULL,
    consolidated_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_entries(session_id, tier);
CREATE INDEX IF NOT EXISTS idx_memory_chapter ON memory_entries(chapter_id);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_entries(session_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_partition ON memory_entries(session_id, cognitive_partition);

-- ── 骰子日志（结构化 + JSONL 文件双写）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS dice_log (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    message_id      TEXT,
    part_id         TEXT REFERENCES message_parts(id) ON DELETE SET NULL,
    agent_id        TEXT DEFAULT '',
    pool            INTEGER NOT NULL,
    threshold       INTEGER NOT NULL DEFAULT 8,
    rolls           TEXT NOT NULL DEFAULT '[]',
    net             INTEGER NOT NULL,
    verdict         TEXT NOT NULL
                        CHECK(verdict IN ('success', 'failure', 'botch', 'critical')),
    attribute       TEXT DEFAULT '',
    skill           TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    input_json      TEXT DEFAULT '{}',
    result_json     TEXT NOT NULL DEFAULT '{}',
    referenced      INTEGER NOT NULL DEFAULT 0
                        CHECK(referenced IN (0, 1)),
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dice_session ON dice_log(session_id);
CREATE INDEX IF NOT EXISTS idx_dice_verdict ON dice_log(session_id, verdict);

-- ── 事件日志（SSE Last-Event-ID 补偿）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_log (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    type            TEXT NOT NULL,
    data_json       TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventlog_session ON event_log(session_id, created_at);

-- ── 角色快照（分支保存点）──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS character_snapshots (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    chapter_id      TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    snapshot_json   TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_session ON character_snapshots(session_id, created_at);

-- ── NPC 角色档案（跨章节复用）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS npc_profiles (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,
    name            TEXT NOT NULL,
    profile_json    TEXT NOT NULL DEFAULT '{}',
    world_key       TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_session_key ON npc_profiles(session_id, key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_world_key ON npc_profiles(world_key, key) WHERE world_key != '';

-- ── NPC 状态（会话内动态变化）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS session_npc_states (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    npc_id          TEXT NOT NULL REFERENCES npc_profiles(id) ON DELETE CASCADE,
    state_json      TEXT NOT NULL DEFAULT '{}',
    affinity        REAL NOT NULL DEFAULT 0.0,
    trust           REAL NOT NULL DEFAULT 0.0,
    relationship_type TEXT DEFAULT 'neutral',
    knowledge_of_protagonist TEXT DEFAULT '{}',
    last_seen_turn  INTEGER DEFAULT 0,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_state_session ON session_npc_states(session_id, npc_id);

-- ── 向量索引元数据 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vector_index_meta (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    index_type      TEXT NOT NULL DEFAULT 'flat',
    dimension       INTEGER NOT NULL DEFAULT 1536,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    index_path      TEXT DEFAULT '',
    last_rebuilt_at REAL,
    created_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vector_meta_session ON vector_index_meta(session_id);

-- ── 章节锚点表 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chapter_anchors (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id      TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    turn_index      INTEGER NOT NULL DEFAULT 0,
    turn_summary    TEXT NOT NULL DEFAULT '',
    state_delta     TEXT NOT NULL DEFAULT '{}',
    narrative_text  TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anchors_session ON chapter_anchors(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_anchors_chapter ON chapter_anchors(chapter_id);

-- ── 迁移版本记录表 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    description     TEXT NOT NULL DEFAULT '',
    applied_at      REAL NOT NULL,
    checksum        TEXT DEFAULT ''
);

-- ── 全局世界（纯内容容器，不绑定 session）────────────────────────────────
CREATE TABLE IF NOT EXISTS worlds (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT DEFAULT '',
    created_at   REAL,
    updated_at   REAL NOT NULL
);

-- ── 世界档案条目（属于全局世界）─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS world_archive_entries (
    id           TEXT PRIMARY KEY,
    world_id     TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    title        TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '{}',
    archive_type TEXT NOT NULL DEFAULT 'lore',
    trigger_keywords TEXT DEFAULT '',
    created_at   REAL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_entries_world ON world_archive_entries(world_id);

-- ── 全局人物模板（不绑定 session）────────────────────────────────────────
CREATE TABLE IF NOT EXISTS character_templates (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    plugin_key     TEXT NOT NULL DEFAULT 'crossover',
    data_json      TEXT NOT NULL DEFAULT '{}',
    schema_version TEXT NOT NULL DEFAULT '4',
    created_at     REAL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_char_templates_plugin ON character_templates(plugin_key);

-- ── 全局 NPC 模板（不绑定 session）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS npc_templates (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    key          TEXT NOT NULL UNIQUE,
    plugin_key   TEXT NOT NULL DEFAULT 'crossover',
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at   REAL,
    updated_at   REAL NOT NULL
);

-- ── 全局物品模板（不绑定 session）────────────────────────────────────────
CREATE TABLE IF NOT EXISTS item_templates (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    item_type    TEXT NOT NULL DEFAULT 'equipment',
    plugin_key   TEXT NOT NULL DEFAULT 'crossover',
    data_json    TEXT NOT NULL DEFAULT '{}',
    created_at   REAL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_templates_type ON item_templates(item_type);

-- ── 全局提示词模板（分 Agent 管理）──────────────────────────────────────
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

-- ── GraphRAG 记忆节点同步状态 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS node_sync_status (
    novel_id        TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    sqlite_written  INTEGER NOT NULL DEFAULT 0,
    graph_written   INTEGER NOT NULL DEFAULT 0,
    vector_written  INTEGER NOT NULL DEFAULT 0,
    synced          INTEGER NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    updated_at      REAL,
    PRIMARY KEY (novel_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_node_sync_pending ON node_sync_status(novel_id, synced);
"""

# 清空迁移补丁——DB 已重建，无需增量迁移
MIGRATION_PATCHES_SQL: list[str] = []


# messages.phase 枚举
class MessagePhase:
    """messages 表 phase 列的合法值（字符串枚举，SQLite 不强制，代码约定）。"""
    P1   = "p1"
    P3   = "p3"
    P4   = "p4"
    META = "meta"

    ALL = (P1, P3, P4, META)


# Part 类型枚举（供代码引用）
class PartType:
    NARRATIVE       = "narrative"
    DM_NOTE         = "dm_note"
    DICE_ROLL       = "dice_roll"
    STATE_PATCH     = "state_patch"
    SYSTEM_GRANT    = "system_grant"
    NPC_ACTION      = "npc_action"
    WORLD_EVENT     = "world_event"
    SKILL_LOAD      = "skill_load"
    CHAPTER_END     = "chapter_end"
    PERMISSION_ASK  = "permission_ask"
    COMPACTION      = "compaction"
    ACTION_OPTIONS  = "action_options"
    REASONING       = "reasoning"
    TEXT            = "text"
    TOOL_CALL       = "tool_call"
    TOOL_RESULT     = "tool_result"
    VAR_DIFF        = "var_diff"
