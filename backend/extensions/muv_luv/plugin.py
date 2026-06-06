"""
MUV-LUV Alternative WorldPlugin — 世界插件实现。
对齐 04-extension-system.md §3 WorldPlugin 接口。

世界设定：
- 时间：1998 年（BETA 登陆地球后约 8 年）
- 主战场：欧亚大陆防线，日本列岛
- 主要势力：国連軍、日本帝国軍、OSF（国際義勇軍）、BETA
- 技术：TSF（戦術步行戦闘機）、強化装備（Fortified Suit）、XM3 OS（1998年尚未出现）
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

WORLD_KEY = "muv_luv"
WORLD_KEY_ALT = "muv_luv_alternative"


class MuvLuvWorldPlugin:
    """MUV-LUV 世界插件。"""

    world_key = WORLD_KEY
    name = "MUV-LUV Alternative"

    # ── 世界规则注入 ─────────────────────────────────────────────────────────

    def get_world_rules(self) -> str:
        """返回注入 DM / Rules Agent 的世界规则文本。"""
        return """\
[世界规则：MUV-LUV Alternative 1998]
1. 技术边界：XM3 OS 尚未存在（白银武 2001 年带来）。当前 OS 为帝国军自研版本，性能较差。
2. 势力态度：自然人（Natural）对协调者（Coordinator/Enhanced Human）存在显著偏见。
3. 行动限制：TSF 以外的民间载具不可进入 BETA 控制区域。
4. 骰子约定：TSF 驾驶检定使用反应（Dexterity）+知觉（Perception），高风险战斗额外需要意志（Composure）检定。
5. 死亡规则：BETA 战斗中，HP 归零代表 TSF 被击毁，角色可能重伤或阵亡（由 DM 裁定）。
"""

    def get_world_context(self, session_state: dict | None = None) -> str:
        """返回注入 Narrator 的当前世界背景。"""
        year = (session_state or {}).get("world_year", 1998)
        return f"""\
当前时间线：{year} 年
BETA 控制区域：欧亚大陆 60%，中国大陆全境，朝鲜半岛
防线状态：日本列岛暂时安全，明斯克防线岌岌可危
技术水平：第二世代 TSF 主流（F-15 Eagle、武御雷等）
"""

    def apply_to_registry(self, registry) -> None:
        """向 PromptRegistry 注入世界片段（05-prompt-architecture.md §3）。"""
        try:
            from ...prompts.registry import PromptFragment
            _cond = f"state.get('plugin_key') in ['{WORLD_KEY}', '{WORLD_KEY_ALT}']"
            registry.register(PromptFragment(
                id=f"{WORLD_KEY}.world_rules",
                layer="world",
                phase=["dm", "rules"],
                priority=200,
                content=self.get_world_rules(),
                condition=_cond,
            ))
            registry.register(PromptFragment(
                id=f"{WORLD_KEY}.world_context",
                layer="world",
                phase=["p3", "p1"],
                priority=210,
                content=self.get_world_context(),
                condition=_cond,
            ))
        except Exception as e:
            logger.warning(f"[MuvLuvPlugin] apply_to_registry 失败: {e}")


# ── 插件入口（extension_loader 自动发现）──────────────────────────────────────
_plugin_instance = MuvLuvWorldPlugin()

def get_plugin() -> MuvLuvWorldPlugin:
    return _plugin_instance


# ── WorldPlugin dataclass 实例（E4修复：供 plugin_registry.register() 使用）────
try:
    try:
        from ...extensions.plugin import WorldPlugin as _WP
        from ...prompts.registry import PromptFragment as _PF
    except ImportError:
        from backend.extensions.plugin import WorldPlugin as _WP  # type: ignore[no-redef]
        from backend.prompts.registry import PromptFragment as _PF  # type: ignore[no-redef]
    PLUGIN = _WP(
        key=WORLD_KEY,
        name="MUV-LUV Alternative",
        description="1998年 BETA 战争世界线，TSF 机甲战斗，高死亡率反乌托邦",
        agent_profile="play",
        system_prompt_fragments=[
            _PF(
                id=f"{WORLD_KEY}.world_rules",
                layer="world",
                phase=["dm", "rules"],
                priority=200,
                content=_plugin_instance.get_world_rules(),
                condition=f"state.get('plugin_key') in ['{WORLD_KEY}', '{WORLD_KEY_ALT}']",
            ),
            _PF(
                id=f"{WORLD_KEY}.world_context",
                layer="world",
                phase=["p3", "p1"],
                priority=210,
                content=_plugin_instance.get_world_context(),
                condition=f"state.get('plugin_key') in ['{WORLD_KEY}', '{WORLD_KEY_ALT}']",
            ),
        ],
    )
except Exception as _e:
    logger.warning("[MuvLuv] PLUGIN dataclass init failed: %s", _e)
    PLUGIN = None  # type: ignore[assignment]
