"""
无限武库 WorldPlugin — 高武世界，玩家收集武器、法器、神器，通过战斗和探索强化自身。
"""
from __future__ import annotations
try:
    from ..plugin import WorldPlugin, plugin_registry
except ImportError:
    from backend.extensions.plugin import WorldPlugin, plugin_registry  # type: ignore[no-redef]


class InfiniteArsenalPlugin(WorldPlugin):
    """无限武库世界插件（含完整生命周期钩子）。"""

    def on_session_init(self, state: dict) -> dict:
        """写入无限武库专属初始属性：战斗积分/武器品阶/武器数量。"""
        char = state.get("character_data", {})
        meta = char.setdefault("meta", {})
        meta.setdefault("battle_points",   0)       # 战斗积分
        meta.setdefault("highest_tier",    "凡品")   # 当前持有最高品阶武器
        meta.setdefault("artifact_count",  0)       # 持有神器数量
        meta.setdefault("weapon_mastery",  10)      # 武器掌握度（0-100）
        meta.setdefault("world_plugin",    "infinite_arsenal")

        attrs = char.setdefault("attributes", {})
        attrs.setdefault("artifact_count", {"dots": 0, "max": 10, "description": "持有神器数"})
        attrs.setdefault("weapon_mastery", {"dots": 2, "max": 5,  "description": "武器精通等级"})

        # 初始武器（凡品长剑）
        inventory: list = char.setdefault("inventory", [])
        if not any(i.get("key") == "starter_sword" for i in inventory):
            inventory.append({
                "id": "starter_sword",
                "key": "starter_sword",
                "name": "铁质长剑",
                "count": 1,
                "quality": "common",
                "description": "凡品武器，无特殊属性，适合初学者使用",
                "metadata": {"tier": "凡品", "resonance": 0},
            })

        state["character_data"] = char
        return state

    def get_rules_skills(self) -> list[str]:
        return [
            "无限武库规则：",
            "  · 使用武器前必须确认角色 inventory 中存在该武器",
            "  · 武器品阶差距超过3级时，低阶武器无法对抗高阶武器的器灵意志",
            "  · 进入秘境/遗迹需满足最低武器品阶门槛（由 DM 设定）",
            "  · 击败强敌后可获得其武器，但须通过器灵认可测试",
            "  · 神品以上武器出场时，天地异象不可避免（叙事必须体现）",
        ]

    def on_turn_start(self, state: dict) -> dict:
        """检查武器共鸣度。"""
        char = state.get("character_data", {})
        mastery = char.get("meta", {}).get("weapon_mastery", 100)
        if mastery < 30:
            state["world_event_hint"] = f"⚠ 武器共鸣度低（{mastery}%），战力仅发挥 {mastery}%"
        return state


infinite_arsenal_plugin = InfiniteArsenalPlugin(
    key="infinite_arsenal",
    name="无限武库",
    description="高武世界，玩家收集各种武器、法器、神器，通过战斗和探索强化自身",
    system_prompt_fragments=[
        {
            "phase": ["all"],
            "content": """\
世界设定：无限武库
玩家身处高武奇幻世界，以收集、精炼、掌握各类武器与神器为核心目标。
核心机制：
- 武器等级（品阶）：凡品 < 灵品 < 玄品 < 地品 < 天品 < 神品 < 无上
- 武器觉醒：顶阶武器拥有器灵或特殊意志，可与持有者共鸣
- 战斗积分：击败强敌、探索遗迹、完成委托均可获得战斗积分
- 武器传承：击败持有者可获得其武器，但需通过武器认可测试
- 神器碎片：神品以上武器可能残留碎片，集齐后可复原完整神器""",
        },
        {
            "phase": ["p1"],
            "content": """\
无限武库规划规则：
- 战斗后必须结算战斗积分和可能的武器掉落
- 进入遗迹/秘境前需确认玩家当前最强武器的品阶是否满足进入门槛
- 器灵共鸣状态影响武器实际发挥（共鸣度低时战力打折）""",
        },
        {
            "phase": ["p3"],
            "content": """\
无限武库叙事规范：
- 武器描写要体现其品阶质感（凡品朴实，神品流光溢彩）
- 战斗中体现武器特性（如速度型武器攻击密集，重击型武器气势磅礴）
- 器灵台词风格随武器属性变化（火系暴烈，冰系冷淡，雷系亢奋）
- 神器出场时附加环境渲染（天地异象、气运震动等）""",
        },
    ],
    extra_attributes=["artifact_count", "weapon_mastery"],
    metadata={
        "weapon_system": True,
        "artifact_system": True,
        "plot_pressure": False,
        "tier_system": "凡品/灵品/玄品/地品/天品/神品/无上",
    },
)

plugin_registry.register(infinite_arsenal_plugin)

PLUGIN = infinite_arsenal_plugin
