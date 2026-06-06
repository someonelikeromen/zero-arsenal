"""
跨界无限流世界生命周期钩子
实现跨界事件触发钩子：在回合结束时有概率触发跨界事件，章节结束时结算 SP 经济。
"""
from __future__ import annotations

import json
import logging
import random

logger = logging.getLogger(__name__)


class CrossoverHook:
    """
    综漫无限流跨界事件钩子。
    - on_turn_end: 有概率触发随机跨界事件
    - on_chapter_end: 章节结束 SP 结算
    - on_session_start: 初始化主神空间状态
    """

    plugin_key = "crossover"
    priority = 20

    _CROSSOVER_EVENT_CHANCE = 0.15  # 每回合 15% 概率触发跨界事件

    _CROSSOVER_EVENTS = [
        "时空裂缝短暂开启，异界气息涌入当前场景",
        "来自异世界的旅行者突然出现，带来陌生世界的消息",
        "神秘传送门在眼前展开，散发着未知世界的气味",
        "一件来历不明的异界文物出现在地上",
        "短暂的时空叠影，两个世界的景象同时浮现",
        "附近空间扭曲，隐约可见另一世界的街景",
        "遭遇来自平行时间线的自己的投影",
    ]

    async def on_turn_end(self, ctx: dict) -> dict:
        """回合结束：有概率触发跨界随机事件。"""
        if random.random() > self._CROSSOVER_EVENT_CHANCE:
            return ctx

        event_desc = random.choice(self._CROSSOVER_EVENTS)
        intensity = random.choice(["low", "medium", "high"])
        sp_reward = {"low": 5, "medium": 15, "high": 30}[intensity]

        ctx.setdefault("world_events", []).append({
            "type": "crossover_event",
            "description": event_desc,
            "intensity": intensity,
            "sp_reward": sp_reward,
        })

        # 增加 SP
        try:
            from ...db import get_db
            session_id = ctx.get("session_id", "")
            if session_id:
                async with get_db() as db:
                    row = await (await db.execute(
                        "SELECT id, data_json FROM character_cards WHERE session_id=? "
                        "ORDER BY updated_at DESC LIMIT 1",
                        (session_id,)
                    )).fetchone()
                if row:
                    char = json.loads(row["data_json"])
                    meta = char.setdefault("meta", {})
                    meta["sp"] = meta.get("sp", 0) + sp_reward
                    from datetime import datetime
                    now = datetime.now().timestamp()
                    async with get_db() as db:
                        await db.execute(
                            "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                            (json.dumps(char, ensure_ascii=False), now, row["id"])
                        )
                        await db.commit()
        except Exception as e:
            logger.warning("[CrossoverHook] SP 结算失败: %s", e)

        return ctx

    async def on_chapter_end(self, ctx: dict) -> dict:
        """章节结束：结算章节 SP 奖励并记录跨界事件数。"""
        session_id = ctx.get("session_id", "")
        world_events = ctx.get("world_events", [])
        crossover_events = [e for e in world_events if e.get("type") == "crossover_event"]

        if crossover_events:
            total_sp = sum(e.get("sp_reward", 0) for e in crossover_events)
            ctx.setdefault("chapter_footnotes", []).append(
                f"[跨界记录] 本章触发 {len(crossover_events)} 次跨界事件，共获得 {total_sp} SP"
            )
        return ctx

    async def on_session_start(self, ctx: dict) -> dict:
        """会话开始时初始化主神空间状态。"""
        ctx.setdefault("world_context", {}).update({
            "system": "主神空间",
            "economy": "SP（积分）驱动",
            "rules": "综漫无限流规则适用",
        })
        return ctx
