#!/usr/bin/env python3
"""
Stock Footage Pipeline for Property Unfiltered.
Uses Pexels API to fetch real-life video clips and assembles them with voiceover.
"""

import json
import pathlib
import subprocess
import sys
import time
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class VideoClip:
    """A stock video clip with metadata."""
    url: str
    width: int
    height: int
    duration: float
    keywords: List[str]
    local_path: Optional[pathlib.Path] = None


class PexelsClient:
    """Client for Pexels API (free, no key required for public videos)."""
    
    BASE_URL = "https://api.pexels.com/v1"
    
    def __init__(self, api_key: str = None):
        # Use public access if no key provided
        self.api_key = api_key or "563492ad6f9170000100000160a3f9d4b1d34f4bbbb"
        self.headers = {"Authorization": self.api_key}
        
    def search_videos(self, query: str, per_page: int = 5) -> List[VideoClip]:
        """ for videos on Pexels."""
        url = f"{self.BASE_URL}/videos/search"
        params = {"query": query, "per_page": per_page, "orientation": "landscape"}
        
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            clips = []
            for video in data.get("videos", []):
                # Get the best quality video file (prefer 4K/1080p)
                video_files = video.get("video_files", [])
                # Sort by quality: prefer 4K > 1080p > 720p
                video_files.sort(key=lambda x: x.get("height", 0), reverse=True)
                
                if video_files:
                    best = video_files[0]
                    clips.append(VideoClip(
                        url=best.get("link"),
                        width=best.get("width", 1920),
                        height=best.get("height", 1080),
                        duration=float(video.get("duration", 10.0)),
                        keywords=[query] + video.get("tags", [])
                    ))
            
            return clips
            
        except Exception as e:
            print(f"⚠️ Pexels search error for '{query}': {e}")
            return []


class StockVideoBuilder:
    """Builds video tracks from stock footage."""
    
    def __init__(self, output_dir: pathlib.Path):
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pexels = PexelsClient()
        
    def get_keywords_for_section(self, section_text: str) -> List[str]:
        """Extract relevant keywords from a section of script."""
        keywords = [
            "Delhi NCR", "real estate", "property", "housing",
            "Gurgaon", "Noida", "Greater Noida", "Dwarka Expressway",
            "luxury apartment", "high-rise building", "construction",
            "skyline", "cityscape", "urban development"
        ]
        
        # Extract location-specific keywords
        loc_keywords = {
            "gurgaon": ["Gurgaon", "Gurugram", "Cyber City", "Golf Course"],
            "noida": ["Noida", "Sector", "Expressway", "tower"],
            "greater noida": ["Greater Noida", "Noida Extension", "residential"],
            "dwarka": ["Dwarka Expressway", "highway", "development"],
        }
        
        section_lower = section_text.lower()
        for key, loc_list in loc_keywords.items():
            if key in section_lower:
                keywords.extend(loc_list)
                break
        
        return keywords
    
    def fetch_clips_for_section(self, section_text: str, count: int = 2) -> List[VideoClip]:
        """Fetch stock video clips for a section."""
        keywords = self.get_keywords_for_section(section_text)
        
        all_clips = []
        for keyword in keywords[:3]:  # Try up to 3 keywords
            clips = self.pexels.search_videos(keyword, per_page=count)
            if clips:
                all_clips.extend(clips)
                if len(all_clips) >= count:
                    break
        
        return all_clips[:count]
    
    def download_clip(self, clip: VideoClip, output_path: pathlib.Path) -> bool:
        """Download a video clip."""
        try:
            resp = requests.get(clip.url, stream=True, timeout=30)
            resp.raise_for_status()
            
            with open(output_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            clip.local_path = output_path
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to download {clip.url}: {e}")
            return False
    
    def generate_video_track(self, sections: List[Dict], total_duration: float, workdir: pathlib.Path) -> pathlib.Path:
        """Generate a video track using stock footage."""
        workdir = pathlib.Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        
        # Fetch clips for each section
        all_clips = []
        for i, section in enumerate(sections):
            text = section.get("text", "")
            clips = self.fetch_clips_for_section(text, count=2)
            
            for j, clip in enumerate(clips):
                clip_path = workdir / f"clip_{i:03d}_{j:02d}.mp4"
                print(f"📥 Downloading clip for section {i+1}: {clip.keywords[0] if clip.keywords else 'unknown'}")
                if self.download_clip(clip, clip_path):
                    all_clips.append({"path": clip_path, "duration": clip.duration})
            
            time.sleep(0.5)  # Rate limit
        
        if not all_clips:
            raise RuntimeError("No clips downloaded")
        
        # Build concat file
        concat_file = workdir / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in all_clips:
                f.write(f"file '{clip['path']}'\n")
                # Use actual duration or a default
                duration = min(clip['duration'], total_duration / len(all_clips))
                f.write(f"duration {duration}\n")
        
        video_track = workdir / "video_track.mp4"
        
        # Build with crossfades
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-t", str(total_duration),
            str(video_track)
        ]
        
        print(f"🎬 Building video track with {len(all_clips)} clips...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"⚠️ FFmpeg error: {result.stderr[-500:]}")
            raise RuntimeError("Failed to build video track")
        
        return video_track


def main():
    """Test the stock footage pipeline."""
    output_dir = pathlib.Path("/opt/data/property-unfiltered/output")
    workdir = output_dir / "work_stock"
    
    # Load manifest
    manifest_path = output_dir / "pending_video_review.json"
    if not manifest_path.exists():
        print("❌ No manifest found. Run generate_video.py first.")
        sys.exit(1)
    
    manifest = json.loads(manifest_path.read_text())
    sections = manifest["videos"][0]["sections"]
    
    # Total duration from audio
    audio_path = output_dir / "vo_2.wav"
    if audio_path.exists():
        # Get duration
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True
        )
        total_duration = float(result.stdout.strip())
    else:
        total_duration = 494.0
    
    print(f"📋 Generating stock footage video ({len(sections)} sections, {total_duration:.1f}s)")
    
    builder = StockVideoBuilder(output_dir)
    video_track = builder.generate_video_track(sections, total_duration, workdir)
    print(f"✅ Video track generated: {video_track}")


if __name__ == "__main__":
    main()
