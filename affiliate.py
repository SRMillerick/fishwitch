#!/usr/bin/env python3
"""Affiliate monitoring — the weekly Amazon check as one command.

Amazon has **no earnings API and no sale/earnings alerts** (verified 2026-09-30:
e-mail preferences are newsletters/updates, SMS is marketing, push is
deals/program/recommendations). Revenue therefore stays a manual dashboard
check; this module automates the *trigger* — it summarizes the outbound-click
log into the numbers that matter for Associates and keeps the 3-sale clock in
view.

Pure functions only; the CLI feeds it rows read from `logs/out.jsonl`.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

APPROVED = date(2026, 9, 28)                    # Amazon Associates approval
DEADLINE = APPROVED + timedelta(days=180)       # 3 qualifying sales or closure
TARGET = 3
DASHBOARD = "https://affiliate-program.amazon.com/home"
# Only Amazon links carry the Associates tag; manufacturer/rapala/zman links
# carry no commission and are reported separately.
COMMISSIONED = {"amazon"}


def within_days(rows: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    out = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(str(r.get("ts", "")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                out.append(r)
        except Exception:
            continue
    return out


def summarize(rows: list[dict], days: int = 7, top: int = 6) -> dict:
    window = within_days(rows, days)
    bots = [r for r in window if r.get("bot")]
    human = [r for r in window if not r.get("bot")]
    amazon = [r for r in human if (r.get("retailer") or "").lower() in COMMISSIONED]
    other = Counter((r.get("retailer") or "?") for r in human
                    if (r.get("retailer") or "").lower() not in COMMISSIONED)
    return dict(
        days=days,
        total=len(human),
        bots=len(bots),
        amazon=len(amazon),
        share=(len(amazon) / len(human) if human else 0.0),
        by_entry=Counter(r.get("entry") or "?" for r in amazon).most_common(top),
        by_src=Counter(r.get("src") or "?" for r in amazon).most_common(),
        other=other.most_common(top),
        deadline=DEADLINE,
        days_left=(DEADLINE - date.today()).days,
        target=TARGET,
    )
