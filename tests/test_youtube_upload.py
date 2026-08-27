import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import youtube_upload as yu  # noqa: E402


def test_load_review_index(monkeypatch, tmp_path):
    manifest = tmp_path / "pending_video_review.json"
    manifest.write_text(json.dumps({"videos": [
        {"titles": ["A"]}, {"titles": ["B"]}
    ]}), encoding="utf-8")
    rev = yu._load_review(manifest, 1)
    assert rev["titles"] == ["B"]


def test_load_review_out_of_range(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"videos": [{"titles": ["A"]}]}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        yu._load_review(manifest, 5)


def test_build_credentials_rejects_bad_json():
    with pytest.raises(Exception):
        yu.build_credentials("not json", "rt")
