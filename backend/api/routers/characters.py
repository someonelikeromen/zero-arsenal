"""
全局人物模板管理路由。
- CRUD: /api/characters
- 生成: /api/characters/generate/questions (SSE) + /api/characters/generate (SSE)
"""
from __future__ import annotations
import json
import time
import uuid
import logging
from typing import Optional, AsyncIterator

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from ...db import get_db
from ...agents.llm import llm_stream
from ...db.character_v4 import (
    create_default_character,
    migrate_v3_to_v4,
    validate_character,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_to_v4(data: dict, plugin_key: str, source: str = "") -> dict:
    """
    将任意角色卡数据归一化到 v4 并做 jsonschema 校验（R-M14 / D7）。
    - 非 v4（缺 schema_version 或 < 4）先 migrate_v3_to_v4；
    - 校验失败仅告警（保留归一化后的数据，不静默丢弃用户输入）。
    供 characters 路由所有写入入口共用。
    """
    if not isinstance(data, dict) or not data:
        return create_default_character("新角色", plugin_key)
    out = data
    try:
        sv = str(out.get("schema_version") or out.get("meta", {}).get("schema_version") or "0")
        if sv < "4":
            out = migrate_v3_to_v4(out)
        valid, errs = validate_character(out)
        if not valid:
            logger.warning("[characters%s] 角色卡 v4 校验未通过（保留数据）: %s",
                           f":{source}" if source else "", errs[:5])
    except Exception as e:
        logger.warning("[characters%s] 角色卡 v4 归一化异常: %s",
                       f":{source}" if source else "", e)
    return out


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreateCharacterTemplateRequest(BaseModel):
    name: str
    plugin_key: str = "crossover"
    data_json: dict = {}


class UpdateCharacterTemplateRequest(BaseModel):
    name: Optional[str] = None
    plugin_key: Optional[str] = None
    data_json: Optional[dict] = None


class GenerateQuestionsRequest(BaseModel):
    plugin_key: str = "crossover"
    char_type: str = "original"


class GenerateCharacterRequest(BaseModel):
    mode: str = "quick"           # quick | quiz | background
    plugin_key: str = "crossover"
    name: str = ""
    gender: str = ""
    char_type: str = "original"   # original | transmigrator
    traversal_method: str = ""    # 穿越方式
    background_text: str = ""     # background 模式用
    answers: list[dict] = []      # quiz 模式用 [{question, answer}]
    # ── Phase 2A 高度自定义入口 ──────────────────────────────────────────────
    core_traits: str = ""         # 用户自由描述的 2-3 个关键词
    ability_tendency: str = ""    # combat | tech | social | mixed —— 影响 capability_cap
    canon_source: str = ""        # 原作角色名或资料 URL（提供生成上下文）
    first_message: str = ""       # 角色开场独白（直接带入档案，不交给 LLM 改写）


# ── 生成 Prompts ──────────────────────────────────────────────────────────────

_QUESTIONS_SYSTEM = """你是一个 TRPG 角色创建助手，负责生成用于推断角色心理和人格的情境问卷。
要求：
1. 生成5道情境题，每道题有3个选项（A/B/C）
2. 题目无道德正确答案，考察应对压力、边界感、情绪、自我认知等
3. 输出 JSON 数组：[{"id":"q1","question":"...","options":{"A":"...","B":"...","C":"..."}},...}]
只输出 JSON，不要其他文字。"""

_CHARACTER_SYSTEM = """你是一个 TRPG 角色建档专家。根据用户提供的信息，生成一份完整的角色 v4 JSON。

铁律（必须遵守）：
- 缺陷不能是变相优点（如"太完美"不算缺陷）
- 创伤不能写成变强理由
- 心理推断要具体，不美化
- 初始道具只填背景明确提到的，不额外添加
- 属性值范围 1-10，初始角色一般 3-6

v4 JSON 格式：
{{
  "name": "角色名",
  "plugin_key": "plugin_key值",
  "attributes": {{"strength":4,"dexterity":4,"intelligence":5,"will":4,"empathy":4}},
  "max_hp": 40,
  "current_hp": 40,
  "skills": {{"基础搏击":2,"社交":3}},
  "inventory": [{{"name":"道具名","type":"equipment","quantity":1,"description":"描述"}}],
  "mental_state": {{"stress":0,"morale":60,"trauma_level":0}},
  "relationships": {{}},
  "economy": {{"points":100,"currency":0}},
  "psyche_model": {{
    "core_values": ["核心价值观1","核心价值观2"],
    "knowledge_scope": {{"knows": ["已知事项"], "blind_spots": ["盲区/不知道的事"]}},
    "capability_cap": {{"combat":"战斗能力上限描述","tech":"技术能力描述","social":"社交能力描述","special_sense":"特殊感知或null"}},
    "behavior_patterns": "1-2句典型行为模式",
    "emotional_triggers": "什么情况下会脱离常规反应"
  }},
  "meta": {{"background":"背景简述","personality":"性格描述","flaws":["缺陷1"]}}
}}

psyche_model 要求：
- core_values 至少 2 条，具体且能驱动行为
- knowledge_scope 区分角色「知道什么」和「不知道什么」，用于防止全知叙事
- capability_cap 必须反映用户指定的能力倾向，不能各项平均堆高
只输出 JSON，不要其他文字。"""


_ABILITY_TENDENCY_HINT = {
    "combat": "能力倾向：战斗型 —— capability_cap.combat 应明显高于其他，skills 偏战斗。",
    "tech": "能力倾向：技术型 —— capability_cap.tech 应明显突出，skills 偏知识/工程。",
    "social": "能力倾向：社交型 —— capability_cap.social 应明显突出，skills 偏交涉/洞察。",
    "mixed": "能力倾向：混合型 —— 各项能力较均衡但仍有 1 项略高。",
}


async def _fetch_canon_context(canon_source: str) -> str:
    """
    若 canon_source 是 URL，则用 web_scraper 抓取作为原作上下文；
    否则作为原作角色名直接注入（依赖 LLM 自身的原作知识）。
    失败时静默返回空，不阻断生成。
    """
    src = (canon_source or "").strip()
    if not src:
        return ""
    if src.startswith("http://") or src.startswith("https://"):
        try:
            from ...utils.web_scraper import fetch_url_text
            raw_text, _engine = await fetch_url_text(src)
            if raw_text:
                return f"\n[原作资料（节选）]\n{raw_text[:3000]}\n"
        except Exception as e:
            logger.warning("[characters] canon_source fetch failed: %s", e)
        return ""
    return f"\n原作角色：{src}（请基于原作设定生成，但属性仍按本系统量级 1-10 标定）\n"


async def _build_character_prompt(req: GenerateCharacterRequest) -> list[dict]:
    """根据生成模式构建 prompt（异步：可能联网抓取原作上下文）。"""
    user_content = f"世界观：{req.plugin_key}\n角色名：{req.name or '未命名'}\n性别：{req.gender or '不限'}\n"
    if req.char_type == "transmigrator":
        user_content += f"角色类型：穿越者（{req.traversal_method or '意外穿越'}）\n"
    if req.core_traits.strip():
        user_content += f"核心特质关键词：{req.core_traits.strip()}\n"
    if req.ability_tendency.strip():
        user_content += _ABILITY_TENDENCY_HINT.get(req.ability_tendency.strip(), "") + "\n"
    canon_ctx = await _fetch_canon_context(req.canon_source)
    if canon_ctx:
        user_content += canon_ctx

    if req.mode == "background" and req.background_text:
        user_content += f"\n背景描述：\n{req.background_text}"
    elif req.mode == "quiz" and req.answers:
        qa_text = "\n".join([f"问题：{a.get('question','')}\n回答：{a.get('answer','')}" for a in req.answers])
        user_content += f"\n问卷作答：\n{qa_text}"
    else:
        user_content += "\n请生成一个有趣且有深度的角色。"

    system = _CHARACTER_SYSTEM.replace("{{", "{").replace("}}", "}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user_content}]


# ── CRUD 路由 ─────────────────────────────────────────────────────────────────

@router.get("/characters")
async def list_character_templates(plugin_key: Optional[str] = None):
    async with get_db() as db:
        if plugin_key:
            rows = await (await db.execute(
                "SELECT id, name, plugin_key, schema_version, created_at, updated_at"
                " FROM character_templates WHERE plugin_key=? ORDER BY updated_at DESC",
                (plugin_key,)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT id, name, plugin_key, schema_version, created_at, updated_at"
                " FROM character_templates ORDER BY updated_at DESC"
            )).fetchall()
    return {"characters": [dict(r) for r in rows]}


@router.get("/characters/{cid}")
async def get_character_template(cid: str):
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT * FROM character_templates WHERE id=?", (cid,)
        )).fetchone()
    if not row:
        raise HTTPException(404, "Character template not found")
    r = dict(row)
    r["data_json"] = json.loads(r.get("data_json") or "{}")
    return r


@router.post("/characters")
async def create_character_template(req: CreateCharacterTemplateRequest):
    cid = str(uuid.uuid4())
    now = time.time()
    raw_data = _normalize_to_v4(req.data_json or {}, req.plugin_key, source="create")
    async with get_db() as db:
        await db.execute(
            "INSERT INTO character_templates (id, name, plugin_key, data_json, schema_version, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, req.name, req.plugin_key, json.dumps(raw_data, ensure_ascii=False), "4", now, now)
        )
        await db.commit()
    return {"character_id": cid, "name": req.name}


@router.patch("/characters/{cid}")
async def update_character_template(cid: str, req: UpdateCharacterTemplateRequest):
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM character_templates WHERE id=?", (cid,))).fetchone()
        if not row:
            raise HTTPException(404, "Character template not found")
        updates, vals = [], []
        if req.name is not None: updates.append("name=?"); vals.append(req.name)
        if req.plugin_key is not None: updates.append("plugin_key=?"); vals.append(req.plugin_key)
        if req.data_json is not None:
            norm = _normalize_to_v4(req.data_json, req.plugin_key or "crossover", source="update")
            updates.append("data_json=?")
            vals.append(json.dumps(norm, ensure_ascii=False))
        if updates:
            vals += [time.time(), cid]
            await db.execute(f"UPDATE character_templates SET {','.join(updates)},updated_at=? WHERE id=?", vals)
            await db.commit()
    return {"ok": True}


@router.delete("/characters/{cid}")
async def delete_character_template(cid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM character_templates WHERE id=?", (cid,))
        await db.commit()
    return {"ok": True}


# ── PNG 角色卡导入/导出（SillyTavern / Chub 兼容）─────────────────────────────

@router.post("/characters/import-png")
async def import_character_png(file: UploadFile = File(...), plugin_key: str = "crossover"):
    """上传 PNG 角色卡 → 解析 chara chunk → 创建人物模板。"""
    from ...utils.png_card import decode_card
    raw = await file.read()
    try:
        payload = decode_card(raw)
    except Exception as e:
        raise HTTPException(400, f"PNG 角色卡解析失败: {e}")

    name = str(payload.get("name") or payload.get("char_name") or "导入角色")
    cid = str(uuid.uuid4())
    now = time.time()
    payload_wp = payload.get("plugin_key", plugin_key)
    payload = _normalize_to_v4(payload, payload_wp, source="import-png")
    async with get_db() as db:
        await db.execute(
            "INSERT INTO character_templates (id, name, plugin_key, data_json, schema_version, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, name, payload.get("plugin_key", plugin_key),
             json.dumps(payload, ensure_ascii=False), "4", now, now)
        )
        await db.commit()
    return {"character_id": cid, "name": name}


@router.get("/characters/{cid}/export-png")
async def export_character_png(cid: str):
    """导出人物模板为 PNG 角色卡（data_json 嵌入 chara chunk）。"""
    from ...utils.png_card import encode_card
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT name, data_json FROM character_templates WHERE id=?", (cid,)
        )).fetchone()
    if not row:
        raise HTTPException(404, "Character template not found")
    r = dict(row)
    try:
        data = json.loads(r.get("data_json") or "{}")
    except Exception:
        data = {}
    png = encode_card(None, data)
    safe_name = (r.get("name") or "character").replace("/", "_")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.png"'},
    )


# ── SSE 生成端点 ──────────────────────────────────────────────────────────────

@router.post("/characters/generate/questions")
async def generate_questions(req: GenerateQuestionsRequest):
    """LLM → SSE 返回 5 道问卷题目。"""
    messages = [
        {"role": "system", "content": _QUESTIONS_SYSTEM},
        {"role": "user", "content": f"世界观：{req.plugin_key}，角色类型：{req.char_type}，生成问卷"},
    ]

    async def _stream() -> AsyncIterator[bytes]:
        full_text = ""
        try:
            yield f"data: {json.dumps({'type': 'start'})}\n\n".encode()

            async def on_delta(d: str) -> None:
                nonlocal full_text
                full_text += d

            await llm_stream(messages, on_delta=on_delta, max_tokens=1500)

            try:
                s = full_text.find("[")
                e = full_text.rfind("]") + 1
                questions = json.loads(full_text[s:e]) if s >= 0 else []
                if s < 0:
                    logger.warning("[characters] 引导问题 LLM 输出未含 JSON 数组，降级 questions=[]（text 长度=%d）", len(full_text))
            except Exception as e:
                logger.warning("[characters] 引导问题 JSON 解析失败，降级 questions=[]: %s", e)
                questions = []

            yield f"data: {json.dumps({'type': 'done', 'questions': questions}, ensure_ascii=False)}\n\n".encode()
        except Exception as ex:
            yield f"data: {json.dumps({'type': 'error', 'message': str(ex)})}\n\n".encode()

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/characters/generate")
async def generate_character(req: GenerateCharacterRequest):
    """LLM → SSE 流式返回 v4 角色 JSON。"""

    async def _stream() -> AsyncIterator[bytes]:
        full_text = ""
        try:
            yield f"data: {json.dumps({'type': 'start'})}\n\n".encode()

            # 异步构建 prompt（可能联网抓取原作上下文）
            messages = await _build_character_prompt(req)

            async def on_delta(d: str) -> None:
                nonlocal full_text
                full_text += d

            await llm_stream(messages, on_delta=on_delta, max_tokens=2200)

            # Parse final character JSON
            try:
                s = full_text.find("{")
                e = full_text.rfind("}") + 1
                char_data = json.loads(full_text[s:e]) if s >= 0 else {}
                if not char_data:
                    logger.warning("[characters] 角色生成 LLM 输出未含有效 JSON，降级默认卡（world=%s）", req.plugin_key)
                    char_data = create_default_character(req.name or "新角色", req.plugin_key)
            except Exception as e:
                logger.warning("[characters] 角色生成 JSON 解析失败，降级默认卡（world=%s）: %s", req.plugin_key, e)
                char_data = create_default_character(req.name or "新角色", req.plugin_key)

            # D7：LLM 产出归一化到 v4 并校验（失败仅告警，保留生成结果）
            char_data = _normalize_to_v4(char_data, req.plugin_key, source="generate")

            # first_message 由用户直接指定，不交给 LLM 改写
            if req.first_message.strip():
                char_data["first_message"] = req.first_message.strip()

            yield f"data: {json.dumps({'type': 'done', 'character': char_data}, ensure_ascii=False)}\n\n".encode()
        except Exception as ex:
            yield f"data: {json.dumps({'type': 'error', 'message': str(ex)})}\n\n".encode()

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
