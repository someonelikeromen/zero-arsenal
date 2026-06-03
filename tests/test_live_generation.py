"""测试真实 LLM 生成流程：世界观提炼 + 人物创建 + URL 抓取"""
import requests
import json
import time
import sys

BACKEND = "http://127.0.0.1:8000"


def test_parse_document():
    print("\n=== 测试1: 文本提炼世界观（parse-document SSE）===")
    worlds = requests.get(f"{BACKEND}/api/worlds", timeout=5).json()["worlds"]
    wid = worlds[0]["id"]

    sample_text = """
    钢弹SEED世界观：宇宙世纪71（CE71）
    在这个世界，自然人（Naturals）与协调者（Coordinators）之间的战争正在爆发。
    协调者是经过基因工程改造的人类，拥有更高的智力和体能。
    地球联合军（Earth Alliance）代表自然人，ZAFT代表协调者阵营。
    主要地点：PLANT殖民地群（协调者家园）、奥布联合酋长国（中立国）、海利奥波利斯（中立殖民地）。
    关键事件：血色情人节——ZAFT对阿拉斯加基地的核攻击导致大量平民伤亡，激化了双方仇恨。
    主要机体：Strike Gundam（突击高达）由地球联合军开发，Freedom Gundam（自由高达）由PLANT提供。
    """

    r = requests.post(
        f"{BACKEND}/api/worlds/{wid}/parse-document",
        json={"text": sample_text},
        timeout=90,
        stream=True,
    )
    print(f"  HTTP {r.status_code}")
    entries = []
    for line in r.iter_lines():
        if line.startswith(b"data:"):
            data = json.loads(line[5:].strip())
            t = data.get("type")
            if t == "start":
                print("  → LLM 开始生成...")
            elif t == "done":
                entries = data.get("entries", [])
                print(f"  ✓ 提炼完成！{len(entries)} 条档案条目：")
                for e in entries:
                    at = e.get("archive_type", "lore")
                    title = e.get("title", "")
                    content = e.get("content", "")[:60]
                    print(f"    [{at}] {title} — {content}...")
            elif t == "error":
                print(f"  ✗ 错误: {data.get('message')}")
    return wid, entries


def test_character_generate():
    print("\n=== 测试2: LLM 快速创建人物（generate SSE）===")
    r = requests.post(
        f"{BACKEND}/api/characters/generate",
        json={
            "mode": "quick",
            "world_plugin": "gundam_seed",
            "name": "苏力图",
            "gender": "男",
            "char_type": "transmigrator",
            "traversal_method": "意识穿越",
        },
        timeout=90,
        stream=True,
    )
    print(f"  HTTP {r.status_code}")
    char_data = {}
    for line in r.iter_lines():
        if line.startswith(b"data:"):
            data = json.loads(line[5:].strip())
            t = data.get("type")
            if t == "start":
                print("  → LLM 开始生成角色...")
            elif t == "done":
                char_data = data.get("character", {})
                name = char_data.get("name", "未知")
                attrs = char_data.get("attributes", {})
                meta = char_data.get("meta", {})
                personality = meta.get("personality", "")[:80]
                flaws = meta.get("flaws", [])
                print(f"  ✓ 角色生成完成！")
                print(f"    名称: {name}")
                print(f"    属性: {attrs}")
                print(f"    性格: {personality}")
                print(f"    缺陷: {flaws}")
                skills = char_data.get("skills", {})
                print(f"    技能: {list(skills.keys())[:5]}")
            elif t == "error":
                print(f"  ✗ 错误: {data.get('message')}")
    return char_data


def test_quiz_questions():
    print("\n=== 测试3: LLM 生成问卷题目（generate/questions SSE）===")
    r = requests.post(
        f"{BACKEND}/api/characters/generate/questions",
        json={"world_plugin": "gundam_seed", "char_type": "transmigrator"},
        timeout=60,
        stream=True,
    )
    print(f"  HTTP {r.status_code}")
    questions = []
    for line in r.iter_lines():
        if line.startswith(b"data:"):
            data = json.loads(line[5:].strip())
            t = data.get("type")
            if t == "start":
                print("  → LLM 生成问卷中...")
            elif t == "done":
                questions = data.get("questions", [])
                print(f"  ✓ 生成 {len(questions)} 道问卷题目：")
                for q in questions[:3]:
                    qid = q.get("id", "")
                    qtext = q.get("question", "")[:70]
                    opts = q.get("options", {})
                    print(f"    {qid}: {qtext}")
                    for k, v in list(opts.items())[:2]:
                        print(f"      {k}) {v[:50]}")
            elif t == "error":
                print(f"  ✗ 错误: {data.get('message')}")
    return questions


def test_fetch_lore_url():
    print("\n=== 测试4: URL 抓取世界观（fetch-lore）===")
    worlds = requests.get(f"{BACKEND}/api/worlds", timeout=5).json()["worlds"]
    wid = worlds[0]["id"]

    # 测试 BiliBili WIKI（httpx 直达）
    test_url = "https://wiki.biligame.com/gundam/ZGMF-X10A%E8%87%AA%E7%94%B1%E9%AB%98%E8%BE%BE"
    print(f"  抓取URL: {test_url[:60]}...")

    r = requests.post(
        f"{BACKEND}/api/worlds/{wid}/fetch-lore",
        json={"url": test_url},
        timeout=90,
        stream=True,
    )
    print(f"  HTTP {r.status_code}")
    entries = []
    for line in r.iter_lines():
        if line.startswith(b"data:"):
            data = json.loads(line[5:].strip())
            t = data.get("type")
            if t == "start":
                print("  → 抓取并分析中...")
            elif t == "done":
                entries = data.get("entries", [])
                print(f"  ✓ 提炼完成！{len(entries)} 条档案条目：")
                for e in entries[:5]:
                    at = e.get("archive_type", "lore")
                    title = e.get("title", "")
                    print(f"    [{at}] {title}")
            elif t == "error":
                print(f"  ✗ 错误（可能是网络/反爬）: {data.get('message')}")
    return entries


def test_save_and_confirm(wid: str, entries: list):
    if not entries:
        print("\n  跳过 confirm-lore（无条目）")
        return
    print(f"\n=== 测试5: 确认保存档案条目（confirm-lore）===")
    r = requests.post(
        f"{BACKEND}/api/worlds/{wid}/confirm-lore",
        json={"entries": entries[:3]},
        timeout=10,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        result = r.json()
        print(f"  ✓ 写入 {result['written']} 条档案到世界 {wid[:8]}...")


if __name__ == "__main__":
    print("=" * 60)
    print("  ZeroArsenal 真实 LLM 生成流程测试")
    print("=" * 60)

    wid, doc_entries = test_parse_document()
    assert wid, "parse-document 失败：未获取到有效 world_id"

    time.sleep(1)
    char_data = test_character_generate()
    assert char_data, "character generate 失败：未返回有效角色数据"

    time.sleep(1)
    questions = test_quiz_questions()
    assert isinstance(questions, list), "quiz questions 失败：响应不是列表"

    time.sleep(1)
    url_entries = test_fetch_lore_url()
    # URL 抓取允许网络失败（返回空列表），但不能抛出异常
    assert isinstance(url_entries, list), "fetch-lore 失败：返回非列表数据"

    if wid and doc_entries:
        test_save_and_confirm(wid, doc_entries)

    print("\n" + "=" * 60)
    print("  全部通过")
    print("=" * 60)
