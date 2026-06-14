"""
E2E test: research-lore SSE endpoint
Creates a world, fires the SSE endpoint, verifies it streams events, then cleans up.
"""
import json, sys, time, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8001"


def create_world(name):
    payload = json.dumps({"name": name, "description": "e2e test"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/worlds",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=10)
    data = json.loads(r.read())
    return data.get("world_id") or data.get("id")


def delete_world(wid):
    try:
        req = urllib.request.Request(f"{BASE}/api/worlds/{wid}", method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def test_sse_endpoint(wid, world_name):
    """Send SSE request and collect events for up to 60 seconds."""
    payload = json.dumps({
        "context": f"Anime/manga world: {world_name}",
        "max_rounds": 4,
    }).encode()

    req = urllib.request.Request(
        f"{BASE}/api/worlds/{wid}/research-lore",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    events = []
    event_types = []

    print(f"  Connecting to SSE (world_id={wid})...")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        print(f"  SSE response: HTTP {resp.status} content-type={resp.headers.get('Content-Type','?')}")

        buf = b""
        start = time.time()
        max_wait = 90  # allow up to 90s for research

        while time.time() - start < max_wait:
            try:
                chunk = resp.read(1024)
            except Exception as e:
                print(f"  Read error: {e}")
                break

            if not chunk:
                print("  Stream closed by server")
                break

            buf += chunk
            while b"\n\n" in buf:
                line_b, buf = buf.split(b"\n\n", 1)
                line = line_b.decode("utf-8", "replace")
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    continue

                t = evt.get("type", "unknown")
                event_types.append(t)
                events.append(evt)

                if t == "tool_call":
                    print(f"    [tool_call] {evt.get('tool')} -- {evt.get('args_brief','')[:60]}")
                elif t == "tool_done":
                    print(f"    [tool_done] {evt.get('brief','')}")
                elif t == "thinking":
                    txt = evt.get("text", "")[:60]
                    if txt:
                        print(f"    [thinking] {txt}")
                elif t == "done":
                    entries = evt.get("entries", [])
                    pages = evt.get("pages_fetched", 0)
                    print(f"    [done] entries={len(entries)} pages={pages}")
                    for e in entries[:3]:
                        print(f"      [{e.get('archive_type')}] {e.get('title','')}: {e.get('content','')[:60]}")
                    break
                elif t == "error":
                    print(f"    [error] {evt.get('message','')}")

            if "done" in event_types or "error" in event_types:
                break

    except urllib.error.URLError as e:
        print(f"  URLError: {e}")
        return False
    except Exception as e:
        print(f"  Exception: {e}")
        return False

    print(f"\n  Events received: {event_types}")
    print(f"  Total events: {len(events)}")

    success = len(events) > 0 and ("done" in event_types or "tool_call" in event_types)
    print(f"  Result: {'PASS' if success else 'FAIL'}")
    return success


if __name__ == "__main__":
    print("=== Research Lore SSE E2E Test ===\n")

    print("Creating test world...")
    wid = create_world("Gundam SEED E2E Test")
    if not wid:
        print("FAIL: could not create world")
        sys.exit(1)
    print(f"  world_id: {wid}")

    try:
        ok = test_sse_endpoint(wid, "Gundam SEED")
    finally:
        delete_world(wid)
        print(f"\nCleaned up world {wid}")

    sys.exit(0 if ok else 1)
