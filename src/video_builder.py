"""Assemble the final video with FFmpeg.

For one finished script + voiceover audio this module:
  1. Resolves per-section background sources:
       - stock image via Pexels (if PEXELS_API_KEY set), else
       - generated gradient title card (local, always works).
  2. Builds a Ken Burns clip per section, sized to the section's word share
     of the total audio duration.
  3. Concatenates section clips, applies fade in/out.
  4. Builds subtitles from the voiceover (faster-whisper) or, failing that,
     an approximate SRT derived from audio duration / word count.
  5. Muxes video + audio + burned subtitles and encodes a YouTube-ready MP4
     (libx264, CRF 18, AAC, faststart).

No paid services required. All FFmpeg patterns follow the openmontage/ffmpeg
skill reference.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from src import utils

logger = logging.getLogger("video_builder")

DIMENSIONS = {"Short": (1080, 1920), "Long": (1920, 1080)}
FPS = 30

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _find_font() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True)


# ── Background sources ─────────────────────────────────────────────────
def _fetch_pexels_image(query: str, size: tuple[int, int], out_path: Path) -> bool:
    """Try to fetch a stock image from Pexels. Returns success bool."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return False
    try:
        import requests
        w, h = size
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 1, "orientation": "portrait" if h > w else "landscape"},
            headers={"Authorization": key}, timeout=20,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            return False
        url = photos[0]["src"].get("large2x") or photos[0]["src"].get("original")
        img = requests.get(url, timeout=30)
        img.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img.content)
        return True
    except Exception as exc:  # noqa: BLE001 - fall back to title card
        logger.warning("Pexels fetch failed (%s); using title card", exc)
        return False


def _make_title_card(text: str, size: tuple[int, int], out_path: Path) -> None:
    """Generate a gradient background with the section heading as an overlay."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    font = _find_font()
    vf = []
    # Ken-Burns friendly: draw a subtle darker band for text legibility
    vf.append("drawbox=x=0:y=ih*0.42:w=iw:h=ih*0.16:color=black@0.35:t=fill")
    if font and text:
        escaped = text.replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
        vf.append(f"drawtext=fontfile={font}:text='{escaped}':"
                  f"fontsize={int(h*0.06)}:fontcolor=white:"
                  f"x=(w-text_w)/2:y=(h-text_h)/2")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"gradients=s={w}x{h}:c0=0x0f2027:c1=0x203a43:c2=0x2c5364:n=3",
        "-vf", ",".join(vf),
        "-frames:v", "1", str(out_path),
    ]
    _run(cmd)


def _resolve_backgrounds(sections: list[dict], content_type: str,
                         workdir: Path) -> list[Path]:
    """Return a background image path for each section."""
    size = DIMENSIONS[content_type]
    images: list[Path] = []
    for i, section in enumerate(sections):
        out = workdir / f"bg_{i:03d}.png"
        query = str(section.get("heading") or section.get("text", "")[:40])
        if not _fetch_pexels_image(query, size, out):
            _make_title_card(str(section.get("heading") or f"Section {i+1}"), size, out)
        images.append(out)
    return images


# ── Per-section Ken Burns clips ────────────────────────────────────────
def _kenburns_clip(image: Path, duration: float, content_type: str,
                   out_path: Path) -> None:
    w, h = DIMENSIONS[content_type]
    frames = max(int(duration * FPS), FPS)  # at least 1 second
    # NOTE: no `-loop 1` here. zoompan generates exactly `d` output frames per
    # input frame; looping the input would spawn d frames per looped frame and
    # balloon memory until OOM. Single image + d=N is the memory-safe recipe.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(image),
        "-vf",
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"zoompan=z='min(zoom+0.0008,1.25)':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out_path),
    ]
    _run(cmd)


def _word_durations(sections: list[dict], total_duration: float) -> list[float]:
    total_words = max(sum(len(str(s.get("text", "")).split()) for s in sections), 1)
    durations = []
    for s in sections:
        share = len(str(s.get("text", "")).split()) / total_words
        durations.append(share * total_duration)
    # Normalise to exactly match total
    durations = [d / sum(durations) * total_duration for d in durations]
    return durations


def _build_video_track(sections: list[dict], total_duration: float,
                       content_type: str, workdir: Path) -> Path:
    images = _resolve_backgrounds(sections, content_type, workdir)
    durations = _word_durations(sections, total_duration)
    clips: list[Path] = []
    for i, (img, dur) in enumerate(zip(images, durations)):
        clip = workdir / f"clip_{i:03d}.mp4"
        _kenburns_clip(img, dur, content_type, clip)
        clips.append(clip)

    concat = workdir / "video_track.mp4"
    list_file = workdir / "concat.txt"
    list_file.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(concat),
    ])
    return concat


# ── Subtitles ──────────────────────────────────────────────────────────
def _format_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(segments: list[tuple[float, float, str]], out_path: Path) -> None:
    lines = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_format_ts(start)} --> {_format_ts(end)}")
        lines.append(text)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _make_srt_from_whisper(audio: Path, out_path: Path) -> bool:
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio), language="en")
        srt = [(seg.start, seg.end, seg.text.strip())
               for seg in segments if seg.text.strip()]
        if not srt:
            return False
        _write_srt(srt, out_path)
        return True
    except Exception as exc:  # noqa: BLE001 - fall back to approx
        logger.warning("Whisper transcription failed (%s); using approx SRT", exc)
        return False


def _make_approx_srt(full_script: str, total_duration: float, out_path: Path) -> None:
    words = full_script.split()
    n = len(words)
    per_word = total_duration / max(n, 1)
    segments = []
    i = 0
    while i < n:
        chunk = words[i:i + 8]
        start = i * per_word
        end = (i + len(chunk)) * per_word
        segments.append((start, end, " ".join(chunk)))
        i += 8
    _write_srt(segments, out_path)


def _build_subtitles(audio: Path, full_script: str, total_duration: float,
                     workdir: Path) -> Path:
    srt = workdir / "subtitles.srt"
    if not _make_srt_from_whisper(audio, srt):
        _make_approx_srt(full_script, total_duration, srt)
    return srt


# ── Final mux ──────────────────────────────────────────────────────────
def _final_mux(video_track: Path, audio: Path, srt: Path,
               total_duration: float, content_type: str, out_mp4: Path) -> None:
    w, h = DIMENSIONS[content_type]
    srt_esc = str(srt).replace(":", "\\:").replace("'", "\\'")
    vf = [
        f"fade=t=in:st=0:d=0.5",
        f"fade=t=out:st={max(total_duration-0.6,0):.3f}:d=0.6",
        f"subtitles={srt_esc}",
    ]
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_track),
        "-i", str(audio),
        "-filter_complex", f"[0:v]{','.join(vf)}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        # Memory-efficient encoding (matters on GH Actions 7GB runners and
        # capped containers): minimal lookahead, single thread.
        "-x264-params", "rc-lookahead=1:sync-lookahead=0:frame-threads=1",
        "-threads", "1",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        "-shortest",
        str(out_mp4),
    ]
    _run(cmd)


def build(sections: list[dict], audio: str | Path, full_script: str,
          content_type: str, out_mp4: str | Path,
          workdir: str | Path | None = None) -> Path:
    """Assemble the final MP4 for a video.

    sections: [{"heading", "text"}, ...] — one per script section.
    audio: path to the voiceover WAV.
    full_script: the full spoken text (for subtitles).
    content_type: "Short" | "Long".
    """
    out_mp4 = Path(out_mp4)
    workdir = Path(workdir) if workdir else out_mp4.parent
    workdir.mkdir(parents=True, exist_ok=True)

    total_duration = _audio_duration(audio)
    logger.info("Building video: sections=%d duration=%.1fs type=%s",
                len(sections), total_duration, content_type)

    video_track = _build_video_track(sections, total_duration, content_type, workdir)
    srt = _build_subtitles(Path(audio), full_script, total_duration, workdir)
    _final_mux(video_track, Path(audio), srt, total_duration, content_type, out_mp4)
    logger.info("Video written: %s", out_mp4)
    return out_mp4


def _audio_duration(audio: str | Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])
