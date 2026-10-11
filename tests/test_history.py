"""Weather-history layer (the ERA5 archive): the lag clamp, and the deprecation
that made it fragile.

`History` clamps its end date to `today(UTC) - 5` because the archive lags. That
clamp used `datetime.utcnow()`, which is deprecated and scheduled for removal —
and because the harness is run with warnings-as-errors in CI-style checks, a
single deprecated call raises at *import* time and takes the whole suite with it.
"""
import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import layers.history as hist


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _payload(days=3):
    d0 = datetime.now(timezone.utc).date() - timedelta(days=6)
    times = [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {"daily": {"time": times,
                      "temperature_2m_max": [20.0] * days,
                      "temperature_2m_min": [10.0] * days}}


class ArchiveClampTest(unittest.TestCase):
    def _build(self, end):
        seen = {}

        def fake_fetch(params, **kw):
            seen.update(params)
            return FakeResp(_payload())

        with mock.patch.object(hist, "_fetch", fake_fetch):
            return hist.History(38.9, -122.6, end, days=10), seen

    def test_future_end_clamps_to_the_utc_archive_edge(self):
        _h, seen = self._build(datetime.now(timezone.utc) + timedelta(days=30))
        expected = (datetime.now(timezone.utc).date()
                    - timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertEqual(seen["end_date"], expected)

    def test_past_end_is_not_clamped_forward(self):
        past = datetime.now(timezone.utc) - timedelta(days=40)
        _h, seen = self._build(past)
        self.assertEqual(seen["end_date"], past.date().strftime("%Y-%m-%d"))

    def test_window_spans_the_requested_days(self):
        _h, seen = self._build(datetime.now(timezone.utc))
        span = (datetime.strptime(seen["end_date"], "%Y-%m-%d")
                - datetime.strptime(seen["start_date"], "%Y-%m-%d")).days
        self.assertEqual(span, 10)

    def test_series_is_parsed_in_fahrenheit(self):
        h, _ = self._build(datetime.now(timezone.utc))
        self.assertTrue(h.series)
        self.assertIn("tmax", h.series[0])
        self.assertAlmostEqual(h.series[0]["tmax"], 68.0)      # 20C
        self.assertAlmostEqual(h.series[0]["tmin"], 50.0)      # 10C


class DeprecationGuardTest(unittest.TestCase):
    """One `utcnow()` anywhere in first-party code aborts the suite at import
    when warnings are promoted to errors — keep it at zero. Parsed with `ast`,
    not a substring scan: prose that merely names the call is not a call."""

    @staticmethod
    def _calls_deprecated_utc_now(path: Path) -> bool:
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "utcnow":
                return True
            if isinstance(node, ast.Name) and node.id == "utcnow":
                return True
        return False

    def test_no_first_party_utcnow(self):
        root = Path(__file__).resolve().parent.parent
        skip = {"site", ".cache", ".git", "__pycache__", "node_modules"}
        hits = [str(py.relative_to(root)) for py in sorted(root.rglob("*.py"))
                if not set(py.parts) & skip
                and self._calls_deprecated_utc_now(py)]
        self.assertEqual(hits, [], f"deprecated utcnow() in {hits}")


if __name__ == "__main__":
    unittest.main()
