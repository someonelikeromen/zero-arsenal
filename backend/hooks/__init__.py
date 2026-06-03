from .hook_manager import HookManager, HookEvent, HookDef, hook_manager
from . import builtin_hooks as _builtin_hooks  # 触发内置 Hook 自动注册

__all__ = ["HookManager", "HookEvent", "HookDef", "hook_manager"]
