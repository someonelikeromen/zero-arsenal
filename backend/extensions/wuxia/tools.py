"""
武侠世界插件 — 扩展工具集示例。
TOOLS 列表会被 _discover_extension_tools() 自动注册到 ToolRegistry。
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime

try:
    from ...tools.registry import ToolDef
except ImportError:
    from backend.tools.registry import ToolDef  # type: ignore[no-redef]


async def _cultivate(session_id: str, technique: str = "吐纳基础法", duration: int = 1) -> dict:
    """
    执行修炼行为：消耗时间（in-world），提升内力值（meta.inner_force）。
    每次修炼消耗 duration 个时间单位，内力提升 duration * 10 点（上限 9999）。
    """
    from ...db import get_db
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}
            char = json.loads(row["data_json"])
            meta: dict = char.setdefault("meta", {})
            inner_force = int(meta.get("inner_force", 0))
            gain = duration * 10
            meta["inner_force"] = min(9999, inner_force + gain)
            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )
            await db.execute(
                "INSERT OR IGNORE INTO memory_entries "
                "(id, session_id, content, tier, cognitive_partition, source_agent, created_at) "
                "VALUES (?, ?, ?, 'episodic', 'player_action', 'tool:cultivate', ?)",
                (str(uuid.uuid4()), session_id,
                 f"修炼【{technique}】{duration}个时辰，内力 {inner_force} → {meta['inner_force']}",
                 now)
            )
            await db.commit()
    except Exception as e:
        return {"error": str(e)}
    return {
        "ok": True,
        "technique": technique,
        "inner_force_before": inner_force,
        "inner_force_after": meta["inner_force"],
        "duration": duration,
    }


async def _inner_power_circulate(
    session_id: str,
    technique: str = "小周天循环",
    cycles: int = 1,
) -> dict:
    """
    内力运转：根据已修炼的功法运转一个/多个小周天。
    每个周天回复 inner_force 消耗量（通用公式：cycles × 5），
    同时将修炼状态记录到世界档案。
    """
    from ...db import get_db
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}
            char = json.loads(row["data_json"])
            meta: dict = char.setdefault("meta", {})
            inner_before = int(meta.get("inner_force", 0))
            recovery = cycles * 5
            inner_after = min(9999, inner_before + recovery)
            meta["inner_force"] = inner_after
            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )
            await db.execute(
                "INSERT OR IGNORE INTO memory_entries "
                "(id, session_id, content, tier, cognitive_partition, source_agent, created_at) "
                "VALUES (?, ?, ?, 'episodic', 'player_action', 'tool:inner_power_circulate', ?)",
                (str(uuid.uuid4()), session_id,
                 f"运转【{technique}】{cycles} 个周天，内力 {inner_before} → {inner_after}",
                 now)
            )
            await db.commit()
        return {
            "ok": True,
            "technique": technique,
            "cycles": cycles,
            "inner_force_before": inner_before,
            "inner_force_after": inner_after,
            "recovery": recovery,
        }
    except Exception as e:
        return {"error": str(e)}


async def _query_sects(sect_name: str = "") -> dict:
    """
    查询武侠世界门派信息，读取 data/sects-catalog.json。
    sect_name 为空时返回所有门派列表；提供名称则返回该门派详情。
    """
    from pathlib import Path
    catalog_path = Path(__file__).parent / "data" / "sects-catalog.json"
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        sects = data.get("sects", [])
        if sect_name:
            match = next(
                (s for s in sects if s.get("name") == sect_name or s.get("id") == sect_name), None
            )
            if not match:
                return {"ok": False, "error": f"未找到门派：{sect_name}"}
            return {"ok": True, "sect": match}
        return {"ok": True, "sects": sects, "total": len(sects)}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[wuxia] sects-catalog.json 加载失败: {e}")
        return {"ok": False, "error": str(e)}


async def _query_techniques(technique_name: str = "", sect_id: str = "") -> dict:
    """
    查询武侠世界武功/功法信息，读取 data/techniques-catalog.json。
    可按名称精确查找或按门派 ID 筛选。
    """
    from pathlib import Path
    catalog_path = Path(__file__).parent / "data" / "techniques-catalog.json"
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        techniques = data.get("techniques", [])
        if technique_name:
            match = next(
                (t for t in techniques if t.get("name") == technique_name or t.get("id") == technique_name), None
            )
            if not match:
                return {"ok": False, "error": f"未找到武功：{technique_name}"}
            return {"ok": True, "technique": match}
        if sect_id:
            filtered = [t for t in techniques if t.get("sect_id") == sect_id or t.get("sect") == sect_id]
            return {"ok": True, "techniques": filtered, "total": len(filtered)}
        return {"ok": True, "techniques": techniques, "total": len(techniques)}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[wuxia] techniques-catalog.json 加载失败: {e}")
        return {"ok": False, "error": str(e)}


async def _spar_challenge(
    session_id: str,
    opponent_key: str,
    opponent_level: int = 1,
    outcome: str = "",
) -> dict:
    """
    发起/接受切磋挑战。
    根据结果更新江湖名望（CHARM）：胜利+15/平局+5/负局-5。
    记录切磋事件到世界档案。
    """
    import random as _random
    from ...db import get_db
    now = datetime.now().timestamp()

    # 若未提供 outcome，使用骰子逻辑决定胜负
    if not outcome:
        player_roll  = _random.randint(1, 20)
        opponent_roll = _random.randint(1, max(1, opponent_level * 2))
        if player_roll > opponent_roll:
            outcome = "win"
        elif player_roll == opponent_roll:
            outcome = "draw"
        else:
            outcome = "lose"
    else:
        player_roll  = None
        opponent_roll = None

    charm_delta = {"win": 15, "draw": 5, "lose": -5}.get(outcome, 0)
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}
            char = json.loads(row["data_json"])
            meta: dict = char.setdefault("meta", {})
            charm_before = int(meta.get("wuxia_charm", 0))
            charm_after = max(0, charm_before + charm_delta)
            meta["wuxia_charm"] = charm_after
            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )
            # 写入世界档案
            await db.execute(
                "INSERT INTO world_archives "
                "(id, session_id, title, content, archive_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'lore', ?, ?)",
                (
                    str(uuid.uuid4()), session_id,
                    f"切磋记录：{opponent_key}",
                    json.dumps({
                        "opponent": opponent_key,
                        "opponent_level": opponent_level,
                        "outcome": outcome,
                        "charm_change": charm_delta,
                        "timestamp": now,
                    }, ensure_ascii=False),
                    now, now,
                )
            )
            await db.commit()
        result = {
            "ok": True,
            "opponent": opponent_key,
            "outcome": outcome,
            "charm_before": charm_before,
            "charm_after": charm_after,
            "charm_delta": charm_delta,
        }
        if player_roll is not None:
            result["dice"] = {"player": player_roll, "opponent": opponent_roll}
        return result
    except Exception as e:
        return {"error": str(e)}


TOOLS: list[ToolDef] = [
    ToolDef(
        name="cultivate",
        description="【武侠专属】进行内力修炼，提升角色内力（inner_force）属性。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "technique":  {"type": "string", "description": "修炼功法名称", "default": "吐纳基础法"},
                "duration":   {"type": "integer", "description": "修炼时长（时辰），1~8", "default": 1},
            },
            "required": ["session_id"],
        },
        handler=_cultivate,
        permission_required="allow",
        tags=["write", "character", "wuxia"],
        group="wuxia",
    ),
    ToolDef(
        name="inner_power_circulate",
        description=(
            "【武侠专属】运转内力小周天，恢复消耗的内力值。"
            "适合战斗后调息或修炼间隙运功恢复。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string",  "description": "会话 ID"},
                "technique":  {"type": "string",  "description": "运转功法名", "default": "小周天循环"},
                "cycles":     {"type": "integer", "description": "运转周天数（1~9）", "default": 1},
            },
            "required": ["session_id"],
        },
        handler=_inner_power_circulate,
        permission_required="allow",
        tags=["write", "character", "wuxia"],
        group="wuxia",
    ),
    ToolDef(
        name="spar_challenge",
        description=(
            "【武侠专属】发起或接受切磋挑战，根据结果更新江湖名望（wuxia_charm）。"
            "outcome: win（胜）/ draw（平）/ lose（负）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id":     {"type": "string",  "description": "会话 ID"},
                "opponent_key":   {"type": "string",  "description": "对手标识（如 sect_elder）"},
                "opponent_level": {"type": "integer", "description": "对手武功等级 1-10", "default": 1},
                "outcome":        {"type": "string",  "description": "切磋结果 win/draw/lose（留空则自动骰子判定）", "default": ""},
            },
            "required": ["session_id", "opponent_key"],
        },
        handler=_spar_challenge,
        permission_required="allow",
        tags=["write", "social", "wuxia"],
        group="wuxia",
    ),
    ToolDef(
        name="query_sects",
        display_name="查询门派",
        description="【武侠专属】查询武侠世界的门派信息，读取 sects-catalog.json。可按名称精确查找。",
        parameters={
            "type": "object",
            "properties": {
                "sect_name": {"type": "string", "description": "门派名称或 ID（不填则返回全部门派）"},
            },
            "required": [],
        },
        handler=_query_sects,
        permission_required="allow",
        tags=["read", "world", "wuxia"],
        group="wuxia",
    ),
    ToolDef(
        name="query_techniques",
        display_name="查询武功",
        description="【武侠专属】查询武功/功法信息，读取 techniques-catalog.json。可按名称或门派筛选。",
        parameters={
            "type": "object",
            "properties": {
                "technique_name": {"type": "string", "description": "武功名称或 ID（可选）"},
                "sect_id":        {"type": "string", "description": "按门派 ID 筛选（可选）"},
            },
            "required": [],
        },
        handler=_query_techniques,
        permission_required="allow",
        tags=["read", "world", "wuxia"],
        group="wuxia",
    ),
]
