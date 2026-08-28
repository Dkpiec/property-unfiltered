#!/usr/bin/env python3
"""Gate-3 real-footage video generator for approved content packages.

Reads output/pending_content_review.json (Gate-2 approved content), and for
each approved content id:
  1. synthesises per-section voiceover via edge-tts (en-IN-PrabhatNeural),
  2. fetches REAL video clips per section from Pixabay (PIXABAY_API_KEY):
       - intro/hook section -> aerial / drone city footage,
       - final/CTA section  -> map / navigation footage,
       - middle sections    -> location-keyword footage (Gurgaon/Noida/...),
     with a gradient title-card fallback when a section yields no clips,
  3. builds a uniform 1920x1080@30fps (Long) / 1080x1920@30fps (Short) video
     track from the clips,
  4. generates approximate subtitles from the script,
  5. muxes video + audio + burned subtitles into a YouTube-ready MP4,
  6. writes output/pending_video_review.json for the Gate-3 approval gate.

All paths are repo-relative so it runs identically on a GitHub Actions runner
and locally. Free/local tooling only (Pixabay free tier + edge-tts + ffmpeg).

Usage:
  python src/generate_pixabay_video.py --contents "1" --topics-run-id 12345
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any

# Allow `python src/generate_pixabay_video.py` to import the src package.
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import pixabay
from src import utils

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FPS = 30
DIMENSIONS = {"Short": (1080, 1920), "Long": (1920, 1080)}
DEFAULT_VOICE = "en-IN-PrabhatNeural"

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _find_font() -> str | None:
    for p in _FONT_CANDIDATES:
        if pathlib.Path(p).exists():
            return p
    return None


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def _audio_duration(audio: pathlib.Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


# ── Voiceover (edge-tts, free) ─────────────────────────────────────────
def synthesize_voiceover(sections: list[dict], out_wav: pathlib.Path,
                         voice: str) -> float:
    """Synthesize per-section speech and concatenate into one WAV."""
    try:
        import edge_tts
        import asyncio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"edge-tts not installed: {exc}") from exc

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    mp3s: list[pathlib.Path] = []

    async def synth(text: str, idx: int) -> pathlib.Path:
        chunk = out_wav.parent / f"_vo_chunk_{idx}.mp3"
        comm = edge_tts.Communicate(text, voice, rate="+0%")
        await comm.save(str(chunk))
        return chunk

    async def go() -> None:
        for i, s in enumerate(sections):
            text = str(s.get("text", "")).strip()
            if not text:
                continue
            print(f"  TTS section {i+1} ({len(text)} chars) ...")
            mp3s.append(await synth(text, i))
            time.sleep(0.3)

    asyncio.run(go())
    if not mp3s:
        raise RuntimeError("No sections produced audio")

    concat = out_wav.parent / "_vo_concat.txt"
    concat.write_text("\n".join(f"file '{m.resolve()}'" for m in mp3s) + "\n",
                      encoding="utf-8")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(out_wav),
    ])
    for m in mp3s:
        m.unlink(missing_ok=True)
    concat.unlink(missing_ok=True)
    return _audio_duration(out_wav)


# ── Pixabay clips ──────────────────────────────────────────────────────
def _section_kind(section: dict, index: int, total: int) -> str:
    """Classify a section: aerial (intro), map (outro), or location (middle).

    Overridable via an explicit 'segment' hint in the section dict.
    """
    hint = str(section.get("segment", "")).strip().lower()
    if hint in ("aerial", "map", "location"):
        return hint
    if index == 0:
        return "aerial"
    if index == total - 1:
        return "map"
    return "location"


def _queries_for_kind(kind: str, section: dict) -> list[str]:
    if kind == "aerial":
        return pixabay.LOCATION_KEYWORDS["aerial"][:3]
    if kind == "map":
        return pixabay.LOCATION_KEYWORDS["map"][:3]
    return pixabay.LOCATION_KEYWORDS.get("gurgaon", [])  # replaced below


def _location_queries(section: dict) -> list[str]:
    """Return Pixabay search queries for a location section's text."""
    client_hints = pixabay.LOCATION_KEYWORDS
    text = str(section.get("text", "")).lower() + " " + \
           str(section.get("heading", "")).lower()
    for loc_key, queries in client_hints.items():
        if loc_key in ("aerial", "aerial_city", "map"):
            continue
        if loc_key in text:
            return queries[:3]
    return ["city skyline", "apartment building", "urban construction"]


def fetch_clip(client: pixabay.PixabayClient, queries: list[str],
               content_type: str, workdir: pathlib.Path,
               index: int) -> pathlib.Path | None:
    """Download the first valid clip for a query list; return its path."""
    orientation = "horizontal"
    min_w, min_h = 1920, 1080
    if content_type == "Short":
        orientation = "vertical"
        min_w, min_h = 720, 1280
    for query in queries:
        clips = client.search(query, per_page=4, orientation=orientation,
                              min_width=min_w, min_height=min_h)
        for clip in clips:
            out = workdir / f"raw_{index:03d}.mp4"
            print(f"  📥 [{query}] -> {out.name} ({clip.width}x{clip.height})")
            if client.download(clip.url, out):
                return out
            time.sleep(0.3)
        time.sleep(0.3)
    return None


# ── Video track ────────────────────────────────────────────────────────
def _image_segment(image: pathlib.Path, duration: float, content_type: str,
                   workdir: pathlib.Path, out_path: pathlib.Path) -> None:
    """Render a still image (e.g. a public report page) to a uniform video
    segment: blurred backdrop + centered page + slow Ken Burns zoom.

    Keeps the whole page readable (contain fit) while adding subtle motion.
    """
    w, h = DIMENSIONS[content_type]
    frames = max(int(duration * FPS), FPS)

    # Step 1: build a single composited frame (blurred bg + centered page).
    comp = workdir / f"_comp_{out_path.stem}.png"
    _run([
        "ffmpeg", "-y", "-i", str(image),
        "-filter_complex",
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},boxblur=30:5,eq=brightness=-0.08[bgv];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgv];"
        f"[bgv][fgv]overlay=(W-w)/2:(H-h)/2[v]",
        "-map", "[v]", "-frames:v", "1", str(comp),
    ])

    # Step 2: slow zoom on the composite for the section duration.
    try:
        _run([
            "ffmpeg", "-y", "-i", str(comp),
            "-vf", f"zoompan=z='min(zoom+0.0006,1.15)':d={frames}:"
                   f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                   f"s={w}x{h}:fps={FPS}",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_path),
        ])
    finally:
        comp.unlink(missing_ok=True)


def _title_card_fallback(section: dict, index: int, duration: float,
                         content_type: str, workdir: pathlib.Path,
                         out_path: pathlib.Path) -> None:
    """Gradient card w/ heading text, encoded to uniform specs."""
    w, h = DIMENSIONS[content_type]
    font = _find_font()
    heading = str(section.get("heading") or f"Section {index+1}")
    escaped = heading.replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
    vf = ["drawbox=x=0:y=ih*0.40:w=iw:h=ih*0.20:color=black@0.40:t=fill"]
    if font and heading:
        vf.append(f"drawtext=fontfile={font}:text='{escaped}':"
                  f"fontsize={int(h*0.05)}:fontcolor=white:"
                  f"x=(w-text_w)/2:y=(h-text_h)/2")
    frames = max(int(duration * FPS), FPS)
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"gradients=s={w}x{h}:c0=0x0f2027:c1=0x203a43:c2=0x2c5364:n=3",
        "-vf", ",".join(vf),
        "-frames:v", "1", "-c:v", "png", f"{out_path}.png",
    ])
    _run([
        "ffmpeg", "-y",
        "-i", f"{out_path}.png",
        "-vf", f"scale={w}:{h},zoompan=z='min(zoom+0.0008,1.25)':d={frames}:"
               f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out_path),
    ])
    pathlib.Path(f"{out_path}.png").unlink(missing_ok=True)


def _normalize_clip(raw: pathlib.Path, duration: float, content_type: str,
                    out_path: pathlib.Path) -> None:
    """Re-encode a downloaded clip to uniform dims @30fps, trimmed length."""
    w, h = DIMENSIONS[content_type]
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},fps={FPS},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y",
        "-i", str(raw),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-an", str(out_path),
    ])


def _word_durations(sections: list[dict], total_duration: float) -> list[float]:
    words = [len(str(s.get("text", "")).split()) for s in sections]
    total = max(sum(words), 1)
    durs = [w / total * total_duration for w in words]
    scale = total_duration / max(sum(durs), 1e-9)
    return [d * scale for d in durs]


def build_video_track(sections: list[dict], total_duration: float,
                      content_type: str, workdir: pathlib.Path,
                      client: pixabay.PixabayClient) -> pathlib.Path:
    workdir.mkdir(parents=True, exist_ok=True)
    durations = _word_durations(sections, total_duration)
    segs: list[pathlib.Path] = []

    for i, (section, dur) in enumerate(zip(sections, durations)):
        seg = workdir / f"seg_{i:03d}.mp4"
        kind = _section_kind(section, i, len(sections))
        img = section.get("image")
        if img:
            img_path = (REPO_ROOT / img) if not pathlib.Path(img).is_absolute() else pathlib.Path(img)
            if img_path.exists():
                print(f"  📊 Section {i+1}: report image segment -> {img_path}")
                try:
                    _image_segment(img_path, dur, content_type, workdir, seg)
                    segs.append(seg)
                    continue
                except Exception as exc:  # noqa: BLE001
                    print(f"  ⚠️ Image segment {i} failed: {exc}; falling back to clip")
            else:
                print(f"  ⚠️ Section {i+1}: image missing {img_path} — falling back to clip")
        queries = (_location_queries(section) if kind == "location"
                   else _queries_for_kind(kind, section))
        print(f"  🎬 Section {i+1}: kind={kind} queries={queries}")
        raw = fetch_clip(client, queries, content_type, workdir, i)
        if raw is not None:
            try:
                _normalize_clip(raw, dur, content_type, seg)
                raw.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠️ Clip {i} normalize failed: {exc}; fallback card")
                raw.unlink(missing_ok=True)
                _title_card_fallback(section, i, dur, content_type, workdir, seg)
        else:
            print(f"  🃏 Section {i+1}: no clip — gradient card")
            _title_card_fallback(section, i, dur, content_type, workdir, seg)
        segs.append(seg)

    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{s.resolve()}'\n" for s in segs),
                           encoding="utf-8")
    track = workdir / "video_track.mp4"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(track),
    ])
    return track


# ── Subtitles (approx from script, no whisper needed on runners) ───────
def _format_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_approx_srt(full_script: str, total_duration: float,
                    out_path: pathlib.Path) -> None:
    words = full_script.split()
    n = max(len(words), 1)
    per_word = total_duration / n
    lines: list[str] = []
    i = 0
    idx = 1
    while i < n:
        chunk = words[i:i + 8]
        start = i * per_word
        end = (i + len(chunk)) * per_word
        lines += [str(idx), f"{_format_ts(start)} --> {_format_ts(end)}",
                  " ".join(chunk), ""]
        i += 8
        idx += 1
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ── Final mux (memory-safe for GH runners) ─────────────────────────────
def final_mux(video_track: pathlib.Path, audio: pathlib.Path,
              srt: pathlib.Path, total_duration: float, content_type: str,
              out_mp4: pathlib.Path) -> None:
    """Mux video + audio into the final MP4.

    Memory-safe two-pass strategy (no libass subtitle burn, which OOMs on
    constrained runners): first re-encode the video track alone applying
    fades, then stream-copy it together with audio + soft subtitles.
    """
    workdir = video_track.parent
    faded = workdir / "video_faded.mp4"
    vf = [
        "fade=t=in:st=0:d=0.5",
        f"fade=t=out:st={max(total_duration-0.6, 0):.3f}:d=0.6",
    ]
    _run([
        "ffmpeg", "-y",
        "-i", str(video_track),
        "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-x264-params", "rc-lookahead=1:sync-lookahead=0:frame-threads=1",
        "-threads", "1",
        str(faded),
    ], timeout=1500)

    # Mux video (stream-copy) + audio + soft subtitles (mov_text).
    _run([
        "ffmpeg", "-y",
        "-i", str(faded),
        "-i", str(audio),
        "-i", str(srt),
        "-map", "0:v", "-map", "1:a", "-map", "2",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        "-movflags", "+faststart",
        "-shortest",
        str(out_mp4),
    ], timeout=600)
    faded.unlink(missing_ok=True)


# ── Orchestration ──────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate-3 Pixabay video generator")
    parser.add_argument("--contents", required=True,
                        help="Comma-separated content indices from "
                             "pending_content_review.json, e.g. '1'")
    parser.add_argument("--voice", default=DEFAULT_VOICE,
                        help="edge-tts voice")
    args = parser.parse_args(argv)

    out_dir = REPO_ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "pending_content_review.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing {manifest_path} — run generate_content first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contents = manifest.get("contents", [])

    indices = [int(x) for x in args.contents.split(",") if x.strip()]
    picked = [c for c in contents if c["topic"]["id"] in indices] or \
             [contents[i - 1] for i in indices if 0 < i <= len(contents)]
    if not picked:
        raise RuntimeError(f"No content matched {indices}")

    api_key = utils.getenv("PIXABAY_API_KEY", "")
    client = pixabay.PixabayClient(api_key)
    if not api_key:
        print("⚠️  PIXABAY_API_KEY not set — gradient cards only")

    reviews = []
    for content in picked:
        cid = content["topic"]["id"]
        content_type = content.get("content_type", "Long")
        sections = content["sections"]
        full_script = content.get("full_script") or " ".join(
            str(s.get("text", "")) for s in sections)

        workdir = out_dir / f"work_pixabay_{cid}"
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)

        # 1. Voiceover
        audio = out_dir / f"vo_{cid}.wav"
        duration = synthesize_voiceover(sections, audio, args.voice)
        print(f"🎙️ Voiceover ready: {duration:.1f}s -> {audio}")

        # 2-3. Clips + track
        track = build_video_track(sections, duration, content_type,
                                  workdir, client)
        print(f"🎞️ Video track: {track}")

        # 4. Subtitles
        srt = workdir / "subtitles.srt"
        make_approx_srt(full_script, duration, srt)

        # 5. Mux
        video_name = (f"video_{cid}_"
                      f"{'short' if content_type == 'Short' else 'long'}.mp4")
        out_mp4 = out_dir / video_name
        final_mux(track, audio, srt, duration, content_type, out_mp4)
        print(f"✅ Video: {out_mp4} ({out_mp4.stat().st_size/1e6:.1f} MB, "
              f"{duration:.1f}s)")

        # 6. Review manifest
        reviews.append({
            "video_path": str(out_mp4),
            "script": full_script,
            "sections": sections,
            "titles": content.get("titles", []),
            "description": content.get("description", ""),
            "tags": content.get("tags", []),
            "thumbnail_ideas": content.get("thumbnail_ideas", []),
            "content_type": content_type,
            "topic": content.get("topic", {"id": cid}),
            "duration_sec": round(duration, 1),
            "generated_at": utils.utc_now_iso(),
        })

    review_path = out_dir / "pending_video_review.json"
    review_path.write_text(json.dumps({
        "generated_at": utils.utc_now_iso(),
        "count": len(reviews),
        "videos": reviews,
    }, indent=2), encoding="utf-8")
    print(f"📄 Review manifest: {review_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
