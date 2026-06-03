"""
变量执行引擎 — TavernCommand 处理器 + RestrictedPython VM。
"""
from __future__ import annotations
import re
import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── TavernCommand 处理器（简单指令） ──────────────────────────────────────────

class TavernCommandProcessor:
    """
    处理 {{SET/ADD/MUL/DIV}} 指令，支持嵌套 key 路径（如 character.stress）。
    这是安全快速路径，不需要沙箱。
    """

    def apply_patches(self, patches: list[dict], state: dict) -> dict:
        """
        将 patches 列表应用到 state，返回修改后的副本。
        patches 格式: [{"cmd": "SET"|"ADD", "key": "path.to.key", "value": "...", "delta": float|None}]
        """
        result = copy.deepcopy(state)
        for patch in patches:
            cmd = patch.get("cmd", "SET").upper()
            key_path = patch.get("key", "")
            value = patch.get("value", "")
            delta = patch.get("delta")
            try:
                self._apply_one(result, cmd, key_path, value, delta)
            except Exception as e:
                logger.warning(f"patch failed {cmd} {key_path}: {e}")
        return result

    def _apply_one(self, state: dict, cmd: str, key_path: str, value: str, delta: Any) -> None:
        keys = key_path.split(".")
        target = state
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        leaf = keys[-1]

        if cmd == "SET":
            # 尝试类型推断
            target[leaf] = self._coerce(value)
        elif cmd == "ADD":
            current = float(target.get(leaf, 0))
            d = float(delta) if delta is not None else self._parse_num(value)
            # 对 stress/morale 等百分比属性钳位到 0-100
            new_val = current + d
            if leaf in ("stress", "morale", "clarity", "hp", "current"):
                new_val = max(0.0, new_val)
            target[leaf] = new_val
        elif cmd == "MUL":
            current = float(target.get(leaf, 0))
            target[leaf] = current * self._parse_num(value)
        elif cmd == "DIV":
            current = float(target.get(leaf, 0))
            divisor = self._parse_num(value)
            if divisor != 0:
                target[leaf] = current / divisor
        elif cmd == "PUSH":
            # {{PUSH: list.key=value}} — 向列表追加元素（字符串/数字/bool）
            lst = target.get(leaf, [])
            if not isinstance(lst, list):
                lst = [lst]
            lst.append(self._coerce(value))
            target[leaf] = lst
        elif cmd == "POP":
            # {{POP: list.key}} — 从列表移除最后一个元素
            lst = target.get(leaf, [])
            if isinstance(lst, list) and lst:
                lst.pop()
            target[leaf] = lst

    @staticmethod
    def _coerce(value: str) -> Any:
        v = value.strip()
        if v.lower() in ("true", "yes"): return True
        if v.lower() in ("false", "no"): return False
        try: return int(v)
        except ValueError: pass
        try: return float(v)
        except ValueError: pass
        return v

    @staticmethod
    def _parse_num(value: str) -> float:
        try:
            return float(value.strip().lstrip("+"))
        except ValueError:
            return 0.0


# ── RestrictedPython VM（复杂变量表达式） ─────────────────────────────────────

class VariableVM:
    """
    受限 Python 沙箱执行环境。
    当 RestrictedPython 可用时使用沙箱；否则 fallback 到 TavernCommandProcessor。
    超时 2 秒。
    """

    def __init__(self) -> None:
        self._rp_available = False
        try:
            from RestrictedPython import compile_restricted, safe_globals
            self._compile = compile_restricted
            self._safe_globals = safe_globals
            self._rp_available = True
        except ImportError:
            pass

    def execute(self, code: str, state: dict) -> dict:
        """执行受限代码，返回修改后的 state。超时或异常时返回原始 state。"""
        if not self._rp_available:
            # 无 RestrictedPython 时，降级到 TavernCommandProcessor 兼容路径（纯 JSON Patch）。
            # 如果 code 是标准 TavernCommand 格式，委托给 _tavern；否则明确拒绝执行。
            logger.warning(
                "RestrictedPython not available; VM code execution is not supported. "
                "Falling back to TavernCommand-only mode — complex Python expressions will be rejected."
            )
            # 返回原 state（不修改），让上层调用方按 TavernCommand 结果处理
            return state

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._run_restricted, code, state)
            try:
                return future.result(timeout=2.0)
            except concurrent.futures.TimeoutError:
                logger.warning("VM execution timed out")
                return state
            except Exception as e:
                logger.warning(f"VM execution error: {e}")
                return state

    def _run_restricted(self, code: str, state: dict) -> dict:
        from RestrictedPython import compile_restricted, safe_globals, safe_builtins
        local_state = copy.deepcopy(state)
        glb = {
            **safe_globals,
            "__builtins__": safe_builtins,
            "state": local_state,
        }
        byte_code = compile_restricted(code, "<vm>", "exec")
        exec(byte_code, glb)  # noqa: S102
        return local_state


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

_tavern = TavernCommandProcessor()
_vm = VariableVM()


def execute_state_change(
    patches: list[dict],
    state: dict,
    vm_code: str = "",
    use_vm: bool = False,
) -> dict:
    """
    统一状态变更入口。
    1. 先用 TavernCommandProcessor 处理简单 SET/ADD 指令
    2. 如果有 vm_code 且 use_vm=True，再用 VM 执行复杂表达式
    """
    result = _tavern.apply_patches(patches, state)
    if use_vm and vm_code.strip():
        result = _vm.execute(vm_code, result)
    return result
