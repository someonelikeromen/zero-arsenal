"""
Jinja2 模板加载器 — 为各 Agent prompt 提供 .j2 文件渲染入口。
用途: python prompts/template_loader.py --template dm_gate --var char_summary="林峰"
用法: from prompts.template_loader import render_prompt
环境变量: PROMPT_TEMPLATES_DIR — 覆盖默认模板目录
MCP集成: 可包装为 MCP tool，函数签名见 render_prompt()

参考设计文档 05-prompt-architecture.md §3（Jinja2 路径）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认模板目录
_DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_template_dir() -> Path:
    override = os.getenv("PROMPT_TEMPLATES_DIR", "")
    return Path(override) if override else _DEFAULT_TEMPLATE_DIR


def render_prompt(
    template_name: str,
    variables: dict[str, Any] | None = None,
    strict: bool = False,
) -> str:
    """
    加载并渲染指定 Jinja2 模板（.j2 文件）。

    Parameters
    ----------
    template_name : 模板名，不含 .j2 后缀（如 "dm_gate"、"world"、"narrator_p3"）
    variables     : 模板变量字典
    strict        : True 时使用 StrictUndefined（未定义变量报错），默认 False（空字符串代替）

    Returns
    -------
    渲染后的字符串；若 jinja2 未安装或文件不存在则返回空字符串并记录警告。
    """
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined
    except ImportError:
        logger.warning(
            "[TemplateLoader] jinja2 未安装，无法渲染模板。"
            "请运行 `pip install jinja2` 启用。"
        )
        return ""

    template_dir = _get_template_dir()
    j2_path = template_dir / f"{template_name}.j2"

    if not j2_path.exists():
        logger.warning(f"[TemplateLoader] 模板文件不存在: {j2_path}")
        return ""

    try:
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined if strict else Undefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        template = env.get_template(f"{template_name}.j2")
        return template.render(**(variables or {}))
    except Exception as e:
        logger.warning(f"[TemplateLoader] 模板渲染失败 ({template_name}): {e}")
        return ""


def list_templates() -> list[str]:
    """返回可用模板名列表（不含 .j2 后缀）。"""
    template_dir = _get_template_dir()
    if not template_dir.exists():
        return []
    return [p.stem for p in sorted(template_dir.glob("*.j2"))]


def load_agent_prompts() -> int:
    """
    扫描 prompts/agents/*.md 并将 frontmatter 声明的片段注册到 PromptRegistry。
    返回成功注册的数量。（P4 修复）

    Markdown frontmatter 格式（YAML 头部）：
      ---
      id: agent.dm_gate
      layer: agent
      phase: dm
      priority: 100
      ---
    """
    agents_dir = Path(__file__).parent / "agents"
    if not agents_dir.exists():
        return 0

    try:
        from .registry import registry, PromptFragment
    except ImportError:
        logger.warning("[TemplateLoader] PromptRegistry import failed")
        return 0

    count = 0
    for md_file in sorted(agents_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            # 解析 YAML frontmatter
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    fm_text = parts[1].strip()
                    content = parts[2].strip()
                    # 简单 YAML 解析（只处理 key: value 格式）
                    fm: dict = {}
                    for line in fm_text.splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            fm[k.strip()] = v.strip()
                    frag_id = fm.get("id", md_file.stem)
                    phase_raw = fm.get("phase", "all")
                    phase = [p.strip() for p in phase_raw.split(",")]
                    priority = int(fm.get("priority", 100))
                    layer = fm.get("layer", "agent")
                    registry.register(PromptFragment(
                        id=frag_id,
                        layer=layer,
                        phase=phase,
                        priority=priority,
                        content=content,
                    ))
                    count += 1
                    logger.debug("[TemplateLoader] agent prompt registered: %s", frag_id)
        except Exception as e:
            logger.warning("[TemplateLoader] Failed to load %s: %s", md_file.name, e)

    logger.info("[TemplateLoader] %d agent prompts loaded from agents/*.md", count)
    return count


def load_prompt_fragment_file(md_path: "Path | str") -> "PromptFragment | None":
    """
    从单个 .md 文件（YAML frontmatter + 正文）加载并返回 PromptFragment。
    供扩展系统 E6 批量注册扩展 prompt_fragments 使用。
    返回 None 表示解析失败或文件格式不符合要求。
    """
    from pathlib import Path as _Path
    try:
        from .registry import PromptFragment
    except ImportError:
        return None

    path = _Path(md_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        fm_text, content = parts[1].strip(), parts[2].strip()
        fm: dict = {}
        for line in fm_text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip("\"'")
        frag_id = fm.get("id", path.stem)
        phase_raw = fm.get("phase", "all")
        phase = [p.strip() for p in phase_raw.split(",")]
        agent_filter_raw = fm.get("agent_filter", "")
        agent_filter = [a.strip() for a in agent_filter_raw.split(",") if a.strip()] if agent_filter_raw else []
        return PromptFragment(
            id=frag_id,
            layer=fm.get("layer", "world"),
            phase=phase,
            priority=int(fm.get("priority", 200)),
            content=content,
            inject_as=fm.get("inject_as", "system"),
            condition=fm.get("condition") or None,
            trigger=fm.get("trigger", "always"),
            agent_filter=agent_filter,
        )
    except Exception as e:
        logger.warning("[TemplateLoader] load_prompt_fragment_file failed for %s: %s", md_path, e)
        return None


def main(template: str, variables: dict | None = None, strict: bool = False) -> dict:
    """CLI / MCP 入口。"""
    result = render_prompt(template, variables, strict)
    available = list_templates()
    return {
        "ok": bool(result),
        "template": template,
        "rendered": result,
        "available_templates": available,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="渲染 Jinja2 .j2 prompt 模板")
    parser.add_argument("--template", required=True, help="模板名（不含 .j2 后缀）")
    parser.add_argument("--vars", default="{}", help="模板变量（JSON 字符串）")
    parser.add_argument("--strict", action="store_true", help="严格模式（未定义变量报错）")
    parser.add_argument("--list", action="store_true", help="列出所有可用模板")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(list_templates(), ensure_ascii=False, indent=2))
    else:
        try:
            variables = json.loads(args.vars)
        except json.JSONDecodeError:
            variables = {}
        result = main(args.template, variables, args.strict)
        print(json.dumps(result, ensure_ascii=False, indent=2))
