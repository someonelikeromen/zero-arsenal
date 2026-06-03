"""
跨界世界插件 — 扩展工具集。
TOOLS 列表会被 _discover_extension_tools() 自动注册到 ToolRegistry。
"""
from __future__ import annotations
import json
import random
import uuid
from datetime import datetime

try:
    from ...tools.registry import ToolDef
except ImportError:
    from backend.tools.registry import ToolDef  # type: ignore[no-redef]


# 预设跨界随机事件列表
_CROSSOVER_EVENTS = [
    ("来自异世界的旅行者突然出现，带来陌生世界的消息", "medium"),
    ("时空裂缝开启，异界气息涌入当前场景", "high"),
    ("神秘传送门在眼前展开，散发着未知世界的气味", "high"),
    ("一件来历不明的异界文物出现在地上", "low"),
    ("短暂的时空叠影，两个世界的景象同时浮现", "medium"),
    ("远处传来异界生物的叫声，旋即消失", "low"),
    ("天空出现短暂的异常极光，预示跨界能量波动", "medium"),
    ("遭遇来自平行时间线的自己的投影", "high"),
    ("一封来自未知世界的信件落在脚边", "low"),
    ("周围的重力短暂出现异常，像是不同物理法则叠加", "medium"),
    ("附近空间扭曲，隐约可见另一世界的街景", "medium"),
    ("携带的物品短暂具有了异世界属性", "low"),
    ("感应到来自远方世界的强者气息", "high"),
    ("时间短暂停滞，只有跨界者能感知", "high"),
    ("发现一处疑似跨界传送阵的古老遗迹", "medium"),
]


async def _get_player_points(session_id: str) -> dict:
    """
    获取玩家在跨界世界中积累的积分和徽章。
    从 character_cards 的 meta 字段读取。
    """
    from ...db import get_db
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
        if not row:
            return {"session_id": session_id, "points": 0, "badges": []}
        char = json.loads(row["data_json"])
        meta = char.get("meta", {})
        return {
            "session_id": session_id,
            "points": int(meta.get("crossover_points", 0)),
            "badges": meta.get("badges", []),
        }
    except Exception as e:
        return {"error": str(e)}


async def _award_badge(
    session_id: str,
    badge_name: str,
    reason: str = "",
) -> dict:
    """
    为玩家颁发跨界徽章。
    向 world_archives 写入成就记录，并更新角色卡 meta.badges 列表。
    """
    from ...db import get_db
    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            # 读取角色卡
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if row:
                char = json.loads(row["data_json"])
                meta = char.setdefault("meta", {})
                badges: list = meta.setdefault("badges", [])
                if badge_name not in badges:
                    badges.append(badge_name)
                    await db.execute(
                        "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                        (json.dumps(char, ensure_ascii=False), now, row["id"])
                    )

            # 写入成就档案
            archive_content = json.dumps({
                "badge": badge_name,
                "reason": reason,
                "awarded_at": now,
            }, ensure_ascii=False)
            await db.execute(
                "INSERT INTO world_archives "
                "(id, session_id, title, content, archive_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'achievement', ?, ?)",
                (str(uuid.uuid4()), session_id, badge_name, archive_content, now, now)
            )
            await db.commit()
        return {"badge": badge_name, "awarded": True, "reason": reason}
    except Exception as e:
        return {"error": str(e)}


async def _open_shop(session_id: str, category: str = "") -> dict:
    """
    打开主神商店，列出可购买的物品。
    读取 data/shop-catalog.json；无文件时返回内置兜底。
    """
    from pathlib import Path
    catalog_path = Path(__file__).parent / "data" / "shop-catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        categories = catalog.get("categories", [])
        if category:
            categories = [c for c in categories if c["id"] == category or c["name"] == category]
        items_flat = [
            {**item, "category_id": cat["id"], "category_name": cat["name"]}
            for cat in categories
            for item in cat.get("items", [])
        ]
        return {
            "ok": True,
            "currency": catalog.get("currency", "crossover_points"),
            "categories": [c["name"] for c in catalog.get("categories", [])],
            "items": items_flat,
            "total": len(items_flat),
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[crossover] shop-catalog.json 加载失败: {e}，返回空商店")
        return {"ok": True, "currency": "crossover_points", "categories": [], "items": [], "total": 0}


async def _random_crossover_event(session_id: str) -> dict:
    """
    触发一个随机跨界事件。优先使用 LLM 生成有情境感的事件描述；
    LLM 不可用时降级到预设列表。
    """
    try:
        from ...agents.llm import llm_complete
        result_text = await llm_complete(
            messages=[
                {"role": "system", "content":
                    "你是综漫无限流小说的叙事助手。根据请求，生成一个简短的随机跨界事件（1-2句话）。"
                    "回复格式：JSON {\"event\": \"...\", \"intensity\": \"low|medium|high\"}"},
                {"role": "user", "content": f"为会话 {session_id} 生成一个跨界随机事件。"},
            ],
            temperature=0.9,
            max_tokens=128,
        )
        raw = result_text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(raw)
        return {
            "event": data.get("event", ""),
            "intensity": data.get("intensity", "medium"),
            "session_id": session_id,
            "generated_by": "llm",
        }
    except Exception:
        event_text, intensity = random.choice(_CROSSOVER_EVENTS)
        return {
            "event": event_text,
            "intensity": intensity,
            "session_id": session_id,
            "generated_by": "preset",
        }


async def _earn_sp_by_kill(
    session_id: str,
    enemy_key: str,
    enemy_tier: int,
    enemy_tier_sub: str = "M",
    killed: bool = True,
) -> dict:
    """
    根据敌人星级计算并发放击杀 SP 奖励。
    SP 表：1★→50 / 2★→200 / 3★→800 / 4★→3200 / 5★→12800
    子段位倍率：L×0.8 / M×1.0 / U×1.3；击杀额外 ×1.5。
    """
    from ...db import get_db
    sp_table = {1: 50, 2: 200, 3: 800, 4: 3200, 5: 12800}
    base_sp = sp_table.get(max(1, min(5, enemy_tier)), 50)
    sub_mul = {"L": 0.8, "M": 1.0, "U": 1.3}.get(enemy_tier_sub.upper(), 1.0)
    kill_bonus = 1.5 if killed else 1.0
    total = int(base_sp * sub_mul * kill_bonus)

    now = datetime.now().timestamp()
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if row:
                char = json.loads(row["data_json"])
                meta = char.setdefault("meta", {})
                meta["crossover_points"] = int(meta.get("crossover_points", 0)) + total
                await db.execute(
                    "UPDATE character_cards SET data_json=?, points=?, updated_at=? WHERE id=?",
                    (json.dumps(char, ensure_ascii=False), meta["crossover_points"], now, row["id"])
                )
                await db.commit()
        return {
            "sp_gained": total,
            "enemy": enemy_key,
            "tier": f"{enemy_tier}★{enemy_tier_sub}",
            "killed": killed,
        }
    except Exception as e:
        return {"error": str(e)}


TOOLS: list[ToolDef] = [
    ToolDef(
        name="get_player_points",
        description="获取玩家在跨界世界中积累的积分数量和已解锁的徽章列表。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_get_player_points,
        permission_required="allow",
        tags=["read", "crossover"],
        group="crossover",
    ),
    ToolDef(
        name="award_badge",
        description="为玩家颁发跨界成就徽章，并记录到世界档案中。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "badge_name": {"type": "string", "description": "徽章名称"},
                "reason":     {"type": "string", "description": "颁发原因（可选）", "default": ""},
            },
            "required": ["session_id", "badge_name"],
        },
        handler=_award_badge,
        permission_required="allow",
        tags=["write", "crossover"],
        group="crossover",
    ),
    ToolDef(
        name="open_shop",
        display_name="主神商店",
        description="打开主神商店，列出可购买的物品（从 shop-catalog.json 加载）。可指定 category 筛选类别。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "category":   {"type": "string", "description": "商品类别 ID 或名称（可选）"},
            },
            "required": ["session_id"],
        },
        handler=_open_shop,
        permission_required="allow",
        tags=["read", "economy", "crossover"],
        group="crossover",
    ),
    ToolDef(
        name="random_crossover_event",
        description="触发一个随机跨界事件，为场景增加跨界世界的神秘感。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_random_crossover_event,
        permission_required="allow",
        tags=["narrative", "crossover"],
        group="crossover",
    ),
    ToolDef(
        name="earn_sp_by_kill",
        description=(
            "根据敌人星级计算击杀 SP 奖励并写入角色卡。"
            "enemy_tier: 1-5 星；enemy_tier_sub: L/M/U；killed: 是否击杀（否则只算战斗胜利）。"
            "在战斗结束后由 VarAgent 调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id":    {"type": "string",  "description": "会话 ID"},
                "enemy_key":     {"type": "string",  "description": "敌人标识（如 dragon_lord）"},
                "enemy_tier":    {"type": "integer", "description": "敌人星级 1-5"},
                "enemy_tier_sub":{"type": "string",  "description": "子段位 L/M/U", "default": "M"},
                "killed":        {"type": "boolean", "description": "是否击杀（否则只算胜利）", "default": True},
            },
            "required": ["session_id", "enemy_key", "enemy_tier"],
        },
        handler=_earn_sp_by_kill,
        permission_required="allow",
        tags=["write", "economy", "combat", "crossover"],
        group="crossover",
    ),
]
