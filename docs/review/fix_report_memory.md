# 记忆子系统修复报告（fix_report_memory.md）

> 修复基准日期：2026-06-04
> 范围（仅允许编辑）：`backend/memory/**`、`backend/utils/llm_client.py`、`backend/db/queries.py`、记忆 API 路由（位于 `backend/api/routers/sessions.py` 的 `GET /sessions/{id}/memory`）。
> 验证：所有编辑文件 `py_compile` 通过；`import memory.*`（backend cwd）与 `import backend.memory.*`（repo root）均成功；无 chromadb/sentence-transformers 时可优雅降级（本环境恰好已安装，故 full mode 现已激活）。

---

## 结论表

| 项 | 状态 | 证据 (file:line) | 说明 |
|---|---|---|---|
| C5-03（LLM 提取链未接生产） | ✅ | `backend/memory/extract_queue.py:100-138`（`_process_task` 轨道A）、`:196-221`（`_run_llm_extraction`）；`backend/memory/adapter.py:393-449`（`enqueue_extraction` 带 messages/novel_id/world_key）；生产调用方 `backend/agents/var_agent.py:125`（已在仓内，调 `memory_adapter.enqueue_extraction`） | 队列消费者现双轨：轨道A 调 `memory_extractor.extract_and_persist` 写 NetworkX 图（+向量），轨道B 保留启发式 SQLite。`var_agent` 每回合的入队已携带完整 payload，**无需越权改动**即可触发 LLM 图谱提取。 |
| C5-04（retriever 无词法兜底） | ✅ | `backend/memory/retriever.py:295-363`（`_lexical_only_recall`）、`:430-447`（向量为空时触发） | 向量层不可用/为空时，直接扫描图中 recalled 类型节点用 Bigram 词法独立召回，叠加时序/分区/视角权重；图扩散仍以词法命中为种子。无 embedding 也能召回。 |
| C5-05（add_memory 向量写全错） | ✅ | `backend/memory/adapter.py:357-405`（`_write_node_to_engine`）、`:340-348`（调用点） | 改用模块级 `graph_manager`/`vector_manager` 单例；`MemoryNode(node_id=…, node_type=…, extra=…)` 字段名修正；embedding 经 `get_embedding_client().embed()` 生成后 `vector_manager.upsert_node`；图写入不依赖 chromadb，向量缺失时跳过不报错。 |
| D5（四层召回·生产写入接线） | ✅ | 同 C5-03 + `backend/memory/retriever.py:189-475`（四级链路：向量→词法→图扩散→认知/视角重排） | LLM 提取 + embedding + 图写入的生产路径已贯通（经队列轨道A）。图层在无 chromadb 时仍写入，配合 C5-04 词法兜底，四级召回不再空跑。 |
| D6（5 认知分区视角隔离） | ✅ | `backend/memory/retriever.py:69-150`（`VIEWER_PARTITION_FILTERS` + `viewer_allowed_partitions`/`partition_visible_to_viewer`/`viewer_partition_multiplier`）；应用点 `:451-459`（向量命中）、`:486-491`（图邻居）、`:340-360`（词法兜底）；fallback `backend/memory/adapter.py:169-180` | 5 分区 = `character_pov / objective_global / world_state / relationship / objective_local`。每视角定义可见分区集合 + 召回乘数；npc_<name> 归一到 npc 并叠加 `scope_owner` 过滤；全分区视角（chronicler/narrator）不过滤以保留默认行为。 |
| conf_b08（GET /memory 应用 viewer_agent） | ✅ | `backend/api/routers/sessions.py:1237-1287`（新增 `viewer_agent` query 参数，透传 `adapter.recall`，并按 5 分区白名单过滤结构化 entries，返回体含 `viewer_agent`） | 召回文本与结构化 entries 均按请求视角隔离。 |

### 顺带修复（在 `memory/**` 范围内，且为通过 import 验证所必需）
| 项 | 状态 | 证据 | 说明 |
|---|---|---|---|
| C5-02 / B08-02（rollback `get_db()` 误用） | ✅ | `backend/memory/rollback.py:9-32`（`_clear_sync_status` 用 `async with get_db()`）、`:55-73`、`:135-160` | 删除 `db = get_db()` + `db._exec(...)` 误用，改为正确异步上下文 + 批量 `DELETE`（`node_sync_status` 表已由 parent 建好）。 |
| R-D11（`get_extract_queue` 缺失致 import 脆弱） | ✅ | `backend/memory/extract_queue.py:225-227` | 直接定义 `get_extract_queue()`；消除 `engine.py:14-20` 依赖 `backend` 顶包的脆弱回退。**副作用（正向）**：本环境装有 chromadb/st，修复后 `MemoryEngine` 实例化成功，记忆引擎从 fallback 切到 **full mode**（`get_engine_status()` → `{"mode":"full"}`）。 |

---

## PARENT MUST WIRE

**核心 D5/C5-03 不需要任何越权改动**：生产每回合路径 `backend/agents/var_agent.py:125` 已调用 `memory_adapter.enqueue_extraction(...)`（该函数在范围内已增强为携带 messages/novel_id/world_key），队列消费者已被改为运行 LLM 图谱提取器。链路自洽，开箱即用。

**可选增强（非必需）**：章节固化路径 `backend/agents/chronicler_agent.py:253-259` 当前只入队 `{session_id, chapter_id, narrative_text, user_input, source_agent}`，缺 `messages`/`novel_id`，故其只走轨道B（SQLite 启发式），不触发 LLM 图谱提取。若希望章节摘要也进图谱，parent 可将该入队 payload 增补为：

```python
# backend/agents/chronicler_agent.py  ~line 253（chronicler 入队处）
extract_queue.enqueue({
    "session_id": ctx.session_id,
    "novel_id": ctx.session_id,                 # 新增
    "world_key": getattr(ctx, "world_plugin", ""),  # 新增
    "chapter_id": chapter_id,
    "narrative_text": summary,
    "messages": [{"role": "assistant", "content": summary}],  # 新增：触发 LLM 轨道A
    "user_input": "",
    "source_agent": "chronicler",
})
```

此为锦上添花，**核心四层召回与 D5 写入接线已在范围内完成，无阻塞项**。

---

## 验证记录
- `python -m py_compile`：rollback.py / extract_queue.py / adapter.py / retriever.py / llm_client.py / queries.py / extractor.py / sessions.py 全部 EXIT=0。
- `python -c "import memory.extractor, memory.retriever, memory.adapter, memory.rollback, memory.extract_queue, memory.engine"`（cwd=backend）→ `MEMORY_IMPORT_OK`。
- `python -c "import backend.memory.extractor, ..."`（cwd=repo root）→ `BACKEND_PREFIX_IMPORT_OK`。
- viewer 助手抽检：`dm` 不见 `character_pov`；`chronicler` 可见；`world` 不见 `relationship`；`narrator` == 全 5 分区；`protagonist` 对 `character_pov` 乘数 1.25；`npc_alice` 归一到 npc 白名单。
- `get_engine_status()` → `{'mode':'full','available':True}`。
