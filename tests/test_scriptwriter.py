import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import scriptwriter as sw  # noqa: E402

SCRIPT_FIXTURE = {
    "content_type": "Long",
    "working_title": "Gurgaon vs Noida 2026",
    "hook": "Which NCR corridor actually delivers returns?",
    "sections": [
        {"heading": "Intro", "text": "We compare Gurgaon and Noida."},
        {"heading": "Prices", "text": "Average prices differ by {{NUM:avg-price}}."},
    ],
    "cta": "Subscribe for weekly NCR data.",
    "full_script": "We compare Gurgaon and Noida. Subscribe.",
}

META_FIXTURE = {
    "titles": ["A", "B", "C", "D", "E"],
    "description": "SEO description here.",
    "tags": [f"tag{i}" for i in range(15)],
    "thumbnail_ideas": ["No hype", "Data"],
}


class FakeLLM:
    responses = {}

    @staticmethod
    def generate(task, prompt, system=None):
        return FakeLLM.responses[task], ""


def test_write_script(monkeypatch):
    FakeLLM.responses = {"script": SCRIPT_FIXTURE}
    monkeypatch.setattr(sw.llm, "generate", FakeLLM.generate)
    settings = {"content": {
        "shorts": {"duration_sec": [30, 60], "words": [130, 170]},
        "long": {"duration_sec": [480, 720], "words": [1100, 1500]},
    }}
    topic = {"title": "Gurgaon vs Noida", "type": "Long"}
    out = sw.write_script(topic, settings)
    assert out["content_type"] == "Long"
    assert out["full_script"] == SCRIPT_FIXTURE["full_script"]


def test_ensure_full_script_builds_when_missing():
    data = {"hook": "H", "sections": [{"text": "S1"}, {"text": "S2"}], "cta": "C"}
    out = sw.ensure_full_script(data)
    assert "S1" in out["full_script"] and "C" in out["full_script"]


def test_write_metadata_normalizes(monkeypatch):
    FakeLLM.responses = {"metadata": META_FIXTURE}
    monkeypatch.setattr(sw.llm, "generate", FakeLLM.generate)
    out = sw.write_metadata("T", "Long", "script text")
    assert len(out["titles"]) == 5
    assert len(out["tags"]) == 15
    assert len(out["thumbnail_ideas"]) >= 2


def test_metadata_short_titles_truncated(monkeypatch):
    fix = dict(META_FIXTURE)
    fix["titles"] = ["only"]
    fix["tags"] = ["a", "b"]
    FakeLLM.responses = {"metadata": fix}
    monkeypatch.setattr(sw.llm, "generate", FakeLLM.generate)
    out = sw.write_metadata("T", "Long", "s")
    assert len(out["titles"]) == 5
    assert len(out["tags"]) == 15


def test_write_full_package(monkeypatch):
    FakeLLM.responses = {"script": SCRIPT_FIXTURE, "metadata": META_FIXTURE}
    monkeypatch.setattr(sw.llm, "generate", FakeLLM.generate)
    settings = {"content": {
        "shorts": {"duration_sec": [30, 60], "words": [130, 170]},
        "long": {"duration_sec": [480, 720], "words": [1100, 1500]},
    }}
    topic = {"title": "Gurgaon vs Noida", "type": "Long"}
    pkg = sw.write_full_package(topic, settings)
    assert "script" in pkg and "metadata" in pkg
    assert pkg["script"]["full_script"]
    assert len(pkg["metadata"]["titles"]) == 5
