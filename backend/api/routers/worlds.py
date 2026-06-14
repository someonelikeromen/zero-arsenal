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
from ...utils.web_scraper import (
    fetch_url_text, list_rules, save_rules, load_rules,
    suggest_wiki_urls, extract_wiki_links,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class CreateWorldRequest(BaseModel):
    name: str
    description: str = ""


class UpdateWorldRequest(BaseModel):
    name: Optional[str] = None
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


class SuggestUrlsRequest(BaseModel):
    world_name: str
    hints: list[str] = []


class FetchLoreRequest(BaseModel):
    # 兼容单 URL（旧）与多 URL 批量（新）：二者择一
    url: Optional[str] = None
    urls: Optional[list[str]] = None
    follow_links: bool = False
    max_follow_links: int = 5       # 跟踪嵌套链接数上限（前端可调 1-20）
    max_chars_per_page: int = 6000  # 单页最大字符数（前端可调 2000-20000）
    max_total_chars: int = 30000    # 全部页面合并上限（前端可调 10000-100000）


class RefineLoreRequest(BaseModel):
    source_text: str
    archive_ids: list[str] = []


class ParseDocumentRequest(BaseModel):
    text: str


class ConfirmLoreRequest(BaseModel):
    entries: list[dict]  # [{title, content, archive_type}]


class ResearchLoreRequest(BaseModel):
    context: str = ""           # 额外上下文（别名、原著类型等）
    max_rounds: int = 12        # 最大研究轮次


# ── 世界提炼 Prompt ───────────────────────────────────────────────────────────

_LORE_EXTRACT_SYSTEM = """你是一个世界观档案提炼助手。
从用户提供的原始文本中，提炼出适合 TRPG/小说创作的世界观条目。
每条条目包含：title（简洁标题）、content（具体内容，300字以内）、archive_type（lore/rule/setting/npc 之一）。
若文本涉及多个版本（漫画/动画/小说/TV版/游戏版），在 content 中注明版本来源。
同一世界观条目在不同版本有差异时，合并为一条并在括号内说明版本差异。
输出格式：JSON 数组，每个元素形如 {"title":"...","content":"...","archive_type":"..."}
只输出 JSON，不要其他文字。"""

_LORE_REFINE_SYSTEM = """你是一个世界观档案修订助手。
根据用户提供的来源（可能是原著文档、细节说明或修改意见），修订或补充现有档案条目。
规则：
- 对已有条目：若内容有误或不完整，修正并保留原有 id 字段。
- 若需新增条目：id 字段设为空字符串""。
- 不需要修改的条目不必包含在输出中。
- 输出格式：JSON 数组，字段：id、title、content、archive_type（lore/rule/setting/npc）。
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
async def list_worlds():
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM worlds ORDER BY updated_at DESC"
        )).fetchall()
    return {"worlds": [dict(r) for r in rows]}


@router.post("/worlds")
async def create_world(req: CreateWorldRequest):
    wid = str(uuid.uuid4())
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO worlds (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
            (wid, req.name, req.description, now, now)
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

async def _refine_lore_sse(existing_archives: list[dict], source_text: str) -> AsyncIterator[str]:
    """调用 LLM 修订现有档案，以 SSE 格式流式返回。"""
    existing_json = json.dumps(
        [{"id": a.get("id", ""), "title": a.get("title", ""), "content": a.get("content", ""),
          "archive_type": a.get("archive_type", "lore")} for a in existing_archives],
        ensure_ascii=False
    )
    messages = [
        {"role": "system", "content": _LORE_REFINE_SYSTEM},
        {"role": "user", "content": f"现有档案条目：\n{existing_json}\n\n补充/修订来源：\n{source_text[:6000]}"},
    ]
    full_text = ""
    try:
        async def on_delta(delta: str) -> None:
            nonlocal full_text
            full_text += delta

        yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"
        await llm_stream(messages, on_delta=on_delta, max_tokens=2000)

        try:
            start = full_text.find("[")
            end = full_text.rfind("]") + 1
            entries = json.loads(full_text[start:end]) if start >= 0 else []
        except Exception as e:
            logger.warning("[worlds] refine-lore JSON 解析失败，降级 entries=[]: %s", e)
            entries = []

        yield f"data: {json.dumps({'type': 'done', 'entries': entries, 'raw': full_text}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"


@router.post("/worlds/suggest-urls")
async def suggest_urls(req: SuggestUrlsRequest):
    """根据世界名（及可选 hints）从 wiki_patterns.json 生成候选 URL 列表。"""
    candidates = suggest_wiki_urls(req.world_name, req.hints)
    return {"candidates": candidates, "total": len(candidates)}


@router.post("/worlds/{wid}/fetch-lore")
async def fetch_lore_from_url(wid: str, req: FetchLoreRequest):
    """抓取一个或多个 URL 内容 → LLM 提炼 → SSE 返回结果（不自动写库）。
    自动降级：httpx → Playwright（处理 Cloudflare / JS 渲染页面）。
    支持批量：传 urls=[...] 时逐条抓取，每条发 url_status 事件（失败可单独重试），
    全部抓完后对成功文本合并提炼。
    follow_links=True 时还会提取页面内链并让 LLM 选最相关子页跟踪抓取。
    """
    # 归一化为 URL 列表（兼容旧版单 url 字段）
    url_list: list[str] = []
    if req.urls:
        url_list = [u.strip() for u in req.urls if u and u.strip()]
    elif req.url:
        url_list = [req.url.strip()]

    max_chars_per_page = req.max_chars_per_page
    max_total_chars = req.max_total_chars

    async def _stream() -> AsyncIterator[bytes]:
        if not url_list:
            yield f"data: {json.dumps({'type': 'error', 'message': '未提供有效 URL'})}\n\n".encode()
            return

        combined_parts: list[str] = []
        total_chars = 0
        ok_count = 0

        async def _fetch_one(u: str) -> tuple[str, str]:
            """抓取单 URL，返回 (text, engine)。"""
            raw_text, engine = await fetch_url_text(u, max_chars=max_chars_per_page)
            return raw_text, engine

        # ── 一级抓取 ────────────────────────────────────────────────────────
        raw_html_map: dict[str, str] = {}
        for u in url_list:
            yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'fetching'}, ensure_ascii=False)}\n\n".encode()
            try:
                raw_text, engine = await _fetch_one(u)
                if not raw_text:
                    yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'failed', 'reason': '页面内容为空或无法访问'}, ensure_ascii=False)}\n\n".encode()
                    continue
                ok_count += 1
                raw_html_map[u] = raw_text
                chunk_text = raw_text[:max_chars_per_page]
                combined_parts.append(f"[来源: {u}]\n{chunk_text}")
                total_chars += len(chunk_text)
                yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'fetched', 'engine': engine, 'chars': len(raw_text)}, ensure_ascii=False)}\n\n".encode()
            except Exception as e:
                yield f"data: {json.dumps({'type': 'url_status', 'url': u, 'status': 'failed', 'reason': str(e)}, ensure_ascii=False)}\n\n".encode()

        if ok_count == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': '所有 URL 抓取失败，请检查链接或站点抓取规则'})}\n\n".encode()
            return

        # ── 嵌套链接跟踪 ─────────────────────────────────────────────────────
        if req.follow_links and total_chars < max_total_chars:
            from urllib.parse import urlparse
            all_sub_links: list[str] = []
            for u, html in raw_html_map.items():
                base = f"{urlparse(u).scheme}://{urlparse(u).netloc}"
                links = extract_wiki_links(html, base)
                all_sub_links.extend(links[:20])  # 每页最多取20候选

            # 去重，排除已抓
            all_sub_links = [l for l in all_sub_links if l not in raw_html_map]
            seen_sub: set[str] = set()
            unique_sub = []
            for l in all_sub_links:
                if l not in seen_sub:
                    seen_sub.add(l)
                    unique_sub.append(l)

            if unique_sub:
                # LLM 轻量筛选最相关的子页
                yield f"data: {json.dumps({'type': 'link_selection', 'candidate_count': len(unique_sub)}, ensure_ascii=False)}\n\n".encode()
                try:
                    filter_prompt = (
                        f"候选子页 URL 列表（共{len(unique_sub)}条）：\n"
                        + "\n".join(unique_sub[:50])
                        + f"\n\n请从中选出最多 {req.max_follow_links} 个与世界观/设定最相关的页面 URL。"
                        + "\n只输出 JSON 数组，如 [\"url1\",\"url2\"]，不要其他文字。"
                    )
                    selection_raw = await llm_complete(
                        messages=[{"role": "user", "content": filter_prompt}],
                        max_tokens=500,
                    )
                    s, e = selection_raw.find("["), selection_raw.rfind("]") + 1
                    selected_links: list[str] = json.loads(selection_raw[s:e]) if s >= 0 else []
                    selected_links = selected_links[:req.max_follow_links]
                except Exception:
                    selected_links = unique_sub[:req.max_follow_links]

                # 抓取选中子页
                for sub_url in selected_links:
                    if total_chars >= max_total_chars:
                        break
                    yield f"data: {json.dumps({'type': 'url_status', 'url': sub_url, 'status': 'fetching', 'depth': 'sub'}, ensure_ascii=False)}\n\n".encode()
                    try:
                        sub_text, sub_engine = await _fetch_one(sub_url)
                        if sub_text:
                            chunk = sub_text[:max_chars_per_page]
                            combined_parts.append(f"[来源(子页): {sub_url}]\n{chunk}")
                            total_chars += len(chunk)
                            yield f"data: {json.dumps({'type': 'url_status', 'url': sub_url, 'status': 'fetched', 'engine': sub_engine, 'chars': len(sub_text), 'depth': 'sub'}, ensure_ascii=False)}\n\n".encode()
                    except Exception as ex:
                        yield f"data: {json.dumps({'type': 'url_status', 'url': sub_url, 'status': 'failed', 'reason': str(ex), 'depth': 'sub'}, ensure_ascii=False)}\n\n".encode()

        combined = "\n\n".join(combined_parts)[:max_total_chars]
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


@router.post("/worlds/{wid}/refine-lore")
async def refine_lore(wid: str, req: RefineLoreRequest):
    """LLM 修订档案：根据用户提供的文档/意见，对现有条目进行修正并生成新增条目。
    SSE 流：type=start → type=done（含 entries 数组）。
    entries 中有 id 的是修订现有条目，id 为空的是新增条目。
    """
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM world_archive_entries WHERE world_id=? ORDER BY created_at ASC", (wid,)
        )).fetchall()
    archives = [dict(r) for r in rows]
    if req.archive_ids:
        archives = [a for a in archives if a.get("id") in req.archive_ids]

    async def _stream() -> AsyncIterator[bytes]:
        async for chunk in _refine_lore_sse(archives, req.source_text):
            yield chunk.encode()

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


# ── LLM Agent 智能研究 ─────────────────────────────────────────────────────────

@router.post("/worlds/{wid}/research-lore")
async def research_lore(wid: str, req: ResearchLoreRequest):
    """
    LLM Agent 自主研究世界观，SSE 流式返回研究日志和最终档案条目。

    SSE 事件类型：
      thinking  - LLM 推理文本片段
      tool_call - Agent 调用工具（搜索/抓取）
      tool_done - 工具执行完成
      done      - 研究完成，携带 entries 列表
      error     - 遭遇错误
    """
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT name FROM worlds WHERE id=?", (wid,)
        )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="world not found")
    world_name = row["name"]

    async def _sse_generator():
        from ...agents.research_agent import run_research_agent

        queue: list[dict] = []

        async def on_event(evt: dict) -> None:
            queue.append(evt)

        # 启动 research agent（并发，通过 queue 推事件）
        import asyncio
        task = asyncio.create_task(
            run_research_agent(
                world_name=world_name,
                context=req.context,
                max_rounds=min(req.max_rounds, 15),
                on_event=on_event,
            )
        )

        # 轮询 queue，推送给客户端
        while not task.done() or queue:
            # 先推已积压的事件
            while queue:
                evt = queue.pop(0)
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            if not task.done():
                await asyncio.sleep(0.1)

        # 确保 task 异常被捕获
        try:
            await task
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
