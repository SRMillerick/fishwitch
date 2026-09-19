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


if __name__ == "__main__":
    unittest.main()
