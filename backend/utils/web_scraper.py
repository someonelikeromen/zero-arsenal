"""
Web 抓取工具 — 规则驱动多级降级策略

站点规则从 backend/data/sys_config/scraper_rules.json 加载，支持热重载。
Wiki 候选 URL 模式从 backend/data/sys_config/wiki_patterns.json 加载，支持前端增删改。
新增站点：直接编辑对应 JSON 文件，无需修改代码。

引擎优先级：
  httpx (轻量) → Playwright Chromium (JS渲染/反爬)
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import re
import json
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Windows 上 uvicorn reload worker 设置了 WindowsSelectorEventLoopPolicy（因为是子进程），
# 导致 FastAPI 运行在 SelectorEventLoop 中。SelectorEventLoop 在 Windows 上没有实现
# _make_subprocess_transport，Playwright 无法启动 Chromium 子进程。
# 修复：在独立线程中创建 ProactorEventLoop（Windows 上唯一支持子进程的 loop）运行 Playwright。
_PLAYWRIGHT_NEEDS_THREAD = sys.platform == "win32"


async def _run_in_playwright_thread(async_fn, *args, **kwargs):
    """
    在独立线程中用 ProactorEventLoop 运行 Playwright 相关的异步函数。

    背景：Windows 上 uvicorn reload worker 使用 SelectorEventLoop，
    该 loop 不支持 subprocess_exec（缺少 _make_subprocess_transport 实现），
    Playwright 启动 Chromium 时直接报 NotImplementedError。
    ProactorEventLoop 是 Windows 上唯一支持子进程管道通信的事件循环实现。
    """
    if not _PLAYWRIGHT_NEEDS_THREAD:
        return await async_fn(*args, **kwargs)

    def _runner():
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_fn(*args, **kwargs))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    running_loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw_proc") as ex:
        return await running_loop.run_in_executor(ex, _runner)

_RULES_PATH = Path(__file__).parent.parent / "data" / "sys_config" / "scraper_rules.json"
_WIKI_PATTERNS_PATH = Path(__file__).parent.parent / "data" / "sys_config" / "wiki_patterns.json"

_COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# MediaWiki API 快路径：匹配已知 MediaWiki 站点，用 API 取纯文本，比 Playwright 可靠 10 倍
# key = 域名关键字, value = API 路径前缀函数或固定值
_MEDIAWIKI_DOMAINS: dict[str, str] = {
    "wikipedia.org":       "/w/api.php",
    "moegirl.org.cn":      "/api.php",
    "fandom.com":          "/api.php",
    "wiki.biligame.com":   None,   # 需要特殊路径，见 _try_mediawiki_api
    "wikia.com":           "/api.php",
}

_rules_cache: Optional[list[dict]] = None
_rules_mtime: float = 0.0
_wiki_patterns_cache: Optional[list[dict]] = None
_wiki_patterns_mtime: float = 0.0


def load_rules(force: bool = False) -> list[dict]:
    """加载站点规则，支持文件变更时热重载。"""
    global _rules_cache, _rules_mtime
    try:
        mtime = _RULES_PATH.stat().st_mtime
        if not force and _rules_cache is not None and mtime == _rules_mtime:
            return _rules_cache
        data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        _rules_cache = [r for r in data.get("rules", []) if r.get("enabled", True)]
        _rules_mtime = mtime
        return _rules_cache
    except Exception as e:
        logger.warning(f"[Scraper] 加载 scraper_rules.json 失败: {e}，使用空规则列表")
        return []


def get_rule_for_url(url: str) -> Optional[dict]:
    """根据 URL 匹配最具体的站点规则（最长域名匹配）。"""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    rules = load_rules()
    best: Optional[dict] = None
    best_len = 0
    for rule in rules:
        domain = rule.get("domain", "")
        if domain and domain in host and len(domain) > best_len:
            best = rule
            best_len = len(domain)
    return best


def _extract_text_from_html(html: str) -> str:
    """从 HTML 中提取可读文本（去除脚本/样式/导航噪声）。"""
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _detect_mediawiki_api(url: str) -> Optional[tuple[str, str]]:
    """
    检测 URL 是否属于已知 MediaWiki 站点。
    返回 (api_base_url, page_title)，失败返回 None。
    """
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path

    for domain_key, api_suffix in _MEDIAWIKI_DOMAINS.items():
        if domain_key not in netloc:
            continue

        # 提取页面标题（wiki URL 格式：/wiki/Title 或 /Title）
        title: Optional[str] = None
        wiki_m = re.search(r"/wiki/(.+)$", path)
        if wiki_m:
            title = urllib.parse.unquote(wiki_m.group(1))
        elif domain_key == "moegirl.org.cn":
            # 萌娘百科：路径即标题，如 /学园默示录
            if path and path != "/":
                title = urllib.parse.unquote(path.lstrip("/"))
        elif domain_key == "wiki.biligame.com":
            # Biligame：路径格式 /{game}/Title
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2:
                game_seg = parts[0]
                title = urllib.parse.unquote(parts[-1])
                api_base = f"{parsed.scheme}://{parsed.netloc}/{game_seg}/api.php"
                return api_base, title
        
        if not title:
            continue

        if api_suffix:
            api_base = f"{parsed.scheme}://{parsed.netloc}{api_suffix}"
        else:
            continue

        return api_base, title

    return None


async def _try_mediawiki_api(url: str, max_chars: int) -> Optional[tuple[str, str]]:
    """
    尝试通过 MediaWiki API 抓取页面纯文本。
    - Wikipedia：优先用 REST API /api/rest_v1/page/summary（宽松鉴权），降级用 action=query
    - 其他 MediaWiki：使用 action=query&prop=extracts
    成功返回 (text, "mediawiki_api")，失败返回 None。
    """
    info = _detect_mediawiki_api(url)
    if not info:
        return None

    api_base, title = info
    parsed = urllib.parse.urlparse(url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"

    # 符合 MediaWiki / Wikipedia UA 政策的请求头
    api_headers = {
        "User-Agent": "ZeroArsenal/1.0 (TRPG world-lore research bot; non-commercial) python-httpx",
        "Accept": "application/json",
    }

    # Wikipedia 优先使用 REST API（不需要 Token，更稳定）
    if "wikipedia.org" in parsed.netloc:
        rest_url = f"{base_origin}/api/rest_v1/page/summary/{urllib.parse.quote(title, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(rest_url, headers={
                    **api_headers,
                    # Wikipedia 需要真实 UA，否则 403
                    "User-Agent": _COMMON_HEADERS["User-Agent"],
                })
                if resp.status_code == 200:
                    data = resp.json()
                    extract = data.get("extract", "")
                    if extract and len(extract) > 100:
                        text = re.sub(r"\n{3,}", "\n\n", extract).strip()
                        return text[:max_chars], "mediawiki_api"
        except Exception as e:
            logger.debug("[Scraper] Wikipedia REST API failed for %s: %s, trying action=query", url, e)

    # 通用 MediaWiki action=query 路径
    params = urllib.parse.urlencode({
        "action": "query",
        "prop": "extracts",
        "titles": title,
        "format": "json",
        "explaintext": "true",
        "exsectionformat": "plain",
        "redirects": "1",
    })
    api_url = f"{api_base}?{params}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(api_url, headers={
                **api_headers,
                "User-Agent": _COMMON_HEADERS["User-Agent"],
            })
            resp.raise_for_status()
            data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                continue
            extract = page_data.get("extract", "")
            if extract and len(extract) > 100:
                text = re.sub(r"\n{3,}", "\n\n", extract).strip()
                return text[:max_chars], "mediawiki_api"
    except Exception as e:
        logger.debug("[Scraper] MediaWiki action=query failed for %s: %s", url, e)

    return None


async def fetch_url_text(url: str, max_chars: int = 12000) -> tuple[str, str]:
    """
    抓取 URL 并返回 (提取的可读文本, 使用的引擎名)。

    策略（按优先级）：
    1. MediaWiki API 快路径（Wikipedia/萌娘百科/Fandom/Biligame）
    2. 查找 scraper_rules.json 中匹配的站点规则
    3. 按规则指定的 engine 优先尝试
    4. 若 httpx 失败自动切换 Playwright（无对应规则时也适用）

    返回: (text: str, engine: str)
    """
    rule = get_rule_for_url(url)
    preferred_engine = rule.get("engine", "httpx") if rule else "httpx"
    selectors = rule.get("content_selectors", []) if rule else []
    wait_ms = rule.get("wait_ms", 2000) if rule else 2000
    max_chars = rule.get("max_chars", max_chars) if rule else max_chars

    # MediaWiki API 快路径（比 Playwright 可靠，无需 JS 渲染）
    # 仅在规则未强制指定 playwright 时尝试
    if preferred_engine != "playwright":
        mw_result = await _try_mediawiki_api(url, max_chars)
        if mw_result:
            return mw_result

    use_playwright = preferred_engine == "playwright"

    if not use_playwright:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url, headers=_COMMON_HEADERS)
                resp.raise_for_status()
                html = resp.text
                if "cf-browser-verification" in html or "Enable JavaScript" in html or len(html) < 500:
                    use_playwright = True
                else:
                    text = _extract_text_from_html(html)
                    return text[:max_chars], "httpx"
        except Exception as e:
            logger.warning(f"[Scraper] httpx failed for {url}: {e}, trying Playwright")
            use_playwright = True

    if use_playwright:
        return await _fetch_with_playwright(url, max_chars, selectors=selectors, wait_ms=wait_ms)

    return "", "failed"


async def _fetch_with_playwright(
    url: str,
    max_chars: int,
    selectors: list[str] | None = None,
    wait_ms: int = 2500,
) -> tuple[str, str]:
    """使用 Playwright 抓取（外层，Windows 下自动切换 ProactorEventLoop 线程）。"""
    return await _run_in_playwright_thread(
        _fetch_with_playwright_impl, url, max_chars, selectors, wait_ms
    )


async def _fetch_with_playwright_impl(
    url: str,
    max_chars: int,
    selectors: list[str] | None = None,
    wait_ms: int = 2500,
) -> tuple[str, str]:
    """使用 Playwright 抓取，支持自定义 CSS 选择器和等待时间。"""
    import traceback as _traceback

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright 未安装，请运行: pip install playwright && playwright install chromium")

    _default_selectors = [
        "#mw-content-text .mw-parser-output",
        "#mw-content-text",
        ".mw-parser-output",
        ".page-content",
        "article",
        "main",
        "body",
    ]
    use_selectors = selectors if selectors else _default_selectors

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=_COMMON_HEADERS["User-Agent"],
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
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}",
                lambda r: r.abort(),
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

            content = ""
            for selector in use_selectors:
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
            content = re.sub(r"\n{3,}", "\n\n", content).strip()
            return content[:max_chars], "playwright"
    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e) or repr(e)
        tb_summary = _traceback.format_exc().strip().splitlines()[-3:]
        logger.warning(
            "[Scraper] Playwright failed for %s: %s: %s\n%s",
            url, err_type, err_msg, "\n".join(tb_summary),
        )
        raise RuntimeError(f"Playwright 抓取失败: {err_type}: {err_msg}")


# ── API: 列出当前规则（供前端和 Tool 调用） ──────────────────────────────────

def list_rules() -> list[dict]:
    """返回所有规则（含禁用的），用于前端管理界面。"""
    try:
        data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        return data.get("rules", [])
    except Exception:
        return []


def save_rules(rules: list[dict]) -> bool:
    """将规则写回 scraper_rules.json，触发下次热重载。"""
    global _rules_cache
    try:
        existing = {}
        if _RULES_PATH.exists():
            existing = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        existing["rules"] = rules
        _RULES_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        _rules_cache = None  # 强制重载
        return True
    except Exception as e:
        logger.error(f"[Scraper] save_rules failed: {e}")
        return False


# ── Wiki 候选 URL 模式管理 ────────────────────────────────────────────────────

def load_wiki_patterns(force: bool = False) -> list[dict]:
    """加载 wiki_patterns.json，支持文件变更时热重载。"""
    global _wiki_patterns_cache, _wiki_patterns_mtime
    try:
        mtime = _WIKI_PATTERNS_PATH.stat().st_mtime
        if not force and _wiki_patterns_cache is not None and mtime == _wiki_patterns_mtime:
            return _wiki_patterns_cache
        data = json.loads(_WIKI_PATTERNS_PATH.read_text(encoding="utf-8"))
        _wiki_patterns_cache = data if isinstance(data, list) else []
        _wiki_patterns_mtime = mtime
        return _wiki_patterns_cache
    except Exception as e:
        logger.warning(f"[Scraper] 加载 wiki_patterns.json 失败: {e}，使用默认空列表")
        return []


def list_wiki_patterns() -> list[dict]:
    """返回所有 wiki 模式（含禁用的），用于前端管理界面。"""
    try:
        data = json.loads(_WIKI_PATTERNS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_wiki_patterns(patterns: list[dict]) -> bool:
    """将 wiki 模式写回 wiki_patterns.json，触发下次热重载。"""
    global _wiki_patterns_cache
    try:
        _WIKI_PATTERNS_PATH.write_text(
            json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _wiki_patterns_cache = None  # 强制重载
        return True
    except Exception as e:
        logger.error(f"[Scraper] save_wiki_patterns failed: {e}")
        return False


def _build_url_from_pattern(pattern: str, world_name: str, slug_transform: Optional[str]) -> str:
    """将世界名填入 URL 模式的 {name} 和 {slug} 占位符。"""
    name_encoded = urllib.parse.quote(world_name, safe="")
    if slug_transform == "lowercase_hyphen":
        slug = world_name.lower().replace(" ", "-").replace("_", "-")
    elif slug_transform == "lowercase_underscore":
        slug = world_name.lower().replace(" ", "_").replace("-", "_")
    else:
        slug = urllib.parse.quote(world_name, safe="")
    return pattern.replace("{name}", name_encoded).replace("{slug}", slug)


def suggest_wiki_urls(world_name: str, hints: list[str] | None = None) -> list[dict]:
    """
    根据世界名（及可选的别名 hints）从 wiki_patterns.json 生成候选 URL 列表。
    返回: [{"source": str, "url": str, "label": str}]
    """
    patterns = [p for p in load_wiki_patterns() if p.get("enabled", True)]
    all_names = [world_name] + (hints or [])
    seen: set[str] = set()
    results: list[dict] = []
    for name in all_names:
        for pat in patterns:
            url = _build_url_from_pattern(
                pat["pattern"], name, pat.get("slug_transform")
            )
            if url not in seen:
                seen.add(url)
                results.append({
                    "source": pat["source"],
                    "url": url,
                    "label": f"[{pat['source']}] {name}",
                })
    return results


# ── Wiki 内链提取 ─────────────────────────────────────────────────────────────

_WIKI_NOISE_PATTERNS = re.compile(
    r"/(Special|Talk|User|User_talk|Wikipedia|File|Image|Category|Help|"
    r"Template|MediaWiki|Module|Portal)([:/]|$)",
    re.IGNORECASE,
)


def extract_wiki_links(html: str, base_domain: str) -> list[str]:
    """
    从 HTML 中提取同域 wiki 内链，过滤 Special/Talk/User/Category 等噪声页。
    返回去重后的绝对 URL 列表。
    """
    href_re = re.compile(r'href=["\']([^"\'#?]+)["\']', re.IGNORECASE)
    links: list[str] = []
    seen: set[str] = set()
    for m in href_re.finditer(html):
        href = m.group(1).strip()
        # 构造绝对 URL
        if href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = base_domain.rstrip("/") + href
        elif href.startswith("http"):
            url = href
        else:
            continue
        # 仅保留同域链接
        if base_domain.replace("https://", "").replace("http://", "").split("/")[0] not in url:
            continue
        # 过滤噪声页
        if _WIKI_NOISE_PATTERNS.search(href):
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links
