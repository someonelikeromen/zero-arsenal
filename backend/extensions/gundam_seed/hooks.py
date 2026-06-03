"""
Gundam SEED 世界生命周期钩子
在骰子判定后评估 MS 损伤，监控 PS 装甲能量耗尽事件。
"""
from __future__ import annotations

import json
import logging
import random

logger = logging.getLogger(__name__)


class GundamSeedHook:
    """
    Gundam SEED 机动战士战斗钩子。
    骰子结果后自动更新 MS 状态，PS 装甲耗尽时触发警报。
    """

    world_plugin = "gundam_seed"
    priority = 10

    async def on_roll_check(self, ctx: dict) -> dict:
        """骰子判定后：根据成败更新 MS 战斗状态。"""
        verdict = ctx.get("verdict", "")
        session_id = ctx.get("session_id", "")
        reason = ctx.get("reason", "")

        # 只处理 MS 战斗相关判定
        combat_keywords = ["战斗", "攻击", "回避", "高达", "MS", "机动战士", "驾驶", "射击"]
        if not any(kw in reason for kw in combat_keywords):
            return ctx

        try:
            from ...db import get_db
            async with get_db() as db:
                row = await (await db.execute(
                    "SELECT id, data_json FROM character_cards WHERE session_id=? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (session_id,)
                )).fetchone()

            if not row:
                return ctx

            char = json.loads(row["data_json"])
            meta = char.setdefault("meta", {})
            ms = meta.setdefault("mobile_suit", {
                "model": "GAT-X105 突击高达",
                "hull_integrity": 100,
                "power": 100,
                "phase_shift_active": True,
                "phase_shift_energy": 80,
                "beam_rifle_ammo": 15,
                "status": "战斗中",
            })

            if verdict == "failure":
                # 失败：MS 受到伤害
                damage = random.randint(8, 30)
                ms["hull_integrity"] = max(0, ms.get("hull_integrity", 100) - damage)

                # PS 装甲消耗加速
                ps_drain = random.randint(5, 20)
                ms["phase_shift_energy"] = max(0, ms.get("phase_shift_energy", 80) - ps_drain)

                if ms["phase_shift_energy"] <= 0:
                    ms["phase_shift_active"] = False
                    ctx.setdefault("system_events", []).append({
                        "type": "warning",
                        "message": "⚠️ PS 装甲能量耗尽！机体失去相位移动装甲防护！",
                        "severity": "high",
                    })

                ctx.setdefault("state_patches", []).append({
                    "path": "meta.mobile_suit",
                    "value": ms,
                    "reason": f"MS 战斗受损：机体 -{damage}%，PS能量 -{ps_drain}%",
                })

            elif verdict == "success":
                # 成功：消耗弹药和能量
                ammo_cost = random.randint(1, 3)
                ms["beam_rifle_ammo"] = max(0, ms.get("beam_rifle_ammo", 15) - ammo_cost)
                ps_cost = random.randint(2, 8)
                ms["phase_shift_energy"] = max(0, ms.get("phase_shift_energy", 80) - ps_cost)

                if ms["phase_shift_energy"] <= 0:
                    ms["phase_shift_active"] = False

                ctx.setdefault("state_patches", []).append({
                    "path": "meta.mobile_suit",
                    "value": ms,
                    "reason": f"MS 战斗消耗：光束步枪 -{ammo_cost} 发，PS能量 -{ps_cost}%",
                })

            # 机体临界警告
            if ms.get("hull_integrity", 100) < 20:
                ctx.setdefault("system_events", []).append({
                    "type": "warning",
                    "message": f"⚠️ {ms.get('model','MS')} 损伤严重！机体完整度 {ms['hull_integrity']}%！",
                    "severity": "critical",
                })

        except Exception as e:
            logger.warning("[GundamSeedHook] MS 状态更新失败: %s", e)

        return ctx

    async def on_session_start(self, ctx: dict) -> dict:
        """会话开始时初始化 CE71 宇宙世纪背景信息。"""
        ctx.setdefault("world_context", {}).update({
            "era": "Cosmic Era 71",
                "conflict": "地球联合 vs ZAFT",
                "setting": "血色情人节后，战争全面爆发",
        })
        return ctx
