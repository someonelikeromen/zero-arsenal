"""
用途: 会话级生成取消注册表。前端「停止生成」→ DELETE /sessions/{id}/stream
      在此登记取消标记；Agent 管线在节点边界（agent_span）检查并中断。
用法:
    from backend.agents.cancellation import request_cancel, is_cancelled, clear_cancel
环境变量: 无
MCP集成: 不暴露为工具。
Skill集成: 无。
"""
from __future__ import annotations

import threading

# 进程内取消标记集合（单进程部署足够；多进程需迁移到 Redis，见 ARCHITECTURE.md）
_cancelled: set[str] = set()
_lock = threading.Lock()


class TurnCancelled(Exception):
    """玩家主动取消当前回合生成时抛出。"""


def request_cancel(session_id: str) -> None:
    """登记取消请求。"""
    with _lock:
        _cancelled.add(session_id)


def is_cancelled(session_id: str) -> bool:
    """查询会话是否被请求取消。"""
    with _lock:
        return session_id in _cancelled


def clear_cancel(session_id: str) -> None:
    """清除取消标记（回合开始/结束时调用）。"""
    with _lock:
        _cancelled.discard(session_id)
