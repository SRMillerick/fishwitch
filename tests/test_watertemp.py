"""Water-temp layer: parsing, distance guard, lake-site preference, cache."""
import unittest
from unittest import mock

import layers.watertemp as wt

HDR = "agency_cd\tsite_no\tstation_nm\tsite_tp_cd\tdec_lat_va\tdec_long_va\n"
# search box centered on Berryessa-ish (38.51, -122.23)
RDB = (HDR
       + "USGS\t900\tFAR RIVER\tST\t40.00\t-122.00\n"          # ~165 km — rejected
       + "USGS\t901\tCLOSE CREEK\tST\t38.505\t-122.225\n"        # closest, stream
       + "USGS\t902\tNEAR LAKE\tLK\t38.515\t-122.235\n")         # lake site


class FakeResp:
    def __init__(self, text="", payload=None):
        self.text, self._payload = text, payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_get(pt, calls):
    def _get(url, params=None, **kw):
        calls.append(url)
        if "nwis/site" in url:
            return FakeResp(text=RDB)
        if "nwis/iv" in url:
            pt.append(params.get("sites"))
            return FakeResp(payload={"value": {"timeSeries": [{"values": [
                {"value": [{"value": "20"}]}]}]}})   # 20 °C = 68 °F
        raise AssertionError(url)
    return _get


class WaterTempTest(unittest.TestCase):
    def setUp(self):
        wt._cache.clear()

    def test_distance(self):
        self.assertAlmostEqual(wt._dist_km(38.5, -122.2, 38.5, -122.2), 0, places=3)
        self.assertAlmostEqual(wt._dist_km(38.0, -122.0, 39.0, -122.0), 111.2, delta=2)

    def test_parse_stations(self):
        calls = []
        with mock.patch.object(wt.requests, "get", make_get([], calls)):
            st = wt.find_stations(38.51, -122.23)
        self.assertEqual(len(st), 3)
        self.assertEqual(st[2]["type"], "LK")

    def test_distance_guard_rejects_far_station(self):
        calls = []
        far_only = HDR + "USGS\t900\tFAR RIVER\tST\t40.00\t-122.00\n"
        with mock.patch.object(wt.requests, "get",
                               lambda url, **kw: FakeResp(text=far_only)):
            self.assertIsNone(wt.nearest_water_temp(38.51, -122.23))

    def test_prefers_lake_site_and_converts(self):
        calls, queried = [], []
        with mock.patch.object(wt.requests, "get", make_get(queried, calls)):
            got = wt.nearest_water_temp(38.51, -122.23)
        self.assertEqual(got, ("NEAR LAKE", 68.0, "USGS gauge"))
        self.assertEqual(queried[0], "902")     # lake site queried before the closer stream
        self.assertTrue(any("nwis/site" in c for c in calls))

    def test_cache_avoids_second_fetch(self):
        calls = []
        with mock.patch.object(wt.requests, "get", make_get([], calls)):
            a = wt.nearest_water_temp(38.51, -122.23)
            n = len(calls)
            b = wt.nearest_water_temp(38.51, -122.23)
        self.assertEqual(a, b)
        self.assertEqual(len(calls), n)         # served from cache


if __name__ == "__main__":
    unittest.main()
