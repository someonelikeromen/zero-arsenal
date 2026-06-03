"""
内置 Hook 实现。

内置两个 hook：
1. log_turn_hook   — before_turn 事件，记录回合开始日志（debug level）
2. error_alert_hook — on_error 事件，记录错误到 event_log 表
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .hook_manager import HookDef, HookEvent, hook_manager

logger = logging.getLogger(__name__)


# ── 内置 Hook 1：回合开始日志 ─────────────────────────────────────────────────

async def _log_turn_handler(context: dict) -> dict:
    """记录回合开始的调试日志。"""
    session_id = context.get("session_id", "unknown")
    turn = context.get("turn", "?")
    agent = context.get("agent", "?")
    logger.debug(
        f"[HookEvent.before_turn] session={session_id} turn={turn} agent={agent} "
        f"ts={datetime.now(timezone.utc).isoformat()}"
    )
    return context


log_turn_hook = HookDef(
    id="builtin.log_turn",
    event=HookEvent.before_turn,
    handler=_log_turn_handler,
    priority=10,
    description="记录每回合开始的调试信息",
)


# ── 内置 Hook 2：错误写入 event_log ─────────────────────────────────────────

async def _error_alert_handler(context: dict) -> dict:
    """将错误信息记录到数据库 event_log 表。"""
    error = context.get("error", "")
    session_id = context.get("session_id", "")
    agent = context.get("agent", "unknown")

    logger.error(f"[HookEvent.on_error] session={session_id} agent={agent} error={error}")

    # 尝试写入数据库，失败时静默跳过（hook 不应该级联崩溃）
    try:
        import uuid, json
        from ..db.connection import get_db

        async with get_db() as db:
            await db.execute(
                "INSERT INTO event_log (id, session_id, type, data_json, created_at) "
                "VALUES (?, ?, 'agent.error', ?, ?)",
                (
                    str(uuid.uuid4()),
                    session_id,
                    json.dumps({"agent": agent, "error": error}, ensure_ascii=False),
                    datetime.now(timezone.utc).timestamp(),
                ),
            )
            await db.commit()
    except Exception as exc:
        logger.debug(f"error_alert_hook: 写入 event_log 失败 — {exc}")

    return context


error_alert_hook = HookDef(
    id="builtin.error_alert",
    event=HookEvent.on_error,
    handler=_error_alert_handler,
    priority=20,
    description="将错误事件记录到数据库 event_log 表",
)


# ── 自动注册 ─────────────────────────────────────────────────────────────────

def register_builtin_hooks() -> None:
    """注册所有内置 hook 到全局 hook_manager。"""
    hook_manager.register(log_turn_hook)
    hook_manager.register(error_alert_hook)
    logger.debug("builtin_hooks: 内置 hook 注册完成")


# 模块被 import 时自动注册
register_builtin_hooks()
