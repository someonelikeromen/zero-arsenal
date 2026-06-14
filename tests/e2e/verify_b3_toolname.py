# -*- coding: utf-8 -*-
"""
验证 B3：发送一条消息，观察 SSE part.created 事件是否携带 tool_name。
通过拦截 SSE 流完成验证。
"""
import json, time, requests, threading
from playwright.sync_api import sync_playwright

BASE  = "http://127.0.0.1:8001"
FRONT = "http://localhost:5173"
SS    = "tests/e2e/screenshots"

def ss(page, name):
    page.screenshot(path=f"{SS}/b3_{name}.png", full_page=False)
    print(f"[截图] {name}")

def get_session_with_parts():
    """找一个有 parts 的会话，或取第一个会话"""
    r = requests.get(f"{BASE}/api/sessions?limit=10", timeout=5).json()
    sessions = r.get("items", r.get("sessions", []))
    if not sessions:
        return None
    for s in sessions:
        pr = requests.get(f"{BASE}/api/sessions/{s['id']}/parts?limit=5", timeout=5).json()
        if pr.get("items"):
            return s["id"]
    return sessions[0]["id"]

def listen_sse_for_tool_created(session_id, timeout=60):
    """订阅 SSE，返回首次出现 tool_name 的 part.created 事件"""
    found = []
    stop = threading.Event()

    def _run():
        try:
            with requests.get(f"{BASE}/api/sessions/{session_id}/events",
                              stream=True, timeout=timeout + 5) as resp:
                for line in resp.iter_lines():
                    if stop.is_set():
                        break
                    if not line:
                        continue
                    text = line.decode("utf-8", errors="replace")
                    if text.startswith("data:"):
                        try:
                            ev = json.loads(text[5:].strip())
                            etype = ev.get("type", "")
                            if etype == "part.created":
                                d = ev.get("data", {})
                                found.append({
                                    "type": etype,
                                    "part_type": d.get("part_type"),
                                    "tool_name": d.get("tool_name"),
                                    "has_tool_name": "tool_name" in d,
                                })
                                if d.get("part_type") == "tool_call":
                                    stop.set()
                                    break
                        except Exception:
                            pass
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return found, stop, t


def dismiss_modal(page):
    for sel in ['button:has-text("关闭")', 'button:has-text("开始")',
                'button:has-text("确定")', '[aria-label="Close"]']:
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
    except Exception:
        pass


def main():
    sid = get_session_with_parts()
    if not sid:
        print("[ERROR] 没有可用会话")
        return

    print(f"使用会话: {sid}")

    # 订阅 SSE 监听 tool_call part.created
    sse_found, sse_stop, sse_thread = listen_sse_for_tool_created(sid, timeout=90)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        # 导航进会话
        page.goto(f"{FRONT}/sessions/{sid}", timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        page.wait_for_timeout(3000)
        dismiss_modal(page)
        ss(page, "01_before_send")

        # 找输入框并发送一条触发工具调用的消息
        input_sel = "textarea, input[type='text'], [contenteditable='true']"
        try:
            inp = page.locator(input_sel).last
            inp.wait_for(timeout=5000)
            inp.click()
            inp.fill("查询我现在的角色状态")
            ss(page, "02_typed")
            page.keyboard.press("Enter")
            print("消息已发送，等待 SSE 事件...")
            ss(page, "03_sent")
        except Exception as e:
            print(f"[WARN] 发送消息失败: {e}")
            ss(page, "03_send_failed")

        # 等最多 90 秒等待 tool_call part.created
        waited = 0
        while not sse_stop.is_set() and waited < 90:
            time.sleep(2)
            waited += 2
            if waited % 10 == 0:
                print(f"  等待中... {waited}s, 已捕获事件: {len(sse_found)}")

        sse_stop.set()
        sse_thread.join(timeout=3)

        ss(page, "04_after_response")
        page_text = page.locator("body").inner_text()

        print(f"\n共捕获 part.created 事件: {len(sse_found)}")
        tc_events = [e for e in sse_found if e.get("part_type") == "tool_call"]
        other_events = [e for e in sse_found if e.get("part_type") != "tool_call"]

        print(f"  tool_call 类型: {len(tc_events)}")
        print(f"  其他类型: {len(other_events)}")

        if tc_events:
            for ev in tc_events:
                tool_name = ev.get("tool_name")
                has = ev.get("has_tool_name")
                print(f"\n  [B3 验证] part.created (tool_call):")
                print(f"    tool_name 存在: {'YES ✓' if has else 'NO ✗'}")
                print(f"    tool_name 值: {tool_name!r}")
                print(f"    结果: {'PASS ✓' if tool_name else 'FAIL ✗'}")
        else:
            print("\n  [B3] 本次对话未触发工具调用（LLM 未使用工具）")
            print("  可能原因：消息内容未触发工具，或 LLM 直接文本回复")
            # 检查页面是否有任何叙事内容
            has_content = len(page_text.strip()) > 100
            print(f"  页面有响应内容: {'YES' if has_content else 'NO'}")

        browser.close()

    print("\n===== 验证完成 =====")


if __name__ == "__main__":
    main()
