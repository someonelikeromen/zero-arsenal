"""
LangGraph 图 — 完整 Agent 管线。

流程：
  user_input
      │
  [rules]     ← 规则校验门禁（pass / block）
      │
  ┌───┴──────────┐
  │ block        │ pass
  │              │
 [END]      [dm_gate]  ← DM 阈门验证（allow / block / needs_roll）
                 │
         ┌───────┴──────────┐
         │ needs_roll       │ allow / block
         │                  │
     [dice_node]            │
         │                  │
         └────────┬─────────┘
                  │
               [npc]   ← NPC 行为计算（block 时跳过，直接透传）
                  │
              [world]  ← 世界状态演变（轻量，无变化时透传）
                  │
            [narrator]  ← 四阶段叙事（P1规划→P2记忆→P3写作→P4结算）
                  │
              [style]   ← 文风润色 + 纯净度检查
                  │
               [var]    ← 变量结算，写回 DB
                  │
          [chronicler]  ← 章节固化（每 N 轮自动触发）
                  │
              [END]
"""
from __future__ import annotations
import asyncio
import copy
import logging
import importlib
import pathlib
from langgraph.graph import StateGraph, END
from .state import TurnContext
from .rules_agent import rules_agent_node
from .dm_agent import dm_agent_node
from .dice_node import dice_node
from .npc_agent import npc_agent_node
from .world_agent import world_agent_node
from .narrator_agent import narrator_agent_node
from .style_agent import style_agent_node
from .var_agent import var_agent_node
from .chronicler_agent import chronicler_agent_node, should_consolidate
from .agent_node import inject_registered_nodes

_log = logging.getLogger(__name__)


# ── 路由函数 ──────────────────────────────────────────────────────────────────

def _route_after_rules(ctx: TurnContext) -> str:
    """规则校验后路由：block/hard_block → END，否则进入 dm_gate。"""
    return "end" if ctx.rules_verdict in ("block", "hard_block") else "dm_gate"


def _route_after_dm(ctx: TurnContext) -> str:
    """
    DM 阶段后的路由决策：
    - reject  → 直接 END（节省所有后续 LLM 调用，兼容旧版 block）
    - needs_roll → dice 节点
    - modify  → parallel_nw（DM 改写行动后继续叙事，ctx.modified_action 已填充）
    - pass    → parallel_nw（兼容旧版 allow）
    """
    if ctx.dm_verdict in ("reject", "block"):
        return "end"
    if ctx.dm_verdict == "needs_roll":
        return "dice"
    # pass / allow / modify 都继续叙事
    return "parallel_nw"


# ── 并行 NPC + World 节点 ─────────────────────────────────────────────────────

async def parallel_npc_world_node(ctx: TurnContext) -> TurnContext:
    """
    并行运行 NPC 和 World Agent，合并结果到 ctx。
    各自收到 ctx 的深拷贝，互不干扰；任一失败时静默降级，主链路不中断。
    """
    ctx_for_npc = copy.deepcopy(ctx)
    ctx_for_world = copy.deepcopy(ctx)

    npc_result, world_result = await asyncio.gather(
        npc_agent_node(ctx_for_npc),
        world_agent_node(ctx_for_world),
        return_exceptions=True,
    )

    if isinstance(npc_result, Exception):
        _log.warning("parallel npc_agent failed: %s", npc_result)
    else:
        ctx.npc_reactions = npc_result.npc_reactions

    if isinstance(world_result, Exception):
        _log.warning("parallel world_agent failed: %s", world_result)
    else:
        ctx.world_events = world_result.world_events

    return ctx


# ── Chronicler 包装节点 ───────────────────────────────────────────────────────

async def chronicler_wrapper(ctx: TurnContext) -> TurnContext:
    """
    按需执行 ChroniclerAgent：
    - should_consolidate 为 True 时执行章节固化并触发 on_chapter_end Hook
    - 否则直接透传 ctx 至 END
    """
    from .agent_span import agent_span
    async with agent_span(ctx, "chronicler"):
        if await should_consolidate(ctx.session_id):
            result = await chronicler_agent_node(ctx)
            # 触发 on_chapter_end Hook
            try:
                from ..hooks import hook_manager, HookEvent
                await hook_manager.fire(HookEvent.on_chapter_end, {
                    "session_id": ctx.session_id,
                    "chapter_id": getattr(result, "chapter_id", ""),
                    "turn_index": getattr(result, "turn_index", 0),
                })
            except Exception as e:
                _log.warning("[chronicler] on_chapter_end hook failed: %s", e)
            return result
        return ctx
    return ctx


# ── 行动选项节点 ──────────────────────────────────────────────────────────────

async def options_node(ctx: TurnContext) -> TurnContext:
    """
    回合结束后（play 模式）自动生成行动选项 Part。
    只有当叙事正文非空且 dm_verdict != 'block' 时才执行，避免重复或无意义触发。
    """
    if ctx.mode != "play":
        return ctx
    if ctx.dm_verdict in ("block", "reject") or ctx.rules_verdict in ("block", "hard_block"):
        return ctx
    if not ctx.narrative_text:
        return ctx

    try:
        from ..tools.builtin_tools import _generate_action_options
        context_snippet = (ctx.narrative_text or "")[:300]
        await _generate_action_options(
            session_id=ctx.session_id,
            context=context_snippet,
            count=3,
            _msg_id=ctx.message_id or "",
        )
    except Exception as e:
        _log.debug("[options_node] generate_action_options skipped: %s", e)

    return ctx


# ── 图构建 ────────────────────────────────────────────────────────────────────

def _discover_extension_agents() -> None:
    """
    扫描 extensions/*/agents.py，自动导入以触发扩展节点注册。
    失败时静默降级，不影响主图构建。
    """
    ext_dir = pathlib.Path(__file__).parent.parent / "extensions"
    if not ext_dir.exists():
        return
    for agents_py in ext_dir.glob("*/agents.py"):
        pkg_name = agents_py.parent.name
        module_path = f"backend.extensions.{pkg_name}.agents"
        try:
            importlib.import_module(module_path)
            _log.info("[AgentNode] discovered extension agents: %s", module_path)
        except ImportError:
            # 相对导入 fallback
            try:
                importlib.import_module(f".extensions.{pkg_name}.agents", package="backend")
            except Exception as e2:
                _log.debug("[AgentNode] extension agents import skipped (%s): %s", pkg_name, e2)
        except Exception as e:
            _log.warning("[AgentNode] extension agents load failed (%s): %s", pkg_name, e)


def build_graph():
    """构建并编译 LangGraph 图（含扩展节点注入）。"""
    # 发现并导入所有扩展 agents.py（触发 register_node 调用）
    _discover_extension_agents()

    builder = StateGraph(TurnContext)

    builder.add_node("rules", rules_agent_node)
    builder.add_node("dm_gate", dm_agent_node)
    builder.add_node("dice", dice_node)
    builder.add_node("parallel_nw", parallel_npc_world_node)
    builder.add_node("narrator", narrator_agent_node)
    builder.add_node("style", style_agent_node)
    builder.add_node("var", var_agent_node)
    builder.add_node("chronicler", chronicler_wrapper)
    builder.add_node("options", options_node)

    builder.set_entry_point("rules")

    # rules 后：block → END，pass → dm_gate
    builder.add_conditional_edges(
        "rules",
        _route_after_rules,
        {
            "end": END,
            "dm_gate": "dm_gate",
        }
    )

    # dm_gate 后：reject/block → END，needs_roll → dice，pass/modify/allow → parallel_nw
    builder.add_conditional_edges(
        "dm_gate",
        _route_after_dm,
        {
            "end":         END,
            "dice":        "dice",
            "parallel_nw": "parallel_nw",
        }
    )

    # dice 完成后汇入 parallel_nw
    builder.add_edge("dice", "parallel_nw")

    # 主链路（先构建 edge_map，注入扩展节点后再统一 add_edge，避免重复边冲突）
    main_edge_map = {
        "parallel_nw": "narrator",
        "narrator":    "style",
        "style":       "var",
        "var":         "chronicler",
        "chronicler":  "options",
    }

    # 先注入扩展节点（允许修改 edge_map），再统一添加主链路边
    inject_registered_nodes(builder, main_edge_map)

    for src, dst in main_edge_map.items():
        builder.add_edge(src, dst)
    builder.add_edge("options", END)

    return builder.compile()


# 全局图实例（懒加载）
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
