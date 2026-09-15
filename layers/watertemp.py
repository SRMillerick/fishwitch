"""Real water temperature — USGS NWIS where stations exist.

Most small private lakes (like HVL) have no gauge; big public waters do.
Search: lake/stream sites with water-temp sensor (parameterCd 00010) in a
bounding box; fetch latest instantaneous value. Returns None gracefully so
the report falls back to the air-temp estimate.
"""
from __future__ import annotations
import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (fishing report tool)"}


def find_stations(lat: float, lng: float, radius_deg: float = 0.5) -> list[dict]:
    b = f"{lng-radius},{lat-radius/2},{lng+radius},{lat+radius/2}"
    r = requests.get("https://waterservices.usgs.gov/nwis/site/",
                     params=dict(format="rdb", bBox=b, parameterCd="00010",
                                 siteOutput="expanded"),
                     headers=UA, timeout=15)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("agency_cd"):
            cols = line.split("\t")
            continue
        row = dict(zip(cols, line.split("\t")))
        try:
            out.append(dict(no=row["site_no"], name=row["station_nm"],
                            lat=float(row["dec_lat_va"]), lng=float(row["dec_long_va"])))
        except (KeyError, ValueError):
            continue
    return out


def latest_temp(site_no: str) -> float | None:
    """Latest instantaneous water temp in °F."""
    r = requests.get("https://waterservices.usgs.gov/nwis/iv/",
                     params=dict(format="json", sites=site_no, parameterCd="00010"),
                     headers=UA, timeout=15)
    try:
        vals = r.json()["value"]["timeSeries"][0]["values"][0]["value"]
        v = float(vals[0]["value"])
        return v * 9 / 5 + 32
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def nearest_water_temp(lat: float, lng: float) -> tuple[str, float] | None:
    """(station_name, temp_f) or None."""
    try:
        st = find_stations(lat, lng)
    except Exception:
        return None
    if not st:
        return None
    st.sort(key=lambda s: (s["lat"] - lat) ** 2 + (s["lng"] - lng) ** 2)
    for s in st[:3]:
        t = latest_temp(s["no"])
        if t is not None:
            return s["name"], t
    return None
