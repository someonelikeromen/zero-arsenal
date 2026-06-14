"""
ZeroArsenal 全流程用户模拟测试（Playwright 浏览器代理 + 真实 LLM + 无限武库）
========================================================================
流程：创建角色 → 创建世界 → 开始会话（infinite_arsenal）→
      30轮真实LLM对话（含商店/评估/抽卡等专属工具触发）→
      部分回退 → 记忆压缩验证 → 数据完整性核查

运行前提：后端（8001）+ 前端（5173）同时运行，DeepSeek API Key 已配置。

运行命令：
  python tests/e2e/test_sim_full_flow.py

可选环境变量：
  FRONTEND_URL   默认 http://localhost:5173
  BACKEND_URL    默认 http://127.0.0.1:8001
  HEADLESS       默认 1（0=可见浏览器，方便调试）
  ROUNDS         默认 30（对话轮数）
  REVERT_AT      默认 25（在第几轮触发回退）
  LLM_TIMEOUT_MS 默认 120000（单轮 LLM 等待上限，ms）

注：脚本式伪 E2E，标注 stub；CI 以 -m "not stub" 排除。
"""
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

# ── 配置 ────────────────────────────────────────────────────────────────────
FRONTEND  = os.environ.get("FRONTEND_URL",   "http://localhost:5173")
BACKEND   = os.environ.get("BACKEND_URL",    "http://127.0.0.1:8001")
HEADLESS  = os.environ.get("HEADLESS", "1") != "0"
ROUNDS    = int(os.environ.get("ROUNDS",    "30"))
REVERT_AT = int(os.environ.get("REVERT_AT", "25"))
LLM_MS    = int(os.environ.get("LLM_TIMEOUT_MS", "120000"))

TS     = datetime.now().strftime("%Y%m%d_%H%M%S")
SS_DIR = pathlib.Path(__file__).parent.parent / "screenshots" / f"sim_full_{TS}"
SS_DIR.mkdir(parents=True, exist_ok=True)


# ── 阶段意图提示（每 5 轮一个阶段，LLM 驱动叙事，玩家给开放方向）─────────────
PHASE_INTENTS = [
    # Phase 1: 落地探索（R1-5）
    "环顾四周，了解当前所在地，感受手中铁剑传来的武器共鸣。",
    "向附近的路人或店主询问，了解这片大陆的武器体系和基本规则。",
    "前往最近的武器铺，观察各类武器，打探当地行情和品阶分布。",
    "尝试感应手中铁剑的器灵，进行一次简单的共鸣练习，看看有什么反应。",
    "根据目前了解的情况，制定初步计划，朝最有利的方向行动。",
    # Phase 2: 主神商店（R6-10）——触发 shop/evaluate/gacha 工具
    "前往主神空间，查看当前积分和可兑换的物品列表。",
    "在主神商店仔细浏览武器类目，询问DM有什么适合当前阶段的推荐。",
    "请DM帮我评估一下手中铁剑的器灵状态、共鸣潜力和当前价值。",
    "尝试用当前积分兑换或购买一件能提升实力的物品，请DM根据积分决定能换什么。",
    "申请进行一次主神抽卡，消耗积分看看能获得什么惊喜。",
    # Phase 3: 野外探险与战斗（R11-15）
    "按照DM叙事的走向，前往下一个地点或应对眼前出现的情况。",
    "遭遇敌人或危险时，使用手中武器主动迎战，感受武器共鸣在战斗中的变化。",
    "战斗结束后，向主神提交本次战斗结果，结算奖励，查看积分变化。",
    "寻找进一步提升武器共鸣度的方法，尝试与器灵进行更深层次的沟通。",
    "根据当前局势和DM给出的提示，作出最符合角色性格的判断并执行。",
    # Phase 4: 深入剧情（R16-20）——触发章节压缩阈值
    "沿着DM叙事的线索，主动深入探查这片区域隐藏的秘密或危险。",
    "遇到新的NPC时，主动建立联系，尝试获取有价值的情报或合作。",
    "整理目前拥有的物品、武器和积分，向DM询问下一步最优的强化路线。",
    "面对DM设置的选择或危机，坚定地作出符合角色性格的决策并承担后果。",
    "全力推进主线，尽可能触发更多有意思的世界事件和NPC互动。",
    # Phase 5: 新章节强化（R21-25）——压缩后验证管线
    "新章节开始，从当前位置出发继续探索，感受之前积累带来的变化。",
    "利用之前获得的物品和积分，进行一次系统性的装备强化或技能升级。",
    "主动前往一处听说更危险的区域，寻求更强的挑战和更好的武器。",
    "与之前遇到的NPC或势力进行深度交涉，推动主线剧情向前发展。",
    "根据这几章的经历和当前状态，制定清晰的下一步计划并立刻执行。",
    # Phase 6: 终章冲刺（R26-30）——最终管线压力测试
    "朝着目前最重要的目标全力冲刺，调动一切可用的资源和手段。",
    "面对关键时刻，使用目前最强的武器和已掌握的技法，全力一搏。",
    "处理仍未解决的支线任务或NPC关系，为这段旅程做好收尾。",
    "全面盘点：查看当前积分、所有武器状态、角色属性，确认当前综合实力。",
    "向DM请求一次总结，回顾这段旅程的关键成就和当前状态快照。",
]


# ── IssueRecorder：发现即写盘 ─────────────────────────────────────────────────
class IssueRecorder:
    """所有问题发现即写入 JSONL，不等最终汇总。"""

    def __init__(self, ss_dir: pathlib.Path) -> None:
        self.ss_dir = ss_dir
        self.log_file = ss_dir / "issues.jsonl"
        self.issues: list[dict] = []

    def record(self, page, level: str, category: str, detail: str, round_num: int = -1) -> None:
        """level: ERROR / WARNING / INFO"""
        ts = datetime.now().isoformat()
        ss_name = f"issue_{len(self.issues):03d}_{category}_{ts[:19].replace(':', '-')}.png"
        try:
            page.screenshot(path=str(self.ss_dir / ss_name), full_page=False)
        except Exception as e:
            ss_name = f"(截图失败: {e})"
        entry = {
            "ts": ts, "level": level, "category": category,
            "detail": detail, "round": round_num, "screenshot": ss_name,
        }
        self.issues.append(entry)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        icon = "🔴" if level == "ERROR" else "🟡" if level == "WARNING" else "ℹ️"
        print(f"  {icon} [{level}][R{round_num}] {category}: {detail[:120]}")


# ── 辅助函数 ─────────────────────────────────────────────────────────────────
def ss(page, name: str) -> None:
    """截图，失败时静默。"""
    try:
        page.screenshot(path=str(SS_DIR / name), full_page=False)
    except Exception as e:
        print(f"  ⚠ 截图 {name} 失败: {e}")


def log_step(results: list, name: str, status: str, detail: str = "") -> None:
    icon = {"ok": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(status, "?")
    msg = f"  {icon} {name}" + (f"  ({detail[:80]})" if detail else "")
    print(msg)
    results.append({"step": name, "status": status, "detail": detail, "ts": datetime.now().isoformat()})


def nav_tab(page, label: str) -> None:
    """点击主页左侧竖向导航 Tab。"""
    for sel in [f"button:has-text('{label}')", f"[data-tab='{label}']"]:
        el = page.locator(sel).first
        if el.count():
            el.click()
            page.wait_for_timeout(600)
            return
    print(f"  ⚠ 未找到 Tab 按钮: {label}")


def dismiss_modal(page) -> None:
    """关闭首次启动的主题选择弹窗（如有）。"""
    try:
        btn = page.locator("button:has-text('开始使用')").first
        if btn.count() and btn.is_visible(timeout=2000):
            btn.click()
            page.wait_for_timeout(400)
    except Exception:
        pass


def wait_for_idle(page, timeout_ms: int = 120_000) -> float:
    """
    等待 LLM 管线完成。
    InputBar 在 sending=true 时：textarea disabled + 显示「停止」按钮。
    完成后：恢复「发送」按钮（id=__send_btn）。
    """
    start = time.time()
    # 等待 sending 开始（stop 按钮出现 或 textarea disabled）
    try:
        page.wait_for_selector("button:has-text('停止')", state="visible", timeout=6000)
    except Exception:
        pass  # 可能太快跳过 sending 状态
    # 等待 sending 结束（发送按钮回来）
    page.wait_for_selector("#__send_btn", state="attached", timeout=timeout_ms)
    page.wait_for_timeout(500)
    return time.time() - start


def get_latest_narrative(page) -> str:
    """
    提取当前页面最后一条助手叙事文本（取各候选选择器最后一个可见元素）。
    """
    candidates = [
        ".narrative-text",
        "[data-role='assistant']",
        ".message-assistant",
        ".prose",
        ".whitespace-pre-wrap",
    ]
    for sel in candidates:
        els = page.locator(sel).all()
        if els:
            try:
                return els[-1].inner_text(timeout=3000)[:400]
            except Exception:
                continue
    # 后备：取整个 MessageThread 的最后 400 字符
    try:
        body = page.locator(".message-thread, #message-thread, [class*='MessageThread']").first
        if body.count():
            return body.inner_text(timeout=3000)[-400:]
    except Exception:
        pass
    return ""


def check_round_response(page, recorder: IssueRecorder, round_num: int, narrative: str, elapsed: float) -> None:
    """每轮 LLM 响应完成后立即检查，问题发现即截图写盘。"""
    # 1. 叙事长度
    if len(narrative.strip()) < 30:
        recorder.record(page, "ERROR", "empty_response",
                        f"叙事过短 {len(narrative)}字", round_num)
    # 2. 错误关键词
    ERROR_WORDS = ["[错误]", "系统错误", "LLM调用失败", "Internal Server Error",
                   "500 Internal", "连接失败", "超时", "请重试"]
    for w in ERROR_WORDS:
        if w in narrative:
            recorder.record(page, "ERROR", "error_in_narrative",
                            f"叙事含错误词「{w}」: {narrative[:120]}", round_num)
            break
    # 3. 响应超慢
    if elapsed > 90:
        recorder.record(page, "WARNING", "slow_response",
                        f"响应耗时 {elapsed:.1f}s", round_num)
    # 4. UI Toast 错误
    try:
        for sel in [".toast-error", "[data-type='error']", ".error-toast",
                    "[class*='toast'][class*='error']", "[class*='notify'][class*='error']"]:
            toast = page.locator(sel).first
            if toast.count() and toast.is_visible(timeout=500):
                recorder.record(page, "ERROR", "ui_toast_error",
                                toast.inner_text(timeout=1000)[:120], round_num)
                break
    except Exception:
        pass
    # 5. 页面崩溃
    try:
        body_len = len(page.inner_text("body", timeout=3000))
        if body_len < 100:
            recorder.record(page, "ERROR", "page_crash",
                            f"页面内容异常少 {body_len}字", round_num)
    except Exception:
        pass


def check_tool_hints(page, recorder: IssueRecorder, round_num: int, narrative: str) -> None:
    """Phase 2（R6-10）：检查工具触发痕迹。"""
    TOOL_HINTS = ["主神空间", "积分", "兑换", "评估", "抽卡", "战斗奖励",
                  "tier", "★", "batch_points", "武器", "器灵", "品阶"]
    has_hint = any(h in narrative for h in TOOL_HINTS)
    if not has_hint:
        recorder.record(page, "WARNING", "tool_not_triggered",
                        f"Phase2工具轮叙事未见工具痕迹: {narrative[:100]}", round_num)


# ── 主测试流程 ───────────────────────────────────────────────────────────────
def main() -> None:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("❌ playwright 未安装。请运行: pip install playwright && playwright install chromium")
        sys.exit(1)

    step_results: list[dict] = []
    console_errors: list[str] = []
    network_errors: list[str] = []
    round_ok_count = 0
    round_total_elapsed = 0.0

    # 共享状态，由 response 拦截器填充
    captured: dict = {
        "character_id": None,
        "world_id":     None,
        "session_id":   None,
        "msg_id":       None,          # 最近一轮捕获的 message_id
    }
    round_ids: dict[int, str] = {}    # round_num → message_id
    revert_target_msg_id: str | None = None

    recorder = IssueRecorder(SS_DIR)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 0: 前置健康检查（requests，不走浏览器）
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 65)
    print("  STEP 0: 前置健康检查")
    print("=" * 65)
    try:
        r = requests.get(f"{BACKEND}/health", timeout=5)
        assert r.status_code == 200, f"health 返回 {r.status_code}"
        info_r = requests.get(f"{BACKEND}/api/system/info", timeout=10)
        info = info_r.json() if info_r.ok else {}
        log_step(step_results, "STEP0 健康检查", "ok",
                 f"tools={info.get('tools','?')} plugins={info.get('plugins','?')}")
    except Exception as e:
        log_step(step_results, "STEP0 健康检查", "fail", str(e))
        print("❌ 后端不可用，终止测试。")
        return

    try:
        requests.get(FRONTEND, timeout=5)
        log_step(step_results, "STEP0 前端可访问", "ok")
    except Exception as e:
        log_step(step_results, "STEP0 前端可访问", "fail", str(e))
        print("❌ 前端不可用，终止测试。")
        return

    print(f"\n📁 截图目录: {SS_DIR}")
    print(f"📋 问题日志: {SS_DIR / 'issues.jsonl'}")
    print(f"   对话轮数: {ROUNDS}  回退位置: R{REVERT_AT}\n")

    # ══════════════════════════════════════════════════════════════════════
    # 启动浏览器
    # ══════════════════════════════════════════════════════════════════════
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS, slow_mo=100)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        current_round = [0]  # 用 list 让 closure 可修改

        # ── 监控钩子 ───────────────────────────────────────────────────────
        def on_console(msg):
            if msg.type in ("error", "warning"):
                text = msg.text[:300]
                console_errors.append({"type": msg.type, "text": text, "ts": datetime.now().isoformat()})
                if msg.type == "error" and "ResizeObserver" not in text and "favicon" not in text:
                    recorder.record(page, "WARNING", "console_error", text, current_round[0])

        def on_response(resp):
            url = resp.url
            status = resp.status
            if status >= 400 and "/api/" in url:
                detail = f"{status} {url}"
                if status >= 500:
                    recorder.record(page, "ERROR", "network_5xx", detail, current_round[0])
                else:
                    recorder.record(page, "WARNING", "network_4xx", detail, current_round[0])
                network_errors.append(detail)

            # 拦截角色生成保存响应
            if "/api/characters" in url and resp.request.method == "POST" and status == 200:
                try:
                    body = resp.json()
                    cid = body.get("character_id") or body.get("id")
                    if cid and not captured["character_id"]:
                        captured["character_id"] = cid
                        print(f"  📌 character_id 捕获: {cid[:8]}...")
                except Exception:
                    pass

            # 拦截世界创建响应
            if "/api/worlds" in url and resp.request.method == "POST" and status == 200:
                try:
                    body = resp.json()
                    wid = body.get("world_id") or body.get("id")
                    if wid and not captured["world_id"]:
                        captured["world_id"] = wid
                        print(f"  📌 world_id 捕获: {wid[:8]}...")
                except Exception:
                    pass

            # 拦截会话创建响应
            if "/api/sessions" in url and resp.request.method == "POST" and status == 200:
                try:
                    body = resp.json()
                    sid = body.get("session_id") or body.get("id")
                    if sid and not captured["session_id"] and "message" not in url and "fork" not in url:
                        captured["session_id"] = sid
                        print(f"  📌 session_id 捕获: {sid[:8]}...")
                except Exception:
                    pass

            # 拦截发消息响应
            if "/message" in url and resp.request.method == "POST" and status in (200, 202):
                try:
                    body = resp.json()
                    mid = body.get("message_id")
                    if mid:
                        captured["msg_id"] = mid
                except Exception:
                    pass

        page.on("console", on_console)
        page.on("response", on_response)

        # ══════════════════════════════════════════════════════════════════
        # STEP 1: 角色创建（人物 Tab → 背景创建 → AI生成 → 保存）
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print("  STEP 1: 角色创建（背景创建模式 + 无限武库插件）")
        print("=" * 65)
        try:
            page.goto(FRONTEND, timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            dismiss_modal(page)
            ss(page, "01a_home.png")

            # 导航到人物 Tab
            nav_tab(page, "人物")
            page.wait_for_timeout(500)
            ss(page, "01b_char_tab.png")

            # 点击创建人物按钮
            created_modal = False
            for btn_sel in ["button:has-text('+ 创建人物')", "button:has-text('创建人物')",
                            "button:has-text('创建第一个人物')"]:
                btn = page.locator(btn_sel).first
                if btn.count() and btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(600)
                    created_modal = True
                    break
            assert created_modal, "未找到创建人物按钮"
            ss(page, "01c_create_modal.png")

            # Step 0: 选择「背景创建」
            bg_btn = page.locator("button:has-text('背景创建')").first
            assert bg_btn.count(), "未找到「背景创建」模式按钮"
            bg_btn.click()
            page.wait_for_timeout(400)
            ss(page, "01d_mode_selected.png")

            # Step 1: 填写基础信息
            # 名称
            name_input = page.locator("input[placeholder*='角色名称']").first
            if not name_input.count():
                name_input = page.locator("input").first
            name_input.fill("武者苏力")

            # 选择插件 infinite_arsenal
            plugin_sel = page.locator("select").first
            if plugin_sel.count():
                plugin_sel.select_option(value="infinite_arsenal")
                page.wait_for_timeout(200)

            # 背景文本（仅在 background 模式下显示）
            bg_textarea = page.locator("textarea[placeholder*='背景']").first
            if not bg_textarea.count():
                bg_textarea = page.locator("textarea").first
            bg_textarea.fill(
                "来自现代的软件工程师，意外穿越到武器意志显化的高武世界。"
                "性格理性冷静，喜欢用工程思维分析问题。"
                "初到此地，手持一把普通铁剑，正在摸索这个世界的武器共鸣体系。"
                "知道这个世界拥有主神空间，可以用积分兑换各类武器和技能。"
            )
            ss(page, "01e_filled.png")

            # 点击「生成角色」
            gen_btn = page.locator("button:has-text('生成角色')").first
            assert gen_btn.count(), "未找到「生成角色」按钮"
            gen_btn.click()
            print("  ⏳ AI 角色生成中（最多 120s）...")

            # 等待步骤 4（预览 + 保存），出现「保存为模板」按钮
            page.wait_for_selector("button:has-text('保存为模板')", timeout=120000)
            ss(page, "01f_generated.png")
            print("  ✓ 角色生成完成，进入预览")

            # 保存
            save_btn = page.locator("button:has-text('保存为模板')").first
            save_btn.click()
            page.wait_for_timeout(2000)
            ss(page, "01g_saved.png")

            char_id = captured.get("character_id")
            log_step(step_results, "STEP1 角色创建", "ok" if char_id else "warn",
                     f"character_id={char_id or '未捕获'}")
        except Exception as e:
            recorder.record(page, "ERROR", "step1_char_create", str(e))
            ss(page, "01_err.png")
            log_step(step_results, "STEP1 角色创建", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 2: 世界创建（世界 Tab + API 写入 lore）
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print("  STEP 2: 世界创建（神魔大陆·无限武库）")
        print("=" * 65)
        try:
            # 确保回到主页
            if "/sessions/" in page.url:
                page.goto(FRONTEND, timeout=10000)
                page.wait_for_load_state("networkidle")
                dismiss_modal(page)

            nav_tab(page, "世界")
            page.wait_for_timeout(500)
            ss(page, "02a_world_tab.png")

            # 点击「+ 新建世界」
            for btn_sel in ["button:has-text('+ 新建世界')", "button:has-text('新建世界')",
                            "button:has-text('创建世界')"]:
                btn = page.locator(btn_sel).first
                if btn.count() and btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            ss(page, "02b_create_form.png")

            # 填写世界名称
            name_input = page.locator("input[placeholder*='世界名称'], input[placeholder*='名称']").first
            if name_input.count():
                name_input.fill("神魔大陆·无限武库")

            # 填写描述
            desc_textarea = page.locator("textarea[placeholder*='描述'], textarea[placeholder*='description']").first
            if desc_textarea.count():
                desc_textarea.fill(
                    "武器意志显化的高武世界。武器拥有自己的器灵，与持有者共鸣越深则越强大。"
                    "武器品阶分九级：凡品→灵品→玄品→地品→天品→宗品→王品→皇品→神品。"
                    "主神空间可以用积分兑换神器和技能书。"
                )

            # 提交创建
            for btn_sel in ["button:has-text('创建')", "button:has-text('确认')",
                            "button:has-text('保存')", "button[type='submit']"]:
                btn = page.locator(btn_sel).first
                if btn.count() and btn.is_visible(timeout=1000):
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            ss(page, "02c_created.png")

            world_id = captured.get("world_id")
            if not world_id:
                # 后备：从 API 列表拿最新世界
                try:
                    r = requests.get(f"{BACKEND}/api/worlds", timeout=5)
                    if r.ok:
                        worlds = r.json().get("worlds", [])
                        if worlds:
                            world_id = worlds[-1]["id"]
                            captured["world_id"] = world_id
                            print(f"  📌 world_id 后备获取: {world_id[:8]}...")
                except Exception:
                    pass

            # 通过 API 写入 2 条 lore（浏览器内操作复杂，直接 API 等效）
            if world_id:
                lore_entries = [
                    {"title": "武器品阶体系",
                     "content": "凡品 < 灵品 < 玄品 < 地品 < 天品 < 宗品 < 王品 < 皇品 < 神品。"
                                "品阶越高，器灵意志越强，战力上限越高。相差3阶以上则无法抗衡。",
                     "archive_type": "rule"},
                    {"title": "主神空间规则",
                     "content": "每次完成任务、战斗、探索可获得积分。积分可在主神商店兑换武器、"
                                "强化材料、技能书、特殊道具。抽卡消耗积分，有保底机制。",
                     "archive_type": "lore"},
                ]
                written = 0
                for entry in lore_entries:
                    try:
                        r = requests.post(f"{BACKEND}/api/worlds/{world_id}/archives",
                                          json=entry, timeout=5)
                        if r.ok:
                            written += 1
                    except Exception:
                        pass
                print(f"  📎 写入 lore 条目: {written}/2")

            log_step(step_results, "STEP2 世界创建", "ok" if world_id else "warn",
                     f"world_id={world_id or '未获取'}")
            ss(page, "02d_done.png")
        except Exception as e:
            recorder.record(page, "ERROR", "step2_world_create", str(e))
            ss(page, "02_err.png")
            log_step(step_results, "STEP2 世界创建", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 3: 会话创建（会话 Tab → infinite_arsenal + 选世界/角色 → 开场）
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print("  STEP 3: 会话创建（infinite_arsenal）")
        print("=" * 65)
        try:
            if "/sessions/" in page.url:
                page.goto(FRONTEND, timeout=10000)
                page.wait_for_load_state("networkidle")
                dismiss_modal(page)

            nav_tab(page, "会话")
            page.wait_for_timeout(500)

            # 点击「+ 新建会话」展开表单
            new_btn = page.locator("button:has-text('+ 新建会话'), button:has-text('新建会话')").first
            if new_btn.count():
                new_btn.click()
                page.wait_for_timeout(600)
            ss(page, "03a_new_session_form.png")

            # 填写会话标题
            title_input = page.locator("input[placeholder*='标题']").first
            if title_input.count():
                title_input.fill(f"无限武库全流程_{TS}")

            # 选择插件 infinite_arsenal
            plugin_select = page.locator("select").first
            if plugin_select.count():
                plugin_select.select_option(value="infinite_arsenal")
                page.wait_for_timeout(300)

            # 选择世界（卡片按钮，匹配名称）
            world_id = captured.get("world_id")
            if world_id:
                world_card = page.locator(f"button:has-text('神魔大陆')").first
                if world_card.count():
                    world_card.click()
                    page.wait_for_timeout(200)
                else:
                    # 按 world_id 选第2张卡（跳过「不使用」）
                    cards = page.locator(".grid button, .card-world").all()
                    if len(cards) > 1:
                        cards[1].click()
                        page.wait_for_timeout(200)

            # 选择角色（卡片按钮，匹配名称）
            char_btn = page.locator("button:has-text('武者苏力')").first
            if char_btn.count():
                char_btn.click()
                page.wait_for_timeout(200)
            ss(page, "03b_session_configured.png")

            # 提交：点击「开始会话」
            start_btn = page.locator("button:has-text('开始会话')").first
            assert start_btn.count(), "未找到「开始会话」按钮"
            start_btn.click()
            print("  ⏳ 等待进入会话页面...")
            page.wait_for_url("**/sessions/**", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            ss(page, "03c_session_page.png")

            # 从 URL 获取 session_id
            url_parts = page.url.split("/sessions/")
            if len(url_parts) > 1:
                sid_from_url = url_parts[-1].split("?")[0].strip("/")
                if sid_from_url:
                    captured["session_id"] = sid_from_url
            session_id = captured.get("session_id")
            print(f"  📌 session_id: {session_id}")

            # 等待开场叙述完成（系统自动触发或需手动触发）
            print("  ⏳ 等待开场叙述完成...")
            try:
                # 如果有「开始」按钮则点击
                opening_btn = page.locator("button:has-text('开始'), button:has-text('生成开场')").first
                if opening_btn.count() and opening_btn.is_visible(timeout=3000):
                    opening_btn.click()
            except Exception:
                pass
            # 等待输入栏就绪
            try:
                page.wait_for_selector("#__send_btn", state="attached", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            ss(page, "03d_opening.png")

            log_step(step_results, "STEP3 会话创建", "ok" if session_id else "warn",
                     f"session_id={session_id or '未获取'}")
        except Exception as e:
            recorder.record(page, "ERROR", "step3_session_create", str(e))
            ss(page, "03_err.png")
            log_step(step_results, "STEP3 会话创建", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 4: 30 轮 LLM 驱动对话
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print(f"  STEP 4: {ROUNDS} 轮 LLM 驱动对话（infinite_arsenal）")
        print("=" * 65)

        session_id = captured.get("session_id")
        round_ok_count = 0
        round_total_elapsed = 0.0

        for rn in range(1, ROUNDS + 1):
            current_round[0] = rn
            intent = PHASE_INTENTS[(rn - 1) % len(PHASE_INTENTS)]
            print(f"\n── Round {rn:02d}/{ROUNDS} ─────────────────────────────────────")
            print(f"  意图: {intent[:60]}...")

            try:
                # 找 textarea（必须 enabled）
                textarea = page.locator("textarea:not([disabled])").last
                if not textarea.count():
                    textarea = page.locator("textarea").last
                textarea.fill(intent)
                ss(page, f"04_r{rn:02d}_before.png")

                # 拦截 message_id
                captured["msg_id"] = None
                # 发送：按 Enter
                textarea.press("Enter")
                t_start = time.time()

                # 等待 LLM 完成
                elapsed = wait_for_idle(page, LLM_MS)
                round_total_elapsed += elapsed

                # 获取叙事
                narrative = get_latest_narrative(page)
                narrative_len = len(narrative.strip())

                # 记录 message_id
                mid = captured.get("msg_id")
                if mid:
                    round_ids[rn] = mid
                if rn == REVERT_AT:
                    revert_target_msg_id = mid
                    print(f"  ⭐ 记录回退目标 msg_id: {mid}")

                # 截图
                ss(page, f"04_r{rn:02d}_response.png")

                # 实时质量检查
                check_round_response(page, recorder, rn, narrative, elapsed)

                # Phase 2 工具检查（R6-10）
                if 6 <= rn <= 10:
                    check_tool_hints(page, recorder, rn, narrative)

                # 记忆压缩检查点（第20轮后）
                if rn == 20 and session_id:
                    try:
                        r = requests.get(f"{BACKEND}/api/sessions/{session_id}", timeout=5)
                        if r.ok:
                            # current_chapter 是 dict（含 is_consolidated）或 None
                            cur_ch = r.json().get("current_chapter")
                            is_cons = cur_ch.get("is_consolidated", False) if isinstance(cur_ch, dict) else False
                            ch_title = cur_ch.get("title", "?") if isinstance(cur_ch, dict) else "?"
                            if not is_cons:
                                recorder.record(page, "WARNING", "no_chapter_advance",
                                                f"第20轮后章节未固化: title={ch_title}", rn)
                            else:
                                print(f"  📊 章节压缩检查: is_consolidated=True title={ch_title} ✓")
                    except Exception as ce:
                        print(f"  ⚠ 章节压缩检查失败: {ce}")

                # 每 5 轮打印进度 + 角色卡状态
                if rn % 5 == 0:
                    print(f"\n  📊 进度 R{rn}/{ROUNDS} | 平均耗时 {round_total_elapsed/rn:.1f}s/轮")
                    if session_id:
                        try:
                            cr = requests.get(f"{BACKEND}/api/sessions/{session_id}/character", timeout=5)
                            if cr.ok:
                                char = cr.json().get("character", cr.json())
                                meta = char.get("meta", {}) if isinstance(char, dict) else {}
                                inv = char.get("inventory", []) if isinstance(char, dict) else []
                                print(f"  👤 角色卡: battle_points={meta.get('battle_points','?')} "
                                      f"weapon_mastery={meta.get('weapon_mastery','?')} "
                                      f"inventory={len(inv)}件")
                        except Exception:
                            pass

                print(f"  ✓ R{rn} | {elapsed:.1f}s | {narrative_len}字 | {narrative[:80].replace(chr(10),' ')}")
                if narrative_len >= 30:
                    round_ok_count += 1

            except Exception as e:
                recorder.record(page, "ERROR", f"round_{rn}", f"轮次异常: {e}", rn)
                ss(page, f"04_r{rn:02d}_err.png")
                print(f"  ❌ R{rn} 失败: {e}")

        avg_elapsed = round_total_elapsed / max(ROUNDS, 1)
        log_step(step_results, f"STEP4 {ROUNDS}轮对话",
                 "ok" if round_ok_count == ROUNDS else "warn",
                 f"成功{round_ok_count}/{ROUNDS}轮 均耗时{avg_elapsed:.1f}s")
        ss(page, "04_rounds_done.png")

        # ══════════════════════════════════════════════════════════════════
        # STEP 5: 部分回退（回退第 REVERT_AT 轮）
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print(f"  STEP 5: 回退到第 {REVERT_AT} 轮之前（共回退 {ROUNDS - REVERT_AT} 轮）")
        print("=" * 65)
        current_round[0] = -1
        revert_ok = False
        try:
            # 打开右侧「历史」Tab
            hist_btn = page.locator("button:has-text('历史'), button[title*='历史']").first
            if not hist_btn.count():
                # 尝试找到右侧 Tab 栏
                hist_btn = page.locator("button:has-text('📜')").first
            if hist_btn.count():
                hist_btn.click()
                page.wait_for_timeout(600)
            ss(page, "05a_history_tab_opened.png")

            # 切换到「消息回溯」子 Tab
            msg_tab = page.locator("button:has-text('消息回溯')").first
            if msg_tab.count():
                msg_tab.click()
                page.wait_for_timeout(800)
            ss(page, "05b_message_tab.png")

            # 找到回退目标消息并点击「↩ 回溯」
            if revert_target_msg_id:
                # 尝试直接通过 data-id 或文本找到目标行
                # 由于按钮 opacity-0（hover 才显示），用 force=True 点击
                revert_done = False
                all_revert_btns = page.locator("button:has-text('↩ 回溯')").all()
                # 消息列表最新在上，REVERT_AT 对应约第 (ROUNDS - REVERT_AT + 1) 个用户消息
                # 即从顶部数第 (ROUNDS - REVERT_AT + 1) 个
                target_idx = ROUNDS - REVERT_AT  # 从顶(最新)往下数的索引（0-based）
                if len(all_revert_btns) > target_idx:
                    btn = all_revert_btns[target_idx]
                    btn.scroll_into_view_if_needed()
                    btn.hover()
                    page.wait_for_timeout(200)
                    btn.click(force=True)
                    revert_done = True
                elif all_revert_btns:
                    # 退而求其次：点第一个（最新）
                    all_revert_btns[0].click(force=True)
                    revert_done = True
                else:
                    print("  ⚠ 未找到任何「↩ 回溯」按钮，尝试 API 直接回退")
                    if revert_target_msg_id and session_id:
                        r = requests.post(f"{BACKEND}/api/sessions/{session_id}/revert",
                                          json={"message_id": revert_target_msg_id}, timeout=10)
                        if r.ok:
                            revert_done = True
                            print(f"  ✓ API 回退成功: {r.json()}")
                        else:
                            recorder.record(page, "ERROR", "revert_api_fail",
                                            f"API回退失败: {r.status_code} {r.text[:80]}")

                if revert_done:
                    page.wait_for_timeout(600)
                    # 处理确认对话框
                    confirm_btn = page.locator("button:has-text('回溯')").first
                    if confirm_btn.count() and confirm_btn.is_visible(timeout=3000):
                        confirm_btn.click()
                        print("  ✓ 点击确认「回溯」")
                        page.wait_for_timeout(2000)
            else:
                # 没有捕获到 message_id，通过 API 回退
                # 注意：/messages 返回 {"items": [...]}，消息 key 为 message_id
                print("  ⚠ revert_target_msg_id 未捕获，从消息列表获取")
                if session_id:
                    r = requests.get(f"{BACKEND}/api/sessions/{session_id}/messages",
                                     params={"limit": 100}, timeout=5)
                    if r.ok:
                        msgs = r.json().get("items", [])
                        user_msgs = [m for m in msgs if m.get("role") == "user"]
                        if len(user_msgs) >= REVERT_AT:
                            # message_id 是消息标识符（rename from id）
                            target_mid = user_msgs[REVERT_AT - 1].get("message_id", "")
                            if target_mid:
                                r2 = requests.post(f"{BACKEND}/api/sessions/{session_id}/revert",
                                                   json={"message_id": target_mid}, timeout=10)
                                if r2.ok:
                                    print(f"  ✓ API 回退到 msg_id={target_mid[:8]}...")

            ss(page, "05c_after_revert.png")

            # 回退后 API 核查
            # 注意：/messages 只返回 status='active' 的消息，不含已回退消息
            # 通过活跃消息总数验证回退生效
            if session_id:
                try:
                    r = requests.get(f"{BACKEND}/api/sessions/{session_id}/messages",
                                     params={"limit": 200}, timeout=5)
                    if r.ok:
                        # API 返回 {"items": [...], "has_more": ...}
                        active_msgs = r.json().get("items", [])
                        print(f"  📊 回退后活跃消息数: {len(active_msgs)}")
                        # 期望活跃消息约 ≤ REVERT_AT×2 + 开场 + buffer
                        # （因为只有 active 消息，reverted 消息不在 items 中）
                        expected_max = REVERT_AT * 2 + 6
                        if len(active_msgs) > expected_max:
                            recorder.record(page, "WARNING", "revert_count_mismatch",
                                            f"回退后活跃消息数 {len(active_msgs)} > 期望 {expected_max}")
                        elif len(active_msgs) == 0:
                            recorder.record(page, "ERROR", "revert_cleared_all",
                                            "回退后活跃消息为0，可能回退过度")
                        else:
                            print(f"  ✓ 回退正常，活跃消息数在预期范围内")
                        # 另查 session 确认 current_chapter
                        rs = requests.get(f"{BACKEND}/api/sessions/{session_id}", timeout=5)
                        if rs.ok:
                            mc = rs.json().get("message_count", "?")
                            print(f"  📊 会话 message_count(active)={mc}")
                except Exception as ve:
                    print(f"  ⚠ 回退核查失败: {ve}")

            # 继续 5 轮新方向对话（验证管线恢复）
            print(f"\n  ↪ 回退后继续 5 轮新方向对话...")
            POST_REVERT_INTENTS = [
                "重新审视当前局势，选择一个不同的方向推进。",
                "尝试一条之前没有走过的路，看看能遇到什么。",
                "重新与主神空间联系，查看回退后的积分状态。",
                "利用这次重来的机会，做出更优化的选择。",
                "沿新方向全力推进，争取达到更好的结果。",
            ]
            post_ok = 0
            for pr in range(1, 6):
                intent = POST_REVERT_INTENTS[pr - 1]
                try:
                    textarea = page.locator("textarea:not([disabled])").last
                    textarea.fill(intent)
                    captured["msg_id"] = None
                    textarea.press("Enter")
                    elapsed = wait_for_idle(page, LLM_MS)
                    narrative = get_latest_narrative(page)
                    check_round_response(page, recorder, ROUNDS + pr, narrative, elapsed)
                    ss(page, f"05d_post_revert_{pr}.png")
                    print(f"  ✓ 续跑 PR{pr} | {elapsed:.1f}s | {len(narrative)}字")
                    if len(narrative.strip()) >= 30:
                        post_ok += 1
                except Exception as e:
                    recorder.record(page, "ERROR", f"post_revert_{pr}", str(e))
                    ss(page, f"05d_post_revert_{pr}_err.png")
                    print(f"  ❌ 续跑 PR{pr} 失败: {e}")

            revert_ok = True
            log_step(step_results, f"STEP5 回退+续跑",
                     "ok" if post_ok == 5 else "warn",
                     f"续跑{post_ok}/5轮")
            ss(page, "05e_done.png")

        except Exception as e:
            recorder.record(page, "ERROR", "step5_revert", str(e))
            ss(page, "05_err.png")
            log_step(step_results, "STEP5 回退", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 6: 记忆压缩系统验证
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print("  STEP 6: 记忆压缩系统验证")
        print("=" * 65)
        memory_ok = False
        try:
            session_id = captured.get("session_id")
            assert session_id, "session_id 未获取"

            # 6.1 章节（chapters 树）
            # /chapters 返回 {"chapters": [树状节点...]}，每节点有 chapter_id/is_consolidated
            # summary 字段需额外调用 /chapters/{id}/summary
            chapters: list = []
            consolidated: list = []
            r = requests.get(f"{BACKEND}/api/sessions/{session_id}/chapters", timeout=5)
            if r.ok:
                # 递归展平章节树
                def flatten_chapters(nodes: list) -> list:
                    result = []
                    for n in nodes:
                        result.append(n)
                        result.extend(flatten_chapters(n.get("children", [])))
                    return result
                raw_tree = r.json().get("chapters", [])
                chapters = flatten_chapters(raw_tree)
                consolidated = [c for c in chapters if c.get("is_consolidated")]
                print(f"  📊 章节数={len(chapters)} 已固化={len(consolidated)}")
                if len(consolidated) == 0 and ROUNDS >= 20:
                    recorder.record(page, "WARNING", "no_consolidated_chapter",
                                    f"经历{ROUNDS}轮，无已固化章节（chronicler 可能失效）")
                # 对已固化章节，单独获取 summary
                for c in consolidated[:2]:
                    cid = c.get("chapter_id", "")
                    if not cid:
                        continue
                    rs = requests.get(
                        f"{BACKEND}/api/sessions/{session_id}/chapters/{cid}/summary", timeout=5)
                    if rs.ok:
                        summary = rs.json().get("summary", "")
                        print(f"  📝 章节摘要({len(summary or '')}字): {(summary or '')[:80]}")
                        if not summary:
                            recorder.record(page, "WARNING", "empty_chapter_summary",
                                            f"chapter_id={cid[:8]} 摘要为空")
            else:
                recorder.record(page, "WARNING", "chapters_api_fail",
                                f"GET /chapters → {r.status_code}")

            # 6.2 chapter_anchors 记录数
            r2 = requests.get(f"{BACKEND}/api/sessions/{session_id}/chapters/anchors", timeout=5)
            if r2.ok:
                anchors = r2.json().get("anchors", [])
                print(f"  📊 chapter_anchors={len(anchors)} 条（期望≥{ROUNDS}）")
                if len(anchors) < ROUNDS * 0.7:
                    recorder.record(page, "WARNING", "low_anchor_count",
                                    f"anchors={len(anchors)} 远少于预期 {ROUNDS}")
            else:
                print(f"  ⚠ GET /chapters/anchors → {r2.status_code}（可能端点不存在）")

            # 6.3 记忆健康状态（/api/system/memory-health）
            # 返回 {"ok": true, "memory": {"mode": "full"|"fallback", "is_full_mode": bool, ...}}
            r3 = requests.get(f"{BACKEND}/api/system/memory-health", timeout=5)
            if r3.ok:
                h_data = r3.json()
                mem = h_data.get("memory", {})
                mode = mem.get("mode", "unknown")
                is_full = mem.get("is_full_mode", False)
                print(f"  🧠 记忆健康: mode={mode} is_full={is_full}")
                if mode == "fallback":
                    recorder.record(page, "WARNING", "memory_fallback_mode",
                                    "记忆系统运行在 fallback 模式（无向量引擎）")
                    print(f"     组件状态: {json.dumps({k:v for k,v in mem.items() if k not in ('mode','is_full_mode')}, ensure_ascii=False)[:120]}")
            else:
                print(f"  ⚠ GET /api/system/memory-health → {r3.status_code}")

            # 6.4 记忆回忆测试（早期事件）
            r4 = requests.get(f"{BACKEND}/api/sessions/{session_id}/memory",
                              params={"q": "铁质长剑 武者苏力", "top_k": 3}, timeout=10)
            if r4.ok:
                recall = r4.json()
                items = recall.get("results", recall.get("memories", []))
                print(f"  🔍 早期记忆召回: {len(items)} 条（关键词: 铁质长剑）")
                if len(items) == 0:
                    recorder.record(page, "WARNING", "early_memory_lost",
                                    "早期记忆（铁质长剑）在压缩后无法召回")
            else:
                print(f"  ⚠ GET /sessions/{session_id}/memory → {r4.status_code}")

            memory_ok = True
            log_step(step_results, "STEP6 记忆验证", "ok",
                     f"chapters={len(chapters)} consolidated={len(consolidated)}")
        except Exception as e:
            recorder.record(page, "ERROR", "step6_memory", str(e))
            log_step(step_results, "STEP6 记忆验证", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 7: 数据完整性验证
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 65)
        print("  STEP 7: 数据完整性验证")
        print("=" * 65)
        try:
            session_id = captured.get("session_id")
            world_id   = captured.get("world_id")
            assert session_id

            # 7.1 会话基本信息
            r = requests.get(f"{BACKEND}/api/sessions/{session_id}", timeout=5)
            if r.ok:
                sdata = r.json()
                msg_count = sdata.get("message_count", "?")
                cur_ch = sdata.get("current_chapter")   # dict 或 None
                ch_title = cur_ch.get("title", "?") if isinstance(cur_ch, dict) else "(无)"
                ch_cons  = cur_ch.get("is_consolidated", False) if isinstance(cur_ch, dict) else False
                print(f"  📊 会话: message_count={msg_count} current_chapter={ch_title} "
                      f"is_consolidated={ch_cons}")

            # 7.2 角色卡状态
            r2 = requests.get(f"{BACKEND}/api/sessions/{session_id}/character", timeout=5)
            if r2.ok:
                char_raw = r2.json()
                char = char_raw.get("character", char_raw) if isinstance(char_raw, dict) else {}
                meta = char.get("meta", {}) if isinstance(char, dict) else {}
                inv  = char.get("inventory", []) if isinstance(char, dict) else []
                print(f"  👤 角色: battle_points={meta.get('battle_points','?')} "
                      f"weapon_mastery={meta.get('weapon_mastery','?')} "
                      f"inventory={len(inv)}件")
                if meta.get("battle_points", 0) == 0:
                    recorder.record(page, "WARNING", "no_battle_points",
                                    "经过30轮，battle_points 仍为0，战斗奖励结算可能未触发")
            else:
                recorder.record(page, "WARNING", "character_api_fail",
                                f"GET /character → {r2.status_code}")

            # 7.3 消息列表扫描
            # 注意：/messages 只返回 status='active' 消息，键为 "items"
            # 字段名：message_id（不是 id）
            all_msgs: list = []
            r3 = requests.get(f"{BACKEND}/api/sessions/{session_id}/messages",
                               params={"limit": 200}, timeout=10)
            if r3.ok:
                all_msgs = r3.json().get("items", [])
                null_content = [m for m in all_msgs
                                if m.get("content") is None and m.get("role") != "assistant"]
                print(f"  📨 活跃消息: 总数={len(all_msgs)} null_content={len(null_content)}")
                if len(null_content) > 0:
                    recorder.record(page, "WARNING", "null_content_messages",
                                    f"{len(null_content)} 条用户消息 content=null")
                # 通过 session.message_count 与 all_msgs 数差异推断是否有回退
                if REVERT_AT and ROUNDS > REVERT_AT:
                    # 期望活跃消息约为 (REVERT_AT + 5) × 2 + 开场buffer
                    expected_approx = (REVERT_AT + 5) * 2 + 4
                    if len(all_msgs) > expected_approx + 10:
                        recorder.record(page, "WARNING", "unexpected_msg_count",
                                        f"活跃消息数 {len(all_msgs)} 远超预期约 {expected_approx}")

            # 7.4 世界档案
            if world_id:
                r4 = requests.get(f"{BACKEND}/api/worlds/{world_id}/archives", timeout=5)
                if r4.ok:
                    archives = r4.json().get("archives", [])
                    print(f"  🌍 世界档案: {len(archives)} 条（期望≥2）")
                    if len(archives) < 2:
                        recorder.record(page, "WARNING", "low_archive_count",
                                        f"世界档案仅 {len(archives)} 条，创建时写入可能失败")

            log_step(step_results, "STEP7 数据验证", "ok",
                     f"活跃消息={len(all_msgs) if r3.ok else '?'}")
        except Exception as e:
            recorder.record(page, "ERROR", "step7_data", str(e))
            log_step(step_results, "STEP7 数据验证", "fail", str(e)[:100])

        # ══════════════════════════════════════════════════════════════════
        # STEP 8: 汇总输出 + 写盘
        # ══════════════════════════════════════════════════════════════════
        ss(page, "08_final_state.png")
        browser.close()

    # ── 打印汇总 ─────────────────────────────────────────────────────────────
    total_elapsed_min = round_total_elapsed / 60
    print("\n" + "═" * 65)
    print("  全流程测试汇总")
    print("═" * 65)
    print("步骤结果:")
    for sr in step_results:
        icon = {"ok": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(sr["status"], "?")
        detail = f"  ({sr['detail'][:70]})" if sr["detail"] else ""
        print(f"  {icon} {sr['step']}{detail}")

    print(f"\n实时发现问题（共 {len(recorder.issues)} 条）:")
    errors   = [i for i in recorder.issues if i["level"] == "ERROR"]
    warnings = [i for i in recorder.issues if i["level"] == "WARNING"]
    for issue in recorder.issues:
        icon = "🔴" if issue["level"] == "ERROR" else "🟡"
        print(f"  {icon} [R{issue['round']}] {issue['category']}: {issue['detail'][:80]}")
        print(f"       → 截图: {issue['screenshot']}")

    fail_steps = sum(1 for s in step_results if s["status"] == "fail")
    warn_steps = sum(1 for s in step_results if s["status"] == "warn")
    print(f"\n关键指标:")
    print(f"  总对话轮数:   {ROUNDS} + 5(回退后续跑)")
    print(f"  回退位置:     第 {REVERT_AT} 轮")
    print(f"  成功轮数:     {round_ok_count}/{ROUNDS}")
    print(f"  平均响应:     {round_total_elapsed / max(ROUNDS, 1):.1f}s/轮")
    print(f"  步骤结果:     失败={fail_steps} 警告={warn_steps} 通过={len(step_results)-fail_steps-warn_steps}")
    print(f"  问题数:       ERROR={len(errors)} / WARNING={len(warnings)}")
    print(f"  总耗时:       约 {total_elapsed_min:.1f} 分钟（不含初始化）")
    print(f"\n截图目录: {SS_DIR}")
    print(f"问题日志: {SS_DIR / 'issues.jsonl'}")

    # 写 result.json
    result = {
        "ts":            TS,
        "rounds":        ROUNDS,
        "revert_at":     REVERT_AT,
        "round_ok":      round_ok_count,
        "avg_elapsed_s": round_total_elapsed / max(ROUNDS, 1),
        "session_id":    captured.get("session_id"),
        "world_id":      captured.get("world_id"),
        "character_id":  captured.get("character_id"),
        "step_results":  step_results,
        "issues":        recorder.issues,
        "console_errors": console_errors[:20],
        "network_errors": network_errors[:20],
        "round_ids":     {str(k): v for k, v in round_ids.items()},
    }
    result_file = SS_DIR / "result.json"
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果 JSON:  {result_file}")
    print("═" * 65)


if __name__ == "__main__":
    main()
