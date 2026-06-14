"""
Research Agent — LLM 驱动的迭代 Web 研究循环

架构：自定义 ReAct 循环（不依赖 run_tool_loop），
直接调用 litellm + 工具注册表，并在每一步通过 on_event 回调推送 SSE 事件。

SSE 事件类型（推送给前端）：
  thinking  - LLM 文字推理片段（出现时）
  tool_call - Agent 调用工具（tool、args 摘要）
  tool_done - 工具完成（tool、brief 结果摘要）
  done      - 研究完成，携带 entries 列表
  error     - 遭遇致命错误

用法：
    from backend.agents.research_agent import run_research_agent

    async def my_sse(event: dict):
        ...  # yield SSE JSON

    entries = await run_research_agent(
        world_name="Gundam SEED",
        context="Mobile Suit Gundam SEED，CE71纪年",
        on_event=my_sse,
    )
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# 最大研究轮次（每轮含一次 LLM 调用 + N 次工具调用）
_MAX_ROUNDS = 12
# 单轮最大工具调用数（防止 LLM 一次性发起过多）
_MAX_TOOLS_PER_ROUND = 5
# Doom Loop 防护：同签名调用超过此次数 → 跳过
_DOOM_THRESHOLD = 3

_RESEARCH_SYSTEM = """\
你是一个专业的 TRPG 世界观研究员。你的任务是收集关于「{world}」世界的设定资料，\
用于生成结构化的世界观档案。

工作流程：
1. 首先用 web_search 搜索「{world} wiki」「{world} 百科」「{world} 世界观设定」等关键词
2. 从搜索结果中选择权威来源（优先 wiki 站点、萌娘百科、Fandom、Biligame），用 fetch_webpage 抓取
3. 阅读内容后，如果发现有价值的相关页面链接，继续 fetch_webpage 深挖（如角色、地点、技术体系等）
4. 当收集到足够多的内容（至少 3-5 个页面、覆盖世界观、角色、背景等多个层面）后，\
调用 synthesize_lore 提炼档案条目

工具选择策略：
- fetch_webpage：普通网页首选，速度快
- browse_url：当 fetch_webpage 返回错误或空内容时改用此工具——它使用真实 Chromium 浏览器，\
  适合 Wikipedia、Fandom、萌娘百科等需要 JS 渲染或 bot 检测会拦截 httpx 的站点；\
  speed 较慢但成功率更高，wait_seconds 可调大（6-8）应对 Cloudflare 等慢加载页面
- synthesize_lore：唯一的退出工具，调用后研究结束

注意事项：
- web_search 查询要多样化，覆盖不同角度（世界设定、主要人物、历史、技术/魔法体系等）
- fetch_webpage/browse_url 优先抓权威 wiki 页面，避免新闻/论坛/购物等无效页面
- 每个独立话题抓一个页面即可，不要重复抓同一页面
- 收集到 5-8 个页面的内容后即可调用 synthesize_lore
- synthesize_lore 只能调用一次，调用后研究结束
"""


async def run_research_agent(
    world_name: str,
    context: str = "",
    max_rounds: int = _MAX_ROUNDS,
    on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> list[dict]:
    """
    执行 LLM 驱动的迭代 web 研究，返回提炼好的 lore entries。

    Args:
        world_name:  目标世界名称
        context:     额外上下文（如世界别名、原著类型）
        max_rounds:  最大研究轮次
        on_event:    async callable，接收 SSE 事件 dict

    Returns:
        list[dict] — [{"title":..., "content":..., "archive_type":...}, ...]
    """
    import litellm

    from .llm import load_agent_config
    from ..tools.registry import tool_registry, ToolContext

    async def emit(evt: dict) -> None:
        if on_event:
            try:
                await on_event(evt)
            except Exception:
                pass

    # 准备工具列表（只允许研究相关工具）
    _ALLOWED_TOOLS = {"web_search", "fetch_webpage", "browse_url", "synthesize_lore"}
    openai_tools: list[dict] = []
    for tool_name_reg in _ALLOWED_TOOLS:
        defn = tool_registry.get(tool_name_reg)
        if defn:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": defn.name,
                    "description": defn.description,
                    "parameters": defn.schema(),
                },
            })

    if not openai_tools:
        logger.error("[research_agent] 未找到任何研究工具，检查 tool_registry 注册状态")
        return []

    # LLM 配置（复用 dm 角色配置）
    config = load_agent_config("dm")
    provider = config.get("provider", "deepseek")
    model_name = config.get("model", "deepseek-chat")
    if provider == "deepseek":
        model_str = f"deepseek/{model_name}"
    elif provider == "openai":
        model_str = model_name
    else:
        model_str = f"{provider}/{model_name}"
    temperature = float(config.get("temperature", 0.5))

    system_prompt = _RESEARCH_SYSTEM.format(world=world_name)
    user_content = f"请开始研究世界：{world_name}"
    if context:
        user_content += f"\n额外上下文：{context}"

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    ctx = ToolContext(session_id="research", agent_name="research")
    call_counter: Counter = Counter()
    all_fetched_texts: list[str] = []
    lore_entries: list[dict] = []
    synthesize_called = False

    for round_idx in range(max_rounds):
        logger.info("[research_agent] Round %d / %d", round_idx + 1, max_rounds)

        try:
            resp = await litellm.acompletion(
                model=model_str,
                messages=messages,
                temperature=temperature,
                max_tokens=1500,
                tools=openai_tools,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error("[research_agent] LLM call failed: %s", e, exc_info=True)
            await emit({"type": "error", "message": f"LLM 调用失败：{e}"})
            break

        choice = resp.choices[0]
        msg = choice.message

        # LLM 文字思考内容
        if msg.content:
            await emit({"type": "thinking", "text": msg.content})

        raw_tc = getattr(msg, "tool_calls", None) or []

        # 无工具调用 → 研究结束
        if not raw_tc:
            logger.info("[research_agent] No tool calls, ending research loop")
            break

        # 序列化工具调用并追加助手消息
        tc_list = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in raw_tc[:_MAX_TOOLS_PER_ROUND]
        ]
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": tc_list,
        })

        # 执行工具调用
        for tc in tc_list:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}

            # Doom Loop 防护
            sig = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
            call_counter[sig] += 1
            if call_counter[sig] > _DOOM_THRESHOLD:
                logger.warning("[research_agent] Doom loop detected for %s, skipping", tool_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps({"ok": False, "error": "重复调用已被跳过，请换一个查询或页面"}, ensure_ascii=False),
                })
                continue

            # 发射 tool_call 事件
            args_brief = _brief_args(tool_name, args)
            await emit({"type": "tool_call", "tool": tool_name, "args_brief": args_brief})

            # 调用工具
            handler_def = tool_registry.get(tool_name)
            if not handler_def:
                result = {"ok": False, "error": f"工具 {tool_name!r} 未注册"}
            else:
                try:
                    result = await handler_def.handler(**args)
                except Exception as ex:
                    result = {"ok": False, "error": str(ex)}

            # 收集抓取的文本（fetch_webpage 和 browse_url 均收集）
            if tool_name in ("fetch_webpage", "browse_url") and isinstance(result, dict) and result.get("ok"):
                text = result.get("text", "")
                if text:
                    all_fetched_texts.append(text)

            # 处理 synthesize_lore 结果
            if tool_name == "synthesize_lore" and isinstance(result, dict) and result.get("ok"):
                lore_entries = result.get("entries", [])
                synthesize_called = True

            # 结果摘要发送给 LLM
            result_summary = _summarize_result(tool_name, result)
            await emit({"type": "tool_done", "tool": tool_name, "brief": result_summary})

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(_trim_result(tool_name, result), ensure_ascii=False),
            })

        # synthesize_lore 已调用 → 研究完成
        if synthesize_called:
            break

    # 如果循环结束但未调用 synthesize_lore，用已收集文本做最后提炼
    if not synthesize_called and all_fetched_texts:
        await emit({"type": "thinking", "text": "研究轮次已用完，使用已收集内容自动提炼..."})
        from ..extensions.web_scraper.tools import _synthesize_lore
        try:
            result = await _synthesize_lore(texts=all_fetched_texts, world_name=world_name)
            lore_entries = result.get("entries", [])
        except Exception as e:
            logger.error("[research_agent] fallback synthesize failed: %s", e)

    await emit({
        "type": "done",
        "entries": lore_entries,
        "entries_count": len(lore_entries),
        "pages_fetched": len(all_fetched_texts),
    })
    return lore_entries


def _brief_args(tool_name: str, args: dict) -> str:
    """生成工具调用的简短描述，用于 SSE 日志。"""
    if tool_name == "web_search":
        return f'搜索："{args.get("query", "")}"'
    if tool_name in ("fetch_webpage", "browse_url"):
        url = args.get("url", "")
        prefix = "浏览：" if tool_name == "browse_url" else "抓取："
        return f"{prefix}{url[:60]}{'...' if len(url) > 60 else ''}"
    if tool_name == "synthesize_lore":
        n = len(args.get("texts", []))
        return f"提炼 {n} 段文本"
    return json.dumps(args, ensure_ascii=False)[:80]


def _summarize_result(tool_name: str, result: dict) -> str:
    """生成工具结果的简短摘要，用于 SSE 日志。"""
    if not isinstance(result, dict):
        return "完成"
    if not result.get("ok"):
        return f"失败：{result.get('error', '未知错误')[:60]}"
    if tool_name == "web_search":
        count = result.get("count", 0)
        return f"找到 {count} 条结果"
    if tool_name == "fetch_webpage":
        chars = result.get("chars", 0)
        engine = result.get("engine", "")
        return f"抓取成功（{engine}，{chars} 字）"
    if tool_name == "browse_url":
        chars = result.get("chars", 0)
        title = result.get("title", "")[:30]
        return f"浏览成功（{title}，{chars} 字）"
    if tool_name == "synthesize_lore":
        n = result.get("entries_count", 0)
        return f"提炼出 {n} 条档案"
    return "完成"


def _trim_result(tool_name: str, result: dict) -> dict:
    """裁剪工具结果，避免消息历史过长。"""
    if not isinstance(result, dict):
        return result
    if tool_name == "fetch_webpage":
        # 只传前 3000 字给 LLM，节省 token
        trimmed = dict(result)
        if "text" in trimmed:
            trimmed["text"] = trimmed["text"][:3000]
        return trimmed
    if tool_name == "synthesize_lore":
        # 只传条目数，不传完整内容（LLM 不需要读回自己生成的）
        return {"ok": result.get("ok"), "entries_count": result.get("entries_count", 0)}
    return result
