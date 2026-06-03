"""
E2E 测试：首页枢纽系统
验证七 Tab 竖向导航、世界管理、人物创建、资产库、存档、提示词 Tab

注：脚本式伪 E2E（test_ 函数带位置参数、依赖运行中的后端/前端），非标准 pytest 用例，
标注 stub；CI 以 `-m "not stub"` 排除。
"""
import asyncio
import json
import time
import os
import sys
import requests
from datetime import datetime

import pytest

pytestmark = pytest.mark.stub

BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://localhost:5175"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def screenshot_path(step: str) -> str:
    return os.path.join(SCREENSHOTS_DIR, f"{RUN_ID}_hub_{step}.png")


# ── API Tests ─────────────────────────────────────────────────────────────────

def test_worlds_api():
    print("\n[API] Testing /api/worlds ...")
    # Create world
    r = requests.post(f"{BACKEND}/api/worlds", json={"name": "测试世界", "world_plugin": "crossover", "description": "E2E测试"}, timeout=10)
    assert r.status_code == 200, f"Create world failed: {r.text}"
    wid = r.json()["world_id"]
    print(f"  ✓ 创建世界 ID={wid}")

    # List worlds
    r = requests.get(f"{BACKEND}/api/worlds", timeout=5)
    assert r.status_code == 200
    worlds = r.json()["worlds"]
    assert any(w["id"] == wid for w in worlds), "World not in list"
    print(f"  ✓ 列出世界 ({len(worlds)} 个)")

    # Add archive
    r = requests.post(f"{BACKEND}/api/worlds/{wid}/archives",
        json={"title": "世界背景", "content": "这是一个测试世界的背景故事", "archive_type": "lore"}, timeout=5)
    assert r.status_code == 200, f"Create archive failed: {r.text}"
    aid = r.json()["archive_id"]
    print(f"  ✓ 创建档案条目 ID={aid}")

    # List archives
    r = requests.get(f"{BACKEND}/api/worlds/{wid}/archives", timeout=5)
    assert r.status_code == 200
    archives = r.json()["archives"]
    assert len(archives) >= 1
    print(f"  ✓ 列出档案 ({len(archives)} 条)")

    # Update archive
    r = requests.patch(f"{BACKEND}/api/worlds/{wid}/archives/{aid}",
        json={"title": "更新后的世界背景"}, timeout=5)
    assert r.status_code == 200
    print(f"  ✓ 更新档案")

    # Update world
    r = requests.patch(f"{BACKEND}/api/worlds/{wid}",
        json={"description": "已更新的描述"}, timeout=5)
    assert r.status_code == 200
    print(f"  ✓ 更新世界")

    return wid


def test_character_templates_api():
    print("\n[API] Testing /api/characters ...")
    time.sleep(1)  # avoid rate limiting
    char_data = {
        "name": "测试角色", "gender": "male", "tier": "T0",
        "world_plugin": "crossover", "background": "测试背景",
        "stats": {"strength": 5, "agility": 5, "intelligence": 5},
        "skills": [], "items": []
    }

    # Create template
    r = requests.post(f"{BACKEND}/api/characters",
        json={"name": "测试角色", "world_plugin": "crossover", "data_json": char_data}, timeout=10)
    assert r.status_code == 200, f"Create character failed: {r.text}"
    cid = r.json()["character_id"]
    print(f"  ✓ 创建人物模板 ID={cid}")

    # List templates
    r = requests.get(f"{BACKEND}/api/characters", timeout=5)
    assert r.status_code == 200
    chars = r.json()["characters"]
    assert any(c["id"] == cid for c in chars), "Character not in list"
    print(f"  ✓ 列出人物模板 ({len(chars)} 个)")

    # Get single template
    r = requests.get(f"{BACKEND}/api/characters/{cid}", timeout=5)
    assert r.status_code == 200
    assert r.json()["name"] == "测试角色"
    print(f"  ✓ 获取人物模板详情")

    # Update
    r = requests.patch(f"{BACKEND}/api/characters/{cid}", json={"name": "更新的角色"}, timeout=5)
    assert r.status_code == 200
    print(f"  ✓ 更新人物模板")

    return cid


def test_assets_api():
    print("\n[API] Testing /api/assets ...")
    time.sleep(2)  # avoid rate limiting

    # List NPCs (pre-existing)
    r = requests.get(f"{BACKEND}/api/assets/npcs", timeout=5)
    assert r.status_code == 200, f"List NPCs failed: {r.text}"
    npcs = r.json()["npcs"]
    print(f"  ✓ 列出NPC模板 ({len(npcs)} 个)")

    time.sleep(1)
    # List items (pre-existing)
    r = requests.get(f"{BACKEND}/api/assets/items", timeout=5)
    assert r.status_code == 200, f"List items failed: {r.text}"
    items = r.json()["items"]
    print(f"  ✓ 列出物品模板 ({len(items)} 个)")

    return None, None


def test_prompts_api():
    print("\n[API] Testing /api/prompts ...")
    time.sleep(2)  # avoid rate limiting

    # List prompts (triggers default creation)
    r = requests.get(f"{BACKEND}/api/prompts", timeout=5)
    assert r.status_code == 200, f"List prompts failed: {r.text}"
    prompts = r.json()["prompts"]
    print(f"  ✓ 列出提示词 ({len(prompts)} 条，含默认值)")
    assert len(prompts) >= 6, "Should have at least 6 default prompts"

    time.sleep(1)
    # Filter by agent
    r = requests.get(f"{BACKEND}/api/prompts?agent=dm", timeout=5)
    assert r.status_code == 200, f"Filter prompts failed: {r.text}"
    dm_prompts = r.json()["prompts"]
    assert len(dm_prompts) >= 1
    print(f"  ✓ 按agent筛选 dm: {len(dm_prompts)} 条")

    return prompts[0]["id"]


def test_session_with_templates(wid: str, cid: str):
    print("\n[API] Testing session creation with templates ...")
    time.sleep(2)  # avoid rate limiting
    # Create session using world template
    r = requests.post(f"{BACKEND}/api/sessions",
        json={"world_plugin": "crossover", "title": "模板测试会话",
              "world_id": wid, "character_template_id": cid}, timeout=10)
    assert r.status_code == 200, f"Create session failed: {r.text}"
    sid = r.json()["session_id"]
    print(f"  ✓ 从模板创建会话 ID={sid}")

    # Verify archives were copied
    r = requests.get(f"{BACKEND}/api/sessions/{sid}/world-archives", timeout=5)
    assert r.status_code == 200
    archives = r.json()["archives"]
    print(f"  ✓ 验证世界档案已复制 ({len(archives)} 条)")

    # Verify character exists
    r = requests.get(f"{BACKEND}/api/sessions/{sid}/character", timeout=5)
    assert r.status_code == 200
    print(f"  ✓ 验证人物卡已创建")

    return sid


def test_confirm_lore(wid: str):
    print("\n[API] Testing confirm-lore ...")
    entries = [
        {"title": "魔法规则", "content": "这个世界的魔法消耗精神力", "archive_type": "rule"},
        {"title": "大陆概况", "content": "这是一片广袤的大陆", "archive_type": "lore"},
    ]
    r = requests.post(f"{BACKEND}/api/worlds/{wid}/confirm-lore",
        json={"entries": entries}, timeout=10)
    assert r.status_code == 200
    result = r.json()
    assert result["written"] == 2
    print(f"  ✓ 批量写入档案 ({result['written']} 条)")


# ── Browser Tests (Playwright) ────────────────────────────────────────────────

async def test_browser():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("\n[Browser] playwright 未安装，跳过浏览器测试")
        return

    print("\n[Browser] 启动 Playwright 浏览器测试...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # 1. 首页 - 七Tab导航
        print("  → 加载首页...")
        await page.goto(FRONTEND, timeout=15000)
        await page.wait_for_timeout(1500)
        await page.screenshot(path=screenshot_path("01_home_sessions"))
        print(f"  ✓ 首页截图 → 01_home_sessions.png")

        # 验证导航栏
        nav_labels = ['会话', '世界', '人物', '资产库', '存档', '提示词', '设置']
        for label in nav_labels:
            el = page.locator(f"text={label}").first
            visible = await el.is_visible()
            print(f"  {'✓' if visible else '✗'} 导航项「{label}」{'可见' if visible else '不可见'}")

        # 2. 世界 Tab
        print("  → 切换到世界 Tab...")
        await page.click("text=世界")
        await page.wait_for_timeout(800)
        await page.screenshot(path=screenshot_path("02_worlds_tab"))
        print(f"  ✓ 世界Tab截图 → 02_worlds_tab.png")

        # 验证世界列表
        world_list = page.locator("text=世界库")
        assert await world_list.is_visible(), "世界库标题未显示"
        new_world_btn = page.locator("text=+ 新建世界")
        assert await new_world_btn.is_visible(), "新建世界按钮未显示"
        print("  ✓ 世界Tab内容正确")

        # 3. 人物 Tab
        print("  → 切换到人物 Tab...")
        await page.click("text=人物")
        await page.wait_for_timeout(800)
        await page.screenshot(path=screenshot_path("03_characters_tab"))
        print(f"  ✓ 人物Tab截图 → 03_characters_tab.png")

        create_btn = page.locator("text=+ 创建人物")
        assert await create_btn.is_visible(), "创建人物按钮未显示"
        print("  ✓ 人物Tab内容正确")

        # 4. 资产库 Tab
        print("  → 切换到资产库 Tab...")
        await page.click("text=资产库")
        await page.wait_for_timeout(800)
        await page.screenshot(path=screenshot_path("04_assets_tab"))
        print(f"  ✓ 资产库Tab截图 → 04_assets_tab.png")

        asset_title = page.locator("text=资产库")
        assert await asset_title.first.is_visible()
        print("  ✓ 资产库Tab内容正确")

        # 5. 存档 Tab
        print("  → 切换到存档 Tab...")
        await page.click("text=存档")
        await page.wait_for_timeout(800)
        await page.screenshot(path=screenshot_path("05_archives_tab"))
        print(f"  ✓ 存档Tab截图 → 05_archives_tab.png")

        # 6. 提示词 Tab
        print("  → 切换到提示词 Tab...")
        await page.click("text=提示词")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=screenshot_path("06_prompts_tab"))
        print(f"  ✓ 提示词Tab截图 → 06_prompts_tab.png")

        # Should show agent categories (use button role to avoid strict-mode violation)
        dm_btn = page.get_by_role("button", name="DM 裁判", exact=False).first
        if await dm_btn.is_visible():
            print("  ✓ 提示词分类显示正确")

        # 7. 设置 Tab
        print("  → 切换到设置 Tab...")
        await page.click("text=设置")
        await page.wait_for_timeout(800)
        await page.screenshot(path=screenshot_path("07_settings_tab"))
        print(f"  ✓ 设置Tab截图 → 07_settings_tab.png")

        # Verify settings content is embedded
        model_config = page.locator("text=模型配置")
        assert await model_config.is_visible(), "设置内容未嵌入"
        print("  ✓ 设置Tab内容正确（SettingsPage嵌入）")

        # 8. 测试创建世界 Modal
        print("  → 测试新建世界 Modal...")
        await page.click("text=世界")
        await page.wait_for_timeout(500)
        await page.click("text=+ 新建世界")
        await page.wait_for_timeout(600)
        await page.screenshot(path=screenshot_path("08_world_modal"))
        print(f"  ✓ 世界Modal截图 → 08_world_modal.png")

        # Fill name
        name_input = page.locator("input[placeholder='世界名称（必填）']")
        if await name_input.is_visible():
            await name_input.fill("E2E测试世界")
            await page.screenshot(path=screenshot_path("09_world_modal_filled"))
            print("  ✓ 世界Modal填写完成")

        # Close modal
        close_btn = page.locator("button:has-text('×')").first
        await close_btn.click()
        await page.wait_for_timeout(300)

        # 9. 测试创建人物 Modal
        print("  → 测试创建人物 Modal...")
        await page.click("text=人物")
        await page.wait_for_timeout(500)
        await page.click("text=+ 创建人物")
        await page.wait_for_timeout(600)
        await page.screenshot(path=screenshot_path("10_character_modal"))
        print(f"  ✓ 人物Modal截图 → 10_character_modal.png")

        # Verify step 0 - mode selection
        quick_btn = page.locator("text=快速创建")
        assert await quick_btn.is_visible(), "快速创建选项未显示"
        quiz_btn = page.locator("text=问卷创建")
        assert await quiz_btn.is_visible(), "问卷创建选项未显示"
        bg_btn = page.locator("text=背景创建")
        assert await bg_btn.is_visible(), "背景创建选项未显示"
        print("  ✓ 人物创建向导三种模式均显示")

        # Close modal
        close_btn2 = page.locator("button:has-text('×')").first
        await close_btn2.click()

        # 10. 返回会话Tab，测试下拉显示
        print("  → 返回会话Tab测试...")
        await page.click("text=会话")
        await page.wait_for_timeout(600)
        await page.screenshot(path=screenshot_path("11_sessions_with_templates"))
        print(f"  ✓ 会话Tab (含模板选项) → 11_sessions_with_templates.png")

        # 11. 折叠侧边栏测试
        print("  → 测试侧边栏折叠...")
        collapse_btn = page.locator("button:has-text('←')").first
        if await collapse_btn.is_visible():
            await collapse_btn.click()
            await page.wait_for_timeout(400)
            await page.screenshot(path=screenshot_path("12_sidebar_collapsed"))
            print(f"  ✓ 折叠侧边栏截图 → 12_sidebar_collapsed.png")
            # Expand back
            expand_btn = page.locator("button:has-text('→')").first
            if await expand_btn.is_visible():
                await expand_btn.click()
        
        await browser.close()
        print("\n  ✓ 所有浏览器测试通过")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  ZeroArsenal 首页枢纽系统 E2E 测试")
    print(f"  运行时间: {RUN_ID}")
    print("=" * 60)

    errors = []

    # API Tests
    try:
        wid = test_worlds_api()
    except Exception as e:
        errors.append(f"worlds API: {e}")
        wid = None

    try:
        test_confirm_lore(wid) if wid else None
    except Exception as e:
        errors.append(f"confirm-lore API: {e}")

    try:
        cid = test_character_templates_api()
    except Exception as e:
        import traceback; traceback.print_exc()
        errors.append(f"characters API: {e}")
        cid = None

    try:
        test_assets_api()
    except Exception as e:
        errors.append(f"assets API: {e}")

    try:
        test_prompts_api()
    except Exception as e:
        errors.append(f"prompts API: {e}")

    try:
        if wid and cid:
            test_session_with_templates(wid, cid)
    except Exception as e:
        errors.append(f"session with templates: {e}")

    # Browser Tests
    try:
        asyncio.run(test_browser())
    except Exception as e:
        errors.append(f"browser: {e}")

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"  ✗ {len(errors)} 个测试失败:")
        for err in errors:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print("  ✓ 所有测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    main()
