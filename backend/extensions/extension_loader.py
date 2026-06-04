"""
用途: 三级扩展目录发现与加载
      ① 内置级 backend/extensions/
      ② 用户级 ~/.zero-arsenal/extensions/
      ③ 项目级 .zero-arsenal/extensions/（最高优先级）
用法: from backend.extensions.extension_loader import discover_extensions, load_all_extensions
环境变量: ZERO_ARSENAL_EXTENSIONS_OVERRIDE — 追加额外的扩展搜索路径（分号分隔）
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 搜索路径（优先级从低到高）────────────────────────────────────────────────
_BUILTIN_EXT_DIR = Path(__file__).parent          # backend/extensions/
_USER_EXT_DIR    = Path.home() / ".zero-arsenal" / "extensions"
_PROJECT_EXT_DIR = Path(".zero-arsenal") / "extensions"


def _get_search_paths() -> list[tuple[int, Path]]:
    """返回 [(priority, path)] 列表，priority 越高（数字大）覆盖优先级越高。"""
    paths: list[tuple[int, Path]] = [
        (0, _BUILTIN_EXT_DIR),
        (1, _USER_EXT_DIR),
        (2, _PROJECT_EXT_DIR),
    ]
    extra = os.getenv("ZERO_ARSENAL_EXTENSIONS_OVERRIDE", "")
    for idx, extra_path in enumerate(extra.split(";") if extra else []):
        p = Path(extra_path.strip())
        if p.exists():
            paths.append((10 + idx, p))
    return paths


@dataclass
class ExtensionBundle:
    """单个扩展的元数据（已选出最高优先级路径）。"""
    ext_id:    str
    path:      Path
    priority:  int
    manifest:  dict = field(default_factory=dict)


@dataclass
class LoadedExtension:
    """加载完成的扩展（所有可注册组件）。"""
    ext_id:          str
    path:            Path
    manifest:        dict          = field(default_factory=dict)
    world_plugin:    Any           = None    # WorldPlugin 实例
    tools:           list          = field(default_factory=list)   # list[ToolDef]
    agent_nodes:     list          = field(default_factory=list)   # list[AgentNode]
    hooks:           Any           = None    # ExtensionHooks 实例
    skills:          list[Path]    = field(default_factory=list)
    rules:           list[Path]    = field(default_factory=list)
    prompt_fragments: list[Path]   = field(default_factory=list)

    @property
    def key(self) -> str:
        """
        稳定扩展键（NEW-C8-08）。main.py 用 `getattr(_ext, "key", "")` 取键以
        标注 hook_id；此前 LoadedExtension 无 key 字段恒回退到模块名，导致
        loader 注册路径与 discover_and_register_hooks 的 hook_id 不一致、无法去重。
        统一返回 ext_id，使两条注册路径产生相同 id（ext.{ext_id}.{method}）从而互相覆盖去重。
        """
        return self.ext_id


def discover_extensions() -> dict[str, ExtensionBundle]:
    """
    扫描三级目录，按优先级选出每个扩展 id 的最终路径。
    只有含 manifest.json 的目录才被识别为扩展。
    返回 {extension_id: ExtensionBundle}。
    """
    registry: dict[str, list[tuple[int, Path, dict]]] = {}

    for priority, base_path in _get_search_paths():
        if not base_path.exists():
            continue
        for ext_dir in sorted(base_path.iterdir()):
            if not ext_dir.is_dir() or ext_dir.name.startswith("_"):
                continue
            manifest_path = ext_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[ExtLoader] 无法解析 {manifest_path}: {e}")
                continue
            ext_id = manifest.get("id") or ext_dir.name
            registry.setdefault(ext_id, []).append((priority, ext_dir, manifest))

    bundles: dict[str, ExtensionBundle] = {}
    for ext_id, candidates in registry.items():
        candidates.sort(key=lambda x: x[0])   # 优先级升序
        _, winner_path, winner_manifest = candidates[-1]  # 取最高优先级
        bundles[ext_id] = ExtensionBundle(
            ext_id=ext_id,
            path=winner_path,
            priority=candidates[-1][0],
            manifest=winner_manifest,
        )
        if len(candidates) > 1:
            shadower = candidates[-1][1]
            shadowed = [c[1] for c in candidates[:-1]]
            logger.info(
                f"[ExtLoader] '{ext_id}' 被 {shadower} 覆盖（低优先级: {shadowed}）"
            )

    logger.info(f"[ExtLoader] 发现 {len(bundles)} 个扩展: {list(bundles)}")
    return bundles


def _import_module_from_path(module_name: str, file_path: Path) -> Any:
    """从绝对路径动态导入 Python 模块。"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"无法加载 {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def load_extension(bundle: ExtensionBundle) -> LoadedExtension:
    """加载单个扩展包，返回所有可注册的组件。"""
    loaded = LoadedExtension(
        ext_id=bundle.ext_id,
        path=bundle.path,
        manifest=bundle.manifest,
    )
    base_mod = f"_za_ext_{bundle.ext_id}"

    # ── plugin.py → WorldPlugin ──────────────────────────────────────
    plugin_path = bundle.path / "plugin.py"
    if plugin_path.exists():
        try:
            module = _import_module_from_path(f"{base_mod}_plugin", plugin_path)
            loaded.world_plugin = getattr(module, "PLUGIN", None)
            if loaded.world_plugin is None:
                # 尝试自动实例化第一个 WorldPlugin 子类
                for name in dir(module):
                    obj = getattr(module, name)
                    if isinstance(obj, type) and name.endswith("Plugin"):
                        loaded.world_plugin = obj()
                        break
        except Exception as e:
            logger.warning(f"[ExtLoader] {bundle.ext_id}/plugin.py 加载失败: {e}")

    # ── tools.py → list[ToolDef] ─────────────────────────────────────
    tools_path = bundle.path / "tools.py"
    if tools_path.exists():
        try:
            module = _import_module_from_path(f"{base_mod}_tools", tools_path)
            loaded.tools = getattr(module, "TOOLS", [])
        except Exception as e:
            logger.warning(f"[ExtLoader] {bundle.ext_id}/tools.py 加载失败: {e}")

    # ── agents.py → list[AgentNode] ──────────────────────────────────
    agents_path = bundle.path / "agents.py"
    if agents_path.exists():
        try:
            module = _import_module_from_path(f"{base_mod}_agents", agents_path)
            loaded.agent_nodes = getattr(module, "AGENT_NODES", [])
        except Exception as e:
            logger.warning(f"[ExtLoader] {bundle.ext_id}/agents.py 加载失败: {e}")

    # ── hooks.py → ExtensionHooks 实例 ───────────────────────────────
    hooks_path = bundle.path / "hooks.py"
    if hooks_path.exists():
        try:
            module = _import_module_from_path(f"{base_mod}_hooks", hooks_path)
            loaded.hooks = getattr(module, "HOOKS", None)
            if loaded.hooks is None:
                # 自动查找实现了 Hook 方法的类实例
                for name in dir(module):
                    obj = getattr(module, name)
                    if isinstance(obj, type) and name.endswith("Hooks"):
                        loaded.hooks = obj()
                        break
        except Exception as e:
            logger.warning(f"[ExtLoader] {bundle.ext_id}/hooks.py 加载失败: {e}")

    # ── 文件资产 ──────────────────────────────────────────────────────
    for attr, subdir, pattern in [
        ("skills",           "skills",  "*.md"),
        ("rules",            "rules",   "*.md"),
        ("prompt_fragments", "prompts", "**/*.md"),
    ]:
        d = bundle.path / subdir
        if d.exists():
            setattr(loaded, attr, list(d.glob(pattern)))

    logger.debug(
        f"[ExtLoader] 加载 '{bundle.ext_id}': "
        f"plugin={'✓' if loaded.world_plugin else '✗'} "
        f"tools={len(loaded.tools)} "
        f"agents={len(loaded.agent_nodes)} "
        f"hooks={'✓' if loaded.hooks else '✗'} "
        f"skills={len(loaded.skills)} rules={len(loaded.rules)}"
    )
    return loaded


def load_all_extensions() -> list[LoadedExtension]:
    """
    扫描三级目录，加载全部扩展，返回 LoadedExtension 列表。
    调用方负责将 tools/agent_nodes/hooks 注册到对应 Registry。
    """
    bundles = discover_extensions()
    loaded_list: list[LoadedExtension] = []
    for bundle in bundles.values():
        loaded_list.append(load_extension(bundle))
    return loaded_list
