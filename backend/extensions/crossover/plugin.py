"""
综漫无限流 WorldPlugin — 玩家穿越多个动漫/游戏世界执行任务，兼含无限武库能力体系。
设计文档 04-extension-system.md §2.4
"""
from __future__ import annotations
try:
    from ..plugin import WorldPlugin, plugin_registry
except ImportError:
    from backend.extensions.plugin import WorldPlugin, plugin_registry  # type: ignore[no-redef]


class CrossoverPlugin(WorldPlugin):
    """综漫无限流世界插件（含完整生命周期钩子，兼含无限武库能力体系）。"""

    def on_session_init(self, state: dict) -> dict:
        """
        会话创建时写入初始属性：
        - 无限流：主神点数、世界周期、生存计数
        - 武库体系：战斗积分、武器品阶、武器掌握度、初始武器
        """
        char = state.get("character_data", {})
        meta = char.setdefault("meta", {})

        # ── 无限流核心 ──────────────────────────────────────────────────────
        # crossover_points 为经济工具实际读写的键
        meta.setdefault("crossover_points", 1000)
        meta.setdefault("world_cycle", 1)
        meta.setdefault("survival_count", 0)
        meta.setdefault("plugin_key", "crossover")

        # D7：与角色卡 v4 economy 结构对齐
        economy = char.setdefault("economy", {})
        economy.setdefault("points", meta["crossover_points"])
        economy.setdefault("badges", 0)
        economy.setdefault("tier", 0)
        economy.setdefault("tier_sub", "")

        # ── 武库体系 ────────────────────────────────────────────────────────
        meta.setdefault("battle_points",  0)
        meta.setdefault("highest_tier",   "凡品")
        meta.setdefault("artifact_count", 0)
        meta.setdefault("weapon_mastery", 10)

        # ── 属性 ────────────────────────────────────────────────────────────
        attrs = char.setdefault("attributes", {})
        attrs.setdefault("luck",           {"dots": 2, "max": 5,  "description": "幸运值"})
        attrs.setdefault("loyalty",        {"dots": 2, "max": 5,  "description": "忠诚度"})
        attrs.setdefault("artifact_count", {"dots": 0, "max": 10, "description": "持有神器数"})
        attrs.setdefault("weapon_mastery", {"dots": 2, "max": 5,  "description": "武器精通等级"})

        # ── 初始武器（凡品长剑）────────────────────────────────────────────
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
            "无限流铁律：",
            "  · 玩家死亡触发真实死亡机制，意识回归主神空间，丢失本次世界积累的所有points",
            "  · 穿越者携带的技能/道具须在角色卡 inventory 中存在，否则视为非法使用",
            "  · '剧情压'存在：强行违背原作核心剧情节点须消耗额外 points（由 DM 裁量）",
            "  · 不得在世界内透露自己是穿越者（违规触发 NPC 排斥惩罚）",
            "无限武库规则：",
            "  · 使用武器前必须确认角色 inventory 中存在该武器",
            "  · 武器品阶差距超过3级时，低阶武器无法对抗高阶武器的器灵意志",
            "  · 进入秘境/遗迹需满足最低武器品阶门槛（由 DM 设定）",
            "  · 击败强敌后可获得其武器，但须通过器灵认可测试",
            "  · 神品以上武器出场时，天地异象不可避免（叙事必须体现）",
        ]

    def on_turn_start(self, state: dict) -> dict:
        """每轮开始检查 points 耗尽与武器共鸣度。"""
        char = state.get("character_data", {})
        meta = char.get("meta", {})
        points = meta.get("points", 0)
        mastery = meta.get("weapon_mastery", 100)
        if points <= 0:
            state["world_event_hint"] = "⚠ 强化点数耗尽，主神空间警告：继续失败将强制撤离"
        elif mastery < 30:
            state["world_event_hint"] = f"⚠ 武器共鸣度低（{mastery}%），战力仅发挥 {mastery}%"
        return state


crossover_plugin = CrossoverPlugin(
    key="crossover",
    name="综漫无限流",
    description="玩家作为穿越者进入各种动漫/游戏世界完成主神任务，获得强化点数和技能；内含武器收集与神器体系",
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
            "phase": ["all"],
            "content": """\
武库体系：
玩家可收集、精炼各类武器与神器，武器品阶决定战力上限。
- 武器等级（品阶）：凡品 < 灵品 < 玄品 < 地品 < 天品 < 神品 < 无上
- 武器觉醒：顶阶武器拥有器灵，可与持有者共鸣（共鸣度影响实际战力）
- 战斗积分：击败强敌、探索遗迹均可获得，用于武器强化与兑换
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
叙事规范：
- 世界内存在"剧情压"（强制推进原作剧情的力量）
- 原著角色的性格和能力要符合原作设定
- 玩家可以改变剧情走向，但需要付出相应代价
- 穿越者技能带入时注明来源世界
- 武器描写要体现其品阶质感（凡品朴实，神品流光溢彩）
- 战斗中体现武器特性（速度型攻击密集，重击型气势磅礴）
- 器灵台词风格随武器属性变化（火系暴烈，冰系冷淡，雷系亢奋）
- 神器出场时附加环境渲染（天地异象、气运震动等）""",
        },
        {
            "phase": ["all"],
            "content": """\
【世界档案自动生成】
当剧情需要进入一个新的/随机的目标世界时，若档案库中尚无该世界的资料，可调用 generate_world 工具自动建档：
  generate_world(world_name="目标世界名", hints=["英文名或别名"])
工具将自动从 Fandom/萌娘百科/维基百科等来源抓取资料，提炼世界观条目并写入档案库。
建档完成后 world_id 可在世界参考中使用，档案将在后续叙事中提供世界背景支撑。
若目标世界档案已存在，工具会追加新条目而不重复创建世界记录。
调用前无需用户手动操作，工具会询问用户确认后自动执行。""",
        },
    ],
    extra_attributes=["luck", "loyalty", "artifact_count", "weapon_mastery"],
    metadata={
        "point_system": True,
        "multi_world": True,
        "badge_system": True,
        "weapon_system": True,
        "artifact_system": True,
        "tier_system": "凡品/灵品/玄品/地品/天品/神品/无上",
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

PLUGIN = crossover_plugin
