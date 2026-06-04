"""
tool_loop — Agent 内层工具调用循环。

参考 pi 的 agent-loop.ts 思路：
  1. LLM 返回 tool_calls → 并发执行 → 将结果拼回 messages → 继续
  2. LLM 返回 finish_reason=stop 或 content → 循环结束
  3. Doom Loop 防护：同工具+同参数 3 次 → 终止
  4. 最多 10 轮循环

用法：
    from .tool_loop import run_tool_loop, ToolContext

    text, calls = await run_tool_loop(
        messages=[{"role": "user", "content": "..."}],
        system_prompt="...",
        tools=["read_character", "get_world_state"],
        agent_config=load_agent_config("dm"),
        ctx=ToolContext(session_id="...", agent_name="dm"),
    )
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import Counter
from typing import Callable, Optional

# ToolContext 在 registry 中定义，这里重新导出，方便调用方直接从 tool_loop 导入
from ..tools.registry import ToolContext  # noqa: F401

logger = logging.getLogger(__name__)

_DOOM_THRESHOLD = 3       # 同签名调用超过此次数视为 doom loop
_DEFAULT_MAX_ITER = 20    # 最大循环轮数（D12：恢复为设计值 20）


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_tool_loop(
    messages: list[dict],
    system_prompt: str,
    tools: list[str],
    agent_config: dict,
    ctx: ToolContext,
    max_iterations: int = _DEFAULT_MAX_ITER,
    on_delta: Optional[Callable] = None,
) -> tuple[str, list[dict]]:
    """
    执行 tool_use 内层循环。

    Returns:
        (final_text, tool_call_records)
        - final_text: LLM 最终非工具文本输出
        - tool_call_records: [{"tool": name, "args": {...}, "result": {...}}, ...]

    出现任何错误时静默返回 ("", [])，不崩溃上层管线。
    """
    try:
        return await _run(messages, system_prompt, tools, agent_config, ctx,
                          max_iterations, on_delta)
    except Exception as e:
        # NEW-C3-04：致命错误（litellm 超时/限流/provider 不可用等）此前被压成
        # ("",[])，调用方无法区分 "模型没说话" 与 "调用失败"。这里升级为 ERROR +
        # exc_info，确保栈可见；仍返回空以避免崩溃上层管线（契约保持不变）。
        logger.error("[tool_loop] run_tool_loop failed: %s: %s",
                     type(e).__name__, e, exc_info=True)
        return "", []


async def _run(
    messages: list[dict],
    system_prompt: str,
    tools: list[str],
    agent_config: dict,
    ctx: ToolContext,
    max_iterations: int,
    on_delta: Optional[Callable],
) -> tuple[str, list[dict]]:
    from ..tools.registry import tool_registry
    import litellm

    # 拼装完整消息（系统提示优先）
    full_messages: list[dict] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    # 按 AgentProfile.active_tools 过滤传给 LLM 的工具列表
    # 优先使用会话级有效 Profile（含 WorldPlugin overlay），否则使用全局 Profile
    filtered_tools = list(tools)
    try:
        from .permission import profile_registry
        session_id = getattr(ctx, "session_id", None) or ""
        profile_name = getattr(ctx, "profile_name", None) or "play"
        if session_id:
            profile = profile_registry.get_session_profile(session_id, profile_name)
        else:
            profile = profile_registry.get(profile_name)
        filtered_tools = profile.filter_tools(filtered_tools)
    except Exception:
        pass  # 过滤失败时使用原列表

    # 取出本次循环允许使用的工具（OpenAI 格式）
    openai_tools = tool_registry.to_openai_functions(names=filtered_tools)

    # 构建 litellm 模型字符串
    provider   = agent_config.get("provider", "deepseek")
    model_name = agent_config.get("model", "deepseek-chat")
    temperature = float(agent_config.get("temperature", 0.7))
    max_tokens  = int(agent_config.get("max_tokens", 1024))

    if provider == "deepseek":
        model_str = f"deepseek/{model_name}"
    elif provider == "openai":
        model_str = f"openai/{model_name}"
    else:
        model_str = model_name

    # 是否启用 function calling（配置中可关闭）
    use_fc = bool(agent_config.get("functions", True)) and bool(openai_tools)

    call_counter: Counter = Counter()
    all_tool_calls: list[dict] = []

    for iteration in range(max_iterations):
        # --- 构造 LLM 请求 ---
        kwargs: dict = {
            "model":       model_str,
            "messages":    full_messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        if use_fc:
            kwargs["tools"]       = openai_tools
            kwargs["tool_choice"] = "auto"

        # NEW-C3-04 / D-22：FC 调用失败时自动降级到文本解析模式，而非整体
        # 吞成空输出。仅对启用了 FC 的请求做一次降级重试；非 FC 错误向上抛。
        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as fc_err:
            if use_fc:
                logger.warning(
                    "[tool_loop] function calling 调用失败，降级为文本解析模式重试: %s: %s",
                    type(fc_err).__name__, fc_err,
                )
                use_fc = False
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                resp = await litellm.acompletion(**kwargs)
            else:
                raise
        choice = resp.choices[0]
        msg    = choice.message

        # --- 检查工具调用 ---
        raw_tc = getattr(msg, "tool_calls", None) or []

        # function calling 模式：无工具调用 → 循环结束
        if use_fc and not raw_tc:
            return msg.content or "", all_tool_calls

        # 非 function calling 模式：尝试文本解析
        if not use_fc:
            content = msg.content or ""
            parsed  = _parse_tool_calls_from_text(content)
            if not parsed:
                return content, all_tool_calls
            # 将助手消息追加（带原始文本），然后用解析结果走工具流程
            full_messages.append({"role": "assistant", "content": content})
            tc_list = parsed
        else:
            # 将 litellm tool_call 对象序列化为 dict，追加助手消息
            tc_list = [
                {
                    "id":   tc.id,
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in raw_tc
            ]
            full_messages.append({
                "role":       "assistant",
                "content":    msg.content,
                "tool_calls": tc_list,
            })

        # --- 按 execution_mode 分组执行工具 ---
        # sequential 工具串行执行（有副作用），parallel 工具并发执行（幂等）
        results = await _execute_batch(tc_list, tool_registry, ctx, call_counter, all_tool_calls)

        # 全部触发 doom loop 时退出
        if all(r["result"].get("error") == "doom_loop_detected" for r in results):
            logger.warning("[tool_loop] All tool calls hit doom loop guard, stopping")
            break

        # 将工具结果追加到消息列表
        for r in results:
            full_messages.append({
                "role":         "tool",
                "tool_call_id": r["id"],
                "content":      json.dumps(r["result"], ensure_ascii=False),
            })

    # 从历史中找最后一条有效的 assistant 文本
    for m in reversed(full_messages):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"], all_tool_calls

    return "", all_tool_calls


# ---------------------------------------------------------------------------
# 单工具调用（含 Doom Loop 防护）
# ---------------------------------------------------------------------------

async def _execute_batch(
    tc_list: list[dict],
    tool_registry,
    ctx: ToolContext,
    call_counter: Counter,
    all_tool_calls: list,
) -> list[dict]:
    """
    按 ToolDef.execution_mode 分批执行：
    - sequential 工具依次串行执行（保证副作用顺序）
    - parallel   工具在同批中并发执行
    最终结果保持 tc_list 原始顺序。
    """
    # 先把 tc_list 按 execution_mode 分批，保持相对顺序
    # 连续的 parallel 合并为一批，sequential 各自一批
    batches: list[tuple[str, list[dict]]] = []
    for tc in tc_list:
        tool_def = tool_registry.get(tc.get("function", {}).get("name", ""))
        mode = getattr(tool_def, "execution_mode", "parallel") if tool_def else "parallel"
        if batches and batches[-1][0] == "parallel" and mode == "parallel":
            batches[-1][1].append(tc)
        else:
            batches.append((mode, [tc]))

    ordered_results: list[dict] = []
    for mode, batch in batches:
        if mode == "parallel":
            batch_results = await asyncio.gather(*[
                _execute_one(tc, tool_registry, ctx, call_counter, all_tool_calls)
                for tc in batch
            ])
            ordered_results.extend(batch_results)
        else:
            # sequential：逐个等待
            for tc in batch:
                r = await _execute_one(tc, tool_registry, ctx, call_counter, all_tool_calls)
                ordered_results.append(r)

    return ordered_results


async def _execute_one(
    tc: dict,
    tool_registry,
    ctx: ToolContext,
    call_counter: Counter,
    all_tool_calls: list,
) -> dict:
    """执行单个工具调用，含 Doom Loop 防护和错误静默降级。"""
    func  = tc.get("function", {})
    name  = func.get("name", "")
    args_raw = func.get("arguments", "{}")
    tc_id = tc.get("id", "")

    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
    except json.JSONDecodeError:
        args = {}

    # Doom Loop 检测
    sig = f"{name}:{json.dumps(args, sort_keys=True)}"
    call_counter[sig] += 1
    if call_counter[sig] >= _DOOM_THRESHOLD:
        logger.warning(
            f"[tool_loop] Doom loop: {name} called {call_counter[sig]}x "
            f"with same args, blocking"
        )
        return {"id": tc_id, "name": name, "result": {"error": "doom_loop_detected"}}

    tool_def = tool_registry.get(name)

    # ── 运行时权限门控（10-permission-modes.md §4.2）──────────────────────────
    try:
        from .permission import profile_registry, PermissionAction
        _session_id = getattr(ctx, "session_id", None) or ""
        _profile_name = getattr(ctx, "profile_name", None) or "play"
        _profile = (
            profile_registry.get_session_profile(_session_id, _profile_name)
            if _session_id else profile_registry.get(_profile_name)
        )
        _action = _profile.check_tool(name)
        if _action == PermissionAction.DENY:
            logger.info("[tool_loop] 工具 '%s' 被权限 DENY 拦截 (profile=%s)", name, _profile_name)
            return {"id": tc_id, "name": name, "result": {
                "error": "permission_denied",
                "tool_name": name,
                "profile": _profile_name,
                "message": f"工具 '{name}' 在 '{_profile_name}' 模式下被禁止执行",
            }}
        # ASK 权限：真正阻塞式挂起等待用户确认（60s 超时 → deny），S7 修复
        if _action == PermissionAction.ASK and _session_id:
            from .ask_handler import check_permission_and_ask
            _allowed = await check_permission_and_ask(
                session_id=_session_id,
                tool_name=name,
                tool_args=args,
                profile_name=_profile_name,
                reason=f"工具 '{name}' 在 '{_profile_name}' 模式下需要确认执行",
            )
            if not _allowed:
                logger.info("[tool_loop] 工具 '%s' ASK 被拒绝 (profile=%s)", name, _profile_name)
                return {"id": tc_id, "name": name, "result": {
                    "error": "permission_denied",
                    "tool_name": name,
                    "profile": _profile_name,
                    "message": f"工具 '{name}' 执行请求被用户拒绝或超时",
                }}
    except Exception as _perm_err:
        # 安全策略（fail-closed）：权限解析本身出错时拒绝执行，
        # 不得静默放行 —— 否则攻击者可借触发异常绕过权限门控。
        logger.warning(
            "[tool_loop] 权限检查异常，安全拒绝工具 '%s': %s", name, _perm_err
        )
        return {"id": tc_id, "name": name, "result": {
            "error": "permission_check_failed",
            "tool_name": name,
            "message": f"工具 '{name}' 权限检查异常，已安全拒绝执行",
        }}

    # 工具级别 before_hooks（在全局 Hook 之前执行）
    if tool_def and tool_def.before_hooks:
        for hook_fn in tool_def.before_hooks:
            try:
                patched = await hook_fn(args, ctx)
                if isinstance(patched, dict):
                    args = patched
            except Exception as _bhe:
                logger.debug(f"[tool_loop] before_hook for {name} raised: {_bhe}")

    # 触发 before_tool_call Hook（可修改 args 或中止调用）
    try:
        from ..hooks import hook_manager, HookEvent
        hook_ctx = {
            "session_id": ctx.session_id,
            "agent_name": ctx.agent_name,
            "tool_name": name,
            "args": args,
            "allow": True,
        }
        hook_ctx = await hook_manager.fire(HookEvent.before_tool_call, hook_ctx)
        if not hook_ctx.get("allow", True):
            result = {"error": "blocked_by_hook", "tool_name": name}
            all_tool_calls.append({"tool": name, "args": args, "result": result})
            return {"id": tc_id, "name": name, "result": result}
        # Hook 可修改 args
        if isinstance(hook_ctx.get("args"), dict):
            args = hook_ctx["args"]
    except Exception:
        pass

    # ── emit tool_call Part（工具执行前）────────────────────────────────────
    _part_id = str(uuid.uuid4())
    _now = __import__("time").time()
    try:
        from ..bus import bus
        from ..db.schema import PartType
        if ctx.session_id:
            await bus.publish_part_created(
                ctx.session_id, _part_id, PartType.TOOL_CALL,
                ctx.message_id or "", ctx.agent_name,
            )
    except Exception:
        pass

    result = await tool_registry.execute(name, args, ctx=ctx)

    # ── emit tool_result Part（工具执行后）──────────────────────────────────
    try:
        from ..bus import bus
        if ctx.session_id:
            await bus.publish_part_done(
                ctx.session_id, _part_id,
                {"tool_name": name, "args": args, "result": result, "status": "done"},
            )
    except Exception:
        pass

    # 触发 after_tool_call Hook
    try:
        from ..hooks import hook_manager, HookEvent
        after_ctx = {
            "session_id": ctx.session_id,
            "agent_name": ctx.agent_name,
            "tool_name": name,
            "args": args,
            "result": result,
        }
        after_ctx = await hook_manager.fire(HookEvent.after_tool_call, after_ctx)
        if isinstance(after_ctx.get("result"), dict):
            result = after_ctx["result"]
    except Exception:
        pass

    # 工具级别 after_hooks（在全局 Hook 之后执行）
    if tool_def and tool_def.after_hooks:
        for hook_fn in tool_def.after_hooks:
            try:
                patched = await hook_fn(args, result, ctx)
                if isinstance(patched, dict):
                    result = patched
            except Exception as _ahe:
                logger.debug(f"[tool_loop] after_hook for {name} raised: {_ahe}")

    # ── gacha 结果写入 TurnContext.gacha_pending ──────────────────────────────
    if (name == "draw_gacha"
            and isinstance(result, dict)
            and result.get("ok")
            and isinstance(result.get("results"), list)
            and ctx.turn_ctx is not None):
        try:
            ctx.turn_ctx.gacha_pending.extend(result["results"])
        except Exception:
            pass

    all_tool_calls.append({"tool": name, "args": args, "result": result})
    return {"id": tc_id, "name": name, "result": result}


# ---------------------------------------------------------------------------
# 文本解析回退（非 function calling 模式）
# ---------------------------------------------------------------------------

def _parse_tool_calls_from_text(text: str) -> list[dict]:
    """
    从 LLM 文本响应中提取工具调用（function calling 不可用时的 fallback）。
    支持两种格式：
      1. <tool_call>{"name": "...", "arguments": {...}}</tool_call>
      2. ```json\n{"tool": "...", "args": {...}}\n```
    """
    calls: list[dict] = []

    # --- 格式 1：<tool_call> 标签 ---
    for m in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        try:
            data = json.loads(m.group(1).strip())
            name = data.get("name") or data.get("tool", "")
            if not name:
                continue
            raw_args = data.get("arguments") or data.get("args") or {}
            calls.append({
                "id":   str(uuid.uuid4())[:8],
                "type": "function",
                "function": {
                    "name":      name,
                    "arguments": json.dumps(raw_args, ensure_ascii=False),
                },
            })
        except (json.JSONDecodeError, KeyError):
            pass

    if calls:
        return calls

    # --- 格式 2：```json 代码块 ---
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            name = data.get("tool") or data.get("name", "")
            if not name:
                continue
            raw_args = data.get("args") or data.get("arguments") or data.get("parameters") or {}
            calls.append({
                "id":   str(uuid.uuid4())[:8],
                "type": "function",
                "function": {
                    "name":      name,
                    "arguments": json.dumps(raw_args, ensure_ascii=False),
                },
            })
        except (json.JSONDecodeError, KeyError):
            pass

    return calls
