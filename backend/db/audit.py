"""
用途: JSONL 审计追加写入（02-system-architecture.md §8 JSONL 归档）
用法: from backend.db.audit import append_audit_event
环境变量:
    ZERO_ARSENAL_AUDIT_DIR — 审计日志目录（默认 data/audit/）
MCP集成: 只追加，禁止修改或删除
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_AUDIT_DIR = Path(__file__).parent.parent / "data" / "audit"
_AUDIT_DIR: Path = Path(os.getenv("ZERO_ARSENAL_AUDIT_DIR", str(_DEFAULT_AUDIT_DIR)))


def _get_audit_file(session_id: str) -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _AUDIT_DIR / f"{session_id[:8]}_{date_str}.jsonl"


def append_audit_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """追加一条审计事件到 JSONL 文件（只追加，线程安全）。"""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "type": event_type,
        **payload,
    }
    audit_file = _get_audit_file(session_id)
    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[audit] JSONL append failed for {session_id[:8]}: {e}")


def append_turn_anchor(
    session_id: str,
    anchor_id: str,
    turn_index: int,
    turn_summary: str,
    state_delta: dict[str, Any] | None = None,
) -> None:
    """追加回合锚点审计记录。"""
    append_audit_event(
        session_id,
        "turn_anchor",
        {
            "anchor_id": anchor_id,
            "turn_index": turn_index,
            "turn_summary": turn_summary,
            "state_delta": state_delta or {},
        },
    )


def append_dice_roll(
    session_id: str,
    dice_expr: str,
    result: int,
    part_id: str = "",
) -> None:
    """追加骰子审计记录（可完整回放）。"""
    append_audit_event(
        session_id,
        "dice_roll",
        {
            "dice_expr": dice_expr,
            "result": result,
            "part_id": part_id,
        },
    )
