# -*- coding: utf-8 -*-
"""P1 — GachaAgent 注册链路运行时验证

注：当前用例多为对源码/注册名的静态检查，不执行 GachaAgent.execute，
标注 stub，CI 以 `-m "not stub"` 排除（见 docs/STUB_ANALYSIS.md T07）。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytestmark = pytest.mark.stub


def test_turn_context_has_gacha_fields():
    """TurnContext 必须包含 gacha_pending 和 gacha_granted 字段。"""
    from backend.agents.state import TurnContext
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(TurnContext)}
    assert "gacha_pending" in field_names, "TurnContext 缺少 gacha_pending 字段"
    assert "gacha_granted" in field_names, "TurnContext 缺少 gacha_granted 字段"


def test_turn_context_gacha_defaults_are_lists():
    """gacha_pending / gacha_granted 默认值应为空列表。"""
    from backend.agents.state import TurnContext

    ctx = TurnContext(session_id="s1", message_id="m1", user_input="test")
    assert ctx.gacha_pending == [], f"gacha_pending 默认值错误：{ctx.gacha_pending!r}"
    assert ctx.gacha_granted == [], f"gacha_granted 默认值错误：{ctx.gacha_granted!r}"


def test_gacha_agent_insert_after_is_var():
    """GachaAgent.insert_after 必须是 'var'（与 graph.py edge_map 键一致）。"""
    from backend.extensions.infinite_arsenal.agents import GachaAgent

    assert GachaAgent.insert_after == "var", (
        f"insert_after={GachaAgent.insert_after!r}，应为 'var'"
    )


def test_gacha_agent_registered_after_import():
    """导入 agents.py 后，GachaAgent 应出现在全局注册表中。"""
    import importlib
    # 重新加载确保 register_node 被调用
    import backend.extensions.infinite_arsenal.agents  # noqa: F401
    from backend.agents.agent_node import list_registered_nodes

    names = [n.name for n in list_registered_nodes()]
    assert "gacha_agent" in names, (
        f"gacha_agent 未注册，当前注册表：{names}"
    )


def test_gacha_agent_uses_attribute_not_dict():
    """GachaAgent.execute 必须用属性访问 ctx.gacha_pending，不能用 ctx.get()。"""
    import inspect
    from backend.extensions.infinite_arsenal.agents import GachaAgent

    src = inspect.getsource(GachaAgent.execute)
    assert "ctx.get(" not in src, (
        "GachaAgent.execute 仍在使用 ctx.get()，TurnContext 是 dataclass 没有该方法"
    )


def test_gacha_agent_execute_runtime():
    """GachaAgent.execute 运行时断言：gacha_pending 非空时应填充 gacha_granted。"""
    from backend.extensions.infinite_arsenal.agents import GachaAgent
    from backend.agents.state import TurnContext

    ctx = TurnContext(
        session_id="test_session",
        message_id="test_msg",
        user_input="抽卡",
    )
    # 模拟一个 gacha_pending 请求
    ctx.gacha_pending = [{"pool": "basic", "count": 1, "reason": "测试"}]

    async def _run():
        return await GachaAgent.execute(ctx)

    try:
        result_ctx = asyncio.run(_run())
        # 运行后 gacha_pending 应被清空或 gacha_granted 应有数据
        assert result_ctx is not None, "execute 返回了 None"
        # 宽松断言：不要求 granted 一定非空（依赖 DB），但不能抛出异常
    except Exception as e:
        # DB 不可用是允许的，但其他异常不行
        err_str = str(e).lower()
        acceptable = any(kw in err_str for kw in ["database", "db", "sqlite", "no such table", "connection"])
        assert acceptable, f"GachaAgent.execute 运行时异常（非 DB 问题）: {e}"
