#!/usr/bin/env python3
"""Generate a stylized Delhi NCR location map for the video.

Dark-themed schematic map (not to scale) highlighting the key micro-markets
and expressways covered in the story: Delhi, Gurugram, Noida, Greater Noida,
Dwarka Expressway, Golf Course Road, Noida Expressway.
"""
from __future__ import annotations

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "assets" / "maps"
OUT.mkdir(parents=True, exist_ok=True)

BG = "#0f2027"
CARD = "#16282f"
GRID = "#2c4a55"
TXT = "#e8f0f2"
ACCENT = "#e8a33d"
BLUE = "#4da6c8"
GREEN = "#6fbf73"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": BG,
    "savefig.facecolor": BG,
    "text.color": TXT,
    "font.family": "DejaVu Sans",
})

# Approx Delhi NCR coordinates (lon, lat) for schematic layout
LOCATIONS = {
    "Delhi":           (77.21, 28.61),
    "Gurugram":        (77.03, 28.46),
    "Noida":           (77.32, 28.57),
    "Greater Noida":   (77.50, 28.47),
    "Faridabad":       (77.30, 28.41),
    "Ghaziabad":       (77.42, 28.67),
}
# Corridors: list of (name, [lon, lat] points, color)
CORRIDORS = [
    ("Dwarka Expressway",  [(76.98, 28.49), (77.06, 28.51), (77.10, 28.52)], ACCENT),
    ("Golf Course Road",   [(77.04, 28.44), (77.06, 28.45), (77.08, 28.46)], BLUE),
    ("Noida Expressway",   [(77.29, 28.54), (77.35, 28.51), (77.41, 28.48)], GREEN),
]


def main() -> None:
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    ax.set_facecolor(CARD)

    # Draw corridor polylines first (under the cities)
    for name, pts, color in CORRIDORS:
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        ax.plot(lons, lats, color=color, lw=7, alpha=0.85, solid_capstyle="round",
                zorder=2)
        # Label at the middle point
        mx, my = lons[1], lats[1]
        ax.annotate(name, (mx, my), textcoords="offset points", xytext=(10, -14),
                    color=color, fontsize=20, fontweight="bold", zorder=5)

    # City markers
    for city, (lon, lat) in LOCATIONS.items():
        ax.scatter(lon, lat, s=320, color=ACCENT, edgecolor=TXT, linewidth=2,
                   zorder=4)
        ax.annotate(city, (lon, lat), textcoords="offset points", xytext=(14, 12),
                    color=TXT, fontsize=26, fontweight="bold", zorder=5)

    # Bounding box (Delhi NCR extent)
    ax.set_xlim(76.90, 77.58)
    ax.set_ylim(28.36, 28.74)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_color(GRID)
        ax.spines[s].set_linewidth(2)

    ax.set_title("DELHI NCR — MICRO-MARKETS IN FOCUS", color=TXT,
                 fontsize=40, fontweight="bold", pad=20, loc="left")
    ax.text(0.0, -0.06, "Dwarka Exprwy · Golf Course Rd · Noida Exprwy — the corridors driving 2026 price growth",
            transform=ax.transAxes, color="#8fa8b0", fontsize=19, va="top")
    fig.tight_layout()
    fig.savefig(OUT / "map_delhi_ncr.png", dpi=100)
    plt.close(fig)
    print("map_delhi_ncr.png")


if __name__ == "__main__":
    main()
