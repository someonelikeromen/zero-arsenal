"""
用途: 外部 MCP 子 Agent 调用路径（设计 03-agent-system.md §8.3 / §8.2 shield 隔离）。
用法: from backend.agents.external_agent import call_external_agent
      result = await call_external_agent("my_server", "summarize", {"text": ...})
环境变量:
    ZERO_ARSENAL_EXTERNAL_AGENT_TIMEOUT — 外部 Agent 调用超时秒数（默认 300，对齐 D19）
MCP集成: 直接复用 tools/mcp_bridge 的 MCP HTTP 调用通道。
Skill集成: 无。

D13：外部 MCP 子 Agent 的调用必须用 `asyncio.shield` 包裹，使其不随父回合（turn）
的取消而被中途撕裂 —— 父任务被取消时，已在途的外部调用应当跑完（或自行超时），
避免外部服务侧留下半成品状态 / 资源泄漏。本模块提供统一入口与超时/异常归一化。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _default_timeout() -> float:
    try:
        return float(os.environ.get("ZERO_ARSENAL_EXTERNAL_AGENT_TIMEOUT", "300"))
    except ValueError:
        return 300.0


async def call_external_agent(
    server_name: str,
    tool_name: str,
    args: Optional[dict] = None,
    *,
    timeout: Optional[float] = None,
) -> dict:
    """
    调用外部 MCP 子 Agent（工具），返回归一化结果 dict（始终含 ok 字段）。

    隔离语义（D13 / §8.2）：
    - 实际调用以独立 task 运行，并用 `asyncio.shield` 包裹 await：父回合取消时
      不会强制取消在途的外部调用（防止外部状态半成品）。
    - 用 `asyncio.wait_for` 施加硬超时；超时仅放弃等待，shielded task 仍会自然跑完
      或自行因底层 HTTP 超时结束（不阻塞管线返回）。

    Returns:
        {"ok": True, "result": <dict>} 或 {"ok": False, "error": "...", ...}
    """
    args = args or {}
    timeout = timeout if timeout is not None else _default_timeout()

    try:
        from ..tools.mcp_bridge import mcp_bridge
    except Exception as e:
        logger.warning("[external_agent] mcp_bridge 不可用: %s", e)
        return {"ok": False, "error": "mcp_bridge_unavailable", "detail": str(e)}

    async def _invoke() -> dict:
        return await mcp_bridge.call_tool(server_name, tool_name, args)

    # 独立 task + shield：父取消不撕裂在途外部调用
    task = asyncio.ensure_future(_invoke())
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "[external_agent] %s/%s 超时（%.0fs），放弃等待但不强杀在途调用",
            server_name, tool_name, timeout,
        )
        return {"ok": False, "error": "external_agent_timeout",
                "server": server_name, "tool": tool_name, "timeout": timeout}
    except asyncio.CancelledError:
        # 父回合被取消：shield 已保护 task 继续运行，这里把取消向上传播，
        # 但记录一条日志以便排查（task 不会被撕裂）。
        logger.info(
            "[external_agent] 父回合取消，%s/%s 在途调用受 shield 保护继续执行",
            server_name, tool_name,
        )
        raise
    except Exception as e:
        logger.warning("[external_agent] %s/%s 调用异常: %s: %s",
                       server_name, tool_name, type(e).__name__, e)
        return {"ok": False, "error": "external_agent_failed",
                "server": server_name, "tool": tool_name, "detail": str(e)}

    if isinstance(result, dict) and result.get("error"):
        return {"ok": False, "error": result["error"], "server": server_name,
                "tool": tool_name, "result": result}
    return {"ok": True, "result": result}
