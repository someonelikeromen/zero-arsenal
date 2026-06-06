"""
Gundam SEED 世界专属工具
实现 SEED 世界的协调者能力检定和 MS 战斗状态查询。
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path

from ...tools.registry import ToolDef, tool_registry

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"


# ── 协调者能力激活检定 ─────────────────────────────────────────────────────────

async def _coordinator_check(
    session_id: str,
    ability: str = "combat",
    difficulty: int = 3,
) -> dict:
    """
    对协调者特化能力进行检定。
    能力类型：combat（战斗）/ piloting（驾驶）/ analysis（分析）/ coordination（协调）
    难度 1-5，越高越难。
    """
    from ...db import get_db

    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id,)
            )).fetchone()

        char = json.loads(row["data_json"]) if row else {}
        attributes = char.get("attributes", {})

        # 协调者能力加成（根据属性计算基础值）
        attr_map = {
            "combat": attributes.get("STR", 3),
            "piloting": attributes.get("DEX", 3),
            "analysis": attributes.get("INT", 3),
            "coordination": attributes.get("WIS", 3),
        }
        base_value = attr_map.get(ability, 3)

        # 是否为协调者（bonus）
        meta = char.get("meta", {})
        is_coordinator = meta.get("is_coordinator", False)
        coordinator_bonus = 2 if is_coordinator else 0

        total = base_value + coordinator_bonus
        threshold = difficulty * 2
        rolls = [random.randint(1, 6) for _ in range(total)]
        successes = sum(1 for r in rolls if r >= 4)

        return {
            "ability": ability,
            "difficulty": difficulty,
            "threshold": threshold,
            "rolls": rolls,
            "successes": successes,
            "is_coordinator": is_coordinator,
            "coordinator_bonus_applied": coordinator_bonus > 0,
            "result": "成功" if successes >= difficulty else "失败",
            "margin": successes - difficulty,
        }
    except Exception as e:
        return {"error": str(e)}


# ── 机动战士战斗状态查询 ───────────────────────────────────────────────────────

async def _query_ms_status(session_id: str, ms_name: str = "") -> dict:
    """
    查询当前会话中机动战士（MS）的战斗状态。
    返回机体损伤、能量槽、武装状态。
    """
    from ...db import get_db

    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id,)
            )).fetchone()

        if not row:
            return {"error": "未找到角色数据"}

        char = json.loads(row["data_json"])
        meta = char.get("meta", {})
        ms_data = meta.get("mobile_suit", {})

        if not ms_data:
            ms_data = {
                "model": ms_name or "GAT-X105 突击高达",
                "hull_integrity": 100,
                "power": 100,
                "beam_rifle_ammo": 15,
                "phase_shift_active": True,
                "phase_shift_energy": 80,
                "status": "战斗待机",
                "pilot": char.get("name", "未知"),
            }

        return {
            "mobile_suit": ms_data,
            "combat_capable": ms_data.get("hull_integrity", 100) >= 20,
            "phase_shift_active": ms_data.get("phase_shift_active", False),
        }
    except Exception as e:
        return {"error": str(e)}


# ── 模块级 TOOLS 列表（供扩展加载器自动发现） ────────────────────────────────

TOOLS: list[ToolDef] = [
    ToolDef(
        name="coordinator_check",
        description=(
            "对 CE71 宇宙世纪协调者的特化能力进行骰子检定。"
            "ability: combat/piloting/analysis/coordination；difficulty 1-5。"
            "Gundam SEED 世界专属工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "ability": {
                    "type": "string",
                    "enum": ["combat", "piloting", "analysis", "coordination"],
                    "description": "能力类型",
                },
                "difficulty": {
                    "type": "integer",
                    "minimum": 1, "maximum": 5,
                    "description": "难度等级 1-5",
                },
            },
            "required": ["session_id"],
        },
        handler=_coordinator_check,
        plugin_key="gundam_seed",
        tags=["combat", "coordinator"],
    ),
    ToolDef(
        name="query_ms_status",
        description=(
            "查询当前机动战士（MS）的战斗状态：机体损伤、能量、武器弹药、PS装甲状态。"
            "Gundam SEED 世界专属工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "ms_name": {"type": "string", "description": "机体型号（可选）"},
            },
            "required": ["session_id"],
        },
        handler=_query_ms_status,
        plugin_key="gundam_seed",
        tags=["combat", "mecha"],
    ),
]


def register_tools() -> None:
    """兼容旧调用路径：向工具注册表手动注册（TOOLS 列表由加载器自动发现时无需调用）。"""
    for tool in TOOLS:
        tool_registry.register(tool)
