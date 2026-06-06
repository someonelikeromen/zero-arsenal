"""
全局提示词模板管理路由。分 Agent 类别管理 system prompt，支持启用/禁用、排序、重置。
"""
from __future__ import annotations
import json
import time
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# ── 内置默认提示词 ─────────────────────────────────────────────────────────────

DEFAULT_PROMPTS = [
    {
        "agent": "dm",
        "label": "DM 核心规则",
        "content": "你是一个公正的 TRPG 地下城主（DM）。\n- 根据世界规则判断玩家行动的可行性\n- 主动抛出有趣的挑战和选择\n- 使用骰子判定结果，不轻易放水\n- 世界有自己的运转逻辑，不因玩家便利而扭曲",
        "sort_order": 0,
    },
    {
        "agent": "narrator",
        "label": "叙述者风格",
        "content": "你是故事叙述者。\n- 使用第三人称、过去时态描写\n- Show don't tell：通过感官细节而非心理解析描述\n- 短句与长句交替，节奏张弛有度\n- 禁止使用：仿佛、似乎、不知为何",
        "sort_order": 0,
    },
    {
        "agent": "npc",
        "label": "NPC 行为准则",
        "content": "扮演 NPC 时：\n- 只表达 NPC 已知的信息\n- NPC 有自己的利益、恐惧和底线\n- 不会无缘无故帮助主角\n- 对话后追加简短行为描写（眼神/动作）",
        "sort_order": 0,
    },
    {
        "agent": "world",
        "label": "世界观一致性",
        "content": "维护世界观时：\n- 当前世界插件：{{plugin_key}}\n- 技术/魔法水平与设定一致\n- 时间线不倒退（已发生的事无法撤销）\n- 关键 NPC 不随意离开或死亡",
        "sort_order": 0,
    },
    {
        "agent": "style",
        "label": "写作风格",
        "content": "整体写作要求：\n- 主角：{{character_name}}\n- 对话格式：话语在前，说话人标注在后\n- 战斗场景：具体描写动作轨迹，避免笼统\n- 禁止三连排比句式",
        "sort_order": 0,
    },
    {
        "agent": "rules",
        "label": "规则系统",
        "content": "骰子与规则：\n- 重要行动需要骰子判定\n- 失败有后果，不可撤销\n- 技能/属性影响骰池大小\n- 连续失败可触发混沌事件",
        "sort_order": 0,
    },
]


async def _ensure_defaults_exist(db) -> None:
    """若数据库无提示词条目，插入默认值。"""
    count = (await (await db.execute("SELECT COUNT(*) FROM prompt_templates")).fetchone())[0]
    if count == 0:
        now = time.time()
        for i, p in enumerate(DEFAULT_PROMPTS):
            pid = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO prompt_templates (id, agent, label, content, enabled, sort_order, created_at, updated_at)"
                " VALUES (?,?,?,?,1,?,?,?)",
                (pid, p["agent"], p["label"], p["content"], i, now, now)
            )
        await db.commit()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreatePromptRequest(BaseModel):
    agent: str
    label: str
    content: str = ""
    enabled: int = 1
    sort_order: int = 0


class UpdatePromptRequest(BaseModel):
    label: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[int] = None
    sort_order: Optional[int] = None


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("/prompts")
async def list_prompts(agent: Optional[str] = None):
    async with get_db() as db:
        await _ensure_defaults_exist(db)
        if agent:
            rows = await (await db.execute(
                "SELECT * FROM prompt_templates WHERE agent=? ORDER BY sort_order ASC, created_at ASC",
                (agent,)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT * FROM prompt_templates ORDER BY agent ASC, sort_order ASC"
            )).fetchall()
    return {"prompts": [dict(r) for r in rows]}


@router.post("/prompts")
async def create_prompt(req: CreatePromptRequest):
    pid = str(uuid.uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO prompt_templates (id, agent, label, content, enabled, sort_order, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (pid, req.agent, req.label, req.content, req.enabled, req.sort_order, now, now)
        )
        await db.commit()
    return {"prompt_id": pid, "label": req.label}


@router.patch("/prompts/{pid}")
async def update_prompt(pid: str, req: UpdatePromptRequest):
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM prompt_templates WHERE id=?", (pid,))).fetchone()
        if not row:
            raise HTTPException(404, "Prompt not found")
        updates, vals = [], []
        if req.label is not None: updates.append("label=?"); vals.append(req.label)
        if req.content is not None: updates.append("content=?"); vals.append(req.content)
        if req.enabled is not None: updates.append("enabled=?"); vals.append(req.enabled)
        if req.sort_order is not None: updates.append("sort_order=?"); vals.append(req.sort_order)
        if updates:
            vals += [time.time(), pid]
            await db.execute(f"UPDATE prompt_templates SET {','.join(updates)},updated_at=? WHERE id=?", vals)
            await db.commit()
    return {"ok": True}


@router.delete("/prompts/{pid}")
async def delete_prompt(pid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM prompt_templates WHERE id=?", (pid,))
        await db.commit()
    return {"ok": True}


@router.post("/prompts/reset")
async def reset_prompts():
    """清空所有提示词并重置为内置默认值。"""
    async with get_db() as db:
        await db.execute("DELETE FROM prompt_templates")
        await db.commit()
        now = time.time()
        for i, p in enumerate(DEFAULT_PROMPTS):
            pid = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO prompt_templates (id, agent, label, content, enabled, sort_order, created_at, updated_at)"
                " VALUES (?,?,?,?,1,?,?,?)",
                (pid, p["agent"], p["label"], p["content"], i, now, now)
            )
        await db.commit()
    return {"ok": True, "reset_count": len(DEFAULT_PROMPTS)}
