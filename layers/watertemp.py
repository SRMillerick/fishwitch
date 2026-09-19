"""Real water temperature — USGS NWIS where stations exist.

Most small private lakes (like HVL) have no gauge; big public waters do.
Search: lake/stream sites with a water-temp sensor (parameterCd 00010) in a
bounding box; fetch the latest instantaneous value.

Two hard rules learned the hard way (2026-09-19):
  - a **distance guard** — a station 50 km down the valley is a different
    thermal regime, and silently substituting it is worse than an honest
    estimate. Stations beyond `MAX_KM` are ignored.
  - **lake sites first** — `site_tp_cd == "LK"` beats a closer stream.
Results (including None) are cached for 30 minutes so a report render never
hammers NWIS. Returns None gracefully — the report then says "estimated".

CDEC was surveyed as a second source (2026-09-19): its realtime sensor 25 is a
river/stream network; the checked reservoir stations (CLE, LSO, BER, FOL, ORO,
NML, DNP, MCO, CAM, SHA) publish no water-temp sensor, and no sensor-25 station
sits near a registry lake. It is therefore not wired in — there is nothing to
read for these waters.
"""
from __future__ import annotations
import math
import time

import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (fishing report tool)"}
MAX_KM = 30.0
CACHE_TTL = 1800  # seconds
_cache: dict[tuple, tuple[float, tuple | None]] = {}


def _dist_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a_lat, a_lng, b_lat, b_lng))
    return 6371 * math.acos(min(1, math.sin(la1) * math.sin(la2)
                                + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1)))


def find_stations(lat: float, lng: float, radius_deg: float = 0.5) -> list[dict]:
    b = f"{lng-radius_deg},{lat-radius_deg/2},{lng+radius_deg},{lat+radius_deg/2}"
    r = requests.get("https://waterservices.usgs.gov/nwis/site/",
                     params=dict(format="rdb", bBox=b, parameterCd="00010",
                                 siteOutput="expanded"),
                     headers=UA, timeout=20)
    r.raise_for_status()
    out = []
    cols = []
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("agency_cd"):
            cols = line.split("\t")
            continue
        if not cols:
            continue
        row = dict(zip(cols, line.split("\t")))
        try:
            out.append(dict(no=row["site_no"], name=row["station_nm"],
                            lat=float(row["dec_lat_va"]), lng=float(row["dec_long_va"]),
                            type=row.get("site_tp_cd", "")))
        except (KeyError, ValueError):
            continue
    return out


def latest_temp(site_no: str) -> float | None:
    """Latest instantaneous water temp in °F."""
    r = requests.get("https://waterservices.usgs.gov/nwis/iv/",
                     params=dict(format="json", sites=site_no, parameterCd="00010"),
                     headers=UA, timeout=20)
    try:
        vals = r.json()["value"]["timeSeries"][0]["values"][0]["value"]
        v = float(vals[0]["value"])
        return v * 9 / 5 + 32
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def nearest_water_temp(lat: float, lng: float,
                       max_km: float = MAX_KM) -> tuple[str, float, str] | None:
    """(station_name, temp_f, source_label) or None. Guarded + cached."""
    key = (round(lat, 3), round(lng, 3), max_km)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    result = None
    try:
        st = [s for s in find_stations(lat, lng)
              if _dist_km(lat, lng, s["lat"], s["lng"]) <= max_km]
        # lake stations first, then nearest — never a distant river
        st.sort(key=lambda s: (s.get("type") != "LK", _dist_km(lat, lng, s["lat"], s["lng"])))
        for s in st[:3]:
            t = latest_temp(s["no"])
            if t is not None:
                result = (s["name"], t, "USGS gauge")
                break
    except Exception:
        result = None
    _cache[key] = (time.time(), result)
    return result
