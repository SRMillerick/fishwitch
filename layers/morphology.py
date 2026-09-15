"""Morphology layer — the lake-card factory for waters we've never met.

The market angler names any lake; fishwitch must characterize it from
public data before it can parameterize turnover, temp bias, and pattern:

  identity    Nominatim (OSM) — lat/lng, surface area from extratags
  elevation   Open-Meteo elevation API (DEM)
  depth class surface-area band → estimated mean/max depth (labeled estimate;
              refined by Quickdraw/Genesis/GLOBathy when available)
  mixing type shallow→polymictic (mixes on any front), mid→dimictic-ish,
              deep reservoir→warm-monomictic (CA pattern)
  turnover    trigger temp + surface bias derived from the above — these
              feed layers.history.infer_turnover()

Everything is an estimate and labeled as such; manual registry values always
override. This is how a lake we've never met gets a first-cut card.
"""
from __future__ import annotations
import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (fishing report tool)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
ELEVATION = "https://api.open-meteo.com/v1/elevation"


def geocode_water(name: str) -> dict | None:
    """Best water-body hit with extratags (surface area when OSM has it)."""
    try:
        r = requests.get(NOMINATIM, params=dict(
            q=name, format="json", limit=6, extratags=1,
            featuretype="water"), headers=UA, timeout=15)
        r.raise_for_status()
        results = r.json()
    except Exception:
        return None
    waters = [x for x in results
              if x.get("class") in ("water", "waterway", "natural")
              or x.get("type") in ("water", "lake", "reservoir", "pond", "river")]
    if not waters:
        return None
    x = waters[0]
    extratags = x.get("extratags", {}) or {}
    area_m2 = None
    for k in ("surface", "area"):
        try:
            area_m2 = float(str(extratags.get(k, "")).replace(",", ""))
            break
        except ValueError:
            continue
    return dict(name=x.get("name") or x["display_name"].split(",")[0],
                display=x["display_name"], lat=float(x["lat"]), lng=float(x["lon"]),
                osm_type=x.get("type", ""), area_m2=area_m2)


def elevation(lat: float, lng: float) -> float | None:
    try:
        r = requests.get(ELEVATION, params=dict(latitude=lat, longitude=lng),
                         headers=UA, timeout=10)
        return r.json()["elevation"][0]
    except Exception:
        return None


def characterize(card: dict) -> dict:
    """Add depth class, mixing type, turnover params to a geocoded card."""
    lat = card["lat"]
    area_m2 = card.get("area_m2")
    area_acres = (area_m2 / 4046.86) if area_m2 else None
    alt = card.get("alt_m") or elevation(card["lat"], card["lng"])
    card["alt_m"] = alt

    # depth class: prefer a real Wikidata depth over the area band
    wd_depth = card.pop("wikidata_depth_ft", None)
    if wd_depth:
        card["est_max_depth_ft"] = wd_depth
        card["depth_source"] = "wikidata"
    if wd_depth or card.get("depth_source") == "wikidata":
        d = wd_depth or card.get("est_max_depth_ft")
        if d < 20:
            card["depth_class"] = "shallow (<20 ft)"
        elif d < 60:
            card["depth_class"] = "mid (20-60 ft)"
        else:
            card["depth_class"] = "deep (60 ft+)"
    elif area_acres is None:
        card["depth_class"], card["est_max_depth_ft"] = "unknown", None
    elif area_acres < 200:
        card["depth_class"], card["est_max_depth_ft"] = "shallow (<20 ft)", 18
    elif area_acres < 5000:
        card["depth_class"], card["est_max_depth_ft"] = "mid (20-60 ft)", 45
    else:
        card["depth_class"], card["est_max_depth_ft"] = "deep (60 ft+)", 120
    if area_acres:
        card["area_acres"] = round(area_acres)

    # mixing type + turnover parameterization (fall-turnover focus)
    dc = card["depth_class"]
    if dc.startswith("shallow"):
        card["mixing"] = "polymictic — mixes on any strong front"
        trig, bias = 72.0, 3.0
    elif dc.startswith("deep") and lat >= 40:
        card["mixing"] = "dimictic — stratifies hard, dramatic turnover"
        trig, bias = 62.0, 6.0
    elif dc.startswith("deep"):
        card["mixing"] = "warm-monomictic — one big fall turnover"
        trig, bias = 64.0, 6.0
    else:
        card["mixing"] = "weakly stratified — fall mixing front-driven"
        trig, bias = 68.0, 4.0
    # high elevation cools faster → slightly higher trigger
    if alt and alt > 1500:
        trig += 2.0
    card["turnover"] = dict(trigger_f=round(trig, 1), surface_bias_f=bias,
                            basis="morphology estimate — override in registry")
    return card


def build_card(name: str) -> dict | None:
    card = geocode_water(name)
    if not card:
        return None
    # Wikidata enrichment: fills area/depth/elevation when OSM lacks them
    try:
        from layers import wikidata as wd
        extra = wd.lookup(name)
        if extra:
            if extra.get("area_km2") and not card.get("area_m2"):
                card["area_m2"] = extra["area_km2"] * 1e6
                card["area_source"] = "wikidata"
            if extra.get("max_depth_m"):
                card["wikidata_depth_ft"] = round(extra["max_depth_m"] * 3.281)
            if extra.get("elevation_m") and not card.get("alt_m"):
                card["alt_m"] = extra["elevation_m"]
            if extra.get("wikidata_id"):
                card["wikidata_id"] = extra["wikidata_id"]
    except Exception:
        pass
    return characterize(card)
