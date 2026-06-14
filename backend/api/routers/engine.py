"""
引擎 & 工具路由：骰子、技能、扩展、Agent Profile、工具注册表、提示词片段。
对应设计文档 11-api-design.md §6
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from ...db import get_db, PartType
from ...bus import bus
from ...engine import RollRequest, DiceRollResult, compute_roll_request, log_roll

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 骰子引擎 ──────────────────────────────────────────────────────────────────

@router.post("/engine/roll")
async def roll_dice(req: RollRequest) -> DiceRollResult:
    """独立骰子接口。确定性计算，结果不可被 LLM 更改。"""
    import uuid
    from datetime import datetime
    from ...bus import BusEvent, EventType

    result = compute_roll_request(req)
    log_roll(result, req.session_id or "", req.message_id or "")

    if req.session_id:
        now = datetime.now().timestamp()
        dice_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                "INSERT INTO dice_log (id, session_id, message_id, pool, threshold, rolls, net, verdict, attribute, skill, reason, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dice_id, req.session_id, req.message_id or "",
                 result.pool, result.threshold,
                 json.dumps(result.rolls),
                 result.net, result.verdict,
                 result.attribute, result.skill, result.reason,
                 json.dumps(result.model_dump(), ensure_ascii=False), now)
            )
            await db.commit()
        dice_part_id = str(uuid.uuid4())
        dice_content = result.model_dump()
        dice_msg_id = req.message_id if hasattr(req, "message_id") and req.message_id else ""
        await bus.publish_part_created(
            req.session_id, dice_part_id, PartType.DICE_ROLL, dice_msg_id, "engine"
        )
        await bus.publish_part_done(req.session_id, dice_part_id, dice_content)

    return result


# ── 战斗引擎 ──────────────────────────────────────────────────────────────────

@router.post("/engine/combat")
async def combat_action(req: dict):
    """
    战斗动作接口：对会话角色卡施加伤害 / 治疗，持久化并返回结果 + 部位状态。

    body:
      session_id: str（必填）
      action: "damage" | "heal"（默认 damage）
      amount: int（伤害/治疗量）
      part: str（受击部位，默认 torso）
      damage_type: str（physical/qi/magic/tech，默认 physical）
      attacker_tier: int（默认 1）
      is_critical: bool | None
      bypass_armor: bool（默认 False）
    """
    from datetime import datetime
    from ...engine.combat import CombatEngine

    session_id = req.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id is required")
    action = req.get("action", "damage")
    amount = int(req.get("amount", 0))
    part = req.get("part", "torso")

    async with get_db() as db:
        row = await (await db.execute(
            "SELECT data_json FROM character_cards WHERE session_id=? ORDER BY updated_at DESC LIMIT 1",
            (session_id,)
        )).fetchone()
        if not row:
            raise HTTPException(404, "该会话尚无角色卡")
        char_data = json.loads(row["data_json"] or "{}")

        if action == "heal":
            result = CombatEngine.apply_heal(char_data, amount, part=part)
        else:
            result = CombatEngine.apply_damage(
                char_data, amount,
                part=part,
                damage_type=req.get("damage_type", "physical"),
                is_critical=req.get("is_critical"),
                attacker_tier=int(req.get("attacker_tier", 1)),
                bypass_armor=bool(req.get("bypass_armor", False)),
            )

        now = datetime.now().timestamp()
        await db.execute(
            "UPDATE character_cards SET data_json=?, updated_at=? WHERE session_id=?",
            (json.dumps(char_data, ensure_ascii=False), now, session_id)
        )
        await db.commit()

    from dataclasses import asdict
    parts_status = char_data.get("attributes", {}).get("hp", {}).get("parts", {})
    return {
        "ok": True,
        "action": action,
        "result": asdict(result),
        "overall_hp_ratio": CombatEngine.get_overall_hp_ratio(char_data),
        "parts": parts_status,
    }


# ── 经济系统 ──────────────────────────────────────────────────────────────────

_ECONOMY_CATALOGS: dict[str, dict] = {
    # plugin_key → {pools_file, shop_file, currency}
    "infinite_arsenal": {"pools": "pool-catalog.json", "shop": None, "currency": "crossover_points"},
    "crossover":        {"pools": None, "shop": "shop-catalog.json", "currency": "crossover_points"},
}


def _load_extension_json(plugin: str, filename: str) -> dict | list | None:
    """读取 backend/extensions/{plugin}/data/{filename}。失败返回 None。"""
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # → backend/
    path = os.path.join(base, "extensions", plugin, "data", filename)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[economy] 读取 %s 失败: %s", path, e)
        return None


@router.get("/engine/economy/{session_id}")
async def get_economy(session_id: str):
    """
    返回会话经济状态：货币余额 / 徽章 + 按 plugin_key 对应的卡池/商城目录。
    """
    async with get_db() as db:
        sess = await (await db.execute(
            "SELECT plugin_key FROM sessions WHERE id=?", (session_id,)
        )).fetchone()
        plugin_key = sess["plugin_key"] if sess else "crossover"
        char_row = await (await db.execute(
            "SELECT data_json, points FROM character_cards WHERE session_id=? "
            "ORDER BY updated_at DESC LIMIT 1", (session_id,)
        )).fetchone()

    meta: dict = {}
    if char_row:
        try:
            meta = json.loads(char_row["data_json"] or "{}").get("meta", {}) or {}
        except Exception:
            meta = {}

    cat_cfg = _ECONOMY_CATALOGS.get(plugin_key, {})
    currency = cat_cfg.get("currency", "points")
    balance = int(meta.get(currency, meta.get("points", char_row["points"] if char_row else 0) or 0))
    badges = meta.get("badges", meta.get("medals", []))

    pools = _load_extension_json(plugin_key, cat_cfg["pools"]) if cat_cfg.get("pools") else None
    shop = _load_extension_json(plugin_key, cat_cfg["shop"]) if cat_cfg.get("shop") else None

    return {
        "session_id": session_id,
        "plugin_key": plugin_key,
        "currency": currency,
        "balance": balance,
        "badges": badges if isinstance(badges, list) else [],
        "battle_points": int(meta.get("battle_points", 0) or 0),
        "pools": (pools or {}).get("pools", []) if isinstance(pools, dict) else [],
        "shop": shop if shop is not None else [],
        "has_economy": bool(cat_cfg),
    }


# ── 技能 / 扩展 / 规则 ────────────────────────────────────────────────────────

@router.get("/engine/skills")
async def list_skills():
    """列出所有已注册的 SKILL.md 技能。"""
    from ...tools.skill_loader import skill_registry
    return skill_registry.list_skills()


@router.get("/engine/extensions")
async def list_extensions(ext_type: str = "plugin"):
    """列出已加载的扩展。ext_type=plugin 只返回行为包；ext_type=all 返回全部。"""
    from ...extensions import plugin_registry
    plugins = plugin_registry.list_plugins()
    if ext_type != "all":
        plugins = [p for p in plugins if p.get("ext_type", "plugin") == ext_type]
    return {"extensions": plugins, "count": len(plugins)}


@router.get("/engine/rules")
async def list_extension_rules():
    """列出所有已加载的扩展规则（Track C RuleRegistry）。"""
    try:
        from ...extensions.rules_loader import rule_registry
        return {"rules": rule_registry.list_rules(), "count": len(rule_registry.list_rules())}
    except ImportError as e:
        logger.warning("[engine] rules_loader 未初始化，规则列表降级为空: %s", e)
        return {"rules": [], "count": 0, "note": "rules_loader not initialized"}


@router.post("/engine/rules/{rule_id}/activate")
async def activate_rule(rule_id: str, enabled: bool = True):
    """运行时激活/停用指定规则。"""
    try:
        from ...extensions.rules_loader import rule_registry
        ok = rule_registry.activate(rule_id, enabled)
        if ok:
            return {"rule_id": rule_id, "enabled": enabled}
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    except ImportError:
        raise HTTPException(status_code=503, detail="rules_loader not available")


# ── 提示词片段 ────────────────────────────────────────────────────────────────

@router.get("/prompts/fragments")
async def list_prompt_fragments():
    """列出所有已注册的提示词片段（调试用）。"""
    from ...prompts import registry
    return {"fragments": registry.list_fragments(), "count": len(registry.list_fragments())}


# ── Agent Profile ─────────────────────────────────────────────────────────────

@router.get("/agents/profiles")
async def list_profiles():
    """列出所有已注册的 AgentProfile。"""
    from ...agents.permission import profile_registry
    return {"profiles": profile_registry.list_profiles(), "count": len(profile_registry.list_profiles())}


@router.get("/agents/profiles/{profile_name}/check")
async def check_tool_permission(profile_name: str, tool: str):
    """检查指定 Profile 对某工具的权限（tool 作为 query 参数）。"""
    from ...agents.permission import profile_registry, PermissionAction
    action = profile_registry.check_tool(profile_name, tool)
    return {"profile": profile_name, "tool": tool, "action": action.value}


# ── 工具注册表 ────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools(tag: Optional[str] = None):
    """列出所有已注册的工具，可按 tag 过滤。"""
    from ...tools import tool_registry
    tags = [tag] if tag else None
    tools = tool_registry.list_tools(tags)
    return {"tools": tools, "count": len(tools)}


@router.post("/tools/{tool_name}")
async def execute_tool(tool_name: str, body: dict, session_id: Optional[str] = None):
    """直接执行工具（调试/测试用）。"""
    from ...tools import tool_registry
    args = {**body}
    if session_id:
        args["session_id"] = session_id
    result = await tool_registry.execute(tool_name, args)
    return result
