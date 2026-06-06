"""
真实 LLM 测试 — 使用 DeepSeek 官方 Key 验证各 Agent 管线。
运行：  python test_llm_real.py
"""
import asyncio
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 加载 .env
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=True)

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
print(f"[KEY] DEEPSEEK_API_KEY={'*' * 8 + KEY[-6:] if KEY else 'NOT SET'}")

# ── 测试 1：直接 litellm 调用 ───────────────────────────────────────────────

async def test_basic_llm():
    print("\n=== Test 1: litellm 直接调用 ===")
    import litellm
    resp = await litellm.acompletion(
        model="deepseek/deepseek-chat",
        messages=[{"role": "user", "content": "用一句话介绍自己，你是什么"}],
        temperature=0.5,
        max_tokens=80,
    )
    text = resp.choices[0].message.content
    print(f"[LLM] 响应: {text}")
    assert text and len(text) > 5, "响应为空"
    print("[OK] litellm 直接调用成功")


# ── 测试 2：通过 llm.py 封装层 ─────────────────────────────────────────────

async def test_llm_wrapper():
    print("\n=== Test 2: llm.py 封装层 ===")
    sys.path.insert(0, ".")
    from backend.agents.llm import llm_complete, llm_stream

    # 非流式
    result = await llm_complete(
        messages=[{"role": "user", "content": "请用三个词描述'跑团小说'"}],
        provider="deepseek",
        model="deepseek-chat",
        temperature=0.3,
        max_tokens=50,
    )
    print(f"[llm_complete] {result}")
    assert result, "llm_complete 返回空"

    # 流式
    chunks = []
    async def on_delta(d: str):
        chunks.append(d)

    full = await llm_stream(
        messages=[{"role": "user", "content": "写一句优美的武侠开场白（20字内）"}],
        on_delta=on_delta,
        provider="deepseek",
        model="deepseek-chat",
        temperature=0.8,
        max_tokens=60,
    )
    print(f"[llm_stream] {full} (chunks={len(chunks)})")
    assert full and len(chunks) >= 1, "流式返回异常"
    print("[OK] llm.py 封装层测试通过")


# ── 测试 3：RulesAgent ─────────────────────────────────────────────────────

async def test_rules_agent():
    print("\n=== Test 3: RulesAgent ===")
    from backend.agents.state import TurnContext
    from backend.agents.rules_agent import rules_agent_node

    ctx = TurnContext(
        session_id="test-session",
        message_id="test-msg-1",
        user_input="我尝试用剑劈开眼前的石门",
        plugin_key="crossover",
        mode="play",
        character_data={"identity": {"name": "测试角色"}},
    )
    result = await rules_agent_node(ctx)
    print(f"[rules_verdict] {result.rules_verdict} | reason: {result.rules_reason}")
    assert result.rules_verdict in ("pass", "block"), f"意外的 verdict: {result.rules_verdict}"
    print("[OK] RulesAgent 通过")


# ── 测试 4：DM Agent ───────────────────────────────────────────────────────

async def test_dm_agent():
    print("\n=== Test 4: DM Agent ===")
    from backend.agents.state import TurnContext
    from backend.agents.dm_agent import dm_agent_node

    ctx = TurnContext(
        session_id="test-session",
        message_id="test-msg-2",
        user_input="我向守卫谎称自己是城主的使者，要求进入密室",
        plugin_key="crossover",
        mode="play",
        character_data={"identity": {"name": "李逍遥"}, "attributes": {"charisma": {"base": 7}}},
    )
    result = await dm_agent_node(ctx)
    print(f"[dm_verdict] {result.dm_verdict} | note: {result.dm_note}")
    assert result.dm_verdict in ("allow", "block", "needs_roll"), f"意外 verdict: {result.dm_verdict}"
    print("[OK] DM Agent 通过")


# ── 测试 5：NarratorAgent P3（流式叙事） ──────────────────────────────────

async def test_narrator():
    print("\n=== Test 5: NarratorAgent 流式叙事 ===")

    # 需要初始化 DB（使用独立临时文件避免与运行中的后端 DB 锁冲突）
    from backend.db import init_db, set_db_path
    import tempfile, pathlib
    import uuid
    tmp = pathlib.Path(tempfile.gettempdir()) / f"za_test_{uuid.uuid4().hex}.db"
    set_db_path(tmp)
    await init_db()

    from backend.agents.state import TurnContext
    from backend.agents.narrator_agent import narrator_agent_node

    ctx = TurnContext(
        session_id="test-narr",
        message_id="test-narr-msg",
        user_input="我拔出长剑，向前方的黑影冲去",
        plugin_key="crossover",
        mode="play",
        character_data={"identity": {"name": "剑客赵云"}},
        dm_verdict="allow",
        dm_note="行动合理",
        scene_goal="展示剑客的勇气",
    )
    result = await narrator_agent_node(ctx)
    print(f"[narrative] ({len(result.narrative_text)}字)\n{result.narrative_text[:200]}...")
    assert len(result.narrative_text) >= 30, f"叙事过短: {len(result.narrative_text)}"
    print("[OK] NarratorAgent 通过")


# ── 主入口 ────────────────────────────────────────────────────────────────

async def main():
    tests = [
        test_basic_llm,
        test_llm_wrapper,
        test_rules_agent,
        test_dm_agent,
        test_narrator,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            await t()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
