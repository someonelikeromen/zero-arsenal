"""
test_research_lore.py - Agentic World Research Loop component tests
Usage: python tests/test_research_lore.py
"""
import asyncio
import json
import sys
import urllib.request

BASE = "http://localhost:8001"


def chk(ok): return "[OK]" if ok else "[FAIL]"


def test_tool_registry():
    print("\n=== T1: Tool Registry ===")
    url = f"{BASE}/api/tools"
    try:
        r = urllib.request.urlopen(url, timeout=10)
        data = json.loads(r.read())
        tools = data.get("tools", [])
        names = [t.get("name") for t in tools]
        print(f"  Registered tools count: {len(names)}")
        for wanted in ["web_search", "synthesize_lore", "fetch_webpage", "batch_fetch_lore"]:
            print(f"  {chk(wanted in names)} {wanted}")
        return "web_search" in names and "synthesize_lore" in names
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def test_endpoint_registered():
    print("\n=== T2: research-lore endpoint ===")
    url = f"{BASE}/openapi.json"
    try:
        r = urllib.request.urlopen(url, timeout=10)
        spec = json.loads(r.read())
        paths = spec.get("paths", {})
        found = any("research-lore" in p for p in paths)
        print(f"  {chk(found)} research-lore in OpenAPI paths")
        for p in paths:
            if "research-lore" in p:
                print(f"    -> {p}")
        return found
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


async def test_mediawiki_api():
    print("\n=== T3: MediaWiki API fast path ===")
    sys.path.insert(0, ".")
    from backend.utils.web_scraper import _try_mediawiki_api, _detect_mediawiki_api

    test_cases = [
        ("https://zh.wikipedia.org/wiki/Mobile_Suit_Gundam_SEED", "wikipedia.org"),
        ("https://zh.moegirl.org.cn/Destiny", "moegirl.org.cn"),
        ("https://gundam.fandom.com/wiki/ZGMF-X42S_Destiny_Gundam", "fandom.com"),
        ("https://wiki.biligame.com/gundam/ZGMF-X10A", "biligame.com"),
    ]

    for url, expected_domain in test_cases:
        info = _detect_mediawiki_api(url)
        detected = info is not None
        api_base, title = (info if info else ("N/A", "N/A"))
        print(f"  {chk(detected)} detect {expected_domain}: api={api_base[:50]} title={title}")

    print("\n  Actual Wikipedia fetch...")
    try:
        result = await _try_mediawiki_api(
            "https://zh.wikipedia.org/wiki/Mobile_Suit_Gundam_SEED", max_chars=500
        )
        if result:
            text, engine = result
            print(f"  [OK] engine={engine}, chars={len(text)}")
            print(f"  Preview: {text[:100]}")
        else:
            print("  [FAIL] not recognized as MediaWiki or fetch failed")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_web_search():
    print("\n=== T4: web_search (DuckDuckGo) ===")
    sys.path.insert(0, ".")
    from backend.extensions.web_scraper.tools import _web_search

    result = await _web_search("Gundam SEED wiki setting", max_results=5)
    ok = result.get("ok", False)
    count = result.get("count", 0)
    print(f"  {chk(ok)} ok={ok}, results={count}")
    for r in result.get("results", [])[:3]:
        print(f"    - {r['title'][:50]} -> {r['url'][:60]}")

    if count == 0:
        print("  WARN: 0 results (DDG rate limit or parse failure)")
    return ok


async def test_synthesize_lore():
    print("\n=== T5: synthesize_lore ===")
    sys.path.insert(0, ".")
    from backend.extensions.web_scraper.tools import _synthesize_lore

    sample_texts = [
        "Mobile Suit Gundam SEED takes place in the Cosmic Era (CE) year 71. "
        "Two factions: Earth Alliance vs ZAFT. "
        "Coordinators are genetically enhanced humans; Naturals are ordinary humans. "
        "Bloody Valentine: ZAFT destroyed agricultural colony Junius Seven, killing millions.",

        "Main characters: "
        "Kira Yamato - Coordinator, pilots Strike/Freedom Gundam. "
        "Athrun Zala - ZAFT elite, Kira's friend, pilots Justice Gundam. "
        "Lacus Clyne - Singer, peace activist.",
    ]

    result = await _synthesize_lore(texts=sample_texts, world_name="Gundam SEED")
    ok = result.get("ok", False)
    count = result.get("entries_count", 0)
    print(f"  {chk(ok and count > 0)} ok={ok}, entries={count}")
    for e in result.get("entries", [])[:3]:
        print(f"    [{e.get('archive_type')}] {e.get('title')}: {e.get('content','')[:60]}...")
    return ok and count > 0


def test_research_lore_sse():
    """SSE endpoint E2E - listen for up to 25 seconds."""
    print("\n=== T6: research-lore SSE E2E ===")
    import time

    # Create test world
    create_payload = json.dumps({"name": "GundamSEED_Test", "description": "test"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/worlds",
        data=create_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        r = urllib.request.urlopen(req, timeout=10)
        world_data = json.loads(r.read())
        wid = world_data.get("world_id") or world_data.get("id")
        if not wid:
            print(f"  ERROR: no world_id in response: {world_data}")
            return False
        print(f"  Created world: {wid}")
    except Exception as e:
        print(f"  ERROR creating world: {e}")
        return False

    research_payload = json.dumps({"context": "CE71, space colony war", "max_rounds": 3}).encode()
    req2 = urllib.request.Request(
        f"{BASE}/api/worlds/{wid}/research-lore",
        data=research_payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    events_received = []
    event_types = set()
    timeout = 25

    try:
        resp = urllib.request.urlopen(req2, timeout=timeout + 5)
        start = time.time()
        buf = b""
        print(f"  SSE connected, listening up to {timeout}s...")
        while time.time() - start < timeout:
            chunk = resp.read(512)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                line, buf = buf.split(b"\n\n", 1)
                line_s = line.decode("utf-8", "replace")
                if line_s.startswith("data:"):
                    try:
                        evt = json.loads(line_s[5:].strip())
                        t = evt.get("type", "unknown")
                        event_types.add(t)
                        events_received.append(evt)
                        if t == "tool_call":
                            print(f"    [tool_call] {evt.get('tool')} -- {evt.get('args_brief','')[:60]}")
                        elif t == "tool_done":
                            print(f"    [tool_done] {evt.get('brief','')}")
                        elif t == "thinking":
                            txt = evt.get("text", "")[:60]
                            if txt:
                                print(f"    [thinking] {txt}")
                        elif t == "done":
                            print(f"    [done] entries={len(evt.get('entries', []))}, pages={evt.get('pages_fetched',0)}")
                        elif t == "error":
                            print(f"    [error] {evt.get('message')}")
                    except Exception:
                        pass
            if "done" in event_types or "error" in event_types:
                break
    except Exception as e:
        print(f"  SSE ERROR: {e}")
        return False
    finally:
        try:
            del_req = urllib.request.Request(f"{BASE}/api/worlds/{wid}", method="DELETE")
            urllib.request.urlopen(del_req, timeout=5)
            print(f"  Cleaned world: {wid}")
        except Exception:
            pass

    print(f"  Event types received: {event_types}")
    print(f"  Total events: {len(events_received)}")
    success = len(events_received) > 0 and ("done" in event_types or "tool_call" in event_types)
    print(f"  {chk(success)} SSE received events")
    return success


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    results = {}
    results["tool_registry"] = test_tool_registry()
    results["endpoint_registered"] = test_endpoint_registered()
    asyncio.run(test_mediawiki_api())
    results["web_search"] = asyncio.run(test_web_search())
    results["synthesize_lore"] = asyncio.run(test_synthesize_lore())
    results["research_lore_sse"] = test_research_lore_sse()

    print("\n" + "=" * 50)
    print("Summary:")
    for name, ok in results.items():
        print(f"  {chk(ok)} {name}")
    all_pass = all(results.values())
    print(f"\n{'ALL PASS' if all_pass else 'SOME FAILED'}")
    sys.exit(0 if all_pass else 1)
