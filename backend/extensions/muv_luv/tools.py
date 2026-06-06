"""
MUV-LUV Alternative 世界专属工具
实现 TSF 状态查询和 BETA 威胁评估两个核心工具。
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


# ── TSF 状态查询 ──────────────────────────────────────────────────────────────

async def _query_tsf_status(session_id: str, tsf_name: str = "") -> dict:
    """
    查询当前会话中战术机（TSF）的状态，包括损伤、燃料、弹药。
    若 tsf_name 为空，查询主角所驾驶的 TSF。
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
        tsf_data = meta.get("tsf", {})

        if not tsf_data:
            # 默认 TSF 状态
            tsf_data = {
                "model": tsf_name or "Type-94 不知火",
                "hull_integrity": 100,
                "fuel": 100,
                "ammo_36mm": 120,
                "ammo_120mm": 36,
                "close_combat_blade": "完好",
                "status": "待机",
            }

        return {
            "tsf": tsf_data,
            "pilot": char.get("name", "未知"),
            "combat_ready": tsf_data.get("hull_integrity", 100) >= 30,
        }
    except Exception as e:
        return {"error": str(e)}


# ── BETA 威胁评估 ─────────────────────────────────────────────────────────────

async def _beta_threat_assessment(
    session_id: str,
    sector: str = "前线",
    radius_km: float = 5.0,
) -> dict:
    """
    评估指定扇区的 BETA 威胁级别。
    基于当前时间线（1998年）和扇区位置生成威胁报告。
    """
    try:
        # 读取 BETA 种类数据
        beta_catalog_path = _DATA_DIR / "beta-catalog.json"
        if beta_catalog_path.exists():
            beta_catalog = json.loads(beta_catalog_path.read_text(encoding="utf-8"))
        else:
            beta_catalog = {
                "species": [
                    {"name": "突击种", "threat": "high", "count_range": [50, 200]},
                    {"name": "要塞种", "threat": "extreme", "count_range": [1, 5]},
                    {"name": "光线种", "threat": "extreme", "count_range": [5, 30]},
                    {"name": "戦車種", "threat": "medium", "count_range": [20, 100]},
                    {"name": "兵士種", "threat": "low", "count_range": [100, 500]},
                ]
            }

        # 基于 sector 生成威胁评估
        threat_roll = random.random()
        if threat_roll < 0.3:
            threat_level = "低"
            species_count = 1
        elif threat_roll < 0.7:
            threat_level = "中"
            species_count = random.randint(2, 3)
        else:
            threat_level = "高"
            species_count = random.randint(3, 5)

        detected_species = random.sample(
            beta_catalog.get("species", []),
            min(species_count, len(beta_catalog.get("species", [])))
        )

        units: list[dict] = []
        total_count = 0
        for sp in detected_species:
            count = random.randint(*sp["count_range"])
            total_count += count
            units.append({
                "species": sp["name"],
                "threat": sp["threat"],
                "estimated_count": count,
            })

        return {
            "sector": sector,
            "radius_km": radius_km,
            "threat_level": threat_level,
            "detected_units": units,
            "total_estimated_count": total_count,
            "recommended_action": (
                "维持当前阵地" if threat_level == "低" else
                "请求后援" if threat_level == "中" else
                "紧急撤退或全力迎击"
            ),
            "assessment_time": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


# ── 模块级 TOOLS 列表（供扩展加载器自动发现） ────────────────────────────────

TOOLS: list[ToolDef] = [
    ToolDef(
        name="query_tsf_status",
        description="查询当前战术机（TSF）的状态：机体损伤、燃料余量、弹药数量。MUV-LUV 世界专属工具。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "tsf_name": {"type": "string", "description": "TSF 型号名（可选，空则查主角机体）"},
            },
            "required": ["session_id"],
        },
        handler=_query_tsf_status,
        plugin_key="muv_luv",
        tags=["combat", "mecha"],
    ),
    ToolDef(
        name="beta_threat_assessment",
        description="评估指定扇区内的 BETA 威胁级别，返回敌方种类、数量和建议行动。MUV-LUV 世界专属工具。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "sector": {"type": "string", "description": "扇区名称，如'前线'、'C区'"},
                "radius_km": {"type": "number", "description": "侦测半径（公里），默认 5.0"},
            },
            "required": ["session_id"],
        },
        handler=_beta_threat_assessment,
        plugin_key="muv_luv",
        tags=["combat", "intel"],
    ),
]


def register_tools() -> None:
    """兼容旧调用路径：向工具注册表手动注册（TOOLS 列表由加载器自动发现时无需调用）。"""
    for tool in TOOLS:
        tool_registry.register(tool)
