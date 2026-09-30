#!/usr/bin/env python3
"""Rank state candidates for a Featured batch (demand proxy join).

Signals joined per candidate:
  - CDFW stocking (statewide export; plants in the last ~year) — managed-fishery
    and trout-demand evidence;
  - county population (Census vintage CSV, cached 30 days) — reach;
  - distance to the nearest already-covered registry water — cluster value.

Stocking rows match candidates by coordinates (fallback: distinctive name
tokens) within the row's county (multi-county rows are split). Obvious
watercourses (rivers/creeks/sloughs/meadows) are flagged, not silently dropped.
Writes config/candidates/<ST>_ranked.json.

    ~/.astro-venv/bin/python tools/rank_candidates.py --state CA
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from layers.stocking import _tok, fetch_all_plants  # noqa: E402

REGISTRY = ROOT / "config" / "lakes.json"
CANDIDATES = ROOT / "config" / "candidates"
CENSUS_CACHE = ROOT / ".cache" / "census"
CENSUS_URL = ("https://www2.census.gov/programs-surveys/popest/datasets/"
              "2020-2024/counties/totals/co-est2024-alldata.csv")
NOT_LAKE = ("river", "creek", "slough", "fork", "section", "meadow", "canal",
            "ditch", "drain", "wash", "springs", "falls", "rapids", "gorge",
            "historical", "basin", "flood")


def _haversine_m(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def _nearest_covered_km(lat: float, lng: float, reg_pts: list) -> float | None:
    if not reg_pts:
        return None
    return min(_haversine_m((lat, lng), p) for p in reg_pts) / 1000


def _lake_like(name: str) -> bool:
    n = (name or "").lower()
    return not any(tok in n for tok in NOT_LAKE)


def _county_pop() -> dict[str, int]:
    """CA county name (lowercase, no ' County') → 2024 population estimate."""
    CENSUS_CACHE.mkdir(parents=True, exist_ok=True)
    path = CENSUS_CACHE / "co-est2024-alldata.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 30 * 86400:
        req = urllib.request.Request(CENSUS_URL,
                                     headers={"User-Agent": "baromoon-coverage/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    out = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8", errors="replace"))):
        if row.get("STNAME") == "California":
            name = (row.get("CTYNAME") or "").replace(" County", "").strip().lower()
            try:
                out[name] = int(row.get("POPESTIMATE2024") or 0)
            except ValueError:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="CA")
    ap.add_argument("--radius-m", type=float, default=2000.0)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    cand_path = CANDIDATES / f"{args.state}.json"
    if not cand_path.exists():
        raise SystemExit(f"no candidate file at {cand_path} — run tools/gnis_inventory.py first")
    waters = json.loads(cand_path.read_text())["waters"]
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    reg_pts = [(v["lat"], v["lng"]) for v in reg.values()
               if v.get("lat") is not None and v.get("lng") is not None]
    pops = _county_pop()

    plants = fetch_all_plants(1)
    by_county = defaultdict(list)
    for w in waters:
        by_county[(w.get("county") or "").strip().lower()].append(w)

    hits = defaultdict(lambda: dict(plants=0, weeks=set(), species=set(),
                                    last="", match_m=None, cdfw_water=""))
    matched_rows = 0
    unmatched = defaultdict(lambda: dict(plants=0, county="", species=set(),
                                         last="", water_id=""))
    for p in plants:
        counties = [c.strip().lower() for c in (p.get("county") or "").split(",") if c.strip()]
        pool = [w for c in counties for w in by_county.get(c, [])]
        if not pool:
            unmatched[(p.get("water"), p.get("county"))]["plants"] += 1
            continue
        best = None
        ptok = _tok(p.get("water") or "")
        if p.get("lat") is not None:
            for w in pool:
                d = _haversine_m((p["lat"], p["lng"]), (w["lat"], w["lng"]))
                # Conservative: a close coordinate alone can be a neighbouring
                # water (Kings River vs Avocado Lake). Require a distinctive
                # name token, or a very tight (<300 m) location match.
                if (ptok & _tok(w["name"])) and d <= args.radius_m:
                    if best is None or d < best[0]:
                        best = (d, w)
                elif d <= 300 and (best is None or d < best[0]):
                    best = (d, w)
        if best is None and ptok:
            for w in pool:
                if ptok & _tok(w["name"]):
                    d = (_haversine_m((p["lat"], p["lng"]), (w["lat"], w["lng"]))
                         if p.get("lat") is not None else 99999)
                    if best is None or d < best[0]:
                        best = (d, w)
        if best is None:
            key = (p.get("water"), p.get("county"))
            u = unmatched[key]
            u["plants"] += 1
            u["county"] = p.get("county")
            u["species"].add(p.get("species"))
            u["last"] = max(u["last"], p.get("date") or "")
            u["water_id"] = p.get("water_id")
            continue
        matched_rows += 1
        d, w = best
        h = hits[w["feature_id"]]
        h["plants"] += 1
        h["weeks"].add(p.get("date") or "")
        h["species"].add(p.get("species"))
        h["last"] = max(h["last"], p.get("date") or "")
        h["match_m"] = d
        h["cdfw_water"] = p.get("water")

    ranked = []
    for w in waters:
        h = hits.get(w["feature_id"])
        if not h:
            continue
        pop = pops.get((w.get("county") or "").strip().lower(), 0)
        near = _nearest_covered_km(w["lat"], w["lng"], reg_pts) or 0
        reach = math.log10(max(pop, 1000)) if pop else 3.0
        stock = 1 + min(h["plants"], 20) / 20          # 1..2
        prox = 1 + max(0.0, 1 - near / 120)            # 1..2
        ranked.append(dict(
            feature_id=w["feature_id"], name=w["name"],
            feature_class=w["feature_class"], county=w["county"],
            lat=w["lat"], lng=w["lng"], county_pop=pop,
            lake_like=_lake_like(w["name"]),
            plants=h["plants"], weeks=len(h["weeks"]),
            species=sorted(s for s in h["species"] if s),
            last_plant=h["last"], cdfw_water=h["cdfw_water"],
            match_m=round(h["match_m"], 1) if h["match_m"] is not None else None,
            nearest_covered_km=round(near, 1), score=round(reach * stock * prox, 2)))
    ranked.sort(key=lambda r: -r["score"])

    out = CANDIDATES / f"{args.state}_ranked.json"
    first = [r for r in ranked if r["lake_like"]]
    out.write_text(json.dumps(dict(
        state=args.state, generated_from=cand_path.name,
        stocking_rows=len(plants), matched_rows=matched_rows,
        ranked=ranked,
        ranked_lake_like=first,
        unmatched=sorted(({**v, "water": k[0], "county": k[1],
                           "species": sorted(v["species"])}
                          for k, v in unmatched.items()),
                         key=lambda x: -x["plants"])[:200],
    ), indent=1, default=list) + "\n")

    print(f"CDFW rows: {len(plants):,} · matched to candidates: {matched_rows:,} "
          f"({matched_rows / max(1, len(plants)):.0%})")
    print(f"{len(ranked):,} candidates carry a plant; "
          f"{len(first):,} look lake-like (of {len(waters):,})\n")
    print(f"{'#':>3} {'name':36s} {'class':9s} {'county':14s} {'pop':>9} "
          f"{'pl':>3} {'wks':>4} {'last':10s} {'km':>6} {'score':>6}  species")
    for i, r in enumerate(first[:args.top], 1):
        print(f"{i:3d} {r['name'][:36]:36s} {r['feature_class']:9s} {r['county'][:14]:14s} "
              f"{r['county_pop']:9,d} {r['plants']:3d} {r['weeks']:4d} "
              f"{r['last_plant'][:10]:10s} {r['nearest_covered_km']:6.0f} "
              f"{r['score']:6.2f}  {','.join(r['species'])}")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
