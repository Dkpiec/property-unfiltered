"""End-to-end video generation for approved topics.

Reads output/pending_topics.json, takes the approved topic indices, and for each:
  1. writes the script + metadata (scriptwriter)
  2. synthesises the voiceover (voiceover)
  3. assembles the MP4 (video_builder)
  4. appends a review record to output/pending_video_review.json

Does NOT upload anywhere. The review manifest is the handoff to the human
approval gate (Gate 2).

Usage:
  python src/generate_video.py --topics "1,3"      # topic ids 1 and 3
  python src/generate_video.py --topics "2" --dry-run
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import scriptwriter, utils, video_builder, voiceover  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_topics() -> list[dict]:
    path = REPO_ROOT / "output" / "pending_topics.json"
    if not path.exists():
        raise RuntimeError(f"Missing {path} — run topic generation first")
    return json.loads(path.read_text(encoding="utf-8"))["topics"]


def process_topic(topic: dict, settings: dict, out_dir: pathlib.Path) -> dict:
    pkg = scriptwriter.write_full_package(topic, settings)
    script, meta = pkg["script"], pkg["metadata"]

    # Flatten script sections for TTS + backgrounds
    sections = [
        {"heading": s.get("heading", f"Section {i+1}"), "text": s.get("text", "")}
        for i, s in enumerate(script.get("sections", []) or [])
    ]
    if not sections:
        sections = [{"heading": "Intro", "text": script["full_script"]}]

    content_type = topic["type"]
    audio, duration = voiceover.synthesize(
        [s["text"] for s in sections], out_dir / f"vo_{topic['id']}.wav"
    )

    video_name = f"video_{topic['id']}_{'short' if content_type == 'Short' else 'long'}.mp4"
    video = video_builder.build(
        sections, audio, script["full_script"], content_type,
        out_dir / video_name, workdir=out_dir / f"work_{topic['id']}",
    )

    return {
        "video_path": str(video),
        "script": script["full_script"],
        "sections": sections,
        "titles": meta["titles"],
        "description": meta["description"],
        "tags": meta["tags"],
        "thumbnail_ideas": meta["thumbnail_ideas"],
        "content_type": content_type,
        "topic": {"id": topic["id"], "title": topic["title"]},
        "duration_sec": round(duration, 1),
        "timestamp": utils.utc_now_iso(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate videos for approved topics")
    parser.add_argument("--topics", required=True,
                        help="Comma-separated topic ids from pending_topics.json, e.g. '1,3'")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use placeholder TTS audio (no real synthesis)")
    args = parser.parse_args(argv)

    logger = utils.setup_logging("generate_video")
    try:
        if args.dry_run:
            import os
            os.environ["TTS_DRY_RUN"] = "1"

        settings = utils.load_config("config/settings.yaml")
        out_dir = REPO_ROOT / settings["paths"]["output"]
        out_dir.mkdir(parents=True, exist_ok=True)

        ids = [int(x) for x in args.topics.split(",") if x.strip()]
        topics = [t for t in load_topics() if t["id"] in ids]
        if not topics:
            raise RuntimeError(f"No topics matched ids {ids}")

        reviews = [process_topic(t, settings, out_dir) for t in topics]

        manifest = {"generated_at": utils.utc_now_iso(),
                    "count": len(reviews), "videos": reviews}
        out = out_dir / "pending_video_review.json"
        utils.write_manifest(out, manifest)
        for r in reviews:
            logger.info("Video ready: %s [%s] %.1fs", r["video_path"], r["content_type"], r["duration_sec"])
        return 0
    except Exception as exc:  # noqa: BLE001 - entry point logs + exits non-zero
        logger.error("generate_video failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
