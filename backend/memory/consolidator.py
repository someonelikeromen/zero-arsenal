"""
层级压缩/遗忘系统 — 按阈值触发 event→synopsis 压缩
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from memory.schema import (
    MemoryNode,
    NodeType,
    RelationType,
    TemporalBucket,
    CONSOLIDATION_CONFIG,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uid() -> str:
    return str(uuid.uuid4())


class MemoryConsolidator:
    """
    层级压缩服务。
    当同章节 event 节点数量超过阈值时，将其压缩为 synopsis 节点。
    由 Chronicler 在章节固化时或 Planner 在章节开始时异步触发。
    """

    async def check_and_consolidate(
        self, novel_id: str, world_key: str, chapter_id: str
    ) -> int:
        """检查并执行压缩。返回压缩删除的节点数。"""
        from memory.graph import graph_manager
        g = graph_manager.get(novel_id)

        # 获取当前章节的 event 节点
        chapter_events = [
            data for _, data in g._G.nodes(data=True)
            if (data.get("node_type") == NodeType.EVENT.value
                and data.get("chapter_id") == chapter_id
                and data.get("world_key", "") == world_key)
        ]

        threshold = CONSOLIDATION_CONFIG["event_to_synopsis"]["threshold"]
        if len(chapter_events) < threshold:
            return 0

        logger.info(
            f"[Consolidator:{novel_id}] 触发压缩：章节 {chapter_id} "
            f"有 {len(chapter_events)} 个事件节点（阈值 {threshold}）"
        )

        removed = await self._consolidate_events(
            novel_id=novel_id,
            world_key=world_key,
            chapter_id=chapter_id,
            events=chapter_events,
        )
        return removed

    async def _consolidate_events(
        self,
        novel_id: str,
        world_key: str,
        chapter_id: str,
        events: list[dict],
    ) -> int:
        """
        将多个 event 节点压缩为一个 synopsis 节点。
        保留重要性最高的 N 条，其余删除。
        """
        from memory.graph import graph_manager
        from memory.vector import vector_manager
        from utils.llm_client import get_llm_client, get_embedding_client

        keep_n = CONSOLIDATION_CONFIG["event_to_synopsis"]["keep_top_n"]

        # 按重要性降序排列
        events_sorted = sorted(
            events, key=lambda x: x.get("importance", 0.5), reverse=True
        )
        to_keep   = events_sorted[:keep_n]
        to_remove = events_sorted[keep_n:]

        if not to_remove:
            return 0

        # 获取所有事件内容，交给 LLM 生成章节摘要
        event_texts = "\n".join(
            f"- {e.get('title', '')}: {e.get('summary', e.get('content',''))[:100]}"
            for e in events_sorted
        )

        try:
            llm = get_llm_client()
            synopsis_content = await llm.chat(
                messages=[
                    {"role": "system", "content":
                        "你是一个叙事摘要员。将给定的事件列表压缩成一段简洁的章节摘要。"
                        "保留关键信息，去掉冗余细节。100字以内。"},
                    {"role": "user", "content": f"请压缩以下事件：\n{event_texts}"},
                ],
                role="calibrator",
                temperature=0.3,
                max_tokens=512,
            )
        except Exception as e:
            logger.warning(f"[Consolidator] LLM 摘要失败: {e}，使用拼接摘要")
            synopsis_content = event_texts[:500]

        # 创建 synopsis 节点
        synopsis_node = MemoryNode(
            node_id=_uid(),
            novel_id=novel_id,
            node_type=NodeType.SYNOPSIS,
            world_key=world_key,
            title=f"第{chapter_id[-4:] if len(chapter_id) > 4 else chapter_id}章摘要",
            content=synopsis_content,
            summary=synopsis_content[:100],
            temporal_bucket=TemporalBucket.ADJACENT_PAST,
            chapter_id=chapter_id,
            created_at=_now(),
            updated_at=_now(),
            confidence=0.9,
            importance=0.8,
            extra={"consolidated_from": [e.get("node_id","") for e in to_remove]},
        )

        await graph_manager.add_node(novel_id, synopsis_node)

        # 向量嵌入
        try:
            emb_client = get_embedding_client()
            emb = await emb_client.embed(synopsis_node.content)
            from memory.vector import vector_manager
            await vector_manager.upsert_node(novel_id, synopsis_node, emb)
        except Exception as e:
            logger.warning(f"[Consolidator] 摘要节点向量化失败: {e}")

        # 删除被压缩的事件节点
        remove_ids = [e.get("node_id", "") for e in to_remove if e.get("node_id")]
        removed_count = await graph_manager.remove_nodes(novel_id, remove_ids)
        await vector_manager.delete_nodes(novel_id, remove_ids)

        logger.info(
            f"[Consolidator:{novel_id}] 压缩完成：删除 {removed_count} 个事件节点，"
            f"生成 synopsis {synopsis_node.node_id[:8]}"
        )
        return removed_count


# ── 全局单例 ──────────────────────────────────────────────────────────────
memory_consolidator = MemoryConsolidator()
