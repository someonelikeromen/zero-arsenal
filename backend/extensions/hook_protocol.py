"""
ExtensionHooks Protocol — 扩展可实现此 Protocol 来挂钩系统事件。
扫描 extensions/*/hooks.py，自动注册到 HookManager。
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ExtensionHooks(Protocol):
    """
    扩展 Hook 协议接口（对齐 04-extension-system.md §5 完整 14 类）。
    extensions/*/hooks.py 中实现此协议的类，将被自动注册到 HookManager。
    所有方法均为可选（不实现则忽略）。
    """

    # ── 工具调用 Hook ─────────────────────────────────────────────────
    async def before_tool_call(self, ctx: dict) -> dict:
        """工具调用前触发，返回 ctx（allow=False 可阻止调用）。"""
        ...

    async def after_tool_call(self, ctx: dict) -> dict:
        """工具调用后触发，可修改工具返回结果。"""
        ...

    # ── 图节点 Hook ───────────────────────────────────────────────────
    async def before_agent_node(self, ctx: dict) -> dict:
        """每个 LangGraph 节点执行前调用，ctx 含 agent_name/state。"""
        ...

    async def after_agent_node(self, ctx: dict) -> dict:
        """每个 LangGraph 节点执行后调用，ctx 含 agent_name/state。"""
        ...

    # ── 会话生命周期 ──────────────────────────────────────────────────
    async def on_session_start(self, ctx: dict) -> dict:
        """会话创建时调用（首次 turn 的 before_turn 之前）。"""
        ...

    async def on_session_end(self, ctx: dict) -> dict:
        """会话正常结束时调用（归档完成后），只读。"""
        ...

    async def on_session_error(self, ctx: dict) -> dict:
        """管线抛出异常时调用，ctx 含 error 字段，只读。"""
        ...

    # ── 回合生命周期 ──────────────────────────────────────────────────
    async def on_turn_start(self, ctx: dict) -> dict:
        """回合开始前触发，可修改 ctx 数据（兼容旧名 before_turn）。"""
        ...

    async def on_turn_end(self, ctx: dict) -> dict:
        """回合结束后触发（after_turn）。"""
        ...

    # ── 变量结算 Hook ─────────────────────────────────────────────────
    async def before_var_update(self, ctx: dict) -> dict:
        """变量结算前，ctx 含 update dict。返回 skip=True 可跳过此条更新。"""
        ...

    async def after_var_update(self, ctx: dict) -> dict:
        """变量结算后，可触发副作用（如成就检查）。"""
        ...

    # ── NPC Hook ──────────────────────────────────────────────────────
    async def before_npc_response(self, ctx: dict) -> dict:
        """NPC 子 Session 启动前调用，ctx 含 npc_key/state。"""
        ...

    async def after_npc_response(self, ctx: dict) -> dict:
        """NPC 响应生成后调用，可修改 ctx.response。"""
        ...

    # ── 叙事 Hook ─────────────────────────────────────────────────────
    async def after_narrative_generated(self, ctx: dict) -> dict:
        """NarratorAgent P3 完成后、StyleAgent 前，ctx 含 narrative 文本。"""
        ...

    async def after_style_applied(self, ctx: dict) -> dict:
        """StyleAgent 完成后，ctx 含最终 narrative 与 purity_score。"""
        ...

    # ── 记忆 Hook ─────────────────────────────────────────────────────
    async def before_memory_compress(self, ctx: dict) -> dict:
        """记忆压缩前，ctx 含 turns_to_compress 列表，可过滤或标记。"""
        ...

    # ── 骰子 + 章节 ───────────────────────────────────────────────────
    async def on_roll_check(self, ctx: dict) -> dict:
        """骰子判定前触发，可修改 threshold/pool。"""
        ...

    async def on_chapter_end(self, ctx: dict) -> dict:
        """章节固化后触发。"""
        ...


def discover_and_register_hooks() -> int:
    """
    扫描三级扩展目录（内置/用户/项目）的 hooks.py，自动注册到 HookManager。

    NEW-C8-02：复用 `discover_extensions()` 的 bundle 路径，天然跳过 `_` 前缀目录
              （如 `_template`），不再用裸 glob 误加载骨架钩子。
    NEW-C8-04：三级目录全部覆盖（此前硬编码仅扫描 backend/extensions/）。
    NEW-C8-06：只实例化类名以 Hook/Hooks 结尾或显式 HOOKS 导出的类，避免盲目
              实例化模块内任意类（含 import 进来的第三方类）。
    NEW-C8-03/C9-04：hook_id 统一为 `ext.{ext_key}.{method}`，与
              `HookManager.register_extension_hooks`（loader 路径）一致，使两条
              注册路径产生相同 id → 后者覆盖前者 → 去重（消除 wuxia 等双重触发）。
    返回成功注册的钩子数量。
    """
    from ..hooks.hook_manager import hook_manager, HookEvent, HookDef
    import importlib.util
    import sys

    count = 0

    # 协议方法名 → HookEvent 映射（完整 14 类）
    _EVENT_MAP: dict[str, HookEvent] = {
        # 工具调用
        "before_tool_call":          HookEvent.before_tool_call,
        "after_tool_call":           HookEvent.after_tool_call,
        # 图节点
        "before_agent_node":         HookEvent.before_agent_node,
        "after_agent_node":          HookEvent.after_agent_node,
        # 会话生命周期
        "on_session_start":          HookEvent.on_session_start,
        "on_session_end":            HookEvent.on_session_end,
        "on_session_error":          HookEvent.on_session_error,
        # 回合生命周期
        "on_turn_start":             HookEvent.before_turn,
        "on_turn_end":               HookEvent.after_turn,
        # 变量结算
        "before_var_update":         HookEvent.before_var_update,
        "after_var_update":          HookEvent.after_var_update,
        # NPC
        "before_npc_response":       HookEvent.before_npc_response,
        "after_npc_response":        HookEvent.after_npc_response,
        # 叙事
        "after_narrative_generated": HookEvent.after_narrative_generated,
        "after_style_applied":       HookEvent.after_style_applied,
        # 记忆
        "before_memory_compress":    HookEvent.before_memory_compress,
        # 骰子 + 章节
        "on_roll_check":             HookEvent.on_roll_check,
        "on_chapter_end":            HookEvent.on_chapter_end,
    }

    # NEW-C8-04：复用三级目录发现（含 user/project 级），而非硬编码内置目录。
    try:
        from .extension_loader import discover_extensions
        bundles = list(discover_extensions().values())
    except Exception as e:
        logger.warning(f"[HookProtocol] discover_extensions 失败，回退仅扫描内置目录: {e}")
        bundles = []

    if bundles:
        _iter = [(b.ext_id, b.path / "hooks.py") for b in bundles]
    else:
        # 回退：仅内置目录，仍跳过 `_` 前缀目录
        ext_root = Path(__file__).parent
        _iter = [
            (f.parent.name, f) for f in ext_root.glob("*/hooks.py")
            if not f.parent.name.startswith("_")
        ]

    for ext_key, hooks_file in _iter:
        if not hooks_file.exists():
            continue
        try:
            # 动态导入 extensions/{ext_key}/hooks.py
            module_name = f"zero_arsenal_ext_{ext_key}_hooks"
            spec = importlib.util.spec_from_file_location(module_name, hooks_file)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            # NEW-C8-06：优先用显式 HOOKS 导出；否则只取类名以 Hook/Hooks 结尾的类，
            # 不再盲目实例化模块内任意类。
            candidates: list[tuple[str, object]] = []
            explicit = getattr(module, "HOOKS", None)
            if explicit is not None and not isinstance(explicit, type):
                candidates.append((type(explicit).__name__, explicit))
            else:
                for attr_name in dir(module):
                    obj = getattr(module, attr_name)
                    if not (isinstance(obj, type) and obj is not ExtensionHooks):
                        continue
                    if not (attr_name.endswith("Hook") or attr_name.endswith("Hooks")):
                        continue
                    try:
                        candidates.append((attr_name, obj()))
                    except Exception:
                        continue

            for attr_name, instance in candidates:
                cls = type(instance)
                # 为每个已实现的方法注册对应 HookEvent
                for method_name, event in _EVENT_MAP.items():
                    method = getattr(instance, method_name, None)
                    if method and callable(method) and method_name in cls.__dict__:
                        # NEW-C8-03：与 loader 路径 (register_extension_hooks) 同 id 以去重
                        hook_id = f"ext.{ext_key}.{method_name}"
                        hook_def = HookDef(
                            id=hook_id,
                            event=event,
                            handler=method,
                            priority=50,
                            description=f"Extension hook: {ext_key}/{attr_name}.{method_name}",
                        )
                        hook_manager.register(hook_def)
                        count += 1
                        logger.debug(f"[HookProtocol] registered {hook_id}")

        except Exception as e:
            logger.warning(f"[HookProtocol] failed to load {hooks_file}: {e}")

    logger.info(f"[HookProtocol] discovered {count} hooks (3-tier scan)")
    return count
