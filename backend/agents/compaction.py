"""
Compaction — 当 context token 接近上限时，压缩历史对话。
来自 05-prompt-architecture.md §7.3

触发条件：估算 token 数 > COMPACT_THRESHOLD（默认 3000）
压缩方式：
  1. 从 DB 取最近 20 条 narrative Parts 文本
  2. 调用 LLM（chronicler 配置）生成 300 字内摘要
  3. 将摘要注入 ctx.memory_context 前缀
  4. 写 compaction Part 到 DB 和 Bus
"""
from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime

from .state import TurnContext

logger = logging.getLogger(__name__)

COMPACT_THRESHOLD = 3000   # 估算 token 超过此值才触发
# NEW-C3-03：压缩后保留的「近期上下文」尾部字符数。摘要覆盖的较早历史段
# 会被截断丢弃，只保留最近这段原文 + 摘要，确保净 token 下降而非上升。
COMPACT_KEEP_TAIL_CHARS = 1200
SUMMARY_SYSTEM = """\
你是叙事摘要助手。请将以下历史叙事段落压缩为 300 字以内的中文摘要，
保留关键事件、人物状态和场景背景，去除重复细节。
只输出摘要正文，不加标题或说明。"""


async def maybe_compact(ctx: TurnContext) -> TurnContext:
    """
    检查当前上下文 token 估算量，超阈值时压缩历史叙事并更新 ctx.memory_context。
    失败时记录 error 并返回原始 ctx。
    """
    try:
        from ..prompts.token_budget import token_budget

        total_text = (
            (ctx.memory_context or "")
            + (ctx.narrative_text or "")
            + ctx.character_data.get("meta", {}).get("session_notes", "")
        )
        estimated = token_budget.estimate_tokens(total_text)

        if estimated < COMPACT_THRESHOLD:
            return ctx

        logger.info(
            f"[Compaction] session={ctx.session_id} estimated_tokens={estimated} "
            f">= {COMPACT_THRESHOLD}，触发压缩"
        )

        # conf_b04：触发 before_memory_compress（扩展可中止压缩或调整阈值上下文）
        try:
            from ..hooks import hook_manager, HookEvent
            _bmc = await hook_manager.fire(HookEvent.before_memory_compress, {
                "session_id": ctx.session_id,
                "estimated_tokens": estimated,
                "threshold": COMPACT_THRESHOLD,
                "proceed": True,
            })
            if _bmc.get("proceed") is False:
                logger.info("[Compaction] before_memory_compress hook 取消本次压缩")
                return ctx
        except Exception as _e:
            logger.debug("[Compaction] before_memory_compress hook failed: %s", _e)

        # 从 DB 取最近 20 条 narrative Parts
        narrative_texts = await _fetch_recent_narratives(ctx.session_id, limit=20)
        if not narrative_texts:
            return ctx

        combined = "\n\n".join(narrative_texts)

        # 调用 LLM 生成摘要
        summary = await _summarize(combined)
        if not summary:
            return ctx

        # NEW-C3-03：实际裁剪历史，而非单纯前缀追加（旧实现只会净增 token）。
        # 用「摘要 + 最近尾部原文」替换原有 memory_context：较早的、已被摘要
        # 覆盖的历史段被丢弃，仅保留最近 COMPACT_KEEP_TAIL_CHARS 字符的连续上下文。
        compaction_block = f"[历史摘要]\n{summary}"
        prev_context = ctx.memory_context or ""
        before_tokens = token_budget.estimate_tokens(prev_context)
        if len(prev_context) > COMPACT_KEEP_TAIL_CHARS:
            tail = prev_context[-COMPACT_KEEP_TAIL_CHARS:]
            ctx.memory_context = compaction_block + "\n\n[近期上下文]\n" + tail
        elif prev_context:
            ctx.memory_context = compaction_block + "\n\n" + prev_context
        else:
            ctx.memory_context = compaction_block
        after_tokens = token_budget.estimate_tokens(ctx.memory_context)

        # 写 compaction Part 到 DB 和 Bus
        await _write_compaction_part(ctx, summary)

        logger.info(
            "[Compaction] session=%s 压缩完成，摘要 %d 字，memory_context token %d → %d",
            ctx.session_id, len(summary), before_tokens, after_tokens,
        )

    except Exception as exc:
        logger.error("[Compaction] 压缩失败: %s", exc, exc_info=True)

    return ctx


async def _fetch_recent_narratives(session_id: str, limit: int = 20) -> list[str]:
    """从 DB 拉取最近 N 条 narrative Parts 的文本内容。"""
    try:
        from ..db import get_db
        from ..db.schema import PartType

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT content FROM message_parts "
                "WHERE session_id=? AND type=? AND status='done' "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, PartType.NARRATIVE, limit),
            )
            rows = await cursor.fetchall()

        texts: list[str] = []
        for (raw,) in reversed(rows):  # 时间正序
            try:
                obj = json.loads(raw) if isinstance(raw, str) else raw
                text = obj.get("text", "") if isinstance(obj, dict) else str(obj)
                if text:
                    texts.append(text)
            except Exception:
                pass
        return texts
    except Exception as exc:
        logger.warning(f"[Compaction] 拉取叙事记录失败: {exc}")
        return []


async def _summarize(combined_text: str) -> str:
    """调用 LLM（chronicler 配置）将历史叙事压缩为 300 字摘要。"""
    try:
        from .llm import llm_complete, load_agent_config

        cfg = load_agent_config("chronicler")
        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": combined_text[:6000]},  # 防止超 context
        ]
        summary = await llm_complete(
            messages,
            provider=cfg.get("provider", "deepseek"),
            model=cfg.get("model", "deepseek-chat"),
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 600),
        )
        return summary.strip()
    except Exception as exc:
        logger.warning(f"[Compaction] LLM 摘要失败: {exc}")
        return ""


async def _write_compaction_part(ctx: TurnContext, summary: str) -> None:
    """将压缩摘要写入 DB 的 message_parts 表，并发布 Bus 事件。"""
    try:
        from ..db import get_db
        from ..db.schema import PartType
        from ..bus import bus

        part_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        content = json.dumps({"summary": summary}, ensure_ascii=False)

        async with get_db() as db:
            await db.execute(
                "INSERT INTO message_parts "
                "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'done', 'narrator', ?, ?)",
                (
                    part_id,
                    ctx.message_id,
                    ctx.session_id,
                    PartType.COMPACTION,
                    content,
                    now,
                    now,
                ),
            )
            await db.commit()

        await bus.publish_part_created(
            ctx.session_id, part_id, PartType.COMPACTION, ctx.message_id, "narrator"
        )
        await bus.publish_part_done(ctx.session_id, part_id, {"summary": summary})

    except Exception as exc:
        logger.warning(f"[Compaction] 写入 Part 失败（静默）: {exc}")
