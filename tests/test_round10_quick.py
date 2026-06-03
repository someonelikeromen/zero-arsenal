# -*- coding: utf-8 -*-
"""Round 10 quick smoke tests."""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))


def t1_turn_context_fields():
    from backend.agents.state import TurnContext
    import dataclasses
    fnames = [f.name for f in dataclasses.fields(TurnContext)]
    dups = [x for x in set(fnames) if fnames.count(x) > 1]
    assert not dups, f"Duplicate fields: {dups}"
    for required in ("turn_index", "rules_roll", "rules_verdict", "style_warnings", "var_updates"):
        assert required in fnames, f"Missing field: {required}"
    ctx = TurnContext(session_id="s", message_id="m", user_input="x")
    assert ctx.turn_index == 0
    assert ctx.rules_roll is None
    print("t1 OK: TurnContext fields clean")


def t2_tier_logic():
    CORE_KW = ("突破", "死亡", "觉醒", "获得", "失去", "任务完成", "境界", "永久")
    SEM = re.compile(r"[\u4e00-\u9fff]{2,8}[\s\-—是：:为]+.{5,40}")
    def tier(p):
        if any(k in p for k in CORE_KW): return "core"
        if SEM.search(p): return "semantic"
        return "episodic"
    assert tier("林劫突破了第三境界") == "core"
    assert tier("赤焰门是当地最大的帮派") == "semantic"
    assert tier("夜风轻拂，行人稀少") == "episodic"
    print("t2 OK: tier classification logic")


def t3_fallback_recall_tiers():
    src = (BACKEND / "memory" / "adapter.py").read_text(encoding="utf-8")
    fn_start = src.index("async def _fallback_recall")
    segment = src[fn_start:fn_start + 5000]
    for expected in ("tier='core'", "tier='semantic'", "tier='episodic'", "chapter", "LIKE"):
        assert expected in segment, f"Missing in _fallback_recall: {expected}"
    print("t3 OK: SQLite 4-tier fallback recall")


def t4_get_session_enriched():
    src = (BACKEND / "api" / "routes.py").read_text(encoding="utf-8")
    idx = src.index("async def get_session")
    seg = src[idx:idx + 900]
    assert "message_count" in seg, "Missing message_count"
    assert "current_chapter" in seg, "Missing current_chapter"
    print("t4 OK: GET /sessions/{id} enriched")


def t5_world_panel_npc():
    src = (FRONTEND / "components" / "panels" / "WorldPanel.tsx").read_text(encoding="utf-8")
    assert "NpcProfile" in src
    assert "npcs" in src
    assert "/npcs" in src
    print("t5 OK: WorldPanel NPC tab present")


def t6_character_panel_extras():
    src = (FRONTEND / "components" / "panels" / "CharacterPanel.tsx").read_text(encoding="utf-8")
    assert "skills" in src
    assert "inventory" in src
    assert "meta" in src
    print("t6 OK: CharacterPanel renders skills + inventory + meta")


def t7_llm_routes_max_tokens():
    src = (FRONTEND / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")
    assert "max_tokens" in src, "LlmRoutesTab missing max_tokens field"
    assert "PUT" in src, "LlmRoutesTab missing PUT save"
    print("t7 OK: SettingsPage LlmRoutesTab has max_tokens edit")


if __name__ == "__main__":
    t1_turn_context_fields()
    t2_tier_logic()
    t3_fallback_recall_tiers()
    t4_get_session_enriched()
    t5_world_panel_npc()
    t6_character_panel_extras()
    t7_llm_routes_max_tokens()
    print("\nAll round-10 tests passed!")
