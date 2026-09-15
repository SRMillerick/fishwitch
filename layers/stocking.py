"""Fish stocking layer — CDFW planting events.

Trout planted in a bass lake = a forage event: stockers run shallow for
days after planting and the bass know the schedule better than the anglers.
Primary: data.ca.gov open-data API (Socrata-style datastore_search).
Fallback: manual `stocking` entries in config/lakes.json (date, species, count).
"""
from __future__ import annotations
from datetime import datetime, timedelta
import requests

UA = {"User-Agent": "fishwitch-mvp/1.0"}
DATA_CA_GOV = "https://data.ca.gov/api/3/action/datastore_search"


def fetch_recent_stocking(water_name: str, days: int = 45,
                          resource_id: str | None = None) -> list[dict]:
    """Query the CA open-data portal; returns [] on any failure (no key)."""
    if not resource_id:
        # resource id for CDFW fish stocking is set in lakes.json when known
        return []
    try:
        r = requests.get(DATA_CA_GOV, params=dict(
            resource_id=resource_id, limit=1000,
            q=water_name), headers=UA, timeout=15)
        r.raise_for_status()
        rows = r.json()["result"]["records"]
    except Exception:
        return []
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for row in rows:
        when = row.get("date") or row.get("stocking_date") or ""
        try:
            dt = datetime.fromisoformat(str(when)[:10])
        except ValueError:
            continue
        if dt >= cutoff and water_name.split(",")[0].lower() in str(row).lower():
            out.append(dict(date=dt, species=str(row.get("species", "fish")).strip()))
    return sorted(out, key=lambda x: x["date"])


def registry_stocking(lake: dict, days: int = 45) -> list[dict]:
    """Manual entries from lakes.json: stocking: [{date, species}]."""
    out = []
    cutoff = datetime.now() - timedelta(days=days)
    for e in lake.get("stocking", []):
        try:
            dt = datetime.fromisoformat(str(e.get("date"))[:10])
        except ValueError:
            continue
        if dt >= cutoff:
            out.append(dict(date=dt, species=e.get("species", "fish")))
    return sorted(out, key=lambda x: x["date"])


def recent(lake: dict, days: int = 45) -> list[dict]:
    rid = (lake.get("sources") or {}).get("cdfw_resource_id")
    return fetch_recent_stocking(lake["name"], days, rid) or registry_stocking(lake, days)
