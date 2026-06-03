"""
神兵库世界插件 — 扩展工具集。
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


# 材料 → 武器类型映射
_MATERIAL_TO_TYPE = {
    "玄铁": "剑",
    "精钢": "刀",
    "寒玉": "弓",
    "神木": "法杖",
    "龙骨": "长枪",
    "陨铁": "重锤",
    "幽金": "匕首",
}

# 技法 → 品质/攻击加成
_TECHNIQUE_TO_QUALITY = {
    "基础锻造":  ("普通", "C", 10, 20),
    "精炼":      ("精良", "B", 25, 40),
    "上古秘法":  ("稀有", "A", 50, 70),
    "神兵秘法":  ("传说", "S", 90, 120),
}


async def _get_arsenal_inventory(session_id: str) -> dict:
    """
    获取角色的武器库存清单（inventory 中 type='weapon' 的物品）。
    """
    from ...db import get_db
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
        if not row:
            return {"weapons": [], "count": 0}
        char = json.loads(row["data_json"])
        inventory: list = char.get("inventory", [])
        weapons = [item for item in inventory if isinstance(item, dict)
                   and item.get("type") in ("weapon", "武器")]
        return {"weapons": weapons, "count": len(weapons)}
    except Exception as e:
        return {"error": str(e)}


async def _forge_weapon(
    session_id: str,
    material: str,
    technique: str = "基础锻造",
) -> dict:
    """
    使用指定材料和技法锻造武器，追加到角色库存。
    优先使用 LLM 生成真实的武器属性描述；LLM 不可用时降级到固定映射表。
    """
    from ...db import get_db
    now = datetime.now().timestamp()

    # 尝试 LLM 生成武器详情
    weapon: dict | None = None
    try:
        from ....agents.llm import llm_complete
        llm_resp = await llm_complete(
            messages=[
                {"role": "system", "content":
                    "你是综漫无限流神兵铸造系统。根据材料和技法，生成武器信息。"
                    "回复 JSON：{\"name\": str, \"weapon_type\": str, \"quality\": str, "
                    "\"grade\": \"C|B|A|S\", \"attack\": int, \"description\": str}"},
                {"role": "user", "content":
                    f"材料：{material}，技法：{technique}。请生成一把武器。"},
            ],
            temperature=0.7,
            max_tokens=256,
        )
        raw = llm_resp.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(raw)
        weapon = {
            "id": str(uuid.uuid4()),
            "name": data.get("name", f"{material}武器"),
            "type": "weapon",
            "material": material,
            "weapon_type": data.get("weapon_type", ""),
            "quality": data.get("quality", "普通"),
            "grade": data.get("grade", "C"),
            "attack": int(data.get("attack", 15)),
            "description": data.get("description", ""),
            "durability": 100,
            "forged_by": "llm",
            "forged_at": now,
        }
    except Exception:
        # 降级到固定映射表
        weapon_type = _MATERIAL_TO_TYPE.get(material, "匕首")
        quality_name, grade, atk_min, atk_max = _TECHNIQUE_TO_QUALITY.get(
            technique, ("普通", "C", 10, 20)
        )
        attack = random.randint(atk_min, atk_max)
        weapon = {
            "id": str(uuid.uuid4()),
            "name": f"{material}{weapon_type}·{quality_name}",
            "type": "weapon",
            "material": material,
            "weapon_type": weapon_type,
            "quality": quality_name,
            "grade": grade,
            "attack": attack,
            "durability": 100,
            "forged_by": "table",
            "forged_at": now,
        }

    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT id, data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
            if not row:
                return {"error": "character not found"}
            char = json.loads(row["data_json"])
            inventory: list = char.setdefault("inventory", [])
            inventory.append(weapon)
            await db.execute(
                "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), now, row["id"])
            )
            await db.commit()
        return {"weapon": weapon, "forged": True}
    except Exception as e:
        return {"error": str(e)}


async def _evaluate_weapon(session_id: str, weapon_name: str) -> dict:
    """
    评估角色持有的指定武器，返回评级和建议用途。
    """
    from ...db import get_db
    _GRADE_SUGGEST = {
        "S": "适合面对领主级或神话级敌人，搭配神功使用效果最佳",
        "A": "适合精英战斗或重要剧情节点，可应对大多数强敌",
        "B": "日常战斗的可靠之选，性价比高",
        "C": "适合初期探索或练习，面对强敌效果有限",
    }
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? "
                "ORDER BY updated_at DESC LIMIT 1", (session_id,)
            )).fetchone()
        if not row:
            return {"weapon_name": weapon_name, "found": False}
        char = json.loads(row["data_json"])
        inventory: list = char.get("inventory", [])
        # 模糊匹配武器名
        matched = next(
            (item for item in inventory
             if isinstance(item, dict) and weapon_name in item.get("name", "")),
            None
        )
        if not matched:
            return {"weapon_name": weapon_name, "found": False,
                    "note": "未在库存中找到该武器"}
        grade = matched.get("grade", "C")
        return {
            "weapon_name": matched["name"],
            "found": True,
            "grade": grade,
            "attack": matched.get("attack", 0),
            "durability": matched.get("durability", 100),
            "suggested_use": _GRADE_SUGGEST.get(grade, "通用武器"),
        }
    except Exception as e:
        return {"error": str(e)}


_SUB_TIERS = ["L", "M", "U"]
_ITEM_CATEGORIES = [
    "ApplicationTechnique",  # 武技/功法
    "Weapon",                # 武器
    "Armor",                 # 防具
    "Companion",             # 伙伴
    "Knowledge",             # 知识/记忆
]

# ── 卡池配置：从 data/pool-catalog.json 加载 ────────────────────────────────
def _load_pool_catalog() -> dict[str, dict]:
    """从 pool-catalog.json 加载卡池配置，键为池 id。"""
    from pathlib import Path
    catalog_path = Path(__file__).parent / "data" / "pool-catalog.json"
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        result: dict[str, dict] = {}
        for pool in data.get("pools", []):
            pid = pool["id"]
            # 统一 tier_weights 键为 int
            tw = {int(k): v for k, v in pool.get("tier_weights", {}).items()}
            result[pid] = {
                "cost": pool.get("cost_per_draw", 100),
                "pity_at": pool.get("pity_at", 90),
                "tier_weights": tw,
                "category_weights": pool.get("category_weights", {}),
                "description": pool.get("description", ""),
                "display_name": pool.get("display_name", pid),
            }
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[GachaTools] pool-catalog.json 加载失败: {e}，使用内置默认值")
        return {
            "综合池": {"cost": 100, "tier_weights": {1: 60, 2: 25, 3: 10, 4: 4, 5: 1},
                      "category_weights": {}, "description": "综合卡池"},
            "战术池": {"cost": 5000, "tier_weights": {1: 0, 2: 10, 3: 35, 4: 40, 5: 15},
                      "category_weights": {}, "description": "战术卡池"},
            "战略池": {"cost": 250000, "tier_weights": {1: 0, 2: 0, 3: 5, 4: 35, 5: 60},
                      "category_weights": {}, "description": "战略卡池"},
        }

_POOL_CATALOG: dict[str, dict] = _load_pool_catalog()


async def _draw_gacha(
    session_id: str,
    pool_name: str = "综合池",
    count: int = 1,
) -> dict:
    """
    无限武库抽卡：扣除 SP，按卡池概率生成落点框架。
    返回 tier（星级）、tier_sub（L/M/U）、category（大类）。
    具体 ACG 来源物品需由 GachaAgent 根据落点框架匹配并发货。
    """
    import random
    from ...db import get_db
    pool = _POOL_CATALOG.get(pool_name) or _POOL_CATALOG["综合池"]
    total_cost = pool["cost"] * count
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
            current_sp = int(meta.get("crossover_points", 0))
            if current_sp < total_cost:
                return {
                    "ok": False,
                    "reason": f"SP 不足（需要 {total_cost}，当前 {current_sp}）",
                }
            meta["crossover_points"] = current_sp - total_cost
            await db.execute(
                "UPDATE character_cards SET data_json=?, points=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), meta["crossover_points"], now, row["id"])
            )
            await db.commit()

        # 生成落点（使用 pool-catalog 中的 tier/category 权重）
        weights = pool["tier_weights"]
        tiers   = list(weights.keys())
        probs   = list(weights.values())
        cat_weights = pool.get("category_weights", {})
        cat_list    = list(cat_weights.keys()) if cat_weights else _ITEM_CATEGORIES
        cat_probs   = [cat_weights[c] for c in cat_list] if cat_weights else None
        results = []
        for _ in range(count):
            tier = random.choices(tiers, weights=probs, k=1)[0]
            sub  = random.choice(_SUB_TIERS)
            cat  = random.choices(cat_list, weights=cat_probs, k=1)[0]
            results.append({"tier": tier, "tier_sub": sub, "category": cat})

        return {
            "ok": True,
            "pool": pool_name,
            "count": count,
            "sp_spent": total_cost,
            "sp_remaining": meta["crossover_points"],
            "results": results,
            "note": "落点框架已生成，请 GachaAgent 根据 tier/category 匹配 ACG 来源物品并发货。",
        }
    except Exception as e:
        return {"error": str(e)}


async def _earn_battle_rewards(
    session_id: str,
    enemy_key: str,
    enemy_tier: int,
    enemy_tier_sub: str = "M",
    defeated: bool = True,
    killed: bool = True,
) -> dict:
    """
    无限武库战斗奖励结算：经验 + SP + 可能的物品掉落。
    defeated=True 表示战胜（不一定击杀）；killed=True 表示消灭。
    """
    from ...db import get_db
    sp_table    = {1: 50, 2: 200, 3: 800, 4: 3200, 5: 12800}
    exp_table   = {1: 100, 2: 500, 3: 2000, 4: 8000, 5: 32000}
    sub_mul     = {"L": 0.8, "M": 1.0, "U": 1.3}.get(enemy_tier_sub.upper(), 1.0)
    kill_bonus  = 1.5 if killed else 1.0
    defeat_mul  = 1.0 if defeated else 0.3
    sp_gain  = int(sp_table.get(enemy_tier, 50)  * sub_mul * kill_bonus * defeat_mul)
    exp_gain = int(exp_table.get(enemy_tier, 100) * sub_mul * kill_bonus * defeat_mul)

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
            meta["crossover_points"] = int(meta.get("crossover_points", 0)) + sp_gain
            meta["battle_exp"] = int(meta.get("battle_exp", 0)) + exp_gain
            await db.execute(
                "UPDATE character_cards SET data_json=?, points=?, updated_at=? WHERE id=?",
                (json.dumps(char, ensure_ascii=False), meta["crossover_points"], now, row["id"])
            )
            # 写入记忆
            await db.execute(
                "INSERT OR IGNORE INTO memory_entries "
                "(id, session_id, content, tier, cognitive_partition, source_agent, created_at) "
                "VALUES (?, ?, ?, 'episodic', 'objective_global', 'tool:earn_battle_rewards', ?)",
                (str(uuid.uuid4()), session_id,
                 f"战斗奖励：击{'杀' if killed else '败'} {enemy_key}（{enemy_tier}★{enemy_tier_sub}）"
                 f"，获得 SP×{sp_gain} EXP×{exp_gain}",
                 now)
            )
            await db.commit()
        return {
            "ok": True,
            "enemy": enemy_key,
            "tier": f"{enemy_tier}★{enemy_tier_sub}",
            "defeated": defeated,
            "killed": killed,
            "sp_gained": sp_gain,
            "exp_gained": exp_gain,
            "sp_total": meta["crossover_points"],
        }
    except Exception as e:
        return {"error": str(e)}


TOOLS: list[ToolDef] = [
    ToolDef(
        name="get_arsenal_inventory",
        description="获取角色神兵库存清单，列出所有武器类型的物品及其属性。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
            },
            "required": ["session_id"],
        },
        handler=_get_arsenal_inventory,
        permission_required="allow",
        tags=["read", "arsenal"],
        group="arsenal",
    ),
    ToolDef(
        name="forge_weapon",
        description="使用指定材料和锻造技法打造武器，加入角色库存。材料决定武器类型，技法决定品质。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话 ID"},
                "material":   {"type": "string",
                               "description": "材料名（如 玄铁/精钢/寒玉/神木/龙骨/陨铁/幽金）"},
                "technique":  {"type": "string",
                               "description": "锻造技法（基础锻造/精炼/上古秘法/神兵秘法）",
                               "default": "基础锻造"},
            },
            "required": ["session_id", "material"],
        },
        handler=_forge_weapon,
        permission_required="allow",
        tags=["write", "arsenal"],
        group="arsenal",
    ),
    ToolDef(
        name="evaluate_weapon",
        description="评估角色持有的武器，返回武器评级（S/A/B/C）和建议用途。",
        parameters={
            "type": "object",
            "properties": {
                "session_id":  {"type": "string", "description": "会话 ID"},
                "weapon_name": {"type": "string", "description": "武器名称（支持模糊匹配）"},
            },
            "required": ["session_id", "weapon_name"],
        },
        handler=_evaluate_weapon,
        permission_required="allow",
        tags=["read", "arsenal"],
        group="arsenal",
    ),
    ToolDef(
        name="draw_gacha",
        description=(
            "【无限武库专属】消耗 SP 进行卡池抽取，返回落点框架（tier/tier_sub/category）。"
            "pool_name: 综合池（100 SP）/ 战术池（5000 SP）/ 战略池（250000 SP）。"
            "抽完后需由 GachaAgent 根据落点框架匹配真实 ACG 来源物品并发货。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string",  "description": "会话 ID"},
                "pool_name":  {"type": "string",  "description": "卡池名称（综合池/战术池/战略池）", "default": "综合池"},
                "count":      {"type": "integer", "description": "连抽次数（1-10）", "default": 1},
            },
            "required": ["session_id"],
        },
        handler=_draw_gacha,
        permission_required="ask",
        tags=["write", "gacha", "arsenal"],
        group="arsenal",
    ),
    ToolDef(
        name="earn_battle_rewards",
        description=(
            "【无限武库专属】结算战斗奖励：根据敌人星级发放 SP 和 EXP。"
            "defeated=True 表示战胜；killed=True 表示消灭（击杀 ×1.5 加成）。"
            "在战斗结束后自动调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id":     {"type": "string",  "description": "会话 ID"},
                "enemy_key":      {"type": "string",  "description": "敌人标识"},
                "enemy_tier":     {"type": "integer", "description": "敌人星级 1-5"},
                "enemy_tier_sub": {"type": "string",  "description": "子段位 L/M/U", "default": "M"},
                "defeated":       {"type": "boolean", "description": "是否战胜", "default": True},
                "killed":         {"type": "boolean", "description": "是否击杀", "default": True},
            },
            "required": ["session_id", "enemy_key", "enemy_tier"],
        },
        handler=_earn_battle_rewards,
        permission_required="allow",
        tags=["write", "combat", "economy", "arsenal"],
        group="arsenal",
    ),
]
