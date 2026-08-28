"""Pixabay video API client for Property Unfiltered.

Fetches free stock video clips from Pixabay. Requires PIXABAY_API_KEY
environment variable (free to obtain at https://pixabay.com/api/docs/).

Usage:
    client = PixabayClient()
    clips = client.search("Gurgaon skyline", per_page=3)
    client.download(clips[0].url, "/tmp/clip.mp4")
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("pixabay")

PIXABAY_API_URL = "https://pixabay.com/api/videos/"

# Default keywords for each Delhi NCR location — used when no specific
# query matches, or as fallback keywords for aerial/map sections.
LOCATION_KEYWORDS: dict[str, list[str]] = {
    "gurgaon": ["Gurgaon skyline", "Gurugram city", "Golf Course road", "high rise building"],
    "gurugram": ["Gurgaon skyline", "Gurugram city", "high rise building"],
    "noida": ["Noida city", "Noida expressway", "residential tower", "apartment building"],
    "greater noida": ["Greater Noida", "residential township", "new construction"],
    "dwarka": ["Dwarka expressway", "highway traffic", "road construction"],
    "delhi": ["Delhi city skyline", "India Gate", "Delhi NCR", "city landscape"],
    "aerial": ["aerial city view", "drone city", "city skyline drone", "urban aerial"],
    "aerial_city": ["aerial city view", "drone urban", "city skyline drone"],
    "map": ["city map", "navigation map", "aerial view map", "satellite view"],
}


@dataclass
class VideoClip:
    """A stock video clip returned by Pixabay."""
    url: str
    width: int
    height: int
    duration: float
    tags: list[str] = field(default_factory=list)
    local_path: Path | None = None


class PixabayClient:
    """Lightweight client for the Pixabay Video API.

    Requires PIXABAY_API_KEY in the environment.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("PIXABAY_API_KEY") or ""
        if not self.api_key:
            logger.warning("PIXABAY_API_KEY not set — searches will fail")

    def search(self, query: str, per_page: int = 5,
               orientation: str = "horizontal",
               min_width: int = 1920, min_height: int = 1080) -> list[VideoClip]:
        """Search Pixabay for video clips matching a query.

        Returns a list of VideoClip objects sorted by quality (highest res first).
        Empty list on failure.
        """
        params = {
            "key": self.api_key,
            "q": query,
            "per_page": min(per_page, 200),
            "orientation": orientation,
            "safesearch": "true",
        }
        if min_width:
            params["min_width"] = min_width
        if min_height:
            params["min_height"] = min_height

        try:
            resp = requests.get(PIXABAY_API_URL, params=params, timeout=20)
            if resp.status_code == 429:
                logger.warning("Pixabay rate-limited for '%s', retrying...", query)
                time.sleep(5)
                resp = requests.get(PIXABAY_API_URL, params=params, timeout=20)

            if resp.status_code != 200:
                logger.warning("Pixabay HTTP %d for '%s': %s",
                               resp.status_code, query, resp.text[:120])
                return []

            data = resp.json()
            hits = data.get("hits", [])
            clips: list[VideoClip] = []
            for hit in hits:
                videos = hit.get("videos", {})
                # Pick the best quality video file (largest width)
                best = None
                best_width = 0
                for quality_key in ("large", "medium", "small", "tiny"):
                    vid_info = videos.get(quality_key)
                    if vid_info and isinstance(vid_info, dict):
                        w = vid_info.get("width", 0) or 0
                        if w > best_width:
                            best = vid_info
                            best_width = w

                if best is None:
                    continue

                tags_raw = (hit.get("tags") or "").split(",")
                clips.append(VideoClip(
                    url=best.get("url", ""),
                    width=best.get("width", 1920) or 1920,
                    height=best.get("height", 1080) or 1080,
                    duration=float(hit.get("duration", 10) or 10),
                    tags=[t.strip() for t in tags_raw if t.strip()],
                ))

            # Sort by resolution descending
            clips.sort(key=lambda c: c.width * c.height, reverse=True)
            return clips

        except requests.RequestException as exc:
            logger.warning("Pixabay search error for '%s': %s", query, exc)
            return []

    def download(self, url: str, out_path: Path) -> bool:
        """Download a video clip to disk. Returns True on success."""
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            resp = requests.get(url, stream=True, timeout=120)
            resp.raise_for_status()
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
            ok = out_path.stat().st_size > 10_000
            if not ok:
                logger.warning("Downloaded file too small: %s (%d bytes)",
                               out_path, out_path.stat().st_size)
                out_path.unlink(missing_ok=True)
            return ok
        except requests.RequestException as exc:
            logger.warning("Download failed for %s: %s", url, exc)
            out_path.unlink(missing_ok=True)
            return False

    def search_location(self, section_text: str, per_page: int = 3) -> list[VideoClip]:
        """Extract location keywords from section text and search Pixabay.

        Returns clips for the first matching location keyword set.
        """
        text_lower = section_text.lower()
        for loc_key, queries in LOCATION_KEYWORDS.items():
            if loc_key in text_lower:
                for query in queries[:2]:  # Try first 2 queries
                    clips = self.search(query, per_page=per_page)
                    if clips:
                        return clips
                    time.sleep(0.3)
                break
        # Fallback: try generic real-estate terms
        for query in ["city skyline", "apartment building", "urban construction"]:
            clips = self.search(query, per_page=per_page)
            if clips:
                return clips
            time.sleep(0.3)
        return []

    def search_aerial(self, per_page: int = 3) -> list[VideoClip]:
        """Search for aerial/drone city footage."""
        return self.search("aerial city view", per_page=per_page)

    def search_map(self, per_page: int = 3) -> list[VideoClip]:
        """Search for map / navigation style footage."""
        return self.search("city map navigation", per_page=per_page)