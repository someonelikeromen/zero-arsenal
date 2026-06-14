# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import sys
import time
import types
from pathlib import Path


def _install_langgraph_stub():
    if "langgraph.graph" in sys.modules:
        return
    langgraph = types.ModuleType("langgraph")
    graph = types.ModuleType("langgraph.graph")

    def add_messages(left, right):
        return (left or []) + (right or [])

    class StateGraph:
        def __init__(self, *args, **kwargs):
            pass

    graph.add_messages = add_messages
    graph.StateGraph = StateGraph
    graph.START = "__start__"
    graph.END = "__end__"
    langgraph.graph = graph
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = graph


def test_generate_opening_persists_assistant_message_before_pipeline(monkeypatch, tmp_path):
    _install_langgraph_stub()
    from backend.db.connection import init_db, set_db_path
    import importlib.util

    api_pkg = types.ModuleType("backend.api")
    api_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "backend" / "api")]
    routers_pkg = types.ModuleType("backend.api.routers")
    routers_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "backend" / "api" / "routers")]
    monkeypatch.setitem(sys.modules, "backend.api", api_pkg)
    monkeypatch.setitem(sys.modules, "backend.api.routers", routers_pkg)
    spec = importlib.util.spec_from_file_location(
        "backend.api.routers.stream",
        Path(__file__).resolve().parents[2] / "backend" / "api" / "routers" / "stream.py",
    )
    assert spec and spec.loader
    stream = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "backend.api.routers.stream", stream)
    spec.loader.exec_module(stream)

    db_path = tmp_path / "zero_arsenal.db"
    set_db_path(db_path)
    asyncio.run(init_db())

    session_id = "session-opening"
    now = time.time()
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO sessions (id, plugin_key, agent_profile, mode, title, created_at, updated_at) "
            "VALUES (?, 'crossover', 'play', 'play', 'Opening Test', ?, ?)",
            (session_id, now, now),
        )
        db.commit()

    captured = {}

    class ImmediateBackgroundTasks:
        def add_task(self, fn, *args, **kwargs):
            captured["task"] = (fn, args, kwargs)

    async def fake_pipeline(session_arg, message_arg, content_arg):
        captured["pipeline"] = (session_arg, message_arg, content_arg)
        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "INSERT INTO message_parts "
                "(id, message_id, session_id, type, content, status, agent, sort_order, metadata, created_at, updated_at) "
                "VALUES ('part-opening', ?, ?, 'narrative', '{}', 'done', 'test', 0, '{}', ?, ?)",
                (message_arg, session_arg, now, now),
            )
            db.commit()

    monkeypatch.setattr(stream, "_run_agent_pipeline", fake_pipeline)

    result = asyncio.run(stream.generate_opening(session_id, ImmediateBackgroundTasks()))
    fn, args, kwargs = captured["task"]
    assert kwargs == {}
    asyncio.run(fn(*args))

    with sqlite3.connect(db_path) as db:
        msg = db.execute(
            "SELECT role, content, message_type FROM messages WHERE id=?",
            (result["message_id"],),
        ).fetchone()
        part_count = db.execute(
            "SELECT COUNT(*) FROM message_parts WHERE message_id=?",
            (result["message_id"],),
        ).fetchone()[0]

    assert msg == ("assistant", captured["pipeline"][2], "opening")
    assert part_count == 1


def test_skill_condition_rejects_dunder_expression():
    from backend.tools.skill_loader import SkillMeta, SkillRegistry

    registry = SkillRegistry()
    skill = SkillMeta(
        name="unsafe",
        description="",
        trigger="auto",
        condition='state.__class__.__mro__[1].__subclasses__()',
    )

    assert registry.evaluate_condition(skill, {"mode": "combat"}) is False


def test_skill_condition_allows_simple_state_lookup():
    from backend.tools.skill_loader import SkillMeta, SkillRegistry

    registry = SkillRegistry()
    skill = SkillMeta(
        name="safe",
        description="",
        trigger="auto",
        condition='state["mode"] == "combat" and state["plugin_key"] == "crossover"',
    )

    assert registry.evaluate_condition(skill, {"mode": "combat", "plugin_key": "crossover"}) is True


def test_prompt_condition_rejects_dunder_expression():
    from backend.prompts.registry import PromptRegistry

    registry = PromptRegistry()

    assert registry._evaluate_condition('state.__class__.__mro__[1].__subclasses__()', {"mode": "combat"}) is False
