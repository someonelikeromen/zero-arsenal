"""
Dice Node — 在 DM 请求骰子时执行判定并发布 dice_roll Part。
"""
from __future__ import annotations
import uuid
import json
from datetime import datetime
from .state import TurnContext
from ..engine import RollRequest, compute_roll_request, log_roll
from ..bus import bus
from ..db.schema import PartType


async def dice_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点 — 执行骰子判定（仅当 roll_request 非 None 时触发）。"""
    if not ctx.roll_request:
        return ctx

    req = RollRequest(**ctx.roll_request)
    result = compute_roll_request(req)
    log_roll(result, ctx.session_id, ctx.message_id)

    ctx.roll_result = result.model_dump()

    # 写 DB（仅在有有效 session_id 时）
    now = datetime.now().timestamp()
    part_id = str(uuid.uuid4())
    ctx.dice_part_id = part_id
    content = result.model_dump()

    if ctx.session_id and ctx.message_id:
        from ..db import get_db
        try:
            async with get_db() as db:
                dice_id = str(uuid.uuid4())
                await db.execute(
                    "INSERT INTO dice_log (id, session_id, message_id, pool, threshold, rolls, net, verdict, "
                    "attribute, skill, reason, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (dice_id, ctx.session_id, ctx.message_id,
                     result.pool, result.threshold,
                     json.dumps(result.rolls),
                     result.net, result.verdict,
                     result.attribute, result.skill, result.reason,
                     json.dumps(content, ensure_ascii=False), now)
                )
                await db.execute(
                    "INSERT INTO message_parts (id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'done', 'dice', ?, ?)",
                    (part_id, ctx.message_id, ctx.session_id,
                     PartType.DICE_ROLL, json.dumps(content, ensure_ascii=False), now, now)
                )
                await db.commit()
        except Exception:
            pass  # 不因 DB 失败阻断游戏流程

    # 发布事件
    await bus.publish_part_created(
        ctx.session_id, part_id, PartType.DICE_ROLL, ctx.message_id, "dice"
    )
    await bus.publish_part_done(ctx.session_id, part_id, content)

    return ctx
