"""
扩展插件：web_scraper
提供两个额外的 ToolDef，专门用于批量抓取和规则管理。

此文件由 builtin_tools._discover_extension_tools() 自动发现并注册。
TOOLS 列表中的每个 ToolDef 都会被注册为 LLM Agent 可调用工具。

新增站点支持：
  1. 编辑 backend/data/sys_config/scraper_rules.json
  2. 重启后端（或调用 reload_scraper_rules 工具）即可生效

开发新扩展参考此文件的模式：
  - 创建 backend/extensions/<your_name>/tools.py
  - 暴露 TOOLS: list[ToolDef] 模块变量
  - 无需改动任何核心文件
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from typing import Any

import httpx

from ...tools.registry import ToolDef

logger = logging.getLogger(__name__)


async def _batch_fetch_lore(
    urls: list[str],
    session_id: str = "",
    world_id: str = "",
    max_concurrent: int = 3,
) -> dict:
    """
    并发批量抓取多个 URL，每个提炼后写入档案。
    max_concurrent 控制最大并发数（避免被封）。
    """
    from ...utils.web_scraper import fetch_url_text, get_rule_for_url
    from ...agents.llm import llm_complete
    from ...db import get_db
    import time
    import uuid

    if not urls:
        return {"ok": False, "error": "urls 列表为空", "results": []}

    sem = asyncio.Semaphore(max_concurrent)
    results = []

    _system = """你是世界观档案提炼助手。从原始文本提炼 TRPG 世界观条目。
每条格式：{"title":"...","content":"...（≤300字）","archive_type":"lore|rule|setting|npc"}
输出 JSON 数组，不要其他文字。"""

    async def _one(url: str) -> dict:
        async with sem:
            rule = get_rule_for_url(url)
            alias = rule.get("alias", url[:40]) if rule else url[:40]
            try:
                raw_text, engine = await fetch_url_text(url)
                if not raw_text:
                    return {"url": url, "ok": False, "error": "空内容"}

                raw = await llm_complete(
                    messages=[
                        {"role": "system", "content": _system},
                        {"role": "user", "content": f"文本：\n{raw_text[:6000]}"},
                    ],
                    max_tokens=1500,
                )
                s, e = raw.find("["), raw.rfind("]") + 1
                entries = json.loads(raw[s:e]) if s >= 0 else []
            except Exception as ex:
                return {"url": url, "ok": False, "error": str(ex)}

            now = time.time()
            written = 0
            if entries:
                if world_id:
                    async with get_db() as db:
                        for entry in entries:
                            await db.execute(
                                "INSERT INTO world_archive_entries"
                                " (id, world_id, title, content, archive_type, created_at, updated_at)"
                                " VALUES (?,?,?,?,?,?,?)",
                                (str(uuid.uuid4()), world_id, entry.get("title", ""),
                                 entry.get("content", ""), entry.get("archive_type", "lore"), now, now),
                            )
                        await db.commit()
                        written = len(entries)
                elif session_id:
                    async with get_db() as db:
                        for entry in entries:
                            aid = str(uuid.uuid4())
                            await db.execute(
                                "INSERT OR IGNORE INTO world_archives"
                                " (id, session_id, title, content, archive_type, world_key, created_at, updated_at)"
                                " VALUES (?,?,?,?,?,?,?,?)",
                                (aid, session_id, entry.get("title", ""), entry.get("content", ""),
                                 entry.get("archive_type", "lore"), f"web_{aid[:8]}", now, now),
                            )
                        await db.commit()
                        written = len(entries)

            return {
                "url": url,
                "ok": True,
                "engine": engine,
                "alias": alias,
                "entries_count": len(entries),
                "written": written,
            }

    results = await asyncio.gather(*[_one(u) for u in urls], return_exceptions=False)
    ok_count = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    total_written = sum(r.get("written", 0) for r in results if isinstance(r, dict))
    return {
        "ok": True,
        "total": len(urls),
        "ok_count": ok_count,
        "total_written": total_written,
        "results": results,
    }


async def _reload_scraper_rules() -> dict:
    """强制重新加载 scraper_rules.json（修改规则文件后无需重启后端）。"""
    from ...utils.web_scraper import load_rules
    try:
        rules = load_rules(force=True)
        enabled = [r for r in rules if r.get("enabled", True)]
        return {
            "ok": True,
            "total": len(rules),
            "enabled": len(enabled),
            "domains": [r.get("domain") for r in enabled],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _update_scraper_rule(
    domain: str,
    alias: str = "",
    engine: str = "httpx",
    content_selectors: list[str] | None = None,
    wait_ms: int = 2000,
    max_chars: int = 10000,
    enabled: bool = True,
    notes: str = "",
) -> dict:
    """
    添加或更新一条站点抓取规则。
    若 domain 已存在则更新，否则新增。
    修改立即持久化到 scraper_rules.json。
    """
    from ...utils.web_scraper import list_rules, save_rules
    rules = list_rules()
    existing = next((r for r in rules if r.get("domain") == domain), None)
    new_rule: dict = {
        "domain": domain,
        "alias": alias or domain,
        "engine": engine,
        "content_selectors": content_selectors or [],
        "wait_ms": wait_ms,
        "max_chars": max_chars,
        "enabled": enabled,
        "notes": notes,
    }
    if existing:
        existing.update(new_rule)
        action = "updated"
    else:
        rules.append(new_rule)
        action = "added"

    ok = save_rules(rules)
    return {"ok": ok, "action": action, "domain": domain}


async def _fetch_webpage(url: str, max_chars: int = 4000) -> dict:
    """
    抓取单个 URL 并将文本内容直接返回给 LLM（不写 DB）。
    适合在会话中临时查阅 wiki/文档页面，或在调用 generate_world 前预览内容。
    """
    from ...utils.web_scraper import fetch_url_text
    try:
        raw_text, engine = await fetch_url_text(url, max_chars=max_chars)
        if not raw_text:
            return {"ok": False, "url": url, "error": "页面内容为空或无法访问"}
        return {
            "ok": True,
            "url": url,
            "engine": engine,
            "chars": len(raw_text),
            "text": raw_text[:max_chars],
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


async def _generate_world(
    world_name: str,
    hints: list[str] | None = None,
    max_urls: int = 3,
    max_chars: int = 6000,
) -> dict:
    """
    全自动世界档案生成管线：
    1. 从 wiki_patterns.json 生成候选 URL
    2. 并发抓取前 max_urls 条页面
    3. LLM 提炼世界观条目
    4. 检查 DB 是否已有同名 world（有则追加，无则 INSERT）
    5. 写入 world_archive_entries
    返回 world_id / entries_count 供 LLM 引用。
    """
    import asyncio, time, uuid as _uuid
    from ...utils.web_scraper import suggest_wiki_urls, fetch_url_text
    from ...agents.llm import llm_complete
    from ...db import get_db

    _LORE_SYSTEM = """你是世界观档案提炼助手。从原始文本提炼 TRPG 世界观条目。
每条格式：{"title":"...","content":"...（≤300字）","archive_type":"lore|rule|setting|npc"}
输出 JSON 数组，不要其他文字。"""

    hints = hints or []
    candidates = [c for c in suggest_wiki_urls(world_name, hints) if c]
    urls_to_fetch = [c["url"] for c in candidates[:max_urls]]

    if not urls_to_fetch:
        return {"ok": False, "error": "wiki_patterns.json 中无可用模式，无法生成候选 URL"}

    # 并发抓取
    async def _one(url: str) -> tuple[str, str, str]:
        try:
            text, engine = await fetch_url_text(url, max_chars=max_chars)
            return url, text or "", engine
        except Exception as ex:
            return url, "", str(ex)

    results = await asyncio.gather(*[_one(u) for u in urls_to_fetch])
    texts = [(url, text) for url, text, _ in results if text]
    urls_fetched = [url for url, text, _ in results if text]

    if not texts:
        return {"ok": False, "error": "所有候选 URL 抓取失败", "tried_urls": urls_to_fetch}

    combined = "\n\n".join(f"[来源: {url}]\n{text}" for url, text in texts)[:30000]

    # LLM 提炼
    raw = await llm_complete(
        messages=[
            {"role": "system", "content": _LORE_SYSTEM},
            {"role": "user", "content": f"世界名：{world_name}\n\n文本：\n{combined[:8000]}"},
        ],
        max_tokens=2000,
    )
    try:
        s, e = raw.find("["), raw.rfind("]") + 1
        entries = json.loads(raw[s:e]) if s >= 0 else []
    except Exception:
        entries = []

    # 写库
    now = time.time()
    async with get_db() as db:
        # 查是否已存在同名 world
        existing = await (await db.execute(
            "SELECT id FROM worlds WHERE name=?", (world_name,)
        )).fetchone()
        if existing:
            world_id = existing["id"]
            is_existing = True
        else:
            world_id = str(_uuid.uuid4())
            desc = f"自动生成：{world_name}（来源：{', '.join(urls_fetched)}）"
            await db.execute(
                "INSERT INTO worlds (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
                (world_id, world_name, desc, now, now),
            )
            is_existing = False

        for entry in entries:
            await db.execute(
                "INSERT INTO world_archive_entries"
                " (id, world_id, title, content, archive_type, trigger_keywords, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(_uuid.uuid4()), world_id,
                    entry.get("title", ""), entry.get("content", ""),
                    entry.get("archive_type", "lore"), "", now, now,
                ),
            )
        await db.commit()

    return {
        "ok": True,
        "world_id": world_id,
        "world_name": world_name,
        "entries_count": len(entries),
        "urls_fetched": urls_fetched,
        "existing": is_existing,
    }


# ── TOOLS 暴露给 _discover_extension_tools ──────────────────────────────────

async def _web_search(query: str, max_results: int = 8) -> dict:
    """
    使用 DuckDuckGo HTML 端点搜索网页，无需 API Key。
    返回 [{title, url, snippet}] 列表供 LLM 判断哪些 URL 值得抓取。
    """
    encoded = urllib.parse.quote_plus(query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(search_url, headers=headers)
            html = resp.text
    except Exception as e:
        return {"ok": False, "error": str(e), "results": []}

    results: list[dict] = []
    # 提取每个 result__a 锚点（标题 + redirect URL）
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    ):
        href_raw, title_html = m.group(1), m.group(2)
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        if not title:
            continue
        # 解码 DuckDuckGo redirect  /l/?uddg=https%3A%2F%2F...
        real_url = href_raw
        uddg_m = re.search(r"[?&]uddg=([^&]+)", href_raw)
        if uddg_m:
            real_url = urllib.parse.unquote(uddg_m.group(1))
        elif href_raw.startswith("/"):
            # 相对 URL：跳过
            continue
        results.append({"title": title, "url": real_url, "snippet": ""})
        if len(results) >= max_results:
            break

    # 再补 snippet（result__snippet）—— 顺序匹配
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    )
    for i, snip in enumerate(snippets):
        if i < len(results):
            results[i]["snippet"] = re.sub(r"<[^>]+>", "", snip).strip()

    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": results,
    }


async def _synthesize_lore(
    texts: list[str],
    world_name: str = "",
    max_tokens: int = 2500,
) -> dict:
    """
    将研究过程中累积的网页文本提炼为结构化 TRPG 世界观档案条目。
    这是 Research Agent 循环的「退出工具」——LLM 认为信息已充分时调用。
    返回 entries 列表，格式与 confirm-lore 接口一致。
    """
    from ...agents.llm import llm_complete

    if not texts:
        return {"ok": False, "error": "texts 列表为空", "entries": []}

    combined = "\n\n---\n\n".join(t[:4000] for t in texts)[:20000]

    _system = """你是 TRPG 世界观档案提炼专家。从以下研究资料中提炼结构化档案条目。

要求：
- 每条覆盖一个明确的知识点（地点/人物/规则/历史事件/世界设定均可）
- 内容具体准确，贴合原作，不得凭空补充
- archive_type 取值：lore（世界观/设定）| rule（系统规则）| setting（地点/组织）| npc（人物）| event（事件/历史）
- 每条 content ≤ 400 字
- 至少生成 5 条，尽量多提炼，覆盖不同层面

只输出 JSON 数组，不要其他文字：
[{"title":"...","content":"...","archive_type":"..."}]"""

    user_content = f"世界：{world_name}\n\n研究资料：\n{combined}"
    try:
        raw = await llm_complete(
            messages=[
                {"role": "system", "content": _system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
        )
        s, e = raw.find("["), raw.rfind("]") + 1
        entries = json.loads(raw[s:e]) if s >= 0 else []
        return {
            "ok": True,
            "entries_count": len(entries),
            "entries": entries,
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "entries": []}


# ── browse_url：浏览器代理工具（Playwright-only，跳过 httpx） ────────────────

async def _browse_url(url: str, wait_seconds: int = 4, max_chars: int = 8000) -> dict:
    """
    用 Playwright 无头浏览器直接打开 URL，适合 JS 渲染页面和 bot 检测站点。
    跳过 httpx，强制走真实 Chromium 引擎。
    Windows 下在独立线程的 ProactorEventLoop 中运行（绕过 SelectorEventLoop 不支持子进程的限制）。
    返回页面标题、提取文本、最终 URL（处理重定向后）。
    """
    from ...utils.web_scraper import _run_in_playwright_thread
    return await _run_in_playwright_thread(_browse_url_impl, url, wait_seconds, max_chars)


async def _browse_url_impl(url: str, wait_seconds: int = 4, max_chars: int = 8000) -> dict:
    """Playwright 实现（在 SelectorEventLoop 线程中执行）。"""
    import re as _re
    import traceback as _tb

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "ok": False,
            "url": url,
            "error": "playwright 未安装，请运行: pip install playwright && playwright install chromium",
        }

    _DEFAULT_SELECTORS = [
        "#mw-content-text .mw-parser-output",
        "#mw-content-text",
        ".mw-parser-output",
        ".page-content",
        "article",
        "main",
        "body",
    ]
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    wait_ms = max(0, int(wait_seconds * 1000))
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                ],
            )
            context = await browser.new_context(
                user_agent=_UA,
                locale="zh-CN",
                extra_http_headers={
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-Mode": "navigate",
                },
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # 隐藏 webdriver 标志，减少 bot 检测风险
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            # 屏蔽媒体资源，加速加载
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}",
                lambda r: r.abort(),
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

            title = await page.title()
            final_url = page.url

            content = ""
            for selector in _DEFAULT_SELECTORS:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        content = await el.inner_text()
                        if len(content) > 300:
                            break
                except Exception:
                    continue

            if not content:
                content = await page.inner_text("body")

            await browser.close()
            browser = None

            content = _re.sub(r"\n{3,}", "\n\n", content).strip()
            text = content[:max_chars]

            return {
                "ok": True,
                "url": url,
                "final_url": final_url,
                "title": title,
                "text": text,
                "chars": len(text),
                "engine": "playwright",
            }
    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e) or repr(e)
        tb_lines = _tb.format_exc().strip().splitlines()[-3:]
        import logging as _log
        _log.getLogger(__name__).warning(
            "[browse_url] Playwright failed for %s: %s: %s\n%s",
            url, err_type, err_msg, "\n".join(tb_lines),
        )
        return {
            "ok": False,
            "url": url,
            "error": f"{err_type}: {err_msg}",
        }


TOOLS: list[ToolDef] = [
    ToolDef(
        name="batch_fetch_lore",
        description=(
            "并发批量抓取多个 URL（Wiki/Fandom/Wikipedia 等），为每个页面提炼世界观档案条目并写库。"
            "适合一次性导入多个参考来源。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要抓取的 URL 列表（建议 ≤10 个）",
                },
                "session_id": {"type": "string", "description": "目标会话 ID（写入会话档案）", "default": ""},
                "world_id":   {"type": "string", "description": "目标世界模板 ID（写入全局模板）", "default": ""},
                "max_concurrent": {"type": "integer", "description": "最大并发数（默认 3）", "default": 3},
            },
            "required": ["urls"],
        },
        handler=_batch_fetch_lore,
        permission_required="ask",
        tags=["web", "lore", "scraper", "batch"],
        group="lore",
    ),
    ToolDef(
        name="reload_scraper_rules",
        description="热重载 scraper_rules.json（编辑站点规则后调用，无需重启后端）。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_reload_scraper_rules,
        permission_required="allow",
        tags=["web", "scraper", "config"],
        group="lore",
    ),
    ToolDef(
        name="update_scraper_rule",
        description=(
            "动态添加或更新一条网站抓取规则（domain、engine、CSS 选择器等）。"
            "修改立即持久化，下次抓取即生效，无需重启。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain":            {"type": "string",  "description": "站点域名，如 my-wiki.com"},
                "alias":             {"type": "string",  "description": "友好名称", "default": ""},
                "engine":            {"type": "string",  "description": "引擎：httpx 或 playwright", "default": "httpx"},
                "content_selectors": {"type": "array",   "items": {"type": "string"}, "description": "CSS 选择器列表（优先级从高到低）", "default": []},
                "wait_ms":           {"type": "integer", "description": "Playwright 等待时间（毫秒）", "default": 2000},
                "max_chars":         {"type": "integer", "description": "最大提取字符数", "default": 10000},
                "enabled":           {"type": "boolean", "description": "是否启用", "default": True},
                "notes":             {"type": "string",  "description": "备注说明", "default": ""},
            },
            "required": ["domain"],
        },
        handler=_update_scraper_rule,
        permission_required="allow",
        tags=["web", "scraper", "config"],
        group="lore",
    ),
    ToolDef(
        name="fetch_webpage",
        description=(
            "抓取单个 URL 的文本内容并直接返回给 LLM（不写 DB）。"
            "适合在会话中临时查阅 wiki、百科、文档等页面。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url":       {"type": "string",  "description": "要抓取的 URL"},
                "max_chars": {"type": "integer", "description": "返回最大字符数（默认 4000）", "default": 4000},
            },
            "required": ["url"],
        },
        handler=_fetch_webpage,
        permission_required="ask",
        tags=["web", "scraper", "lookup"],
        group="lore",
    ),
    ToolDef(
        name="generate_world",
        description=(
            "根据世界名称全自动生成世界档案：①自动发现 wiki URL；②抓取页面；"
            "③LLM 提炼世界观条目；④写入 DB 并返回 world_id。"
            "适合无限流剧情进入新世界时一键建档，无需用户手动操作。"
            "若 DB 中已有同名世界，会追加新条目而不重复创建。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "world_name": {"type": "string",  "description": "世界名称，如「刀剑神域」「进击的巨人」"},
                "hints":      {"type": "array",   "items": {"type": "string"},
                               "description": "额外搜索提示，如别名、英文名 [\"SAO\", \"Aincrad\"]", "default": []},
                "max_urls":   {"type": "integer", "description": "最多抓取几个 wiki URL（默认 3）", "default": 3},
                "max_chars":  {"type": "integer", "description": "每页最大字符数（默认 6000）", "default": 6000},
            },
            "required": ["world_name"],
        },
        handler=_generate_world,
        permission_required="ask",
        tags=["web", "world", "lore", "auto"],
        group="world",
    ),
    ToolDef(
        name="web_search",
        description=(
            "使用 DuckDuckGo 搜索网页，返回匹配结果列表（title/url/snippet）。"
            "适合在 Research Agent 循环中动态发现权威来源 URL，"
            "再配合 fetch_webpage 抓取具体内容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "搜索查询词，建议包含世界名和关键词"},
                "max_results": {"type": "integer", "description": "最多返回结果数（默认 8）", "default": 8},
            },
            "required": ["query"],
        },
        handler=_web_search,
        permission_required="ask",
        tags=["web", "search", "research"],
        group="lore",
    ),
    ToolDef(
        name="synthesize_lore",
        description=(
            "将研究过程中累积的多段网页文本提炼为结构化 TRPG 世界观档案条目。"
            "这是 Research Agent 的退出工具——当 LLM 判断已收集足够信息时调用。"
            "返回 entries 列表（title/content/archive_type）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "texts":      {"type": "array",   "items": {"type": "string"},
                               "description": "已抓取的网页文本列表（每项来自一个页面）"},
                "world_name": {"type": "string",  "description": "目标世界名称（用于提炼上下文）", "default": ""},
            },
            "required": ["texts"],
        },
        handler=_synthesize_lore,
        permission_required="allow",
        tags=["web", "lore", "research", "synthesize"],
        group="lore",
    ),
    ToolDef(
        name="browse_url",
        description=(
            "用真实无头浏览器（Playwright Chromium）打开网页，返回页面标题和正文文本。"
            "适合 Wikipedia、Fandom、萌娘百科等 httpx 被 bot 检测拦截的站点。"
            "比 fetch_webpage 慢（需启动浏览器），但成功率更高，能执行 JavaScript。"
            "返回 {ok, url, final_url, title, text, chars, engine}。"
            "如果 fetch_webpage 返回错误或空内容，改用此工具重试。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要打开的网页 URL",
                },
                "wait_seconds": {
                    "type": "integer",
                    "description": "页面加载后额外等待秒数（默认 4，JS 密集页面可增大到 8）",
                    "default": 4,
                },
                "max_chars": {
                    "type": "integer",
                    "description": "返回文本最大字符数（默认 8000）",
                    "default": 8000,
                },
            },
            "required": ["url"],
        },
        handler=_browse_url,
        permission_required="ask",
        tags=["web", "browser", "playwright", "research"],
        group="lore",
    ),
]
