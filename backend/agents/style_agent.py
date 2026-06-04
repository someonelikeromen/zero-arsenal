"""
StyleAgent — 对 NarratorAgent 的正文进行文风润色和纯净度检查。
遵循 12-anti-llm-cliche-and-purity.mdc 规则。
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


STYLE_SYSTEM = """\
你是跑团文风纯净度审查员。你必须：
1. 扫描正文中的LLM俗套表达（禁词：月光倾泻/深吸一口气/心跳加速/微微一怔/眼眸/嘴角/不禁/不由得/彼时/仿佛/似乎/一丝/浑身一震/后背发凉/不知为何/莫名其妙等）
2. 对轻度违规给出 purity_score（0.6~1.0）和最多2条 warnings，不修改正文
3. 只对重度违规（purity_score < 0.5）提供润色版本，否则 polished="" 表示原文可用
返回JSON（无代码块包裹）：{"purity_score": 0.9, "warnings": [...], "polished": "润色版或空字符串"}
"""

# ── 程序化禁词表（分级，无需 LLM 即可触发警告）────────────────────────────────

# 严重俗套（每个 -0.15）
_CLICHE_HEAVY = (
    "月光倾泻", "深吸一口气", "心跳加速", "浑身一震", "后背发凉",
    "热泪盈眶", "泪水夺眶", "心如刀割", "血脉贲张", "热血沸腾",
    "灵魂颤抖", "全身僵住", "双腿发软", "头皮发麻",
)

# 轻度俗套（每个 -0.05）
_CLICHE_LIGHT = (
    "微微一怔", "不禁", "不由得", "仿佛", "似乎", "一丝", "眼眸",
    "嘴角", "彼时", "莫名其妙", "不知为何", "不由自主", "下意识",
    "本能地", "情不自禁", "心中一动", "心头一紧", "脑海中",
    "如同", "恍若", "宛如", "好似",
)

# 主观心理分析排比（短语模式，出现 ≥2 次 -0.1）
_PSYCHO_PATTERNS = (
    "他知道", "她知道", "他明白", "她明白",
    "他感到", "她感到", "他意识到", "她意识到",
)


def _program_purity_scan(text: str) -> tuple[float, list[str]]:
    """
    程序化禁词扫描，无需 LLM。
    返回 (score, warnings)，score 越低越差。
    """
    score = 1.0
    warnings: list[str] = []

    heavy_hits = [w for w in _CLICHE_HEAVY if w in text]
    light_hits = [w for w in _CLICHE_LIGHT if w in text]
    psycho_hits = [p for p in _PSYCHO_PATTERNS if text.count(p) >= 2]

    if heavy_hits:
        penalty = min(len(heavy_hits) * 0.15, 0.6)
        score -= penalty
        warnings.append(f"严重俗套表达：{'、'.join(heavy_hits[:3])}")

    if light_hits:
        penalty = min(len(light_hits) * 0.05, 0.3)
        score -= penalty
        if len(light_hits) > 3:
            warnings.append(f"轻度俗套堆积（{len(light_hits)}处）：{'、'.join(light_hits[:4])}")
        elif light_hits:
            warnings.append(f"轻度俗套：{'、'.join(light_hits)}")

    if psycho_hits:
        score -= 0.1
        warnings.append(f"主观心理分析排比：{'、'.join(psycho_hits[:2])}")

    return max(0.0, round(score, 2)), warnings


async def style_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — 文风润色与纯净度检查。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "style"):
        return await _style_impl(ctx)
    return ctx


async def _style_impl(ctx: TurnContext) -> TurnContext:
    narrative_text = ctx.narrative_text or ""

    # 文本过短，直接透传
    if len(narrative_text) < 50:
        return ctx

    # ── 程序化预扫描（速度快，零成本）──────────────────────────────────────────
    pre_score, pre_warnings = _program_purity_scan(narrative_text)

    # 预扫描分数已很差时（<0.4）直接触发重度润色，不再浪费 LLM
    if pre_score < 0.4:
        ctx.purity_score = pre_score
        ctx.style_warnings = pre_warnings
        # 仍然调用 LLM 生成润色版（但跳过分析阶段，只要求输出润色正文）
        try:
            cfg = load_agent_config("style")
            polish_msg = [
                {"role": "system", "content": "你是文风润色师。用简洁有力的白描笔法重写以下正文，去除所有俗套表达，保持情节不变。直接输出润色后的正文，不加任何说明。"},
                {"role": "user", "content": narrative_text},
            ]
            polished = await llm_complete(
                messages=polish_msg,
                provider=cfg.get("provider", "deepseek"),
                model=cfg.get("model", "deepseek-chat"),
                temperature=0.4,
                max_tokens=cfg.get("max_tokens", 1024),
            )
            ctx.polished_narrative = polished.strip()
            if ctx.polished_narrative:
                ctx.narrative_text = ctx.polished_narrative
                await _replace_narrative_in_db(ctx)
        except Exception as e:
            logger.warning(f"[style_agent] polish fallback failed: {e}")
        await _fire_after_style_applied(ctx)
        return ctx

    cfg = load_agent_config("style")

    # 从 PromptRegistry 构建 style 系统提示（Layer 0 + agent.style）
    style_system = STYLE_SYSTEM
    try:
        from ..prompts.registry import registry as _pr
        from ..prompts.token_budget import system_prompt_budget as _spb
        built = _pr.build_system_prompt(
            phase="style",
            session_id=ctx.session_id,
            state={"world_plugin": ctx.world_plugin, "mode": ctx.mode},
            token_budget=_spb("style", ctx.mode),
        )
        if built.strip():
            style_system = built
    except Exception:
        pass

    try:
        messages = [
            {"role": "system", "content": style_system},
            {"role": "user", "content": f"请审查以下正文：\n\n{narrative_text}"},
        ]
        raw = await llm_complete(
            messages=messages,
            provider=cfg.get("provider", "deepseek"),
            model=cfg.get("model", "deepseek-chat"),
            temperature=cfg.get("temperature", 0.1),
            max_tokens=cfg.get("max_tokens", 1024),
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

        result = json.loads(raw)
        llm_score = float(result.get("purity_score", 1.0))
        llm_warnings = result.get("warnings", [])
        # 合并程序化扫描与 LLM 分析结果（取较低分，合并警告）
        ctx.purity_score = min(llm_score, pre_score) if pre_score < 1.0 else llm_score
        ctx.style_warnings = list(dict.fromkeys(pre_warnings + llm_warnings))  # 去重保序
        ctx.polished_narrative = result.get("polished", "")
    except Exception as e:
        logger.warning(f"[style_agent] parse error, skipping: {e}")
        # def_c2：LLM 解析失败时此前直接 return，丢弃了程序化预扫描结果。
        # 改为持久化 pre_score/pre_warnings，保证文风分数不因 LLM 异常而归零失踪。
        ctx.purity_score = pre_score
        ctx.style_warnings = pre_warnings
        await _fire_after_style_applied(ctx)
        return ctx

    # ── 重度违规（<0.5）：用润色版替换正文 ────────────────────────────────────────
    if ctx.polished_narrative and ctx.purity_score < 0.5:
        ctx.narrative_text = ctx.polished_narrative
        await _replace_narrative_in_db(ctx)

    # ── 中度违规（0.5~0.7）：最多 2 轮段落级重写 ─────────────────────────────────
    elif 0.5 <= ctx.purity_score < 0.7:
        ctx.narrative_text = await _paragraph_rewrite(ctx, ctx.narrative_text, cfg, max_rounds=2)

    # ── 非 play 模式：向前端发 dm_note 审查报告 ─────────────────────────────────
    if ctx.mode != "play" and (ctx.style_warnings or ctx.purity_score < 0.9):
        part_id = str(uuid.uuid4())
        now = datetime.now().timestamp()
        content = {
            "note": f"[文风审查] 纯净度 {ctx.purity_score:.2f}",
            "purity_score": ctx.purity_score,
            "warnings": ctx.style_warnings,
            "polished_applied": bool(ctx.polished_narrative and ctx.purity_score < 0.5),
        }
        try:
            await _write_part(ctx, part_id, PartType.DM_NOTE, content, now)
            await bus.publish_part_done(ctx.session_id, part_id, content)
        except Exception as e:
            logger.warning(f"[style_agent] failed to write part: {e}")

    await _fire_after_style_applied(ctx)
    return ctx


async def _fire_after_style_applied(ctx: TurnContext) -> None:
    """conf_b04：触发 after_style_applied（扩展可读取最终文风分数/正文）。"""
    try:
        from ..hooks import hook_manager, HookEvent
        await hook_manager.fire(HookEvent.after_style_applied, {
            "session_id": ctx.session_id,
            "agent_name": "style",
            "purity_score": getattr(ctx, "purity_score", None),
            "warnings": getattr(ctx, "style_warnings", []),
            "narrative_text": ctx.narrative_text,
        })
    except Exception as _e:
        logger.debug("[style_agent] after_style_applied hook failed: %s", _e)


async def _paragraph_rewrite(
    ctx: TurnContext,
    text: str,
    cfg: dict,
    max_rounds: int = 2,
) -> str:
    """
    对中度违规（0.5 ≤ purity < 0.7）正文做最多 max_rounds 轮段落级重写。
    每轮只找并重写含俗套词的段落，而非全文替换，降低过度改写风险。
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    changed = False

    for _round in range(max_rounds):
        new_paragraphs: list[str] = []
        round_changed = False
        for para in paragraphs:
            if not any(w in para for w in _CLICHE_HEAVY + _CLICHE_LIGHT):
                new_paragraphs.append(para)
                continue
            try:
                rewritten = await llm_complete(
                    messages=[
                        {"role": "system", "content": (
                            "你是文风润色师。将以下段落中的俗套表达替换为简洁白描，"
                            "保持情节内容不变，直接输出重写后的段落，不加说明。"
                        )},
                        {"role": "user", "content": para},
                    ],
                    provider=cfg.get("provider", "deepseek"),
                    model=cfg.get("model", "deepseek-chat"),
                    temperature=0.3,
                    max_tokens=min(len(para) * 2, 512),
                )
                rewritten = rewritten.strip()
                if rewritten and len(rewritten) > 20:
                    new_paragraphs.append(rewritten)
                    round_changed = True
                else:
                    new_paragraphs.append(para)
            except Exception:
                new_paragraphs.append(para)
        paragraphs = new_paragraphs
        if round_changed:
            changed = True
        else:
            break  # 本轮无变化，提前退出

    if changed:
        result = "\n\n".join(paragraphs)
        ctx.polished_narrative = result
        ctx.narrative_text = result
        await _replace_narrative_in_db(ctx)
        return result
    return text


async def _replace_narrative_in_db(ctx: TurnContext) -> None:
    """将润色版正文写回 DB 本回合的 narrative Part（message_id 精确定位），并通知前端。"""
    try:
        from ..db import get_db
        async with get_db() as db:
            # 优先按 message_id 精确定位本回合的 narrative part，避免跨回合污染
            part = await (await db.execute(
                "SELECT id FROM message_parts WHERE session_id=? AND message_id=? AND type=? "
                "ORDER BY created_at DESC LIMIT 1",
                (ctx.session_id, ctx.message_id, PartType.NARRATIVE)
            )).fetchone()
            # 降级：若 message_id 未匹配（旧数据），回退到 session 最近一条
            if not part:
                part = await (await db.execute(
                    "SELECT id FROM message_parts WHERE session_id=? AND type=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (ctx.session_id, PartType.NARRATIVE)
                )).fetchone()
            if part:
                now_ts = datetime.now().timestamp()
                polished_content = json.dumps(
                    {"text": ctx.polished_narrative}, ensure_ascii=False
                )
                await db.execute(
                    "UPDATE message_parts SET content=?, updated_at=? WHERE id=?",
                    (polished_content, now_ts, part["id"])
                )
                await db.commit()
                await bus.publish_part_done(
                    ctx.session_id,
                    part["id"],
                    {"text": ctx.polished_narrative, "_polished": True},
                )
    except Exception as e:
        logger.warning(f"[style_agent] polished replace failed: {e}")


async def _write_part(ctx: TurnContext, part_id: str, part_type: str, content: dict, now: float) -> None:
    from ..db import get_db
    async with get_db() as db:
        await db.execute(
            "INSERT INTO message_parts "
            "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'done', 'style', ?, ?)",
            (part_id, ctx.message_id, ctx.session_id,
             part_type, json.dumps(content, ensure_ascii=False), now, now)
        )
        await db.commit()
