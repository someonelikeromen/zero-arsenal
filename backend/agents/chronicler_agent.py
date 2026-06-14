"""
ChroniclerAgent — 章节固化与记忆压缩。
每回合：写入 chapter_anchors 增量记录 + JSONL 审计追加 + SSE turn_complete。
每 CHAPTER_TURN_THRESHOLD 轮：生成全量章节摘要写入 chapters 表。
"""
from __future__ import annotations
import uuid
import json
import logging
from datetime import datetime
from .state import TurnContext
from .llm import llm_complete, load_agent_config
from ..bus import bus, BusEvent, EventType
from ..db.schema import PartType
from ..db.audit import append_turn_anchor

logger = logging.getLogger(__name__)

CHAPTER_TURN_THRESHOLD = 10


CONSOLIDATE_SYSTEM = """\
你是跑团小说的史官。将以下场景片段压缩成一段 150-200 字的章节摘要。
要求：
- 第三人称叙事视角
- 记录关键事件、人物关系变化、状态改变
- 不包含主观评价
- 最后一句点明本章核心转折或悬念
"""


async def _last_consolidated_boundary_ts(db, session_id: str) -> float:
    """返回最后一个已固化章节 end_message 的 created_at 时间戳（无则 0）。"""
    row = await (await db.execute(
        "SELECT m.created_at AS ts FROM chapters c "
        "JOIN messages m ON m.id = c.end_message_id "
        "WHERE c.session_id=? AND c.is_consolidated=1 AND c.end_message_id IS NOT NULL "
        "ORDER BY m.created_at DESC LIMIT 1",
        (session_id,)
    )).fetchone()
    return float(row["ts"]) if row and row["ts"] is not None else 0.0


async def should_consolidate(session_id: str) -> bool:
    """检查「上次固化边界之后」累积的消息数是否达到阈值（NEW-C2-03）。"""
    try:
        from ..db import get_db
        async with get_db() as db:
            boundary_ts = await _last_consolidated_boundary_ts(db, session_id)
            row = await db.execute(
                "SELECT COUNT(*) as cnt FROM messages "
                "WHERE session_id=? AND created_at > ?",
                (session_id, boundary_ts)
            )
            cnt = (await row.fetchone())["cnt"]
        return cnt >= CHAPTER_TURN_THRESHOLD
    except Exception:
        return False


async def _write_turn_anchor(ctx: TurnContext) -> str:
    """每回合写入 chapter_anchors 增量记录，返回 anchor_id。"""
    anchor_id = str(uuid.uuid4())
    now = datetime.now().timestamp()

    # 取本回合叙事文本（最近一条 narrative part）
    narrative_text = ""
    try:
        from ..db import get_db
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT content FROM message_parts "
                "WHERE session_id=? AND type='narrative' AND status='done' "
                "AND message_id=? ORDER BY created_at DESC LIMIT 1",
                (ctx.session_id, ctx.message_id)
            )).fetchone()
            if row:
                narrative_text = json.loads(row["content"]).get("text", "")
    except Exception:
        pass

    # 取当前 turn_index（已有 anchors 数 + 1）
    turn_index = 0
    current_chapter_id: str | None = None
    try:
        from ..db import get_db
        async with get_db() as db:
            cnt_row = await (await db.execute(
                "SELECT COUNT(*) as cnt FROM chapter_anchors WHERE session_id=?",
                (ctx.session_id,)
            )).fetchone()
            turn_index = (cnt_row["cnt"] if cnt_row else 0) + 1

            # 获取最近未固化章节 ID
            chap_row = await (await db.execute(
                "SELECT id FROM chapters WHERE session_id=? AND is_consolidated=0 "
                "ORDER BY created_at DESC LIMIT 1",
                (ctx.session_id,)
            )).fetchone()
            current_chapter_id = chap_row["id"] if chap_row else None

            await db.execute(
                "INSERT INTO chapter_anchors "
                "(id, session_id, chapter_id, message_id, turn_index, turn_summary, state_delta, narrative_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (anchor_id, ctx.session_id, current_chapter_id,
                 ctx.message_id, turn_index,
                 narrative_text[:100] if narrative_text else "",
                 json.dumps(getattr(ctx, "state_delta", {}), ensure_ascii=False),
                 narrative_text, now)
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"[chronicler] turn_anchor write failed: {e}")

    # JSONL 审计追加（非阻塞，失败不影响主流程）
    try:
        append_turn_anchor(
            session_id=ctx.session_id,
            anchor_id=anchor_id,
            turn_index=turn_index,
            turn_summary=narrative_text[:100] if narrative_text else "",
        )
    except Exception:
        pass

    # 发布 turn_complete SSE（02-system-architecture.md §8）
    try:
        await bus.publish(BusEvent(
            type=EventType.TURN_COMPLETE,
            session_id=ctx.session_id,
            data={"anchor_id": anchor_id, "turn_index": turn_index},
        ))
    except Exception as e:
        logger.debug(f"[chronicler] turn_complete publish failed: {e}")

    return anchor_id


async def chronicler_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点 — 每轮写 anchor；达到阈值时额外执行章节固化。"""
    # 每回合写入增量锚点
    anchor_id = await _write_turn_anchor(ctx)
    logger.debug(f"[chronicler] anchor {anchor_id[:8]} written for turn of {ctx.session_id[:8]}")

    if not await should_consolidate(ctx.session_id):
        return ctx

    logger.info(f"Consolidating chapter for session {ctx.session_id[:8]}")

    # 计算本章消息边界（上次固化之后的窗口）
    boundary_ts = 0.0
    start_message_id: str | None = None
    end_message_id: str | None = None
    try:
        from ..db import get_db
        async with get_db() as db:
            boundary_ts = await _last_consolidated_boundary_ts(db, ctx.session_id)
            start_row = await (await db.execute(
                "SELECT id FROM messages WHERE session_id=? AND created_at>? "
                "ORDER BY created_at ASC LIMIT 1",
                (ctx.session_id, boundary_ts)
            )).fetchone()
            end_row = await (await db.execute(
                "SELECT id FROM messages WHERE session_id=? AND created_at>? "
                "ORDER BY created_at DESC LIMIT 1",
                (ctx.session_id, boundary_ts)
            )).fetchone()
            start_message_id = start_row["id"] if start_row else None
            end_message_id = end_row["id"] if end_row else None
    except Exception as e:
        logger.warning(f"[chronicler] boundary calc failed: {e}")

    # 取本章窗口（上次固化之后）的 narrative Parts（NEW-C2-04：按边界过滤，避免跨章重叠）
    narrative_texts = await _get_recent_narratives(ctx.session_id, after_ts=boundary_ts)
    if not narrative_texts:
        return ctx

    combined = "\n\n".join(narrative_texts)
    summary = await _generate_summary(combined)
    if not summary:
        return ctx

    now = datetime.now().timestamp()
    chapter_id = str(uuid.uuid4())

    try:
        from ..db import get_db
        async with get_db() as db:
            # 获取当前会话的 branch_label
            sess_row = await (await db.execute(
                "SELECT branch_label FROM sessions WHERE id=?", (ctx.session_id,)
            )).fetchone()
            branch_label = (sess_row["branch_label"] if sess_row else None) or "main"

            # 获取当前章节序号（已有多少个已固化章节）
            count_row = await (await db.execute(
                "SELECT COUNT(*) as cnt FROM chapters WHERE session_id=? AND is_consolidated=1",
                (ctx.session_id,)
            )).fetchone()
            chapter_index = (count_row["cnt"] if count_row else 0) + 1

            # 获取上一章节 ID（作为 parent_chapter_id）
            prev_row = await (await db.execute(
                "SELECT id FROM chapters WHERE session_id=? AND is_consolidated=1 "
                "ORDER BY created_at DESC LIMIT 1",
                (ctx.session_id,)
            )).fetchone()
            parent_chapter_id = prev_row["id"] if prev_row else None

            # 更新或创建章节记录（写入分支字段）
            existing = await (await db.execute(
                "SELECT id FROM chapters WHERE session_id=? AND is_consolidated=0 ORDER BY created_at LIMIT 1",
                (ctx.session_id,)
            )).fetchone()

            if existing:
                chapter_id = existing["id"]
                await db.execute(
                    "UPDATE chapters SET is_consolidated=1, summary=?, updated_at=?, "
                    "branch_label=?, chapter_index=?, parent_chapter_id=?, "
                    "start_message_id=?, end_message_id=? WHERE id=?",
                    (summary, now, branch_label, chapter_index, parent_chapter_id,
                     start_message_id, end_message_id, chapter_id)
                )
            else:
                await db.execute(
                    "INSERT INTO chapters (id, session_id, is_consolidated, summary, "
                    "branch_label, chapter_index, parent_chapter_id, "
                    "start_message_id, end_message_id, created_at, updated_at) "
                    "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chapter_id, ctx.session_id, summary,
                     branch_label, chapter_index, parent_chapter_id,
                     start_message_id, end_message_id, now, now)
                )

            # 写入记忆条目（semantic 层）
            mem_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO memory_entries (id, session_id, chapter_id, content, tier, "
                "cognitive_partition, source_agent, created_at) VALUES (?, ?, ?, ?, 'semantic', "
                "'objective_global', 'chronicler', ?)",
                (mem_id, ctx.session_id, chapter_id, summary, now)
            )
            await db.commit()
    except Exception as e:
        logger.warning(f"Chronicler DB write failed: {e}")
        return ctx

    # 章节固化后触发 5W1H ExtractQueue 分析（非阻塞，后台处理）
    try:
        from ..memory.extract_queue import extract_queue
        # 携带 novel_id/world_key/messages → 章节摘要也进 LLM 图谱提取（轨道A），
        # 而非仅 SQLite 启发式（轨道B）。messages 用章节摘要构造单条 assistant 消息。
        extract_queue.enqueue({
            "session_id": ctx.session_id,
            "novel_id": ctx.session_id,
            "world_key": getattr(ctx, "plugin_key", "") or "",
            "chapter_id": chapter_id,
            "narrative_text": summary,
            "messages": [{"role": "assistant", "content": summary}],
            "user_input": "",
            "source_agent": "chronicler",
        })
        logger.debug(f"[chronicler] 5W1H extract enqueued for chapter {chapter_id[:8]}")
    except Exception as e:
        logger.debug(f"[chronicler] enqueue_extraction skipped: {e}")

    # 发布 chapter_end Part
    part_id = str(uuid.uuid4())
    content = {"chapter_id": chapter_id, "summary": summary}
    try:
        from ..db import get_db
        async with get_db() as db:
            await db.execute(
                "INSERT INTO message_parts (id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'done', 'chronicler', ?, ?)",
                (part_id, ctx.message_id, ctx.session_id,
                 PartType.CHAPTER_END, json.dumps(content, ensure_ascii=False), now, now)
            )
            await db.commit()
    except Exception:
        pass

    await bus.publish_part_created(
        ctx.session_id, part_id, PartType.CHAPTER_END, ctx.message_id, "chronicler"
    )
    await bus.publish_part_done(ctx.session_id, part_id, content)

    # 发布 chapter.consolidated SSE（前端 ChapterTree 监听刷新）
    await bus.publish(BusEvent(
        type=EventType.CHAPTER_CONSOLIDATED,
        session_id=ctx.session_id,
        data={"chapter_id": chapter_id, "summary_length": len(summary)},
    ))

    # 调用 ChapterConsolidator 执行 episodic → semantic 压缩
    try:
        from ..memory.chapter_consolidator import memory_consolidator
        result = await memory_consolidator.consolidate_chapter(
            session_id=ctx.session_id,
            chapter_id=chapter_id,
        )
        logger.debug(f"Consolidator result: {result}")
    except Exception as e:
        logger.debug(f"memory_consolidator.consolidate_chapter skipped: {e}")

    logger.info(f"Chapter consolidated: {chapter_id[:8]} ({len(summary)} chars)")
    return ctx


async def _get_recent_narratives(
    session_id: str, limit: int = 50, after_ts: float = 0.0
) -> list[str]:
    """取未固化窗口（created_at > after_ts）内的 narrative Parts，按时间升序拼接。"""
    try:
        from ..db import get_db
        async with get_db() as db:
            rows = await db.execute(
                "SELECT content FROM message_parts "
                "WHERE session_id=? AND type='narrative' AND status='done' "
                "AND created_at > ? "
                "ORDER BY created_at ASC LIMIT ?",
                (session_id, after_ts, limit)
            )
            return [json.loads(r["content"]).get("text", "") for r in await rows.fetchall()]
    except Exception:
        return []


async def _generate_summary(combined_text: str) -> str:
    cfg = load_agent_config("chronicler")
    try:
        return await llm_complete(
            messages=[
                {"role": "system", "content": CONSOLIDATE_SYSTEM},
                {"role": "user", "content": combined_text[:3000]},
            ],
            provider=cfg.get("provider", "deepseek"),
            model=cfg.get("model", "deepseek-chat"),
            temperature=cfg.get("temperature", 0.4),
            max_tokens=cfg.get("max_tokens", 512),
        )
    except Exception as e:
        logger.warning(f"Chronicler LLM failed: {e}")
        # 返回最简摘要而非空字符串，确保章节记录有内容
        lines = [l.strip() for l in combined_text.splitlines() if l.strip()]
        preview = " ".join(lines[:5])[:200]
        return f"[自动摘要] {preview}…" if preview else "[章节内容生成失败]"


async def get_chapter_context(session_id: str, limit: int = 3) -> str:
    """获取最近 N 个已固化章节的摘要（供叙事上下文使用）。"""
    try:
        from ..db import get_db
        async with get_db() as db:
            rows = await db.execute(
                "SELECT summary FROM chapters WHERE session_id=? AND is_consolidated=1 "
                "AND summary != '' ORDER BY created_at DESC LIMIT ?",
                (session_id, limit)
            )
            summaries = [r["summary"] for r in await rows.fetchall()]
        return "\n---\n".join(reversed(summaries)) if summaries else ""
    except Exception:
        return ""
