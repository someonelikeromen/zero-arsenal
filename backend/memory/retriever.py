"""
混合召回管线 — 精确对应 ST-BME retriever.js 的 Python 移植
四级召回：向量语义 → Bigram词法增强 → 图扩散 → 认知权重/时序重打分
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from memory.schema import NodeType, TemporalBucket


# ════════════════════════════════════════════════════════════════════════════
# ST-BME 精确参数（对应 ST-BME retriever.js 原始值）
# ════════════════════════════════════════════════════════════════════════════

# 认知分区权重（按 DB schema cognitive_partition 列的实际存储值）
# DB 枚举：character_pov | objective_global | world_state | relationship | objective_local
SCOPE_WEIGHTS: dict[str, float] = {
    "character_pov":    1.25,   # 主角主观视角记忆（感受/判断）
    "world_state":      1.10,   # 世界状态变化（场景/时局）
    "relationship":     1.00,   # NPC 关系数据（中性）
    "objective_local":  0.90,   # 当前区域客观事件
    "objective_global": 0.75,   # 全局背景设定（避免淹没具体事件）
}

# 内容类型权重（按 design §2.4 COGNITIVE_WEIGHTS，用于 content_type 维度）
# 当 cognitive_partition 缺失时使用 content_type fallback
COGNITIVE_WEIGHTS: dict[str, float] = {
    "character_pov":   1.25,
    "dialogue":        1.15,
    "action_result":   1.10,
    "objective_event": 1.00,
    "objective_global": 0.75,
    "system_info":     0.60,
}

# 时序分桶优先级
TEMPORAL_BUCKET_PRIORITY: dict[str, int] = {
    "current":       5,
    "adjacent_past": 4,
    "undated":       3,
    "flashback":     2,
    "distant_past":  1,
    "future":        0,
}

# 词法匹配权重
LEXICAL_WEIGHTS: dict[str, float] = {
    "exact_primary":      1.00,
    "exact_secondary":    0.82,
    "contains_primary":   0.92,
    "contains_secondary": 0.68,
    "overlap_primary":    0.72,
    "overlap_secondary":  0.52,
}

# 综合得分融合权重
VECTOR_WEIGHT  = 0.65
LEXICAL_WEIGHT = 0.35

# 图扩散节点固定得分
GRAPH_DIFFUSE_SCORE = 0.45

# 时序微调系数
TEMPORAL_TUNE_COEFF = 0.05


# ════════════════════════════════════════════════════════════════════════════
# Bigram 词法工具
# ════════════════════════════════════════════════════════════════════════════

def build_bigram_units(text: str) -> list[str]:
    """
    构建中文 Bigram 词法单元（对应 ST-BME 精确实现）。
    例：「藏宝室」 → [「藏宝」, 「宝室」, 「藏宝室」]
    """
    result: set[str] = set()
    chars = list(text)
    for i in range(len(chars) - 1):
        result.add(chars[i] + chars[i + 1])
    result.add(text)            # 完整字符串也加入
    # 尝试 jieba 分词增强
    try:
        import jieba
        for word in jieba.cut(text, cut_all=False):
            if len(word) > 1:
                result.add(word)
    except ImportError:
        pass
    return list(result)


def compute_lexical_score(
    query_units: list[str],
    node_primary: str,
    node_secondary: str = "",
) -> float:
    """
    计算词法匹配得分（对应 ST-BME retriever.js computeLexicalScore）。
    node_primary  = title（主字段）
    node_secondary = content[:100]（次字段）
    """
    score = 0.0
    for unit in query_units:
        # 主字段匹配
        if unit == node_primary:
            score = max(score, LEXICAL_WEIGHTS["exact_primary"])
        elif unit in node_primary:
            score = max(score, LEXICAL_WEIGHTS["contains_primary"])
        elif any(c in node_primary for c in unit):
            score = max(score, LEXICAL_WEIGHTS["overlap_primary"])

        # 次字段匹配（content 前100字）
        if node_secondary:
            if unit == node_secondary:
                score = max(score, LEXICAL_WEIGHTS["exact_secondary"])
            elif unit in node_secondary:
                score = max(score, LEXICAL_WEIGHTS["contains_secondary"])
            elif any(c in node_secondary for c in unit):
                score = max(score, LEXICAL_WEIGHTS["overlap_secondary"])

    return score


def determine_scope_key(
    node_meta: dict, protagonist_location: str
) -> str:
    """
    判断节点的认知分区键（影响 POV 权重）。
    返回值与 DB schema 的 cognitive_partition 枚举对齐：
    character_pov | world_state | relationship | objective_local | objective_global
    """
    node_type = node_meta.get("node_type", "")
    scope_owner = node_meta.get("scope_owner", "")
    # 优先使用节点上已记录的 cognitive_partition
    stored_partition = node_meta.get("cognitive_partition", "")
    if stored_partition in SCOPE_WEIGHTS:
        return stored_partition

    if node_type == NodeType.POV_MEMORY.value:
        if scope_owner == "protagonist":
            return "character_pov"
        else:
            return "objective_global"
    elif node_type == NodeType.LOCATION.value:
        if protagonist_location and node_meta.get("node_title", "") == protagonist_location:
            return "objective_local"
        else:
            return "objective_global"
    elif node_type in (NodeType.RELATIONSHIP.value if hasattr(NodeType, "RELATIONSHIP") else "relationship", "relationship"):
        return "relationship"
    elif node_type in ("world_state", "scene", "environment"):
        return "world_state"
    else:
        return "objective_global"


def check_pov_visibility(node_meta: dict, viewer_agent: str) -> bool:
    """
    POV 可见性过滤（分层隔离规则）。
    确保 DM 不被 pov_memory 节点污染裁判视角。
    """
    node_type = node_meta.get("node_type", "")

    if node_type != NodeType.POV_MEMORY.value:
        return True  # 非 pov_memory 节点对所有 Agent 可见

    agent_rules = {
        "chronicler": lambda m: True,          # 书记员上帝视角
        "dm":         lambda m: False,         # DM 拒绝 pov_memory
        "planner":    lambda m: False,         # Planner 拒绝 pov_memory
        "protagonist": lambda m: m.get("scope_owner") == "protagonist",
    }

    if viewer_agent.startswith("npc_"):
        npc_name = viewer_agent.replace("npc_", "")
        return node_meta.get("scope_owner") == npc_name

    rule = agent_rules.get(viewer_agent, lambda m: False)
    return rule(node_meta)


# ════════════════════════════════════════════════════════════════════════════
# 主召回管线
# ════════════════════════════════════════════════════════════════════════════

async def hybrid_recall(
    novel_id: str,
    world_key: str,
    query_text: str,
    protagonist_location: str = "",
    viewer_agent: str = "chronicler",
    top_k: int = 15,
) -> dict:
    """
    完整四级混合召回管线（精确对应 ST-BME 设计）。

    Returns:
        {
            "core": [节点dict],      # Core 层常驻（rule/thread/synopsis）
            "recalled": [节点dict],  # 动态层 Top-K
        }
    """
    from memory.graph import graph_manager
    from memory.vector import vector_manager
    from utils.llm_client import get_embedding_client

    # ── Step 1：Core 常驻层（直接读取，不经召回）──────────────────────────
    core_nodes = await graph_manager.get_nodes_by_type(
        novel_id,
        NodeType.core_types(),
        world_key=world_key,
    )
    logger.debug(f"[Retriever] Core 层: {len(core_nodes)} 个节点")

    # ── Step 2A：向量语义检索 ─────────────────────────────────────────────
    emb_client = get_embedding_client()
    try:
        query_embedding = await emb_client.embed(query_text)
        vector_results = await vector_manager.query(
            novel_id=novel_id,
            embedding=query_embedding,
            n_results=top_k * 2,
            world_key=world_key,
        )
    except Exception as e:
        logger.warning(f"[Retriever] 向量检索失败: {e}，跳过")
        vector_results = []

    # ── Step 2B：Bigram 词法增强 ──────────────────────────────────────────
    query_bigrams = build_bigram_units(query_text)

    scored_nodes: list[dict] = []
    seen_ids: set[str] = set()

    for hit in vector_results:
        meta = hit.get("metadata", {})
        node_id = meta.get("node_id", "")
        if not node_id or node_id in seen_ids:
            continue

        # POV 可见性过滤
        if not check_pov_visibility(meta, viewer_agent):
            continue

        vector_score = hit.get("score", 0.0)
        node_title   = meta.get("node_title", "")
        content_snip = (hit.get("content", ""))[:100]

        lexical_score = compute_lexical_score(query_bigrams, node_title, content_snip)

        # 综合得分
        hybrid_score = VECTOR_WEIGHT * vector_score + LEXICAL_WEIGHT * lexical_score

        # 时序分桶微调
        bucket = meta.get("temporal_bucket", "undated")
        temporal_prio = TEMPORAL_BUCKET_PRIORITY.get(bucket, 3)
        hybrid_score *= (1 + temporal_prio * TEMPORAL_TUNE_COEFF)

        # 认知分区权重（pov_memory 节点专属）
        if meta.get("node_type") == NodeType.POV_MEMORY.value:
            scope_key = determine_scope_key(meta, protagonist_location)
            hybrid_score *= SCOPE_WEIGHTS.get(scope_key, 0.75)

        seen_ids.add(node_id)
        scored_nodes.append({
            "content":  hit.get("content", ""),
            "metadata": meta,
            "score":    hybrid_score,
        })

    # ── Step 2C：图扩散（沿关系边扩展）──────────────────────────────────
    seed_ids = [
        n["metadata"]["node_id"]
        for n in scored_nodes[:5]
        if n["metadata"].get("node_id")
    ]

    if seed_ids:
        neighbors = await graph_manager.get_neighbors(
            novel_id=novel_id,
            seed_node_ids=seed_ids,
            relation_types=["involved_in", "occurred_at", "advances", "related", "caused_by"],
            max_hops=2,
        )
        for neighbor in neighbors:
            nid = neighbor.get("node_id", "")
            if not nid or nid in seen_ids:
                continue
            if not check_pov_visibility(neighbor, viewer_agent):
                continue
            seen_ids.add(nid)
            scored_nodes.append({
                "content":  neighbor.get("content", neighbor.get("summary", "")),
                "metadata": {
                    "node_id":        nid,
                    "node_type":      neighbor.get("node_type", ""),
                    "node_title":     neighbor.get("title", ""),
                    "temporal_bucket":neighbor.get("temporal_bucket", "undated"),
                    "scope_owner":    neighbor.get("scope_owner", ""),
                },
                "score":    GRAPH_DIFFUSE_SCORE,
            })

    # ── Step 3：排序（注入 importance 乘数）、Top-K 截断 ─────────────────
    # importance ∈ [0,1]，乘数 (0.5 + 0.5 * importance)，保证高重要度节点优先
    for node in scored_nodes:
        imp = float(node.get("metadata", {}).get("importance", 0.5))
        node["score"] = node["score"] * (0.5 + 0.5 * imp)

    scored_nodes.sort(key=lambda x: x["score"], reverse=True)
    recalled_nodes = scored_nodes[:top_k]

    logger.debug(
        f"[Retriever] 召回完成: core={len(core_nodes)}, "
        f"recalled={len(recalled_nodes)} (from {len(scored_nodes)} 候选)"
    )

    return {
        "core":     core_nodes,
        "recalled": recalled_nodes,
    }


# ════════════════════════════════════════════════════════════════════════════
# NPC 最近行为召回（供 Planner 角色漂移检测使用）
# ════════════════════════════════════════════════════════════════════════════

async def get_npc_recent_behavior(
    novel_id: str,
    npc_name: str,
    chapters_back: int = 3,
) -> list[dict]:
    """
    召回最近 N 章内，某 NPC 的行为相关节点。
    """
    from memory.graph import graph_manager

    all_events = await graph_manager.get_nodes_by_type(
        novel_id,
        [NodeType.EVENT, NodeType.CHARACTER],
    )

    # 过滤与 NPC 相关的节点（title 或 extra.participants 匹配）
    relevant = []
    for node in all_events:
        title = node.get("title", "")
        content = node.get("content", "")
        extra = node.get("extra", {})
        participants = extra.get("participants", []) if isinstance(extra, dict) else []

        if (npc_name in title or npc_name in content
                or npc_name in participants):
            relevant.append(node)

    # 按时间排序，取最近的
    relevant.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return relevant[:chapters_back * 10]
