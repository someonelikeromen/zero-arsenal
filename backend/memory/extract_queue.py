"""
有界异步提取队列 — 防止记忆提取任务堆积
采用 asyncio.Queue 实现，最大容量由 EXTRACT_QUEUE_MAX 配置控制
"""
from __future__ import annotations

import asyncio
import re as _re
from typing import Optional, Callable
from loguru import logger


# ── 5W1H tier 分层（轨道 B 启发式兜底）──────────────────────────────────────────
# 集中定义，供 _process_task 与测试共享，避免在测试内重写同款逻辑（STUB-T10）。
CORE_KEYWORDS = ("突破", "死亡", "觉醒", "获得", "失去", "叛变", "盟约", "任务完成",
                 "境界", "武库", "宗师", "关键", "永久")
SEMANTIC_PATTERNS = _re.compile(
    r"(?:【|「|《)?([A-Z\u4e00-\u9fff]{2,8})(?:】|」|》)?"
    r"(?:\s*[-—是：:为]+\s*)(.{5,40})"
)

# tier → 认知分区映射
_TIER_PARTITION = {
    "core": "core_facts",
    "semantic": "world_knowledge",
    "episodic": "objective_global",
}


def determine_tier(para: str) -> str:
    """根据段落内容判定记忆 tier：core / semantic / episodic。"""
    if any(kw in para for kw in CORE_KEYWORDS):
        return "core"
    if SEMANTIC_PATTERNS.search(para):
        return "semantic"
    return "episodic"


class ExtractQueue:
    """
    有界异步记忆提取队列。
    工作模式：生产者（写作回合结束）→ 队列 → 消费者（后台 worker）
    防止大量短回合快速写入导致的提取任务堆积。
    """

    def __init__(self, max_size: int = 50):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._max_size = max_size
        self._dropped = 0     # 丢弃计数（队列满时）
        self._processed = 0   # 已处理计数

    async def start(self) -> None:
        """启动后台消费者 worker"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info(f"[ExtractQueue] 启动（最大容量 {self._max_size}）")

    async def stop(self) -> None:
        """停止队列，等待剩余任务完成"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info(
            f"[ExtractQueue] 停止：已处理 {self._processed}，"
            f"丢弃 {self._dropped}"
        )

    def enqueue(self, task: dict) -> bool:
        """
        非阻塞入队。
        task = {
            "novel_id": str,
            "world_key": str,
            "chapter_id": str,
            "messages": list[dict],
            "novel_config": dict,
        }
        Returns: True=入队成功, False=队列已满（任务被丢弃）
        """
        try:
            self._queue.put_nowait(task)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            logger.warning(
                f"[ExtractQueue] 队列已满（{self._max_size}），"
                f"丢弃任务 novel_id={task.get('novel_id','?')[:8]}，"
                f"累计丢弃 {self._dropped}"
            )
            return False

    async def _worker(self) -> None:
        """
        后台消费者循环。
        每个 task 格式：{session_id, chapter_id, narrative_text, world_plugin}
        """
        while self._running:
            try:
                task = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_task(task)
                self._processed += 1
                logger.debug(
                    f"[ExtractQueue] 完成 session={task.get('session_id','?')[:8]}, "
                    f"队列剩余={self._queue.qsize()}"
                )
            except Exception as e:
                logger.error(f"[ExtractQueue] 提取任务异常: {e}")
            finally:
                self._queue.task_done()

    async def _process_task(self, task: dict) -> None:
        """
        处理单个提取任务，双轨写入（08-memory-system.md §4）：

        轨道 A — LLM 图谱提取（生产主路径，C5-03/D5）：
          当任务携带 messages + novel_id 时，调用 memory_extractor.extract_and_persist，
          把 8 类结构化节点写入 NetworkX 图（+ 向量库，如可用），供 hybrid_recall 四级召回。
          图写入仅依赖 networkx（无 chromadb 也可工作），向量写入在依赖缺失时自动降级。

        轨道 B — 启发式 SQLite 兜底（5W1H 分层）：
          始终执行，把叙事分段写入 memory_entries（episodic/semantic/core），
          供 _fallback_recall 在无向量层时仍可关键词召回。
        """
        session_id     = task.get("session_id", "")
        chapter_id     = task.get("chapter_id", "")
        narrative_text = task.get("narrative_text", "")
        user_input     = task.get("user_input", "")
        source_agent   = task.get("source_agent", "narrator")

        # ── 轨道 A：LLM 图谱提取（生产路径）─────────────────────────────────
        await self._run_llm_extraction(task, session_id, chapter_id)

        if not session_id or not narrative_text.strip():
            return

        import uuid
        from datetime import datetime

        now = datetime.now().timestamp()
        paragraphs = [p.strip() for p in narrative_text.split("\n") if len(p.strip()) > 10]
        if not paragraphs:
            paragraphs = [narrative_text[:600]]

        try:
            from ..db import get_db
            async with get_db() as db:
                for para in paragraphs[:8]:  # 最多 8 段

                    # 判断 tier（共享模块级逻辑）
                    tier = determine_tier(para)
                    partition = _TIER_PARTITION[tier]

                    entry_id = str(uuid.uuid4())
                    await db.execute(
                        "INSERT OR IGNORE INTO memory_entries "
                        "(id, session_id, chapter_id, content, tier, "
                        "cognitive_partition, source_agent, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry_id, session_id, chapter_id, para[:800],
                         tier, partition, source_agent, now),
                    )

                # 额外写入：玩家指令本身作为 episodic 锚点
                if user_input.strip():
                    action_id = str(uuid.uuid4())
                    await db.execute(
                        "INSERT OR IGNORE INTO memory_entries "
                        "(id, session_id, chapter_id, content, tier, "
                        "cognitive_partition, source_agent, created_at) "
                        "VALUES (?, ?, ?, ?, 'episodic', 'player_action', 'player', ?)",
                        (action_id, session_id, chapter_id,
                         f"[玩家行动] {user_input[:300]}", now),
                    )

                await db.commit()

            # 阈值自动固化检查（08-memory-system.md §5.1）
            # 在事务提交后异步触发，不阻塞当前提取任务
            asyncio.create_task(
                self._maybe_auto_consolidate(session_id),
                name=f"auto-consolidate-{session_id[:8]}",
            )
        except Exception as e:
            logger.warning(f"[ExtractQueue] DB 写入失败: {e}")

    async def _run_llm_extraction(
        self, task: dict, session_id: str, chapter_id: str
    ) -> None:
        """
        调用 LLM 驱动的 memory_extractor，把对话提取为 8 类图谱节点（轨道 A）。
        仅当任务携带 messages 且能确定 novel_id 时执行；任何失败都不影响轨道 B。
        """
        messages = task.get("messages") or []
        novel_id = task.get("novel_id") or session_id
        if not messages or not novel_id:
            return
        try:
            from .extractor import memory_extractor
            created = await memory_extractor.extract_and_persist(
                novel_id=novel_id,
                world_key=task.get("world_key", ""),
                chapter_id=chapter_id,
                new_messages=messages,
                novel_config=task.get("novel_config") or {},
            )
            if created:
                logger.info(
                    f"[ExtractQueue] LLM 图谱提取写入 {len(created)} 个节点 "
                    f"(novel={str(novel_id)[:8]})"
                )
        except Exception as e:
            logger.warning(f"[ExtractQueue] LLM 图谱提取失败（降级至 SQLite 兜底）: {e}")

    async def _maybe_auto_consolidate(self, session_id: str) -> None:
        """触发阈值自动固化（独立 Task，失败不影响主流程）。"""
        try:
            from .chapter_consolidator import memory_consolidator
            result = await memory_consolidator.auto_consolidate_if_needed(session_id)
            if result.get("triggered"):
                logger.info(
                    f"[ExtractQueue] 阈值自动固化完成: "
                    f"chapter={result.get('chapter_id','?')[:8]} "
                    f"consolidated={result.get('result',{}).get('consolidated',0)}"
                )
        except Exception as e:
            logger.debug(f"[ExtractQueue] _maybe_auto_consolidate 失败（忽略）: {e}")

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> dict:
        return {
            "queue_size":   self._queue.qsize(),
            "max_size":     self._max_size,
            "processed":    self._processed,
            "dropped":      self._dropped,
            "running":      self._running,
        }


# ── 全局单例 ──────────────────────────────────────────────────────────────
extract_queue = ExtractQueue(max_size=50)


def get_extract_queue() -> ExtractQueue:
    """返回全局提取队列单例（消除 engine.py 脆弱的双重 import 回退，R-D11）。"""
    return extract_queue
