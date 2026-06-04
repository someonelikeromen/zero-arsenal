"""
ZeroArsenal E2E 浏览器测试 + API测试 + 真实LLM集成测试
运行: python tests/e2e/test_browser_e2e.py
输出: tests/screenshots/ 目录下的截图 + 控制台报告

注：脚本式伪 E2E（test_ 函数带位置参数、依赖运行中的后端/前端、失败不退出），
非标准 pytest 用例，标注 stub；CI 以 `-m "not stub"` 排除（见 STUB_ANALYSIS T06）。
"""
import asyncio
import json
import os
import sys
import time
import pathlib
import requests
from datetime import datetime

import pytest

pytestmark = pytest.mark.stub

sys.stdout.reconfigure(encoding="utf-8")

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://localhost:5174"
SCREENSHOT_DIR = pathlib.Path(__file__).parent.parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
results = []

def log(msg: str, ok: bool = True):
    mark = "✅" if ok else "❌"
    print(f"  {mark} {msg}")
    results.append({"msg": msg, "ok": ok, "ts": datetime.now().isoformat()})

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════
# Part 1: API 烟雾测试（直接 HTTP，不依赖浏览器）
# ═══════════════════════════════════════════════════════════════

def test_api_smoke():
    section("Part 1: API Smoke Tests")

    # 健康检查
    r = requests.get(f"{BACKEND_URL}/health", timeout=5)
    assert r.status_code == 200
    log(f"GET /health → {r.status_code} {r.json()}")

    # 会话列表
    r = requests.get(f"{BACKEND_URL}/api/sessions", timeout=5)
    assert r.status_code == 200
    sessions = r.json()
    log(f"GET /api/sessions → {len(sessions)} 个会话")

    # 世界插件（扩展）列表
    r = requests.get(f"{BACKEND_URL}/api/engine/extensions", timeout=5)
    assert r.status_code == 200
    worlds = r.json()
    log(f"GET /api/engine/extensions → {worlds}")

    # 系统信息（可能较慢，用较长超时且不中断流程）
    try:
        r = requests.get(f"{BACKEND_URL}/api/system/info", timeout=15)
        if r.ok:
            sinfo = r.json()
            log(f"GET /api/system/info → tools={sinfo.get('tools','?')} plugins={sinfo.get('plugins','?')} skills={sinfo.get('skills','?')}")
        else:
            log(f"GET /api/system/info → {r.status_code}", ok=False)
    except Exception as e:
        log(f"GET /api/system/info 超时/失败: {e}", ok=False)

    # 创建新会话
    payload = {
        "title": f"E2E测试会话_{TIMESTAMP}",
        "world_plugin": "crossover",
        "mode": "play",
    }
    r = requests.post(f"{BACKEND_URL}/api/sessions", json=payload, timeout=10)
    assert r.status_code == 200
    session = r.json()
    session_id = session.get("session_id") or session.get("id")
    assert session_id, f"响应缺少 session_id 字段: {session}"
    log(f"POST /api/sessions → 创建成功 id={session_id[:8]}...")

    # 查询会话详情
    r = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}", timeout=5)
    assert r.status_code == 200
    detail = r.json()
    log(f"GET /api/sessions/{{id}} → {detail.get('title') or detail.get('id','?')}")

    # 技能列表（写作风格）
    r = requests.get(f"{BACKEND_URL}/api/engine/skills", timeout=5)
    skills_data = r.json() if r.ok else []
    skills_count = len(skills_data) if isinstance(skills_data, list) else len(skills_data.get("skills", skills_data))
    log(f"GET /api/engine/skills → {r.status_code} 数量={skills_count}")

    # Hooks 列表
    r = requests.get(f"{BACKEND_URL}/api/hooks", timeout=5)
    hooks_count = len(r.json()) if r.ok else 0
    log(f"GET /api/hooks → {r.status_code} 数量={hooks_count}")

    return session_id


# ═══════════════════════════════════════════════════════════════
# Part 2: 真实 LLM API 端对端消息测试
# ═══════════════════════════════════════════════════════════════

def test_real_llm_message(session_id: str):
    section("Part 2: 真实 LLM 消息管线测试")

    payload = {
        "content": "我站在破旧的驿站门口，四周是荒凉的戈壁。向老板询问这里最近发生了什么？",
        "message_type": "action",
    }
    r = requests.post(
        f"{BACKEND_URL}/api/sessions/{session_id}/message",
        json=payload,
        timeout=15,
    )
    if r.status_code not in (200, 202):
        log(f"POST /message → {r.status_code}: {r.text[:200]}", ok=False)
        return None

    resp = r.json()
    stream_url = resp.get("stream_url", "")
    message_id = resp.get("message_id", "")
    log(f"POST /message → {r.status_code} message_id={message_id[:8] if message_id else '?'}... stream_url={stream_url}")

    # 消费 SSE 流
    sse_url = f"{BACKEND_URL}{stream_url}" if stream_url.startswith("/") else stream_url
    log(f"连接 SSE: {sse_url}")

    # SSE 事件类型（来自 backend/bus/event_types.py）:
    # part.updated  → data.delta = 流式文本片段
    # part.done     → data.content = 完整 Part 内容
    # agent.started / agent.ended → data.agent = agent名称
    # session.done / session.idle → 管线完成
    # session.error → 错误
    narrative_parts = []
    agents_seen = []
    start_ts = time.time()
    done = False

    try:
        with requests.get(sse_url, stream=True, timeout=120) as sse_r:
            for raw_line in sse_r.iter_lines(decode_unicode=True):
                if time.time() - start_ts > 110:
                    log("SSE 超时（110s），停止", ok=False)
                    break
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(raw_line[5:].strip())
                except Exception:
                    continue

                etype = evt.get("type", "")
                edata = evt.get("data", {})

                if etype == "part.updated":
                    delta = edata.get("delta", "")
                    if delta:
                        narrative_parts.append(delta)
                elif etype == "agent.started":
                    agents_seen.append(edata.get("agent", "?"))
                elif etype in ("session.done", "session.idle"):
                    log(f"{etype} → agents={agents_seen}")
                    done = True
                    break
                elif etype == "session.error":
                    # session.error 之后不再有 session.idle，主动停止
                    err_msg = edata.get('message') or edata.get('error') or json.dumps(edata)[:100]
                    has_narrative = len("".join(narrative_parts)) > 0
                    log(f"session.error (post-narrative={has_narrative}): {err_msg[:120]}", ok=has_narrative)
                    break  # 无论有没有叙事文本，session.error 后的 session.idle 不会到来

        full_text = "".join(narrative_parts)
        chars = len(full_text)
        elapsed = time.time() - start_ts
        log(f"叙事文本: {chars} 字 | 首100字: {full_text[:100].replace(chr(10), ' ')}")
        if chars >= 20:
            log(f"真实LLM管线通过（{chars}字叙事，{len(agents_seen)}个agents，耗时{elapsed:.1f}s）")
        else:
            log(f"叙事过短: {chars} 字（耗时{elapsed:.1f}s，done={done}）", ok=False)
            return None

    except Exception as e:
        log(f"SSE 消费失败: {e}", ok=False)
        return None

    return message_id


# ═══════════════════════════════════════════════════════════════
# Part 3: 浏览器 UI 测试（Playwright）
# ═══════════════════════════════════════════════════════════════

def test_browser_ui(session_id: str):
    section("Part 3: 浏览器 UI 测试 (Playwright)")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        import pytest
        pytest.skip("playwright 未安装，跳过浏览器 UI 测试")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # ── 3.1 首页 ──────────────────────────────────────────────
        page.goto(FRONTEND_URL)
        page.wait_for_load_state("networkidle", timeout=15000)
        ss = SCREENSHOT_DIR / f"{TIMESTAMP}_01_homepage.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"截图: {ss.name}")

        # 检查首页关键元素
        body_text = page.inner_text("body")
        has_title = "ZeroArsenal" in body_text or "zero-arsenal" in body_text.lower() or "会话" in body_text or "创建" in body_text
        log(f"首页加载 → body含关键词={has_title}")
        print(f"    首页文字摘要: {body_text[:150].replace(chr(10),' ')}")

        # ── 3.2 会话列表/导航 ────────────────────────────────────
        # 查找并截图现有会话
        try:
            page.wait_for_selector("a, button, [role='button']", timeout=5000)
        except PWTimeout:
            pass
        
        links = page.locator("a[href*='session'], a[href*='/s/']").all()
        log(f"首页会话链接数: {len(links)}")

        # ── 3.3 设置页面 ──────────────────────────────────────────
        page.goto(f"{FRONTEND_URL}/settings")
        page.wait_for_load_state("networkidle", timeout=10000)
        ss = SCREENSHOT_DIR / f"{TIMESTAMP}_02_settings.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"截图: {ss.name}")

        settings_text = page.inner_text("body")
        has_settings = any(kw in settings_text for kw in ["API", "LLM", "DeepSeek", "设置", "配置"])
        log(f"设置页加载 → 含配置关键词={has_settings}")

        # ── 3.4 Session 详情页（路由为 /sessions/$id）──────────────────────
        page.goto(f"{FRONTEND_URL}/sessions/{session_id}")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        page.wait_for_timeout(2000)

        ss = SCREENSHOT_DIR / f"{TIMESTAMP}_03_session_initial.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"截图: {ss.name}")

        session_text = page.inner_text("body")
        has_chat = any(kw in session_text for kw in ["输入", "发送", "Send", "消息", "驿站", "戈壁", "E2E"])
        log(f"会话页加载 → 含聊天关键词={has_chat}")

        # ── 3.5 尝试输入框交互 ────────────────────────────────────
        # 查找输入框
        input_sel = None
        for sel in ["textarea", "input[type='text']", "[placeholder*='输入']", "[placeholder*='message']"]:
            if page.locator(sel).count() > 0:
                input_sel = sel
                break

        if input_sel:
            page.locator(input_sel).first.fill("你好，我是新来的探险者。")
            page.wait_for_timeout(500)
            ss = SCREENSHOT_DIR / f"{TIMESTAMP}_04_input_filled.png"
            page.screenshot(path=str(ss), full_page=True)
            log(f"输入框填充成功 → 截图: {ss.name}")

            # 查找发送按钮
            send_btn = None
            for sel in ["button[type='submit']", "button:has-text('发送')", "button:has-text('Send')", "button:has-text('▶')"]:
                if page.locator(sel).count() > 0:
                    send_btn = sel
                    break
            
            if send_btn:
                page.locator(send_btn).first.click()
                page.wait_for_timeout(1500)
                ss = SCREENSHOT_DIR / f"{TIMESTAMP}_05_after_send.png"
                page.screenshot(path=str(ss), full_page=True)
                log(f"点击发送后截图: {ss.name}")
            else:
                log("未找到发送按钮", ok=False)
        else:
            log("未找到输入框", ok=False)

        # ── 3.6 侧栏面板测试 ─────────────────────────────────────
        # 尝试点击各面板 tab
        for tab_text in ["骰子", "章节", "世界", "角色", "记忆"]:
            btns = page.locator(f"button:has-text('{tab_text}'), [role='tab']:has-text('{tab_text}')").all()
            if btns:
                try:
                    btns[0].click()
                    page.wait_for_timeout(600)
                    ss = SCREENSHOT_DIR / f"{TIMESTAMP}_panel_{tab_text}.png"
                    page.screenshot(path=str(ss), full_page=True)
                    log(f"面板 [{tab_text}] → 截图: {ss.name}")
                except Exception as e:
                    log(f"面板 [{tab_text}] 点击失败: {e}", ok=False)

        # ── 3.7 骰子功能测试 ─────────────────────────────────────
        dice_btns = page.locator("button:has-text('D'), button:has-text('d'), button:has-text('骰子'), button:has-text('投')").all()
        if dice_btns:
            dice_btns[0].click()
            page.wait_for_timeout(1000)
            ss = SCREENSHOT_DIR / f"{TIMESTAMP}_06_dice.png"
            page.screenshot(path=str(ss), full_page=True)
            log(f"骰子操作截图: {ss.name}")
        else:
            log("未找到骰子按钮（跳过）")

        # ── 最终全页截图 ──────────────────────────────────────────
        ss = SCREENSHOT_DIR / f"{TIMESTAMP}_99_final_state.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"最终状态截图: {ss.name}")

        # Console errors
        browser.close()

    log("浏览器 UI 测试完成")


# ═══════════════════════════════════════════════════════════════
# Part 4: 扩展功能 API 测试
# ═══════════════════════════════════════════════════════════════

def test_extension_apis(session_id: str):
    section("Part 4: 扩展 & 工具 API 测试")

    # Agent Profile 列表
    r = requests.get(f"{BACKEND_URL}/api/agents/profiles", timeout=5)
    log(f"GET /api/agents/profiles → {r.status_code} 数量={len(r.json()) if r.ok else '?'}")

    # 等待速率限制恢复
    import time as _time; _time.sleep(2)

    # 记忆搜索
    r = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}/memory?q=驿站&top_k=5", timeout=5)
    mem_count = len(r.json()) if r.ok else ("限流" if r.status_code == 429 else "?")
    log(f"GET /memory?q=驿站 → {r.status_code} 记忆数={mem_count}", ok=r.ok)

    # 世界档案（含NPC）
    r = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}/world-archives", timeout=5)
    log(f"GET /world-archives → {r.status_code} 数量={len(r.json()) if r.ok else ('限流' if r.status_code == 429 else '?')}", ok=r.ok)

    # 章节树
    r = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}/chapters", timeout=5)
    log(f"GET /chapters → {r.status_code}")

    # Pending ASKs
    r = requests.get(f"{BACKEND_URL}/api/sessions/{session_id}/asks", timeout=5)
    log(f"GET /asks → {r.status_code}")

    # 工具列表
    r = requests.get(f"{BACKEND_URL}/api/tools", timeout=5)
    tools = r.json() if r.ok else []
    log(f"GET /api/tools → {r.status_code} 数量={len(tools) if isinstance(tools, list) else '?'}")

    # 骰子 roll API（正确路径，等待速率限制恢复）
    import time as _time; _time.sleep(2)
    r = requests.post(
        f"{BACKEND_URL}/api/engine/roll",
        json={"pool": 4, "threshold": 8, "reason": "E2E测试", "session_id": session_id},
        timeout=10,
    )
    if r.ok:
        roll = r.json()
        log(f"POST /api/engine/roll pool=4 → net={roll.get('net','?')} rolls={roll.get('rolls','?')} verdict={roll.get('verdict','?')}")
    elif r.status_code == 429:
        log(f"POST /api/engine/roll → 429 限流（端点被限流，未验证成功）", ok=False)
    else:
        log(f"POST /api/engine/roll → {r.status_code}: {r.text[:150]}", ok=False)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n{'#'*60}")
    print(f"  ZeroArsenal E2E 测试  [{TIMESTAMP}]")
    print(f"  Backend: {BACKEND_URL}")
    print(f"  Frontend: {FRONTEND_URL}")
    print(f"  Screenshots: {SCREENSHOT_DIR}")
    print(f"{'#'*60}")

    passed = 0
    failed = 0

    try:
        session_id = test_api_smoke()
        passed += 1
    except Exception as e:
        log(f"API Smoke 测试失败: {e}", ok=False)
        failed += 1
        session_id = None

    if session_id:
        try:
            test_real_llm_message(session_id)
            passed += 1
        except Exception as e:
            log(f"LLM消息测试失败: {e}", ok=False)
            failed += 1

        try:
            test_extension_apis(session_id)
            passed += 1
        except Exception as e:
            log(f"扩展API测试失败: {e}", ok=False)
            failed += 1

        try:
            test_browser_ui(session_id)
            passed += 1
        except Exception as e:
            log(f"浏览器UI测试失败: {e}", ok=False)
            import traceback
            traceback.print_exc()
            failed += 1

    # ── 汇总 ──────────────────────────────────────────────────
    section("测试汇总")
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = sum(1 for r in results if not r["ok"])
    print(f"  检查项: {len(results)}  通过: {ok_count}  失败: {fail_count}")

    # 截图列表
    screenshots = sorted(SCREENSHOT_DIR.glob(f"{TIMESTAMP}_*.png"))
    print(f"\n  截图文件 ({len(screenshots)} 张):")
    for s in screenshots:
        print(f"    - {s.name}")

    # 写入 JSON 报告
    report_path = SCREENSHOT_DIR / f"{TIMESTAMP}_report.json"
    report = {
        "timestamp": TIMESTAMP,
        "backend": BACKEND_URL,
        "frontend": FRONTEND_URL,
        "session_id": session_id,
        "results": results,
        "screenshots": [s.name for s in screenshots],
        "summary": {"total": len(results), "passed": ok_count, "failed": fail_count},
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON报告: {report_path}")

    if fail_count > 0:
        print(f"\n  ⚠️  {fail_count} 项检查失败")
        sys.exit(1)
    else:
        print(f"\n  🎉 全部检查通过！")


if __name__ == "__main__":
    main()
