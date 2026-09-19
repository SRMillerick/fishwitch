"""Shoreline wind exposure — where the wind stacks bait.

Given a lake's cached OSM polygon (`config/shorelines.json`, fetch direction)
and a meteorological wind direction (the direction the wind blows *from*),
compute for each shoreline vertex the **upwind fetch**: the distance across
water toward the wind source. Aggregate by compass sector:

  - longest average fetch  → the **wind-stacked** (downwind) bank
  - shortest average fetch → the **lee** shore

Pure planar geometry, deterministic, no network at render time. Results are
cached per (lake, 45° sector) in-process. Data © OpenStreetMap contributors.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "config" / "shorelines.json"
SECTOR_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
MAX_POINTS = 320           # decimate big lakes for the O(V·E) ray cast

_lakes: dict | None = None
_wind_cache: dict[tuple, dict | None] = {}


def _load() -> dict:
    global _lakes
    if _lakes is None:
        try:
            _lakes = json.loads(PATH.read_text()).get("lakes", {})
        except Exception:
            _lakes = {}
    return _lakes


def polygon(lake_key: str) -> list[list[float]] | None:
    e = _load().get(lake_key)
    return e.get("polygon") if e else None


def _decimate(poly: list[list[float]], cap: int = MAX_POINTS) -> list[list[float]]:
    if len(poly) <= cap:
        return poly
    step = len(poly) / cap
    return [poly[min(len(poly) - 1, int(i * step))] for i in range(cap)]


def _project(poly: list[list[float]], lat0: float) -> list[tuple[float, float]]:
    """(x=east metres, y=north metres) plane around the lake."""
    kx = 111320 * math.cos(math.radians(lat0))
    ky = 110540
    return [(lng * kx, lat * ky) for lat, lng in poly]


def _ray_fetch_m(px: float, py: float, dx: float, dy: float,
                 ring: list[tuple[float, float]]) -> float | None:
    """Distance from (px,py) along the unit ray (dx,dy) to the ring."""
    best = None
    n = len(ring)
    for i in range(n):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - px) * ey - (ay - py) * ex) / den
        u = ((ax - px) * dy - (ay - py) * dx) / den
        if t > 1e-6 and -1e-9 <= u <= 1 + 1e-9:
            if best is None or t < best:
                best = t
    return best


def wind_shore(lake_key: str, wind_dir_deg: float | None) -> dict | None:
    """Wind source direction (0=N, 90=E) → stacked/lee shore, or None.

    `wind_dir_deg` is the meteorological *from* direction.
    """
    if wind_dir_deg is None:
        return None
    poly = polygon(lake_key)
    if not poly or len(poly) < 4:
        return None
    sector = int(round((float(wind_dir_deg) % 360) / 45)) % 8
    key = (lake_key, sector)
    if key in _wind_cache:
        return _wind_cache[key]

    pts = _decimate(poly)
    lat0 = sum(a for a, _ in pts) / len(pts)
    ring = _project(pts, lat0)
    cx = sum(x for x, _ in ring) / len(ring)
    cy = sum(y for _, y in ring) / len(ring)
    theta = math.radians(sector * 45)
    dx, dy = math.sin(theta), math.cos(theta)     # toward the wind source

    per_sector: dict[int, list[float]] = {i: [] for i in range(8)}
    for (x, y) in ring:
        f = _ray_fetch_m(x, y, dx, dy, ring)
        if f is None:
            f = 0.0      # a windward-shore vertex: no water upwind of it
        bearing = math.degrees(math.atan2(x - cx, y - cy)) % 360
        per_sector[int(round(bearing / 45)) % 8].append(f)

    means = {s: (sum(v) / len(v)) for s, v in per_sector.items() if v}
    if not means:
        _wind_cache[key] = None
        return None

    def ring_dist(a: int, b: int) -> int:
        return min((a - b) % 8, (b - a) % 8)

    # exact ties are broken toward the physically opposite sector (stacked)
    # and toward the wind source (lee), so an axis-aligned lake can't report
    # a neighbouring sector just because it came first in iteration order.
    opposite = (sector + 4) % 8
    stacked = max(means, key=lambda s: (means[s], -ring_dist(s, opposite)))
    lee = min(means, key=lambda s: (means[s], ring_dist(s, sector)))
    result = dict(
        from_sector=SECTOR_NAMES[sector], from_deg=round(float(wind_dir_deg) % 360),
        stacked=SECTOR_NAMES[stacked], stacked_fetch_m=round(means[stacked]),
        lee=SECTOR_NAMES[lee], lee_fetch_m=round(means[lee]),
        note=(f"wind from {SECTOR_NAMES[sector]} — the {SECTOR_NAMES[stacked]} shore "
              f"is wind-stacked (fetch ~{means[stacked]:.0f} m), "
              f"the {SECTOR_NAMES[lee]} shore is the lee"))
    _wind_cache[key] = result
    return result
