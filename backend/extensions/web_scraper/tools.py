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
from typing import Any

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


# ── TOOLS 暴露给 _discover_extension_tools ──────────────────────────────────

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
]
