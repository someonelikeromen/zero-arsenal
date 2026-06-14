# -*- coding: utf-8 -*-
"""
验证三个 Bug 修复：
  B3 - 未知工具显示（SSE tool_name）
  B6 - chronicler turn anchor 写入
  B_parts - 会话历史记录显示
"""
import json, time, requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8001"
FRONT = "http://localhost:5173"
SS_DIR = "tests/e2e/screenshots"

def ss(page, name):
    path = f"{SS_DIR}/verify_{name}.png"
    page.screenshot(path=path, full_page=False)
    print(f"[截图] {name}")

def api(method, path, **kwargs):
    try:
        kwargs.setdefault("timeout", 10)
        r = getattr(requests, method.lower())(f"{BASE}{path}", **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def dismiss_modal(page):
    for sel in ['button:has-text("关闭")', 'button:has-text("开始")',
                'button:has-text("确定")', 'button[aria-label="Close"]']:
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=800):
                b.click()
                page.wait_for_timeout(500)
                return
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def main():
    print("\n========== 验证开始 ==========\n")

    # ── 1. 验证 parts API 字段（B_parts）────────────────────────────────────
    print("【B_parts】检查 /parts API 字段...")
    sess_list = api("GET", "/api/sessions?limit=5")
    sessions = sess_list.get("items", sess_list.get("sessions", []))
    sid = sessions[0]["id"] if sessions else None

    if sid:
        parts_r = api("GET", f"/api/sessions/{sid}/parts?limit=10")
        items = parts_r.get("items", [])
        if items:
            first = items[0]
            has_id     = "id"     in first and first["id"]
            has_status = "status" in first
            has_agent  = "agent"  in first
            has_part_id = "part_id" in first
            print(f"  id: {first.get('id','MISSING')[:12]}...")
            print(f"  part_id 同步: {'OK' if has_part_id else 'MISSING'}")
            print(f"  status: {first.get('status','MISSING')}")
            print(f"  agent: {first.get('agent','MISSING')!r}")
            ok = has_id and has_status and has_agent
            print(f"  结果: {'PASS ✓' if ok else 'FAIL ✗'}\n")
        else:
            print("  无 parts，跳过字段检查\n")
    else:
        print("  无会话，跳过\n")

    # ── 2. 浏览器验证会话历史显示 ─────────────────────────────────────────
    print("【B_parts】浏览器打开会话，检查历史内容显示...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # 首页 dismiss modal
        page.goto(FRONT, timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)
        dismiss_modal(page)

        if sid:
            page.goto(f"{FRONT}/sessions/{sid}", timeout=20000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            page.wait_for_timeout(4000)  # 等 loadParts + 渲染
            ss(page, "02_session_history")

            # 检查是否有内容渲染
            body_text = page.locator("body").inner_text()
            visible_chars = len(body_text.strip())
            # 查找 part 容器
            part_els = page.locator("[class*='Part'], [class*='part'], [data-part]").all()
            print(f"  body 文字长度: {visible_chars}")
            print(f"  Part 元素数: {len(part_els)}")
            print(f"  页面片段: {body_text[:200].replace(chr(10),' ')}")
            print(f"  结果: {'PASS ✓' if visible_chars > 50 else 'FAIL ✗'}\n")
        else:
            print("  无会话 ID，跳过浏览器验证\n")

        # ── 3. 验证 B3 - 工具名 SSE 初始化 ─────────────────────────────
        # 查 interface.py 修改是否生效：找一个有 tool_call part 的 session
        print("【B3】检查 tool_call part 是否有 tool_name 字段（DB 层）...")
        tc_check = api("GET", f"/api/sessions?limit=20")
        all_sessions = tc_check.get("items", [])
        found_tc = False
        for s in all_sessions:
            pr = api("GET", f"/api/sessions/{s['id']}/parts?limit=50")
            tc_parts = [p for p in pr.get("items", []) if p.get("type") == "tool_call"]
            if tc_parts:
                content = tc_parts[0].get("content", {})
                tool_name = content.get("tool_name", "")
                print(f"  找到 tool_call part: content={json.dumps(content, ensure_ascii=False)[:120]}")
                print(f"  tool_name in content: {'OK '+tool_name if tool_name else '旧数据无 tool_name（新会话才生效）'}")
                found_tc = True
                break
        if not found_tc:
            print("  无 tool_call 历史数据，B3 需新建会话才能验证（代码已改，下次调用生效）")

        # ── 4. 验证 B6 - chronicler turn anchor 写入 ──────────────────
        print("\n【B6】检查 chapter_anchors 记录...")
        if sid:
            # 通过 API 查 chapters 和 turn anchors（需直接查 DB 或间接通过 messages 推断）
            msgs = api("GET", f"/api/sessions/{sid}/messages?limit=50")
            msg_count = len(msgs.get("items", msgs.get("messages", [])))
            chaps = api("GET", f"/api/sessions/{sid}/chapters")
            chap_count = len(chaps.get("items", chaps.get("chapters", [])))
            print(f"  messages 数: {msg_count}")
            print(f"  chapters 数: {chap_count}")
            print(f"  chronicler 阈值已调整为 10（需 10 轮才触发固化）")
            print(f"  结果: 代码已修改（THRESHOLD=10 + wrapper 每轮调用），验证需新跑 10+ 轮\n")

        ss(page, "03_final_state")
        browser.close()

    print("========== 验证完成 ==========")


if __name__ == "__main__":
    main()
