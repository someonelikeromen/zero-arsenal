"""
综漫无限流 WorldPlugin — 玩家穿越多个动漫/游戏世界执行任务。
设计文档 04-extension-system.md §2.4
"""
from __future__ import annotations
try:
    from ..plugin import WorldPlugin, plugin_registry
except ImportError:
    from backend.extensions.plugin import WorldPlugin, plugin_registry  # type: ignore[no-redef]


class CrossoverPlugin(WorldPlugin):
    """综漫无限流世界插件（含完整生命周期钩子）。"""

    def on_session_init(self, state: dict) -> dict:
        """
        会话创建时写入无限流专属初始属性：
        - points: 主神点数（初始 1000）
        - badges: 支线徽章列表
        - world_cycle: 当前穿越世界周期编号
        - survival_count: 已完成世界数
        """
        char = state.get("character_data", {})
        meta = char.setdefault("meta", {})

        # 只在首次创建时初始化（避免覆盖已有数据）
        meta.setdefault("points", 1000)
        meta.setdefault("badges", [])
        meta.setdefault("world_cycle", 1)
        meta.setdefault("survival_count", 0)
        meta.setdefault("world_plugin", "crossover")

        # 补全 extra_attributes（luck/loyalty）
        attrs = char.setdefault("attributes", {})
        attrs.setdefault("luck",    {"dots": 2, "max": 5, "description": "幸运值"})
        attrs.setdefault("loyalty", {"dots": 2, "max": 5, "description": "忠诚度"})

        state["character_data"] = char
        return state

    def get_rules_skills(self) -> list[str]:
        """返回无限流世界专属规则摘要（注入 rules_agent 系统提示）。"""
        return [
            "无限流铁律：",
            "  · 玩家死亡触发真实死亡机制，意识回归主神空间，丢失本次世界积累的所有points",
            "  · 穿越者携带的技能/道具须在角色卡 inventory 中存在，否则视为非法使用",
            "  · '剧情压'存在：强行违背原作核心剧情节点须消耗额外 points（由 DM 裁量）",
            "  · 不得在世界内透露自己是穿越者（违规触发 NPC 排斥惩罚）",
        ]

    def on_turn_start(self, state: dict) -> dict:
        """每轮开始时检查 points 是否耗尽（若 ≤0 触发任务失败提示）。"""
        char = state.get("character_data", {})
        points = char.get("meta", {}).get("points", 0)
        if points <= 0:
            state["world_event_hint"] = "⚠ 强化点数耗尽，主神空间警告：继续失败将强制撤离"
        return state


crossover_plugin = CrossoverPlugin(
    key="crossover",
    name="综漫无限流",
    description="玩家作为穿越者进入各种动漫/游戏世界完成主神任务，获得强化点数和技能",
    system_prompt_fragments=[
        {
            "phase": ["all"],
            "content": """\
世界设定：综漫无限流
玩家作为"无限流穿越者"受主神空间委派，进入各类动漫/游戏世界执行任务。
核心机制：
- 强化点数（Points）：完成任务/支线获得，可在主神空间购买强化
- 支线徽章（D/C/B/A/S/SS级）：完成支线任务奖励，可兑换稀有能力
- 穿越规则：每个世界有固定周期，周期结束强制撤离
- 死亡惩罚：真实死亡，意识回归主神空间（可复活但损失强化）""",
        },
        {
            "phase": ["p3"],
            "content": """\
无限流叙事规范：
- 世界内存在"剧情压"（强制推进原作剧情的力量）
- 原著角色的性格和能力要符合原作设定
- 玩家可以改变剧情走向，但需要付出相应代价
- 穿越者技能带入时注明来源世界""",
        },
    ],
    extra_attributes=["luck", "loyalty"],
    metadata={
        "point_system": True,
        "multi_world": True,
        "badge_system": True,
    },
    permission_overlay={
        "play": [
            {"pattern": "roll_*", "action": "allow"},
            {"pattern": "search_*", "action": "allow"},
        ],
        "review": [
            {"pattern": "update_*", "action": "ask"},
            {"pattern": "write_*", "action": "ask"},
        ],
    },
)

plugin_registry.register(crossover_plugin)

# 供 extension_loader 直接获取实例（避免自动实例化无参数错误）
PLUGIN = crossover_plugin
