"""
Ask 权限交互处理器 — 在 review/plan 模式下，工具调用需要用户确认时暂停管线。
实现方式：asyncio.Event 同步，超时后自动拒绝。
"""
from __future__ import annotations
import asyncio
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ask 请求超时秒数（超时视为 deny）
ASK_TIMEOUT_SECONDS = 60


@dataclass
class PendingAsk:
    ask_id: str
    session_id: str
    tool_name: str
    tool_args: dict
    reason: str
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _decision: str = "pending"   # pending | allow | deny

    async def wait(self) -> str:
        """等待用户决策，超时返回 deny。"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=ASK_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._decision = "deny"
        return self._decision

    def resolve(self, decision: str) -> None:
        """用户作出决策（allow/deny）。"""
        self._decision = decision
        self._event.set()


class AskManager:
    """管理所有 pending ask 请求。"""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAsk] = {}

    def create_ask(self, session_id: str, tool_name: str,
                   tool_args: dict, reason: str = "") -> PendingAsk:
        ask_id = str(uuid.uuid4())
        ask = PendingAsk(
            ask_id=ask_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            reason=reason,
        )
        self._pending[ask_id] = ask
        return ask

    def resolve(self, ask_id: str, decision: str) -> bool:
        ask = self._pending.get(ask_id)
        if not ask:
            return False
        ask.resolve(decision)
        del self._pending[ask_id]
        return True

    def list_pending(self, session_id: str) -> list[dict]:
        return [
            {"ask_id": a.ask_id, "tool_name": a.tool_name,
             "tool_args": a.tool_args, "reason": a.reason}
            for a in self._pending.values()
            if a.session_id == session_id
        ]


ask_manager = AskManager()


async def check_permission_and_ask(
    session_id: str,
    tool_name: str,
    tool_args: dict,
    profile_name: str,
    reason: str = "",
) -> bool:
    """
    检查权限并处理 ask 交互。
    返回 True = 允许执行，False = 拒绝。
    """
    from .permission import profile_registry, PermissionAction
    from ..bus import bus, BusEvent, EventType

    # 优先使用会话级有效 Profile（含 WorldPlugin overlay）
    effective_profile = profile_registry.get_session_profile(session_id, profile_name)
    action = effective_profile.check_tool(tool_name)

    if action == PermissionAction.ALLOW:
        return True
    if action == PermissionAction.DENY:
        return False

    # ASK 模式：发布 permission_ask Part，等待用户确认
    ask = ask_manager.create_ask(session_id, tool_name, tool_args, reason)

    await bus.publish(BusEvent(
        type=EventType.PERMISSION_ASK,
        session_id=session_id,
        data={
            "ask_id": ask.ask_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "reason": reason,
        }
    ))

    decision = await ask.wait()
    logger.info(f"ask {ask.ask_id} resolved: {decision}")

    # 发布 permission.granted 或 permission.denied SSE
    result_event_type = (
        EventType.PERMISSION_GRANTED if decision == "allow" else EventType.PERMISSION_DENIED
    )
    try:
        await bus.publish(BusEvent(
            type=result_event_type,
            session_id=session_id,
            data={
                "ask_id": ask.ask_id,
                "tool_name": tool_name,
                "decision": decision,
            }
        ))
    except Exception:
        pass

    return decision == "allow"
