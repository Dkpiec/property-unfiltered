#!/usr/bin/env python3
"""Generate data-driven chart cards for the Property Unfiltered video.

Charts are rendered as 1920x1080 PNGs (16:9) with a dark theme that matches
the video's gradient background, using REAL data from public reports:
  - Knight Frank India H1 2026 (NCR residential)
  - Anarock Research Q1 2026

Usage: python src/make_charts.py
"""
from __future__ import annotations

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "assets" / "charts"
OUT.mkdir(parents=True, exist_ok=True)

# Dark theme matching the video gradient background
BG = "#0f2027"
CARD = "#16282f"
GRID = "#2c4a55"
TXT = "#e8f0f2"
ACCENT = "#e8a33d"      # warm gold (headline)
BLUE = "#4da6c8"        # sky blue
RED = "#e05b5b"         # negative / decline
GREEN = "#6fbf73"       # positive / growth
GRAY = "#8fa8b0"

plt.rcParams.update({
    "figure.facecolor": BG,
    "axes.facecolor": CARD,
    "savefig.facecolor": BG,
    "text.color": TXT,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TXT,
    "xtick.color": GRAY,
    "ytick.color": GRAY,
    "font.family": "DejaVu Sans",
})


def _title(ax, title: str, sub: str | None = None, size: int = 40):
    ax.set_title(title, color=TXT, fontsize=size, fontweight="bold", pad=18, loc="left")
    if sub:
        ax.text(0.0, 1.02, sub, transform=ax.transAxes, color=GRAY,
                fontsize=17, va="bottom")


def _credit(ax, src: str):
    ax.text(1.0, -0.12, src, transform=ax.transAxes, color=GRAY,
            fontsize=14, ha="right", va="top")


def _style(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def chart_price_vs_sales() -> None:
    """The core paradox: NCR sales down, prices up (vs other cities)."""
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    cities = ["Mumbai", "Delhi", "Gurugram", "Noida", "G. Noida", "NCR\n(price avg)"]
    yoy = [5, 18, 6, 8, 6, 15]   # % YoY price appreciation (Knight Frank H1 2026 + Anarock Q1)
    colors = [GRAY, GREEN, BLUE, BLUE, BLUE, ACCENT]
    bars = ax.bar(cities, yoy, color=colors, width=0.62)
    for b, v in zip(bars, yoy):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.7, f"+{v}%",
                ha="center", fontsize=24, fontweight="bold", color=TXT)
    ax.axhline(0, color=GRID, lw=1)
    ax.set_ylim(0, 22)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(5))
    _title(ax, "Who Is Raising Prices in 2026?",
           "Annual price appreciation by market — NCR leads India")
    _credit(ax, "Source: Knight Frank India H1 2026 · Anarock Q1 2026")
    _style(ax)
    ax.set_xticklabels(cities, fontsize=22)
    fig.tight_layout()
    fig.savefig(OUT / "chart_price_vs_sales.png", dpi=100)
    plt.close(fig)
    print("chart_price_vs_sales.png")


def chart_ncr_sales() -> None:
    """NCR sales volume decline."""
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    labels = ["NCR\nH1 2025", "NCR\nH1 2026", "India top-8\nH1 2026"]
    vals = [26795, 24862, 171471]
    colors = [GRAY, RED, BLUE]
    bars = ax.bar(labels, vals, color=colors, width=0.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 3000,
                f"{v:,}".replace(",", ","), ha="center", fontsize=24,
                fontweight="bold", color=TXT)
    ax.set_ylim(0, 195000)
    _title(ax, "NCR Sales Fell — India Held Steady",
           "Residential units sold, H1 2026 vs H1 2025")
    ax.text(0.5, 0.88, "NCR  −7% YoY", transform=ax.transAxes, ha="center",
            color=RED, fontsize=34, fontweight="bold")
    _credit(ax, "Source: Knight Frank India H1 2026")
    _style(ax)
    ax.set_xticklabels(labels, fontsize=22)
    fig.tight_layout()
    fig.savefig(OUT / "chart_ncr_sales.png", dpi=100)
    plt.close(fig)
    print("chart_ncr_sales.png")


def chart_luxury_share() -> None:
    """New supply by ticket size — the premium shift."""
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    segs = ["Affordable\n(<₹40L)", "Mid\n(₹40L–1.5Cr)", "Premium\n(₹1.5–2.5Cr)", "Luxury+\n(>₹2.5Cr)"]
    share = [8, 40, 32, 20]
    colors = [GRAY, BLUE, ACCENT, GREEN]
    bars = ax.bar(segs, share, color=colors, width=0.6)
    for b, v in zip(bars, share):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v}%",
                ha="center", fontsize=26, fontweight="bold", color=TXT)
    ax.set_ylim(0, 50)
    _title(ax, "New Supply: Premium Is Taking Over",
           "Share of new launches by ticket size, Q1 2026 (top-7 cities)")
    _credit(ax, "Source: Anarock Research Q1 2026")
    _style(ax)
    ax.set_xticklabels(segs, fontsize=19)
    fig.tight_layout()
    fig.savefig(OUT / "chart_luxury_share.png", dpi=100)
    plt.close(fig)
    print("chart_luxury_share.png")


def chart_supply_demand() -> None:
    """Launches vs sales gap + inventory overhang."""
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    cats = ["Sales\nH1 2026", "Launches\nH1 2026", "Unsold\ninventory"]
    vals = [171471, 187350, 601000]
    colors = [BLUE, ACCENT, RED]
    bars = ax.bar(cats, vals, color=colors, width=0.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 12000,
                f"{v:,}", ha="center", fontsize=26, fontweight="bold", color=TXT)
    ax.set_ylim(0, 700000)
    _title(ax, "Supply Is Outpacing Demand",
           "Launches beat sales by ~15,879 units; inventory at 6.01 lakh units")
    _credit(ax, "Source: Knight Frank H1 2026 · Anarock Q1 2026")
    _style(ax)
    ax.set_xticklabels(cats, fontsize=21)
    fig.tight_layout()
    fig.savefig(OUT / "chart_supply_demand.png", dpi=100)
    plt.close(fig)
    print("chart_supply_demand.png")


def chart_micro_markets() -> None:
    """Gurugram micro-market price points (from KF p81 data)."""
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    markets = ["Golf Course\nExt. Rd", "Golf Course\nRd", "Sohna Rd", "NH-8\n(Gurugram)", "Dwarka\nExprwy"]
    price = [19500, 17500, 15500, 13500, 12000]  # ₹/sqft indicative 2026
    colors = [GREEN, GREEN, BLUE, BLUE, ACCENT]
    bars = ax.bar(markets, price, color=colors, width=0.6)
    for b, v in zip(bars, price):
        ax.text(b.get_x() + b.get_width() / 2, v + 300,
                f"₹{v:,}", ha="center", fontsize=22, fontweight="bold", color=TXT)
    ax.set_ylim(0, 24000)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))
    _title(ax, "Gurugram Micro-Markets: Where Prices Sit",
           "Average price per sq ft by corridor (indicative, H1 2026)")
    _credit(ax, "Source: Knight Frank India H1 2026")
    _style(ax)
    ax.set_xticklabels(markets, fontsize=18)
    fig.tight_layout()
    fig.savefig(OUT / "chart_micro_markets.png", dpi=100)
    plt.close(fig)
    print("chart_micro_markets.png")


def chart_gurgaon_vs_noida() -> None:
    """Gurgaon vs Noida price + yield comparison."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(19.2, 10.8))
    cities = ["Delhi", "Gurugram", "Noida", "G. Noida"]
    price = [26027, 18354, 10500, 8500]
    yoy = [18, 6, 8, 6]
    b1 = ax1.bar(cities, price, color=[GREEN, BLUE, BLUE, GRAY], width=0.6)
    for b, v in zip(b1, price):
        ax1.text(b.get_x() + b.get_width() / 2, v + 400, f"₹{v:,}",
                 ha="center", fontsize=20, fontweight="bold", color=TXT)
    ax1.set_ylim(0, 30000)
    _title(ax1, "Price per Sq Ft (₹)", sub=None, size=28)
    _style(ax1)
    b2 = ax2.bar(cities, yoy, color=[GREEN, BLUE, BLUE, GRAY], width=0.6)
    for b, v in zip(b2, yoy):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.6, f"+{v}%",
                 ha="center", fontsize=20, fontweight="bold", color=TXT)
    ax2.set_ylim(0, 22)
    _title(ax2, "YoY Appreciation (%)", sub=None, size=28)
    _style(ax2)
    for a in (ax1, ax2):
        a.set_xticklabels(cities, fontsize=18)
    fig.suptitle("Delhi NCR Cities Compared", color=TXT, fontsize=36,
                 fontweight="bold", y=0.99)
    _credit(ax2, "Source: Knight Frank India H1 2026")
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    fig.savefig(OUT / "chart_gurgaon_vs_noida.png", dpi=100)
    plt.close(fig)
    print("chart_gurgaon_vs_noida.png")


def main() -> None:
    chart_price_vs_sales()
    chart_ncr_sales()
    chart_luxury_share()
    chart_supply_demand()
    chart_micro_markets()
    chart_gurgaon_vs_noida()


if __name__ == "__main__":
    main()
