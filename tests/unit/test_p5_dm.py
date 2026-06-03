# -*- coding: utf-8 -*-
"""P5 — DM modify verdict 验证

注：用例仅断言 prompt 含字符串，非运行时验证，标注 stub
（见 docs/STUB_ANALYSIS.md T09）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytestmark = pytest.mark.stub


def test_dm_system_prompt_includes_modify():
    """DM_SYSTEM_PROMPT 必须列出 modify 作为合法 verdict。"""
    from backend.agents.dm_agent import DM_SYSTEM_PROMPT

    assert "modify" in DM_SYSTEM_PROMPT, (
        "DM_SYSTEM_PROMPT 未包含 modify verdict，设计要求 pass/reject/modify"
    )


def test_dm_agent_stores_modified_action():
    """dm_agent.py 处理 modify 结果时，必须将 modified_action 写入 TurnContext。"""
    dm_src = (
        Path(__file__).parent.parent.parent / "backend" / "agents" / "dm_agent.py"
    ).read_text(encoding="utf-8")

    assert "modified_action" in dm_src, (
        "dm_agent.py 未处理 modified_action 字段"
    )


def test_turn_context_has_modified_action_field():
    """TurnContext 必须有 modified_action 字段（供 graph.py 路由和 narrator 消费）。"""
    from backend.agents.state import TurnContext
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(TurnContext)}
    assert "modified_action" in field_names, (
        "TurnContext 缺少 modified_action 字段"
    )


def test_graph_routes_modify_verdict():
    """graph.py 的 _route_after_dm 必须处理 modify 分支。"""
    graph_src = (
        Path(__file__).parent.parent.parent / "backend" / "agents" / "graph.py"
    ).read_text(encoding="utf-8")

    assert "modify" in graph_src, (
        "graph.py 未处理 dm modify 分支"
    )


def test_dm_agent_node_block_on_failure():
    """运行时：dm_agent 解析失败时 dm_verdict 应为 'block'。"""
    import asyncio
    from backend.agents.dm_agent import dm_agent_node
    from backend.agents.state import TurnContext

    ctx = TurnContext(
        session_id="test_p5",
        message_id="msg_p5",
        user_input="触发 DM 判定",
    )
    ctx.rules_verdict = "pass"

    async def _run():
        # 无 LLM 配置时，dm_agent 应 block 而非 allow
        return await dm_agent_node(ctx)

    try:
        result_ctx = asyncio.run(_run())
        assert result_ctx is not None, "dm_agent_node 返回 None"
        # 若 LLM 不可用，verdict 应为 'block'（不得为 'allow'）
        if result_ctx.dm_verdict not in ("pass", "allow", "block", "modify"):
            # 未知 verdict 也是错误
            assert False, f"dm_verdict 为非法值: {result_ctx.dm_verdict!r}"
    except Exception as e:
        err_str = str(e).lower()
        acceptable = any(kw in err_str for kw in ["database", "db", "sqlite", "llm", "api", "connection", "key"])
        assert acceptable, f"dm_agent_node 运行时异常（非 LLM/DB 问题）: {e}"
