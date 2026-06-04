# -*- coding: utf-8 -*-
"""P2 — main.py lifespan 接入 extension_loader 验证"""
import sys
import inspect
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.stub
def test_load_all_extensions_imported_in_main():
    """main.py 必须 import load_all_extensions。（静态源码子串检查 · stub）"""
    main_src = (Path(__file__).parent.parent.parent / "backend" / "main.py").read_text(encoding="utf-8")
    assert "load_all_extensions" in main_src, (
        "main.py 没有引用 load_all_extensions"
    )


@pytest.mark.stub
def test_load_all_extensions_called_in_lifespan():
    """main.py lifespan 函数必须调用 load_all_extensions()。"""
    import backend.main as m

    src = inspect.getsource(m.lifespan)
    assert "load_all_extensions" in src, (
        "lifespan() 未调用 load_all_extensions()，扩展加载链路空转"
    )


def test_extension_loader_discover_returns_dict():
    """discover_extensions() 应返回 dict，包含内置三个扩展。"""
    from backend.extensions.extension_loader import discover_extensions

    result = discover_extensions()
    assert isinstance(result, dict), f"discover_extensions 返回非 dict：{type(result)}"
    # 内置三个扩展应被发现
    for ext_id in ("crossover", "wuxia", "infinite_arsenal"):
        assert ext_id in result, f"内置扩展 '{ext_id}' 未被发现，当前：{list(result.keys())}"


def test_load_all_extensions_returns_loaded_bundles():
    """load_all_extensions() 应返回至少 1 个 LoadedExtension。"""
    from backend.extensions.extension_loader import load_all_extensions

    bundles = load_all_extensions()
    assert len(bundles) >= 1, "load_all_extensions 返回空列表"
