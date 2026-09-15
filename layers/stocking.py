"""Fish stocking layer — CDFW planting events, live.

Source: CDFW's public Fish Planting Schedule (nrm.dfg.ca.gov/FishPlants/
PublicPlantSearch) — "updated in real time by hatchery staff". Queried by
county (the form's canonical filter), cached on disk (county map: 7 days,
plants: 12 hours — plants are weekly events).

Trout planted in a bass lake = a forage event: stockers run shallow for
days after planting and the bass know the schedule better than the anglers.

Water matching: CDFW spellings differ from ours ("Ralphine Lake" vs "Lake
Ralphine", "Blue Lake Upper" vs "Blue Lake (Upper Blue Lakes)") — match on
distinctive tokens (drop lake/reservoir/pond/river/park/the/county).

Fallback: manual `stocking` entries in config/lakes.json (date, species).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (baromoon fishing reports)"}
SEARCH = "https://nrm.dfg.ca.gov/fishplants/publicplantsearch"
CACHE = Path(__file__).resolve().parent.parent / ".cache" / "stocking"
STOP = {"lake", "lakes", "reservoir", "pond", "river", "creek", "park",
        "the", "county", "ca", "regional", "upper", "lower", "north", "south"}


def _tok(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t} - STOP


def county_ids() -> dict[str, int]:
    """name → id from the search form itself (no hardcoded county table)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / "counties.json"
    if key.exists() and time.time() - key.stat().st_mtime < 7 * 86400:
        return {k: v for k, v in json.loads(key.read_text()).items()}
    r = requests.get(SEARCH, headers=UA, timeout=20)
    r.raise_for_status()
    ids = dict(re.findall(r'<option value="(\d+)">([A-Za-z ]+)</option>', r.text))
    out = {name: int(i) for i, name in ids.items()}
    if out:
        key.write_text(json.dumps(out))
    return out


def fetch_county_plants(counties: list[str], timeframe: int = 1) -> list[dict]:
    """timeframe: 1=all (±1yr) · 2=current-future · 3=past. Cached 12h."""
    CACHE.mkdir(parents=True, exist_ok=True)
    ids = county_ids()
    wanted = []
    for c in counties:
        cid = ids.get(c) or ids.get(f"{c} County")
        if cid:
            wanted.append((c, cid))
    if not wanted:
        return []
    key = CACHE / ("plants_" + ",".join(str(c) for _, c in sorted(wanted)) + ".json")
    if key.exists() and time.time() - key.stat().st_mtime < 43200:
        return [dict(p, date=datetime.fromisoformat(p["date"])) for p in json.loads(key.read_text())]
    params = [("Params.Counties", str(cid)) for _, cid in wanted]
    params += [("Params.PlantTimeFrame", str(timeframe)), ("submit", "Search")]
    r = requests.get(SEARCH, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        if len(cells) != 4 or "Week of" in cells[0]:
            continue
        week, water, county, species = (re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in cells)
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})-", week)
        if not m:
            continue
        mm, dd, yy = map(int, m.groups())
        out.append(dict(date=datetime(yy, mm, dd), water=water,
                        county=county, species=species))
    out.sort(key=lambda p: p["date"])
    key.write_text(json.dumps([dict(p, date=p["date"].isoformat()) for p in out]))
    return out


def match_water(plants: list[dict], lake_name: str) -> list[dict]:
    """CDFW water names ↔ our registry names, by distinctive tokens."""
    want = _tok(lake_name)
    if not want:
        return []
    best, best_overlap = [], 0
    for p in plants:
        overlap = len(want & _tok(p["water"]))
        if overlap > best_overlap:
            best, best_overlap = [p], overlap
        elif overlap and overlap == best_overlap:
            best.append(p)
    return best if best_overlap else []


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
    """Most recent plants for this water, newest last. Live CDFW by county
    (lake card needs `county`), else manual registry entries."""
    county = lake.get("county")
    if county:
        try:
            plants = match_water(fetch_county_plants([county]), lake["name"])
            cutoff = datetime.now() - timedelta(days=days)
            hits = [dict(date=p["date"], species=p["species"])
                    for p in plants if p["date"] >= cutoff]
            if hits:
                return hits
        except Exception:
            pass  # CDFW unreachable → fall through to manual entries
    return registry_stocking(lake, days)
