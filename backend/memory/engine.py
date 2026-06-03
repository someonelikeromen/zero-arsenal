"""
记忆引擎统一入口 — MemoryEngine 门面类
汇聚 graph/vector/retriever/extractor 的对外接口
"""
from __future__ import annotations

from memory.schema import MemoryNode, NodeType, RelationType
from memory.graph import graph_manager
from memory.vector import vector_manager
from memory.retriever import hybrid_recall, get_npc_recent_behavior
from memory.extractor import memory_extractor
from memory.consolidator import memory_consolidator
from memory.rollback import memory_rollback
try:
    from memory.extract_queue import get_extract_queue  # type: ignore
except ImportError:
    # 使用零度武库内置队列
    from backend.memory.extract_queue import extract_queue as _eq
    def get_extract_queue():
        return _eq


class MemoryEngine:
    """
    记忆引擎门面（Facade）。
    Agent 只需通过此类与记忆系统交互，屏蔽内部复杂性。
    """

    # ── 读取（召回）─────────────────────────────────────────────────────────

    async def recall(
        self,
        novel_id: str,
        world_key: str,
        query_text: str,
        protagonist_location: str = "",
        viewer_agent: str = "chronicler",
        top_k: int = 15,
    ) -> dict:
        """混合召回（core + recalled 两层）"""
        return await hybrid_recall(
            novel_id=novel_id,
            world_key=world_key,
            query_text=query_text,
            protagonist_location=protagonist_location,
            viewer_agent=viewer_agent,
            top_k=top_k,
        )

    async def get_npc_behavior(
        self, novel_id: str, npc_name: str, chapters_back: int = 3
    ) -> list[dict]:
        """NPC 近期行为召回"""
        return await get_npc_recent_behavior(novel_id, npc_name, chapters_back)

    # ── 写入（提取）─────────────────────────────────────────────────────────

    def enqueue_extraction(
        self,
        novel_id: str,
        world_key: str,
        chapter_id: str,
        messages: list[dict],
        novel_config: dict = None,
    ) -> bool:
        """将提取任务加入后台队列（非阻塞）"""
        queue = get_extract_queue()
        # 对齐 extract_queue._process_task 所需字段：session_id / narrative_text
        narrative_text = "\n".join(
            m.get("content", "")
            for m in messages
            if m.get("role") in ("assistant", "narrator")
        )
        user_input = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        return queue.enqueue({
            "session_id":    novel_id,        # novel_id 在 session 体系中即 session_id
            "novel_id":      novel_id,        # 保留供 full extractor 使用
            "world_key":     world_key,
            "chapter_id":    chapter_id,
            "narrative_text": narrative_text,
            "user_input":    user_input,
            "messages":      messages,
            "novel_config":  novel_config or {},
            "source_agent":  "memory_engine",
        })

    async def extract_sync(
        self,
        novel_id: str,
        world_key: str,
        chapter_id: str,
        messages: list[dict],
        novel_config: dict = None,
    ) -> list[str]:
        """同步提取（测试/调试用）"""
        return await memory_extractor.extract_and_persist(
            novel_id=novel_id,
            world_key=world_key,
            chapter_id=chapter_id,
            new_messages=messages,
            novel_config=novel_config or {},
        )

    # ── 压缩 ─────────────────────────────────────────────────────────────────

    async def consolidate(
        self, novel_id: str, world_key: str, chapter_id: str
    ) -> int:
        """触发层级压缩（章节固化时调用）"""
        return await memory_consolidator.check_and_consolidate(
            novel_id, world_key, chapter_id
        )

    # ── 回滚 ─────────────────────────────────────────────────────────────────

    async def rollback(
        self,
        novel_id: str,
        chapter_id: str,
        chapter_created_at: str,
    ) -> dict:
        """回滚指定章节后的脏节点"""
        return await memory_rollback.rollback_chapter(
            novel_id, chapter_id, chapter_created_at
        )

    # ── 调试/统计 ────────────────────────────────────────────────────────────

    def get_graph_stats(self, novel_id: str) -> dict:
        return graph_manager.get_stats(novel_id)

    def get_queue_stats(self) -> dict:
        return get_extract_queue().stats

    async def update_protagonist_node(self, novel_id: str, payload: dict) -> None:
        """更新图中的主角 character 节点（ItemType on_purchase 调用）"""
        protagonist_name = payload.get("protagonist_name", "")
        if not protagonist_name:
            return
        graph = graph_manager.get(novel_id)
        # 查找现有主角节点
        for nid, data in graph._G.nodes(data=True):
            if (data.get("node_type") == NodeType.CHARACTER.value
                    and data.get("extra", {}).get("is_protagonist")):
                graph.update_node(nid, content=str(payload))
                graph.save()
                return


# ── 全局单例 ──────────────────────────────────────────────────────────────
memory_engine = MemoryEngine()
