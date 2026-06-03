"""
<扩展名> WorldPlugin 骨架。

把本文件复制到你的扩展目录后：
1. 改 key / name / description
2. 在 on_session_init 写入世界专属初始属性
3. 在 get_rules_skills 返回世界铁律（注入 rules_agent）
4. 在 system_prompt_fragments 写世界设定（注入对应阶段提示词）
5. 按需实现 on_turn_start / on_turn_end 钩子
"""
from __future__ import annotations
try:
    from ..plugin import WorldPlugin, plugin_registry
except ImportError:
    from backend.extensions.plugin import WorldPlugin, plugin_registry  # type: ignore[no-redef]


class TemplatePlugin(WorldPlugin):
    """示例世界插件 — 删除本注释并实现你的逻辑。"""

    def on_session_init(self, state: dict) -> dict:
        """会话创建时写入世界专属初始属性（只在首次创建，勿覆盖已有数据）。"""
        char = state.get("character_data", {})
        meta = char.setdefault("meta", {})
        meta.setdefault("example_resource", 0)      # TODO: 替换为你的资源字段
        meta.setdefault("world_plugin", "template")
        state["character_data"] = char
        return state

    def get_rules_skills(self) -> list[str]:
        """返回世界铁律摘要（注入 rules_agent 系统提示）。"""
        return [
            "示例世界铁律：",
            "  · TODO: 在此列出该世界不可违背的硬规则",
        ]

    def on_turn_start(self, state: dict) -> dict:
        """每轮开始的钩子（可选）。"""
        return state


template_plugin = TemplatePlugin(
    key="template",                         # TODO: 唯一键（小写下划线）
    name="模板世界",                         # TODO: 显示名
    description="扩展骨架，复制后修改为你的世界插件。",
    system_prompt_fragments=[
        {
            "phase": ["all"],
            "content": "世界设定：（TODO 在此描述世界观、核心机制、基调）",
        },
    ],
    extra_attributes=[],                    # TODO: 世界专属额外属性（如 ["luck"]）
    metadata={},
    permission_overlay={
        "play": [
            {"pattern": "roll_*", "action": "allow"},
        ],
    },
)

plugin_registry.register(template_plugin)

# 供 extension_loader 直接获取实例
PLUGIN = template_plugin
