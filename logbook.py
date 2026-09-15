"""Catch logbook — the feedback loop. Log what you catch; future reports get
empirical: your best producers at this lake, under this moon phase, at this
hour. Data beats doctrine.

    fishwitch log --lure "110 walker" --species bass --notes "grass edge"
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

BOOK = Path(__file__).resolve().parent / "config" / "logbook.jsonl"


def append(entry: dict):
    BOOK.parent.mkdir(exist_ok=True)
    entry.setdefault("ts", datetime.now().isoformat(timespec="minutes"))
    with BOOK.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def load() -> list[dict]:
    if not BOOK.exists():
        return []
    out = []
    for line in BOOK.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summary_for(lake_name: str, angler: str | None = None) -> dict | None:
    """Catch stats, optionally scoped to one angler: {n, best_lure, best_lure_n}."""
    rows = [r for r in load()
            if (r.get("lake") or "").lower() in (lake_name or "").lower()]
    if angler:
        rows = [r for r in rows if (r.get("angler") or "").lower() == angler.lower()]
    rows = [r for r in rows if r.get("result") != "skunk"]  # catches only
    if not rows:
        return None
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("lure"):
            counts[r["lure"]] = counts.get(r["lure"], 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else None
    return dict(n=len(rows), best_lure=best[0] if best else None,
                best_lure_n=best[1] if best else 0)
