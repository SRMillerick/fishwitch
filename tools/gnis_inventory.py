#!/usr/bin/env python3
"""Build a state candidate inventory from USGS GNIS domestic names.

Source: The National Map staged products, DomesticNames_<ST>_Text.zip (USGS;
US government data). Filters to lake/reservoir/pond feature classes, dedupes
by (name, county), excludes waters already in config/lakes.json (normalized
name match or within --radius-m), and writes config/candidates/<ST>.json for
the Featured-onboarding queue.

    ~/.astro-venv/bin/python tools/gnis_inventory.py --state CA
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "lakes.json"
OUTDIR = ROOT / "config" / "candidates"
CACHE = Path("/tmp") / "fishwitch-gnis"
BASE = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
        "DomesticNames")
UA = {"User-Agent": "baromoon-coverage/1.0 (water inventory; USGS GNIS)"}
DEFAULT_CLASSES = ("Lake", "Reservoir", "Pond")


def _download(state: str) -> tuple[str, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE / f"DomesticNames_{state}_Text.zip"
    url = f"{BASE}/DomesticNames_{state}_Text.zip"
    if not zip_path.exists():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            zip_path.write_bytes(r.read())
    with zipfile.ZipFile(io.BytesIO(zip_path.read_bytes())) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        text = zf.read(name).decode("utf-8-sig", errors="replace")
    return text, url


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="CA", help="USPS abbreviation (default CA)")
    ap.add_argument("--classes", default=",".join(DEFAULT_CLASSES),
                    help="GNIS feature classes to keep")
    ap.add_argument("--radius-m", type=float, default=1500.0,
                    help="exclude candidates this close to a registry water")
    args = ap.parse_args()

    classes = tuple(c.strip() for c in args.classes.split(",") if c.strip())
    text, url = _download(args.state)
    lines = text.splitlines()
    if not lines:
        raise SystemExit("empty GNIS extract")
    header = lines[0].split("|")
    idx = {name: i for i, name in enumerate(header)}
    needed = ("feature_id", "feature_name", "feature_class", "state_name",
              "county_name", "prim_lat_dec", "prim_long_dec")
    missing = [k for k in needed if k not in idx]
    if missing:
        raise SystemExit(f"unexpected GNIS schema, missing: {missing}")

    # The extract is dominated by its own state; neighbours appear on the edges.
    mode_state = Counter(
        p[idx["state_name"]] for p in
        (ln.split("|") for ln in lines[1:]) if len(p) > idx["state_name"]).most_common(1)
    state_name = mode_state[0][0] if mode_state else args.state

    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    reg_nc = {(_norm(v.get("name")), _norm(v.get("county"))) for v in reg.values()}
    reg_pts = [(v.get("lat"), v.get("lng")) for v in reg.values()
               if v.get("lat") is not None and v.get("lng") is not None]

    seen: set[tuple[str, str]] = set()
    waters, excluded = [], []
    raw = state_rows = 0
    for line in lines[1:]:
        p = line.split("|")
        if len(p) <= idx["prim_long_dec"]:
            continue
        raw += 1
        if p[idx["state_name"]] != state_name:
            continue
        state_rows += 1
        if p[idx["feature_class"]] not in classes:
            continue
        try:
            lat, lng = float(p[idx["prim_lat_dec"]]), float(p[idx["prim_long_dec"]])
        except ValueError:
            continue
        name, county = p[idx["feature_name"]], p[idx["county_name"]]
        key = (_norm(name), county)
        if key in seen:
            continue
        seen.add(key)
        if (_norm(name), _norm(county)) in reg_nc:
            excluded.append(dict(name=name, county=county, why="name"))
            continue
        near = next((d for d in (_haversine_m((lat, lng), q) for q in reg_pts)
                     if d <= args.radius_m), None)
        if near is not None:
            excluded.append(dict(name=name, county=county, why=f"{near:.0f} m"))
            continue
        waters.append(dict(feature_id=p[idx["feature_id"]], name=name,
                           feature_class=p[idx["feature_class"]], county=county,
                           lat=round(lat, 6), lng=round(lng, 6)))

    waters.sort(key=lambda w: (w["county"], w["name"]))
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{args.state}.json"
    out.write_text(json.dumps(dict(
        state=args.state, state_name=state_name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=url, classes=list(classes), radius_m=args.radius_m,
        counts=dict(raw=raw, state_rows=state_rows, kept=len(waters),
                    excluded_registry=len(excluded)),
        waters=waters,
    ), indent=1) + "\n")

    by_class = Counter(w["feature_class"] for w in waters)
    by_county = Counter(w["county"] for w in waters)
    print(f"GNIS {state_name}: {state_rows:,} rows · {len(waters):,} candidates kept "
          f"({', '.join(f'{k}={v:,}' for k, v in by_class.most_common())})")
    print(f"excluded as already covered: {len(excluded)}")
    for e in excluded:
        print(f"  - {e['name']} ({e['county']}) [{e['why']}]")
    print("top counties: " + ", ".join(f"{k}={v}" for k, v in by_county.most_common(12)))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
