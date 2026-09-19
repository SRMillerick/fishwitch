"""Shoreline fetch — OSM water polygons for the wind-exposure layer.

One-time (re-runnable) adapter, mirroring the other `adapters/`: fetch the
water body polygon around a lake's registry point from Overpass, stitch
multipolygon outers, keep the ring that contains the centroid (else the
largest), simplify to ~20 m, and write `config/shorelines.json`.

Data © OpenStreetMap contributors, ODbL. Output is cached in the repo because
report rendering must never depend on Overpass being up.

    python adapters/shorelines.py [--only lake-key] [--refresh]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LAKES = ROOT / "config" / "lakes.json"
OUT = ROOT / "config" / "shorelines.json"
UA = {"User-Agent": "fishwitch-mvp/1.0 (shoreline fetch; ODbL)"}
OVERPASS = "https://overpass-api.de/api/interpreter"
TOLERANCE_M = 10.0


def _query(lat: float, lng: float, radius_m: int) -> str:
    return (
        f"[out:json][timeout:40];"
        f"(way[\"natural\"=\"water\"](around:{radius_m},{lat},{lng});"
        f"relation[\"natural\"=\"water\"](around:{radius_m},{lat},{lng}););"
        "out geom;")


def _get(query: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            r = requests.get(OVERPASS, params={"data": query}, headers=UA, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError("overpass unavailable")


def _rings(element: dict) -> list[list[tuple[float, float]]]:
    """(lat, lng) rings from a way or a multipolygon relation."""
    def ring_from_geom(geom: list[dict]) -> list[tuple[float, float]]:
        return [(g["lat"], g["lon"]) for g in geom]

    if element.get("type") == "way":
        g = element.get("geometry") or []
        return [ring_from_geom(g)] if len(g) >= 4 else []

    # relation: stitch outer member ways by shared endpoints
    segs = []
    for m in element.get("members", []):
        if m.get("role") == "inner" or not m.get("geometry"):
            continue
        pts = ring_from_geom(m["geometry"])
        if len(pts) >= 2:
            segs.append(pts)
    rings: list[list[tuple[float, float]]] = []
    while segs:
        cur = segs.pop(0)
        changed = True
        while changed:
            changed = False
            for i, s in enumerate(segs):
                if cur[-1] == s[0]:
                    cur += s[1:]
                elif cur[-1] == s[-1]:
                    cur += list(reversed(s))[1:]
                elif cur[0] == s[-1]:
                    cur = s[:-1] + cur
                elif cur[0] == s[0]:
                    cur = list(reversed(s[:-1])) + cur
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if len(cur) >= 4 and cur[0] != cur[-1]:
            cur.append(cur[0])
        if len(cur) >= 4:
            rings.append(cur)
    return rings


def _contains(ring: list[tuple[float, float]], lat: float, lng: float) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x = (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1
            if lng < x:
                inside = not inside
    return inside


def _area_m2(ring: list[tuple[float, float]]) -> float:
    lat0 = sum(p[0] for p in ring) / len(ring)
    kx = 111320 * math.cos(math.radians(lat0))
    ky = 110540
    s = 0.0
    for i in range(len(ring)):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % len(ring)]
        s += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(s) / 2


def _perp(p, a, b):
    if a == b:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    y, x = p
    y1, x1 = a
    y2, x2 = b
    num = abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1))
    return num / math.hypot(x2 - x1, y2 - y1)


def _seg_dist_m(p, a, b, kx: float, ky: float) -> float:
    """Distance from point p to segment ab in metres (p,a,b are lat,lng)."""
    py, px = p[0] * ky, p[1] * kx
    ay, ax = a[0] * ky, a[1] * kx
    by, bx = b[0] * ky, b[1] * kx
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dist_to_ring(ring: list[tuple[float, float]], lat: float, lng: float) -> float:
    kx = 111320 * math.cos(math.radians(lat))
    ky = 110540
    return min(_seg_dist_m((lat, lng), ring[i], ring[(i + 1) % len(ring)], kx, ky)
               for i in range(len(ring)))


def simplify(ring: list[tuple[float, float]], tol_deg: float) -> list[tuple[float, float]]:
    """Douglas-Peucker (iterative)."""
    if len(ring) < 4:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop()
        dmax, idx = 0.0, -1
        for i in range(a + 1, b):
            d = _perp(ring[i], ring[a], ring[b])
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol_deg and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(ring, keep) if k]


def fetch_lake(key: str, lake: dict) -> dict | None:
    lat, lng = lake["lat"], lake["lng"]
    acres = lake.get("area_acres") or 0
    radius = 4000 if acres < 5000 else 12000
    data = _get(_query(lat, lng, radius))
    # A candidate is relevant if it contains the point or its shore is within
    # 800 m. Among relevant rings take the largest — a lake beats the pond the
    # point happens to sit in, and an 18 km-away lake can never win.
    best, best_area = None, 0.0
    for el in data.get("elements", []):
        for ring in _rings(el):
            if not (_contains(ring, lat, lng) or _dist_to_ring(ring, lat, lng) <= 800):
                continue
            a = _area_m2(ring)
            if a > best_area:
                best, best_area = ring, a
    if best is None:
        return None
    tol_deg = TOLERANCE_M / 111320.0
    simple = simplify(best, tol_deg)
    return dict(name=lake.get("name", key), polygon=[[round(a, 6), round(b, 6)] for a, b in simple],
                points_raw=len(best), points=len(simple),
                area_acres=round(best_area / 4046.86),
                centroid=[round(sum(a for a, _ in best) / len(best), 6),
                          round(sum(b for _, b in best) / len(best), 6)])


def run(only: str | None = None, refresh: bool = False) -> None:
    lakes = json.loads(LAKES.read_text())
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    out.setdefault("_note", ("OSM water polygons for wind-exposure (fetch direction), "
                             "simplified ~20 m. Data © OpenStreetMap contributors, ODbL."))
    out.setdefault("source", "OpenStreetMap via Overpass API")
    out.setdefault("lakes", {})
    for key, lake in lakes.items():
        if only and key != only:
            continue
        if lake.get("lat") is None:
            continue
        if key in out["lakes"] and not refresh:
            print(f"  = {key} (cached)")
            continue
        try:
            got = fetch_lake(key, lake)
        except Exception as e:
            print(f"  ✗ {key}: {e}")
            continue
        if not got:
            print(f"  ✗ {key}: no polygon found")
            continue
        out["lakes"][key] = got
        print(f"  ✓ {key}: {got['points']} pts (from {got['points_raw']}), "
              f"{got['area_acres']} acres")
        time.sleep(2)              # be polite to Overpass
    out["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(out['lakes'])} lakes)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one registry lake key")
    ap.add_argument("--refresh", action="store_true", help="re-fetch cached lakes")
    run(**vars(ap.parse_args()))
