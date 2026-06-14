"""Small allow-list evaluator for skill/prompt condition expressions."""
from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from typing import Any


_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class ConditionError(ValueError):
    pass


def evaluate_condition_expr(condition: str, state: Mapping[str, Any]) -> bool:
    """Evaluate a tiny expression language over ``state``.

    Supported forms intentionally cover existing frontmatter conditions:
    ``state["key"]`` lookups, constants, ``and``/``or``/``not``, comparisons,
    and ``in`` / ``not in``. Attribute access and calls are rejected.
    """
    tree = ast.parse(condition, mode="eval")
    return bool(_eval(tree.body, state))


def _eval(node: ast.AST, state: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, state) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(bool(v) for v in values)
        if isinstance(node.op, ast.Or):
            return any(bool(v) for v in values)
        raise ConditionError("unsupported boolean operator")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_eval(node.operand, state))

    if isinstance(node, ast.Compare):
        left = _eval(node.left, state)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, state)
            if isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            else:
                fn = _COMPARE_OPS.get(type(op))
                if fn is None:
                    raise ConditionError("unsupported comparison")
                ok = fn(left, right)
            if not ok:
                return False
            left = right
        return True

    if isinstance(node, ast.Subscript):
        target = _eval(node.value, state)
        key = _eval(node.slice, state)
        if not isinstance(target, Mapping):
            raise ConditionError("subscript target must be a mapping")
        return target.get(key)

    if isinstance(node, ast.Name):
        if node.id == "state":
            return state
        raise ConditionError(f"unknown name: {node.id}")

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [_eval(e, state) for e in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, state) for e in node.elts)

    raise ConditionError(f"unsupported expression: {type(node).__name__}")
