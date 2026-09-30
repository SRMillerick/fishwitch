#!/usr/bin/env python3
"""Research dossier for a Featured batch: card + Wikipedia + CDFW per water.

For each named candidate (looked up by name+county in
config/candidates/<ST>_ranked.json) it builds the morphology card, fetches the
best Wikipedia article and extracts infobox area/depth/elevation + fish
mentions, and joins the CDFW planting record. Prints a digest and writes
/tmp/<state>_dossier.json. Read-only; nothing enters the registry here.

    ~/.astro-venv/bin/python tools/onboard_batch.py --state CA \
        --names "Sandy Wool Lake|Jenkinson Lake|..."
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from layers.morphology import characterize, elevation  # noqa: E402

RANKED = ROOT / "config" / "candidates"
WIKI = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "baromoon-coverage/1.0 (water dossier)"}

# specific patterns first; generic bass/trout only when no specific form matched
FISH_PATTERNS = [
    (r"\blargemouth bass\b|\bblack bass\b", "largemouth bass"),
    (r"\bsmallmouth bass\b", "smallmouth bass"),
    (r"\bstriped bass\b|\bstriper\b", "striped bass"),
    (r"\bspotted bass\b", "spotted bass"),
    (r"\brainbow trout\b", "rainbow trout"),
    (r"\bbrown trout\b", "brown trout"),
    (r"\blake trout\b", "lake trout"),
    (r"\bkokanee\b", "kokanee"),
    (r"\bchannel cat\b|\bchannel catfish\b", "channel catfish"),
    (r"\bcrappie\b", "crappie"),
    (r"\bbluegill\b", "bluegill"),
    (r"\bsunfish\b", "sunfish"),
    (r"\bperch\b", "perch"),
    (r"\bcarp\b", "carp"),
    (r"\bshad\b", "shad"),
    (r"\bsalmon\b", "salmon"),
    (r"\bsturgeon\b", "sturgeon"),
    (r"\bcatfish\b", "catfish"),
    (r"\btrout\b", "trout"),
    (r"\bbass\b", "bass"),
]


def _num(s: str) -> float:
    return float(s.replace(",", "").strip())


def _to_acres(value: float, unit: str) -> float | None:
    u = unit.lower()
    if u.startswith("acre"):
        return value
    if "sq mi" in u or "sqmi" in u or u.startswith("mi"):
        return value * 640
    if "hectare" in u or u == "ha":
        return value * 2.47105
    if "km2" in u or "sq km" in u or u.startswith("km"):
        return value * 247.105
    return None


def _to_ft(value: float, unit: str) -> float | None:
    u = unit.lower()
    if u.startswith("ft") or "feet" in u or "foot" in u:
        return value
    if u.startswith("m") and "mi" not in u:
        return value * 3.28084
    return None


def _field(wikitext: str, keys: tuple[str, ...]):
    for key in keys:
        m = re.search(r"\n\s*\|\s*" + key.replace("-", "[-_]") +
                      r"\s*=\s*(.*?)(?=\n\s*\||\n\s*\}\})", wikitext, re.S | re.I)
        if not m:
            continue
        raw = re.sub(r"\s+", " ", m.group(1)).strip()
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
        if not raw or "VALUE" in raw:
            continue
        cm = re.search(r"\{\{[Cc]onvert\|([\d,.]+)\|([A-Za-z0-9 .]+)", raw)
        if cm:
            return _num(cm.group(1)), cm.group(2)
    return None


def _species(wikitext: str) -> list[str]:
    low = wikitext.lower()
    found, specific = [], set()
    for pat, canon in FISH_PATTERNS:
        if re.search(pat, low):
            if canon in ("bass", "trout") and any(
                    s.endswith(canon) and s != canon for s in specific):
                continue
            if canon not in found:
                found.append(canon)
                specific.add(canon)
    return found


def _parse_wikitext(wt: str) -> dict:
    out = dict(area_acres=None, depth_ft=None, elevation_ft=None, species=[])
    a = _field(wt, ("surface_area", "area"))
    if a:
        ac = _to_acres(*a)
        if ac:
            out["area_acres"] = round(ac)
    d = _field(wt, ("max-depth", "max_depth", "depth"))
    if d:
        ft = _to_ft(*d)
        if ft:
            out["depth_ft"] = round(ft)
    e = _field(wt, ("elevation",))
    if e:
        ft = _to_ft(*e)
        if ft:
            out["elevation_ft"] = round(ft)
    out["species"] = _species(wt)
    return out


def _page_by_title(title: str):
    try:
        r = requests.get(WIKI, params=dict(action="query", titles=title, redirects="1",
                                           prop="revisions", rvprop="content",
                                           rvslots="main", format="json", formatversion="2"),
                         headers=UA, timeout=25)
        p = r.json()["query"]["pages"][0]
        if p.get("missing"):
            return None
        return p, p["revisions"][0]["slots"]["main"]["content"]
    except Exception:
        return None


def _api(params: dict, attempts: int = 4) -> dict:
    """Wikipedia API GET with backoff — the dossier bursts get throttled."""
    for i in range(attempts):
        try:
            r = requests.get(WIKI, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1.5 * (i + 1))
    return {}


def wiki_lookup(name: str) -> dict:
    """One batched title query per lake (redirects included), then a constrained
    search fallback. Picks the best hit by exact-title + infobox/species score."""
    out = dict(title=None, area_acres=None, depth_ft=None, elevation_ft=None,
               species=[], found=False)
    stems = [name, f"{name} (California)", f"{name} (lake)", f"{name} Reservoir",
             f"{name} (reservoir)"]
    d = _api(dict(action="query", titles="|".join(stems), redirects="1",
                  prop="revisions", rvprop="content", rvslots="main",
                  format="json", formatversion="2"))
    best = None
    for p in d.get("query", {}).get("pages", []):
        if p.get("missing"):
            continue
        title = p.get("title") or ""
        if name.lower().split()[0] not in title.lower():
            continue
        try:
            wt = p["revisions"][0]["slots"]["main"]["content"]
        except Exception:
            continue
        parsed = _parse_wikitext(wt)
        score = (3 if title.lower() == name.lower() else 0)
        score += (1 if parsed["area_acres"] else 0)
        score += (1 if parsed["depth_ft"] else 0)
        score += min(len(parsed["species"]), 2)
        if best is None or score > best[0]:
            best = (score, title, parsed)
    if best:
        out.update(title=best[1], found=True, **best[2])
        return out
    d = _api(dict(action="query", list="search", srsearch=f"{name} lake California",
                  srlimit=5, format="json", formatversion="2"))
    for hit in d.get("query", {}).get("search", []):
        title = hit["title"]
        if "list of" in title.lower() or name.lower().split()[0] not in title.lower():
            continue
        page = _page_by_title(title)
        if page:
            p, wt = page
            out.update(title=p.get("title") or title, found=True, **_parse_wikitext(wt))
            return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="CA")
    ap.add_argument("--names", required=True, help="pipe-separated water names")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ranked = json.loads((RANKED / f"{args.state}_ranked.json").read_text())
    index = {}
    for r in ranked["ranked"]:
        index.setdefault(r["name"].lower(), []).append(r)

    dossier = []
    for raw in args.names.split("|"):
        name = raw.strip()
        if not name:
            continue
        matches = index.get(name.lower(), [])
        if not matches:
            dossier.append(dict(name=name, error="not in ranked candidates"))
            print(f"!! {name}: no ranked candidate match")
            continue
        cand = matches[0]
        time.sleep(1.2)
        wk = wiki_lookup(name)
        # GNIS coordinates are the inventory truth; the DEM is a sanity-check,
        # not a replacement. Wikipedia elevation wins when present (the DEM has
        # produced sea-level readings for mountain lakes).
        card = dict(name=name, display=f"{name}, {cand['county']} County, California",
                    lat=cand["lat"], lng=cand["lng"], osm_type="")
        dem = elevation(cand["lat"], cand["lng"])
        card["alt_m"] = (round(wk["elevation_ft"] / 3.28084) if wk["elevation_ft"]
                         else (round(dem) if dem is not None else None))
        if wk["area_acres"]:
            card["area_acres"] = wk["area_acres"]
            card["area_m2"] = round(wk["area_acres"] * 4046.86)
        card = characterize(card)
        if wk["depth_ft"]:
            card["est_max_depth_ft"] = wk["depth_ft"]
        entry = dict(
            name=name, county=cand["county"], feature_class=cand["feature_class"],
            lat=cand["lat"], lng=cand["lng"], county_pop=cand["county_pop"],
            dem_m=round(dem) if dem is not None else None,
            cdfw=dict(plants=cand["plants"], weeks=cand["weeks"],
                      species=cand["species"], last=cand["last_plant"]),
            wiki=wk, card=card,
        )
        dossier.append(entry)
        geo = f"{card['lat']:.4f},{card['lng']:.4f} alt={card.get('alt_m')}m (dem={entry['dem_m']})"
        print(f"== {name} ({cand['county']}) | {geo}")
        print(f"   card: area={card.get('area_acres')} class={card.get('depth_class')} "
              f"est={card.get('est_max_depth_ft')}")
        print(f"   wiki [{wk['title']}]: area={wk['area_acres']} depth={wk['depth_ft']} "
              f"elev={wk['elevation_ft']} species={wk['species']}")
        print(f"   cdfw: plants={cand['plants']} wks={cand['weeks']} species={cand['species']}")

    out = Path(args.out or f"/tmp/{args.state}_dossier.json")
    out.write_text(json.dumps(dossier, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
