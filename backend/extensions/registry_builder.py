"""
ExtensionRegistry Builder — 自动扫描并生成 __registry__.json。
设计文档 04-extension-system.md §1.3

在服务启动时（main.py lifespan）调用 build_registry()，
扫描三级目录并生成/更新 extensions/__registry__.json。

扫描逻辑统一委托给 extension_loader.discover_extensions()，
消除双轨漂移：loader 和 registry_builder 使用相同的发现逻辑
（以 manifest.json 为扩展标识符，三级优先级覆盖）。

优先级（高 → 低）：
  ③ project-level   .zero-arsenal/extensions/
  ② user-level      ~/.zero-arsenal/extensions/
  ① builtin-level   backend/extensions/
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_registry(builtin_dir: Optional[Path] = None) -> dict:
    """
    委托 extension_loader.discover_extensions() 发现扩展，
    构建并返回注册表 dict，同时写入 builtin_dir/__registry__.json。
    统一发现逻辑，避免 registry_builder 与 extension_loader 双轨漂移。
    """
    if builtin_dir is None:
        builtin_dir = Path(__file__).parent

    # 统一使用 extension_loader 的发现逻辑（manifest.json 为标识符）
    from .extension_loader import discover_extensions
    bundles = discover_extensions()

    # 将 ExtensionBundle 转为注册表 meta 格式
    extensions_list = []
    for ext_id, bundle in bundles.items():
        ext_dir = bundle.path
        tier_name = {0: "builtin", 1: "user", 2: "project"}.get(bundle.priority, "external")
        meta: dict = {
            "key":         ext_id,
            "path":        str(ext_dir),
            "priority":    bundle.priority,
            "tier":        tier_name,
            "has_plugin":  (ext_dir / "plugin.py").exists(),
            "has_agents":  (ext_dir / "agents.py").exists(),
            "has_tools":   (ext_dir / "tools.py").exists(),
            "has_skills":  (ext_dir / "skills").exists(),
            "has_prompts": (ext_dir / "prompts").exists(),
        }
        # manifest 元数据
        manifest = bundle.manifest
        if manifest.get("display_name"):
            meta["display_name"] = manifest["display_name"]
        if manifest.get("description"):
            meta["description"] = manifest["description"]
        if manifest.get("version"):
            meta["version"] = manifest["version"]
        extensions_list.append(meta)

    result = {
        "version": "1.0",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "extensions": extensions_list,
    }

    # 写入 __registry__.json
    registry_file = builtin_dir / "__registry__.json"
    try:
        registry_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"[ExtRegistry] generated {registry_file} ({len(extensions_list)} extensions)")
    except Exception as e:
        logger.warning(f"[ExtRegistry] write failed: {e}")

    return result


def load_registry(builtin_dir: Optional[Path] = None) -> dict:
    """读取已生成的 __registry__.json，不存在时自动生成。"""
    if builtin_dir is None:
        builtin_dir = Path(__file__).parent
    registry_file = builtin_dir / "__registry__.json"
    if registry_file.exists():
        try:
            return json.loads(registry_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return build_registry(builtin_dir)


# ── 兼容旧调用方的目录扫描函数（已废弃，仅保留签名供外部引用，不实际扫描）──────
def _scan_extension_dir(ext_dir: "Path", priority: int) -> list:
    """已废弃：目录扫描逻辑已统一至 extension_loader.discover_extensions()。"""
    return []
