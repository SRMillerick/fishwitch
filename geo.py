"""Geocoding + timezone resolution.

Birth places -> Open-Meteo geocoding API (cities, returns timezone).
Bodies of water -> Nominatim (OSM), then timezone resolved from Open-Meteo.
Everything degrades gracefully offline: callers can always pass lat/lng/tz.
"""
from __future__ import annotations
import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (local fishing report tool)"}
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode_city(name: str) -> list[dict]:
    """City/town lookup for birth places. Returns dicts with lat/lng/tz."""
    try:
        r = requests.get(GEO_URL, params={"name": name, "count": 5,
                                          "language": "en", "format": "json"},
                         headers=UA, timeout=10)
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for res in r.json().get("results", []) or []:
        out.append(dict(
            name=res.get("name", "?"),
            region=res.get("admin1", ""),
            country=res.get("country", ""),
            lat=res["latitude"], lng=res["longitude"],
            tz=res.get("timezone", ""),
        ))
    return out


def geocode_waterbody(name: str) -> list[dict]:
    """Lake/river lookup via Nominatim. Prefers water-type results."""
    try:
        r = requests.get(NOMINATIM, params={"q": name, "format": "json",
                                            "limit": 8, "featuretype": "water"},
                         headers=UA, timeout=10)
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for res in r.json():
        out.append(dict(
            name=res.get("name", "") or res.get("display_name", "?").split(",")[0],
            display=res.get("display_name", "?"),
            lat=float(res["lat"]), lng=float(res["lon"]),
            type=res.get("type", ""), klass=res.get("class", ""),
        ))
    # water features first, then alphabetical stability
    out.sort(key=lambda d: (not (d["klass"] in ("water", "waterway", "natural")
                                 or d["type"] in ("water", "lake", "reservoir",
                                                  "pond", "river")), d["name"]))
    return out


def tz_for(lat: float, lng: float) -> tuple[str, int]:
    """Resolve timezone name + utc offset seconds via Open-Meteo."""
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": lat, "longitude": lng,
                                 "current": "temperature_2m", "timezone": "auto"},
                         headers=UA, timeout=10)
        r.raise_for_status()
        j = r.json()
        return j.get("timezone", "UTC"), int(j.get("utc_offset_seconds", 0))
    except Exception:
        return "UTC", 0
