"""ICS / RSS rendering for the tier ledger — plain text, no dependencies.

Both feeds are deterministic over the same `_horizon()` window scan that
powers /outlook: no accounts, no tracking, no third-party requests. Calendar
clients subscribe by URL; nothing is emailed and nothing is stored.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from email.utils import format_datetime
from zoneinfo import ZoneInfo

BASE = "https://baromoon.com"
MIN_OVERALL = 7.0  # A-tier and up — "plan around it"


def tier(overall: float) -> str:
    return "S" if overall >= 7.5 else ("A" if overall >= 7.0 else "B")


def _utc(dt: datetime, tz: str | None) -> datetime:
    try:
        return dt.replace(tzinfo=ZoneInfo(tz or "UTC")).astimezone(timezone.utc)
    except Exception:
        return dt.replace(tzinfo=timezone.utc)


def _ics_text(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;") \
                   .replace(",", "\\,").replace("\n", "\\n")


def _report_url(lake: dict, start: datetime, base: str) -> str:
    key = lake.get("id") or lake.get("name", "")
    return f"{base}/report?lake={key}&at={start:%Y-%m-%d}%20{start:%H:%M}"


def ical(rows: list[dict], lake: dict, base: str = BASE) -> str:
    key = lake.get("id") or lake.get("name", "")
    tz = lake.get("tz")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//baromoon//ledger//EN",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
           f"X-WR-CALNAME:baromoon — {_ics_text(lake.get('name', ''))}"]
    for r in rows:
        picks = " + ".join(r.get("picks") or []) or "fish"
        start, end = r["start"], r["end"]
        summary = f"baromoon {tier(r['overall'])} · {r['overall']:g} — {picks}"
        desc = f"{lake.get('name', '')} · picks: {picks}"
        if r.get("prime"):
            desc += f" · prime {r['prime']:%H:%M}"
        out += ["BEGIN:VEVENT",
                f"UID:{start:%Y%m%dT%H%M%S}-{key}@baromoon.com",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_utc(start, tz):%Y%m%dT%H%M%SZ}",
                f"DTEND:{_utc(end, tz):%Y%m%dT%H%M%SZ}",
                f"SUMMARY:{_ics_text(summary)}",
                f"DESCRIPTION:{_ics_text(desc)}",
                f"URL:{_report_url(lake, start, base)}",
                "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def rss(rows: list[dict], lake: dict, base: str = BASE) -> str:
    key = lake.get("id") or lake.get("name", "")
    tz = lake.get("tz")
    items = []
    for r in rows:
        picks = " + ".join(r.get("picks") or []) or "fish"
        start = r["start"]
        title = f"{start:%a %b %d, %I:%M %p} — {tier(r['overall'])} ({r['overall']:g})"
        desc = f"{lake.get('name', '')} · picks: {picks}"
        if r.get("prime"):
            desc += f" · prime {r['prime']:%I:%M %p}"
        items.append(
            "<item>"
            f"<title>{html.escape(title)}</title>"
            f"<link>{html.escape(_report_url(lake, start, base))}</link>"
            f'<guid isPermaLink="false">{start:%Y%m%dT%H%M%S}-{key}</guid>'
            f"<pubDate>{format_datetime(_utc(start, tz))}</pubDate>"
            f"<description>{html.escape(desc)}</description>"
            "</item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
            f"<title>baromoon — best windows, {html.escape(lake.get('name', ''))}</title>"
            f"<link>{base}/outlook?lake={key}</link>"
            "<description>Scored fishing windows from weather, sky and lake state. "
            "Ranking never sees money; conditions-first, same inputs → same report.</description>"
            + "".join(items) + "</channel></rss>")
