"""
WuxiaHooks — 武侠世界 Hook 实现示例。
实现 ExtensionHooks Protocol，由 hook_protocol.discover_and_register_hooks() 自动发现。

示例效果：
- on_roll_check：内力高于 80 时降低骰子难度（修炼加成）
- before_tool_call：记录武器相关工具调用到日志
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class WuxiaHooks:
    """
    武侠世界专属 Hook。
    继承 ExtensionHooks Protocol 中需要的方法即可，无需 import Protocol 基类。
    """

    async def on_roll_check(self, ctx: dict) -> dict:
        """
        内力高时降低检定难度（修炼境界加成）。
        内力 > 80 → threshold -1（最低 4）
        内力 > 95 → threshold -2（最低 4）
        """
        char_data = ctx.get("character_data", {})
        derived = char_data.get("derived", {})
        inner_force = 0

        # 兼容两种字段路径
        if isinstance(derived, dict):
            inner_force = derived.get("inner_force", 0)
        if not inner_force:
            meta = char_data.get("meta", {})
            inner_force = meta.get("inner_force", 0)

        original = ctx.get("threshold", 8)
        if inner_force > 95:
            ctx["threshold"] = max(4, original - 2)
            logger.debug(
                f"[WuxiaHooks] on_roll_check: inner_force={inner_force} "
                f"threshold {original} -> {ctx['threshold']} (玄阶加成)"
            )
        elif inner_force > 80:
            ctx["threshold"] = max(4, original - 1)
            logger.debug(
                f"[WuxiaHooks] on_roll_check: inner_force={inner_force} "
                f"threshold {original} -> {ctx['threshold']} (修炼加成)"
            )

        return ctx

    async def before_tool_call(self, ctx: dict) -> dict:
        """
        武器/修炼类工具调用前记录日志（不阻断）。
        """
        tool_name = ctx.get("tool_name", "")
        if any(kw in tool_name for kw in ("cultivate", "forge", "weapon", "arsenal")):
            char_data = ctx.get("character_data", {})
            realm = char_data.get("meta", {}).get("realm", "未知境界")
            logger.info(
                f"[WuxiaHooks] before_tool_call: tool={tool_name}, realm={realm}"
            )
        ctx.setdefault("allow", True)
        return ctx
