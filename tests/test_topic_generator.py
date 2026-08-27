import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import topic_generator as tg  # noqa: E402

SETTINGS = {
    "topics": {"final_count": 5, "min_shorts": 1, "min_long": 1},
    "paths": {"output": "output"},
}
KEYWORDS = [
    {"kw": "Gurgaon", "weight": 1.0},
    {"kw": "Noida", "weight": 1.0},
    {"kw": "RERA", "weight": 0.9},
]


def make_candidates(n, type_="Short"):
    return [{
        "title": f"Topic {i} Gurgaon RERA",
        "type": type_,
        "rationale": "r",
        "keywords": ["Gurgaon", "RERA"],
        "score": 100.0 - i,
    } for i in range(n)]


def test_normalize_filters_bad():
    data = {"candidates": [
        {"title": "Good Short", "type": "Short", "rationale": "x", "keywords": ["Noida"]},
        {"title": "", "type": "Short"},  # empty title -> dropped
        {"title": "No type", "type": "Blog"},  # bad type -> dropped
    ]}
    out = tg.normalize_candidates(data)
    assert len(out) == 1
    assert out[0]["title"] == "Good Short"
    assert out[0]["type"] == "Short"


def test_score_topic():
    c = {"title": "Gurgaon vs Noida prices", "keywords": ["Gurgaon", "Noida"]}
    assert tg.score_topic(c, KEYWORDS) == pytest.approx(2.0)
    c2 = {"title": "Investing tips", "keywords": []}
    assert tg.score_topic(c2, KEYWORDS) == pytest.approx(0.0)


def test_select_top_mix_and_count():
    # 3 Shorts (higher scores) + 3 Longs
    candidates = make_candidates(3, "Short") + make_candidates(3, "Long")
    selected = tg.select_top(candidates, SETTINGS)
    assert len(selected) == 5
    types = {c["type"] for c in selected}
    assert "Short" in types and "Long" in types


def test_select_top_all_same_type_fills_remaining():
    candidates = make_candidates(6, "Short")
    selected = tg.select_top(candidates, SETTINGS)
    assert len(selected) == 5
    assert all(c["type"] == "Short" for c in selected)


def test_main_writes_manifest(monkeypatch, tmp_path):
    captured = {}

    class FakeLLM:
        @staticmethod
        def generate(task, prompt, system=None):
            return {"candidates": make_candidates(10, "Short") + make_candidates(4, "Long")}, ""

    monkeypatch.setattr(tg.llm, "generate", FakeLLM.generate)
    monkeypatch.setattr(tg.research, "enrich", lambda topic: {})
    monkeypatch.setattr(tg.utils, "write_manifest",
                        lambda path, data: captured.update(path=path, data=data))

    rc = tg.main()
    assert rc == 0
    assert len(captured["data"]["topics"]) == 5
    assert captured["path"].name == "pending_topics.json"
    # every topic has the manifest schema
    for t in captured["data"]["topics"]:
        assert {"id", "title", "type", "rationale", "keywords", "score"} <= set(t)
