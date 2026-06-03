"""
回滚系统 — 清除指定章节后创建的脏节点（图/向量/同步状态三套联动）
"""
from __future__ import annotations

from loguru import logger


class MemoryRollback:
    """
    记忆图谱回滚服务。
    当写作回合需要撤销时，清除对应章节的所有记忆节点。
    由 Chronicler / DM 调用（通过 RollbackManifest 中的指令）。
    """

    async def rollback_chapter(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_created_at: str,
    ) -> dict:
        """
        删除 chapter_created_at 之后创建的所有记忆节点。

        Args:
            novel_id: 小说ID
            chapter_id: 要撤销的章节ID
            chapter_created_at: 该章节创建时间（ISO格式），用于确定脏节点边界

        Returns:
            {"graph_removed": int, "vector_removed": int}
        """
        from memory.graph import graph_manager
        from memory.vector import vector_manager
        from db.queries import get_db

        db = get_db()

        # 1. 从图中找出该时间后创建的节点
        graph = graph_manager.get(novel_id)
        dirty_ids = graph.get_nodes_created_after(chapter_created_at)

        if not dirty_ids:
            logger.info(f"[Rollback:{novel_id}] 无需回滚，没有脏节点")
            return {"graph_removed": 0, "vector_removed": 0}

        logger.info(
            f"[Rollback:{novel_id}] 准备回滚 {len(dirty_ids)} 个脏节点 "
            f"（章节 {chapter_id}，时间 {chapter_created_at}）"
        )

        # 2. 删除图节点
        graph_removed = await graph_manager.remove_nodes(novel_id, dirty_ids)

        # 3. 删除向量
        try:
            await vector_manager.delete_nodes(novel_id, dirty_ids)
            vector_removed = len(dirty_ids)
        except Exception as e:
            logger.error(f"[Rollback] 向量删除失败: {e}")
            vector_removed = 0

        # 4. 清除 node_sync_status 记录
        try:
            for nid in dirty_ids:
                await db._exec(
                    "DELETE FROM node_sync_status WHERE novel_id=? AND node_id=?",
                    (novel_id, nid),
                )
        except Exception as e:
            logger.warning(f"[Rollback] 同步状态清除失败: {e}")

        logger.info(
            f"[Rollback:{novel_id}] 完成：图={graph_removed}, 向量={vector_removed}"
        )
        return {"graph_removed": graph_removed, "vector_removed": vector_removed}

    async def restore_character_node(
        self,
        novel_id: str,
        character_name: str,
        pre_chapter_snapshot: dict,
    ) -> bool:
        """
        恢复角色节点至回滚前快照（用于撤销角色状态变更）。
        """
        from memory.graph import graph_manager
        from memory.schema import MemoryNode, NodeType
        import uuid
        from datetime import datetime, timezone

        try:
            node = MemoryNode(
                node_id=str(uuid.uuid4()),
                novel_id=novel_id,
                node_type=NodeType.CHARACTER,
                world_key=pre_chapter_snapshot.get("world_key", ""),
                title=character_name,
                content=pre_chapter_snapshot.get("content", ""),
                summary=pre_chapter_snapshot.get("summary", ""),
                confidence=1.0,
                importance=0.8,
                extra=pre_chapter_snapshot.get("extra", {}),
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            await graph_manager.add_node(novel_id, node)
            return True
        except Exception as e:
            logger.error(f"[Rollback] 角色节点恢复失败 {character_name}: {e}")
            return False

    async def rollback_by_time(self, novel_id: str, since_iso: str) -> dict:
        """
        按时间戳回滚：删除 since_iso 之后创建的所有记忆图谱节点和向量。
        用于对话轮次级别的回滚（区别于章节级别的 rollback_chapter）。

        Args:
            novel_id:  小说ID
            since_iso: ISO8601 时间戳（快照创建时间），删除此时间之后的节点

        Returns:
            {"graph_removed": int, "vector_removed": int}
        """
        from memory.graph import graph_manager
        from memory.vector import vector_manager
        from db.queries import get_db

        db = get_db()

        graph = graph_manager.get(novel_id)
        dirty_ids = graph.get_nodes_created_after(since_iso)

        if not dirty_ids:
            logger.info(f"[Rollback:{novel_id}] 时间回滚：无脏节点（since={since_iso}）")
            return {"graph_removed": 0, "vector_removed": 0}

        logger.info(
            f"[Rollback:{novel_id}] 时间回滚 {len(dirty_ids)} 个节点（since={since_iso}）"
        )

        graph_removed = await graph_manager.remove_nodes(novel_id, dirty_ids)

        vector_removed = 0
        try:
            await vector_manager.delete_nodes(novel_id, dirty_ids)
            vector_removed = len(dirty_ids)
        except Exception as e:
            logger.error(f"[Rollback] 向量删除失败: {e}")

        try:
            for nid in dirty_ids:
                await db._exec(
                    "DELETE FROM node_sync_status WHERE novel_id=? AND node_id=?",
                    (novel_id, nid),
                )
        except Exception as e:
            logger.warning(f"[Rollback] 同步状态清除失败: {e}")

        logger.info(
            f"[Rollback:{novel_id}] 时间回滚完成：图={graph_removed}, 向量={vector_removed}"
        )
        return {"graph_removed": graph_removed, "vector_removed": vector_removed}


# ── 全局单例 ──────────────────────────────────────────────────────────────
memory_rollback = MemoryRollback()
