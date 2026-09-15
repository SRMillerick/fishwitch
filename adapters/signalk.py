"""Signal K — the open marine data server. The clean way to mesh with
OpenCPN, Signal K dashboards, and anything else on the boat network.

Run `fishwitch mesh` (future) on a Pi aboard: consume NMEA -> Signal K deltas,
and push fishwitch prime-window waypoints back to the chartplotter.
"""
from __future__ import annotations
import requests


class SignalK:
    def __init__(self, base="http://localhost:3000", token: str | None = None):
        self.base = base.rstrip("/")
        self.h = {"Authorization": f"JWT {token}"} if token else {}

    def get(self, path: str):
        r = requests.get(f"{self.base}{path}", headers=self.h, timeout=5)
        r.raise_for_status()
        return r.json()

    def get_self(self):
        return self.get("/signalk/v1/api/vessels/self")

    def get_water_temp(self):
        try:
            return self.get("/signalk/v1/api/vessels/self/environment/water/temperature")["value"]
        except Exception:
            return None

    def put(self, path: str, value):
        r = requests.put(f"{self.base}{path}", headers={**self.h, "Content-Type": "application/json"},
                         json=value, timeout=5)
        r.raise_for_status()
        return r

    def put_waypoint(self, name: str, lat: float, lon: float, desc: str = ""):
        """Add a waypoint visible in connected chartplotters (OpenCPN etc)."""
        return self.put("/signalk/v1/api/resources/waypoints/fishwitch/"
                        + name.replace(" ", "-").lower(),
                        dict(position=dict(latitude=lat, longitude=lon),
                             name=name, description=desc,
                             featureType="Waypoint"))
