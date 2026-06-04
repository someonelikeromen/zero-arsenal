"""
World Agent — 计算世界状态在本轮的自然演变。
在 DM 通过后运行，提供世界层面的变化信息给 Narrator，
并向前端发布 world_event Parts（play 模式可见）。
"""
from __future__ import annotations
import uuid
import json
from datetime import datetime
from .state import TurnContext
from .llm import llm_complete, load_agent_config
from ..bus import bus
from ..db.schema import PartType


WORLD_SYSTEM_PROMPT = """\
你是跑团世界的演变计算器。根据玩家行动，计算世界层面的自然演变。
仅在有明显世界变化时输出，否则返回 []。
输出格式（严格 JSON 数组，无 markdown 代码块）：
[{"event_type": "time|weather|npc_move|faction", "description": "简短描述（1句话）", "affects": "影响范围", "world_time": "（可选）变化后的世界时间", "location": "（可选）变化后的当前地点"}]
当事件改变了时间或地点时，请填写对应的 world_time / location 字段（供数据流轴使用）。
大多数普通行动不产生世界事件，请克制输出.\
"""


def _render_world_template(world_plugin: str = "", skill_block: str = "", current_events: str = "") -> str:
    """
    从 prompts/templates/world.j2 渲染世界演变 Agent 系统 prompt。
    渲染失败时回退到内联 WORLD_SYSTEM_PROMPT。
    """
    try:
        from ..prompts.template_loader import render_prompt
        rendered = render_prompt(
            "world",
            variables={
                "world_plugin": world_plugin,
                "skill_block": skill_block,
                "current_events": current_events,
            },
        )
        if rendered.strip():
            return rendered
    except Exception:
        pass
    return WORLD_SYSTEM_PROMPT

# 触发世界演变的关键词（涵盖常规行动，过严门槛降低）
_TRIGGER_KEYWORDS = (
    # 时间/地点移动
    "时间", "天气", "离开", "抵达", "前往", "返回", "出发", "进入", "穿越",
    # 战斗/冲突
    "战斗", "攻击", "逃跑", "反击", "爆炸", "追杀", "伏击",
    # 社会/势力
    "组织", "势力", "派系", "联盟", "叛变", "宣战", "谈判", "协议",
    # 生死/大事
    "死亡", "消失", "觉醒", "突破", "任务完成", "失败",
    # 信息流通
    "消息", "情报", "谣言", "传言",
    # 物品/资源
    "获得", "失去", "交易", "购买", "盗取",
    # 环境变化
    "地震", "火灾", "洪水", "事故",
)


def _should_invoke_world_agent(ctx: TurnContext) -> bool:
    """
    判断本轮是否值得调用世界演变 Agent。
    策略：关键词触发 OR 每 5 轮强制触发一次（保持世界活性）。
    """
    # DM 封锁时跳过
    if ctx.dm_verdict == "block":
        return False

    # 带有剧情压规则的世界插件（如 crossover）总是检查
    try:
        from ..extensions.plugin import plugin_registry
        plugin = plugin_registry.get(ctx.world_plugin)
        if plugin and plugin.metadata.get("plot_pressure"):
            return True
    except Exception:
        pass

    user_input_lower = (ctx.user_input or "").lower()

    # 输入包含触发关键词
    if any(kw in user_input_lower for kw in _TRIGGER_KEYWORDS):
        return True

    # 每 5 轮强制触发一次，保持世界活性（turn_index 从 1 开始）
    turn = getattr(ctx, "turn_index", 0)
    if turn > 0 and turn % 5 == 0:
        return True

    return False


def _build_world_messages(ctx: TurnContext) -> list[dict]:
    return _build_world_messages_with_memory(ctx, ctx.memory_context)


def _build_world_messages_with_memory(ctx: TurnContext, memory_ctx: str) -> list[dict]:
    memory_hint = ""
    if memory_ctx:
        memory_hint = f"背景信息：{memory_ctx[:300]}\n"

    # 优先从 Jinja2 模板渲染；失败回退内联 prompt（05-prompt-architecture.md §3）
    system_content = _render_world_template(
        world_plugin=ctx.world_plugin,
        current_events=memory_hint.strip(),
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": (
            f"世界插件：{ctx.world_plugin}\n"
            f"{memory_hint}"
            f"玩家行动：{ctx.user_input}"
        )},
    ]


async def world_agent_node(ctx: TurnContext) -> TurnContext:
    """LangGraph 节点函数 — 世界状态演变计算。"""
    from .agent_span import agent_span
    async with agent_span(ctx, "world"):
        return await _world_impl(ctx)
    return ctx


async def _world_impl(ctx: TurnContext) -> TurnContext:
    if not _should_invoke_world_agent(ctx):
        ctx.world_events = []
        return ctx

    cfg = load_agent_config("world")

    # 世界 Agent 的专属记忆召回（viewer_agent="world"，只看客观世界层）
    world_memory_ctx = ctx.memory_context  # 先用已有的
    try:
        from ..memory.adapter import memory_adapter
        recalled = await memory_adapter.recall(
            session_id=ctx.session_id,
            world_plugin=ctx.world_plugin,
            query_text=ctx.user_input[:150],
            viewer_agent="world",
            top_k=4,
        )
        if recalled:
            world_memory_ctx = recalled
    except Exception:
        pass

    try:
        raw = await llm_complete(
            messages=_build_world_messages_with_memory(ctx, world_memory_ctx),
            provider=cfg.get("provider", "deepseek"),
            model=cfg.get("model", "deepseek-chat"),
            temperature=cfg.get("temperature", 0.5),
            max_tokens=cfg.get("max_tokens", 256),
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)
        if isinstance(result, list):
            events: list[dict] = []
            for item in result:
                if not isinstance(item, dict):
                    continue
                evt = {
                    "event_type": item.get("event_type", "unknown"),
                    "description": item.get("description", ""),
                    "affects": item.get("affects", ""),
                }
                # NEW-C4-02：透传可选的 world_time / location，使其与
                # runtime_data_stream 的轴 12-13 读取键对齐（此前键不匹配，
                # 世界时间/地点恒走 meta 回退）。
                wt = item.get("world_time") or item.get("new_time")
                loc = item.get("location") or item.get("new_location")
                if wt:
                    evt["world_time"] = str(wt)
                if loc:
                    evt["location"] = str(loc)
                events.append(evt)
            ctx.world_events = events
        else:
            ctx.world_events = []
    except Exception as e:
        # NEW-C2-05：世界事件本属可选，但失败需留日志以区分
        # "克制不输出" 与 "调用/解析崩溃"。
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[world_agent] LLM/JSON 解析失败，world_events 清空: %s: %s",
            type(e).__name__, e,
        )
        ctx.world_events = []

    # 发布 world_event Parts 并写入 world_archives
    if ctx.world_events and ctx.session_id and ctx.message_id:
        now = datetime.now().timestamp()
        try:
            from ..db import get_db
            part_ids_and_contents: list[tuple[str, dict]] = []
            async with get_db() as db:
                for evt in ctx.world_events:
                    if not evt.get("description"):
                        continue
                    part_id = str(uuid.uuid4())
                    content = {
                        "event_type": evt["event_type"],
                        "description": evt["description"],
                        "affects": evt.get("affects", ""),
                    }
                    if evt.get("world_time"):
                        content["world_time"] = evt["world_time"]
                    if evt.get("location"):
                        content["location"] = evt["location"]
                    await db.execute(
                        "INSERT OR IGNORE INTO message_parts "
                        "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 'done', 'world', ?, ?)",
                        (part_id, ctx.message_id, ctx.session_id,
                         PartType.WORLD_EVENT, json.dumps(content, ensure_ascii=False), now, now),
                    )
                    part_ids_and_contents.append((part_id, content))
                    # 同步写入 world_archives（供 P2 回调和 search_lore 工具使用）
                    archive_id = str(uuid.uuid4())
                    archive_entry = {
                        "type": "world_event",
                        "event_type": evt["event_type"],
                        "description": evt["description"],
                        "affects": evt.get("affects", ""),
                        "turn_time": now,
                    }
                    await db.execute(
                        "INSERT OR IGNORE INTO world_archives "
                        "(id, session_id, world_key, archive_type, title, content, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (archive_id, ctx.session_id, ctx.world_plugin,
                         "event", evt["description"][:60],
                         json.dumps(archive_entry, ensure_ascii=False), now, now),
                    )
                await db.commit()

            # 发布 SSE（part.created + part.done，使用同一 part_id）
            for part_id, content in part_ids_and_contents:
                await bus.publish_part_created(
                    ctx.session_id, part_id, PartType.WORLD_EVENT, ctx.message_id, "world"
                )
                await bus.publish_part_done(ctx.session_id, part_id, content)
        except Exception as e:
            # NEW-C2-05：发布失败补日志（此前 except: pass 完全无痕）。
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[world_agent] world_event Part 发布失败: %s: %s",
                type(e).__name__, e,
            )

    return ctx
