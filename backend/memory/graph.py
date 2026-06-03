"""
NetworkX 图操作层 — 精确对应 ST-BME graph.js 的 Python 移植
每本小说对应一个独立 JSON 图文件：data/graphs/{novel_id}.json
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx
from loguru import logger

from memory.schema import MemoryNode, NodeType, RelationType


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graphs_dir() -> Path:
    p = Path("data/graphs")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _graph_path(novel_id: str) -> Path:
    return _graphs_dir() / f"{novel_id}.json"


# ════════════════════════════════════════════════════════════════════════════
# NovelGraph — 单 novel 的内存图
# ════════════════════════════════════════════════════════════════════════════

class NovelGraph:
    """单本小说的 NetworkX 有向图包装器"""

    def __init__(self, novel_id: str):
        self.novel_id = novel_id
        self._G: nx.DiGraph = nx.DiGraph()
        self._path = _graph_path(novel_id)
        self._dirty = False

    # ── 持久化 ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """从 JSON 文件加载图（首次或重启时调用）"""
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self._G = nx.node_link_graph(data, directed=True, multigraph=False)
            logger.debug(f"[Graph:{self.novel_id}] 加载 {self._G.number_of_nodes()} 节点")
        else:
            self._G = nx.DiGraph()
            logger.debug(f"[Graph:{self.novel_id}] 新建空图")

    def save(self) -> None:
        """将图持久化到 JSON 文件"""
        data = nx.node_link_data(self._G)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._dirty = False
        logger.debug(f"[Graph:{self.novel_id}] 保存 {self._G.number_of_nodes()} 节点")

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    # ── 节点操作 ──────────────────────────────────────────────────────────

    def add_node(self, node: MemoryNode) -> None:
        """添加或更新节点"""
        node_dict = node.to_dict()
        node_dict["updated_at"] = _now()
        if not node_dict.get("created_at"):
            node_dict["created_at"] = _now()
        self._G.add_node(node.node_id, **node_dict)
        self._dirty = True
        logger.debug(f"[Graph:{self.novel_id}] 节点 +{node.node_id[:8]} ({node.node_type.value})")

    def update_node(self, node_id: str, **attrs) -> bool:
        """部分更新节点属性"""
        if node_id not in self._G:
            return False
        attrs["updated_at"] = _now()
        self._G.nodes[node_id].update(attrs)
        self._dirty = True
        return True

    def remove_node(self, node_id: str) -> bool:
        """删除节点及其所有关联边"""
        if node_id not in self._G:
            return False
        self._G.remove_node(node_id)
        self._dirty = True
        logger.debug(f"[Graph:{self.novel_id}] 节点 -{node_id[:8]}")
        return True

    def get_node(self, node_id: str) -> Optional[dict]:
        """获取单个节点的属性字典"""
        if node_id not in self._G:
            return None
        return dict(self._G.nodes[node_id])

    def get_nodes_by_type(
        self, node_types: list[NodeType], world_key: str = ""
    ) -> list[dict]:
        """按类型批量获取节点"""
        type_values = {t.value for t in node_types}
        result = []
        for nid, data in self._G.nodes(data=True):
            if data.get("node_type") not in type_values:
                continue
            if world_key and data.get("world_key") and data["world_key"] != world_key:
                continue
            result.append(dict(data))
        return result

    def get_nodes_created_after(self, chapter_created_at: str) -> list[str]:
        """获取在指定时间之后创建的节点 ID 列表（用于回滚）"""
        result = []
        for nid, data in self._G.nodes(data=True):
            created = data.get("created_at", "")
            if created > chapter_created_at:
                result.append(nid)
        return result

    def node_exists(self, node_id: str) -> bool:
        return node_id in self._G

    def node_count(self) -> int:
        return self._G.number_of_nodes()

    # ── 关系边操作 ────────────────────────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: RelationType,
        weight: float = 1.0,
        **attrs,
    ) -> bool:
        """添加有向关系边"""
        if source_id not in self._G or target_id not in self._G:
            logger.warning(
                f"[Graph:{self.novel_id}] 添加边失败：节点不存在 "
                f"({source_id[:8]} → {target_id[:8]})"
            )
            return False
        self._G.add_edge(
            source_id, target_id,
            relation=relation.value,
            weight=weight,
            created_at=_now(),
            **attrs,
        )
        self._dirty = True
        return True

    def remove_edge(self, source_id: str, target_id: str) -> bool:
        if self._G.has_edge(source_id, target_id):
            self._G.remove_edge(source_id, target_id)
            self._dirty = True
            return True
        return False

    def get_edges(self, node_id: str, direction: str = "out") -> list[dict]:
        """
        获取节点的边列表。
        direction: "out" = 出边，"in" = 入边，"both" = 全部
        """
        result = []
        if direction in ("out", "both"):
            for _, target, data in self._G.out_edges(node_id, data=True):
                result.append({"source": node_id, "target": target, **data})
        if direction in ("in", "both"):
            for source, _, data in self._G.in_edges(node_id, data=True):
                result.append({"source": source, "target": node_id, **data})
        return result

    # ── 图扩散（邻居召回）────────────────────────────────────────────────

    def get_neighbors(
        self,
        seed_node_ids: list[str],
        relation_types: list[str] = None,
        max_hops: int = 2,
    ) -> list[dict]:
        """
        从种子节点出发，沿指定关系边扩散召回邻居节点。
        对应 ST-BME retriever 中的图扩散步骤。
        """
        allowed_relations = set(relation_types) if relation_types else None
        visited: set[str] = set(seed_node_ids)
        frontier = list(seed_node_ids)
        result_nodes: list[dict] = []

        for _hop in range(max_hops):
            next_frontier: list[str] = []
            for nid in frontier:
                if nid not in self._G:
                    continue
                for _, neighbor, edge_data in self._G.out_edges(nid, data=True):
                    if neighbor in visited:
                        continue
                    rel = edge_data.get("relation", "")
                    if allowed_relations and rel not in allowed_relations:
                        continue
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
                    node_data = self.get_node(neighbor)
                    if node_data:
                        node_data["_hop"] = _hop + 1
                        result_nodes.append(node_data)
            frontier = next_frontier
            if not frontier:
                break

        return result_nodes

    # ── 统计与调试 ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for _, data in self._G.nodes(data=True):
            t = data.get("node_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total_nodes": self._G.number_of_nodes(),
            "total_edges": self._G.number_of_edges(),
            "by_type": type_counts,
        }

    def export_subgraph(self, node_ids: list[str]) -> dict:
        """导出指定节点的子图（调试用）"""
        sg = self._G.subgraph(node_ids)
        return nx.node_link_data(sg)


# ════════════════════════════════════════════════════════════════════════════
# GraphManager — 多小说图管理器（全局单例）
# ════════════════════════════════════════════════════════════════════════════

class GraphManager:
    """管理多本小说的 NovelGraph 实例（按需加载，LRU 缓存）"""

    _MAX_CACHE = 10   # 最多同时缓存10本小说的图

    def __init__(self):
        self._cache: dict[str, NovelGraph] = {}
        self._access_order: list[str] = []

    def _evict_if_needed(self) -> None:
        while len(self._cache) >= self._MAX_CACHE:
            oldest = self._access_order.pop(0)
            graph = self._cache.pop(oldest, None)
            if graph:
                graph.save_if_dirty()
                logger.debug(f"[GraphManager] 驱逐缓存: {oldest}")

    def get(self, novel_id: str) -> NovelGraph:
        """获取（或加载）指定小说的图"""
        if novel_id not in self._cache:
            self._evict_if_needed()
            g = NovelGraph(novel_id)
            g.load()
            self._cache[novel_id] = g
            self._access_order.append(novel_id)
        else:
            # LRU 更新
            self._access_order.remove(novel_id)
            self._access_order.append(novel_id)
        return self._cache[novel_id]

    async def add_node(self, novel_id: str, node: MemoryNode) -> None:
        g = self.get(novel_id)
        g.add_node(node)
        g.save()

    async def remove_nodes(self, novel_id: str, node_ids: list[str]) -> int:
        """批量删除节点（回滚用），返回实际删除数"""
        g = self.get(novel_id)
        removed = 0
        for nid in node_ids:
            if g.remove_node(nid):
                removed += 1
        if removed:
            g.save()
        return removed

    async def get_nodes_by_type(
        self, novel_id: str, node_types: list[NodeType], world_key: str = ""
    ) -> list[dict]:
        return self.get(novel_id).get_nodes_by_type(node_types, world_key)

    async def get_neighbors(
        self,
        novel_id: str,
        seed_node_ids: list[str],
        relation_types: list[str] = None,
        max_hops: int = 2,
    ) -> list[dict]:
        return self.get(novel_id).get_neighbors(seed_node_ids, relation_types, max_hops)

    async def add_edge(
        self,
        novel_id: str,
        source_id: str,
        target_id: str,
        relation: RelationType,
        **attrs,
    ) -> bool:
        g = self.get(novel_id)
        ok = g.add_edge(source_id, target_id, relation, **attrs)
        if ok:
            g.save()
        return ok

    def save_all(self) -> None:
        """保存所有脏图（关闭时调用）"""
        for g in self._cache.values():
            g.save_if_dirty()

    def get_stats(self, novel_id: str) -> dict:
        return self.get(novel_id).stats()


# ── 全局单例 ──────────────────────────────────────────────────────────────
graph_manager = GraphManager()
