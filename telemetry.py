"""Aggregate page telemetry — the privacy-preserving counterpart to the
outbound-click counter (`logs/out.jsonl`, see `offers.py`).

What is stored: one JSON line per page view — UTC timestamp, route path, the
lake registry key when the route carries one, and the *external referrer host*
only. No IP address, no user agent, no cookies, no full referrer URL, no query
strings. Bots are not filtered (the counts are raw). Read with
`fishwitch stats`; the local web app can render the same summary at /stats.

This is deliberately dumb (append-only, day-rollable by the reader) so it can
never become a user profile: there is no session id and nothing to join on.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

PAGES = Path(__file__).resolve().parent / "logs" / "pages.jsonl"

# routes that are not "pages" for counting purposes
SKIP_PREFIXES = ("/static/", "/out/", "/api/", "/favicon", "/stats")
SKIP_EXACT = ("/robots.txt", "/sitemap.xml")

_LAKE_SAFE = re.compile(r"[^a-z0-9-]")


def should_count(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path.startswith(SKIP_PREFIXES) or path in SKIP_EXACT:
        return False
    return True


def normalize_lake(value: str | None) -> str:
    """Registry keys only — free text, coordinates, or anything long is dropped."""
    if not value:
        return ""
    v = _LAKE_SAFE.sub("", value.strip().lower())[:64]
    return v if 3 <= len(v) <= 64 else ""


def record(path: str, lake: str | None = None, ref: str | None = None,
           log: Path | None = None) -> None:
    """Append one aggregate view line. Never raises (telemetry is best-effort)."""
    try:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path": path[:96], "lake": normalize_lake(lake), "ref": _ref_host(ref)}
        with (log or PAGES).open("a") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass


def _ref_host(ref: str | None) -> str:
    if not ref:
        return ""
    try:
        host = (urlparse(ref).netloc or "").lower().split("@")[-1].split(":")[0]
        return host[:64]
    except Exception:
        return ""


def read(log: Path | None = None) -> list[dict]:
    p = log or PAGES
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        try:
            r = json.loads(line)
            if isinstance(r, dict) and r.get("path"):
                rows.append(r)
        except Exception:
            pass
    return rows


def summarize(days: int = 30, log: Path | None = None, top: int = 15) -> dict:
    """Aggregate rows within the trailing `days` window (UTC)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    rows = []
    for r in read(log):
        try:
            ts = datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                rows.append(r)
        except Exception:
            continue
    by_path = Counter(r.get("path") or "?" for r in rows)
    by_lake = Counter(r.get("lake") for r in rows if r.get("lake"))
    by_ref = Counter(r.get("ref") for r in rows if r.get("ref"))
    by_day = Counter(str(r.get("ts", ""))[:10] for r in rows)
    return dict(total=len(rows), days=days,
                by_path=by_path.most_common(top),
                by_lake=by_lake.most_common(top),
                by_ref=by_ref.most_common(top),
                by_day=sorted(by_day.items()))
