# -*- coding: utf-8 -*-
"""P3 — PartType 新常量 + tool_loop 验证"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_parttype_has_new_constants():
    """PartType 必须包含 reasoning / tool_call / tool_result / var_diff。"""
    from backend.db.schema import PartType

    required = {
        "REASONING":    "reasoning",
        "TOOL_CALL":    "tool_call",
        "TOOL_RESULT":  "tool_result",
        "VAR_DIFF":     "var_diff",
    }
    for attr, value in required.items():
        assert hasattr(PartType, attr), f"PartType 缺少属性 {attr}"
        assert getattr(PartType, attr) == value, (
            f"PartType.{attr} = {getattr(PartType, attr)!r}，期望 {value!r}"
        )


@pytest.mark.stub
def test_tool_loop_emits_bus_events():
    """tool_loop.py 必须引入 bus 并在工具执行前后 emit Part 事件。（静态源码子串检查 · stub）"""
    tool_loop_src = (
        Path(__file__).parent.parent.parent / "backend" / "agents" / "tool_loop.py"
    ).read_text(encoding="utf-8")

    assert "bus" in tool_loop_src, "tool_loop.py 未引入 bus"
    assert "tool_call" in tool_loop_src, "tool_loop.py 未 emit tool_call 类型 Part"


def test_play_yaml_has_tool_call_type():
    """play.yaml visible_part_types 应包含 tool_call（前端才能收到）。"""
    import yaml
    play_yaml = (
        Path(__file__).parent.parent.parent
        / "backend" / "agents" / "profiles" / "play.yaml"
    )
    assert play_yaml.exists(), f"play.yaml 不存在：{play_yaml}"

    data = yaml.safe_load(play_yaml.read_text(encoding="utf-8"))
    visible = data.get("visible_part_types", [])
    assert "tool_call" in visible, (
        f"play.yaml visible_part_types 缺少 tool_call，当前：{visible}"
    )
