"""
ChapterConsolidator — 轻量章节记忆压缩适配器。
设计文档 08-memory-system.md §5（记忆层级压缩）

在章节固化时由 ChroniclerAgent 调用，将 episodic tier 记忆
标记为 consolidated，并生成 semantic tier 摘要节点。

阈值触发：episodic 记忆超过 AUTO_CONSOLIDATE_THRESHOLD 条时，
自动对最旧的未固化章节执行固化（08-memory-system.md §5.1 阈值触发）。

当完整图引擎可用时尝试调用它；否则仅做 SQLite 层标记。
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 08-memory-system.md §9.1 auto_consolidate_threshold
AUTO_CONSOLIDATE_THRESHOLD = 100


class ChapterConsolidator:
    """章节记忆压缩服务（单例）。"""

    async def consolidate_chapter(
        self, session_id: str, chapter_id: str
    ) -> dict:
        """
        将该章节的 episodic 记忆条目标记为 consolidated，
        并尝试合并为 semantic 摘要节点。

        返回：{"consolidated": N, "semantic_entry_id": str | None}
        """
        from ..db import get_db
        now = datetime.now().timestamp()
        consolidated_count = 0
        semantic_id: str | None = None

        try:
            async with get_db() as db:
                # 1. 找出该章节的 episodic 未固化记忆
                rows = await (await db.execute(
                    "SELECT id, content FROM memory_entries "
                    "WHERE session_id=? AND chapter_id=? "
                    "AND tier='episodic' AND consolidated_at IS NULL",
                    (session_id, chapter_id)
                )).fetchall()

                if not rows:
                    return {"consolidated": 0, "semantic_entry_id": None}

                ids = [r["id"] for r in rows]
                texts = [r["content"] for r in rows]

                # 2. 标记为已固化
                placeholders = ",".join("?" * len(ids))
                await db.execute(
                    f"UPDATE memory_entries SET consolidated_at=? WHERE id IN ({placeholders})",
                    [now] + ids
                )
                consolidated_count = len(ids)

                # 3. 生成 semantic 摘要（调用 LLM，失败时简单拼接）
                combined = "\n".join(f"- {t[:120]}" for t in texts[:15])
                summary_text = await self._summarize(combined)

                # 4. 写入 semantic tier 记忆条目
                semantic_id = str(uuid.uuid4())
                await db.execute(
                    "INSERT INTO memory_entries "
                    "(id, session_id, chapter_id, content, tier, cognitive_partition, "
                    "source_agent, created_at) "
                    "VALUES (?, ?, ?, ?, 'semantic', 'objective_global', 'consolidator', ?)",
                    (semantic_id, session_id, chapter_id, summary_text, now)
                )
                await db.commit()

        except Exception as e:
            logger.warning(f"[ChapterConsolidator] session={session_id[:8]} failed: {e}")
            return {"consolidated": 0, "semantic_entry_id": None}

        logger.info(
            f"[ChapterConsolidator] session={session_id[:8]} chapter={chapter_id[:8]}: "
            f"consolidated {consolidated_count} episodic → 1 semantic"
        )
        return {"consolidated": consolidated_count, "semantic_entry_id": semantic_id}

    async def _summarize(self, text: str) -> str:
        """LLM 摘要，失败返回截断原文。"""
        try:
            from ..agents.llm import llm_complete
            return await llm_complete(
                messages=[
                    {"role": "system", "content":
                        "将以下记忆条目压缩成一段 80 字以内的客观摘要。保留关键事件、人物、状态变化。"},
                    {"role": "user", "content": text[:2000]},
                ],
                provider="deepseek",
                model="deepseek-chat",
                temperature=0.3,
                max_tokens=200,
            )
        except Exception:
            return text[:400]


    async def auto_consolidate_if_needed(self, session_id: str) -> dict:
        """
        阈值触发自动固化（08-memory-system.md §5.1）。
        若会话内未固化 episodic 条数 >= AUTO_CONSOLIDATE_THRESHOLD，
        自动对最旧的未固化章节执行一次 consolidate_chapter()。

        返回：{"triggered": bool, "chapter_id": str | None, "result": dict}
        """
        from ..db import get_db
        try:
            async with get_db() as db:
                # 统计未固化 episodic 总数
                count_row = await (await db.execute(
                    "SELECT COUNT(*) as cnt FROM memory_entries "
                    "WHERE session_id=? AND tier='episodic' AND consolidated_at IS NULL",
                    (session_id,)
                )).fetchone()
                count = count_row["cnt"] if count_row else 0

                if count < AUTO_CONSOLIDATE_THRESHOLD:
                    return {"triggered": False, "chapter_id": None, "result": {}}

                # 找最旧的含未固化 episodic 的章节
                oldest_row = await (await db.execute(
                    "SELECT chapter_id FROM memory_entries "
                    "WHERE session_id=? AND tier='episodic' AND consolidated_at IS NULL "
                    "AND chapter_id IS NOT NULL AND chapter_id != '' "
                    "GROUP BY chapter_id ORDER BY MIN(created_at) ASC LIMIT 1",
                    (session_id,)
                )).fetchone()

            if not oldest_row:
                return {"triggered": False, "chapter_id": None, "result": {}}

            chapter_id = oldest_row["chapter_id"]
            logger.info(
                f"[ChapterConsolidator] 阈值触发（{count}>={AUTO_CONSOLIDATE_THRESHOLD}）"
                f" session={session_id[:8]} 最旧章节={chapter_id[:8]}"
            )
            result = await self.consolidate_chapter(session_id, chapter_id)
            return {"triggered": True, "chapter_id": chapter_id, "result": result}

        except Exception as e:
            logger.warning(f"[ChapterConsolidator] auto_consolidate 失败: {e}")
            return {"triggered": False, "chapter_id": None, "result": {}}


# 全局单例
memory_consolidator = ChapterConsolidator()
