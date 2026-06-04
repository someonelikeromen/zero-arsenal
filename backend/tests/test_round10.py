# -*- coding: utf-8 -*-
"""
第十轮测试 — 验证：
1. TurnContext 去重后字段正确（无重复声明）
2. 记忆 ExtractQueue 5W1H tier 分层（core / semantic / episodic）
3. SQLite fallback 4层结构（tier SQL 查询分支逻辑）
4. GET /sessions/{id} 返回 message_count + current_chapter 字段

注：本文件多为静态源码字符串检查 / 在测试内重写业务逻辑（见 STUB_ANALYSIS T10），
不验证真实运行时行为，整体标注 stub，CI 以 `-m "not stub"` 排除。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytestmark = pytest.mark.stub


# ── Test 1: TurnContext 字段完整性 ───────────────────────────────────────────

def test_turn_context_no_duplicates():
    from agents.state import TurnContext
    import dataclasses

    field_names = [f.name for f in dataclasses.fields(TurnContext)]
    # 不应有重复字段
    assert len(field_names) == len(set(field_names)), f"重复字段: {[x for x in field_names if field_names.count(x) > 1]}"

    # 必须包含新增字段
    assert 'turn_index' in field_names, "缺少 turn_index"
    assert 'rules_roll' in field_names, "缺少 rules_roll"
    assert 'rules_verdict' in field_names, "缺少 rules_verdict"
    assert 'style_warnings' in field_names, "缺少 style_warnings"
    assert 'var_updates' in field_names, "缺少 var_updates"

    # 实例化验证
    ctx = TurnContext(session_id="s1", message_id="m1", user_input="测试")
    assert ctx.turn_index == 0
    assert ctx.rules_verdict == "pass"
    assert ctx.rules_roll is None
    assert ctx.purity_score == 1.0
    print("✓ TurnContext 字段完整，无重复")


# ── Test 2: ExtractQueue 5W1H tier 分层 ─────────────────────────────────────

def test_extract_queue_tier_logic():
    # 导入被测真实业务逻辑（不再在测试内重写副本，见 STUB-T10）
    from memory.extract_queue import determine_tier

    # 核心关键词应分到 core
    assert determine_tier("林劫突破了第三境界，获得了神秘能力") == "core", "突破/获得 应为 core"
    assert determine_tier("任务完成：刺杀完成，叛变者已伏诛") == "core", "任务完成 应为 core"

    # 实体描述应分到 semantic
    assert determine_tier("赤焰门是当地最大的帮派组织") == "semantic", "实体描述应为 semantic"
    assert determine_tier("云雾城——一座靠近边境的贸易重镇") == "semantic", "地点描述应为 semantic"

    # 普通叙事应分到 episodic
    assert determine_tier("夜风轻拂，街道上行人稀少") == "episodic", "普通叙事应为 episodic"
    assert determine_tier("他抬起手，推开了那扇沉重的铁门") == "episodic", "动作叙述应为 episodic"

    print("✓ ExtractQueue 5W1H tier 分层逻辑正确")


# ── Test 3: SQLite 4层 fallback recall 查询结构 ──────────────────────────────

def test_memory_fallback_tier_structure():
    """验证 _fallback_recall 函数的 tier 分层 SQL 查询结构存在"""
    import inspect
    from memory.adapter import MemoryAdapter

    src = inspect.getsource(MemoryAdapter._fallback_recall)

    # 应该有 core / semantic / episodic 三个 tier 查询
    assert "tier='core'" in src, "缺少 core tier 查询"
    assert "tier='semantic'" in src, "缺少 semantic tier 查询"
    assert "tier='episodic'" in src, "缺少 episodic tier 查询"

    # 应该有章节摘要
    assert "chapter" in src.lower(), "缺少章节摘要查询"

    # 应该有关键词 LIKE 匹配
    assert "LIKE" in src, "缺少 LIKE 关键词匹配"

    print("✓ SQLite 4层 fallback 包含 core/semantic/episodic tier 查询")


# ── Test 4: session API 字段检查 ─────────────────────────────────────────────

def test_get_session_enriched_fields():
    """验证 get_session 路由中含有 message_count 和 current_chapter 字段的查询"""
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "routes_check",
        Path(__file__).parent.parent / "api" / "routes.py"
    )
    mod = importlib.util.load_from_spec = None  # 不真正导入，只检查源码

    src = open(Path(__file__).parent.parent / "api" / "routes.py", encoding="utf-8").read()

    # 找到 get_session 函数中的 message_count
    idx = src.find("async def get_session")
    assert idx != -1, "找不到 get_session 函数"
    segment = src[idx:idx + 800]
    assert "message_count" in segment, "get_session 缺少 message_count 字段"
    assert "current_chapter" in segment, "get_session 缺少 current_chapter 字段"

    print("✓ GET /sessions/{id} 返回 message_count + current_chapter")


# ── Test 5: WorldPanel NPC tab 存在 ──────────────────────────────────────────

def test_world_panel_npc_tab():
    """验证 WorldPanel 包含 NPC 档案 Tab"""
    src = open(
        Path(__file__).parent.parent.parent / "frontend" / "src" / "components" / "panels" / "WorldPanel.tsx",
        encoding="utf-8"
    ).read()

    assert "NpcProfile" in src, "缺少 NpcProfile 接口"
    assert "tab === 'npcs'" in src or "tab==='npcs'" in src, "缺少 NPC tab 判断"
    assert "/api/sessions/${sessionId}/npcs" in src, "缺少 NPC 数据 fetch"
    print("✓ WorldPanel 包含 NPC 档案 Tab")


# ── Test 6: CharacterPanel 技能/物品展示 ─────────────────────────────────────

def test_character_panel_skills_inventory():
    """验证 CharacterPanel 含有 skills 和 inventory 渲染逻辑"""
    src = open(
        Path(__file__).parent.parent.parent / "frontend" / "src" / "components" / "panels" / "CharacterPanel.tsx",
        encoding="utf-8"
    ).read()

    assert "skills" in src, "缺少 skills 渲染"
    assert "inventory" in src, "缺少 inventory 渲染"
    assert "meta" in src, "缺少 meta 渲染"
    print("✓ CharacterPanel 含有技能、物品栏、meta 字段渲染")


if __name__ == "__main__":
    test_turn_context_no_duplicates()
    test_extract_queue_tier_logic()
    test_memory_fallback_tier_structure()
    test_get_session_enriched_fields()
    test_world_panel_npc_tab()
    test_character_panel_skills_inventory()
    print("\n✅ 第十轮所有测试通过")
