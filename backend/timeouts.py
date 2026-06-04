"""
集中分级超时常量（D19 / 设计 07-tool-registry §7.2）。

四档语义：
- GLOBAL_TOOL_TIMEOUT   普通工具执行默认超时
- LONG_RUNNING_TIMEOUT  长任务（LLM 生成、外部子 Agent）超时
- MCP_TIMEOUT           外部 MCP 调用超时
- PERMISSION_ASK_TIMEOUT 权限 ask 等待用户决策超时（超时 = deny，fail-closed）

所有数值单位为秒。各消费点统一引用本模块，避免散落的魔法数字。
"""
from __future__ import annotations

GLOBAL_TOOL_TIMEOUT: float = 30.0
LONG_RUNNING_TIMEOUT: float = 120.0
MCP_TIMEOUT: float = 15.0
PERMISSION_ASK_TIMEOUT: float = 300.0
