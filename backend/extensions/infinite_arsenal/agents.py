"""
用途: GachaAgent — 无限武库抽卡 Agent 节点
      在 draw_gacha 工具返回落点框架后介入，根据 tier/category 匹配真实 ACG 来源物品并发货。
      插入位置：var_agent 之后（结算阶段）。
用法: 由 extension_loader 自动发现，调用 register_node(GachaAgent()) 注入图。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

try:
    from ...agents.agent_node import AgentNode
    from ...agents.state import TurnContext
except ImportError:
    from backend.agents.agent_node import AgentNode  # type: ignore[no-redef]
    from backend.agents.state import TurnContext  # type: ignore[no-redef]

_log = logging.getLogger(__name__)


def _load_acg_items() -> dict[str, list[dict]]:
    """从 data/acg-source-registry.json 加载 ACG 来源条目，按 category 分类索引。"""
    from pathlib import Path
    registry_path = Path(__file__).parent / "data" / "acg-source-registry.json"
    result: dict[str, list[dict]] = {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        tier_caps: dict[str, int] = data.get("tier_caps", {})
        for src in data.get("sources", []):
            source_name = src.get("display_name", src.get("source_key", ""))
            categories  = src.get("default_categories", ["ApplicationTechnique"])
            max_tier    = tier_caps.get(src.get("source_key", ""), 5)
            for example in src.get("example_items", []):
                # 将 example_item 按来源 tier_cap 分布到 1~max_tier 均匀分配
                estimated_tier = min(3, max_tier)  # 默认 3 星，由 GachaAgent 最终匹配
                for cat in categories:
                    result.setdefault(cat, []).append({
                        "name": example,
                        "source": source_name,
                        "tier": estimated_tier,
                        "max_tier": max_tier,
                        "description": f"来自《{source_name}》的 {example}",
                    })
    except Exception as e:
        _log.warning(f"[GachaAgent] acg-source-registry.json 加载失败: {e}，使用内置种子库")
        return {
            "ApplicationTechnique": [
                {"name": "海军六式（全套）", "source": "海贼王", "tier": 3,
                 "description": "六种超人技能全套：月步/铁块/剃/指枪/纸绘/嵐脚"},
                {"name": "水之呼吸全十一型", "source": "鬼灭之刃", "tier": 2,
                 "description": "水之呼吸全型"},
            ],
            "Weapon": [
                {"name": "王者之剑 Excalibur", "source": "Fate/stay night", "tier": 5,
                 "description": "传说中的圣剑"},
            ],
        }
    return result


# 全局 ACG 物品库（从 JSON 加载）
_ACG_ITEMS: dict[str, list[dict]] = _load_acg_items()


def _pick_item(tier: int, category: str) -> dict:
    """根据 tier 和 category 筛选最匹配的 ACG 物品。"""
    candidates = [
        item for item in _ACG_ITEMS.get(category, [])
        if item.get("tier") == tier
    ]
    if not candidates:
        # 宽泛匹配：相差一星
        candidates = [
            item for item in _ACG_ITEMS.get(category, [])
            if abs(item.get("tier", 0) - tier) <= 1
        ]
    if not candidates:
        # 最终降级：随机返回同类别任意物品
        import random
        all_items = _ACG_ITEMS.get(category, []) or [
            {"name": f"神秘物品·{tier}★", "source": "未知来源",
             "tier": tier, "description": f"来自未知 ACG 世界的 {tier} 星物品"}
        ]
        candidates = all_items
    import random
    return random.choice(candidates)


class GachaAgent(AgentNode):
    """
    无限武库抽卡 Agent。
    在 VarAgent 结算完后介入，检查 TurnContext 是否有待处理的 gacha_pending 记录，
    为每条落点框架匹配 ACG 来源物品并写入角色卡库存。
    """

    name = "gacha_agent"
    display_name = "抽卡发货 Agent"
    insert_after = "var"  # 与 graph.py edge_map 键一致

    async def execute(self, ctx: TurnContext) -> TurnContext:
        pending: list[dict] = ctx.gacha_pending
        if not pending:
            return ctx

        _log.info("[GachaAgent] 处理 %d 条待发货落点", len(pending))
        session_id: str = ctx.session_id
        granted: list[dict] = []

        for frame in pending:
            tier     = int(frame.get("tier", 1))
            tier_sub = str(frame.get("tier_sub", "M"))
            category = str(frame.get("category", "ApplicationTechnique"))

            item = _pick_item(tier, category)
            item_record = {
                "id":          str(uuid.uuid4()),
                "name":        item["name"],
                "source":      item["source"],
                "type":        category,
                "tier":        tier,
                "tier_sub":    tier_sub,
                "description": item["description"],
                "obtained_at": datetime.now().timestamp(),
                "origin":      "gacha",
            }
            granted.append(item_record)
            _log.debug("[GachaAgent] 落点 %d★%s/%s → %s（%s）",
                       tier, tier_sub, category, item["name"], item["source"])

        if granted and session_id:
            await self._write_to_inventory(session_id, granted)

        # 清空待处理队列，写入发货记录
        ctx.gacha_pending = []
        ctx.gacha_granted = ctx.gacha_granted + granted
        return ctx

    @staticmethod
    async def _write_to_inventory(session_id: str, items: list[dict]) -> None:
        """将发货物品追加到角色卡 inventory。"""
        from ...db import get_db
        now = datetime.now().timestamp()
        try:
            async with get_db() as db:
                row = await (await db.execute(
                    "SELECT id, data_json FROM character_cards WHERE session_id=? "
                    "ORDER BY updated_at DESC LIMIT 1", (session_id,)
                )).fetchone()
                if not row:
                    _log.warning("[GachaAgent] session %s 无角色卡，跳过写入", session_id)
                    return
                char = json.loads(row["data_json"])
                inventory: list = char.setdefault("inventory", [])
                inventory.extend(items)
                await db.execute(
                    "UPDATE character_cards SET data_json=?, updated_at=? WHERE id=?",
                    (json.dumps(char, ensure_ascii=False), now, row["id"])
                )
                # 写入记忆条目
                summary = "、".join(i["name"] for i in items)
                await db.execute(
                    "INSERT OR IGNORE INTO memory_entries "
                    "(id, session_id, content, tier, cognitive_partition, source_agent, "
                    "importance, created_at) VALUES (?, ?, ?, 'episodic', 'objective_global', "
                    "'gacha_agent', 0.8, ?)",
                    (str(uuid.uuid4()), session_id,
                     f"抽卡获得：{summary}", now)
                )
                await db.commit()
                _log.info("[GachaAgent] 写入 %d 件物品到 session=%s", len(items), session_id)
        except Exception as e:
            _log.error("[GachaAgent] 写入库存失败: %s", e)


# 供 extension_loader 发现并注册
AGENT_NODES = [GachaAgent()]

# 主动注册到全局图注入表（build_graph 调用 inject_registered_nodes 时生效）
try:
    from ...agents.agent_node import register_node as _register_node  # noqa: E402
except ImportError:
    from backend.agents.agent_node import register_node as _register_node  # type: ignore[no-redef]  # noqa: E402
_register_node(GachaAgent())
