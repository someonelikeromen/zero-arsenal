"""
Hook 系统 — 在 Agent 管线的关键节点插入自定义回调。
来自 create-hook skill 的设计模式。

HookEvent 完整列表（对齐 04-extension-system.md §5）：
工具调用层：before_tool_call / after_tool_call
图节点层：  before_agent_node / after_agent_node
会话生命周期：on_session_start / on_session_end / on_session_error
回合生命周期：before_turn / after_turn
变量结算层：before_var_update / after_var_update
NPC 层：    before_npc_response / after_npc_response
叙事层：    after_narrative_generated / after_style_applied
记忆层：    before_memory_compress
骰子层：    on_roll_check
Part 层：   on_part_done
章节层：    on_chapter_end
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    # ── 工具调用（来自 pi agent-loop）────────────────────────────────────
    before_tool_call          = "before_tool_call"
    after_tool_call           = "after_tool_call"
    # ── LangGraph 图节点（来自 opencode Plugin Hooks）──────────────────
    before_agent_node         = "before_agent_node"
    after_agent_node          = "after_agent_node"
    # ── 会话生命周期 ──────────────────────────────────────────────────
    on_session_start          = "on_session_start"
    on_session_end            = "on_session_end"
    on_session_error          = "on_session_error"
    # ── 回合生命周期 ──────────────────────────────────────────────────
    before_turn               = "before_turn"
    after_turn                = "after_turn"
    # ── 变量结算（来自 pi Extension）──────────────────────────────────
    before_var_update         = "before_var_update"
    after_var_update          = "after_var_update"
    # ── NPC（本项目原创）──────────────────────────────────────────────
    before_npc_response       = "before_npc_response"
    after_npc_response        = "after_npc_response"
    # ── 叙事（本项目原创）──────────────────────────────────────────────
    after_narrative_generated = "after_narrative_generated"
    after_style_applied       = "after_style_applied"
    # ── 记忆（本项目原创）──────────────────────────────────────────────
    before_memory_compress    = "before_memory_compress"
    # ── 骰子 ──────────────────────────────────────────────────────────
    on_roll_check             = "on_roll_check"
    # ── Part / 章节 ───────────────────────────────────────────────────
    on_part_done              = "on_part_done"
    on_chapter_end            = "on_chapter_end"
    # ── 错误 ──────────────────────────────────────────────────────────
    on_error                  = "on_error"

    # 别名（兼容旧代码）
    before_agent              = "before_agent_node"
    after_agent               = "after_agent_node"


@dataclass
class HookDef:
    id: str
    event: HookEvent
    handler: Callable                # async (context: dict) -> dict | None
    priority: int = 50               # 数值越小优先级越高
    description: str = ""


class HookManager:
    """
    Hook 管理器。
    - 支持按事件类型注册多个 hook
    - 按 priority 升序触发（数值小的先执行）
    - 单个 handler 失败不影响后续 hook
    - 每个 handler 超时 5 秒自动跳过
    """

    _HANDLER_TIMEOUT = 5.0

    def __init__(self) -> None:
        self._hooks: dict[str, HookDef] = {}

    def register(self, hook: HookDef) -> None:
        """注册 hook。若 id 已存在则覆盖。"""
        self._hooks[hook.id] = hook
        logger.debug(f"HookManager: 注册 hook [{hook.id}] → {hook.event.value} (priority={hook.priority})")

    def unregister(self, hook_id: str) -> bool:
        """注销 hook，返回是否成功删除。"""
        if hook_id in self._hooks:
            del self._hooks[hook_id]
            logger.debug(f"HookManager: 注销 hook [{hook_id}]")
            return True
        return False

    def list_hooks(self, event: Optional[HookEvent] = None) -> list[dict]:
        """
        列出所有 hook 信息，可按事件类型过滤。
        返回格式：[{id, event, priority, description}]
        """
        hooks = list(self._hooks.values())
        if event is not None:
            hooks = [h for h in hooks if h.event == event]
        hooks.sort(key=lambda h: h.priority)
        return [
            {
                "id": h.id,
                "event": h.event.value,
                "priority": h.priority,
                "description": h.description,
            }
            for h in hooks
        ]

    def register_extension_hooks(self, hooks_impl: object, ext_key: str = "", priority: int = 50) -> int:
        """
        将 ExtensionHooks 协议实例的所有已实现方法注册为 HookDef。
        使用方法名 → HookEvent 的固定映射表。
        返回成功注册的数量。（E1 修复）
        """
        _METHOD_TO_EVENT: dict[str, HookEvent] = {
            "before_tool_call":          HookEvent.before_tool_call,
            "after_tool_call":           HookEvent.after_tool_call,
            "before_agent_node":         HookEvent.before_agent_node,
            "after_agent_node":          HookEvent.after_agent_node,
            "on_session_start":          HookEvent.on_session_start,
            "on_session_end":            HookEvent.on_session_end,
            "on_session_error":          HookEvent.on_session_error,
            "on_turn_start":             HookEvent.before_turn,
            "on_turn_end":               HookEvent.after_turn,
            "before_var_update":         HookEvent.before_var_update,
            "after_var_update":          HookEvent.after_var_update,
            "before_npc_response":       HookEvent.before_npc_response,
            "after_npc_response":        HookEvent.after_npc_response,
            "after_narrative_generated": HookEvent.after_narrative_generated,
            "after_style_applied":       HookEvent.after_style_applied,
            "before_memory_compress":    HookEvent.before_memory_compress,
            "on_roll_check":             HookEvent.on_roll_check,
            "on_chapter_end":            HookEvent.on_chapter_end,
        }
        count = 0
        for method_name, event in _METHOD_TO_EVENT.items():
            fn = getattr(hooks_impl, method_name, None)
            # 跳过协议默认实现（只注册具体类中真正覆写的方法）
            if fn is None:
                continue
            base_fn = getattr(type(hooks_impl).__bases__[0], method_name, None) if type(hooks_impl).__bases__ else None
            if fn is base_fn:
                continue
            hook_id = f"ext.{ext_key or type(hooks_impl).__name__}.{method_name}"
            self.register(HookDef(
                id=hook_id,
                event=event,
                handler=fn,
                priority=priority,
                description=f"[Extension:{ext_key}] {method_name}",
            ))
            count += 1
        logger.info("[HookManager] register_extension_hooks: ext=%s, %d hooks registered", ext_key, count)
        return count

    async def fire(self, event: HookEvent, context: dict) -> dict:
        """
        触发指定事件的所有 hook，按 priority 升序执行。
        - 每个 handler 接收并可修改 context dict
        - 单个 handler 失败或超时不影响后续
        - 返回最终 context
        """
        hooks = [h for h in self._hooks.values() if h.event == event]
        hooks.sort(key=lambda h: h.priority)

        for hook in hooks:
            try:
                result = await asyncio.wait_for(
                    hook.handler(context),
                    timeout=self._HANDLER_TIMEOUT,
                )
                # handler 可以返回修改后的 context dict
                if isinstance(result, dict):
                    context.update(result)
            except asyncio.TimeoutError:
                logger.warning(f"HookManager: hook [{hook.id}] 超时 ({self._HANDLER_TIMEOUT}s)，已跳过")
            except Exception as e:
                logger.warning(f"HookManager: hook [{hook.id}] 执行失败 — {e}")

        return context


# 全局单例
hook_manager = HookManager()
