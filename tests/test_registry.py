"""Registry completeness — the full-card audit must stay green.

The 2026-10-01 cleanup completed the 10 legacy cards (region, area, depth,
morphology, source strings). This locks it: every registry water must carry a
region, species, county, area, depth class + max-depth estimate, mixing, a
turnover basis, and coords/area/depth source strings; and every point must sit
inside its OSM shoreline ring. Mirrors tools/audit_lakes.py so a field can never
silently regress again.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKES = json.loads((ROOT / "config" / "lakes.json").read_text())
SHORES = json.loads((ROOT / "config" / "shorelines.json").read_text()).get("lakes", {})

REQUIRED = ("name", "lat", "lng", "species", "county")
FULL = ("region", "mixing", "depth_class", "est_max_depth_ft")
SOURCES = ("coords_source", "area_source", "depth_source")


def _point_in_ring(lat, lng, ring):
    x, y, inside = lng, lat, False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][1], ring[i][0]
        xj, yj = ring[j][1], ring[j][0]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _nearest_vertex_m(lat, lng, ring):
    import math
    best = float("inf")
    for plat, plng in ring:
        dlat = math.radians(plat - lat)
        dlng = math.radians(plng - lng)
        h = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(plat))
             * math.sin(dlng / 2) ** 2)
        best = min(best, 6371000 * 2 * math.asin(min(1, math.sqrt(h))))
    return best


class TestRegistryCards(unittest.TestCase):
    def test_every_water_has_a_complete_card(self):
        for key, v in LAKES.items():
            with self.subTest(lake=key):
                for f in REQUIRED + FULL:
                    self.assertNotIn(v.get(f), (None, "", []), f"{key} missing {f}")
                self.assertTrue(v.get("area_acres") or v.get("area_m2"),
                                f"{key} missing area")
                self.assertTrue((v.get("turnover") or {}).get("basis"),
                                f"{key} missing turnover.basis")
                for f in SOURCES:
                    self.assertTrue(v.get(f), f"{key} missing {f}")

    def test_every_water_has_a_shoreline_and_point_inside(self):
        for key, v in LAKES.items():
            ring = (SHORES.get(key) or {}).get("polygon")
            with self.subTest(lake=key):
                self.assertTrue(ring, f"{key} has no shoreline")
                # mirrors tools/audit_lakes.py: inside the ring, or a genuine
                # shore point within 50 m (never an OUT point)
                self.assertTrue(
                    _point_in_ring(v["lat"], v["lng"], ring)
                    or _nearest_vertex_m(v["lat"], v["lng"], ring) <= 50,
                    f"{key} point outside its shoreline ring")


if __name__ == "__main__":
    unittest.main()
