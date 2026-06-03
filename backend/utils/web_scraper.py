"""
Web 抓取工具 — 规则驱动多级降级策略

站点规则从 backend/data/sys_config/scraper_rules.json 加载，支持热重载。
新增站点：直接编辑 scraper_rules.json，无需修改代码。

引擎优先级：
  httpx (轻量) → Playwright Chromium (JS渲染/反爬)
"""
from __future__ import annotations
import re
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).parent.parent / "data" / "sys_config" / "scraper_rules.json"

_COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_rules_cache: Optional[list[dict]] = None
_rules_mtime: float = 0.0


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


async def fetch_url_text(url: str, max_chars: int = 12000) -> tuple[str, str]:
    """
    抓取 URL 并返回 (提取的可读文本, 使用的引擎名)。

    策略（按优先级）：
    1. 查找 scraper_rules.json 中匹配的站点规则
    2. 按规则指定的 engine 优先尝试
    3. 若 httpx 失败自动切换 Playwright（无对应规则时也适用）

    返回: (text: str, engine: str)
    """
    rule = get_rule_for_url(url)
    preferred_engine = rule.get("engine", "httpx") if rule else "httpx"
    selectors = rule.get("content_selectors", []) if rule else []
    wait_ms = rule.get("wait_ms", 2000) if rule else 2000
    max_chars = rule.get("max_chars", max_chars) if rule else max_chars

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
    """使用 Playwright 抓取，支持自定义 CSS 选择器和等待时间。"""
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
            content = re.sub(r"\n{3,}", "\n\n", content).strip()
            return content[:max_chars], "playwright"
    except Exception as e:
        raise RuntimeError(f"Playwright 抓取失败: {e}")


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
