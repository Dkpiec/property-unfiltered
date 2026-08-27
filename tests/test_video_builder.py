import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from src import video_builder as vb  # noqa: E402
from src import voiceover  # noqa: E402


def _probe_streams(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return [s["codec_type"] for s in json.loads(r.stdout)["streams"]]


def test_word_durations_sum_to_total():
    sections = [
        {"text": "one two three four"},
        {"text": "one two"},
    ]
    durs = vb._word_durations(sections, 9.0)
    assert len(durs) == 2
    assert abs(sum(durs) - 9.0) < 1e-6
    assert durs[0] > durs[1]  # more words -> longer segment


def test_build_produces_short_mp4(tmp_path):
    os.environ["TTS_DRY_RUN"] = "1"
    try:
        sections = [
            {"heading": "Hook", "text": "Gurgaon prices are rising fast."},
            {"heading": "Data", "text": "Noida offers better value per square foot."},
            {"heading": "CTA", "text": "Subscribe for weekly NCR data."},
        ]
        audio, dur = voiceover.synthesize(
            [s["text"] for s in sections], tmp_path / "vo.wav"
        )
        out = tmp_path / "short.mp4"
        vb.build(sections, audio, " ".join(s["text"] for s in sections),
                 "Short", out, workdir=tmp_path / "work")

        assert out.exists()
        assert out.stat().st_size > 5000
        streams = _probe_streams(out)
        assert "video" in streams and "audio" in streams
        final_dur = vb._audio_duration(out)
        # audio is 3s/section = 9s; allow concat/rounding slack
        assert abs(final_dur - dur) < 2.0
    finally:
        os.environ.pop("TTS_DRY_RUN", None)


def test_title_card_generated(tmp_path):
    img = tmp_path / "card.png"
    vb._make_title_card("Test Heading", (1080, 1920), img)
    assert img.exists()
    assert img.stat().st_size > 1000
