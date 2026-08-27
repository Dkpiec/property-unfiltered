"""Topic generation for Property Unfiltered.

Flow:
  1. Load config + the topics prompt.
  2. (Best-effort) enrich with recent NCR real-estate headlines.
  3. Ask the LLM for 10-15 candidate topics (strict JSON).
  4. Normalize + validate candidates.
  5. Rank by Delhi-NCR keyword relevance and select the top 5,
     guaranteeing a Short/Long mix.
  6. Write output/pending_topics.json for the human approval gate.

Run as:  python src/topic_generator.py     (or  python -m src.topic_generator)
"""
from __future__ import annotations

import pathlib
import sys

# Allow `python src/topic_generator.py` to import the src package.
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import llm_client as llm  # noqa: E402
from src import research, utils  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def normalize_candidates(data) -> list[dict]:
    """Extract + validate a candidate list from the LLM JSON response."""
    if not isinstance(data, dict):
        return []
    raw = data.get("candidates", [])
    if not isinstance(raw, list):
        return []
    candidates = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        ctype = str(item.get("type", "")).strip().capitalize()
        if not title:
            continue
        if ctype not in ("Short", "Long"):
            continue
        keywords = item.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        candidates.append({
            "title": title,
            "type": ctype,
            "rationale": str(item.get("rationale", "")).strip(),
            "keywords": [str(k) for k in keywords],
        })
    return candidates


def score_topic(candidate: dict, keywords: list[dict]) -> float:
    """Relevance score = sum of weights of keywords found in title+tags."""
    text = (candidate.get("title", "") + " " + " ".join(candidate.get("keywords", []))).lower()
    score = 0.0
    for entry in keywords:
        kw = str(entry["kw"]).lower()
        if kw in text:
            score += float(entry.get("weight", 1.0))
    return score


def select_top(candidates: list[dict], settings: dict) -> list[dict]:
    """Rank candidates and pick the top N with a guaranteed Short/Long mix."""
    topics_cfg = settings["topics"]
    final = int(topics_cfg["final_count"])
    min_shorts = int(topics_cfg.get("min_shorts", 1))
    min_long = int(topics_cfg.get("min_long", 1))

    shorts = sorted([c for c in candidates if c["type"] == "Short"],
                    key=lambda c: c["score"], reverse=True)
    longs = sorted([c for c in candidates if c["type"] == "Long"],
                   key=lambda c: c["score"], reverse=True)

    chosen: list[dict] = []
    chosen += shorts[:min_shorts]
    chosen += longs[:min_long]

    chosen_ids = {id(c) for c in chosen}
    remaining = [c for c in candidates if id(c) not in chosen_ids]
    remaining.sort(key=lambda c: c["score"], reverse=True)
    chosen += remaining[: max(0, final - len(chosen))]
    return chosen[:final]


def build_context(settings: dict) -> str:
    """Prepend optional research headlines as context for the LLM."""
    ctx = research.enrich("Delhi NCR real estate")
    headlines = ctx.get("news", [])
    if not headlines:
        return ""
    lines = "\n".join(f"- {h.get('title')}" for h in headlines[:5])
    return ("RECENT NCR REAL-ESTATE NEWS (use as fresh signal; do not invent "
            "different figures):\n" + lines + "\n\n")


def main() -> int:
    logger = utils.setup_logging("topic_generator")
    try:
        settings = utils.load_config("config/settings.yaml")
        prompt_template = utils.load_prompt("config/prompts/topics_prompt.txt")
        keywords = settings["topics"]["keywords"]

        prompt = build_context(settings) + prompt_template
        logger.info("Calling LLM for candidate topics...")
        data, _raw = llm.generate("topics", prompt)

        candidates = normalize_candidates(data)
        if len(candidates) < settings["topics"]["final_count"]:
            raise RuntimeError(
                f"Only {len(candidates)} valid candidates; need "
                f"{settings['topics']['final_count']}"
            )

        for c in candidates:
            c["score"] = round(score_topic(c, keywords), 2)

        selected = select_top(candidates, settings)
        manifest = {
            "generated_at": utils.utc_now_iso(),
            "count": len(selected),
            "topics": [
                {
                    "id": i,
                    "title": t["title"],
                    "type": t["type"],
                    "rationale": t["rationale"],
                    "keywords": t.get("keywords", []),
                    "score": t.get("score", 0),
                }
                for i, t in enumerate(selected, start=1)
            ],
        }
        out = REPO_ROOT / settings["paths"]["output"] / "pending_topics.json"
        utils.write_manifest(out, manifest)
        logger.info("Wrote %d topics to %s", len(selected), out)
        for t in manifest["topics"]:
            logger.info("  %d. [%s] %s (score %s)", t["id"], t["type"], t["title"], t["score"])
        return 0
    except Exception as exc:  # noqa: BLE001 - entry point logs + exits non-zero
        logger.error("topic_generator failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
