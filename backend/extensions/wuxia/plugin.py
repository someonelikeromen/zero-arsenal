"""
武侠世界 WorldPlugin — 江湖门派、内力修炼、轻功。
"""
from __future__ import annotations
try:
    from ..plugin import WorldPlugin, plugin_registry
except ImportError:
    from backend.extensions.plugin import WorldPlugin, plugin_registry  # type: ignore[no-redef]


class WuxiaPlugin(WorldPlugin):
    """武侠江湖世界插件（含完整生命周期钩子）。"""

    def on_session_init(self, state: dict) -> dict:
        """写入武侠专属初始属性：内力/境界/声望。"""
        char = state.get("character_data", {})
        meta = char.setdefault("meta", {})
        meta.setdefault("realm",      "炼气期")
        meta.setdefault("reputation", 0)
        meta.setdefault("sect",       "无门无派")
        meta.setdefault("world_plugin", "wuxia")

        attrs = char.setdefault("attributes", {})
        attrs.setdefault("qi",         {"dots": 3, "max": 10, "current": 30, "description": "内力"})
        attrs.setdefault("reputation", {"dots": 2, "max": 5, "description": "江湖声望等级"})
        state["character_data"] = char
        return state

    def get_rules_skills(self) -> list[str]:
        return [
            "武侠江湖规则：",
            "  · 内力（qi）归零时，武功无法使用，移动速度减半",
            "  · 境界差距超过2级时，低境界者无法正面硬扛，只能逃跑或智取",
            "  · 江湖声望 < -50 时，主要城镇 NPC 拒绝交易/接任务",
            "  · 门派秘籍不可外传，泄露者将遭追杀",
        ]

    def on_turn_start(self, state: dict) -> dict:
        char = state.get("character_data", {})
        qi = char.get("attributes", {}).get("qi", {}).get("current", 10)
        if qi <= 5:
            state["world_event_hint"] = f"⚠ 内力告急（{qi}点），武功使用受限"
        return state


wuxia_plugin = WuxiaPlugin(
    key="wuxia",
    name="武侠江湖",
    description="传统武侠世界，玩家扮演行走江湖的侠客，修炼内功、闯荡门派",
    system_prompt_fragments=[
        {
            "phase": ["all"],
            "content": """\
世界设定：武侠江湖
江湖由门派、帮会、官府三方势力构成。
核心机制：
- 内力（Qi）：驱动武功的基础能量，通过修炼恢复
- 轻功：影响移动速度和隐蔽能力（DEX特化）
- 武学境界：炼气→化劲→归元→化神，境界影响内力上限
- 江湖声望：行侠仗义提升声望，恶行降低声望""",
        },
        {
            "phase": ["p3"],
            "content": """\
武侠叙事规范：
- 武功招式要有名称（自由命名，体现风格）
- 内力消耗后描写气息变化
- 江湖对话用半文言风格（不必全文言）
- 受伤后描写具体部位感受，不用"HP扣了"等游戏化语言""",
        },
    ],
    extra_attributes=["qi", "reputation"],
    metadata={
        "realm_system": True,
        "sect_system": True,
    },
)

plugin_registry.register(wuxia_plugin)

PLUGIN = wuxia_plugin
