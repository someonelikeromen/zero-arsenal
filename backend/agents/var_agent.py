"""
VarAgent — 执行 TavernCommand 变量结算，更新 DB 中的角色状态。
依赖 NarratorAgent P4 提取的 state_patches（tavern_commands）。
"""
from __future__ import annotations
import uuid
import json
import logging
from datetime import datetime
from .state import TurnContext
from ..bus import bus
from ..db.schema import PartType

logger = logging.getLogger(__name__)


async def var_agent_node(ctx: TurnContext) -> TurnContext:
    """
    LangGraph 节点函数 — 变量结算与 DB 写回。
    设计要求：结算失败不影响叙事管线，无论任何异常均返回 ctx。
    """
    try:
        from .agent_span import agent_span
        async with agent_span(ctx, "var"):
            return await _var_impl(ctx)
    except Exception as e:
        # 最外层兜底：确保 var_agent 任何错误不中止管线
        logger.warning(f"[var_agent] unhandled exception (pipeline continues): {e}")
        ctx.var_errors = getattr(ctx, "var_errors", []) + [f"var_agent crash: {e}"]
    return ctx


async def _var_impl(ctx: TurnContext) -> TurnContext:
    # 优先读 tavern_commands（若已定义），否则回落到 state_patches
    commands: list = getattr(ctx, "tavern_commands", None) or ctx.state_patches or []

    if not commands:
        return ctx

    # conf_b04：触发 before_var_update（可由扩展修改/校验 commands）
    try:
        from ..hooks import hook_manager, HookEvent
        _bvu = await hook_manager.fire(HookEvent.before_var_update, {
            "session_id": ctx.session_id,
            "agent_name": "var",
            "commands": commands,
        })
        if isinstance(_bvu.get("commands"), list):
            commands = _bvu["commands"]
    except Exception as _e:
        logger.debug("[var_agent] before_var_update hook failed: %s", _e)

    errors: list = []

    try:
        current_state = await _load_char_state(ctx)
    except Exception as e:
        logger.warning(f"[var_agent] load char state failed: {e}")
        ctx.var_errors = [str(e)]
        return ctx

    try:
        from ..engine.vm import execute_state_change
        # vm_code 来自 ctx.vm_code（若 LLM 生成了复杂状态变更脚本）
        vm_code: str = getattr(ctx, "vm_code", "") or ""
        use_vm: bool = bool(vm_code.strip())
        updated_state = execute_state_change(
            patches=commands,
            state=current_state,
            vm_code=vm_code,
            use_vm=use_vm,
        )
    except Exception as e:
        logger.warning(f"[var_agent] apply_patches failed: {e}")
        ctx.var_errors = [str(e)]
        return ctx

    # 写角色快照（回滚保护点，在本轮 patch 应用前保存旧状态）
    try:
        from ..db import get_db
        snap_id = str(uuid.uuid4())
        now_snap = datetime.now().timestamp()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO character_snapshots "
                "(id, session_id, message_id, snapshot_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (snap_id, ctx.session_id, ctx.message_id,
                 json.dumps(current_state, ensure_ascii=False), now_snap)
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"[var_agent] snapshot write skipped: {e}")

    try:
        await _save_char_state(ctx, updated_state)
    except Exception as e:
        logger.warning(f"[var_agent] save char state failed: {e}")
        errors.append(str(e))

    # 构造变化对比并发布 state_patch Part（先 created 再 done 保证前端 addPart）
    try:
        changes = _diff_states(current_state, updated_state, commands)
        if changes:
            part_id = str(uuid.uuid4())
            now = datetime.now().timestamp()
            content = {"patches": commands, "changes": changes}
            await _write_part(ctx, part_id, PartType.STATE_PATCH, content, now)
            await bus.publish_part_created(
                ctx.session_id, part_id, PartType.STATE_PATCH, ctx.message_id, "var"
            )
            await bus.publish_part_done(ctx.session_id, part_id, content)
    except Exception as e:
        logger.warning(f"[var_agent] publish state_patch failed: {e}")
        errors.append(str(e))

    ctx.var_updates = commands
    ctx.var_errors = errors

    # conf_b04：触发 after_var_update（扩展可据变更做副作用结算，如经济/损耗）
    try:
        from ..hooks import hook_manager, HookEvent
        await hook_manager.fire(HookEvent.after_var_update, {
            "session_id": ctx.session_id,
            "agent_name": "var",
            "commands": commands,
            "updated_state": updated_state,
            "errors": errors,
        })
    except Exception as _e:
        logger.debug("[var_agent] after_var_update hook failed: %s", _e)

    # 异步记忆提取：把本轮叙事加入提取队列
    if ctx.narrative_text and ctx.session_id:
        try:
            from ..memory.adapter import memory_adapter
            from ..db import get_db
            async with get_db() as db:
                row = await db.execute(
                    "SELECT id FROM chapters WHERE session_id=? AND is_consolidated=0 "
                    "ORDER BY created_at DESC LIMIT 1",
                    (ctx.session_id,)
                )
                chapter = await row.fetchone()
                chapter_id = chapter["id"] if chapter else ""

            messages = [
                {"role": "user", "content": ctx.user_input},
                {"role": "assistant", "content": ctx.polished_narrative or ctx.narrative_text},
            ]
            memory_adapter.enqueue_extraction(
                session_id=ctx.session_id,
                world_plugin=ctx.world_plugin,
                chapter_id=chapter_id,
                messages=messages,
            )
        except Exception as _enq_err:
            logger.debug(f"enqueue_extraction failed: {_enq_err}")

    # 清理 runtime Prompt 层（回合结束，释放本轮动态片段）
    try:
        from ..prompts.registry import registry as prompt_registry
        prompt_registry.clear_runtime(ctx.session_id)
    except Exception:
        pass

    return ctx


def _diff_states(old: dict, new: dict, commands: list) -> list[dict]:
    """生成简洁的 old→new 变化列表，仅包含实际有变动的 key。"""
    diffs = []
    for cmd in commands:
        key_path = cmd.get("key", "")
        old_val = _get_nested(old, key_path)
        new_val = _get_nested(new, key_path)
        if old_val != new_val:
            diffs.append({"key": key_path, "old": old_val, "new": new_val})
    return diffs


def _get_nested(state: dict, key_path: str):
    """按 dot-path 取值，找不到返回 None。"""
    keys = key_path.split(".")
    target = state
    for k in keys:
        if not isinstance(target, dict) or k not in target:
            return None
        target = target[k]
    return target


async def _load_char_state(ctx: TurnContext) -> dict:
    from ..db import get_db
    async with get_db() as db:
        row = await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=?",
            (ctx.session_id,)
        )
        char = await row.fetchone()
    if char and char["data_json"]:
        return json.loads(char["data_json"])
    return {}


async def _save_char_state(ctx: TurnContext, state: dict) -> None:
    from ..db import get_db
    now = datetime.now().timestamp()
    async with get_db() as db:
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
            (json.dumps(state, ensure_ascii=False), now, ctx.session_id)
        )
        await db.commit()


async def _write_part(ctx: TurnContext, part_id: str, part_type: str, content: dict, now: float) -> None:
    from ..db import get_db
    async with get_db() as db:
        await db.execute(
            "INSERT INTO message_parts "
            "(id, message_id, session_id, type, content, status, agent, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'done', 'var', ?, ?)",
            (part_id, ctx.message_id, ctx.session_id,
             part_type, json.dumps(content, ensure_ascii=False), now, now)
        )
        await db.commit()
