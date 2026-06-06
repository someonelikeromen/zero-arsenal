"""
用途: 解析叙事中的 system_grant，处理 world_traverse 穿越落账
用法: from backend.engine.grant_parser import process_narrative_grants
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_GRANT_RE = re.compile(
    r"<system_grant\s+[^>]*type=[\"']world_traverse[\"'][^>]*>",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(r"target=[\"']([^\"']+)[\"']", re.IGNORECASE)


def extract_world_traverse_targets(text: str) -> list[str]:
    """从叙事文本提取 world_traverse grant 的 target 世界键。"""
    if not text:
        return []
    targets: list[str] = []
    for m in _GRANT_RE.finditer(text):
        tag = m.group(0)
        tm = _TARGET_RE.search(tag)
        if tm:
            t = tm.group(1).strip()
            if t and t not in targets:
                targets.append(t)
    return targets


async def apply_world_traverse(session_id: str, target_world_key: str) -> dict[str, Any]:
    """切换 sessions.active_world_key，并从全局世界复制档案到会话。"""
    from ..db import get_db
    from .world_keys import normalize_world_key

    target = normalize_world_key(target_world_key)
    if not target:
        return {"ok": False, "error": "empty target"}

    now = time.time()
    copied = 0
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT active_world_key FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        if not row:
            return {"ok": False, "error": "session not found"}
        prev = (dict(row).get("active_world_key") or "").strip()
        if prev == target:
            return {"ok": True, "changed": False, "active_world_key": target}

        await db.execute(
            "UPDATE sessions SET active_world_key=?, updated_at=? WHERE id=?",
            (target, now, session_id),
        )

        world_row = await (await db.execute(
            "SELECT id FROM worlds WHERE world_key=?", (target,)
        )).fetchone()
        if world_row:
            world_id = dict(world_row)["id"]
            archives = await (await db.execute(
                "SELECT * FROM world_archive_entries WHERE world_id=?", (world_id,)
            )).fetchall()
            for ar in archives:
                ard = dict(ar)
                new_id = str(uuid.uuid4())
                cur = await db.execute(
                    "INSERT OR IGNORE INTO world_archives "
                    "(id, session_id, title, content, archive_type, trigger_keywords, world_key, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id, session_id, ard["title"], ard["content"], ard["archive_type"],
                     ard.get("trigger_keywords", ""), target, now, now),
                )
                if cur.rowcount:
                    copied += 1

        await db.commit()

    return {
        "ok": True,
        "changed": True,
        "previous_world_key": prev,
        "active_world_key": target,
        "archives_copied": copied,
    }


async def process_narrative_grants(session_id: str, narrative_text: str) -> list[dict[str, Any]]:
    """处理叙事中全部 world_traverse grant，返回每次落账结果。"""
    results: list[dict[str, Any]] = []
    for target in extract_world_traverse_targets(narrative_text):
        try:
            res = await apply_world_traverse(session_id, target)
            results.append(res)
        except Exception as e:
            logger.warning("[grant_parser] world_traverse failed: %s", e)
            results.append({"ok": False, "target": target, "error": str(e)})
    return results
