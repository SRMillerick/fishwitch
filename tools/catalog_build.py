#!/usr/bin/env python3
"""Build the shipped catalog file from the internal ranked candidate list.

    ~/.astro-venv/bin/python tools/catalog_build.py --state CA

Reads `config/candidates/<ST>_ranked.json` (internal — GNIS inventory joined
with the CDFW stocking export and Census reach), stamps every entry with the
data-threshold verdict (`catalog.annotate`), flags waters already in the
Featured registry, and writes the compact `config/catalog/<ST>.json` that
ships with the app. The build is deterministic; re-run after a ranker refresh.

The shipped file is what the state hubs count and what the on-demand report
uses to name a dropped pin. It is *not* a page generator: catalog entries have
no routes and never enter the sitemap unless the threshold passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402

CAND = ROOT / "config" / "candidates"
LAKES = ROOT / "config" / "lakes.json"


def _registry_index() -> dict:
    reg = json.loads(LAKES.read_text())
    idx = {}
    for key, v in reg.items():
        idx[(v.get("name", "").lower(), (v.get("county") or "").lower())] = key
    return idx


def build(state: str) -> dict:
    ranked = json.loads((CAND / f"{state.upper()}_ranked.json").read_text())
    reg = _registry_index()
    waters = []
    for r in ranked.get("ranked", []):
        key = reg.get((r["name"].lower(), (r.get("county") or "").lower()))
        entry = dict(
            name=r["name"], county=r.get("county"), lat=r.get("lat"), lng=r.get("lng"),
            feature_class=r.get("feature_class"), lake_like=bool(r.get("lake_like")),
            stocked=bool(r.get("stocked")), plants=r.get("plants", 0),
            weeks=r.get("weeks", 0), species=list(r.get("species") or []),
            last_plant=r.get("last_plant"),
            nearest_covered_km=r.get("nearest_covered_km"), score=r.get("score"),
            featured=key is not None, registry_id=key,
            # Threshold inputs. Catalog coordinates are GNIS points; they are
            # not shoreline-verified until the containing-ring check passes,
            # and catalog species are only the CDFW planting row until an
            # agency/Wikipedia source is attached. Both stay false here on
            # purpose — that is what keeps catalog pages out of the index.
            coords_verified=False,
            species_sourced=bool(r.get("species")),
        )
        catalog.annotate(entry)
        waters.append(entry)
    waters.sort(key=lambda e: (-(e.get("score") or 0), e.get("name") or ""))
    out = dict(
        state=state.upper(),
        generated_from=f"config/candidates/{state.upper()}_ranked.json",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        threshold=("index only when coords_verified and species_sourced and area/depth exist"),
        counts=dict(
            inventory=len(waters),
            stocked=sum(1 for e in waters if e["stocked"]),
            lake_like=sum(1 for e in waters if e["lake_like"]),
            featured=sum(1 for e in waters if e["featured"]),
            indexable=sum(1 for e in waters if e["index"]),
        ),
        waters=waters,
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="CA")
    args = ap.parse_args()
    out = build(args.state)
    dest = catalog.catalog_path(args.state)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1) + "\n")
    c = out["counts"]
    print(f"wrote {dest} ({dest.stat().st_size/1e6:.2f} MB)")
    print(f"  inventory {c['inventory']} · stocked {c['stocked']} · lake-like {c['lake_like']} "
          f"· featured {c['featured']} · indexable {c['indexable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
