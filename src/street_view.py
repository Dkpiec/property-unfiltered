#!/usr/bin/env python3
"""
Street View video pipeline for Property Unfiltered.
Fetches Google Maps Street View imagery for real-estate locations and generates video tracks.
"""

import json
import time
import subprocess
import pathlib
import sys
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Try to import Selenium (will install if not available)
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException
except ImportError:
    print("Selenium not installed. Run: pip install selenium webdriver-manager")
    sys.exit(1)

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service


@dataclass
class Location:
    """A real-estate location with Street View coordinates."""
    name: str
    lat: float
    lng: float
    heading: int = 0  # compass direction (0=N, 90=E, 180=S, 270=W)
    pitch: int = 0    # -90 to 90 (looking up/down)
    zoom: int = 1     # 0-3 (0=closest, 3=farthest)


class StreetViewFetcher:
    """Fetches Street View imagery using Selenium (no API key required)."""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        
    def start(self):
        """Initialize the Chrome driver."""
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        
    def stop(self):
        """Close the driver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            
    def fetch_static_image(self, location: Location, output_path: str) -> bool:
        """
        Fetch a Street View static image using Google Maps URL scheme.
        Uses a hidden technique: loads the map and takes a screenshot.
        """
        try:
            # For production, we'll use the screenshot approach
            # Navigate to Google Maps Street View directly
            map_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={location.lat},{location.lng}&heading={location.heading}&pitch={location.pitch}"
            
            self.driver.get(map_url)
            time.sleep(3)  # Wait for panorama to load
            
            # Take screenshot
            self.driver.save_screenshot(output_path)
            return True
            
        except Exception as e:
            print(f"Error fetching Street View for {location.name}: {e}")
            return False


class StreetViewVideoBuilder:
    """Builds video tracks from Street View images."""
    
    def __init__(self, output_dir: pathlib.Path):
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def get_location_for_section(self, section_text: str) -> Optional[Location]:
        """Extract location from a section of script."""
        # Keywords to location mapping
        keywords = {
            "gurgaon": Location("Gurgaon", 28.4595, 77.0266, heading=90, pitch=0),
            "gurugram": Location("Gurugram", 28.4595, 77.0266, heading=90, pitch=0),
            "noida": Location("Noida", 28.5355, 77.3910, heading=0, pitch=0),
            "greater noida": Location("Greater Noida", 28.4744, 77.5040, heading=0, pitch=0),
            "dwarka expressway": Location("Dwarka Expressway", 28.5100, 77.0450, heading=270, pitch=0),
            "sector 150": Location("Noida Sector 150", 28.5580, 77.4100, heading=0, pitch=0),
            "golf course": Location("Golf Course Extension", 28.4600, 77.0700, heading=90, pitch=0),
            "southern peripheral": Location("Southern Peripheral Road", 28.4200, 77.0850, heading=180, pitch=0),
            "greater noida west": Location("Greater Noida West", 28.6500, 77.5100, heading=0, pitch=0),
            "new gurgaon": Location("New Gurgaon", 28.4200, 77.0300, heading=180, pitch=0),
        }
        
        section_lower = section_text.lower()
        for key, loc in keywords.items():
            if key in section_lower:
                return loc
        
        # Default to Gurgaon
        return Location("Gurgaon", 28.4595, 77.0266, heading=90, pitch=0)
    
    def generate_video_track(self, sections: List[Dict], total_duration: float, workdir: pathlib.Path) -> pathlib.Path:
        """
        Generate a video track using Street View imagery for each section.
        Each section gets a Street View panorama with Ken Burns-style pan/zoom.
        """
        workdir = pathlib.Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        
        # Fetch Street View images
        fetcher = StreetViewFetcher(headless=True)
        fetcher.start()
        
        clips = []
        for i, section in enumerate(sections):
            text = section.get("text", "")
            loc = self.get_location_for_section(text)
            
            # Fetch image
            img_path = workdir / f"street_{i:03d}.png"
            print(f"Fetching Street View for section {i+1}: {loc.name}")
            
            # Try different headings to get a good view
            headings = [loc.heading, loc.heading + 45, loc.heading - 45]
            success = False
            for h in headings:
                loc.heading = h % 360
                if fetcher.fetch_static_image(loc, str(img_path)):
                    success = True
                    break
            
            if not success:
                print(f"  ⚠️ Failed to fetch Street View for {loc.name}, using fallback")
                # Generate a fallback gradient image
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"color=c=0x2d4a6b:s=1920x1080:d=1",
                    "-frames:v", "1",
                    str(img_path)
                ], capture_output=True)
            
            clips.append({"path": img_path, "location": loc})
        
        fetcher.stop()
        
        # Build video track by concatenating images with Ken Burns effects
        # Build the ffmpeg command with simple concatenation
        concat_file = workdir / "concat.txt"
        with open(concat_file, "w") as f:
            for i, clip in enumerate(clips):
                # Each section gets equal time share
                duration_per_section = total_duration / len(clips)
                f.write(f"file '{clip['path']}'\n")
                f.write(f"duration {duration_per_section}\n")
        
        video_track = workdir / "video_track.mp4"
        
        # Build with Ken Burns effect using zoompan
        # Use a simpler approach: loop each image with zoompan
        filter_parts = []
        for i, clip in enumerate(clips):
            duration_per_section = total_duration / len(clips)
            filter_parts.append(
                f"[{i}:v]scale=1920*1.2:1080*1.2,zoompan=z='1+0.2*on/({duration_per_section}*{i+1})':d={duration_per_section}:fps=30,format=yuv420p[v{i}]"
            )
        
        # Concatenate all outputs
        concat_inputs = "".join([f"[v{i}]" for i in range(len(clips))])
        filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(clips)}:v=1:a=0[outv]"
        
        cmd = [
            "ffmpeg", "-y",
        ]
        
        # Add inputs
        for clip in clips:
            cmd.extend(["-loop", "1", "-i", str(clip["path"])])
        
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-t", str(total_duration),
            str(video_track)
        ])
        
        print(f"Running ffmpeg to generate video track...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"Error: {result.stderr[-500:]}")
            raise RuntimeError("Failed to generate video track")
        
        return video_track


def main():
    """Test the Street View pipeline."""
    output_dir = pathlib.Path("/opt/data/property-unfiltered/output")
    workdir = output_dir / "work_street"
    
    # Load manifest
    manifest_path = output_dir / "pending_video_review.json"
    if not manifest_path.exists():
        print("No manifest found. Run generate_video.py first.")
        sys.exit(1)
    
    manifest = json.loads(manifest_path.read_text())
    sections = manifest["videos"][0]["sections"]
    
    builder = StreetViewVideoBuilder(output_dir)
    video_track = builder.generate_video_track(sections, 30.0, workdir)
    print(f"Video track generated: {video_track}")


if __name__ == "__main__":
    main()
