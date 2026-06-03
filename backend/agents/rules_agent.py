"""
RulesAgent — 管线入口，规则校验 + 骰子预触发。
职责：
1. 解析玩家行动意图
2. 检查是否违反世界插件硬性规则（如果有）
3. 若需要骰子判定，先 roll 骰（结果不可再修改）
4. 输出 rules_verdict: pass | block
"""
from __future__ import annotations
import uuid
import json
import logging
from datetime import datetime
from .state import TurnContext
from .llm import llm_complete, load_agent_config
from ..bus import bus
from ..db.schema import PartType

logger = logging.getLogger(__name__)


RULES_SYSTEM = """\
你是跑团规则校验器，判断玩家行动是否违反世界硬性规则。
返回JSON（无代码块包裹）：
{"verdict": "pass"|"block"|"hard_block"|"needs_check", "reason": "", "rejection_narrative": "", "notes": [], "check_attr": "", "check_reason": ""}
- pass       : 行动在规则范围内，允许继续
- block      : 行动违反规则，需要 DM 进一步解释后拒绝（柔性拒绝）
- hard_block : 行动从物理/世界逻辑上不可能发生（如穿越实心墙、不死之身），
               立即终止，无需 DM 处理。必须填写 rejection_narrative（≤50字，叙事语气说明"为什么不行"）
- needs_check: 行动需要属性检定才能决定是否允许（高风险行动）
  - check_attr：需要检定的属性名（如 strength/dexterity/intelligence）
  - check_reason：为何需要检定（10字以内）
- reason             : 简短说明（不超过30字）
- rejection_narrative: 仅 hard_block 填写，直接呈现给玩家的叙事拒绝语句
- notes              : 可选的额外校验注记列表
"""

# 需要骰子门禁的关键词（rules_agent 遇到这些词时倾向于返回 needs_check）
_NEEDS_CHECK_HINTS = (
    "强行", "突破", "翻墙", "闯入", "逃脱", "潜入", "偷", "劫",
    "解锁", "破解", "操控", "说服", "威胁", "欺骗", "伪装",
    "挑战", "单打", "死战", "硬扛",
)


def _build_rules_messages(ctx: TurnContext) -> list[dict]:
    """
    构建 rules 阶段消息列表。
    系统提示 = registry Layer 0+1（core+agent.rules）+ 世界规则 Skill + Layer 5 runtime。
    """
    # 从 PromptRegistry 构建完整系统提示（包含 HARD-GATE + agent.rules fragment）
    system_content = RULES_SYSTEM  # 备用 fallback
    try:
        from ..prompts.registry import registry as _pr
        from ..extensions.plugin import plugin_registry as _plug_reg

        # 世界插件提示片段注入 world 层
        plugin = _plug_reg.get(ctx.world_plugin)
        if plugin:
            plugin.apply_to_registry(_pr)

        built = _pr.build_system_prompt(
            phase="rules",
            session_id=ctx.session_id,
            state={"world_plugin": ctx.world_plugin, "mode": ctx.mode},
        )
        if built.strip():
            system_content = built
    except Exception:
        pass

    # 注入世界专属规则 Skill（Layer 5）
    try:
        from ..tools.skill_loader import skill_registry
        state_snapshot = {"world_plugin": ctx.world_plugin, "mode": ctx.mode}
        skill_block = skill_registry.build_injection_block(
            phase="rules", state=state_snapshot, world_plugin=ctx.world_plugin
        )
        if skill_block:
            system_content += "\n\n" + skill_block
    except Exception:
        pass

    # 注入世界插件的规则 Skill 文件内容
    try:
        from ..extensions.plugin import plugin_registry as _plug_reg2
        plugin2 = _plug_reg2.get(ctx.world_plugin)
        if plugin2:
            world_rules = plugin2.get_rules_skills()
            if world_rules:
                system_content += "\n\n[世界专属规则]\n" + "\n".join(world_rules)
    except Exception:
        pass

    # 注入扩展规则（Track C RuleRegistry）
    try:
        from ..extensions.rules_loader import rule_registry as _rule_reg
        rules_block = _rule_reg.build_injection_block("rules")
        if rules_block:
            system_content += "\n\n" + rules_block
    except Exception:
        pass

    # 检测高风险关键词，给 LLM 提示
    input_lower = (ctx.user_input or "").lower()
    risky_hint = ""
    if any(kw in input_lower for kw in _NEEDS_CHECK_HINTS):
        risky_hint = "\n[系统提示：检测到高风险行动关键词，若确实存在不确定性请考虑返回 needs_check]"

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": (
            f"世界插件：{ctx.world_plugin}\n"
            f"玩家行动：{ctx.user_input}"
            f"{risky_hint}"
        )},
    ]


async def rules_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — 规则校验门禁。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "rules"):
        return await _rules_agent_impl(ctx)
    return ctx  # never reached but keeps type checker happy


async def _rules_agent_impl(ctx: TurnContext) -> TurnContext:
    cfg = load_agent_config("rules")

    # ── 优先尝试 tool_loop 路径（查技能触发 + 世界规则后再裁决） ────────────
    result_text: str | None = None
    try:
        from .tool_loop import run_tool_loop, ToolContext as TCtx
        from ..bus import bus as _bus
        tc = TCtx(
            session_id=ctx.session_id,
            message_id=ctx.message_id,
            agent_name="rules",
            profile_name=ctx.mode,
            bus=_bus,
        )
        rules_tools = ["check_skill_trigger", "query_world_rules", "read_character"]
        user_content = (
            f"世界插件：{ctx.world_plugin}\n"
            f"玩家行动：{ctx.user_input}\n"
            "请先用工具查询技能触发和世界规则，再给出裁决 JSON。"
        )
        result_text, _ = await run_tool_loop(
            messages=[{"role": "user", "content": user_content}],
            system_prompt=_build_rules_messages(ctx)[0]["content"],
            tools=rules_tools,
            agent_config=cfg,
            ctx=tc,
            max_iterations=3,
        )
    except Exception as e:
        logger.debug(f"[rules_agent] tool_loop failed, fallback to direct: {e}")
        result_text = None

    # ── 若 tool_loop 失败或返回空，回落到单次 llm_complete ──────────────────
    if not result_text:
        try:
            result_text = await llm_complete(
                messages=_build_rules_messages(ctx),
                provider=cfg.get("provider", "deepseek"),
                model=cfg.get("model", "deepseek-chat"),
                temperature=cfg.get("temperature", 0.2),
                max_tokens=cfg.get("max_tokens", 256),
            )
        except Exception as e:
            logger.warning(f"[rules_agent] llm_complete also failed: {e}")
            result_text = '{"verdict":"block","reason":"LLM不可用，安全拦截"}'

    try:
        raw = (result_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        # 从 tool_loop 结果中提取最终 JSON（末尾出现的 {...}）
        import re as _re
        json_match = _re.search(r'\{[^{}]*"verdict"[^{}]*\}', raw)
        if json_match:
            raw = json_match.group(0)

        result = json.loads(raw)
        # NEW-C1-01 fail-closed：verdict 缺失或不在白名单内一律视为 block
        _RULES_VERDICTS = {"pass", "block", "hard_block", "needs_check"}
        verdict = result.get("verdict")
        if verdict not in _RULES_VERDICTS:
            logger.warning(
                "[rules_agent] verdict 缺失/未知值 %r，fail-closed 视为 block", verdict
            )
            verdict = "block"

        # needs_check：先 roll 骰，再决定最终裁决
        if verdict == "needs_check":
            ctx.rules_verdict, ctx.rules_reason, ctx.rules_notes = await _pre_roll_check(
                ctx=ctx,
                attr=result.get("check_attr", "intelligence"),
                reason=result.get("check_reason", "行动检定"),
                original_reason=result.get("reason", ""),
            )
        elif verdict == "hard_block":
            # hard_block：立即终止，发出叙事拒绝 Part，不经过 DM
            ctx.rules_verdict = "hard_block"
            ctx.rules_reason = result.get("reason", "行动违反世界物理规则")
            ctx.rules_notes = result.get("notes", [])
            await _emit_rejection_narrative(ctx, result.get("rejection_narrative", ctx.rules_reason))
        else:
            ctx.rules_verdict = verdict
            ctx.rules_reason = result.get("reason", "")
            ctx.rules_notes = result.get("notes", [])
    except Exception as e:
        # 安全策略：解析失败默认拦截，防止绕过规则门禁
        logger.warning(f"[rules_agent] parse error, defaulting to block: {e}")
        ctx.rules_verdict = "block"
        ctx.rules_reason = f"规则校验结果解析失败，已安全拦截: {e}"
        ctx.rules_notes = []

    # 发 dm_note Part（plan/review 模式，或 verdict=block 时；hard_block 已在上面单独处理）
    note_content = ctx.rules_reason or ("行动通过规则校验" if ctx.rules_verdict == "pass" else "行动被规则拦截")
    if ctx.rules_verdict in ("block",) or ctx.mode in ("plan", "review"):
        part_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        content = {
            "note": f"[规则校验] {note_content}",
            "verdict": ctx.rules_verdict,
            "notes": ctx.rules_notes,
        }
        try:
            await _write_part(ctx, part_id, PartType.DM_NOTE, content, now)
            await bus.publish_part_created(
                ctx.session_id, part_id, PartType.DM_NOTE, ctx.message_id, "rules"
            )
            await bus.publish_part_done(ctx.session_id, part_id, content)
        except Exception as e:
            logger.warning(f"[rules_agent] failed to write part: {e}")

    return ctx


async def _pre_roll_check(
    ctx: TurnContext,
    attr: str,
    reason: str,
    original_reason: str,
) -> tuple[str, str, list]:
    """
    rules_agent 的「先 roll 骰门禁」：
    - 用角色卡数据对 attr 属性做 d10 检定（难度 1）
    - 成功 → verdict=pass（交给 DM 继续处理）
    - 失败 → verdict=block（行动直接被规则拦截）
    将骰子结果存入 ctx.rules_roll（供前端展示）。
    """
    from ..engine.dice import compute_roll_request, RollRequest, log_roll
    from ..db import get_db

    # 读取角色数据
    char_data: dict = {}
    try:
        async with get_db() as db:
            row = await (await db.execute(
                "SELECT data_json FROM character_cards WHERE session_id=? LIMIT 1",
                (ctx.session_id,),
            )).fetchone()
        if row:
            import json as _j
            char_data = _j.loads(row["data_json"])
    except Exception:
        pass

    roll_threshold = 8
    roll_pool = 3 if not char_data else None

    # 触发 on_roll_check Hook（可让外部修改 DC/目标值）
    try:
        from ..hooks import hook_manager, HookEvent
        hook_ctx = {
            "session_id": ctx.session_id,
            "attribute": attr,
            "reason": reason,
            "threshold": roll_threshold,
            "pool": roll_pool,
        }
        hook_ctx = await hook_manager.fire(HookEvent.on_roll_check, hook_ctx)
        roll_threshold = int(hook_ctx.get("threshold", roll_threshold))
        roll_pool = hook_ctx.get("pool", roll_pool)
    except Exception:
        pass

    req = RollRequest(
        attribute=attr,
        character_data=char_data if char_data else None,
        pool=roll_pool,
        threshold=roll_threshold,
        reason=f"[规则门禁] {reason}",
        session_id=ctx.session_id,
    )
    roll_result = compute_roll_request(req)

    # 记录到 DB
    try:
        await log_roll(roll_result, ctx.session_id, ctx.message_id)
    except Exception:
        pass

    # 保存骰子结果到 ctx，供后续节点（narrator）使用
    ctx.rules_roll = roll_result.model_dump() if hasattr(roll_result, "model_dump") else dict(roll_result)

    # 发布骰子结果 Part 到前端
    try:
        part_id_roll = str(uuid.uuid4())
        roll_content = {
            "note": f"[规则检定] {reason}：{roll_result.verdict}（净{roll_result.net}）",
            "rolls": roll_result.rolls,
            "net": roll_result.net,
            "verdict": roll_result.verdict,
            "attribute": attr,
        }
        now_ts = datetime.now().timestamp()
        await _write_part(ctx, part_id_roll, PartType.DM_NOTE, roll_content, now_ts)
        await bus.publish_part_created(
            ctx.session_id, part_id_roll, PartType.DM_NOTE, ctx.message_id, "rules"
        )
        await bus.publish_part_done(ctx.session_id, part_id_roll, roll_content)
    except Exception as e:
        logger.warning(f"[rules_agent] pre_roll publish failed: {e}")

    # 根据骰子结果决定裁决
    if roll_result.net > 0 or roll_result.verdict in ("success", "critical"):
        return (
            "pass",
            f"规则检定通过（{attr} {roll_result.verdict}，净{roll_result.net}）。{original_reason}",
            [f"检定骰池：{roll_result.pool}d10，成功数：{roll_result.net}"],
        )
    else:
        return (
            "block",
            f"规则检定失败（{attr} {roll_result.verdict}，净{roll_result.net}）。{original_reason or '行动条件不满足'}",
            [f"检定骰池：{roll_result.pool}d10，成功数：{roll_result.net}"],
        )


async def _emit_rejection_narrative(ctx: TurnContext, narrative: str) -> None:
    """
    向前端发出一个拒绝叙事 Part（hard_block 专用）。
    使用 narrative 类型，让玩家以叙事语气看到拒绝原因。
    """
    if not (ctx.session_id and ctx.message_id):
        return
    part_id = str(uuid.uuid4())
    now = datetime.now().timestamp()
    content = {"text": narrative}
    try:
        await _write_part(ctx, part_id, PartType.NARRATIVE, content, now)
        await bus.publish_part_created(
            ctx.session_id, part_id, PartType.NARRATIVE, ctx.message_id, "rules"
        )
        await bus.publish_part_done(ctx.session_id, part_id, content)
    except Exception as e:
        logger.warning(f"[rules_agent] _emit_rejection_narrative failed: {e}")


async def _write_part(ctx: TurnContext, part_id: str, part_type: str, content: dict, now: float) -> None:
    from ..db import get_db
    async with get_db() as db:
        await db.execute(
            "INSERT INTO message_parts "
            "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'done', 'rules', ?, ?)",
            (part_id, ctx.message_id, ctx.session_id,
             part_type, json.dumps(content, ensure_ascii=False), now, now)
        )
        await db.commit()
