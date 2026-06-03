"""
MUV-LUV Alternative 生命周期钩子
实现 TSF 战斗钩子：骰子判定后评估机体损伤、光线种锁定等结果。
"""
from __future__ import annotations

import json
import logging
import random

logger = logging.getLogger(__name__)


class MuvLuvHook:
    """
    MUV-LUV TSF 战斗钩子。
    骰子结果出来后，根据成败自动计算 TSF 损伤和 BETA 威胁响应。
    """

    world_plugin = "muv_luv"
    priority = 10

    async def on_roll_check(self, ctx: dict) -> dict:
        """骰子判定后：根据成败计算 TSF 状态变化。"""
        verdict = ctx.get("verdict", "")
        session_id = ctx.get("session_id", "")
        reason = ctx.get("reason", "")

        # 只处理战斗相关判定
        combat_keywords = ["战斗", "攻击", "回避", "TSF", "BETA", "驾驶", "机动"]
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
            tsf = meta.setdefault("tsf", {
                "model": "Type-94 不知火",
                "hull_integrity": 100,
                "fuel": 100,
                "ammo_36mm": 120,
                "status": "战斗中",
            })

            if verdict == "failure":
                # 失败：TSF 受到损伤
                damage = random.randint(5, 25)
                tsf["hull_integrity"] = max(0, tsf.get("hull_integrity", 100) - damage)
                fuel_cost = random.randint(3, 10)
                tsf["fuel"] = max(0, tsf.get("fuel", 100) - fuel_cost)

                ctx.setdefault("state_patches", []).append({
                    "path": "meta.tsf",
                    "value": tsf,
                    "reason": f"战斗判定失败：机体损伤 -{damage}%，燃料消耗 -{fuel_cost}%",
                })
                logger.debug("[MuvLuvHook] TSF 受损: integrity=%s", tsf["hull_integrity"])

            elif verdict == "success":
                # 成功：消耗弹药
                ammo_cost = random.randint(5, 20)
                tsf["ammo_36mm"] = max(0, tsf.get("ammo_36mm", 120) - ammo_cost)
                fuel_cost = random.randint(2, 5)
                tsf["fuel"] = max(0, tsf.get("fuel", 100) - fuel_cost)

                ctx.setdefault("state_patches", []).append({
                    "path": "meta.tsf",
                    "value": tsf,
                    "reason": f"战斗判定成功：弹药消耗 {ammo_cost} 发，燃料消耗 -{fuel_cost}%",
                })

            # 检查是否触发光线种锁定警告
            if tsf.get("hull_integrity", 100) < 30:
                ctx.setdefault("system_events", []).append({
                    "type": "warning",
                    "message": f"⚠️ 机体损伤临界！机体完整度 {tsf['hull_integrity']}%，建议立即撤退！",
                    "severity": "critical",
                })

        except Exception as e:
            logger.warning("[MuvLuvHook] TSF 状态更新失败: %s", e)

        return ctx

    async def on_chapter_end(self, ctx: dict) -> dict:
        """章节结束时记录 TSF 战况摘要。"""
        session_id = ctx.get("session_id", "")
        try:
            from ...db import get_db
            async with get_db() as db:
                row = await (await db.execute(
                    "SELECT data_json FROM character_cards WHERE session_id=? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (session_id,)
                )).fetchone()

            if row:
                char = json.loads(row["data_json"])
                tsf = char.get("meta", {}).get("tsf", {})
                if tsf:
                    ctx.setdefault("chapter_footnotes", []).append(
                        f"[TSF 状态] {tsf.get('model', '?')}: "
                        f"机体完整度 {tsf.get('hull_integrity', '?')}% | "
                        f"燃料 {tsf.get('fuel', '?')}% | "
                        f"36mm弹药 {tsf.get('ammo_36mm', '?')} 发"
                    )
        except Exception as e:
            logger.warning("[MuvLuvHook] chapter_end TSF 摘要失败: %s", e)
        return ctx
