"""Wind exposure — synthetic geometry so the expected answer is exact."""
import unittest

from layers import shoreline

# ~1.1 km square: [lat, lng]
SQ = [[38.0, -122.0], [38.0, -122.00625], [38.0, -122.0125], [38.005, -122.0125],
      [38.01, -122.0125], [38.01, -122.00625], [38.01, -122.0], [38.005, -122.0]]


class ShorelineTest(unittest.TestCase):
    def setUp(self):
        shoreline._lakes = {"test-lake": {"polygon": SQ}}
        shoreline._wind_cache.clear()

    def test_wind_from_north_stacks_the_south_shore(self):
        r = shoreline.wind_shore("test-lake", 0)
        self.assertEqual(r["from_sector"], "N")
        self.assertEqual(r["stacked"], "S")
        self.assertGreater(r["stacked_fetch_m"], 1000)     # full lake width
        self.assertIn(r["lee"], ("N", "NE", "NW"))
        self.assertLess(r["lee_fetch_m"], 120)

    def test_wind_from_west_stacks_the_east_shore(self):
        r = shoreline.wind_shore("test-lake", 270)
        self.assertEqual(r["from_sector"], "W")
        self.assertEqual(r["stacked"], "E")
        self.assertGreater(r["stacked_fetch_m"], 1000)

    def test_results_are_cached(self):
        a = shoreline.wind_shore("test-lake", 180)
        b = shoreline.wind_shore("test-lake", 180)
        self.assertIs(a, b)

    def test_null_safety(self):
        self.assertIsNone(shoreline.wind_shore("missing-lake", 0))
        self.assertIsNone(shoreline.wind_shore("test-lake", None))


class AdapterRingPickTest(unittest.TestCase):
    """The shoreline adapter must not let a nearby bigger lake steal the
    registry point's own polygon (Fain Lake vs Mesa Reservoir, 2026-09-20)."""

    @staticmethod
    def _way(ring):
        return {"type": "way",
                "geometry": [{"lat": p[0], "lon": p[1]} for p in ring]}

    def test_containing_ring_wins_over_nearby_bigger_ring(self):
        from adapters import shorelines as sh
        small = [[34.5750, -112.3524], [34.5750, -112.3522],
                 [34.5752, -112.3522], [34.5752, -112.3524]]   # Fain Lake
        big = [[34.5750, -112.3470], [34.5750, -112.3420],
               [34.5800, -112.3420], [34.5800, -112.3470]]   # Mesa, ~500 m E
        ring = sh._pick_ring([self._way(big), self._way(small)], 34.5751, -112.3523)
        self.assertEqual(ring, [tuple(p) for p in small])

    def test_largest_containing_ring_wins(self):
        from adapters import shorelines as sh
        pond = [[34.5750, -112.3524], [34.5750, -112.3522],
                [34.5752, -112.3522], [34.5752, -112.3524]]
        lake = [[34.5700, -112.3600], [34.5700, -112.3400],
                [34.5900, -112.3400], [34.5900, -112.3600]]
        ring = sh._pick_ring([self._way(pond), self._way(lake)], 34.5751, -112.3523)
        self.assertEqual(ring, [tuple(p) for p in lake])


if __name__ == "__main__":
    unittest.main()
