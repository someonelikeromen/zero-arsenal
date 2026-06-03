"""
<扩展名> 扩展工具集骨架。

TOOLS 列表会被 _discover_extension_tools() 自动注册到 ToolRegistry，
注册后可被 Agent 在管线中调用（受 permission_overlay 约束）。

工具 handler 约定：
- async 函数，第一个参数通常是 session_id
- 返回 JSON 可序列化的 dict
"""
from __future__ import annotations

try:
    from ...tools.registry import ToolDef
except ImportError:
    from backend.tools.registry import ToolDef  # type: ignore[no-redef]


async def _example_tool(session_id: str, target: str = "") -> dict:
    """
    示例工具：返回一个简单结果。
    TODO: 替换为你的真实逻辑（读写 character_cards / 调用引擎等）。
    """
    return {"ok": True, "session_id": session_id, "target": target, "note": "template tool"}


# 自动注册的工具列表（去掉本注释并填入你的工具）
TOOLS: list[ToolDef] = [
    ToolDef(
        name="template_example",
        description="模板示例工具，演示扩展工具注册方式。",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "示例目标参数"},
            },
            "required": [],
        },
        handler=_example_tool,
        tags=["template", "read"],
    ),
]
