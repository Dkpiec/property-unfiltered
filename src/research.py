"""Best-effort research enrichment for topics and scripts.

Kept deliberately light and NON-FATAL: any failure returns an empty result so
the pipeline never depends on external research services. Currently pulls
recent news headlines (Google News RSS, no API key) to anchor topics/scripts
with real, current Delhi-NCR real-estate signals.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("research")


def fetch_news_headlines(query: str, limit: int = 5) -> list[dict]:
    """Return recent news headlines for `query` via Google News RSS (no key).

    Each item: {"title", "link", "published"}. Returns [] on any failure.
    """
    import requests
    import xml.etree.ElementTree as ET

    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    items: list[dict] = []
    for item in root.iter("item"):
        items.append({
            "title": item.findtext("title"),
            "link": item.findtext("link"),
            "published": item.findtext("pubDate"),
        })
        if len(items) >= limit:
            break
    return items


def enrich(topic: str) -> dict:
    """Gather enrichment context for a topic. Returns dict; {} on failure."""
    try:
        headlines = fetch_news_headlines(f'"{topic}" real estate')
        return {"news": headlines}
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("research.enrich failed for %r: %s", topic, exc)
        return {}
