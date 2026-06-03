"""
Prompt Assembler — 提示词组装工具层。
用途: python engine/prompt_assembler.py --phase p3 --world crossover
MCP集成: 可包装为 MCP tool，函数签名见 assemble()
环境变量: NOVEL_DB — 数据库路径（可选）

实现两条路径：
  1. Registry 路径（默认）：基于 prompts/registry.py 的五层体系 + WorldPlugin 注入
  2. Jinja2 路径（可选）：当传入 template_str 时，用 Jinja2 渲染后附加到 Registry 结果尾部

Registry 路径是主路径；Jinja2 路径用于需要逻辑条件分支的特殊模板（如战斗序章）。

参考设计文档 05-prompt-architecture.md §3
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from jinja2 import Environment, StrictUndefined, TemplateError
    _HAS_JINJA2 = True
except ImportError:
    _HAS_JINJA2 = False
    logger.debug("[PromptAssembler] jinja2 not installed, template path unavailable")


def assemble(
    phase: str,
    session_id: str = "",
    state: dict[str, Any] | None = None,
    world_plugin: str = "crossover",
    template_str: str | None = None,
    template_vars: dict[str, Any] | None = None,
    skill_phase: str | None = None,
) -> str:
    """
    组装指定 phase 的完整系统提示词。

    Parameters
    ----------
    phase          : 目标相位（"all" / "p1" / "p2" / "p3" / "p4" / "dm" / ...）
    session_id     : 会话 ID，用于查询 runtime 层片段
    state          : 注入状态字典（world_plugin、mode 等），用于条件片段判断
    world_plugin   : 世界插件 key，触发插件的 apply_to_registry 注入
    template_str   : 可选 Jinja2 模板字符串；若提供则在 Registry 结果末尾追加渲染结果
    template_vars  : Jinja2 渲染上下文变量
    skill_phase    : 注入 Skill 块时使用的相位（None 则与 phase 相同）

    Returns
    -------
    str  完整系统提示词（UTF-8 字符串）
    """
    state = state or {}
    template_vars = template_vars or {}

    # ── 1. Registry 路径 ─────────────────────────────────────────────────────
    result = _build_from_registry(phase, session_id, state, world_plugin)

    # ── 2. Skill 注入（Layer 5）────────────────────────────────────────────────
    try:
        from ..tools.skill_loader import skill_registry
        skill_block = skill_registry.build_injection_block(
            phase=skill_phase or phase,
            state=state,
            world_plugin=world_plugin,
        )
        if skill_block:
            result = result + "\n\n" + skill_block
    except Exception as e:
        logger.debug(f"[PromptAssembler] skill injection skipped: {e}")

    # ── 3. 扩展规则注入（Track C）────────────────────────────────────────────
    try:
        from ..extensions.rules_loader import rule_registry
        rules_block = rule_registry.build_injection_block(phase)
        if rules_block:
            result = result + "\n\n" + rules_block
    except Exception as e:
        logger.debug(f"[PromptAssembler] rules injection skipped: {e}")

    # ── 4. Jinja2 路径（可选）─────────────────────────────────────────────────
    if template_str:
        result = result + "\n\n" + _render_jinja2(template_str, template_vars, state)

    return result.strip()


def assemble_with_data_stream(
    phase: str,
    user_content: str,
    session_id: str = "",
    state: dict[str, Any] | None = None,
    world_plugin: str = "crossover",
    template_str: str | None = None,
    template_vars: dict[str, Any] | None = None,
    ctx: Any | None = None,
) -> list[dict[str, str]]:
    """
    组装完整 messages，包含 Layer 4 BackendDataStream 注入。
    设计文档 05-prompt-architecture.md §4 + §6

    Layer 4 数据流（仅 dm/narrator 相位注入，其余相位不注入）：
      - 仅 agent 可见，玩家不可见
      - 作为 user 消息前缀，包裹在 <backend_data_stream> 标签内

    Args:
        ctx: TurnContext 实例（提供时自动提取 18 轴数据）
        其余参数同 assemble()
    """
    system = assemble(
        phase=phase,
        session_id=session_id,
        state=state,
        world_plugin=world_plugin,
        template_str=template_str,
        template_vars=template_vars,
    )

    # ── Layer 4 BackendDataStream（仅 dm / narrator / p3 相位）──────────────
    data_stream_block = ""
    if phase in ("dm", "p3", "narrator") and ctx is not None:
        try:
            from .runtime_data_stream import RuntimeDataStreamBuilder
            data_stream_block = RuntimeDataStreamBuilder.build(ctx)
        except Exception as e:
            logger.debug(f"[PromptAssembler] Layer 4 data stream skipped: {e}")

    # 用户消息：数据流前缀 + 实际用户输入
    final_user = (
        (data_stream_block + "\n\n" + user_content).strip()
        if data_stream_block
        else user_content
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": final_user},
    ]


def assemble_messages(
    phase: str,
    user_content: str,
    session_id: str = "",
    state: dict[str, Any] | None = None,
    world_plugin: str = "crossover",
    template_str: str | None = None,
    template_vars: dict[str, Any] | None = None,
    ctx: Any | None = None,
) -> list[dict[str, str]]:
    """
    返回 [{"role": "system", "content": ...}, {"role": "user", "content": ...}] 格式，
    直接传给 llm_complete() 的 messages 参数。

    当 ctx（TurnContext）提供时自动注入 Layer 4 BackendDataStream（仅 dm/p3 相位）。
    """
    return assemble_with_data_stream(
        phase=phase,
        user_content=user_content,
        session_id=session_id,
        state=state,
        world_plugin=world_plugin,
        template_str=template_str,
        template_vars=template_vars,
        ctx=ctx,
    )


# ── 内部实现 ─────────────────────────────────────────────────────────────────

def _build_from_registry(
    phase: str,
    session_id: str,
    state: dict[str, Any],
    world_plugin: str,
) -> str:
    """
    调用 PromptRegistry.build_system_prompt()，先让 WorldPlugin 注入其片段。
    失败时返回空字符串（调用方应提供 fallback）。
    """
    try:
        from ..prompts.registry import registry
        from ..extensions.plugin import plugin_registry as _plug_reg

        plugin = _plug_reg.get(world_plugin)
        if plugin:
            plugin.apply_to_registry(registry)

        return registry.build_system_prompt(
            phase=phase,
            session_id=session_id,
            state=state,
        )
    except Exception as e:
        logger.error(f"[PromptAssembler] registry build failed for phase={phase}: {e}")
        raise RuntimeError(f"PromptAssembler failed for phase={phase}") from e


def _render_jinja2(template_str: str, vars_: dict, state: dict) -> str:
    """
    渲染 Jinja2 模板。jinja2 未安装时降级为原字符串返回。
    """
    if not _HAS_JINJA2:
        logger.warning("[PromptAssembler] jinja2 not installed; returning raw template_str")
        return template_str

    try:
        env = Environment(undefined=StrictUndefined, autoescape=False)
        tmpl = env.from_string(template_str)
        return tmpl.render(**{**state, **vars_})
    except TemplateError as e:
        logger.warning(f"[PromptAssembler] jinja2 render failed: {e}")
        return template_str


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse, json, sys

    parser = argparse.ArgumentParser(description="Prompt Assembler CLI")
    parser.add_argument("--phase", default="p3", help="目标相位（p1/p3/dm/...）")
    parser.add_argument("--world", default="crossover", help="世界插件 key")
    parser.add_argument("--session", default="", help="会话 ID（用于 runtime 片段）")
    parser.add_argument("--state", default="{}", help="状态 JSON 字符串")
    parser.add_argument("--template", default=None, help="Jinja2 模板字符串")
    args = parser.parse_args()

    try:
        state = json.loads(args.state)
    except Exception:
        state = {}

    result = assemble(
        phase=args.phase,
        session_id=args.session,
        state=state,
        world_plugin=args.world,
        template_str=args.template,
    )
    print(json.dumps({"ok": True, "phase": args.phase, "length": len(result), "prompt": result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
