"""
全局世界模板管理路由。
- CRUD: /api/worlds (list/create/update/delete)
- 档案 CRUD: /api/worlds/{wid}/archives
- SSE 世界观提炼: fetch-lore (URL) / parse-document (文本) → 流式返回 → confirm-lore 写库
"""
from __future__ import annotations
import json
import time
import uuid
import logging
from typing import Optional, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...db import get_db
from ...agents.llm import llm_stream, llm_complete
from ...utils.web_scraper import fetch_url_text, list_rules, save_rules, load_rules

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreateWorldRequest(BaseModel):
    name: str
    world_plugin: str = "crossover"
    description: str = ""


class UpdateWorldRequest(BaseModel):
    name: Optional[str] = None
    world_plugin: Optional[str] = None
    description: Optional[str] = None


class CreateArchiveEntryRequest(BaseModel):
    title: str
    content: str = ""
    archive_type: str = "lore"
    trigger_keywords: str = ""    # 逗号分隔的 Lorebook 触发关键词


class UpdateArchiveEntryRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    archive_type: Optional[str] = None
    trigger_keywords: Optional[str] = None


class FetchLoreRequest(BaseModel):
    # 兼容单 URL（旧）与多 URL 批量（新）：二者择一
    url: Optional[str] = None
    urls: Optional[list[str]] = None


class ParseDocumentRequest(BaseModel):
    text: str


class ConfirmLoreRequest(BaseModel):
    entries: list[dict]  # [{title, content, archive_type}]


# ── 世界提炼 Prompt ───────────────────────────────────────────────────────────

_LORE_EXTRACT_SYSTEM = """你是一个世界观档案提炼助手。
从用户提供的原始文本中，提炼出适合 TRPG/小说创作的世界观条目。
每条条目包含：title（简洁标题）、content（具体内容，300字以内）、archive_type（lore/rule/setting/npc 之一）。
输出格式：JSON 数组，每个元素形如 {"title":"...","content":"...","archive_type":"..."}
只输出 JSON，不要其他文字。"""


async def _extract_lore_sse(raw_text: str) -> AsyncIterator[str]:
    """调用 LLM 提炼世界观，以 SSE 格式流式返回 delta 和最终结果。"""
    messages = [
        {"role": "system", "content": _LORE_EXTRACT_SYSTEM},
        {"role": "user", "content": f"请从以下文本提炼世界观档案条目：\n\n{raw_text[:8000]}"},
    ]
    full_text = ""
    try:
        async def on_delta(delta: str) -> None:
            nonlocal full_text
            full_text += delta

        yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"

        await llm_stream(messages, on_delta=on_delta, max_tokens=2000)

        # Parse JSON result
        try:
            start = full_text.find("[")
            end = full_text.rfind("]") + 1
            entries = json.loads(full_text[start:end]) if start >= 0 else []
            if start < 0:
                logger.warning("[worlds] 设定提炼 LLM 输出未含 JSON 数组，降级 entries=[]（text 长度=%d）", len(full_text))
        except Exception as e:
            logger.warning("[worlds] 设定提炼 JSON 解析失败，降级 entries=[]: %s", e)
            entries = []

        yield f"data: {json.dumps({'type': 'done', 'entries': entries, 'raw': full_text}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"


# ── CRUD 路由 ─────────────────────────────────────────────────────────────────

@router.get("/worlds")
async def list_worlds(world_plugin: Optional[str] = None):
    async with get_db() as db:
        if world_plugin:
            rows = await (await db.execute(
                "SELECT * FROM worlds WHERE world_plugin=? ORDER BY updated_at DESC",
                (world_plugin,)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT * FROM worlds ORDER BY updated_at DESC"
            )).fetchall()
    worlds = []
    for r in rows:
        w = dict(r)
        worlds.append(w)
    return {"worlds": worlds}


@router.post("/worlds")
async def create_world(req: CreateWorldRequest):
    wid = str(uuid.uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO worlds (id, name, world_plugin, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (wid, req.name, req.world_plugin, req.description, now, now)
        )
        await db.commit()
    return {"world_id": wid, "name": req.name}


@router.get("/worlds/{wid}")
async def get_world(wid: str):
    async with get_db() as db:
        row = await (await db.execute("SELECT * FROM worlds WHERE id=?", (wid,))).fetchone()
    if not row:
        raise HTTPException(404, "World not found")
    return dict(row)


@router.patch("/worlds/{wid}")
async def update_world(wid: str, req: UpdateWorldRequest):
    async with get_db() as db:
        row = await (await db.execute("SELECT id FROM worlds WHERE id=?", (wid,))).fetchone()
        if not row:
            raise HTTPException(404, "World not found")
        updates, vals = [], []
        if req.name is not None: updates.append("name=?"); vals.append(req.name)
        if req.world_plugin is not None: updates.append("world_plugin=?"); vals.append(req.world_plugin)
        if req.description is not None: updates.append("description=?"); vals.append(req.description)
        if updates:
            vals += [time.time(), wid]
            await db.execute(f"UPDATE worlds SET {','.join(updates)},updated_at=? WHERE id=?", vals)
            await db.commit()
    return {"ok": True}


@router.delete("/worlds/{wid}")
async def delete_world(wid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM worlds WHERE id=?", (wid,))
        await db.commit()
    return {"ok": True}


# ── 档案条目 CRUD ─────────────────────────────────────────────────────────────

@router.get("/worlds/{wid}/archives")
async def list_world_archives(wid: str):
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM world_archive_entries WHERE world_id=? ORDER BY created_at ASC",
            (wid,)
        )).fetchall()
    return {"archives": [dict(r) for r in rows]}


@router.post("/worlds/{wid}/archives")
async def create_world_archive(wid: str, req: CreateArchiveEntryRequest):
    aid = str(uuid.uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO world_archive_entries (id, world_id, title, content, archive_type, trigger_keywords, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (aid, wid, req.title, req.content, req.archive_type, req.trigger_keywords, now, now)
        )
        await db.commit()
    return {"archive_id": aid, "title": req.title}


@router.patch("/worlds/{wid}/archives/{aid}")
async def update_world_archive(wid: str, aid: str, req: UpdateArchiveEntryRequest):
    async with get_db() as db:
        updates, vals = [], []
        if req.title is not None: updates.append("title=?"); vals.append(req.title)
        if req.content is not None: updates.append("content=?"); vals.append(req.content)
        if req.archive_type is not None: updates.append("archive_type=?"); vals.append(req.archive_type)
        if req.trigger_keywords is not None: updates.append("trigger_keywords=?"); vals.append(req.trigger_keywords)
        if updates:
            vals += [time.time(), aid, wid]
            await db.execute(
                f"UPDATE world_archive_entries SET {','.join(updates)},updated_at=? WHERE id=? AND world_id=?", vals
            )
            await db.commit()
    return {"ok": True}


@router.delete("/worlds/{wid}/archives/{aid}")
async def delete_world_archive(wid: str, aid: str):
    async with get_db() as db:
        await db.execute("DELETE FROM world_archive_entries WHERE id=? AND world_id=?", (aid, wid))
        await db.commit()
    return {"ok": True}


# ── SSE 提炼端点 ──────────────────────────────────────────────────────────────

@router.post("/worlds/{wid}/fetch-lore")
async def fetch_lore_from_url(wid: str, req: FetchLoreRequest):
    """抓取一个或多个 URL 内容 → LLM 提炼 → SSE 返回结果（不自动写库）。
    自动降级：httpx → Playwright（处理 Cloudflare / JS 渲染页面）。
    支持批量：传 urls=[...] 时逐条抓取，每条发 url_status 事件（失败可单独重试），
    全部抓完后对成功文本合并提炼。
    """
    # 归一化为 URL 列表（兼容旧版单 url 字段）
    url_list: list[str] = []
    if req.urls:
        url_list = [u.strip() for u in req.urls if u and u.strip()]
    elif req.url:
        url_list = [req.url.strip()]

    async def _stream() -> AsyncIterator[bytes]:
        if not url_list:
            yield f"data: {json.dumps({'type': 'error', 'message': '未提供有效 URL'})}\n\n".encode()
            return

        combined_parts: list[str] = []
        ok_count = 0
        for u in url_list:
            yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'fetching'}, ensure_ascii=False)}\n\n".encode()
            try:
                raw_text, engine = await fetch_url_text(u)
                if not raw_text:
                    yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'failed', 'reason': '页面内容为空或无法访问'}, ensure_ascii=False)}\n\n".encode()
                    continue
                ok_count += 1
                combined_parts.append(f"[来源: {u}]\n{raw_text}")
                yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'fetched', 'engine': engine, 'chars': len(raw_text)}, ensure_ascii=False)}\n\n".encode()
            except Exception as e:
                yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'failed', 'reason': str(e)}, ensure_ascii=False)}\n\n".encode()

        if ok_count == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': '所有 URL 抓取失败，请检查链接或站点抓取规则'})}\n\n".encode()
            return

        combined = "\n\n".join(combined_parts)
        async for chunk in _extract_lore_sse(combined):
            yield chunk.encode()

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/worlds/{wid}/parse-document")
async def parse_document(wid: str, req: ParseDocumentRequest):
    """文本/markdown → LLM 提炼 → SSE 返回结果（不自动写库）。"""
    async def _stream() -> AsyncIterator[bytes]:
        async for chunk in _extract_lore_sse(req.text):
            yield chunk.encode()

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/worlds/{wid}/confirm-lore")
async def confirm_lore(wid: str, req: ConfirmLoreRequest):
    """批量写入前端确认/手改后的档案条目。"""
    now = time.time()
    written = []
    async with get_db() as db:
        for entry in req.entries:
            aid = str(uuid.uuid4())
            title = entry.get("title", "")
            content = entry.get("content", "")
            archive_type = entry.get("archive_type", "lore")
            trigger_keywords = entry.get("trigger_keywords", "")
            await db.execute(
                "INSERT INTO world_archive_entries (id, world_id, title, content, archive_type, trigger_keywords, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (aid, wid, title, content, archive_type, trigger_keywords, now, now)
            )
            written.append({"archive_id": aid, "title": title})
        await db.commit()
    return {"ok": True, "written": len(written), "entries": written}


# ── 站点抓取规则管理 API ─────────────────────────────────────────────────────

class ScraperRuleModel(BaseModel):
    domain: str
    alias: str = ""
    engine: str = "httpx"
    content_selectors: list[str] = []
    wait_ms: int = 2000
    max_chars: int = 10000
    enabled: bool = True
    notes: str = ""


@router.get("/scraper-rules")
async def get_scraper_rules():
    """列出所有站点抓取规则（含禁用的）。"""
    return {"rules": list_rules()}


@router.put("/scraper-rules")
async def update_scraper_rules(rules: list[ScraperRuleModel]):
    """整体替换所有规则（前端保存时调用）。"""
    rules_data = [r.model_dump() for r in rules]
    ok = save_rules(rules_data)
    if not ok:
        raise HTTPException(status_code=500, detail="保存失败")
    return {"ok": True, "total": len(rules_data)}


@router.post("/scraper-rules/reload")
async def reload_scraper_rules():
    """热重载规则文件（手动编辑 JSON 后调用）。"""
    rules = load_rules(force=True)
    enabled = [r for r in rules if r.get("enabled", True)]
    return {"ok": True, "total": len(rules), "enabled": len(enabled)}
