"""Public API v1 — anonymous, serializable, ISO datetimes, attributed."""
import json
import unittest
from datetime import datetime

import public_api

DT = datetime(2026, 9, 19, 17, 30)
CAT = {"id": "dropshot", "label": "Drop shot", "style": "finesse", "depth": "mid",
       "kind": "rig", "technique": "hover", "note": "n",
       "provenance": {"source": "test catalog", "confidence": "sourced"}}
MODEL = {
    "scores": {"weather": 7, "solunar": 9, "astro": 6, "overall": 7.4, "astro_notes": []},
    "weather": {"water_f": 68},
    "sun": {"sunrise": DT, "sunset": DT},
    "moon": {"phase": "first quarter", "illum": 61, "moonrise": DT},
    "solunar": [{"kind": "major", "label": "Moon overhead",
                 "start": DT, "end": DT, "peak": DT}],
    "blocks": [{"start": DT, "end": DT, "light": "golden", "solunar": "major",
                "events": ["prime"], "picks": [(CAT, 9.2, ["why one"])]}],
    "prime": {"start": DT, "end": DT, "light": "golden", "solunar": "major",
              "events": [], "picks": [(CAT, 9.2, ["why one"])]},
    "rods": [CAT], "gap": [(CAT, 8.5, ["gap why"])],
    "knots": [{"id": "palomar", "label": "Palomar knot", "connection": "line-to-hook",
               "provenance": {"confidence": "sourced"}}],
    "line": {"id": "fluorocarbon", "label": "Fluorocarbon", "why": "x", "mine": False},
    "color": {"label": "Low light runs on rods", "rule": "text"},
    "trends": [{"label": "Drop shot", "score": 8.5, "signal": "creator",
                "source": "YouTube", "url": "https://youtu.be/x", "observed_at": "2026-09-18"}],
    "lake_state": "post-turnover (inferred)", "state_basis": "75-day archive",
    "water_temp_source": False, "stocking": [], "access_note": None,
}
LAKE = {"id": "hidden-valley-lake-ca", "name": "Hidden Valley Lake",
        "region": "Lake County, CA"}


class PublicApiTest(unittest.TestCase):
    def test_report_is_serializable_and_iso(self):
        body = public_api.report(MODEL, "hidden-valley-lake-ca", LAKE, DT, 2.5,
                                 "fisher", "bass", "grass")
        text = json.dumps(public_api.envelope(body))
        self.assertIn("post-turnover", text)
        self.assertEqual(body["prime"]["start"], "2026-09-19T17:30")
        self.assertEqual(body["blocks"][0]["picks"][0]["score"], 9.2)
        self.assertNotIn("html", body)

    def test_anonymous_contract(self):
        body = public_api.report(MODEL, "hidden-valley-lake-ca", LAKE, DT, 2.5,
                                 "fisher", "bass", None)
        text = json.dumps(public_api.envelope(body))
        self.assertNotIn("profile", text)
        self.assertNotIn("birth", text)

    def test_links_point_home_and_to_feeds(self):
        body = public_api.report(MODEL, "hidden-valley-lake-ca", LAKE, DT, 2.5,
                                 "fisher", "bass", None)
        l = body["links"]
        self.assertTrue(l["report"].startswith("https://baromoon.com/report?"))
        self.assertIn("ledger.ics", l["calendar"])
        self.assertIn("outlook.rss", l["rss"])

    def test_windows_mapper(self):
        rows = [dict(day="2026-09-20", start=DT, end=DT, overall=7.6,
                     conf="high", prime=DT, picks=["Drop shot"])]
        moon = [("2026-09-20", "first quarter", 61, "<svg/>")]
        w = public_api.windows(rows, moon, "hidden-valley-lake-ca")
        json.dumps(public_api.envelope(w))
        self.assertEqual(w["windows"][0]["start"], "2026-09-19T17:30")
        self.assertEqual(w["moon"][0], {"day": "2026-09-20",
                                        "phase": "first quarter", "illum": 61})

    def test_missing_prime_is_null(self):
        m = dict(MODEL, prime=None, blocks=[])
        body = public_api.report(m, "hidden-valley-lake-ca", LAKE, DT, 2.5,
                                 "fisher", "bass", None)
        self.assertIsNone(body["prime"])
        json.dumps(public_api.envelope(body))


if __name__ == "__main__":
    unittest.main()
