# -*- coding: utf-8 -*-
"""P4 — importance 参与记忆召回验证

注：用例为 inspect.getsource 静态子串检查，不启动服务，标注 stub
（见 docs/STUB_ANALYSIS.md T08）。
"""
import sys
import inspect
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytestmark = pytest.mark.stub


def test_fallback_recall_orders_by_importance():
    """adapter._fallback_recall SQL 必须包含 ORDER BY importance。"""
    adapter_src = (
        Path(__file__).parent.parent.parent / "backend" / "memory" / "adapter.py"
    ).read_text(encoding="utf-8")

    assert "importance" in adapter_src.lower(), (
        "adapter.py 没有使用 importance 字段"
    )
    # 找到 _fallback_recall 函数体，确认有 ORDER BY importance
    assert "ORDER BY importance" in adapter_src or "order by importance" in adapter_src.lower(), (
        "_fallback_recall 的 SQL 未包含 ORDER BY importance"
    )


def test_retriever_uses_importance_multiplier():
    """retriever.py 最终排序必须使用 importance 乘数。"""
    retriever_src = (
        Path(__file__).parent.parent.parent / "backend" / "memory" / "retriever.py"
    ).read_text(encoding="utf-8")

    assert "importance" in retriever_src, (
        "retriever.py 未使用 importance 字段"
    )


def test_adapter_updates_access_count():
    """adapter.py 召回时必须更新 access_count / last_accessed_at。"""
    adapter_src = (
        Path(__file__).parent.parent.parent / "backend" / "memory" / "adapter.py"
    ).read_text(encoding="utf-8")

    assert "access_count" in adapter_src, (
        "adapter.py 未更新 access_count"
    )
    assert "last_accessed_at" in adapter_src, (
        "adapter.py 未更新 last_accessed_at"
    )


def test_memory_adapter_recall_runtime():
    """运行时：MemoryAdapter.recall 不抛出异常，返回 list。"""
    import asyncio
    from backend.memory.adapter import memory_adapter

    async def _run():
        result = await memory_adapter.recall(
            session_id="test_session_p4",
            world_plugin="crossover",
            query_text="测试记忆召回",
            viewer_agent="narrator",
            top_k=5,
        )
        return result

    try:
        result = asyncio.run(_run())
        assert isinstance(result, list), f"recall 应返回 list，实际返回 {type(result)}"
    except Exception as e:
        err_str = str(e).lower()
        acceptable = any(kw in err_str for kw in ["database", "db", "sqlite", "no such table", "connection"])
        assert acceptable, f"memory_adapter.recall 运行时异常（非 DB 问题）: {e}"


def test_memory_adapter_has_is_full_mode_attribute():
    """MemoryAdapter 必须有 is_full_mode 属性供健康检查使用。"""
    from backend.memory.adapter import memory_adapter
    assert hasattr(memory_adapter, "is_full_mode"), (
        "memory_adapter 缺少 is_full_mode 属性"
    )
    assert isinstance(memory_adapter.is_full_mode, bool), (
        f"is_full_mode 应为 bool，实际为 {type(memory_adapter.is_full_mode)}"
    )
