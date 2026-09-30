"""External API usage log — aggregate call counts for the free-tier budget.

One JSONL row per HTTP attempt: {ts, service, endpoint, locations, days,
status}. No PII, no coordinates, no query strings — just what the budget
needs to stay visible before nationwide coverage scales.

Best-effort: a logging failure must never break a report. Read with
`fishwitch weather [--remote]`.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

USAGE = Path(__file__).resolve().parent / "logs" / "usage.jsonl"

# Free-tier ceilings to watch (Open-Meteo, verified 2026-09-30)
FREE_LIMITS = {"per_day": 10_000, "per_hour": 5_000, "per_month": 300_000,
               "commercial": False}


def record(service: str, endpoint: str = "", locations: int = 1,
           days: int | None = None, status=None, note: str = "",
           log: Path | None = None) -> None:
    # The env switch silences the production path; an explicit log argument is
    # always honoured (tests use temp files).
    if log is None and os.environ.get("FISHWITCH_NO_USAGE") == "1":
        return
    try:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "service": service[:32], "endpoint": endpoint[:48],
                "locations": max(0, int(locations)), "days": days, "status": status}
        if note:
            line["note"] = note[:80]
        path = log or USAGE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass


def parse(lines) -> list[dict]:
    rows = []
    for line in lines:
        try:
            r = json.loads(line)
            if isinstance(r, dict) and r.get("service"):
                rows.append(r)
        except Exception:
            pass
    return rows


def read(log: Path | None = None) -> list[dict]:
    p = log or USAGE
    return parse(p.read_text().splitlines()) if p.exists() else []


def summarize(days: int = 30, rows: list[dict] | None = None) -> dict:
    """Totals within the trailing window (UTC), plus today's count."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, days))
    window, today = [], now.date().isoformat()
    for r in (rows if rows is not None else read()):
        try:
            ts = datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            window.append(r)
    calls = sum(max(1, int(r.get("locations") or 1)) for r in window)
    by_service = Counter()
    for r in window:
        by_service[r.get("service")] += max(1, int(r.get("locations") or 1))
    by_day = Counter(str(r.get("ts", ""))[:10] for r in window)
    today_rows = [r for r in window if str(r.get("ts", ""))[:10] == today]
    return dict(days=days, requests=len(window), calls=calls,
                today_calls=sum(max(1, int(r.get("locations") or 1)) for r in today_rows),
                today_requests=len(today_rows),
                by_service=by_service.most_common(),
                by_day=sorted(by_day.items()),
                limits=FREE_LIMITS)
