"""
NPC Agent — 计算主要 NPC 在本轮的反应和行为。
在 DM 通过后、Narrator 之前执行，为叙事提供 NPC 决策素材，
并向前端发布 npc_action Parts（play 模式可见）。

重构后：每个 NPC 独立运行自己的 tool_loop（并发），
可查询自身档案和知识边界后再输出反应。
"""
from __future__ import annotations
import asyncio
import logging
import uuid
import json
from datetime import datetime
from .state import TurnContext
from .llm import load_agent_config
from ..bus import bus, BusEvent, EventType
from ..db.schema import PartType

logger = logging.getLogger(__name__)

NPC_TOOLS = ["query_npc_profile", "get_npc_knowledge_scope", "update_npc_state", "search_memory"]


def _extract_scene_npcs(ctx: TurnContext) -> list[str]:
    """从 character_data 的关系列表提取当前场景相关 NPC 名称。"""
    npcs: list[str] = []

    char_data = ctx.character_data or {}
    relationships = char_data.get("relationships", {})
    if isinstance(relationships, dict):
        npcs.extend(relationships.keys())
    elif isinstance(relationships, list):
        for r in relationships:
            if isinstance(r, dict) and "name" in r:
                npcs.append(r["name"])

    return npcs[:6]


async def _run_single_npc(
    ctx: TurnContext,
    npc_name: str,
    npc_info: dict,
    cfg: dict,
) -> dict:
    """为单个 NPC 运行独立 tool_loop，返回该 NPC 的响应。"""
    from .tool_loop import run_tool_loop, ToolContext as TCtx
    from ..bus import bus as _bus

    tc = TCtx(
        session_id=ctx.session_id,
        message_id=ctx.message_id,
        agent_name="npc",
        profile_name=getattr(ctx, "mode", "default"),
        bus=_bus,
    )

    # ── OCEAN 心理模型注入 ────────────────────────────────────────────────────
    psyche_block = ""
    try:
        from ..engine.psyche import load_from_npc_data, compute_action_bias, describe as psyche_describe
        psyche = load_from_npc_data(npc_info)
        # 情境：DM 裁决为 block 表示高威胁，trust 从角色关系取
        threat = 0.6 if ctx.dm_verdict == "resist" else 0.3
        rel_map = (ctx.character_data or {}).get("relationships", {})
        trust = 0.5
        if isinstance(rel_map, dict) and npc_name in rel_map:
            rel_val = rel_map[npc_name]
            if isinstance(rel_val, dict):
                trust = float(rel_val.get("trust", 0.5))
        bias = compute_action_bias(psyche, {"threat_level": threat, "trust_level": trust})
        psyche_desc = psyche_describe(psyche)
        psyche_block = (
            f"\n[心理模型] {psyche_desc}"
            f"当前行为倾向：{bias.dominant_action}（cooperate={bias.cooperate:.2f}, resist={bias.resist:.2f}）"
        )
    except Exception as _pe:
        logger.debug(f"[npc_agent] psyche injection skipped: {_pe}")

    npc_system = (
        f"你扮演 NPC「{npc_name}」。\n"
        "根据你的身份、当前场景和玩家行动，给出这个NPC的反应（言行举止）。\n"
        "要求：符合角色设定，只能知道你的知识范围内的信息，不超过100字。\n"
        "返回格式：直接输出 NPC 的言行，不加任何前缀。"
        f"{psyche_block}"
    )

    user_content = (
        f"场景：{ctx.plugin_key}\n"
        f"玩家行动：{ctx.user_input}\n"
        "请先用工具查询该NPC的档案和知识边界，再给出反应。"
    )

    try:
        text, _ = await run_tool_loop(
            messages=[{"role": "user", "content": user_content}],
            system_prompt=npc_system,
            tools=NPC_TOOLS,
            agent_config=cfg,
            ctx=tc,
            max_iterations=2,
        )
        return {
            "npc": npc_name,
            "response": text or f"{npc_name}沉默地看着你。",
            "error": None,
        }
    except Exception as e:
        logger.warning("NPC tool_loop 失败 [%s]: %s", npc_name, e)
        # 发送 SSE error part 而非静默返回固定台词
        try:
            await bus.publish(BusEvent(
                type=EventType.PART_CREATED,
                session_id=ctx.session_id,
                data={
                    "type": "error",
                    "content": f"NPC [{npc_name}] 行为计算失败: {e}",
                    "npc": npc_name,
                },
            ))
        except Exception:
            pass
        return {
            "npc": npc_name,
            "response": None,
            "error": str(e),
        }


async def npc_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — NPC 行为计算。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "npc"):
        return await _npc_impl(ctx)
    return ctx


async def _npc_impl(ctx: TurnContext) -> TurnContext:
    # DM 封锁时直接跳过
    if ctx.dm_verdict == "block":
        ctx.npc_reactions = []
        return ctx

    cfg = load_agent_config("npc")
    npc_list = _extract_scene_npcs(ctx)

    # NPC Agent 独立记忆召回（viewer_agent="npc"）
    try:
        from ..memory.adapter import memory_adapter
        recalled = await memory_adapter.recall(
            session_id=ctx.session_id,
            plugin_key=ctx.plugin_key,
            query_text=ctx.user_input[:150],
            viewer_agent="npc",
            top_k=4,
        )
        if recalled:
            ctx.memory_context = recalled
    except Exception:
        pass

    # 从 npc_profiles 表读取持久化 NPC（同时收集 profile 数据供 psyche 使用）
    npc_profiles: dict[str, dict] = {}
    try:
        from ..db import get_db
        async with get_db() as db:
            rows = await db.execute(
                "SELECT npc_key, profile_json FROM npc_profiles WHERE session_id=?",
                (ctx.session_id,),
            )
            for row in await rows.fetchall():
                profile = json.loads(row["profile_json"])
                name = profile.get("name", row["npc_key"])
                npc_profiles[name] = profile
                if name not in npc_list:
                    npc_list.append(name)
    except Exception:
        pass

    if not npc_list:
        ctx.npc_reactions = []
        return ctx

    # conf_b04：触发 before_npc_response（扩展可裁剪/调整出场 NPC 列表）
    try:
        from ..hooks import hook_manager, HookEvent
        _bnr = await hook_manager.fire(HookEvent.before_npc_response, {
            "session_id": ctx.session_id,
            "agent_name": "npc",
            "npc_list": npc_list,
        })
        if isinstance(_bnr.get("npc_list"), list) and _bnr["npc_list"]:
            npc_list = _bnr["npc_list"]
    except Exception as _e:
        logger.debug("[npc_agent] before_npc_response hook failed: %s", _e)

    # 并发为每个 NPC 运行独立 tool_loop（携带 profile 供 psyche 模型使用）
    tasks = [
        _run_single_npc(ctx, npc_name, npc_profiles.get(npc_name, {}), cfg)
        for npc_name in npc_list
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤异常，收集有效结果
    reactions: list[dict] = []
    for npc_name, result in zip(npc_list, raw_results):
        if isinstance(result, Exception):
            logger.warning("NPC tool_loop 异常 [%s]: %s", npc_name, result)
            continue
        if result.get("error"):
            logger.warning("NPC tool_loop 错误 [%s]: %s", npc_name, result["error"])
            continue
        reactions.append({
            "npc_name": result["npc"],
            "intention": result["response"],
            "dialogue": result["response"],
            "emotion": "平静",
        })

    ctx.npc_reactions = reactions

    # conf_b04：触发 after_npc_response（扩展可后处理/记录 NPC 反应）
    try:
        from ..hooks import hook_manager, HookEvent
        _anr = await hook_manager.fire(HookEvent.after_npc_response, {
            "session_id": ctx.session_id,
            "agent_name": "npc",
            "reactions": reactions,
        })
        if isinstance(_anr.get("reactions"), list):
            ctx.npc_reactions = _anr["reactions"]
            reactions = ctx.npc_reactions
    except Exception as _e:
        logger.debug("[npc_agent] after_npc_response hook failed: %s", _e)

    # 发布 npc_action Parts（每个有响应的 NPC）
    if ctx.npc_reactions and ctx.session_id and ctx.message_id:
        now = datetime.now().timestamp()
        try:
            from ..db import get_db
            async with get_db() as db:
                part_ids_and_contents: list[tuple[str, dict]] = []
                for reaction in ctx.npc_reactions:
                    if not (reaction.get("dialogue") or reaction.get("intention")):
                        continue
                    part_id = str(uuid.uuid4())
                    content = {
                        "npc_name": reaction["npc_name"],
                        "intention": reaction["intention"],
                        "dialogue": reaction.get("dialogue"),
                        "emotion": reaction.get("emotion", "平静"),
                    }
                    await db.execute(
                        "INSERT OR IGNORE INTO message_parts "
                        "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 'done', 'npc', ?, ?)",
                        (part_id, ctx.message_id, ctx.session_id,
                         PartType.NPC_ACTION, json.dumps(content, ensure_ascii=False), now, now),
                    )
                    part_ids_and_contents.append((part_id, content))
                await db.commit()

            for part_id, content in part_ids_and_contents:
                await bus.publish_part_created(
                    ctx.session_id, part_id, PartType.NPC_ACTION, ctx.message_id, "npc"
                )
                await bus.publish_part_done(ctx.session_id, part_id, content)
        except Exception as e:
            # 降级补日志：npc_action Part 发布失败此前完全无痕。
            logger.warning("[npc_agent] npc_action Part 发布失败: %s: %s",
                           type(e).__name__, e)

    return ctx
