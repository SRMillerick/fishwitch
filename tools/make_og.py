#!/usr/bin/env python3
"""Generate the 1200x630 social card at web/static/og-card.png.

Reproducible asset: reads the traced triskelion from
web/static/triskelion-bold.svg, uses Cormorant Garamond when available (it
downloads the OFL variable font to /tmp on first run) and falls back to
Liberation Serif. Run from the repo root:

    ~/.astro-venv/bin/python tools/make_og.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "static" / "og-card.png"
MARK = ROOT / "web" / "static" / "triskelion-bold.svg"
W, H = 1200, 630
PAPER, INK, GOLD, DIM, LINE = "#f7f5ef", "#14232a", "#8a5f16", "#4e5c5f", "#c8b183"
FONT_URL = ("https://raw.githubusercontent.com/google/fonts/main/ofl/"
            "cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf")


def _display_font(size: int, weight: int = 400):
    """Cormorant Garamond if we can get it, else the system serif."""
    for cand in (Path.home() / ".fonts" / "CormorantGaramond.ttf",
                 Path("/tmp/CormorantGaramond.ttf")):
        if cand.exists():
            path = cand
            break
    else:
        path = Path(tempfile.gettempdir()) / "CormorantGaramond.ttf"
        try:
            import urllib.request
            urllib.request.urlretrieve(FONT_URL, path)
        except Exception:
            path = Path("/usr/share/fonts/liberation/LiberationSerif-Regular.ttf")
    font = ImageFont.truetype(str(path), size)
    try:  # variable font: pick the weight axis when FreeType supports it
        font.set_variation_by_axes([weight])
    except Exception:
        pass
    return font


def _mark_png(height: int) -> Path:
    """Rasterize the triskelion in brand gold via rsvg-convert."""
    svg = MARK.read_text().replace('fill="#000"', f'fill="{GOLD}"')
    src = Path(tempfile.gettempdir()) / "baromoon-mark.svg"
    dst = Path(tempfile.gettempdir()) / "baromoon-mark.png"
    src.write_text(svg)
    subprocess.run(["rsvg-convert", "-h", str(height), "-o", str(dst), str(src)],
                   check=True, capture_output=True)
    return dst


def main() -> int:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # manuscript frame + double rules
    d.rectangle([36, 36, W - 37, H - 37], outline=LINE, width=1)
    for y in (70, 74, H - 74, H - 70):
        d.line([(90, y), (W - 90, y)], fill=LINE, width=1)

    mark = Image.open(_mark_png(118)).convert("RGBA")
    img.paste(mark, ((W - mark.width) // 2, 104), mark)

    d.text((W // 2, 300), "baromoon", font=_display_font(104, 600),
           fill=INK, anchor="mm")
    d.text((W // 2, 398), "When to go. What to throw.", font=_display_font(44),
           fill=GOLD, anchor="mm")
    d.text((W // 2, 476), "Deterministic, cited fishing plans \u00b7 baromoon.com",
           font=_display_font(27), fill=DIM, anchor="mm")

    img.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB, {W}x{H})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
