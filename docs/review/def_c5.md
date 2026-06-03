# 代码缺陷复审 — 分片 C5「记忆全栈」（def_c5.md）

> 复审基准日期：2026-06-03
> 范围：`backend/memory/*`（adapter / vector / engine / extract_queue / extractor / consolidator / retriever / rollback / chapter_consolidator / schema / graph），并交叉核实 `backend/utils/llm_client.py`、`backend/db/queries.py`、`backend/db/connection.py`、`backend/db/schema.py`。
> 行级证据均以当前文件实际内容为准。

---

## 一、旧报告条目重新判定（STUB-R05~R08 / STUB-02 / R-M12/M13 / R-D11/D12）

### STUB-R05 · consolidator 依赖 utils.llm_client，语义压缩是否可用
- 状态：✅已修复
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/memory/consolidator.py:80,100-112`；`backend/utils/llm_client.py:116-129`
- 证据：`from utils.llm_client import get_llm_client, get_embedding_client` 现可成功导入；`llm = get_llm_client(); synopsis_content = await llm.chat(...)` 真正驱动 LLM 生成章节摘要，`_LLMClient.chat` 底层接 `agents.llm.llm_complete`；LLM 失败时回退拼接（`consolidator.py:113-115`）。语义压缩链路完整可用。
- 修复方向：无需动作（事件级 `event_to_synopsis` 压缩已工作）。

### STUB-R06 · extractor 依赖 utils.llm_client / get_embedding_client / db.queries
- 状态：🔄已变化（import 已修，但运行期两处必崩 → 见 NEW-C5-01 / NEW-C5-02）
- 类别：stub / degradation
- 严重度：🔴核心
- 位置：`backend/memory/extractor.py:224-225,310-313,330,320,333-334,340-343`
- 证据：`from utils.llm_client import get_llm_client`（224）与 `from db.queries import get_db`（311）现已能导入，`_llm_extract` 的 LLM 提取本身可运行。但持久化阶段彻底坏：①`embeddings = await emb_client.embed_batch(texts)`（330）调用了 `_EmbeddingClient` **并不存在**的方法（该类仅有 `embed`，见 `llm_client.py:97`）；②`db = get_db()`（313）把 `@asynccontextmanager`（`connection.py:20-28`）当成对象，随后 `db.upsert_node_sync(...)`（320）、`db._exec(...)`（341）、`db.mark_node_synced(...)`（334）全是不存在的方法；③这些写的 `node_sync_status` 表在 `schema.py` 中根本未建。Step A 异常→`created_ids` 永远为空；Step B 整段向量写入抛异常被吞。
- 修复方向：给 `_EmbeddingClient` 补 `embed_batch`；用 `async with get_db() as db:` 正确取连接并改写 SQL（或新增带 `upsert_node_sync` 等方法的 DB wrapper）；在 schema 补 `node_sync_status` 表。

### STUB-R07 · retriever.hybrid_recall 向量步依赖 get_embedding_client
- 状态：✅已修复（import 与依赖均可用）
- 类别：stub
- 严重度：🟡降级
- 位置：`backend/memory/retriever.py:208,219-227`
- 证据：`from utils.llm_client import get_embedding_client`（208）可导入；`query_embedding = await emb_client.embed(query_text)` 调用的 `embed`（单数）真实存在（`llm_client.py:97`），向量检索→Bigram→图扩散→重打分管线在依赖齐全时完整运行；向量失败有 try/except 降级（229-230）。
- 修复方向：无需动作（但向量失败时无词法兜底，另见 NEW-C5-04）。

### STUB-R08 · rollback 依赖 db.queries.get_db 是否仍 ImportError
- 状态：🔄已变化（ImportError 消失，但 get_db 误用 → 同步状态清理静默失败）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/memory/rollback.py:36-37,64-71,127-129,151-158`
- 证据：`from db.queries import get_db`（36）不再报错。但 `db = get_db()`（37）同样把异步上下文管理器当对象，后续 `db._exec("DELETE FROM node_sync_status ...")`（66-69）调用不存在的方法，被 try/except 捕获仅记 warning（70-71）。图/向量删除在此之前完成且正常，故回滚主体可用，但 `node_sync_status` 清理永远失败（且该表本就不存在）。
- 修复方向：改用 `async with get_db() as db: await db.execute("DELETE FROM node_sync_status ...")`；同步状态表需先建表，否则此清理无意义可删除。

### STUB-02 · ChromaDB/sentence-transformers 缺失 → 关键词召回；vector.py 抽象基类 NotImplementedError
- 状态：🔄已变化（vector.py 已非纯桩，但仍受可选依赖门控）
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/memory/vector.py:21-46,53-202,209-311,333-346`；`backend/memory/adapter.py:44-52,152-315`
- 证据：`VectorStore` 基类的 `NotImplementedError`（24-46）只是抽象接口，`ChromaVectorStore`（53-202）与 `FAISSVectorStore`（209-311）均有完整实现，`VectorStoreManager.get` 还做了 Chroma→FAISS 降级（339-345）。但全量引擎仍由 `adapter._try_load_full_engine` 在 `sentence_transformers`/`chromadb` 任一缺失时整体禁用（`adapter.py:47-50`），降级到 `_fallback_recall` 的 SQLite `memory_entries` 关键词召回（`adapter.py:152-315`）。graph/vector 版 `hybrid_recall` 本身无词法-only 兜底。
- 修复方向：保留双轨；将向量层的可选依赖在文档/health 端点中明确标注（`get_engine_status` 已具备）。

### R-M12 · engine.enqueue_extraction 字段 vs extract_queue._process_task 期望字段
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`backend/memory/engine.py:68-87`；`backend/memory/extract_queue.py:107-111`
- 证据：`enqueue_extraction` 现写入 `session_id`/`narrative_text`/`user_input`/`source_agent`（77-87），与 `_process_task` 读取的 `task.get("session_id")`/`narrative_text`/`user_input`/`source_agent`（107-111）逐一对齐，代码注释也明示「对齐 _process_task 所需字段」。字段不匹配问题已消除。
- 修复方向：无需动作（但队列消费走 SQLite 启发式而非 LLM 图谱提取，见 NEW-C5-03）。

### R-M13 · schema CONSOLIDATION_CONFIG["synopsis_to_arc"] 是否有对应 consolidator 逻辑
- 状态：⚠️仍存在（死配置）
- 类别：dead
- 严重度：🟢次要
- 位置：`backend/memory/schema.py:228-231`；`backend/memory/consolidator.py:50,82`
- 证据：`consolidator.py` 只引用 `CONSOLIDATION_CONFIG["event_to_synopsis"]`（50、82），全仓无任何代码读取 `synopsis_to_arc`；`MemoryConsolidator` 仅实现 event→synopsis 一级压缩，没有 synopsis→arc 弧线摘要逻辑。
- 修复方向：实现 synopsis_to_arc 二级压缩，或从配置中删除该死项。

### R-D11 · engine get_extract_queue 符号缺失回退
- 状态：⚠️仍存在
- 类别：dead / degradation
- 严重度：🟡降级
- 位置：`backend/memory/engine.py:14-20`；`backend/memory/extract_queue.py:211-212`
- 证据：`extract_queue.py` 仅导出实例 `extract_queue`（212），**未定义** `get_extract_queue`；故 `from memory.extract_queue import get_extract_queue`（15）必抛 ImportError，恒走 except 分支 `from backend.memory.extract_queue import extract_queue`（18）。该回退依赖项目根（backend 的父目录）也在 `sys.path`，否则连 except 也会 ImportError 导致整个 `engine.py` 加载失败。
- 修复方向：在 `extract_queue.py` 直接定义 `def get_extract_queue(): return extract_queue`，删除脆弱的双重 import 回退。

### R-D12 · extract_queue 启发式分段（非 LLM）
- 状态：⚠️仍存在
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/memory/extract_queue.py:100-171,126-131`
- 证据：`_process_task` 用 `narrative_text.split("\n")` 分段（121）、`CORE_KEYWORDS` 关键词命中判 tier（126-127,139）、正则 `SEMANTIC_PATTERNS`（128-131）抽实体，写入 SQLite `memory_entries`；全程无 LLM 参与。与 `extractor.py` 的 LLM 8 类节点提取是两套不相交逻辑。
- 修复方向：将队列消费切换为调用 `memory_extractor.extract_and_persist`，或明确文档化「队列=轻量 SQLite 兜底，图谱提取走 extract_sync」。

---

## 二、新发现问题（NEW-C5-xx）

### NEW-C5-01 · `_EmbeddingClient` 缺 `embed_batch`，extractor 批量向量写入必崩
- 状态：🆕新发现
- 类别：stub
- 严重度：🔴核心
- 位置：`backend/memory/extractor.py:330`；`backend/utils/llm_client.py:77-109`
- 证据：extractor 调 `await emb_client.embed_batch(texts)`，但 `_EmbeddingClient` 只实现了 `embed`（单数，97），无 `embed_batch` → `AttributeError`，导致提取的全部节点向量写入失败（被 336 行 except 吞，仅记 error）。
- 修复方向：在 `_EmbeddingClient` 增加 `async def embed_batch(self, texts) -> list[list[float]]`（可循环调用 `embed` 或批量 encode）。

### NEW-C5-02 · extractor/rollback 把 `get_db()` 当对象用，调用不存在的 DB 方法 + 缺表
- 状态：🆕新发现
- 类别：stub / dead
- 严重度：🔴核心
- 位置：`backend/memory/extractor.py:313,320,333-334,341,437,442`；`backend/memory/rollback.py:37,66`；`backend/db/connection.py:20-28`；`backend/db/schema.py`（无 node_sync_status）
- 证据：`get_db` 是 `@asynccontextmanager`，必须 `async with get_db() as db`。extractor/rollback 却 `db = get_db()` 后直接 `db.upsert_node_sync` / `db._exec` / `db._fetchone` / `db.mark_node_synced` —— 这些方法全仓**仅在这两文件被调用、从未被定义**（Grep 0 命中），且操作的 `node_sync_status` 表未在 schema 建立。运行期必抛 AttributeError（多被 try/except 吞）。
- 修复方向：统一 DB 访问方式；要么补一个带这些方法的 DB wrapper 单例，要么改写为 `async with get_db()` + 原生 SQL，并补建 `node_sync_status` 表。

### NEW-C5-03 · LLM 图谱提取链（extractor.py）在生产路径从未被触发
- 状态：🆕新发现
- 类别：unwired
- 严重度：🔴核心
- 位置：`backend/memory/engine.py:58-104`；`backend/memory/extract_queue.py:88-100`；`backend/memory/adapter.py:380-428`
- 证据：唯一调用 `memory_extractor.extract_and_persist` 的是 `engine.extract_sync`（注释自承「测试/调试用」，89-104）。生产入队 `enqueue_extraction` → 队列 `_worker` → `_process_task`（SQLite 正则启发式），绕过 LLM 图谱提取器；adapter 的 full 路径同样只 `enqueue_extraction`（395）。结果：graph/vector 图谱在正常运行中不会被 extractor 写入，retriever 的向量/图扩散召回缺乏数据来源。
- 修复方向：把队列消费指向 `memory_extractor`，或在 adapter full 模式下显式调用 `extract_sync`，明确两套存储的写入责任。

### NEW-C5-04 · retriever 无词法-only 兜底，Bigram 仅对向量命中重排
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`backend/memory/retriever.py:235-272`
- 证据：`scored_nodes` 完全来自 `vector_results` 的遍历（238），`compute_lexical_score` 只对向量命中的节点做重排（252）。当 embedding 不可用（`embed` 返回 `[]`→向量检索空）时 `scored_nodes=[]`、`seed_ids=[]`、图扩散也不触发，`recalled` 仅剩空，退化为「只有 core 层」。设计宣称的「四级召回（向量→Bigram→图→重排）」中 Bigram 并非独立检索通道。
- 修复方向：当向量为空时增加基于图节点 title/content 的 Bigram 词法独立召回通道。

### NEW-C5-05 · adapter.add_memory 的向量写入路径全错（属性/方法/构造参数均不符）
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要（被 try/except 吞，标记 non-critical）
- 位置：`backend/memory/adapter.py:358-373`；`backend/memory/engine.py:23-153`；`backend/memory/schema.py:88-115`
- 证据：`_engine.graph_manager.add_node(node)`（370）与 `_engine.vector_manager.add_node_async(node)`（371）——`MemoryEngine` 实例**没有** `graph_manager`/`vector_manager` 属性（仅模块级 import），`vector_manager` 也无 `add_node_async`；且 `MemoryNode(id=..., type=..., metadata=...)`（361-369）用了错误关键字（schema 字段为 `node_id`/`node_type`/`extra`）。整段必抛异常，被 372 行 `except` 当「非关键」吞掉，导致 add_memory 实际从不写向量。
- 修复方向：改用模块级 `graph_manager`/`vector_manager` 单例与正确的 `MemoryNode(node_id=..., node_type=..., extra=...)` 及 `upsert_node`。

### NEW-C5-06 · consolidator 冗余重复 import + synopsis 标题取 UUID 尾 4 位
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`backend/memory/consolidator.py:79,141,123`
- 证据：`_consolidate_events` 内 `from memory.vector import vector_manager` 在 79 行与 141 行重复导入；`title=f"第{chapter_id[-4:] ...}章摘要"`（123）当 chapter_id 为 UUID 时会生成「第xxxx章摘要」的无意义后缀。
- 修复方向：删除重复 import；用真实章节序号或 `chapter_id` 全量替代尾 4 位截断。

---

## 三、小计

| 类别 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 3 | STUB-R05、STUB-R07、R-M12 |
| 🔄已变化 | 3 | STUB-R06、STUB-R08、STUB-02 |
| ⚠️仍存在 | 3 | R-M13、R-D11、R-D12 |
| 🆕新发现 | 6 | NEW-C5-01 ~ NEW-C5-06 |

- 严重度分布（新发现）：🔴核心 3（NEW-C5-01/02/03）、🟡降级 1（NEW-C5-04）、🟢次要 2（NEW-C5-05/06）。
- **R05~R08 修复结论**：R05 真修复、R07 import 真修复；R06/R08 仅「import 不再报错」属**表面修复**，运行期因 `embed_batch` 缺失与 `get_db()` 误用（+ `node_sync_status` 缺表）仍会崩溃/静默失败。
