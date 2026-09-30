#!/usr/bin/env python3
"""Registry coverage audit — fields, shorelines, and coordinate sanity.

Reports which waters lack full morphology, a shoreline polygon, or source
strings; and whether the registry point falls inside its shoreline ring (the
automated coordinate check that caught Fain and Highland Springs). Read-only.

    ~/.astro-venv/bin/python tools/audit_lakes.py [--gaps-only]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKES = ROOT / "config" / "lakes.json"
SHORES = ROOT / "config" / "shorelines.json"

REQUIRED = ("name", "lat", "lng", "species", "county")
FULL = ("region", "mixing", "depth_class", "est_max_depth_ft")
SOURCES = ("coords_source", "area_source", "depth_source")


def _state(v: dict) -> str:
    region = (v.get("region") or v.get("display") or "")
    m = re.search(r",\s*([A-Z]{2})(?:\s*,|$)", region)
    return m.group(1) if m else "?"


def _has_area(v: dict) -> bool:
    return bool(v.get("area_acres") or v.get("area_m2"))


def _point_in_ring(lat: float, lng: float, ring: list) -> bool:
    x, y, inside = lng, lat, False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][1], ring[i][0]
        xj, yj = ring[j][1], ring[j][0]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _nearest_vertex_m(lat: float, lng: float, ring: list) -> float:
    import math
    best = float("inf")
    for plat, plng in ring:
        dlat = math.radians(plat - lat)
        dlng = math.radians(plng - lng)
        h = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(plat))
             * math.sin(dlng / 2) ** 2)
        best = min(best, 6371000 * 2 * math.asin(min(1, math.sqrt(h))))
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gaps-only", action="store_true")
    args = ap.parse_args()

    lakes = json.loads(LAKES.read_text())
    shores = (json.loads(SHORES.read_text()).get("lakes", {})
              if SHORES.exists() else {})

    rows, gaps = [], 0
    for key, v in lakes.items():
        missing = [f for f in REQUIRED if v.get(f) in (None, "", [])]
        full_missing = [f for f in FULL if v.get(f) in (None, "", [])]
        if not _has_area(v):
            full_missing.append("area")
        if not (v.get("turnover") or {}).get("basis"):
            full_missing.append("turnover")
        src_missing = [f for f in SOURCES if not v.get(f)]
        ring = (shores.get(key) or {}).get("polygon")
        shore = "ok" if ring else "MISSING"
        inside = "-"
        if ring and v.get("lat") is not None:
            if _point_in_ring(v["lat"], v["lng"], ring):
                inside = "in"
            else:
                d = _nearest_vertex_m(v["lat"], v["lng"], ring)
                inside = "shore" if d <= 50 else f"OUT {d:.0f}m"
        row = dict(key=key, state=_state(v), required=missing, full=full_missing,
                   shore=shore, inside=inside, sources=src_missing)
        row["gaps"] = bool(missing or full_missing or not ring
                           or inside.startswith("OUT"))
        if row["gaps"]:
            gaps += 1
        rows.append(row)

    print(f"{'key':28s} {'st':3s} {'req':3s} {'full':5s} {'shore':7s} {'point':8s} sources")
    for r in rows:
        if args.gaps_only and not r["gaps"]:
            continue
        print(f"{r['key']:28s} {r['state']:3s} "
              f"{('OK' if not r['required'] else 'X'):3s} "
              f"{(str(len(r['full'])) if r['full'] else 'OK'):5s} "
              f"{r['shore']:7s} {r['inside']:8s} {','.join(r['sources']) or '-'}")
    print(f"\n{len(rows)} waters · {gaps} with gaps")
    for label, pred in (("missing required fields",
                         lambda r: r["required"]),
                        ("incomplete full card", lambda r: r["full"]),
                        ("no shoreline", lambda r: r["shore"] == "MISSING"),
                        ("point outside shoreline", lambda r: r["inside"].startswith("OUT")),
                        ("no source strings", lambda r: r["sources"])):
        n = sum(1 for r in rows if pred(r))
        if n:
            print(f"  {n:3d}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
