"""
MemoryEntry — Python dataclass 对应 memory_entries 表。
设计文档 06-data-model.md §5 + 08-memory-system.md §7.2
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MemoryEntry:
    """单条记忆条目，与 memory_entries 表对应（06-data-model.md §5.2 + 08-memory-system.md §7.2）。"""
    id: str
    session_id: str
    content: str
    tier: str = "episodic"              # episodic | semantic | core | working
    cognitive_partition: str = "objective_global"
                                        # objective_global | objective_local | world_state | relationship
    chapter_id: str = ""
    source_agent: str = ""
    embedding: Optional[bytes] = None  # float32 向量（二进制）
    bigram_tokens: list[str] = field(default_factory=list)
    graph_nodes: list[str] = field(default_factory=list)   # 关联实体 ID
    created_at: float = 0.0
    consolidated_at: Optional[float] = None
    # 06-data-model.md §5.2 / 08-memory-system.md §5.3 MemoryRecaller 补全字段
    importance: float = 0.5
    access_count: int = 0
    last_accessed_at: Optional[float] = None
    related_npcs: list[str] = field(default_factory=list)
    related_location: str = ""
    world_time: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "MemoryEntry":
        """从 SQLite Row 构造（兼容旧行缺列）。"""
        import json
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            content=row["content"],
            tier=row.get("tier", "episodic"),
            cognitive_partition=row.get("cognitive_partition", "objective_global"),
            chapter_id=row.get("chapter_id") or "",
            source_agent=row.get("source_agent") or "",
            embedding=row.get("embedding"),
            bigram_tokens=json.loads(row["bigram_tokens"]) if row.get("bigram_tokens") else [],
            graph_nodes=json.loads(row["graph_nodes"]) if row.get("graph_nodes") else [],
            created_at=float(row.get("created_at") or 0),
            consolidated_at=row.get("consolidated_at"),
            importance=float(row.get("importance") or 0.5),
            access_count=int(row.get("access_count") or 0),
            last_accessed_at=row.get("last_accessed_at"),
            related_npcs=json.loads(row["related_npcs"]) if row.get("related_npcs") else [],
            related_location=row.get("related_location") or "",
            world_time=row.get("world_time") or "",
        )

    def to_dict(self) -> dict:
        """序列化为 dict（embedding 转 Base64）。"""
        import base64
        return {
            "id": self.id,
            "session_id": self.session_id,
            "content": self.content,
            "tier": self.tier,
            "cognitive_partition": self.cognitive_partition,
            "chapter_id": self.chapter_id,
            "source_agent": self.source_agent,
            "embedding_b64": base64.b64encode(self.embedding).decode() if self.embedding else None,
            "bigram_tokens": self.bigram_tokens,
            "graph_nodes": self.graph_nodes,
            "created_at": self.created_at,
            "consolidated_at": self.consolidated_at,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "related_npcs": self.related_npcs,
            "related_location": self.related_location,
            "world_time": self.world_time,
        }

    @property
    def is_consolidated(self) -> bool:
        return self.consolidated_at is not None

    @property
    def word_count(self) -> int:
        return len(self.content)
