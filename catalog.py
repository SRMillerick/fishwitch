#!/usr/bin/env python3
"""Catalog tier — the cold water inventory behind the Featured registry.

`COVERAGE.md` phase 3: Featured waters are hand-sourced; the Catalog is the
machine inventory (USGS GNIS names joined with the CDFW stocking export). This
module owns two things:

  * The **data-threshold rule**. A catalog water may be indexed only when its
    coordinates are shoreline-verified, its species are sourced beyond the
    CDFW planting row, and area/depth exist. Until then it is a human-only
    "run a report" CTA — no page, no sitemap, no weather compute.
  * **On-demand matching**. `match_by_point()` resolves "my lake isn't listed"
    to the nearest inventory name for the in-memory auto-card; it never
    creates a page.

The shipped data file is `config/catalog/<ST>.json` (compact; GNIS names and
CDFW planting rows are public data). `config/candidates/` stays internal and
is only read by `tools/catalog_build.py`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config"
CAT_DIR = CONFIG / "catalog"

# Words a catalog entry may not satisfy until a real source exists.
BLOCK_COORDS = "coordinates not shoreline-verified"
BLOCK_SPECIES = "species not sourced beyond the CDFW planting row"
BLOCK_AREA = "no area"
BLOCK_DEPTH = "no depth"


def catalog_path(state: str) -> Path:
    return CAT_DIR / f"{state.upper()}.json"


_CACHE: dict[str, tuple[float, list[dict]]] = {}


def load_catalog(state: str = "CA") -> list[dict]:
    p = catalog_path(state)
    if not p.exists():
        return []
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    waters = d.get("waters", []) if isinstance(d, dict) else (d or [])
    _CACHE[str(p)] = (mtime, waters)
    return waters


def states() -> list[str]:
    if not CAT_DIR.exists():
        return []
    return sorted(p.stem.upper() for p in CAT_DIR.glob("*.json"))


def threshold(entry: dict) -> tuple[bool, list[str]]:
    """The index rule in one place. Returns (indexable, blockers)."""
    blockers = []
    if not entry.get("coords_verified"):
        blockers.append(BLOCK_COORDS)
    if not entry.get("species_sourced"):
        blockers.append(BLOCK_SPECIES)
    if not (entry.get("area_acres") or entry.get("area_m2")):
        blockers.append(BLOCK_AREA)
    if not (entry.get("est_max_depth_ft") or entry.get("depth_class")):
        blockers.append(BLOCK_DEPTH)
    return not blockers, blockers


def annotate(entry: dict) -> dict:
    """Stamp `index` + `index_blockers` on a catalog entry (in place)."""
    ok, blockers = threshold(entry)
    entry["index"] = ok
    entry["index_blockers"] = blockers
    return entry


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def match_by_point(lat: float, lng: float, max_km: float = 8.0,
                   catalog: list[dict] | None = None) -> dict | None:
    """Nearest inventory water to a dropped pin. Stocked/lake-like entries win
    ties within 250 m so a reservoir doesn't lose its name to a farm pond."""
    entries = catalog if catalog is not None else load_catalog("CA")
    best, best_entry, best_d = None, None, float("inf")
    for e in entries:
        if e.get("lat") is None or e.get("lng") is None:
            continue
        d = _haversine_km(lat, lng, e["lat"], e["lng"])
        if d > max_km:
            continue
        rank = (0 if e.get("stocked") else 1, 0 if e.get("lake_like") else 1, d)
        if best is None or rank < best:
            best, best_entry, best_d = rank, e, d
            if d <= 0.25 and e.get("stocked") and e.get("lake_like"):
                break
    return best_entry


def match_by_name(name: str, catalog: list[dict] | None = None) -> dict | None:
    """Exact (case-insensitive) inventory name match, preferring stocked lakes."""
    key = " ".join((name or "").lower().split())
    if not key:
        return None
    entries = catalog if catalog is not None else load_catalog("CA")
    hits = [e for e in entries if " ".join((e.get("name") or "").lower().split()) == key]
    if not hits:
        return None
    hits.sort(key=lambda e: (0 if e.get("stocked") else 1, 0 if e.get("lake_like") else 1,
                             e.get("nearest_covered_km") if e.get("nearest_covered_km") is not None else 1e9))
    return hits[0]


def summary(state: str = "CA") -> dict:
    """Counts for the state hubs: inventory, stocked, lake-like, indexable."""
    entries = load_catalog(state)
    return dict(
        state=state.upper(),
        inventory=len(entries),
        stocked=sum(1 for e in entries if e.get("stocked")),
        lake_like=sum(1 for e in entries if e.get("lake_like")),
        featured=sum(1 for e in entries if e.get("featured")),
        indexable=sum(1 for e in entries if e.get("index")),
    )
