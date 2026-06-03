# conf_b08 · 设计符合度审计 — 08 记忆系统（Memory System）

> 审计范围：`docs/design/08-memory-system.md` vs `backend/memory/`（全部 12 文件）+ 上下游接线
> 审计基准日期：2026-06-03
> 关键结论先行：**默认环境（pyproject 未声明 chromadb）下，`_engine_available=False`，召回走 SQLite fallback。四层中实际生效的只有「认知分区权重」一层（叠加在 LIKE 关键词检索上）。向量层、真·Bigram 层、图扩散层在默认环境全部失活。** 即便补装 chromadb，生产热路径也从不向图/向量库写入数据（见 NEW-B08-04/05），向量检索仍返回空、回落 SQLite。

---

### §1.2 记忆分层（working / episodic / semantic / procedural）
- 设计要求：四层 tier —— working（最近20条turn，不embedding）、episodic（事件碎片，有embedding，参与召回）、semantic（章节摘要/设定，永久）、procedural（技能规则，注入 system prompt，从 owned_items 派生）。
- 实现状态：偏离
- 证据：`backend/memory/schema.py:797`（tier 注释 `episodic | semantic | core | working`）、`backend/memory/adapter.py:187-268`（fallback 实际查 core/semantic/episodic/working 四层）。
- 差距：实现 tier 集合为 `working/episodic/semantic/core`，**用 `core` 取代了设计的 `semantic` 顶层、且完全没有 `procedural` 层**；owned_items → procedural 注入链路在 memory/ 内不存在。working 层在 fallback 中并非"最近20条turn"，而是查 `message_parts` 最近 N 条 narrative。
- 处置：补/改设计文档（tier 命名与 procedural 层已实质偏离，应改文档对齐 core 层；或补 procedural 实现）。

### §1.3 + §2 四层混合召回（总体）
- 设计要求：`recall()` 依次执行 视角过滤 → 向量召回(top_k*3) → Bigram召回 → 图扩散 → 认知权重 → 混合排序，返回 top_k。
- 实现状态：部分（仅 full 模式实现全链路；默认环境降级）
- 证据：`backend/memory/retriever.py:189-324` `hybrid_recall` 实现四级链路；但入口 `backend/memory/adapter.py:122-150` 在 `_engine_available` 为 False 或结果为空时回落 `_fallback_recall`。
- 差距：`hybrid_recall` 本身基本忠实设计（向量→词法→图扩散→认知权重→importance 重排）；但它仅在 full 模式被调用，且依赖图/向量库已被填充（实际从未填充，见 NEW-B08-04）。默认环境永远走 `_fallback_recall`（纯 SQLite LIKE）。
- 处置：补实现（修复生产写入链路，否则四级管线为空跑）。

### §2.1 向量语义层（weight=0.65）
- 设计要求：sentence-transformers 本地推理 + L2 归一化 + 余弦相似度 top_k*3；embedding 以 float32 BLOB 存 `memory_entries.embedding`，冷启动全量载入内存。
- 实现状态：偏离 + 默认失活
- 证据：`backend/memory/retriever.py:218-230`（向量经 `vector_manager.query` 走 ChromaDB/FAISS，**非** `memory_entries.embedding` BLOB）；`backend/utils/llm_client.py:97-109` embed 本地推理存在；`backend/memory/adapter.py:46-52`（full 模式硬要求 `chromadb` 可用）；`backend/pyproject.toml:24-26`（**依赖未声明 chromadb**）。
- 差距：①向量不存 SQLite BLOB（设计 §7 已承认改为 Chroma），但 §2.1「冷启动载入 `memory_entries.embedding`」描述与实现不符；②默认环境缺 chromadb → 整层不可用，`embed` 在 sentence-transformers 缺失时返回空向量（`llm_client.py:100-101`）。VECTOR_WEIGHT=0.65 实现一致（`retriever.py:60`）。
- 处置：补/改设计文档 + 补实现（pyproject 增加 chromadb 或显式声明 FAISS 后端）。

### §2.2 Bigram 词法层（weight=0.35）
- 设计要求：jieba 分词 + 字级 bigram + TF-IDF/BM25 风格评分，弥补向量对专名的语义漂移。
- 实现状态：偏离
- 证据：`backend/memory/retriever.py:74-124`（`build_bigram_units` + `compute_lexical_score`，bigram+jieba+整串，但评分是**最大匹配等级**而非 TF-IDF/BM25）；fallback 路径 `backend/memory/adapter.py:179-183` 仅用 `re.split` 取前3词元做 `LIKE` 匹配，**无 bigram、无 jieba、无 IDF**。
- 差距：full 模式的词法层用的是分级 max() 匹配权重（`LEXICAL_WEIGHTS`），与设计文档贴的 BM25 公式不同；且只对向量命中的节点二次打分（向量空则不触发）。默认环境完全没有 Bigram，退化为 LIKE 关键词。LEXICAL_WEIGHT=0.35 数值一致。
- 处置：补/改设计文档（明确实现为分级匹配而非 BM25）。

### §2.3 图扩散层（DIFFUSE_SCORE=0.45）
- 设计要求：NetworkX 有向图，对高分(>0.6)候选向邻居传播 0.45 比例分数；写入时建 same_chapter/same_npc/caused_by 边。
- 实现状态：部分 + 默认失活
- 证据：`backend/memory/graph.py:187-223` `get_neighbors` 一/多跳扩散实现；`backend/memory/retriever.py:274-305`（取前5种子，沿 involved_in/occurred_at/advances/related/caused_by 扩散，邻居固定 `GRAPH_DIFFUSE_SCORE=0.45`）。
- 差距：①实现是"对种子节点的邻居赋固定 0.45 分"，而非设计的"父分数×0.45 且取 max"（`retriever.py:304` 固定值，未乘父分）；②阈值 0.6 高分门槛未实现（直接取 top5 种子）；③边建立时机不符——同章节/同NPC自动连边在生产从不执行（仅 LLM extractor 的 relations 字段建边，而该 extractor 是死代码，见 NEW-B08-04）；④默认 fallback 无图。
- 处置：补/改设计文档 + 补实现（生产写入未建图，扩散层空跑）。

### §2.4 认知分区权重
- 设计要求：按 content_type 赋权（character_pov 1.25 / dialogue 1.15 / action_result 1.10 / objective_event 1.00 / objective_global 0.75 / system_info 0.60）。
- 实现状态：完整（这是默认环境唯一真正生效的一层）
- 证据：`backend/memory/retriever.py:20-37`（SCOPE_WEIGHTS + COGNITIVE_WEIGHTS 双表，数值与设计一致）；`backend/memory/retriever.py:262-265`（对 pov_memory 节点应用 scope 权重）；fallback 同样生效 `backend/memory/adapter.py:18-24` + `:220-225` + `:248-252`（按 `cognitive_partition` × importance 重排）。
- 差距：full 模式只对 `pov_memory` 节点套 scope 权重，非全类型；DB 实际枚举是 `character_pov/objective_global/world_state/relationship/objective_local`，与设计的 content_type 值域（dialogue/action_result/system_info）不同——实现做了两套表兼容。fallback 用的是 SCOPE 五档表。
- 处置：补/改设计文档（值域统一为 cognitive_partition 枚举）。

### §2.5 混合得分公式 + 时序分桶
- 设计要求：`raw = 0.65*vec + 0.35*bigram`，`boosted = raw + graph_boost`，`* cognitive_weight`；时序 `recency_bonus = 1/(1+days_ago*0.1)`，排序键含 recency。
- 实现状态：偏离
- 证据：`backend/memory/retriever.py:255-265`（`hybrid = 0.65*vec + 0.35*lexical`，再 `*(1+temporal_prio*0.05)`，再套 scope 权重）；`:309-311`（最后乘 `0.5+0.5*importance`）。
- 差距：实现用**时序分桶优先级离散加成**（`TEMPORAL_BUCKET_PRIORITY` current=5…future=0 × 0.05）替代设计的 `1/(1+days_ago*0.1)` 连续衰减；新增了 importance 乘数（设计 §2.5 无）；graph_boost 不是相加而是邻居独立成行。公式结构相近但细节不同。
- 处置：补/改设计文档。

### §3 viewer_agent 视角隔离
- 设计要求：5 种视角 `dm/npc/narrator/world/player`，各有 tier 白名单 + content_type 乘数 + npc_filter；`filter_by_viewer` 过滤候选集。
- 实现状态：偏离
- 证据：`backend/memory/retriever.py:160-182` `check_pov_visibility`（视角集为 `chronicler/dm/planner/protagonist/npc_*`，**与设计的 dm/npc/narrator/world/player 不一致**，且只做 pov_memory 节点的布尔可见性，无 tier 白名单、无 content_type 乘数）；fallback `backend/memory/adapter.py:169-174`（仅 world/rules/npc 限 `objective_global` 分区）。
- 差距：①视角枚举与设计完全不同（无 narrator/world/player；多出 chronicler/planner/protagonist/npc_<name>）；②设计的 `VIEWER_FILTERS`（tier 白名单 + 乘数表）整体未实现，退化为"pov_memory 是否可见"的单一布尔；③`MemoryAdapter.recall` 的 `viewer_agent` 默认 `narrator`，但 GET /memory 端点根本不传该参数（`sessions.py:1240-1245`），所以 API 层视角隔离不可用。
- 处置：补实现（视角隔离严重弱化）+ 改设计文档（对齐实际 agent 命名）。

### §4 记忆写入流水线（extract → embedding → 图关联 → 写库 → 固化）
- 设计要求：ChroniclerAgent 产出 → 后台 ExtractQueue（LLM 提取结构化事件）→ embedding 生成 → 图节点关联 → `INSERT OR IGNORE` memory_entries（tier=episodic）→ 固化压缩。
- 实现状态：偏离（生产路径用启发式正则，非 LLM；LLM 提取器为死代码）
- 证据：生产链 `var_agent.py:125` / `chronicler_agent.py:214` → `memory_adapter.enqueue_extraction`（`adapter.py:380-428`）→ `extract_queue.enqueue` → `extract_queue.py:100-180` `_process_task`，用 `CORE_KEYWORDS`/正则 `SEMANTIC_PATTERNS` 启发式分 tier 后 `INSERT OR IGNORE` SQLite（**无 LLM、无 embedding、无图**）。LLM 驱动的 `MemoryExtractor.extract_and_persist`（`extractor.py:136-176`）**全仓库无任何生产调用方**（仅 `engine.extract_sync` 调，自身也无人调）。
- 差距：设计的"LLM 提取结构化事件 + embedding + 图关联"三件套在生产从不发生；实际是关键词正则切段写 SQLite。embedding/图节点关联流水线对生产无效。
- 处置：补实现（接线 LLM extractor 或在文档中将启发式路径定为正式实现）。

### §4.2 MemoryManager 主类
- 设计要求：`MemoryManager` 类封装 recall/add_memory/固化/回滚，构造时载入 SentenceTransformer + GraphDiffusion。
- 实现状态：偏离
- 证据：实现无 `MemoryManager` 类；职责拆为 `MemoryEngine`（`engine.py:23`）门面 + `MemoryAdapter`（`adapter.py:104`）+ 各 manager 单例。
- 差距：类名/封装方式不同（设计 §6/§7 已部分承认），属可接受的结构演进，但 `add_memory` 在 adapter 中调 `_engine.graph_manager` / `_engine.vector_manager`（`adapter.py:370-371`）——`MemoryEngine` **无这两个属性**，且 `MemoryNode(id=..., type=..., metadata=...)`（`adapter.py:361-369`）与 schema 字段名（node_id/node_type）不符 → 该向量写入分支必抛异常被静默吞掉。
- 处置：补/改设计文档 + 修复 add_memory 的引擎写入分支（当前为永久失败的死分支）。

### §5 章节固化（Consolidation）
- 设计要求：三种触发（Chronicler 自动 / 手动 API / episodic>100 阈值）；流程 召回本章 episodic → LLM 摘要(<500字) → 升级 semantic → 原 episodic 标记 consolidated → 更新 chapters。
- 实现状态：部分
- 证据：`backend/memory/chapter_consolidator.py:27-88` `consolidate_chapter`（SQLite：标记 consolidated_at + 生成 semantic 条目，LLM 摘要 `_summarize:90-106`）；阈值触发 `:109-153` `auto_consolidate_if_needed`（>=100）；由 `extract_queue.py:182-194` 在每次提取后异步检查；Chronicler 自动触发 `chronicler_agent.py:255-260`；手动 API `sessions.py:1285-1293`。
- 差距：①存在**两个互相冲突的 `memory_consolidator` 单例**——`chapter_consolidator.py:157`（SQLite，生产用）与 `consolidator.py:159`（图/向量 synopsis 压缩，无人调用，死代码）；②手动 API 走 `adapter.consolidate_session`（按 importance 压最旧30%），与 chapter 级固化语义不同；③`_summarize` 硬编码 `provider="deepseek"`（`chapter_consolidator.py:100`），违反通用化；④不更新 `chapters.is_consolidated`（仅写 memory_entries），但 chronicler 另行更新 chapters。流程主干在，分散且有死实现。
- 处置：补实现（移除/合并死的 `consolidator.MemoryConsolidator`）+ 改文档。

### §6 记忆回滚（Rollback）
- 设计要求：删除目标章节之后的 memory_entries + chapters 行 + 清 working tier + 重建图 + 恢复 character 快照；文档 §6.2 已声明实际为 `MemoryRollback` 操作图谱节点。
- 实现状态：部分（图层可用，SQLite 层与同步表均失效）
- 证据：`backend/memory/rollback.py:16-76` `rollback_chapter` + `:113-163` `rollback_by_time` + `:78-111` `restore_character_node`，与文档 §6.2 对照表一致；接线 `sessions.py:993/1309/1315`。
- 差距：①`rollback.py:37`/`:129` `db = get_db()` 后调 `db._exec(...)`（`:66`/`:153`）——`get_db` 是 `@asynccontextmanager`（`connection.py:20-28`），返回的是上下文管理器对象，**无 `_exec` 方法**，必抛异常（被 `:70`/`:157` try 吞掉）；②`node_sync_status` 表全仓库无建表语句（仅此文件与 extractor 引用）→ 即便修了 db 用法，DELETE 也会因表不存在失败；③图节点删除 + 向量删除走 graph_manager/vector_manager 正常（`:53-58`）。所以回滚的**图谱删除有效，SQLite memory_entries 行与 chapters 行不删、同步状态清理空操作**。
- 处置：补实现（修 get_db 用法 + 建 node_sync_status 表，或删去对它的引用；补 memory_entries 行删除）。

### §7 数据结构与 DB Schema
- 设计要求：文档已大量声明"设计草案 vs 实现差异"（content_type→cognitive_partition、is_consolidated→consolidated_at、新增 bigram_tokens/graph_nodes/importance/access_count 等）。
- 实现状态：完整（文档已对齐实现）
- 证据：`backend/memory/schema.py`（此为图节点 MemoryNode，非表）；表结构与 `MemoryEntry` 由 `backend/db/` 提供（设计 §7 已注明实际路径 `backend/db/schema.py` 与 `backend/db/memory_entry.py`）。
- 差距：设计文档 §7 已诚实记录差异，DB schema 字段与文档贴的 SQL 基本一致；`access_count/last_accessed_at` 在 fallback 召回时确有更新（`adapter.py:449-467`）。`node_sync_status` 表是文档/实现都缺的隐性依赖（见 §6 与 NEW-B08-03）。
- 处置：无需动作（schema 主体）；node_sync_status 缺失另记为缺陷。

### §8 记忆 API（FastAPI 路由）
- 设计要求：文档已声明 `POST /recall` 未实装，实际用 `GET /memory`（参数 q/top_k/tier，无 viewer_agent）。固化/回滚端点存在。
- 实现状态：部分（文档已对齐）
- 证据：`sessions.py:1228-1261` `GET /memory`（与文档 §8 表格一致，确无 viewer_agent）；`:1264-1282` `POST /memory`；`:1285-1293` `POST /memory/consolidate`；`:1296-1315` `POST /memory/rollback`（参数 since/chapter，非设计的 confirm 防误删）。
- 差距：①设计的 `viewer_agent` 五视角在 API 层完全不可达（GET /memory 不收该参数）；②回滚端点无 `confirm=true` 防误操作护栏（设计 §8 强调），直接执行；③固化端点语义被 `consolidate_session`（importance 压缩）替代。
- 处置：补/改设计文档 + 补回滚 confirm 护栏。

### §9 性能与配置参数（MemoryConfig）
- 设计要求：`MemoryConfig` dataclass 统一管理 embedding_model/权重/阈值/缓存等；`use_openai_fallback`、`min_score_threshold=0.3`、`embedding_cache_size` 等。
- 实现状态：缺失（无集中配置类）
- 证据：参数散落各文件硬编码——`retriever.py:60-67`（VECTOR/LEXICAL/GRAPH/TEMPORAL 常数）、`chapter_consolidator.py:21`（阈值100）、`schema.py:222-232`（CONSOLIDATION_CONFIG 阈值10）、`extract_queue.py:212`（max_size=50）。
- 差距：无 `MemoryConfig` 类；`min_score_threshold=0.3`（低分过滤）未实现；OpenAI embedding 降级（设计 §4「降级 OpenAI text-embedding-3-small」）未实现，embed 失败直接返回空向量（`llm_client.py:100-101`）；embedding LRU 缓存未实现。设计 §5.1 的"event>10 压缩"与 §9「episodic>100 固化"两套阈值实现各取一处。
- 处置：补实现（集中配置）+ 改文档。

---

## 跨切片运行期核对（C5 已发现问题 × 设计承诺）

### NEW-B08-01 · `_EmbeddingClient` 无 `embed_batch`，全量提取器向量写入必失败
- 实现状态：缺失（设计 §4「embedding 批量生成」无法运行）
- 证据：`backend/memory/extractor.py:330` `await emb_client.embed_batch(texts)`；`backend/utils/llm_client.py:77-109` `_EmbeddingClient` **只有 `embed`，无 `embed_batch`**。
- 差距：调用即 AttributeError，被 `extractor.py:336-337` 吞掉 → 向量从不写入。即便 LLM 提取器被接线（当前未接），向量层也写不进去。
- 处置：补实现 `embed_batch`（或改用循环 `embed`）。

### NEW-B08-02 · `get_db()` 误用为对象（extractor/rollback）
- 实现状态：缺失/偏离
- 证据：`backend/memory/extractor.py:313` `db = get_db()` 后 `db.upsert_node_sync(...)`（`:320`）；`backend/memory/rollback.py:37` `db = get_db()` 后 `db._exec(...)`（`:66`）。`get_db` 是 `@asynccontextmanager`（`connection.py:20`），无这些方法。对照正确用法 `chapter_consolidator.py:42`/`adapter.py:185` 均为 `async with get_db() as db`。
- 差距：extractor 的 `upsert_node_sync/mark_node_synced` 与 rollback 的 `_exec` 全部抛 AttributeError；extractor 中导致 `created_ids` 永远为空（图节点虽写入但函数报 0）；rollback 的 SQLite/同步清理为空操作。
- 处置：补实现（改 async with + 在 db 层实现 upsert_node_sync/mark_node_synced/_exec，或删除）。

### NEW-B08-03 · `node_sync_status` 表不存在
- 实现状态：缺失
- 证据：`node_sync_status` 仅在 `backend/memory/extractor.py:341`、`backend/memory/rollback.py:67/154` 出现，**无任何 CREATE TABLE**（grep 全 backend 仅此两文件）。
- 差距：设计 §4 流水线「Step C: SQLite node_sync_status 记录同步状态」依赖该表实现"三套存储原子写入/补偿重试"，但表从未建立，相关 SQL 全部失败。三套存储一致性机制名存实亡。
- 处置：补实现（建表）或删除该机制并改文档。

### NEW-B08-04 · LLM 提取器 + 图/向量写入在生产从不触发
- 实现状态：缺失（设计 §4 核心承诺落空）
- 证据：生产 enqueue → `extract_queue._process_task`（`extract_queue.py:100`，启发式正则写 SQLite）；`MemoryExtractor`（`extractor.py:130`）/`engine.extract_sync`（`engine.py:89`）/`consolidator.MemoryConsolidator`（`consolidator.py:28`，图 synopsis）**均无生产调用方**。`engine.enqueue_extraction`（`engine.py:58`）虽存在，但 `get_extract_queue()` 因 `memory/extract_queue.py` 未导出 `get_extract_queue`（`engine.py:14-20` ImportError 分支）回落到同一个启发式 ExtractQueue。
- 差距：图谱与向量库在生产热路径**永不被写入**。因此 full 模式的 `hybrid_recall` 即便启用，向量检索/图扩散也对空库操作，最终回落 SQLite。"四层混合召回"在生产退化为单层 SQLite 关键词召回 + 认知权重重排。
- 处置：补实现（将 LLM extractor 接入队列消费，或显式将启发式路径定为正式方案并重写设计 §2/§4）。

### NEW-B08-05 · 默认环境缺 chromadb → full 模式永不开启
- 实现状态：偏离
- 证据：`backend/memory/adapter.py:46-52`（full 模式 Phase1 要求 `sentence_transformers` **且** `chromadb`）；`backend/pyproject.toml:10-33` 依赖列表**无 chromadb**（仅 sentence-transformers/networkx/jieba）。
- 差距：默认安装下 `find_spec("chromadb")` 为 None → `_engine_available=False` → 所有召回走 `_fallback_recall`。设计 §1「直接复用…向量65%+Bigram35%+图扩散」在默认环境完全不生效。
- 处置：补实现（pyproject 增 chromadb，或将 vector_backend 默认切 FAISS 并声明 faiss-cpu 依赖）+ 改文档说明默认运行模式。

---

## 符合度小计

| 实现状态 | 计数 | 条目 |
|---|---|---|
| 完整 | 2 | §2.4 认知权重、§7 Schema |
| 部分 | 5 | §1.3/§2 总体、§2.3 图扩散、§5 固化、§6 回滚、§8 API |
| 偏离 | 7 | §1.2 分层、§2.1 向量、§2.2 Bigram、§2.5 公式、§3 viewer、§4.2 MemoryManager、NEW-B08-02/05 |
| 缺失 | 4 | §9 配置、NEW-B08-01、NEW-B08-03、NEW-B08-04 |

> 设计要求条目合计 18（13 个设计小节 + 5 个运行期核对）。
> **整体符合度估计 ≈ 35%**：核心算法管线（retriever 四级链路）代码存在且 §2.4 认知权重忠实，但默认环境降级 + 生产写入链路断裂（NEW-B08-04）使其大面积空跑；viewer_agent/MemoryManager/MemoryConfig 与设计实质偏离；回滚/提取存在 get_db 误用与缺表的运行期硬伤。

### 四层召回默认环境生效数（直接回答）
**默认环境（无 chromadb）下四层只有 1 层真正生效**：认知分区权重（叠加在 SQLite LIKE 关键词检索上）。向量语义层、真·Bigram 词法层、图扩散层全部失活——前者因缺 chromadb/sentence-transformers，后两者因图与向量库在生产热路径从不被写入（NEW-B08-04/05）。
