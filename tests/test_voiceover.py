import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import pytest  # noqa: E402

from src import voiceover as vo  # noqa: E402


def test_dry_run_creates_wav(tmp_path):
    os.environ["TTS_DRY_RUN"] = "1"
    try:
        out = tmp_path / "test_dry.wav"
        sections = ["Hello world.", "This is a test."]
        path, duration = vo.synthesize(sections, out)
        assert path.exists()
        assert path.stat().st_size > 100   # has actual audio data
        assert duration > 4.0               # 2 sections × 3s each
    finally:
        os.environ.pop("TTS_DRY_RUN", None)


def test_get_audio_duration_ffprobe(tmp_path):
    # Create a known-duration sine wav
    wav = tmp_path / "beep.wav"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2.5",
         "-ar", "24000", "-ac", "1", str(wav)],
        check=True, capture_output=True,
    )
    dur = vo.get_audio_duration(wav)
    assert abs(dur - 2.5) < 0.1


def test_concat_wavs(tmp_path):
    # Generate two short wavs, concat, check duration
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
                    "-ar", "24000", "-ac", "1", str(a)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1.5",
                    "-ar", "24000", "-ac", "1", str(b)], check=True, capture_output=True)
    out = tmp_path / "concat.wav"
    vo._concat_wavs([a, b], out)
    assert out.exists()
    dur = vo.get_audio_duration(out)
    assert abs(dur - 2.5) < 0.2