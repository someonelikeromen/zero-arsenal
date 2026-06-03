"""
ChromaDB 向量存储层
每本小说×世界观对应一个 Collection: novel_{novel_id}_{world_key}
备选后端: FAISS（当 VECTOR_BACKEND=faiss 时）
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from loguru import logger

from memory.schema import MemoryNode


# ════════════════════════════════════════════════════════════════════════════
# 抽象向量存储接口
# ════════════════════════════════════════════════════════════════════════════

class VectorStore:
    """向量存储的统一接口（ChromaDB / FAISS 均实现此接口）"""

    async def upsert(self, node: MemoryNode, embedding: list[float]) -> None:
        raise NotImplementedError

    async def upsert_batch(
        self, nodes: list[MemoryNode], embeddings: list[list[float]]
    ) -> None:
        for node, emb in zip(nodes, embeddings):
            await self.upsert(node, emb)

    async def query(
        self,
        embedding: list[float],
        n_results: int = 20,
        world_key: str = "",
        filter_types: list[str] = None,
    ) -> list[dict]:
        raise NotImplementedError

    async def delete(self, node_ids: list[str]) -> None:
        raise NotImplementedError

    async def get_collection_count(self) -> int:
        raise NotImplementedError


# ════════════════════════════════════════════════════════════════════════════
# ChromaDB 实现
# ════════════════════════════════════════════════════════════════════════════

class ChromaVectorStore(VectorStore):
    """
    基于 ChromaDB 的向量存储。
    每本小说对应集合名：novel_{novel_id}（跨世界存一个集合，world_key 作 metadata 过滤）
    """

    def __init__(self, novel_id: str, chroma_path: str):
        self.novel_id = novel_id
        self._chroma_path = chroma_path
        self._client = None
        self._collection = None

    def _get_client(self):
        if self._client is None:
            import chromadb
            path = Path(self._chroma_path)
            path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(path))
        return self._client

    def _get_collection(self, world_key: str = ""):
        # 每本小说统一用一个 Collection，world_key 在 metadata 中区分
        col_name = f"novel_{self.novel_id}"
        if self._collection is None or self._collection.name != col_name:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=col_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def upsert(self, node: MemoryNode, embedding: list[float]) -> None:
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, self._upsert_sync, node, embedding
        )

    def _upsert_sync(self, node: MemoryNode, embedding: list[float]) -> None:
        col = self._get_collection()
        metadata = node.metadata_dict()
        # ChromaDB 不接受 None 值
        metadata = {k: (v if v is not None else "") for k, v in metadata.items()}
        col.upsert(
            ids=[node.node_id],
            documents=[node.content or node.summary or node.title],
            embeddings=[embedding],
            metadatas=[metadata],
        )

    async def upsert_batch(
        self, nodes: list[MemoryNode], embeddings: list[list[float]]
    ) -> None:
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, self._upsert_batch_sync, nodes, embeddings
        )

    def _upsert_batch_sync(
        self, nodes: list[MemoryNode], embeddings: list[list[float]]
    ) -> None:
        if not nodes:
            return
        col = self._get_collection()
        ids, docs, embs, metas = [], [], [], []
        for node, emb in zip(nodes, embeddings):
            ids.append(node.node_id)
            docs.append(node.content or node.summary or node.title)
            embs.append(emb)
            meta = {k: (v if v is not None else "") for k, v in node.metadata_dict().items()}
            metas.append(meta)
        col.upsert(ids=ids, documents=docs, embeddings=embs, metadatas=metas)

    async def query(
        self,
        embedding: list[float],
        n_results: int = 20,
        world_key: str = "",
        filter_types: list[str] = None,
    ) -> list[dict]:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._query_sync, embedding, n_results, world_key, filter_types
        )

    def _query_sync(
        self,
        embedding: list[float],
        n_results: int,
        world_key: str,
        filter_types: Optional[list[str]],
    ) -> list[dict]:
        col = self._get_collection()
        total = col.count()
        if total == 0:
            return []

        n = min(n_results, total)
        where: Optional[dict] = None
        if world_key and filter_types:
            where = {"$and": [
                {"world_key": {"$eq": world_key}},
                {"node_type": {"$in": filter_types}},
            ]}
        elif world_key:
            where = {"world_key": {"$eq": world_key}}
        elif filter_types:
            where = {"node_type": {"$in": filter_types}}

        query_kwargs = dict(
            query_embeddings=[embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        if where:
            query_kwargs["where"] = where

        results = col.query(**query_kwargs)

        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append({
                "content":  doc,
                "metadata": meta,
                "distance": dist,
                "score":    1.0 - dist,  # cosine distance → similarity
            })
        return hits

    async def delete(self, node_ids: list[str]) -> None:
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None, self._delete_sync, node_ids
        )

    def _delete_sync(self, node_ids: list[str]) -> None:
        if not node_ids:
            return
        col = self._get_collection()
        col.delete(ids=node_ids)
        logger.debug(f"[ChromaDB:{self.novel_id}] 删除 {len(node_ids)} 条向量")

    async def get_collection_count(self) -> int:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._get_collection().count()
        )


# ════════════════════════════════════════════════════════════════════════════
# FAISS 备选实现（当 chromadb 不可用时）
# ════════════════════════════════════════════════════════════════════════════

class FAISSVectorStore(VectorStore):
    """
    FAISS + JSON 元数据 的轻量向量存储。
    数据路径：data/faiss/{novel_id}/
    """

    def __init__(self, novel_id: str, data_path: str = "data/faiss"):
        self.novel_id = novel_id
        self._dir = Path(data_path) / novel_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.faiss"
        self._meta_path  = self._dir / "metadata.json"
        self._index = None
        self._meta: list[dict] = []  # [{node_id, content, metadata}]
        self._load()

    def _load(self):
        try:
            import faiss, json, numpy as np
            if self._index_path.exists():
                self._index = faiss.read_index(str(self._index_path))
            if self._meta_path.exists():
                with open(self._meta_path, encoding="utf-8") as f:
                    self._meta = json.load(f)
        except ImportError:
            logger.warning("[FAISS] faiss-cpu 未安装，向量存储不可用")

    def _save(self):
        try:
            import faiss, json
            if self._index:
                faiss.write_index(self._index, str(self._index_path))
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(self._meta, f, ensure_ascii=False)
        except ImportError:
            pass

    async def upsert(self, node: MemoryNode, embedding: list[float]) -> None:
        try:
            import faiss, numpy as np
            emb_np = np.array([embedding], dtype=np.float32)
            faiss.normalize_L2(emb_np)

            if self._index is None:
                self._index = faiss.IndexFlatIP(len(embedding))

            # 移除旧记录
            self._meta = [m for m in self._meta if m.get("node_id") != node.node_id]

            self._index.add(emb_np)
            self._meta.append({
                "node_id":  node.node_id,
                "content":  node.content or node.title,
                "metadata": node.metadata_dict(),
                "index":    len(self._meta),
            })
            self._save()
        except ImportError:
            logger.warning("[FAISS] 无法写入向量（faiss-cpu 未安装）")

    async def query(
        self,
        embedding: list[float],
        n_results: int = 20,
        world_key: str = "",
        filter_types: list[str] = None,
    ) -> list[dict]:
        if self._index is None or not self._meta:
            return []
        try:
            import faiss, numpy as np
            emb_np = np.array([embedding], dtype=np.float32)
            faiss.normalize_L2(emb_np)
            k = min(n_results * 3, len(self._meta))
            scores, indices = self._index.search(emb_np, k)

            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._meta):
                    continue
                m = self._meta[idx]
                meta = m.get("metadata", {})
                if world_key and meta.get("world_key") and meta["world_key"] != world_key:
                    continue
                if filter_types and meta.get("node_type") not in filter_types:
                    continue
                results.append({
                    "content":  m["content"],
                    "metadata": meta,
                    "score":    float(score),
                })
                if len(results) >= n_results:
                    break
            return results
        except ImportError:
            return []

    async def delete(self, node_ids: list[str]) -> None:
        self._meta = [m for m in self._meta if m.get("node_id") not in node_ids]
        self._save()

    async def get_collection_count(self) -> int:
        return len(self._meta)


# ════════════════════════════════════════════════════════════════════════════
# VectorStoreManager — 多小说向量存储管理器（全局单例）
# ════════════════════════════════════════════════════════════════════════════

class VectorStoreManager:
    """按需创建/缓存 VectorStore 实例"""

    def __init__(self):
        self._stores: dict[str, VectorStore] = {}
        self._backend: Optional[str] = None
        self._chroma_path: Optional[str] = None

    def _init_settings(self):
        if self._backend is None:
            from config import get_settings
            s = get_settings()
            self._backend = s.vector_backend
            self._chroma_path = s.chromadb_path

    def get(self, novel_id: str) -> VectorStore:
        self._init_settings()
        if novel_id not in self._stores:
            if self._backend == "faiss":
                self._stores[novel_id] = FAISSVectorStore(novel_id)
            else:
                try:
                    self._stores[novel_id] = ChromaVectorStore(
                        novel_id, self._chroma_path
                    )
                except Exception as e:
                    logger.warning(f"[VectorStore] ChromaDB 初始化失败：{e}，降级到 FAISS")
                    self._stores[novel_id] = FAISSVectorStore(novel_id)
        return self._stores[novel_id]

    async def upsert_node(
        self, novel_id: str, node: MemoryNode, embedding: list[float]
    ) -> None:
        await self.get(novel_id).upsert(node, embedding)

    async def upsert_batch(
        self, novel_id: str, nodes: list[MemoryNode], embeddings: list[list[float]]
    ) -> None:
        await self.get(novel_id).upsert_batch(nodes, embeddings)

    async def delete_nodes(self, novel_id: str, node_ids: list[str]) -> None:
        await self.get(novel_id).delete(node_ids)

    async def query(
        self,
        novel_id: str,
        embedding: list[float],
        n_results: int = 20,
        world_key: str = "",
        filter_types: list[str] = None,
    ) -> list[dict]:
        return await self.get(novel_id).query(
            embedding, n_results, world_key, filter_types
        )


# ── 全局单例 ──────────────────────────────────────────────────────────────
vector_manager = VectorStoreManager()
