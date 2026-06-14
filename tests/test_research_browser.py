"""
Browser proxy test: WorldManager AI Research tab - v3 (handles onboarding modal)
"""
import sys, os
sys.path.insert(0, '.')

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright not installed")
    sys.exit(0)

SS_DIR = "tests/screenshots/research_ui"
os.makedirs(SS_DIR, exist_ok=True)

def find_frontend():
    for port in [5173, 5174, 5175, 5176, 5177]:
        try:
            import urllib.request
            urllib.request.urlopen(f"http://localhost:{port}", timeout=2)
            return f"http://localhost:{port}"
        except Exception:
            pass
    return "http://localhost:5173"

with sync_playwright() as p:
    base_url = find_frontend()
    print(f"Frontend: {base_url}")

    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    # 1. Load homepage
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{SS_DIR}/01_home.png")
    print(f"1. Loaded: {page.title()}")

    # 2. Dismiss onboarding modal (click "开始使用")
    start_btn = page.get_by_text("开始使用").first
    if start_btn.count() > 0 and start_btn.is_visible():
        start_btn.click()
        page.wait_for_timeout(800)
        print("2. Dismissed onboarding modal")
    page.screenshot(path=f"{SS_DIR}/02_after_onboarding.png")

    # 3. Find left nav - world tab (sidebar icons)
    # The nav is on the left - look for sidebar navigation
    print("3. Looking for world navigation...")
    all_nav = page.locator("nav a, nav button, aside a, aside button, .sidebar button, [data-tab]").all()
    for item in all_nav[:15]:
        try:
            txt = item.inner_text().strip()
            aria = item.get_attribute("aria-label") or ""
            title = item.get_attribute("title") or ""
            print(f"   nav item: text={txt!r} aria={aria!r} title={title!r}")
        except Exception:
            pass

    # Try clicking 世界 tab in sidebar
    world_clicked = False
    for txt in ["世界", "World", "世界库"]:
        btns = page.get_by_text(txt).all()
        for b in btns:
            try:
                if b.is_visible():
                    b.click()
                    page.wait_for_timeout(800)
                    world_clicked = True
                    print(f"3. Clicked '{txt}'")
                    break
            except Exception:
                pass
        if world_clicked:
            break

    if not world_clicked:
        # Check all visible buttons
        print("3. Could not find world tab, looking for all sidebar elements...")
        sidebar = page.locator("nav, aside, .sidebar, [class*='sidebar'], [class*='nav']").first
        if sidebar.count() > 0:
            items = sidebar.locator("button, a").all()
            for item in items[:15]:
                try:
                    if item.is_visible():
                        txt = item.inner_text().strip()
                        aria = item.get_attribute("aria-label") or ""
                        print(f"   sidebar item: {txt!r} ({aria!r})")
                except Exception:
                    pass

    page.screenshot(path=f"{SS_DIR}/03_world_nav.png")

    # 4. Find world list or world management area
    # Look for "世界" heading or world management panel
    world_section = page.get_by_text("世界管理").first
    if world_section.count() > 0 and world_section.is_visible():
        print("4. Found '世界管理' section")

    # Look for any add-world button
    add_world_clicked = False
    for txt in ["新建世界", "+ 世界", "新建", "创建世界", "添加世界"]:
        btns = page.get_by_text(txt).all()
        for b in btns:
            try:
                if b.is_visible() and b.is_enabled():
                    b.click()
                    page.wait_for_timeout(1000)
                    add_world_clicked = True
                    print(f"4. Clicked '{txt}' button")
                    break
            except Exception:
                pass
        if add_world_clicked:
            break

    if not add_world_clicked:
        # List all buttons to understand UI structure
        print("4. Listing all visible buttons:")
        for b in page.locator("button").all():
            try:
                if b.is_visible():
                    print(f"   button: {b.inner_text().strip()[:60]!r}")
            except Exception:
                pass

    page.screenshot(path=f"{SS_DIR}/04_world_modal.png")

    # 5. Look for AI Research tab
    ai_tab = page.get_by_text("AI 研究").first
    if ai_tab.count() > 0 and ai_tab.is_visible():
        ai_tab.click()
        page.wait_for_timeout(500)
        page.screenshot(path=f"{SS_DIR}/05_ai_tab.png")
        print("5. AI Research tab FOUND and clicked!")

        # Describe what we see
        headings = page.locator("h1, h2, h3, p").all()
        for h in headings[:8]:
            try:
                if h.is_visible():
                    print(f"   text: {h.inner_text().strip()[:80]!r}")
            except Exception:
                pass

        # Find research button
        for txt in ["开始研究", "研究", "Start"]:
            b = page.get_by_text(txt).first
            if b.count() > 0 and b.is_visible():
                print(f"   Found button: '{b.inner_text()}'")
                break
    else:
        print("5. AI Research tab NOT FOUND in current UI state")
        # List tabs if any modal is open
        all_btns = page.locator("button").all()
        for b in all_btns:
            try:
                if b.is_visible():
                    print(f"   btn: {b.inner_text().strip()[:50]!r}")
            except Exception:
                pass
        page.screenshot(path=f"{SS_DIR}/05_no_ai_tab.png")

    browser.close()
    print(f"\nScreenshots: {SS_DIR}/")
