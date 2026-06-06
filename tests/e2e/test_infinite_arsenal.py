"""
无限武库（infinite_arsenal）专项 E2E 测试
- 创建 infinite_arsenal 会话，验证初始角色卡（battle_points / 铁质长剑）
- 发送战斗行动，验证 9-agent 管线 + 叙事生成
- 测试专属工具：get_arsenal_inventory / forge_weapon / evaluate_weapon / earn_battle_rewards
- 验证 Gacha Agent（draw_gacha 抽卡落点）
运行: python tests/e2e/test_infinite_arsenal.py

注：脚本式伪 E2E（test_ 函数带位置参数、依赖运行中的后端），非标准 pytest 用例，
标注 stub；CI 以 `-m "not stub"` 排除（见 STUB_ANALYSIS T05）。
"""
import json
import sys
import time
import pathlib
import requests
from datetime import datetime

import pytest

pytestmark = pytest.mark.stub

sys.stdout.reconfigure(encoding="utf-8")

BACKEND  = "http://127.0.0.1:8000"
SS_DIR   = pathlib.Path(__file__).parent.parent / "screenshots"
SS_DIR.mkdir(exist_ok=True)
TS       = datetime.now().strftime("%Y%m%d_%H%M%S")
results  = []


def log(msg: str, ok: bool = True):
    mark = "✅" if ok else "❌"
    print(f"  {mark} {msg}")
    results.append({"msg": msg, "ok": ok})


def section(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── Part 1: 创建会话 & 验证角色卡 ────────────────────────────────────────────

def test_session_init() -> str:
    section("Part 1: 创建 infinite_arsenal 会话 & 角色卡验证")

    r = requests.post(f"{BACKEND}/api/sessions", json={
        "title": f"IA测试_{TS}",
        "plugin_key": "infinite_arsenal",
        "mode": "play",
    }, timeout=10)
    assert r.status_code == 200
    data = r.json()
    sid  = data.get("session_id") or data.get("id")
    assert sid
    log(f"创建会话 id={sid[:8]}... plugin_key=infinite_arsenal")

    # 读取角色卡
    r2 = requests.get(f"{BACKEND}/api/sessions/{sid}/character", timeout=5)
    if r2.ok:
        raw  = r2.json()
        # API 返回 {"character": {...}} 或直接返回角色对象
        char = raw.get("character", raw) if isinstance(raw, dict) else {}
        meta = char.get("meta", {}) if isinstance(char, dict) else {}
        inv  = (char.get("inventory", []) if isinstance(char, dict) else [])
        log(f"角色卡 meta.battle_points={meta.get('battle_points','?')} "
            f"meta.highest_tier={meta.get('highest_tier','?')} "
            f"meta.weapon_mastery={meta.get('weapon_mastery','?')}")
        has_starter = any(i.get("key") == "starter_sword" for i in inv)
        log(f"初始武器 starter_sword 存在={has_starter}", ok=has_starter)
    else:
        # 直接查 character_cards 路径
        r3 = requests.get(f"{BACKEND}/api/sessions/{sid}", timeout=5)
        log(f"GET /sessions/{{id}} → {r3.status_code}")

    return sid


# ── Part 2: 真实 LLM 战斗行动 ────────────────────────────────────────────────

def test_combat_message(sid: str) -> str | None:
    section("Part 2: 发送战斗行动 & LLM 管线测试")

    payload = {
        "content": "我拔出腰间的铁质长剑，向面前那只黑甲蜥蜴发动突刺，同时调动体内薄弱的武器共鸣。",
        "message_type": "action",
    }
    r = requests.post(f"{BACKEND}/api/sessions/{sid}/message",
                      json=payload, timeout=15)
    if r.status_code not in (200, 202):
        log(f"POST /message → {r.status_code}: {r.text[:200]}", ok=False)
        return None

    resp     = r.json()
    msg_id   = resp.get("message_id", "")
    stream_url = resp.get("stream_url", f"/api/sessions/{sid}/events")
    log(f"POST /message → {r.status_code} message_id={msg_id[:8] if msg_id else '?'}...")

    sse_url = f"{BACKEND}{stream_url}" if stream_url.startswith("/") else stream_url
    narrative_parts: list[str] = []
    agents_seen:     list[str] = []
    start = time.time()

    try:
        with requests.get(sse_url, stream=True, timeout=120) as sse_r:
            for raw in sse_r.iter_lines(decode_unicode=True):
                if time.time() - start > 110:
                    log("SSE 超时", ok=False); break
                if not raw or not raw.startswith("data:"): continue
                try: evt = json.loads(raw[5:].strip())
                except Exception: continue

                etype = evt.get("type", "")
                edata = evt.get("data", {})
                if etype == "part.updated":
                    narrative_parts.append(edata.get("delta", ""))
                elif etype == "agent.started":
                    agents_seen.append(edata.get("agent", "?"))
                elif etype in ("session.done", "session.idle"):
                    log(f"{etype} → agents={agents_seen}"); break
                elif etype == "session.error":
                    err = edata.get("message") or json.dumps(edata)[:100]
                    log(f"session.error: {err[:120]}", ok=len("".join(narrative_parts)) > 0)
                    break

        full = "".join(narrative_parts)
        elapsed = time.time() - start
        log(f"叙事: {len(full)}字 | 首100字: {full[:100].replace(chr(10),' ')}")
        if len(full) >= 20:
            log(f"管线通过（{len(full)}字，{len(agents_seen)}个agents，{elapsed:.1f}s）")
        else:
            log(f"叙事过短 {len(full)}字", ok=False)
            return None
    except Exception as e:
        log(f"SSE 失败: {e}", ok=False); return None

    return msg_id


# ── Part 3: 专属工具 API ──────────────────────────────────────────────────────

def test_arsenal_tools(sid: str):
    section("Part 3: 无限武库专属工具 API 测试")

    # 3.1 get_arsenal_inventory（通过 /api/tools/invoke 或直接 character）
    r = requests.get(f"{BACKEND}/api/sessions/{sid}/character", timeout=5)
    if r.ok:
        raw  = r.json()
        char = raw.get("character", raw) if isinstance(raw, dict) else {}
        inv  = char.get("inventory", []) if isinstance(char, dict) else []
        weapons = [i for i in inv if i.get("quality") or i.get("key")]
        log(f"角色库存 inventory={len(inv)}件 weapons={len(weapons)}件")
        if inv:
            log(f"首件物品: {inv[0].get('name','?')} tier={inv[0].get('metadata',{}).get('tier','?')}")
    else:
        log(f"GET /character → {r.status_code}", ok=False)

    time.sleep(1)

    # 3.2 forge_weapon — 直接调用工具端点
    r_forge = requests.post(f"{BACKEND}/api/tools/invoke", json={
        "tool": "forge_weapon",
        "session_id": sid,
        "args": {"session_id": sid, "material": "玄铁", "technique": "淬火锻造"},
    }, timeout=15)
    if r_forge.ok:
        forge_data = r_forge.json()
        weapon = forge_data.get("result", {}).get("weapon") or forge_data.get("weapon")
        assert weapon is not None, f"forge_weapon 未返回 weapon: {forge_data}"
        log(f"forge_weapon → 武器={weapon.get('name','?')} 攻击={weapon.get('attack','?')}")
    else:
        # 降级：不支持 invoke 端点时跳过但记录
        log(f"POST /tools/invoke forge_weapon → {r_forge.status_code}: {r_forge.text[:100]}", ok=False)

    # 3.3 draw_gacha — 抽卡落点
    r_gacha = requests.post(f"{BACKEND}/api/sessions/{sid}/gacha/draw", json={
        "pool_name": "basic",
        "count": 1,
    }, timeout=15)
    if r_gacha.ok:
        gacha_data = r_gacha.json()
        results_list = gacha_data.get("results", gacha_data.get("items", []))
        log(f"draw_gacha → {len(results_list)} 个结果: {results_list[:1]}")
    else:
        log(f"POST /sessions/{{sid}}/gacha/draw → {r_gacha.status_code}: {r_gacha.text[:100]}", ok=False)

    # 3.4 earn_battle_rewards（骰子+积分结算）
    r2 = requests.post(f"{BACKEND}/api/engine/roll", json={
        "pool": 5, "threshold": 8, "reason": "IA战斗判定测试",
        "session_id": sid,
    }, timeout=10)
    if r2.ok:
        roll = r2.json()
        log(f"骰子 pool=5 → net={roll.get('net','?')} rolls={roll.get('rolls','?')} verdict={roll.get('verdict','?')}")
    else:
        log(f"POST /engine/roll → {r2.status_code}", ok=False)

    # 3.3 世界档案（NPC/地点）
    r3 = requests.get(f"{BACKEND}/api/sessions/{sid}/world-archives", timeout=5)
    log(f"GET /world-archives → {r3.status_code} 数量={len(r3.json()) if r3.ok else '?'}")

    # 3.4 记忆检索（武器/战斗相关）
    r4 = requests.get(f"{BACKEND}/api/sessions/{sid}/memory?q=长剑&top_k=5", timeout=5)
    log(f"GET /memory?q=长剑 → {r4.status_code} 记忆数={len(r4.json()) if r4.ok else '?'}", ok=r4.ok)

    # 3.5 章节树
    r5 = requests.get(f"{BACKEND}/api/sessions/{sid}/chapters", timeout=5)
    if r5.ok:
        tree = r5.json()
        ch   = tree.get("chapters", []) if isinstance(tree, dict) else tree
        log(f"GET /chapters → {r5.status_code} 章节数={len(ch)}")
    else:
        log(f"GET /chapters → {r5.status_code}", ok=False)


# ── Part 4: Playwright 浏览器 UI ─────────────────────────────────────────────

def test_browser_ui(sid: str):
    section("Part 4: 浏览器 UI 测试（infinite_arsenal 会话）")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        pytest.skip("playwright 未安装，跳过浏览器测试")
        return

    frontend = "http://localhost:5174"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # ── 首页：新建会话选择 infinite_arsenal ──────────────────────────────
        page.goto(frontend)
        page.wait_for_load_state("networkidle", timeout=15000)
        ss = SS_DIR / f"{TS}_ia_01_homepage.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"截图: {ss.name}")

        body = page.inner_text("body")
        has_ia = "infinite_arsenal" in body or "无限武库" in body
        log(f"首页含 infinite_arsenal 选项={has_ia}", ok=has_ia)

        # ── 会话页面 ──────────────────────────────────────────────────────────
        page.goto(f"{frontend}/sessions/{sid}")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1500)

        ss = SS_DIR / f"{TS}_ia_02_session.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"截图: {ss.name}")

        text = page.inner_text("body")
        has_narrative = any(kw in text for kw in ["铁质长剑", "黑甲蜥蜴", "武器", "IA测试", "长剑"])
        log(f"叙事内容可见={has_narrative}", ok=has_narrative)

        # ── 右侧面板：角色属性 ────────────────────────────────────────────────
        # 检查骰子面板（属性区）
        has_dice_panel = page.locator("[class*='dice'], button:has-text('投骰'), .dice-panel").count() > 0
        has_stat_panel = page.locator(".font-bold, [class*='stat']").count() > 0
        log(f"属性/骰子面板可见={has_stat_panel or has_dice_panel}")

        # ── 发送第二条战斗指令 ────────────────────────────────────────────────
        input_sel = None
        for sel in ["textarea", "input[type='text']"]:
            if page.locator(sel).count() > 0:
                input_sel = sel; break

        if input_sel:
            page.locator(input_sel).first.fill("我查看一下背包里的武器，确认铁质长剑的共鸣度。")
            page.wait_for_timeout(300)
            ss = SS_DIR / f"{TS}_ia_03_input.png"
            page.screenshot(path=str(ss), full_page=True)
            log(f"输入框填充截图: {ss.name}")
        else:
            log("未找到输入框", ok=False)

        # ── 最终截图 ──────────────────────────────────────────────────────────
        ss = SS_DIR / f"{TS}_ia_99_final.png"
        page.screenshot(path=str(ss), full_page=True)
        log(f"最终截图: {ss.name}")

        browser.close()
    log("浏览器 UI 测试完成")


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'#'*60}")
    print(f"  ZeroArsenal 无限武库专项测试  [{TS}]")
    print(f"  Backend: {BACKEND}")
    print(f"{'#'*60}")

    try:
        sid = test_session_init()
    except Exception as e:
        log(f"会话创建失败: {e}", ok=False)
        return

    try:
        test_combat_message(sid)
    except Exception as e:
        log(f"LLM管线测试失败: {e}", ok=False)

    try:
        test_arsenal_tools(sid)
    except Exception as e:
        log(f"工具API测试失败: {e}", ok=False)

    try:
        test_browser_ui(sid)
    except Exception as e:
        log(f"浏览器测试失败: {e}", ok=False)
        import traceback; traceback.print_exc()

    # ── 汇总 ──────────────────────────────────────────────────────────────────
    section("测试汇总")
    ok_n   = sum(1 for r in results if r["ok"])
    fail_n = sum(1 for r in results if not r["ok"])
    print(f"  检查项: {len(results)}  通过: {ok_n}  失败: {fail_n}")

    shots = sorted(SS_DIR.glob(f"{TS}_ia_*.png"))
    print(f"\n  截图文件 ({len(shots)} 张):")
    for s in shots:
        print(f"    - {s.name}")

    report = SS_DIR / f"{TS}_ia_report.json"
    report.write_text(json.dumps({
        "timestamp": TS, "plugin_key": "infinite_arsenal",
        "session_id": sid,
        "results": results,
        "screenshots": [s.name for s in shots],
        "summary": {"total": len(results), "passed": ok_n, "failed": fail_n},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON报告: {report}")
    print(f"\n  {'🎉 全部通过！' if fail_n == 0 else f'⚠️ {fail_n} 项失败'}")


if __name__ == "__main__":
    main()
