# 设计符合度审计 — 维度 B06「数据模型」

> 审计基准日期：2026-06-03
> 设计权威：`docs/design/06-data-model.md`
> 核对实现：`backend/db/schema.py`、`backend/db/character_v4.py`、`backend/memory/schema.py`
> 子代理：B06（只读）

---

## 1. Session/Message/Part 三层模型

### §1.2 sessions 表
- 设计要求：列 `id / world_plugin(NOT NULL) / agent_profile / mode / branch_of(REFERENCES sessions ON DELETE SET NULL) / branch_label / title / created_at / updated_at / state_json(NOT NULL DEFAULT '{}') / is_archived / character_id`，三个索引。
- 实现状态：完整（有偏离）
- 证据：`backend/db/schema.py:12-30`
- 差距：① `world_plugin` 实现加了 `DEFAULT 'crossover'`（设计仅 NOT NULL）；② `branch_of` 实现为 `REFERENCES sessions(id)`，缺设计的 `ON DELETE SET NULL`（`schema.py:17`）；③ `state_json` 缺 NOT NULL（`schema.py:24`）；④ 实现多出 `fork_from_msg`（`:19`）、`status`（`:21`）两列（设计未列）。三索引齐全（`:28-30`）。
- 处置：补/改设计文档（把 `fork_from_msg`/`status` 与默认值差异写入设计）

### §1.2 sessions.mode 语义
- 设计要求：`mode` = `play / sandbox / replay`（`06-data-model.md:51`）。
- 实现状态：偏离
- 证据：`backend/db/schema.py:16` 注释 `play | plan | review`
- 差距：列存在（C6 关注的 `sessions.mode` 列实际存在，无缺列问题），但枚举取值与设计不同（sandbox/replay vs plan/review）。`branch_of` 列同样实际存在（`:17`），C6 担心的两列均无缺失。
- 处置：补/改设计文档（统一 mode 取值定义）

### §1.2 messages 表
- 设计要求：列 `id / session_id / role(CHECK IN user,assistant,system,tool) / turn_index / phase(CHECK IN p1,p3,p4,meta) / agent_id / status / created_at / completed_at / updated_at / tokens_used`。
- 实现状态：完整（有偏离）
- 证据：`backend/db/schema.py:33-48`
- 差距：① `role` 无 CHECK 约束（`:36`）；② `phase` 无 CHECK 且默认 `''`、注释列举 `dm/npc/world/narrator/style/var`（`:38`）与设计 p1/p3/p4/meta 不一致（虽 `MessagePhase` 类 `:469-476` 定义了 p1/p3/p4/meta）；③ 迁移额外加 `content`、`message_type` 两列（`:354-355`，设计未列）。
- 处置：补/改设计文档 + 评估是否补 CHECK

### §1.2 message_parts 表
- 设计要求：列 `id / message_id / session_id / type / content(NOT NULL DEFAULT '{}') / status(NOT NULL DEFAULT 'streaming' CHECK IN streaming,done,error) / sort_order / created_at / metadata(NOT NULL DEFAULT '{}')`，三索引。
- 实现状态：完整（有偏离）
- 证据：`backend/db/schema.py:51-65`、索引 `:64-65` + `:399`
- 差距：① `content/metadata` 缺 NOT NULL（`:56,60`）；② `status` 无 CHECK（`:57`）；③ 实现多出 `agent`（`:58`）、`updated_at`（`:62`）两列。设计的 `idx_parts_session_id(session_id, created_at)` 由迁移 `idx_parts_session_created` 提供（`:399`）。
- 处置：补/改设计文档

### §1.3 PartType 枚举（17 种）
- 设计要求：11 核心 + 6 扩展 = 17 种 Part 类型。
- 实现状态：完整
- 证据：`backend/db/schema.py:480-498`
- 差距：无。17 种逐一匹配（narrative…compaction 11 种 + action_options/reasoning/text/tool_call/tool_result/var_diff 6 种）。
- 处置：无需动作

---

## 2. 角色卡 v4 Schema

### §2.1 角色卡 JSON Schema（核心结构）— 🔴 最大偏离
- 设计要求：`required = [meta, identity, attributes, body_parts, energy_pools, loadout, psychology, economy]`；`attributes` 用 `schema(standard_10d/cultivation_8d) + values` 由 WorldPlugin 定义维度；`body_parts` 六部位（head/torso/left_arm/right_arm/left_leg/right_leg）含 `hp_max/hp_current/armor/status_effects`；`energy_pools` 数组（minItems 1）；`loadout`（passive_abilities/power_sources/application_techniques/equipped）；`psychology`（ocean/stress/morale/clarity/emotion_state/traumas/beliefs/core_values/behavior_patterns/emotional_triggers）；`economy`（points/badges/tier/tier_sub/cash）；`relationships` 为对象数组（npc_id/name/type/affinity/trust/tags…）；`achievements` 数组。
- 实现状态：偏离（严重）
- 证据：`backend/db/character_v4.py:12-123`（`CHARACTER_V4_SCHEMA`）
- 差距：实现的 v4 实质是设计所称的"v3 旧结构"，几乎全面不符：
  - 顶层 `required` 仅 `["name","world_plugin"]`，**无 `meta/identity/body_parts/energy_pools/loadout/psychology/economy` 强制**（`:17`）。
  - `attributes` 为固定 5 维 `strength/dexterity/intelligence/will/empathy`（1-10），**无 `schema`/`values` 体系切换**，无 standard_10d/cultivation_8d（`:27-38`）。
  - 身体用扁平 `max_hp/current_hp`（`:39-46`）+ `physical_state.body_parts` 仅 **4 部位 head/chest/arms/legs 且为 hp_ratio**（`:51-62`）——设计要求 6 部位、hp_max/hp_current/armor/status_effects。
  - **完全缺 `energy_pools`**（设计 minItems≥1 必填）。
  - **完全缺 `loadout`**（实现仍用 `skills` dict + `inventory` array，`:73-91`）——设计 §8 迁移明确要求 inventory→loadout 拆分。
  - `mental_state` 仅 stress/morale/trauma_level（`:63-72`），**缺 OCEAN/clarity/emotion_state/traumas[]/beliefs/core_values/behavior_patterns/emotional_triggers**。
  - `relationships` 为对象 `{npc_name:{affinity,known_secrets}}`（`:92-102`）——设计为数组且含 type/trust/tags/last_interaction_turn，**缺 trust 等字段**。
  - `economy` = points/currency/special_tokens（`:103-112`）——**缺 badges/tier/tier_sub**，`cash` 改名 `currency`。
  - `meta` = created_at/session_id/writing_style（`:113-121`）——设计要求 schema_version/world_plugin/card_id/created_at/updated_at。
  - **无 `achievements`、无 `identity`（name 扁平）**。
- 处置：补实现（角色卡 v4 重构对齐设计）或重大改设计（若决定保留简化卡，须把设计 §2.1 整体下调到实现版本）

### §8.4 角色卡迁移器 CharacterCardMigrator
- 设计要求：`_migrate_3_to_4` 把 inventory→loadout 并生成 6 部位 body_parts（`06-data-model.md:2051-2076`）。
- 实现状态：偏离
- 证据：`backend/db/character_v4.py:227-319`（`migrate_v3_to_v4`）
- 差距：实现的 v3→v4 迁移产出仍是上面的简化卡——`inventory` 保留（未生成 loadout，`:311`）、body_parts 仍是 4 部位 hp_ratio（`:301-308`）、无 energy_pools。与设计迁移目标结构不一致。
- 处置：补实现（随 §2.1 一并对齐）

### §2.2 character_cards 表
- 设计要求：列 `id / session_id / version(DEFAULT '4.0.0') / card_json / character_name(NOT NULL) / world_plugin(NOT NULL) / tier(DEFAULT 0) / tier_sub(DEFAULT '') / points / hp_overall(REAL DEFAULT 1.0) / created_at / updated_at`，索引 idx_cards_session/idx_cards_name。
- 实现状态：部分（列名/类型偏离）
- 证据：`backend/db/schema.py:68-77`、迁移 `:343-345,372-378`
- 差距：① 列名不符：设计 `version`→实现 `schema_version`（`:71`）、设计 `card_json`→实现 `data_json`（`:72`）；② `hp_overall` 实现为 **INTEGER DEFAULT 0**（`:374`），设计为 **REAL DEFAULT 1.0**（类型+默认值偏离）；③ `tier` 默认 1（设计 0）、`tier_sub` 默认 'M'（设计 ''）；④ `character_name/world_plugin/tier_sub/created_at` 经迁移补齐（`:343,372-375`）。索引齐全（`:377-378`）。
- 处置：补/改设计文档（统一列名）+ 修正 hp_overall 类型

### §2.2 character_snapshots 表
- 设计要求：列 `id / card_id(REFERENCES character_cards ON DELETE CASCADE) / chapter_id / snapshot_json / created_at`。
- 实现状态：偏离
- 证据：`backend/db/schema.py:169-176`
- 差距：实现以 `session_id`（+`message_id`）为锚，**无 `card_id` 外键**（设计要求关联 character_cards.id）。键设计不同。
- 处置：补/改设计文档（说明快照按 session+message 而非 card 锚定）

---

## 3. 世界档案 Schema

### §3.2 world_archives 表
- 设计要求：列 `id / session_id / world_key / archive_json / current_location_id / world_time_str / elapsed_seconds(REAL) / created_at / updated_at`（承载单一世界状态档案）。
- 实现状态：偏离
- 证据：`backend/db/schema.py:80-90`
- 差距：实现把该表改造为"逐条 lore 条目"表：列为 `title / content / archive_type(lore|npc|rule|setting) / world_key / time_flow_ratio`。**缺设计的 `archive_json / current_location_id / world_time_str / elapsed_seconds`**；`archive_json`→`content`。语义从"整世界档案"变为"档案条目"。
- 处置：补/改设计文档（与实现的条目化模型对齐）

### §3.2 npc_profiles 表（C6 关注 .key 列）
- 设计要求：列 `id / world_key(NOT NULL) / npc_name(NOT NULL) / profile_json / created_at / updated_at`；唯一索引 `idx_npc_world_name(world_key, npc_name)`（全局复用，无 session 绑定）。
- 实现状态：偏离
- 证据：`backend/db/schema.py:180-192`、迁移 `:348,352`
- 差距：① 实现新增 `session_id(NOT NULL)`（`:182`）——设计为全局表无 session；② 设计 `npc_name`→实现拆为 `key` + `name` 两列（`:183-184`），唯一约束基于 `key` 而非 `npc_name`：`idx_npc_session_key(session_id,key)`（`:190`）、`idx_npc_world_key(world_key,key) WHERE world_key!=''`（`:192`）。C6 提到的 **`npc_profiles.key` 列实际存在**，是设计里没有、实现新增的列；设计的 `idx_npc_world_name` 未按原名/原列实现。
- 处置：补/改设计文档（把 key/session_id 模型写入设计）

### §3.2 session_npc_states 表
- 设计要求：复合主键 `(session_id, npc_id)`；列含 `affinity(INTEGER) / trust(INTEGER DEFAULT 50) / relationship_type / knowledge_of_protagonist(DEFAULT '[]') / last_seen_turn / state_json`。
- 实现状态：部分（类型/默认偏离）
- 证据：`backend/db/schema.py:195-202`、迁移 `:381-385`
- 差距：① 主键用独立 `id` + `UNIQUE(session_id,npc_id)`（`:196,202`），非设计复合主键；② `affinity/trust` 实现为 **REAL**（`:381-382`），设计 INTEGER；③ `trust` 默认 **0.0**，设计 DEFAULT 50；④ `knowledge_of_protagonist` 默认 **'{}'**（对象），设计 '[]'（数组）。列经迁移补齐。
- 处置：补/改设计文档 + 修正 trust 默认值与类型

---

## 4. 章节树结构

### §4.2 chapters 表
- 设计要求：列 `id / session_id / parent_chapter_id(REFERENCES chapters ON DELETE SET NULL) / branch_label / chapter_index(DEFAULT 1) / start_message_id / end_message_id / summary / key_events(DEFAULT '[]') / is_consolidated / world_time_start / world_time_end / created_at / consolidated_at`，三索引。
- 实现状态：完整（有偏离）
- 证据：`backend/db/schema.py:93-108`、迁移 `:327-329,388-393`
- 差距：① `parent_chapter_id` 缺 `ON DELETE SET NULL`（`:96`）；② `chapter_index DEFAULT 0`（`:98`），设计 DEFAULT 1；③ 实现多出 `turn_count`（`:104`）、`status`（`:105`）、`title`（迁移 `:329`）、`updated_at`（`:107`）；④ `key_events/world_time_start/world_time_end/consolidated_at` 经迁移补齐（`:328,388-390`）。三索引齐全（`:109,392-393`）。
- 处置：补/改设计文档（记录额外列）

---

## 5. 记忆表

### §5.2 memory_entries 表
- 设计要求：列含 `embedding(BLOB) / bigram_tokens / graph_nodes / tier(CHECK IN episodic,semantic,core,working) / cognitive_partition(CHECK IN character_pov,objective_global,npc_pov) / importance / related_npcs / related_location / world_time / access_count / last_accessed_at / consolidated_at`，四索引。
- 实现状态：部分（约束/枚举偏离）
- 证据：`backend/db/schema.py:112-133`、迁移 `:331-336,350,400-402`
- 差距：① `tier` 无 CHECK（`:120`）；② `cognitive_partition` 无 CHECK，且取值不一致——主建表注释列 `character_pov|objective_global|world_state|relationship`（`:123`，含设计没有的 world_state/relationship，缺 npc_pov），迁移列默认 **'objective_local'**（`:350`）与主建表默认 'objective_global'（`:122`）**自相矛盾**，且 objective_local 不在设计枚举内；③ 实现多出 `source_agent`（`:124`）。其余列经迁移补齐，四索引齐全（`:134,400-402`）。
- 处置：补实现（统一 cognitive_partition 默认值/枚举，补 CHECK）+ 改设计文档对齐取值

### §5.2 vector_index_meta 表
- 设计要求：`session_id PRIMARY KEY / index_type(DEFAULT 'faiss_flat') / dimension(DEFAULT 768) / total_vectors / index_path / last_rebuilt_at`。
- 实现状态：部分（列名/默认偏离）
- 证据：`backend/db/schema.py:205-214`、迁移 `:396`
- 差距：① 主键用独立 `id` + `UNIQUE(session_id)`（`:206,214`），设计 session_id 为 PK；② 设计 `total_vectors`→实现 `entry_count`（`:209`，列名偏离）；③ `dimension` 默认 **1536**（`:209`），设计 768；④ `index_type` 默认 'flat'（设计 'faiss_flat'）。`index_path` 经迁移补齐（`:396`）。
- 处置：补/改设计文档（统一列名 entry_count/total_vectors，默认维度）

### §5 记忆架构整体 — GraphRAG 平行实现
- 设计要求：§5 记忆基于 `memory_entries` SQL 表 + 向量(FAISS/Annoy via vector_index_meta) + BM25 + graph_nodes 字段。
- 实现状态：偏离
- 证据：`backend/memory/schema.py:16-67`（`NodeType` 8 类 / `RelationType` / `MemoryNode`）、`backend/memory/graph.py`（NetworkX）、`backend/memory/vector.py`（ChromaDB）
- 差距：实际记忆系统是另一套 GraphRAG 架构（8 类节点 EVENT/RULE/THREAD/SYNOPSIS/CHARACTER/LOCATION/REFLECTION/POV_MEMORY + 关系边，持久化用 NetworkX JSON + ChromaDB），与设计 06 §5 的 `memory_entries` 表模型并行存在。`memory_entries` 表虽建在 schema 中，但召回链路走 `memory/`（非该表）。此设计属 `08-memory-system.md` 范畴，相对 06 为偏离。
- 处置：补/改设计文档（06 §5 与 08 记忆系统对齐，标明 memory_entries 表的实际用途）

### node_sync_status 表 — 🔴 代码引用但 schema 缺失
- 设计要求：06 未定义此表（属 08-memory-system.md 同步状态）。
- 实现状态：缺失
- 证据：引用于 `backend/memory/rollback.py:67,154`（`DELETE FROM node_sync_status`）、`backend/memory/extractor.py:341`（`UPDATE node_sync_status SET retry_count...`）；全仓 `CREATE TABLE` 仅见 `schema.py`，**无任何 `node_sync_status` 建表语句**。
- 差距：代码对 `node_sync_status` 执行 DELETE/UPDATE，但该表在 `schema.py` 及全仓未被创建——运行到这些路径会触发 `no such table`。证实 C6 的关注：node_sync_status 表不存在。
- 处置：补实现（在 schema.py 增加 node_sync_status 建表）

---

## 6. 骰子日志

### §6.1 dice_log 表
- 设计要求：列 `id / session_id / part_id(REFERENCES message_parts) / timestamp(REAL) / input_json / result_json / verdict(CHECK IN success,failure,botch,critical) / agent_id / referenced`，索引 idx_dice_session/idx_dice_verdict。
- 实现状态：部分（列名/约束偏离 + 大量扩展列）
- 证据：`backend/db/schema.py:137-155`、迁移 `:338-341,403`
- 差距：① 设计 `timestamp`→实现用 `created_at`（`:154`，无 timestamp 列，列名偏离）；② `verdict` 无 CHECK（`:147`）；③ 实现多出扁平列 `message_id / pool / threshold / rolls / net / attribute / skill / reason`（`:140,143-150`，设计未列，与 result_json 内容重叠）；④ `part_id/agent_id/input_json/referenced` 经迁移补齐（`:338-341`）。两索引齐全（`:156,403`）。
- 处置：补/改设计文档（记录扁平列与 timestamp→created_at）

---

## 7. 系统配置表

### §7.1/§7.2 agents.json / mcp.json
- 设计要求：LLM 路由配置与 MCP 配置以 JSON 文件存在。
- 实现状态：N/A（非 DB schema，本分片不评判文件内容）
- 证据：—
- 差距：属配置文件层，非数据库 schema 范畴；本审计聚焦 schema.py。
- 处置：无需动作（交由配置相关分片）

### 超出设计 06 的额外表（首页枢纽系统）
- 设计要求：06 未定义这些表。
- 实现状态：偏离（实现新增）
- 证据：`backend/db/schema.py` — `event_log(:159)` / `chapter_anchors(:217)` / `schema_version(:232)` / `worlds(:240)` / `world_archive_entries(:251)` / `character_templates(:263)` / `npc_templates(:275)` / `item_templates(:286)` / `prompt_templates(:298)`
- 差距：9 张表设计 06 未提（部分注明来自 02-system-architecture.md §8 / 首页枢纽系统）。属实现新增，非 06 范畴。
- 处置：补/改设计文档（在 06 或对应设计文档登记这些表）

---

## 8. 数据迁移策略

### §8.1 Alembic 迁移
- 设计要求：用 Alembic（`alembic.ini` + `alembic/versions/001_…002_…`）做版本迁移，`init_db` 调 `command.upgrade(head)`。
- 实现状态：偏离
- 证据：全仓无 alembic 文件（Glob `**/alembic*` 0 命中）；实现改用手写 `MIGRATION_PATCHES_SQL` 列表（`backend/db/schema.py:312-465`）+ `schema_version` 表（`:232-237`）记录补丁版本。
- 差距：未采用 Alembic，改为幂等 ALTER TABLE 补丁清单 + 自管版本表。迁移结果可达成（向后兼容只增不删），但工具链与设计完全不同。
- 处置：补/改设计文档（把迁移方案改记为"手写补丁 + schema_version"，或补 Alembic）

### §8.3 向后兼容（只增不删 / 默认值安全）
- 设计要求：新版本只加字段、新增字段须有合理 DEFAULT。
- 实现状态：完整
- 证据：`backend/db/schema.py:312-465` 全为 `ADD COLUMN`/`CREATE … IF NOT EXISTS`，均带 DEFAULT。
- 差距：无（原则被遵守，仅实现手段非 Alembic）。
- 处置：无需动作

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 5 | sessions 表、message_parts 表、messages 表、PartType 枚举、chapters 表、§8.3 向后兼容 |
| 部分 | 5 | character_cards 表、session_npc_states 表、memory_entries 表、vector_index_meta 表、dice_log 表 |
| 偏离 | 9 | 角色卡 v4 JSON Schema🔴、CharacterCardMigrator、character_snapshots、world_archives、npc_profiles、sessions.mode 语义、记忆 GraphRAG 平行架构、超 06 额外表、Alembic 迁移 |
| 缺失 | 1 | node_sync_status 表🔴（代码引用但未建表） |

> 注：表头"完整"实列 6 项（含 §8.3），统计以条目为准。

**整体符合度估计：约 50%**

- 表层骨架（sessions/messages/message_parts/chapters/PartType/记忆与骰子索引）基本对齐，列大多齐全（多靠 `MIGRATION_PATCHES_SQL` 补齐），但普遍缺 CHECK 约束、外键 `ON DELETE` 子句，并有列名差异（version/schema_version、card_json/data_json、total_vectors/entry_count、timestamp/created_at）。
- **核心数据结构「角色卡 v4」严重偏离**：实现的 `character_v4.py` 实质是设计所称的 v3 简化卡——缺 `energy_pools / loadout / identity / achievements`，body_parts 4 部位(hp_ratio) vs 设计 6 部位(hp_max/hp_current)，psychology 缺 OCEAN/clarity/traumas 等，economy 缺 badges/tier/tier_sub。这是最高优先级差距。

---

### 设计了但 schema/实现里缺失或严重偏离的表/列（重点）

**缺失（代码引用但无建表）：**
- `node_sync_status` 表 — `rollback.py`/`extractor.py` 对其 DELETE/UPDATE，但全仓无 CREATE TABLE。

**设计要求但实现完全没有的角色卡字段（character_v4.py）：**
- `energy_pools`（设计必填 minItems≥1）、`loadout`（passive_abilities/power_sources/application_techniques/equipped）、`identity` 对象、`achievements` 数组、psychology 的 `ocean/clarity/emotion_state/traumas/beliefs/core_values/behavior_patterns/emotional_triggers`、economy 的 `badges/tier/tier_sub`、meta 的 `schema_version/world_plugin/card_id`。

**设计有、实现改名或改语义的列：**
- character_cards：`version`→`schema_version`、`card_json`→`data_json`、`hp_overall` REAL/1.0→INTEGER/0。
- vector_index_meta：`total_vectors`→`entry_count`、维度 768→1536。
- dice_log：`timestamp`→`created_at`。
- npc_profiles：设计 `npc_name`→实现 `key`+`name`（C6 关注的 `.key` 列系实现新增）。
- world_archives：`archive_json/current_location_id/world_time_str/elapsed_seconds` 全缺，改为 `content/archive_type/title/time_flow_ratio`。

**C6 关注点结论：** `sessions.mode`、`sessions.branch_of`、`npc_profiles.key` 三列**均实际存在**（无缺列）；唯独 `node_sync_status` **表确实缺失**。
