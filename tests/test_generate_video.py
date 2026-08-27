import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import generate_video as gv  # noqa: E402

SCRIPT_FIXTURE = {
    "content_type": "Short",
    "working_title": "Gurgaon prices 2026",
    "hook": "Prices in Gurgaon are climbing.",
    "sections": [
        {"heading": "Hook", "text": "Prices in Gurgaon are climbing steadily."},
        {"heading": "Why", "text": "New infrastructure is driving demand."},
    ],
    "cta": "Subscribe for weekly NCR data.",
    "full_script": "Prices in Gurgaon are climbing steadily. New infrastructure is driving demand. Subscribe for weekly NCR data.",
}

META_FIXTURE = {
    "titles": ["T1", "T2", "T3", "T4", "T5"],
    "description": "SEO desc.",
    "tags": [f"tag{i}" for i in range(15)],
    "thumbnail_ideas": ["Data", "No hype"],
}


@pytest.fixture
def fake_topics(tmp_path):
    manifest = {"topics": [
        {"id": 1, "title": "Gurgaon prices 2026", "type": "Short",
         "rationale": "r", "keywords": ["Gurgaon"], "score": 1.0},
    ]}
    out = Path(__file__).resolve().parent.parent / "output"
    out.mkdir(exist_ok=True)
    (out / "pending_topics.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield
    (out / "pending_topics.json").unlink(missing_ok=True)


def test_main_generates_review_and_mp4(monkeypatch, fake_topics):
    import src.scriptwriter as sw

    def fake_generate(task, prompt, system=None):
        return (SCRIPT_FIXTURE if task == "script" else META_FIXTURE), ""

    monkeypatch.setattr(sw.llm, "generate", fake_generate)
    os.environ["TTS_DRY_RUN"] = "1"
    try:
        rc = gv.main(["--topics", "1"])
        assert rc == 0

        out = Path(__file__).resolve().parent.parent / "output"
        review_path = out / "pending_video_review.json"
        assert review_path.exists()
        data = json.loads(review_path.read_text(encoding="utf-8"))
        assert data["count"] == 1
        review = data["videos"][0]
        assert review["content_type"] == "Short"
        assert len(review["titles"]) == 5
        assert len(review["tags"]) == 15
        video = Path(review["video_path"])
        assert video.exists() and video.stat().st_size > 5000
    finally:
        os.environ.pop("TTS_DRY_RUN", None)
        out = Path(__file__).resolve().parent.parent / "output"
        (out / "pending_video_review.json").unlink(missing_ok=True)
