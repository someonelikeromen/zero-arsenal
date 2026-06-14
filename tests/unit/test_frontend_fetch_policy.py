# -*- coding: utf-8 -*-
from pathlib import Path


def test_frontend_api_fetches_go_through_api_layer():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    offenders = []
    for path in root.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "fetch(" in text:
            offenders.append(str(path.relative_to(root)).replace("\\", "/"))

    assert offenders == []
