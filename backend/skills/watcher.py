"""
用途: 开发模式扩展热加载监视器（04-extension-system.md §1.1 可热加载原则）
      监视三级扩展目录中的 .py / .md 文件变更，
      自动重新加载对应扩展模块并刷新 Tool/Hook/Agent 注册表。
用法: 在 main.py lifespan 中调用 start_extension_watcher()（开发模式下自动激活）
环境变量:
  ZERO_ARSENAL_HOT_RELOAD   — 强制启用热加载（"1" 或 "true"）
  ZERO_ARSENAL_NO_HOT_RELOAD — 强制禁用热加载（"1"）
  ZERO_ARSENAL_EXTENSIONS_OVERRIDE — 额外扩展搜索路径（分号分隔）
依赖: watchfiles（可选，缺失时静默跳过热加载）
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# 监视的文件扩展名（.py = 代码，.md = 规则/技能）
_WATCH_SUFFIXES = {".py", ".md"}

# 不触发重载的路径片段（缓存目录等）
_IGNORE_PATTERNS = {"__pycache__", ".git", "node_modules"}


def _should_watch() -> bool:
    """根据环境变量和 DEBUG 模式决定是否启用热加载。"""
    if os.getenv("ZERO_ARSENAL_NO_HOT_RELOAD", "").lower() in ("1", "true"):
        return False
    if os.getenv("ZERO_ARSENAL_HOT_RELOAD", "").lower() in ("1", "true"):
        return True
    # 默认：DEBUG 环境（reload=True 或 ENVIRONMENT!=production）下启用
    env = os.getenv("ENVIRONMENT", "development").lower()
    return env not in ("production", "prod")


def _get_watch_paths() -> list[Path]:
    """返回需要监视的扩展目录（与 extension_loader._get_search_paths 对齐）。"""
    builtin_dir = Path(__file__).parent.parent / "extensions"
    user_dir = Path.home() / ".zero-arsenal" / "extensions"
    project_dir = Path(".zero-arsenal") / "extensions"

    paths: list[Path] = [p for p in [builtin_dir, user_dir, project_dir] if p.exists()]

    extra = os.getenv("ZERO_ARSENAL_EXTENSIONS_OVERRIDE", "")
    for p_str in (extra.split(";") if extra else []):
        p = Path(p_str.strip())
        if p.exists():
            paths.append(p)

    return paths


def _ext_id_from_path(changed_path: Path, watch_paths: list[Path]) -> str | None:
    """从变更文件路径推断扩展 id（子目录名）。"""
    for watch_root in watch_paths:
        try:
            rel = changed_path.relative_to(watch_root)
            parts = rel.parts
            if parts:
                return parts[0]  # 第一级子目录即扩展 id
        except ValueError:
            continue
    return None


async def _reload_extension(ext_id: str) -> None:
    """
    重载指定扩展的全部 Python 模块，并刷新注册表。
    只重载已在 sys.modules 中缓存的模块（避免重新注入新的副作用）。
    """
    prefix = f"_za_ext_{ext_id}_"
    reloaded: list[str] = []

    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(prefix):
            try:
                importlib.reload(sys.modules[mod_name])
                reloaded.append(mod_name)
            except Exception as e:
                logger.warning(f"[Watcher] 重载模块 {mod_name} 失败: {e}")

    if not reloaded:
        logger.debug(f"[Watcher] 扩展 '{ext_id}' 尚未加载，跳过重载")
        return

    logger.info(f"[Watcher] 已重载扩展 '{ext_id}' 模块: {reloaded}")

    # 刷新 Tool / Hook / Agent / PromptFragment 注册表（NEW-C12-05：此前仅刷 Tool）
    try:
        from ..extensions.extension_loader import discover_extensions, load_extension
        from ..tools.registry import ToolRegistry
        bundles = discover_extensions()
        if ext_id not in bundles:
            return
        loaded = load_extension(bundles[ext_id])

        # ① 工具
        if loaded.tools:
            registry = ToolRegistry.get_instance()
            for tool_def in loaded.tools:
                registry.register(tool_def)
            logger.info(f"[Watcher] 扩展 '{ext_id}' 工具已刷新: {[t.name for t in loaded.tools]}")

        # ② Hook（register_extension_hooks 按 ext.{key}.{method} 覆盖去重，幂等）
        if loaded.hooks:
            try:
                from ..hooks import hook_manager
                ext_key = getattr(loaded, "key", "") or ext_id
                n = hook_manager.register_extension_hooks(loaded.hooks, ext_key=str(ext_key))
                logger.info(f"[Watcher] 扩展 '{ext_id}' Hook 已刷新: {n} 个")
            except Exception as e:
                logger.warning(f"[Watcher] 扩展 '{ext_id}' Hook 刷新失败: {e}")

        # ③ Agent 节点
        if loaded.agent_nodes:
            try:
                from ..agents.agent_node import register_node as _register_agent_node
                for node in loaded.agent_nodes:
                    _register_agent_node(node)
                logger.info(f"[Watcher] 扩展 '{ext_id}' Agent 节点已刷新: {len(loaded.agent_nodes)} 个")
            except Exception as e:
                logger.warning(f"[Watcher] 扩展 '{ext_id}' Agent 刷新失败: {e}")

        # ④ PromptFragment（.md 规则/技能变更后重新注入）
        if loaded.prompt_fragments:
            try:
                from ..prompts.template_loader import load_prompt_fragment_file
                from ..prompts.registry import registry as _pr
                for frag_path in loaded.prompt_fragments:
                    frag = load_prompt_fragment_file(frag_path)
                    if frag:
                        _pr.register(frag)
                logger.info(f"[Watcher] 扩展 '{ext_id}' PromptFragment 已刷新: {len(loaded.prompt_fragments)} 个")
            except Exception as e:
                logger.warning(f"[Watcher] 扩展 '{ext_id}' PromptFragment 刷新失败: {e}")
    except Exception as e:
        logger.warning(f"[Watcher] 扩展 '{ext_id}' 注册表刷新失败: {e}")


async def _watch_loop(
    watch_paths: list[Path],
    on_change: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """watchfiles 异步监视循环（仅在 watchfiles 已安装时运行）。"""
    try:
        from watchfiles import awatch, Change
    except ImportError:
        logger.info("[Watcher] watchfiles 未安装，扩展热加载已禁用。"
                    "可运行 `pip install watchfiles` 启用。")
        return

    logger.info(f"[Watcher] 开始监视扩展目录（{len(watch_paths)} 个路径）: "
                f"{[str(p) for p in watch_paths]}")

    try:
        async for changes in awatch(*watch_paths, stop_event=None):
            for change_type, changed_str in changes:
                changed = Path(changed_str)

                # 忽略缓存和无关文件
                if any(ign in changed.parts for ign in _IGNORE_PATTERNS):
                    continue
                if changed.suffix not in _WATCH_SUFFIXES:
                    continue

                ext_id = _ext_id_from_path(changed, watch_paths)
                if not ext_id:
                    continue

                action = {
                    Change.added:    "新增",
                    Change.modified: "修改",
                    Change.deleted:  "删除",
                }.get(change_type, "变更")

                logger.info(f"[Watcher] 检测到 {action}: {changed.name} "
                            f"(扩展: {ext_id})")

                if change_type != Change.deleted:
                    callback = on_change or _reload_extension
                    try:
                        await callback(ext_id)
                    except Exception as e:
                        logger.error(f"[Watcher] 热加载回调失败: {e}")

    except asyncio.CancelledError:
        logger.info("[Watcher] 监视任务已取消")
    except Exception as e:
        logger.error(f"[Watcher] 监视循环异常退出: {e}", exc_info=True)


_watcher_task: asyncio.Task | None = None


async def start_extension_watcher(
    on_change: Callable[[str], Awaitable[None]] | None = None,
) -> asyncio.Task | None:
    """
    启动扩展热加载监视任务（asyncio 后台 Task）。
    - 生产环境（ENVIRONMENT=production）自动跳过。
    - 返回 Task 引用，可在 lifespan shutdown 时调用 task.cancel() 停止。
    - on_change 可注入自定义回调（默认为 _reload_extension）。

    典型用法（main.py lifespan）：
        watcher_task = await start_extension_watcher()
        yield
        if watcher_task:
            watcher_task.cancel()
    """
    global _watcher_task

    if not _should_watch():
        logger.debug("[Watcher] 热加载已禁用（生产模式）")
        return None

    watch_paths = _get_watch_paths()
    if not watch_paths:
        logger.debug("[Watcher] 没有可监视的扩展目录")
        return None

    _watcher_task = asyncio.create_task(
        _watch_loop(watch_paths, on_change),
        name="extension-hot-reload-watcher",
    )
    return _watcher_task


async def stop_extension_watcher() -> None:
    """停止监视任务（lifespan shutdown 调用）。"""
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
        try:
            await _watcher_task
        except asyncio.CancelledError:
            pass
    _watcher_task = None
