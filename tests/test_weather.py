"""Multi-model forecast agreement — honest uncertainty, never scoring."""
import unittest
from datetime import datetime, timedelta
from unittest import mock

import weather as wx


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def payload(temp_c=20.0, wind_kmh=10.0, cloud=0):
    """Three named models; one can be nudged to create a spread."""
    times = [f"2026-09-20T{h:02d}:00" for h in range(24)]
    h = {"time": times}
    for var, base in (("temperature_2m", temp_c), ("wind_speed_10m", wind_kmh),
                      ("cloud_cover", cloud), ("precipitation_probability", 0)):
        for m in wx.AGREE_MODELS:
            h[f"{var}_{m}"] = [base] * 24
    return {"hourly": h}


class AgreementTest(unittest.TestCase):
    def setUp(self):
        wx._AGREE_CACHE.clear()
        self.start = datetime.now() + timedelta(days=1)
        self.end = self.start + timedelta(hours=3)

    def test_perfect_agreement_is_high(self):
        with mock.patch.object(wx.requests, "get", lambda *a, **k: FakeResp(payload())):
            got = wx.model_agreement(38.8, -122.5, self.start, self.end)
        self.assertEqual(got["label"], "high")
        self.assertEqual(got["temp_spread_f"], 0.0)
        self.assertEqual(got["wind_spread_mph"], 0.0)
        self.assertIn("GFS/ECMWF/ICON", got["summary"])

    def test_wide_spread_is_low(self):
        p = payload()
        p["hourly"]["temperature_2m_icon_seamless"] = [25.0] * 24   # +5C vs others
        p["hourly"]["wind_speed_10m_icon_seamless"] = [30.0] * 24   # +20 km/h
        with mock.patch.object(wx.requests, "get", lambda *a, **k: FakeResp(p)):
            got = wx.model_agreement(38.8, -122.5, self.start, self.end)
        self.assertEqual(got["label"], "low")
        self.assertGreater(got["temp_spread_f"], 4.5)

    def test_past_sessions_short_circuit(self):
        def boom(*a, **k):
            raise AssertionError("past windows must not call the network")
        old = datetime(2020, 1, 1)
        with mock.patch.object(wx.requests, "get", boom):
            self.assertIsNone(wx.model_agreement(38.8, -122.5, old, old + timedelta(hours=2)))

    def test_network_failure_is_null(self):
        with mock.patch.object(wx.requests, "get", side_effect=RuntimeError("offline")):
            self.assertIsNone(wx.model_agreement(38.8, -122.5, self.start, self.end))

    def test_cache(self):
        calls = []

        def get(*a, **k):
            calls.append(1)
            return FakeResp(payload())
        with mock.patch.object(wx.requests, "get", get):
            a = wx.model_agreement(38.8, -122.5, self.start, self.end)
            b = wx.model_agreement(38.8, -122.5, self.start, self.end)
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 1)

    def test_label_thresholds(self):
        self.assertEqual(wx._agree_label(1.0, 1.0), "high")
        self.assertEqual(wx._agree_label(3.5, 4.0), "medium")
        self.assertEqual(wx._agree_label(6.0, 2.0), "low")
        self.assertIsNone(wx._agree_label(None, 2.0))


class WaterModelTest(unittest.TestCase):
    def _wx(self, means):
        w = wx.Weather.__new__(wx.Weather)
        base = datetime(2026, 4, 1)
        w.daily = [dict(dt=base + timedelta(days=i), tmax_f=m + 6, tmin_f=m - 6, pop=0)
                   for i, m in enumerate(means)]
        if hasattr(w, "_wseries"):
            del w._wseries
        return w

    def test_warms_with_the_air_and_lags_it(self):
        w = self._wx([50] * 4 + [54] * 4 + [58] * 4 + [62] * 4)
        at = datetime(2026, 4, 16)
        self.assertGreater(w.water_trend_f_per_week(at), 0)
        self.assertLess(w.est_water_f(at), 62 + wx.Weather.WATER_BIAS_F)

    def test_cooling_trend_is_negative(self):
        w = self._wx([70] * 4 + [66] * 4 + [62] * 4 + [58] * 4)
        self.assertLess(w.water_trend_f_per_week(datetime(2026, 4, 16)), 0)

    def test_short_history_is_null_safe(self):
        w = self._wx([60, 60])            # fewer days than the seed window
        self.assertEqual(w._water_series(), [])
        self.assertIsNone(w.est_water_f(datetime(2026, 4, 3)))
        self.assertIsNone(w.water_trend_f_per_week(datetime(2026, 4, 3)))


if __name__ == "__main__":
    unittest.main()
