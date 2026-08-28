"""Gate-2 content package generation for approved topics.

Reads output/pending_topics.json, takes the approved topic indices, and for each:
  1. writes the full voiceover script (scriptwriter),
  2. writes titles / description / tags / thumbnail ideas (scriptwriter),
  3. appends a content review record to output/pending_content_review.json.

This is Gate 2 of the pipeline: the human approves the CONTENT (script +
metadata) in Telegram BEFORE any video is built. The video generator
(src/generate_pixabay_video.py, Gate 3) consumes this manifest.

No video, no TTS, no network calls beyond the LLM. Nothing is uploaded.

Usage:
  python src/generate_content.py --topics "1,3"      # content for topic ids 1,3
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import scriptwriter, utils  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_topics() -> list[dict]:
    path = REPO_ROOT / "output" / "pending_topics.json"
    if not path.exists():
        raise RuntimeError(f"Missing {path} — run topic generation first")
    return json.loads(path.read_text(encoding="utf-8"))["topics"]


def process_topic(topic: dict, settings: dict) -> dict:
    """Build one Gate-2 content review record for an approved topic."""
    pkg = scriptwriter.write_full_package(topic, settings)
    script, meta = pkg["script"], pkg["metadata"]
    content_type = script.get("content_type", topic["type"])

    sections = [
        {"heading": s.get("heading", f"Section {i+1}"), "text": s.get("text", "")}
        for i, s in enumerate(script.get("sections", []) or [])
    ]
    if not sections:
        sections = [{"heading": "Intro", "text": script["full_script"]}]

    return {
        "topic": {"id": topic["id"], "title": topic["title"], "type": topic["type"]},
        "content_type": content_type,
        "working_title": script.get("working_title", topic["title"]),
        "hook": script.get("hook", ""),
        "sections": sections,
        "cta": script.get("cta", ""),
        "full_script": script["full_script"],
        "titles": meta["titles"],
        "description": meta["description"],
        "tags": meta["tags"],
        "thumbnail_ideas": meta["thumbnail_ideas"],
        "timestamp": utils.utc_now_iso(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate-2 content package generator")
    parser.add_argument("--topics", required=True,
                        help="Comma-separated topic ids from pending_topics.json, e.g. '1,3'")
    args = parser.parse_args(argv)

    logger = utils.setup_logging("generate_content")
    try:
        settings = utils.load_config("config/settings.yaml")
        out_dir = REPO_ROOT / settings["paths"]["output"]
        out_dir.mkdir(parents=True, exist_ok=True)

        ids = [int(x) for x in args.topics.split(",") if x.strip()]
        topics = [t for t in load_topics() if t["id"] in ids]
        if not topics:
            raise RuntimeError(f"No topics matched ids {ids}")

        reviews = [process_topic(t, settings) for t in topics]

        manifest = {"generated_at": utils.utc_now_iso(),
                    "count": len(reviews), "contents": reviews}
        out = out_dir / "pending_content_review.json"
        utils.write_manifest(out, manifest)
        for r in reviews:
            logger.info("Content ready: #%s [%s] %s",
                        r["topic"]["id"], r["content_type"], r["working_title"])
        return 0
    except Exception as exc:  # noqa: BLE001 - entry point logs + exits non-zero
        logger.error("generate_content failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
