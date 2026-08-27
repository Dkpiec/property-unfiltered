import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import utils  # noqa: E402


def test_redact_hides_secret_value():
    os.environ["GOOGLE_API_KEY"] = "super-secret-value-xyz"
    try:
        out = utils.redact("my key is super-secret-value-xyz here")
        assert "[REDACTED]" in out
        assert "super-secret-value-xyz" not in out
    finally:
        os.environ.pop("GOOGLE_API_KEY", None)


def test_json_parse_direct():
    assert utils.json_parse('{"a": 1}') == {"a": 1}


def test_json_parse_fenced():
    out = utils.json_parse('```json\n{"a": 1}\n```')
    assert out == {"a": 1}


def test_json_parse_with_prose():
    out = utils.json_parse('Sure! Here you go:\n{"titles": ["A", "B"]}\nHope that helps.')
    assert out == {"titles": ["A", "B"]}


def test_json_parse_array_embedded():
    out = utils.json_parse('prefix [1, 2, 3] suffix')
    assert out == [1, 2, 3]


def test_json_parse_none():
    assert utils.json_parse("no json here") is None


def test_write_manifest_roundtrip(tmp_path):
    data = {"x": 1, "y": [1, 2, 3]}
    p = utils.write_manifest(tmp_path / "sub" / "m.json", data)
    import json as _json
    assert _json.loads(p.read_text()) == data


def test_load_config_yaml():
    cfg = utils.load_config("config/llm.yaml")
    assert "tasks" in cfg
    assert "topics" in cfg["tasks"]


def test_load_prompt():
    txt = utils.load_prompt("config/prompts/topics_prompt.txt")
    assert "DELHI NCR" in txt
