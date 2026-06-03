"""
无限武库生命周期钩子
实现武器损耗和锻造消耗钩子：
- on_roll_check: 战斗后武器耐久度损耗
- on_turn_end: 检查武器损坏状态
- on_chapter_end: 章节结束武库状态汇总
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime

logger = logging.getLogger(__name__)


class InfiniteArsenalHook:
    """
    无限武库武器损耗/锻造消耗钩子。
    管理角色库存中武器的耐久度随战斗使用自然损耗。
    """

    world_plugin = "infinite_arsenal"
    priority = 15

    async def on_roll_check(self, ctx: dict) -> dict:
        """骰子判定后：战斗使用造成武器耐久损耗。"""
        verdict = ctx.get("verdict", "")
        session_id = ctx.get("session_id", "")
        reason = ctx.get("reason", "")

        # 只处理战斗/技能相关判定
        combat_keywords = ["战斗", "攻击", "技能", "武器", "使用", "施展", "招式"]
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
            inventory: list[dict] = char.get("inventory", [])

            # 查找正在使用的武器（type=weapon 且耐久>0）
            weapons = [
                (i, item) for i, item in enumerate(inventory)
                if item.get("type") == "weapon" and item.get("durability", 100) > 0
            ]

            if not weapons:
                return ctx

            # 选择耐久最高的武器进行损耗
            idx, active_weapon = max(weapons, key=lambda x: x[1].get("durability", 0))
            base_wear = 3 if verdict == "success" else 8
            wear = random.randint(base_wear, base_wear + 5)
            old_durability = active_weapon.get("durability", 100)
            new_durability = max(0, old_durability - wear)
            inventory[idx]["durability"] = new_durability

            # 武器破损警告
            events = []
            if new_durability == 0:
                events.append({
                    "type": "item_broken",
                    "message": f"⚠️ [{active_weapon.get('name', '武器')}] 已损坏，需要修复后才能使用！",
                    "item_id": active_weapon.get("id", ""),
                })
            elif new_durability <= 20 and old_durability > 20:
                events.append({
                    "type": "item_warning",
                    "message": f"⚠️ [{active_weapon.get('name', '武器')}] 耐久度严重不足（{new_durability}%），建议尽快修复！",
                    "item_id": active_weapon.get("id", ""),
                })

            if events:
                ctx.setdefault("system_events", []).extend(events)

            # 写回库存
            char["inventory"] = inventory
            now = datetime.now().timestamp()
            async with get_db() as db:
                await db.execute(
                    "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                    (json.dumps(char, ensure_ascii=False), now, row["id"])
                )
                await db.commit()

        except Exception as e:
            logger.warning("[InfiniteArsenalHook] 武器损耗处理失败: %s", e)

        return ctx

    async def on_session_start(self, ctx: dict) -> dict:
        """会话启动时：初始化武器库存上下文，检查是否有待修复的损坏武器（锻造消耗结果）。"""
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
                inventory: list[dict] = char.get("inventory", [])
                weapons = [i for i in inventory if i.get("type") == "weapon"]
                broken = [w for w in weapons if w.get("durability", 100) == 0]
                pending_forge = [w for w in weapons if w.get("forged_by") == "pending"]

                if broken:
                    ctx.setdefault("system_events", []).append({
                        "type": "item_warning",
                        "message": (
                            f"[武库] 发现 {len(broken)} 件损坏武器需要修复："
                            + "、".join(w.get("name", "未知") for w in broken[:3])
                        ),
                    })
                if pending_forge:
                    ctx.setdefault("system_events", []).append({
                        "type": "forge_pending",
                        "message": f"[武库] 有 {len(pending_forge)} 件武器正在锻造中，锻造消耗已预扣。",
                    })
        except Exception as e:
            logger.warning("[InfiniteArsenalHook] session_start 武库初始化失败: %s", e)
        return ctx

    async def on_chapter_end(self, ctx: dict) -> dict:
        """章节结束时汇总武器状态。"""
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
                inventory = char.get("inventory", [])
                weapons = [i for i in inventory if i.get("type") == "weapon"]
                broken = [w for w in weapons if w.get("durability", 100) == 0]
                low = [w for w in weapons if 0 < w.get("durability", 100) <= 30]

                if weapons:
                    ctx.setdefault("chapter_footnotes", []).append(
                        f"[武库状态] 持有武器 {len(weapons)} 件"
                        + (f"，损坏 {len(broken)} 件" if broken else "")
                        + (f"，低耐久 {len(low)} 件" if low else "")
                    )
        except Exception as e:
            logger.warning("[InfiniteArsenalHook] chapter_end 武库汇总失败: %s", e)
        return ctx
