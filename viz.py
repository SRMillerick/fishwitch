"""Server-rendered SVG for a session — no JS, no libraries, deterministic.

The strip shows the report's own numbers on one line: the light bands across
the session, the sun-altitude curve, the barometer, event ticks (sunset, dusk,
solunar majors) and the prime window. Colors come from the page's design
tokens with first-light fallbacks, so print tokens still apply.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from xml.sax.saxutils import escape

LIGHT_FILL = {
    "night": ("var(--ink, #14232a)", 0.12),
    "dusk/dawn": ("var(--water, #17606f)", 0.20),
    "sunset/sunrise": ("var(--water, #17606f)", 0.16),
    "golden": ("var(--gold, #8a5f16)", 0.16),
    "moderate day": ("var(--ink, #14232a)", 0.06),
    "bright day": ("var(--ink, #14232a)", 0.09),
}
EVENTS = (("sunrise", "sunrise"), ("sunset", "sunset"),
          ("civil_dawn", "first light"), ("civil_dusk", "last light"))


def _x(dt: datetime, t0: datetime, t1: datetime, x0: float, x1: float) -> float:
    span = max(1.0, (t1 - t0).total_seconds())
    return x0 + (dt - t0).total_seconds() / span * (x1 - x0)


def _text(x: float, y: float, s: str, **attrs) -> str:
    a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" {a}>{escape(s)}</text>'


def session_timeline_svg(m: dict) -> str:
    t0, t1 = m.get("start"), m.get("end")
    blocks = m.get("blocks") or []
    if not t0 or not t1 or not blocks:
        return ""
    W, H = 1000.0, 188.0
    x0, x1 = 46.0, 988.0
    ytop, ybot = 22.0, 126.0
    prime = m.get("prime")
    mono = "ui-monospace, monospace"

    parts = [
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
        f'aria-label="Session timeline: light bands, sun altitude, pressure and events" '
        f'xmlns="http://www.w3.org/2000/svg">',
        "<title>Session timeline — light, pressure, events</title>",
    ]

    # light bands + block separators
    for b in blocks:
        bx0 = _x(b["start"], t0, t1, x0, x1)
        bx1 = _x(b["end"], t0, t1, x0, x1)
        fill, op = LIGHT_FILL.get(b.get("light", ""), ("var(--ink, #14232a)", 0.05))
        parts.append(f'<rect x="{bx0:.1f}" y="{ytop}" width="{max(1.0, bx1 - bx0):.1f}" '
                     f'height="{ybot - ytop}" fill="{fill}" opacity="{op}"/>')
        parts.append(f'<line x1="{bx0:.1f}" y1="{ytop}" x2="{bx0:.1f}" y2="{ybot}" '
                     f'stroke="var(--line-2, #e5e1d5)" stroke-width="1"/>')
    parts.append(f'<line x1="{x0}" y1="{ybot}" x2="{x1}" y2="{ybot}" '
                 f'stroke="var(--line, #b8b2a0)" stroke-width="1"/>')

    # sun altitude (fixed -20..80 °F-equivalent scale in feet of alt)
    pts = []
    for b in blocks:
        alt = b.get("sun_alt")
        if alt is None:
            continue
        mid = b["start"] + (b["end"] - b["start"]) / 2
        y = ybot - max(0.0, min(1.0, (alt + 20) / 100.0)) * (ybot - ytop)
        pts.append(f"{_x(mid, t0, t1, x0, x1):.1f},{y:.1f}")
    if len(pts) >= 2:
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                     f'stroke="var(--water, #17606f)" stroke-width="2" opacity=".9"/>')

    # pressure (gold) with lo/hi labels
    presses = [b["wx"]["press"] for b in blocks
               if b.get("wx") and b["wx"].get("press") is not None]
    if len(presses) >= 2:
        lo, hi = min(presses), max(presses)
        rng = max(1.0, hi - lo)
        ppts = []
        for b in blocks:
            p = (b.get("wx") or {}).get("press")
            if p is None:
                continue
            mid = b["start"] + (b["end"] - b["start"]) / 2
            y = ybot - (p - lo) / rng * (ybot - ytop) * 0.9 - 4
            ppts.append(f"{_x(mid, t0, t1, x0, x1):.1f},{y:.1f}")
        if len(ppts) >= 2:
            parts.append(f'<polyline points="{" ".join(ppts)}" fill="none" '
                         f'stroke="var(--gold, #8a5f16)" stroke-width="2"/>')
            parts.append(_text(4, ytop + 8, f"{hi:.0f}", fill="var(--gold, #8a5f16)",
                               font_size="10", font_family=mono))
            parts.append(_text(4, ybot - 2, f"{lo:.0f}", fill="var(--gold, #8a5f16)",
                               font_size="10", font_family=mono))

    # event ticks (sun events + solunar majors), alternating label rows
    marks = [(dt, lab) for key, lab in EVENTS
             if (dt := (m.get("sun") or {}).get(key)) and t0 <= dt <= t1]
    for e in (m.get("solunar") or []):
        peak = e.get("peak") or e.get("start")
        if e.get("kind") == "major" and peak and t0 <= peak <= t1:
            marks.append((peak, e.get("label", "major")))
    for i, (dt, lab) in enumerate(sorted(marks)[:6]):
        ex = _x(dt, t0, t1, x0, x1)
        parts.append(f'<line x1="{ex:.1f}" y1="{ytop}" x2="{ex:.1f}" y2="{ybot}" '
                     f'stroke="var(--dim, #4e5c5f)" stroke-width="1" '
                     f'stroke-dasharray="3 3" opacity=".8"/>')
        parts.append(_text(ex, 12 + (i % 2) * 9, lab, fill="var(--dim, #4e5c5f)",
                           font_size="10", text_anchor="middle"))

    # prime marker + pick line
    if prime:
        px0 = _x(prime["start"], t0, t1, x0, x1)
        px1 = _x(prime["end"], t0, t1, x0, x1)
        parts.append(f'<rect x="{px0:.1f}" y="{ytop}" width="{max(2.0, px1 - px0):.1f}" '
                     f'height="{ybot - ytop}" fill="none" stroke="var(--gold, #8a5f16)" '
                     f'stroke-width="2" rx="2"/>')
        picks = " + ".join(c["label"] for c, _, _ in (prime.get("picks") or [])[:2])
        if len(picks) > 44:
            picks = picks[:43] + "…"
        label = f"prime {prime['start']:%H:%M}"
        if picks:
            label += f" · {picks}"
        parts.append(_text(px0, 164, label, fill="var(--gold, #8a5f16)",
                           font_size="11.5", font_family=mono))

    # hour ticks
    step = 3600 if (t1 - t0).total_seconds() <= 4 * 3600 else 7200
    tick = t0.replace(minute=0, second=0, microsecond=0)
    if tick < t0:
        tick += timedelta(hours=1)
    while tick <= t1:
        tx = _x(tick, t0, t1, x0, x1)
        parts.append(f'<line x1="{tx:.1f}" y1="{ybot}" x2="{tx:.1f}" y2="{ybot + 4}" '
                     f'stroke="var(--line, #b8b2a0)" stroke-width="1"/>')
        parts.append(_text(tx, ybot + 15, tick.strftime("%-I %p"), fill="var(--dim, #4e5c5f)",
                           font_size="9.5", text_anchor="middle", font_family=mono))
        tick += timedelta(seconds=step)

    parts.append(_text(x1, 184, "sun altitude · barometer", fill="var(--dim, #4e5c5f)",
                       font_size="9.5", text_anchor="end", font_family=mono))
    parts.append("</svg>")
    return "".join(parts)
