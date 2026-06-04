"""
DM Agent (阈门) — 行动合法性验证。
职责：
  1. 判断玩家行动是否违反规则（物理/叙事一致性）
  2. 决定是否需要骰子判定，以及使用哪个属性
  3. 注入 dm_note Part（仅在 plan/review 模式可见）

tool_loop 增强：DM 可在裁决前多轮调用工具（read_character / get_world_state /
search_memory）查询世界状态，最终仍输出同一 JSON 格式。
失败时自动 fallback 到单次 llm_complete。
"""
from __future__ import annotations
import logging
import uuid
import json
from datetime import datetime
from .state import TurnContext
from .llm import llm_complete, load_agent_config
from ..bus import bus, BusEvent, EventType
from ..db.schema import PartType

logger = logging.getLogger(__name__)


# 内联 fallback prompt（当 .j2 模板加载失败时使用）
DM_SYSTEM_PROMPT = """\
你是一个跑团式小说系统的规则裁判（DM）。你的职责是评估玩家输入的行动合法性。

输出格式（严格 JSON，无 markdown 代码块）：
{
  "verdict": "pass" | "reject" | "modify" | "needs_roll",
  "dm_note": "简短的裁判说明（1-2句）",
  "modified_action": "修改后的行动描述（仅 verdict=modify 时填写，否则为 null）",
  "roll": {
    "attribute": "strength|dexterity|stamina|intelligence|spirit|charisma|composure",
    "skill": "技能名或null",
    "modifier": 0,
    "threshold": 8,
    "reason": "判定原因"
  } | null
}

规则：
- verdict=pass：行动明显可行，无需骰子（等同旧版 allow）
- verdict=needs_roll：需要能力检定
- verdict=reject：行动逻辑不可能或严重违规（等同旧版 block）
- verdict=modify：行动合法但需调整细节，modified_action 填写 DM 改写后的行动
- roll 仅在 needs_roll 时非 null
- modified_action 仅在 modify 时非 null
- dm_note 简洁，不超过 50 字
"""


def _render_dm_template(char_summary: str = "", skill_block: str = "", world_notes: str = "") -> str:
    """
    从 prompts/templates/dm_gate.j2 渲染 DM 系统 prompt（05-prompt-architecture.md §3 Jinja2 路径）。
    渲染失败时回退到内联 DM_SYSTEM_PROMPT。
    """
    try:
        from ..prompts.template_loader import render_prompt
        rendered = render_prompt(
            "dm_gate",
            variables={
                "char_summary": char_summary,
                "skill_block": skill_block,
                "world_notes": world_notes,
            },
        )
        if rendered.strip():
            return rendered
    except Exception:
        pass
    return DM_SYSTEM_PROMPT

def _build_dm_messages(ctx: TurnContext) -> list[dict]:
    char_summary = ""
    if ctx.character_data:
        name = ctx.character_data.get("identity", ctx.character_data).get("name", "未命名")
        attrs = ctx.character_data.get("attributes", {})
        attr_str = " ".join(f"{k[:3].upper()}:{v.get('base',1)}" for k, v in list(attrs.items())[:4])
        char_summary = f"角色：{name} | {attr_str}"

    # 注入 trigger=always / auto 的 dm 相位 Skill（Layer 5）
    skill_block = ""
    try:
        from ..tools.skill_loader import skill_registry
        state_snapshot = {"world_plugin": ctx.world_plugin, "mode": ctx.mode}
        skill_block = skill_registry.build_injection_block(
            phase="dm", state=state_snapshot, world_plugin=ctx.world_plugin
        )
    except Exception:
        pass

    # 从 registry 构建系统提示（Layer 0 HARD-GATE + agent.dm_gate + world 片段）
    # 优先 registry → Jinja2 模板 → 内联 fallback（05-prompt-architecture.md §3）
    system_content = _render_dm_template(
        char_summary=char_summary,
        skill_block=skill_block,
    )
    try:
        from ..prompts.registry import registry as _pr
        from ..extensions.plugin import plugin_registry as _plug_reg
        plugin = _plug_reg.get(ctx.world_plugin)
        if plugin:
            plugin.apply_to_registry(_pr)
        from ..prompts.token_budget import system_prompt_budget as _spb
        built = _pr.build_system_prompt(
            phase="dm",
            session_id=ctx.session_id,
            state={"world_plugin": ctx.world_plugin, "mode": ctx.mode},
            token_budget=_spb("dm", ctx.mode),
        )
        if built.strip():
            system_content = built
    except Exception:
        pass

    if skill_block and skill_block not in system_content:
        system_content += "\n\n" + skill_block

    # 注入扩展规则（Track C RuleRegistry）
    try:
        from ..extensions.rules_loader import rule_registry as _rule_reg
        rules_block = _rule_reg.build_injection_block("dm")
        if rules_block:
            system_content += "\n\n" + rules_block
    except Exception:
        pass

    # ── Layer 4: BackendDataStream（18 轴 DM 参考层）──────────────────────────
    data_stream_block = ""
    try:
        from ..engine.runtime_data_stream import RuntimeDataStreamBuilder
        data_stream_block = RuntimeDataStreamBuilder.build(ctx)
    except Exception:
        pass

    user_content_parts = [
        f"世界插件：{ctx.world_plugin}",
        char_summary,
        data_stream_block,
        f"玩家行动：{ctx.user_input}",
    ]
    user_content = "\n".join(p for p in user_content_parts if p.strip())

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


async def dm_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — DM 阈门验证（支持 tool_loop 多轮工具调用）。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "dm"):
        return await _dm_impl(ctx)
    return ctx


async def _dm_impl(ctx: TurnContext) -> TurnContext:
    cfg = load_agent_config("dm")

    # ------------------------------------------------------------------ #
    # 第一步：尝试 tool_loop 路径（DM 可先查世界/角色信息再裁决）
    # ------------------------------------------------------------------ #
    result_text: str | None = None
    try:
        from .tool_loop import run_tool_loop, ToolContext as TCtx
        from ..bus import bus as _bus

        tc = TCtx(
            session_id=ctx.session_id,
            message_id=ctx.message_id,
            agent_name="dm",
            profile_name=ctx.mode,
            bus=_bus,
        )
        dm_tools = ["read_character", "get_world_state", "search_memory"]

        char_summary = ""
        if ctx.character_data:
            name = ctx.character_data.get("identity", ctx.character_data).get("name", "未命名")
            attrs = ctx.character_data.get("attributes", {})
            attr_str = " ".join(
                f"{k[:3].upper()}:{v.get('base', 1)}"
                for k, v in list(attrs.items())[:4]
            )
            char_summary = f"角色：{name} | {attr_str}\n"

        user_content = (
            f"世界插件：{ctx.world_plugin}\n"
            f"{char_summary}"
            f"玩家行动：{ctx.user_input}"
        )

        # 用 PromptRegistry 拼好的完整系统提示（含世界规则/插件 Skill）
        dm_sys_prompt = DM_SYSTEM_PROMPT  # fallback
        try:
            dm_sys_prompt = _build_dm_messages(ctx)[0]["content"] or DM_SYSTEM_PROMPT
        except Exception:
            pass

        result_text, _ = await run_tool_loop(
            messages=[{"role": "user", "content": user_content}],
            system_prompt=dm_sys_prompt,
            tools=dm_tools,
            agent_config=cfg,
            ctx=tc,
            max_iterations=3,   # DM 只需少量循环
        )
    except Exception as e:
        logger.debug(f"[dm_agent] tool_loop failed, falling back to direct llm_complete: {e}")
        result_text = None

    # ------------------------------------------------------------------ #
    # 第二步：tool_loop 失败或返回空时，fallback 到原有单次 llm_complete
    # ------------------------------------------------------------------ #
    if not result_text:
        try:
            result_text = await llm_complete(
                messages=_build_dm_messages(ctx),
                provider=cfg.get("provider", "deepseek"),
                model=cfg.get("model", "deepseek-chat"),
                temperature=cfg.get("temperature", 0.3),
                max_tokens=cfg.get("max_tokens", 512),
                response_format={"type": "json_object"},
            )
        except Exception as e:
            # 安全策略：LLM 调用失败时拦截，防止绕过 DM 门禁
            ctx.dm_verdict = "block"
            ctx.dm_note = f"[DM llm error, blocked for safety: {e}]"
            logger.warning("[dm_agent] LLM 调用失败，安全拦截: %s", e)
            return ctx

    # ------------------------------------------------------------------ #
    # 第三步：解析 JSON 裁决结果（与原逻辑完全一致）
    # ------------------------------------------------------------------ #
    try:
        raw = result_text.strip()
        # 去除各种代码块包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        # 找到第一个 { 开始解析（防止 LLM 在 JSON 前加注释）
        brace_idx = raw.find("{")
        if brace_idx > 0:
            raw = raw[brace_idx:]

        # 截取第一个完整 JSON 对象（防止 LLM 在 JSON 后追加说明）
        depth = 0
        end_idx = -1
        for ci, ch in enumerate(raw):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = ci + 1
                    break
        if end_idx > 0:
            raw = raw[:end_idx]
        result = json.loads(raw)
        raw_verdict = result.get("verdict")
        # 兼容旧版 allow/block 和新版 pass/reject/modify
        _verdict_map = {"allow": "pass", "block": "reject"}
        mapped_verdict = _verdict_map.get(raw_verdict, raw_verdict)
        # NEW-C1-01 fail-closed：verdict 缺失或不在白名单内一律视为 reject
        _DM_VERDICTS = {"pass", "reject", "modify", "needs_roll"}
        if mapped_verdict not in _DM_VERDICTS:
            logger.warning(
                "[dm_agent] verdict 缺失/未知值 %r，fail-closed 视为 reject", raw_verdict
            )
            mapped_verdict = "reject"
        ctx.dm_verdict = mapped_verdict
        ctx.dm_note = result.get("dm_note", "")

        # modify：DM 改写行动，写入 ctx.modified_action
        if ctx.dm_verdict == "modify":
            ctx.modified_action = result.get("modified_action") or ctx.user_input

        roll_data = result.get("roll")
        if ctx.dm_verdict == "needs_roll" and roll_data:
            ctx.roll_request = {
                "attribute": roll_data.get("attribute", "dexterity"),
                "skill":     roll_data.get("skill"),
                "modifier":  roll_data.get("modifier", 0),
                "threshold": roll_data.get("threshold", 8),
                "reason":    roll_data.get("reason", ctx.user_input),
                "character_data": ctx.character_data or None,
                "session_id":     ctx.session_id,
                "message_id":     ctx.message_id,
            }
    except Exception as e:
        # DM 失败时安全拦截，防止在无 DM 裁决的情况下执行高风险行动
        ctx.dm_verdict = "block"
        ctx.dm_note = f"[DM parse error, blocked for safety: {e}]"

    # 发布 dm_note Part（plan/review 模式下可见；前端 _isVisible 会过滤 play 模式）
    if ctx.dm_note:
        part_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        content = {"note": ctx.dm_note, "verdict": ctx.dm_verdict}
        await _write_part(ctx, part_id, PartType.DM_NOTE, content, now)
        await bus.publish_part_created(
            ctx.session_id, part_id, PartType.DM_NOTE, ctx.message_id, "dm"
        )
        await bus.publish_part_done(ctx.session_id, part_id, content)

    return ctx


async def _write_part(ctx: TurnContext, part_id: str, part_type: str, content: dict, now: float) -> None:
    from ..db import get_db
    async with get_db() as db:
        await db.execute(
            "INSERT INTO message_parts (id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'done', 'dm', ?, ?)",
            (part_id, ctx.message_id, ctx.session_id,
             part_type, json.dumps(content, ensure_ascii=False), now, now)
        )
        await db.commit()
