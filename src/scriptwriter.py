"""Script + metadata writing for approved topics.

For one approved topic, produces:
  - the full voiceover script (sections + hook + CTA + full_script)
  - 5 title options, 1 SEO description, 15 tags, 2-3 thumbnail ideas

All output is LLM-generated (strict JSON) and normalized here so downstream
TTS/video/upload stages never see a malformed shape.
"""
from __future__ import annotations

from src import llm_client as llm  # noqa: F401
from src import utils


def _safe_format(template: str, **values) -> str:
    """Brace-safe template fill (LLM text may contain { } braces)."""
    for key, val in values.items():
        template = template.replace("{" + key + "}", str(val))
    return template


def write_script(topic: dict, settings: dict) -> dict:
    """Generate the voiceover script for a topic (Short or Long)."""
    ctype = topic["type"]
    spec = settings["content"]["shorts"] if ctype == "Short" else settings["content"]["long"]
    duration = (spec["duration_sec"][0] + spec["duration_sec"][1]) // 2
    words = (spec["words"][0] + spec["words"][1]) // 2

    template = utils.load_prompt("config/prompts/script_prompt.txt")
    prompt = _safe_format(
        template,
        title=topic["title"],
        content_type=ctype,
        duration=duration,
        words=words,
    )
    data, _raw = llm.generate("script", prompt)
    if not isinstance(data, dict):
        raise RuntimeError("script LLM response was not an object")
    # Force content type to match the approved topic.
    data["content_type"] = ctype
    return ensure_full_script(data)


def ensure_full_script(data: dict) -> dict:
    """Guarantee a flat `full_script` field for TTS/video stages."""
    if data.get("full_script"):
        return data
    parts = [data.get("hook", "")]
    parts += [s.get("text", "") for s in data.get("sections", []) if isinstance(s, dict)]
    parts.append(data.get("cta", ""))
    data["full_script"] = "\n".join(p for p in parts if str(p).strip())
    return data


def write_metadata(working_title: str, content_type: str, full_script: str) -> dict:
    """Generate titles/description/tags/thumbnail ideas for the video."""
    template = utils.load_prompt("config/prompts/metadata_prompt.txt")
    prompt = _safe_format(
        template,
        working_title=working_title,
        content_type=content_type,
        script=full_script,
    )
    data, _raw = llm.generate("metadata", prompt)
    if not isinstance(data, dict):
        raise RuntimeError("metadata LLM response was not an object")

    titles = [str(t).strip() for t in (data.get("titles") or []) if str(t).strip()]
    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
    thumbs = [str(t).strip() for t in (data.get("thumbnail_ideas") or []) if str(t).strip()]

    # Normalize cardinality (pad with sensible defaults if the model under-delivers)
    titles = (titles + ["", "", "", "", ""])[:5]
    tags = (tags + [f"Delhi NCR real estate", "India real estate",
                    "property investment", "NCR property", "real estate India",
                    "Gurgaon property", "Noida property", "RERA", "flat price",
                    "home buying", "real estate news", "Delhi property",
                    "NCR infrastructure", "first time buyer", "real estate tips"])[:15]
    thumbs = (thumbs + ["No hype", "Real data"])[:3]

    return {
        "titles": titles,
        "description": str(data.get("description", "")).strip(),
        "tags": tags,
        "thumbnail_ideas": thumbs,
    }


def write_full_package(topic: dict, settings: dict) -> dict:
    """Script + metadata for one approved topic."""
    script = write_script(topic, settings)
    meta = write_metadata(
        script.get("working_title", topic["title"]),
        script.get("content_type", topic["type"]),
        script["full_script"],
    )
    return {"script": script, "metadata": meta}
