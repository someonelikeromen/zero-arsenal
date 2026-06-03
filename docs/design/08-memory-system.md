# 08 记忆系统（Memory System）设计文档

> **版本**：v1.0  
> **设计来源**：直接复用 `ai-vn-system-backend/backend/memory/`（向量 65% + Bigram 35% + 图扩散 + 认知分区权重）  
> **状态**：设计稿

---

## 目录

1. [设计来源与总体架构](#1-设计来源与总体架构)
2. [四层混合召回架构](#2-四层混合召回架构)
3. [viewer_agent 视角隔离](#3-viewer_agent-视角隔离)
4. [记忆写入流水线](#4-记忆写入流水线)
5. [章节固化（Consolidation）](#5-章节固化consolidation)
6. [记忆回滚（Rollback）](#6-记忆回滚rollback)
7. [数据结构与 DB Schema](#7-数据结构与-db-schema)
8. [记忆 API（FastAPI 路由）](#8-记忆-apifastapi-路由)
9. [性能与配置参数](#9-性能与配置参数)

---

## 1. 设计来源与总体架构

### 1.1 来源

记忆系统直接移植自 `ai-vn-system-backend/backend/memory/`，核心算法原封不动，适配层仅修改：
- 数据库路径参数化
- Agent 接口从旧版函数式改为 `MemoryManager` 类
- 增加视角隔离（`viewer_agent` 参数）
- 增加回滚支持

### 1.2 记忆分层（Memory Tier）

```
┌─────────────────────────────────────────────────┐
│  working  （工作记忆）                           │
│  • 当前活跃会话最近 20 条 turn                   │
│  • 全量存储，不做 embedding，直接放入 context     │
│  • 章节固化时清空                                │
├─────────────────────────────────────────────────┤
│  episodic （情节记忆）                           │
│  • 单次事件级别的记忆碎片                        │
│  • 有 embedding，参与混合召回                    │
│  • 章节固化后被压缩/升级为 semantic              │
├─────────────────────────────────────────────────┤
│  semantic （语义记忆）                           │
│  • 章节摘要、世界设定、角色档案等长期知识          │
│  • embedding 质量更高（压缩后内聚）              │
│  • 永久保留，支持跨会话继承                      │
├─────────────────────────────────────────────────┤
│  procedural（程序记忆）                          │
│  • 已获得技能/流派的使用规则                     │
│  • 不做 embedding，直接注入 system prompt         │
│  • 从 owned_items 表派生                        │
└─────────────────────────────────────────────────┘
```

### 1.3 总体召回流程

```
recall(query, session_id, viewer_agent, top_k)
         │
         ├─→ [视角过滤] 按 viewer_agent 过滤可见记忆集
         │
         ├─→ [向量召回]  sentence-transformer embed(query)
         │                → L2 归一化 → cosine 相似度 → top_k*3 候选
         │
         ├─→ [Bigram召回] jieba 分词 → TF-IDF → top_k*3 候选
         │
         ├─→ [图扩散]    对候选集中有图关联的节点传播分数
         │
         ├─→ [认知分区权重] character_pov × 1.25 / objective_global × 0.75
         │
         └─→ [混合得分排序] → 返回 top_k 记忆
```

---

## 2. 四层混合召回架构

### 2.1 向量语义层（weight = 0.65）

**算法**：sentence-transformers（`paraphrase-multilingual-MiniLM-L12-v2`，本地推理）

**处理流程**：
```python
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def vector_recall(
    query: str,
    candidate_embeddings: np.ndarray,   # shape: (N, dim)
    candidate_ids: list[str],
    top_k: int = 15,
) -> list[tuple[str, float]]:
    """
    返回 [(entry_id, score), ...]，score 为 L2 归一化后的余弦相似度。
    """
    # 1. 编码查询
    query_emb = model.encode(query, normalize_embeddings=True)  # L2 归一化

    # 2. 余弦相似度（已归一化，等价于点积）
    scores = np.dot(candidate_embeddings, query_emb)  # shape: (N,)

    # 3. Top-K 候选
    top_indices = np.argsort(scores)[::-1][:top_k]

    return [(candidate_ids[i], float(scores[i])) for i in top_indices]
```

**Embedding 存储**：
- 每条 `memory_entries` 记录在写入时同步生成 embedding
- 以 BLOB（float32 numpy array）形式存储在 `memory_entries.embedding` 字段
- 冷启动时一次性加载全部 embedding 到内存（通常 < 50MB）
- 写入新记录时增量追加，无需重建索引

**L2 归一化理由**：余弦相似度对长短文本更公平，避免长文本因向量模长大而天然得分高。

---

### 2.2 Bigram 词法层（weight = 0.35）

**算法**：jieba 分词 + TF-IDF 风格 BM25 评分

```python
import jieba
import math
from collections import Counter

class BigramRecall:
    """
    基于 Bigram（字级二元组）的 TF-IDF 风格召回。
    针对中文短文本优化，比 BM25 更轻量。
    """

    def __init__(self, corpus: list[tuple[str, str]]) -> None:
        """
        corpus: [(entry_id, text), ...]
        """
        self.entry_ids = [eid for eid, _ in corpus]
        self.tokenized = [self._tokenize(text) for _, text in corpus]
        self.idf = self._build_idf()

    def _tokenize(self, text: str) -> list[str]:
        """jieba 分词 + 字级 bigram 混合 token。"""
        words = list(jieba.cut(text))
        bigrams = [text[i:i+2] for i in range(len(text)-1)]
        return words + bigrams

    def _build_idf(self) -> dict[str, float]:
        N = len(self.tokenized)
        df: dict[str, int] = {}
        for tokens in self.tokenized:
            for t in set(tokens):
                df[t] = df.get(t, 0) + 1
        return {t: math.log((N + 1) / (n + 1)) + 1 for t, n in df.items()}

    def recall(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        q_tokens = self._tokenize(query)
        scores = []
        for idx, doc_tokens in enumerate(self.tokenized):
            tf = Counter(doc_tokens)
            score = sum(
                self.idf.get(t, 0) * (tf[t] / (tf[t] + 1.5))
                for t in q_tokens if t in tf
            )
            scores.append((self.entry_ids[idx], score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
```

**设计说明**：
- 词法层弥补向量层对生僻词汇/专有名词（如 NPC 名字、地名）的语义漂移问题
- Bigram 混合 token 增强对中文字形相近词的召回能力（如"苏力"/"苏利"）

---

### 2.3 图扩散层（GRAPH_DIFFUSE_SCORE = 0.45）

**实现**：NetworkX 有向图，节点为 `memory_entry_id`，边为关联关系（同章节/同 NPC/同地点）

```python
import networkx as nx

class GraphDiffusion:
    """
    在向量+Bigram 候选集上执行一跳图扩散，
    将与高分候选相关联的记忆节点分数适当提升。
    """

    DIFFUSE_SCORE = 0.45   # 关联节点获得的分数加成比例

    def __init__(self) -> None:
        self.G = nx.DiGraph()

    def add_edge(self, from_id: str, to_id: str, relation: str) -> None:
        """
        relation: "same_chapter" | "same_npc" | "same_location" | "caused_by"
        """
        self.G.add_edge(from_id, to_id, relation=relation)

    def diffuse(
        self,
        candidate_scores: dict[str, float],   # {entry_id: score}
        max_hops: int = 1,
    ) -> dict[str, float]:
        """
        对 candidate_scores 中的高分节点（> 0.6），
        向其邻居节点传播 DIFFUSE_SCORE 比例的分数。
        """
        augmented = dict(candidate_scores)
        high_score_nodes = {eid for eid, s in candidate_scores.items() if s > 0.6}

        for node in high_score_nodes:
            if node not in self.G:
                continue
            for neighbor in self.G.successors(node):
                propagated = candidate_scores[node] * self.DIFFUSE_SCORE
                if neighbor in augmented:
                    augmented[neighbor] = max(augmented[neighbor], propagated)
                else:
                    augmented[neighbor] = propagated

        return augmented
```

**图边建立时机**：
- 写入 `memory_entries` 时，自动建立：
  - `same_chapter`：同章节的所有记忆两两相连
  - `same_npc`：涉及同一 NPC 的记忆相连
  - `caused_by`：ChroniclerAgent 识别的因果链（可选）

---

### 2.4 认知分区权重

不同 `content_type` 的记忆在召回时享有不同权重，反映其认知"重要性"：

```python
COGNITIVE_WEIGHTS = {
    "character_pov":    1.25,   # 主观视角记忆（主角的感受/判断）
    "dialogue":         1.15,   # 对话记忆（NPC 说过的话高度相关）
    "action_result":    1.10,   # 行动结果（骰点、战斗结果）
    "objective_event":  1.00,   # 客观事件（中性）
    "objective_global": 0.75,   # 世界背景/通用设定（低优先级，避免淹没具体事件）
    "system_info":      0.60,   # 系统信息（最低优先级）
}

def apply_cognitive_weight(entry_id: str, score: float,
                            content_type: str) -> float:
    weight = COGNITIVE_WEIGHTS.get(content_type, 1.0)
    return score * weight
```

---

### 2.5 混合得分公式

```python
VECTOR_WEIGHT = 0.65
BIGRAM_WEIGHT = 0.35

def compute_hybrid_score(
    vector_score: float,
    bigram_score: float,
    graph_boost: float,      # 图扩散额外加成（0 或 DIFFUSE_SCORE × parent_score）
    cognitive_weight: float,
) -> float:
    """
    最终混合得分计算。

    注：bigram_score 需要先归一化到 [0, 1] 再参与计算。
    """
    raw = VECTOR_WEIGHT * vector_score + BIGRAM_WEIGHT * bigram_score
    boosted = raw + graph_boost
    return boosted * cognitive_weight
```

**时序分桶**：
- 同等分数下，更近期的记忆优先（`recency_bonus = 1 / (1 + days_ago * 0.1)`）
- 最终排序键：`(hybrid_score + recency_bonus * 0.05, -days_ago)`

---

## 3. viewer_agent 视角隔离

不同 Agent 召回的记忆集合不同，实现信息不对称和视角隔离。

### 3.1 视角定义

```python
from typing import Literal

ViewerAgent = Literal["dm", "npc", "narrator", "world", "player"]

VIEWER_FILTERS: dict[str, dict] = {
    "dm": {
        "tier_whitelist": ["working", "episodic", "semantic", "procedural"],
        "content_type_multipliers": {},  # 无限制，全量可见
        "npc_filter": None,              # 可见所有 NPC 相关记忆
        "description": "DM 视角，全知，可见所有层级和所有 NPC 的记忆"
    },
    "npc": {
        "tier_whitelist": ["episodic", "semantic"],
        "npc_filter": "self",            # 只见与该 NPC 相关的记忆
        "content_type_multipliers": {
            "character_pov": 0.5,        # NPC 不擅长推断主角的主观感受
        },
        "description": "NPC 视角，只见涉及自身的记忆，主观感知受限"
    },
    "narrator": {
        "tier_whitelist": ["working", "episodic", "semantic"],
        "content_type_multipliers": {
            "dialogue":         1.3,     # 叙事者优先引用对话
            "character_pov":    1.2,     # 叙事者关注情感
            "objective_global": 0.5,     # 叙事者不堆砌背景设定
        },
        "npc_filter": None,
        "description": "叙事者视角，偏向情感和对话，弱化枯燥设定"
    },
    "world": {
        "tier_whitelist": ["semantic"],
        "content_type_multipliers": {
            "objective_global": 1.5,     # 世界视角优先客观事实
            "character_pov":    0.3,     # 世界视角不关注主观
        },
        "npc_filter": None,
        "description": "世界视角，只见语义层级，优先客观世界事件"
    },
    "player": {
        "tier_whitelist": ["working", "episodic"],
        "npc_filter": None,
        "content_type_multipliers": {},
        "description": "玩家视角，只见当前活跃记忆，不见远期历史"
    },
}
```

### 3.2 视角过滤实现

```python
def filter_by_viewer(
    entries: list[MemoryEntry],
    viewer_agent: ViewerAgent,
    npc_name: str | None = None,   # npc 视角时必传
) -> list[MemoryEntry]:
    """
    按 viewer_agent 过滤并调整候选记忆集。
    """
    config = VIEWER_FILTERS[viewer_agent]
    tier_whitelist = config["tier_whitelist"]
    type_multipliers = config.get("content_type_multipliers", {})
    npc_filter = config.get("npc_filter")

    filtered = []
    for entry in entries:
        # Tier 过滤
        if entry.tier not in tier_whitelist:
            continue

        # NPC 过滤（npc 视角只见自身相关记忆）
        if npc_filter == "self" and npc_name:
            if npc_name not in entry.related_entities:
                continue

        # 应用 content_type 权重调整
        multiplier = type_multipliers.get(entry.content_type, 1.0)
        entry = entry._replace(recall_score=entry.recall_score * multiplier)
        filtered.append(entry)

    return filtered
```

---

## 4. 记忆写入流水线

```
ChroniclerAgent 产出（章节固化叙事文本）
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  extract_queue（后台异步提取关键事件）                │
│  • LLM 调用：从叙事文本中提取结构化事件列表          │
│  • 产出：[{title, content, entities, content_type}]  │
│  • 队列化处理，不阻塞主流程                          │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  embedding 生成                                      │
│  • 优先：本地 sentence-transformers（无需 API Key）  │
│  • 降级：OpenAI text-embedding-3-small API          │
│  • embed_text = title + " " + content[:500]          │
│  • L2 归一化后存储为 float32 BLOB                   │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  图节点关联建立                                      │
│  • 与同章节记忆建立 same_chapter 边                  │
│  • 扫描 related_entities，与同 NPC 记忆建立边        │
│  • 更新 GraphDiffusion 对象（内存图）               │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  memory_entries 写入 SQLite                          │
│  • INSERT OR IGNORE（幂等写入）                      │
│  • 字段：见 §7 数据结构                              │
│  • tier = "episodic"（固化前默认）                   │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  章节固化时：Consolidator 压缩                       │
│  • 召回本章节所有 episodic 记忆                      │
│  • LLM 生成章节摘要（< 500 字）                     │
│  • 升级为 semantic tier                              │
│  • 原 episodic 记忆标记 is_consolidated = 1          │
└─────────────────────────────────────────────────────┘
```

### 4.1 后台提取队列

```python
import asyncio
from dataclasses import dataclass

@dataclass
class ExtractTask:
    session_id: str
    chapter_id: str
    raw_text: str
    viewer_agent: str = "dm"

class ExtractQueue:
    """后台异步记忆提取队列，不阻塞主流程。"""

    def __init__(self, memory_manager: "MemoryManager") -> None:
        self._queue: asyncio.Queue[ExtractTask] = asyncio.Queue()
        self._manager = memory_manager
        self._running = False

    async def enqueue(self, task: ExtractTask) -> None:
        await self._queue.put(task)

    async def run(self) -> None:
        """后台持续消费任务。"""
        self._running = True
        while self._running:
            task = await self._queue.get()
            try:
                await self._process(task)
            except Exception as e:
                logger.error("ExtractQueue error: %s", e)
            finally:
                self._queue.task_done()

    async def _process(self, task: ExtractTask) -> None:
        # 1. LLM 提取事件
        events = await self._extract_events_via_llm(task.raw_text)

        # 2. 逐条写入记忆
        for event in events:
            await self._manager.add_memory(
                session_id=task.session_id,
                chapter_id=task.chapter_id,
                title=event["title"],
                content=event["content"],
                content_type=event["content_type"],
                related_entities=event.get("entities", []),
                tier="episodic",
            )

    async def _extract_events_via_llm(self, text: str) -> list[dict]:
        # 调用 LLM 提取，prompt 省略
        # 返回格式：[{"title": "...", "content": "...", "content_type": "...", "entities": [...]}]
        pass
```

---

### 4.2 MemoryManager 主类

```python
class MemoryManager:
    """记忆系统的统一入口，封装召回/写入/固化/回滚。"""

    def __init__(self, db_path: str, config: MemoryConfig) -> None:
        self.db_path = db_path
        self.config = config
        self._vector_model = SentenceTransformer(config.embedding_model)
        self._bigram = None      # 延迟初始化（首次召回时构建）
        self._graph = GraphDiffusion()
        self._cache: dict[str, np.ndarray] = {}  # session_id → 嵌入矩阵缓存

    async def recall(
        self,
        session_id: str,
        query: str,
        viewer_agent: ViewerAgent = "dm",
        top_k: int = 10,
        npc_name: str | None = None,
    ) -> list[MemoryEntry]:
        """混合召回核心入口。"""
        # 1. 加载候选集（视角过滤后）
        all_entries = await self._load_entries(session_id)
        filtered = filter_by_viewer(all_entries, viewer_agent, npc_name)

        if not filtered:
            return []

        # 2. 向量召回
        emb_matrix = np.array([e.embedding for e in filtered])
        vector_results = vector_recall(query, emb_matrix,
                                       [e.id for e in filtered], top_k=top_k*3)

        # 3. Bigram 召回
        if self._bigram is None:
            self._bigram = BigramRecall([(e.id, e.content) for e in filtered])
        bigram_results = self._bigram.recall(query, top_k=top_k*3)

        # 4. 合并得分
        combined: dict[str, float] = {}
        for eid, score in vector_results:
            combined[eid] = VECTOR_WEIGHT * score
        for eid, score in bigram_results:
            # bigram 分数归一化（除以最大值）
            norm_score = score / (max(s for _, s in bigram_results) + 1e-9)
            combined[eid] = combined.get(eid, 0) + BIGRAM_WEIGHT * norm_score

        # 5. 图扩散
        combined = self._graph.diffuse(combined)

        # 6. 认知分区权重
        entry_map = {e.id: e for e in filtered}
        for eid in list(combined.keys()):
            if eid in entry_map:
                combined[eid] = apply_cognitive_weight(
                    eid, combined[eid], entry_map[eid].content_type
                )

        # 7. 时序加成 + 最终排序
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).timestamp()
        scored = []
        for eid, score in combined.items():
            if eid not in entry_map:
                continue
            entry = entry_map[eid]
            days_ago = (now - entry.created_at) / 86400
            recency_bonus = 1 / (1 + days_ago * 0.1)
            final_score = score + recency_bonus * 0.05
            scored.append((entry, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:top_k]]

    async def add_memory(
        self,
        session_id: str,
        chapter_id: str,
        title: str,
        content: str,
        content_type: str,
        related_entities: list[str],
        tier: str = "episodic",
    ) -> str:
        """写入新记忆条目，生成 embedding，建立图关联。"""
        import uuid
        entry_id = str(uuid.uuid4())

        # 生成 embedding
        embed_text = f"{title} {content[:500]}"
        embedding = self._vector_model.encode(embed_text, normalize_embeddings=True)

        # 写 DB
        await self._insert_entry(entry_id, session_id, chapter_id, title,
                                  content, content_type, related_entities,
                                  tier, embedding)

        # 建立图关联
        same_chapter_entries = await self._get_entries_by_chapter(chapter_id)
        for e in same_chapter_entries:
            self._graph.add_edge(entry_id, e.id, "same_chapter")
            self._graph.add_edge(e.id, entry_id, "same_chapter")

        return entry_id
```

---

## 5. 章节固化（Consolidation）

### 5.1 触发时机

| 触发方式 | 条件 |
|---|---|
| ChroniclerAgent 自动触发 | 每次 `consolidate_chapter` 工具调用 |
| 手动触发 | `POST /api/sessions/{id}/memory/consolidate` |
| 阈值触发 | episodic 记忆超过 100 条时自动触发最旧章节 |

### 5.2 固化流程

```python
class ConsolidationPipeline:
    """章节记忆固化：episodic → semantic。"""

    async def consolidate(
        self,
        session_id: str,
        chapter_id: str,
        force: bool = False,
    ) -> ConsolidationResult:
        # 1. 检查是否已固化
        chapter = await self._get_chapter(chapter_id)
        if chapter.is_consolidated and not force:
            return ConsolidationResult(skipped=True, reason="already_consolidated")

        # 2. 召回本章节所有 episodic 记忆
        episodes = await self._load_chapter_episodes(session_id, chapter_id)
        if not episodes:
            return ConsolidationResult(skipped=True, reason="no_episodes")

        # 3. 拼接所有 episodic 内容
        combined_text = "\n\n".join(
            f"[{e.content_type}] {e.title}\n{e.content}"
            for e in episodes
        )

        # 4. LLM 生成章节摘要（< 500 字）
        summary = await self._llm_summarize(combined_text, chapter_id)

        # 5. 摘要写入 semantic tier
        semantic_id = await self.memory_manager.add_memory(
            session_id=session_id,
            chapter_id=chapter_id,
            title=f"第{chapter.chapter_number}章摘要",
            content=summary,
            content_type="objective_event",
            related_entities=self._extract_entities_from_summary(summary),
            tier="semantic",
        )

        # 6. 标记原 episodic 记忆为已固化（保留原始数据，仅降低召回权重）
        await self._mark_episodes_consolidated(chapter_id)

        # 7. 更新 chapters 表
        await self._update_chapter_consolidated(chapter_id)

        return ConsolidationResult(
            skipped=False,
            chapter_id=chapter_id,
            semantic_id=semantic_id,
            episodes_count=len(episodes),
            summary_length=len(summary),
        )

    async def _llm_summarize(self, text: str, chapter_id: str) -> str:
        """调用 LLM 生成 < 500 字的章节摘要。"""
        # 具体 prompt 设计：
        # 1. 提取核心事件（≤ 5 条）
        # 2. 记录关键 NPC 行为变化
        # 3. 标注未解伏笔
        # 4. 总字数 < 500
        pass
```

---

## 6. 记忆回滚（Rollback）

回滚到指定 `chapter_id`，撤销该章节之后的所有记忆写入，恢复叙事树状态。

### 6.1 回滚流程

```
POST /api/sessions/{id}/memory/rollback
    body: { "chapter_id": "xxx" }
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  1. 确认目标章节存在且未被更早的章节依赖             │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  2. 删除该章节之后的所有 memory_entries              │
│     DELETE FROM memory_entries                       │
│     WHERE session_id = ? AND chapter_id IN (         │
│       SELECT id FROM chapters                        │
│       WHERE session_id = ? AND sort_order > ?        │
│     )                                                │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  3. 恢复 chapters 树状态                             │
│     • 删除目标章节之后创建的所有章节记录             │
│     • 将目标章节的 is_consolidated 重置为 0          │
│       （如果是固化章节，需要重新固化）               │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  4. 清除 working tier 记忆                           │
│     DELETE FROM memory_entries                       │
│     WHERE session_id = ? AND tier = 'working'        │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  5. 重建图关联                                       │
│     • 清空 GraphDiffusion 内存图中与已删除记忆       │
│       相关的所有边                                   │
│     • 重新加载剩余记忆建立图                        │
└─────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────┐
│  6. 回滚 character_card 到该章节的快照状态           │
│     （从 chapters.state_snapshot 字段恢复）          │
└─────────────────────────────────────────────────────┘
```

### 6.2 回滚实现

> **实现差异**：实际实现类名为 `MemoryRollback`（`backend/memory/rollback.py`），操作图谱节点而非直接操作 SQLite 表，与设计草案（SQLite `memory_entries` + `chapters` 表直接删除）有根本性差异。

**设计草案 vs 实现对照**：

| 设计草案 | 实际实现 | 说明 |
|---|---|---|
| 类名 `RollbackManager` | 类名 `MemoryRollback` | 改名 |
| `rollback_to_chapter(session_id, target_chapter_id)` | `rollback_chapter(novel_id, chapter_id, chapter_created_at)` | 参数变化，新增时间戳参数 |
| 删除 `memory_entries` 表行 | 删除 `graph_manager` 中的节点 | 操作对象不同 |
| 删除 `chapters` 表行 | 联动删除 `vector_manager` 节点 | 操作层不同 |
| `_rebuild_graph()` 内存重建 | 删除 `node_sync_status` 同步状态 | 清理方式不同 |
| `restore_character_state()` | `restore_character_node()` | 以图节点方式恢复角色状态 |
| — | `rollback_by_time(novel_id, since_iso)` | 新增：按时间戳回滚（轮次级别）|

```python
# 实际实现：backend/memory/rollback.py
class MemoryRollback:
    async def rollback_chapter(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_created_at: str,    # ISO8601 时间戳，确定脏节点边界
    ) -> dict:
        """删除 chapter_created_at 之后创建的所有记忆图谱节点。"""
        graph = graph_manager.get(novel_id)
        dirty_ids = graph.get_nodes_created_after(chapter_created_at)
        graph_removed = await graph_manager.remove_nodes(novel_id, dirty_ids)
        await vector_manager.delete_nodes(novel_id, dirty_ids)
        # 清除 node_sync_status 记录
        ...
        return {"graph_removed": graph_removed, "vector_removed": len(dirty_ids)}

    async def rollback_by_time(self, novel_id: str, since_iso: str) -> dict:
        """按时间戳回滚（轮次级别，区别于章节级别）。"""
        ...

    async def restore_character_node(
        self, novel_id: str, character_name: str, pre_chapter_snapshot: dict
    ) -> bool:
        """恢复角色节点至回滚前快照。"""
        ...

# 全局单例
memory_rollback = MemoryRollback()
```

---

## 7. 数据结构与 DB Schema

### 7.1 memory_entries 表

> **设计草案 vs 实现差异**：实现中字段更丰富，`content_type` 改名为 `cognitive_partition`，`is_consolidated` 改为时间戳 `consolidated_at`，新增了 `bigram_tokens`、`graph_nodes`、`importance`、`access_count` 等召回优化字段。

```sql
-- 以下为实际实现（backend/db/schema.py）
CREATE TABLE IF NOT EXISTS memory_entries (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chapter_id          TEXT REFERENCES chapters(id),
    content             TEXT NOT NULL,
    embedding           BLOB,               -- float32 bytes（L2 归一化，shape 384）
    bigram_tokens       TEXT DEFAULT '[]',  -- JSON array（中文 bigram 分词结果）
    graph_nodes         TEXT DEFAULT '[]',  -- JSON array（关联实体 ID 列表）
    tier                TEXT NOT NULL DEFAULT 'episodic',
                        -- episodic | semantic | core | working
    cognitive_partition TEXT NOT NULL DEFAULT 'objective_global',
                        -- character_pov | objective_global | world_state | relationship
    source_agent        TEXT DEFAULT '',    -- 写入该记忆的 Agent 名称
    importance          REAL NOT NULL DEFAULT 0.5,    -- 重要度 [0,1]
    access_count        INTEGER NOT NULL DEFAULT 0,   -- 被召回次数（遗忘曲线）
    last_accessed_at    REAL,               -- 最近被召回的时间戳
    related_npcs        TEXT DEFAULT '[]',  -- JSON array：关联 NPC key 列表
    related_location    TEXT DEFAULT '',    -- 关联地点标识
    world_time          TEXT DEFAULT '',    -- 世界内时间（如"第3年春"）
    created_at          REAL NOT NULL,
    consolidated_at     REAL                -- 固化完成时间（NULL=未固化）
);
CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_entries(session_id, tier);
```

**设计草案字段对照（已废弃）**：

| 设计草案字段 | 实际实现 | 说明 |
|---|---|---|
| `title TEXT NOT NULL` | 已移除 | 内容直接存 `content`，不单独存标题 |
| `content_type TEXT` | `cognitive_partition TEXT` | 语义等价，但值域不同 |
| `related_entities JSON` | `related_npcs` + `related_location` | 拆分为 NPC 列表和地点两个专用字段 |
| `is_consolidated INTEGER` | `consolidated_at REAL` | 由布尔改为时间戳，保留固化时间信息 |
| `recall_score REAL` | 已移除 | 召回分数不持久化，在内存中计算 |
| — | `bigram_tokens` | 新增：中文 Bigram 分词缓存 |
| — | `graph_nodes` | 新增：图谱关联实体 |
| — | `importance`, `access_count`, `last_accessed_at` | 新增：遗忘曲线/重要度权重字段 |
| — | `source_agent`, `world_time` | 新增：来源 Agent 和世界时间 |

### 7.2 MemoryEntry Python 数据类

> **实现差异**：实际 `MemoryEntry`（`backend/db/memory_entry.py`）与设计草案差异较大，字段已随 §7.1 表结构一并演进。

```python
# 实际实现：backend/db/memory_entry.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MemoryEntry:
    """单条记忆条目，与 memory_entries 表对应。"""
    id: str
    session_id: str
    content: str
    tier: str = "episodic"              # episodic | semantic | core | working
    cognitive_partition: str = "objective_global"
                                        # character_pov | objective_global | world_state | relationship
    chapter_id: str = ""
    source_agent: str = ""
    embedding: Optional[bytes] = None   # float32 向量（二进制存储）
    bigram_tokens: list[str] = field(default_factory=list)
    graph_nodes: list[str] = field(default_factory=list)  # 关联实体 ID
    created_at: float = 0.0
    consolidated_at: Optional[float] = None

    @property
    def is_consolidated(self) -> bool:
        return self.consolidated_at is not None

    @classmethod
    def from_row(cls, row: dict) -> "MemoryEntry":
        """从 SQLite Row 构造。"""
        ...

    def to_dict(self) -> dict:
        """序列化为 dict（embedding 转 Base64）。"""
        ...
```

**设计草案 vs 实现差异**：

| 设计草案字段 | 实际字段 | 说明 |
|---|---|---|
| `title: str` | 已移除 | 无独立标题字段 |
| `content_type: str` | `cognitive_partition: str` | 字段改名 |
| `related_entities: list[str]` | `graph_nodes: list[str]` | 语义更精确（图谱节点 ID）|
| `embedding: np.ndarray \| None` | `embedding: Optional[bytes]` | 存为二进制而非 numpy |
| `is_consolidated: bool` | `is_consolidated: property` | 由字段改为只读属性，派生自 `consolidated_at` |
| `recall_score: float` | 已移除 | 召回分数不持久化 |
| — | `bigram_tokens`, `source_agent` | 新增字段 |

### 7.3 特别说明：骰子结果与 state_patch 不进向量记忆

以下两类数据**只进结构化 DB，不做 embedding，不参与向量召回**：

| 数据类型 | 存储位置 | 原因 |
|---|---|---|
| **骰子结果** | `dice_log` 表 | 结构化数值，语义搜索无意义；通过 chapter_id 直接关联章节 |
| **state_patch** | `message_parts` 表（`part_type='state_patch'`） | TavernCommand 操作序列，通过时间序重放即可，不需要相似度检索 |

这两类数据在 `MemoryManager` 的接口中**不暴露** `add_memory` 方法，由各自的专用写入函数处理：
```python
# 骰子结果
await dice_logger.log(session_id, chapter_id, formula, result, success)

# state_patch
await part_writer.write_patch(session_id, message_id, commands)
```

---

## 8. 记忆 API（FastAPI 路由）

> ⚠️ **实现差异（第二十九轮补录）**：设计草案中的 `POST /recall` 专用端点**未在实际路由中实现**，实际搜索记忆通过 `GET /memory` 端点完成（参数语义也不同）。对照见下方表格。

**端点设计 vs 实现对照**：

| 维度 | 设计草案 | 实际实现（`sessions.py`） |
|---|---|---|
| HTTP 方法 + 路径 | `POST /api/sessions/{id}/memory/recall` | `GET /api/sessions/{id}/memory` |
| 请求参数 | JSON body: `query`, `viewer_agent`, `top_k`, `npc_name` | Query params: `q`, `top_k`, `tier` |
| `viewer_agent` 过滤 | 支持（dm/npc/narrator/world/player 5种） | 不支持（无此参数） |
| 返回结构 | `{entries, total_candidates, query_time_ms}` | `{results, entries, full_mode}` |
| `results` 字段 | — | MemoryAdapter 召回的文本结果（与 DB `entries` 并列返回） |

**实际 `GET /memory` 实现**（简化）：
```python
@router.get("/sessions/{session_id}/memory")
async def search_memory(session_id: str, q: str = "", top_k: int = 10, tier: Optional[str] = None):
    results_text = await memory_adapter.recall(session_id, world_plugin, query_text=q, top_k=top_k)
    # + 从 DB 查 memory_entries（可按 tier 过滤）
    return {"results": results_text, "entries": entries, "full_mode": memory_adapter.is_full_mode}
```

**设计草案的 `POST /recall`（保留作参考，未实现）**：

```python
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

router = APIRouter(prefix="/api/sessions/{session_id}/memory", tags=["memory"])


# ── 召回（设计草案版；未实装，实际用 GET /memory）──────────────────────

class RecallRequest(BaseModel):
    query: str
    viewer_agent: str = "dm"
    top_k: int = 10
    npc_name: str | None = None

class RecallResponse(BaseModel):
    entries: list[dict]
    total_candidates: int
    query_time_ms: float

@router.post("/recall", response_model=RecallResponse)
async def recall_memory(
    session_id: str,
    req: RecallRequest,
    memory_manager: MemoryManager = Depends(get_memory_manager),
) -> RecallResponse:
    """
    召回指定 query 的相关记忆。

    viewer_agent 参数控制视角隔离：
    - dm       → 全知视角，可见所有层级
    - npc      → 指定 NPC 视角，需传 npc_name
    - narrator → 叙事者视角，偏向情感和对话
    - world    → 客观世界视角，只见 semantic 层
    - player   → 玩家视角，只见活跃记忆
    """
    import time
    start = time.time()

    entries = await memory_manager.recall(
        session_id=session_id,
        query=req.query,
        viewer_agent=req.viewer_agent,
        top_k=req.top_k,
        npc_name=req.npc_name,
    )

    return RecallResponse(
        entries=[e.__dict__ for e in entries],
        total_candidates=len(entries),
        query_time_ms=(time.time() - start) * 1000,
    )


# ── 固化 ──────────────────────────────────────────────────────────

class ConsolidateRequest(BaseModel):
    chapter_id: str | None = None
    force: bool = False

class ConsolidateResponse(BaseModel):
    chapter_id: str
    episodes_count: int
    semantic_id: str
    skipped: bool
    reason: str | None = None

@router.post("/consolidate", response_model=ConsolidateResponse)
async def consolidate_memory(
    session_id: str,
    req: ConsolidateRequest,
    pipeline: ConsolidationPipeline = Depends(get_consolidation_pipeline),
) -> ConsolidateResponse:
    """
    手动触发章节固化。

    chapter_id 为 None 时固化最新未固化章节。
    force=True 时允许重新固化已固化章节。
    """
    result = await pipeline.consolidate(
        session_id=session_id,
        chapter_id=req.chapter_id or await pipeline.get_latest_unconsolidated(session_id),
        force=req.force,
    )
    if result.skipped:
        return ConsolidateResponse(
            chapter_id=req.chapter_id or "",
            episodes_count=0,
            semantic_id="",
            skipped=True,
            reason=result.reason,
        )
    return ConsolidateResponse(
        chapter_id=result.chapter_id,
        episodes_count=result.episodes_count,
        semantic_id=result.semantic_id,
        skipped=False,
    )


# ── 回滚 ──────────────────────────────────────────────────────────

class RollbackRequest(BaseModel):
    chapter_id: str
    confirm: bool = False   # 必须传 True 才真正执行（防误操作）

class RollbackResponse(BaseModel):
    target_chapter_id: str
    deleted_chapters: int
    deleted_memories: int
    character_restored: bool

@router.post("/rollback", response_model=RollbackResponse)
async def rollback_memory(
    session_id: str,
    req: RollbackRequest,
    rollback_manager: RollbackManager = Depends(get_rollback_manager),
) -> RollbackResponse:
    """
    回滚到指定章节。

    ⚠️ 危险操作：将删除该章节之后的所有记忆和章节数据。
    必须传 confirm=True 才会真正执行。
    """
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Rollback requires confirm=true. This operation cannot be undone."
        )

    result = await rollback_manager.rollback_to_chapter(session_id, req.chapter_id)

    return RollbackResponse(
        target_chapter_id=result.target_chapter_id,
        deleted_chapters=result.deleted_chapters,
        deleted_memories=result.deleted_memories,
        character_restored=True,
    )
```

---

## 9. 性能与配置参数

### 9.1 MemoryConfig

```python
from dataclasses import dataclass, field

@dataclass
class MemoryConfig:
    # Embedding 模型
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    use_openai_fallback: bool = False   # 本地失败时降级到 OpenAI

    # 召回参数
    vector_weight: float = 0.65
    bigram_weight: float = 0.35
    graph_diffuse_score: float = 0.45
    default_top_k: int = 10
    min_score_threshold: float = 0.3   # 低于此分数的结果过滤

    # 认知权重
    cognitive_weights: dict[str, float] = field(default_factory=lambda: {
        "character_pov": 1.25,
        "dialogue": 1.15,
        "action_result": 1.10,
        "objective_event": 1.00,
        "objective_global": 0.75,
        "system_info": 0.60,
    })

    # 固化策略
    auto_consolidate_threshold: int = 100   # episodic 数量超过此值自动固化
    consolidation_summary_max_tokens: int = 500

    # 性能
    embedding_cache_size: int = 1000   # LRU 缓存最近 N 个查询 embedding
    graph_max_nodes: int = 10000       # 图节点上限，超出时删除最旧 same_chapter 边
```

### 9.2 性能基准（参考值）

| 操作 | 数据规模 | 预期耗时 |
|---|---|---|
| 单条 embedding 生成（本地） | 500字 | < 50ms |
| 混合召回（top_k=10） | 1000 条记忆 | < 200ms |
| 混合召回（top_k=10） | 10000 条记忆 | < 800ms |
| 章节固化（LLM 摘要） | 50 条 episodic | 3-8s（含 LLM 调用） |
| 回滚（删除+重建图） | 500 条记忆 | < 2s |

### 9.3 内存占用估算

| 组件 | 1000 条记忆 | 10000 条记忆 |
|---|---|---|
| Embedding 矩阵（float32, dim=384） | ~1.5 MB | ~15 MB |
| NetworkX 图（边 ≈ 节点×10） | ~2 MB | ~20 MB |
| BigramRecall 索引 | ~0.5 MB | ~5 MB |
| **总计** | ~4 MB | ~40 MB |
