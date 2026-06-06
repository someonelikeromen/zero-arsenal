"""
GundamSeedWorldPlugin — Gundam SEED / CE71 世界插件。

世界设定：宇宙世纪 CE71，血色情人节事件后半年，
ZAFT 与地球联合军激战，协调者与自然人矛盾激化。

按 02-system-architecture.md WorldPlugin 接口实现。
"""
from __future__ import annotations
from pathlib import Path

_HERE = Path(__file__).parent


class GundamSeedWorldPlugin:
    """Gundam SEED CE71 世界插件。"""

    plugin_id = "gundam_seed"
    display_name = "Gundam SEED — 宇宙世纪 CE71"

    # ── 世界规则 ──────────────────────────────────────────────────────────────

    def get_world_rules(self) -> str:
        """加载 rules/ 目录下所有规则文件并合并返回。"""
        rules_dir = _HERE / "rules"
        parts: list[str] = []
        for md_file in sorted(rules_dir.glob("*.md")):
            parts.append(md_file.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(parts) if parts else ""

    # ── 世界上下文（注入 Prompt） ─────────────────────────────────────────────

    def get_world_context(self, session_meta: dict | None = None) -> str:
        """返回当前世界状态的上下文描述，注入 WorldAgent Prompt。"""
        _ = session_meta
        return (
            "【宇宙世纪 CE71】\n"
            "· 血色情人节（CE70-02-11）后半年，全面战争爆发\n"
            "· 主要势力：ZAFT（协调者军）、地球联合军（自然人）、中立奥布联合酋长国\n"
            "· 关键技术：核动力 MS 禁止（N-盾条约）、GAT-X 系列（联合）、ZGMF-X 系列（ZAFT）\n"
            "· 协调者歧视合法化；LOGOS/蓝色宇宙 右翼抬头\n"
            "· 军事科技：核能裁减推动 Phase-Shift 装甲、自然能（Ultracompact Accumulator）主流化"
        )

    # ── 物品/技能数据 ─────────────────────────────────────────────────────────

    def get_skill_catalog(self) -> list[dict]:
        """返回本世界可用的技能/能力目录（供抽卡/兑换系统参考）。"""
        skills_dir = _HERE / "skills"
        catalog: list[dict] = []
        for yaml_file in sorted(skills_dir.glob("*.json")):
            import json
            try:
                catalog.append(json.loads(yaml_file.read_text(encoding="utf-8")))
            except Exception:
                pass
        return catalog

    # ── 元信息 ────────────────────────────────────────────────────────────────

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "world_rules_loaded": bool(self.get_world_rules()),
            "skill_count": len(self.get_skill_catalog()),
        }


# ── 模块级实例 ────────────────────────────────────────────────────────────────
_plugin_instance = GundamSeedWorldPlugin()

# ── WorldPlugin dataclass 实例（E4修复：供 plugin_registry.register() 使用）────
import logging as _logging
_logger = _logging.getLogger(__name__)
try:
    try:
        from ..plugin import WorldPlugin as _WP
        from ...prompts.registry import PromptFragment as _PF
    except ImportError:
        from backend.extensions.plugin import WorldPlugin as _WP  # type: ignore[no-redef]
        from backend.prompts.registry import PromptFragment as _PF  # type: ignore[no-redef]
    PLUGIN = _WP(
        key="gundam_seed",
        name="Gundam SEED — CE71",
        description="宇宙世纪 CE71，血色情人节后半年，协调者与自然人战争",
        agent_profile="play",
        system_prompt_fragments=[
            _PF(
                id="gundam_seed.world_rules",
                layer="world",
                phase=["dm", "rules"],
                priority=200,
                content=_plugin_instance.get_world_rules(),
                condition="state.get('plugin_key') == 'gundam_seed'",
            ),
            _PF(
                id="gundam_seed.world_context",
                layer="world",
                phase=["p3", "p1"],
                priority=210,
                content=_plugin_instance.get_world_context(),
                condition="state.get('plugin_key') == 'gundam_seed'",
            ),
        ],
    )
except Exception as _e:
    _logger.warning("[GundamSeed] PLUGIN dataclass init failed: %s", _e)
    PLUGIN = None  # type: ignore[assignment]
