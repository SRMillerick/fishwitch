"""Web routes that don't touch the network — canonical KB entity pages."""
import unittest
from unittest import mock

import webapp


class KBEntityPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def test_known_entry_renders_cited_page(self):
        r = self.c.get("/kb/dropshot")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for needle in ("Drop shot", "Conditions", "The build", "Sources",
                       "canonical"):
            self.assertIn(needle, html)

    def test_unknown_entry_404(self):
        self.assertEqual(self.c.get("/kb/not-an-entry").status_code, 404)

    def test_kb_table_links_entities(self):
        html = self.c.get("/kb?species=bass").get_data(as_text=True)
        self.assertIn('href="/kb/dropshot"', html)

    def test_bait_entity_renders(self):
        r = self.c.get("/kb/abstract")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for needle in ("The Abstract", "urchin-dice", "Field notes", "Sources"):
            self.assertIn(needle, html)

    def test_kb_index_lists_baits_and_family(self):
        html = self.c.get("/kb?species=bass").get_data(as_text=True)
        self.assertIn("Cross-species baits", html)
        self.assertIn('href="/kb/abstract"', html)
        # the family link is on the bait page
        bait = self.c.get("/kb/abstract").get_data(as_text=True)
        self.assertIn('href="/kb/prickly-pear"', bait)

    def test_service_worker_served_at_root_scope(self):
        r = self.c.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Service-Worker-Allowed"), "/")
        self.assertIn("fetch", r.get_data(as_text=True))

    def test_sitemap_includes_entities(self):
        xml = self.c.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/kb/dropshot", xml)
        self.assertIn("/kb/carolina", xml)


class LandingLedgerTest(unittest.TestCase):
    """The landing page accepts a lake and embeds the registry for the
    browser-side nearest-water pick. No network: the heavy report/ledger
    builders are mocked."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _get(self, path):
        seen = {}

        def fake_report(payload, anonymous=False):
            seen["lake"] = payload.get("lake")
            return dict(lake="Mocked Water", overall=7.1, moon_svg="",
                        moon={"phase": "Waxing crescent", "illum": 12},
                        prime_t=None, picks=["Drop shot"])

        with mock.patch.object(webapp, "_report_response", side_effect=fake_report), \
                mock.patch.object(webapp, "_ledger", return_value=[]):
            html = self.c.get(path).get_data(as_text=True)
        return html, seen

    def test_lake_param_selects_the_water(self):
        html, seen = self._get("/?lake=hidden-valley-lake-ca")
        self.assertEqual(seen["lake"], "hidden-valley-lake-ca")
        self.assertIn("Mocked Water", html)  # mocked teaser label

    def test_unknown_lake_falls_back_to_demo_water(self):
        _, seen = self._get("/?lake=not-a-real-lake")
        self.assertEqual(seen["lake"], "hidden-valley-lake-ca")

    def test_landing_embeds_nearby_waters_registry(self):
        html, _ = self._get("/")
        self.assertIn('id="bm-waters"', html)
        self.assertIn('id="near-me-wrap"', html)
        self.assertIn('id="waters-list"', html)
        self.assertIn("hidden-valley-lake-ca", html)

    def test_nearest_lakes_radius_order(self):
        import math

        def km(a, b):
            la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
            return 6371 * math.acos(min(1, math.sin(la1) * math.sin(la2) +
                                         math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1)))

        reg = webapp.registry()
        home = reg["hidden-valley-lake-ca"]
        near = webapp._nearest_lakes(home, 3)
        self.assertEqual(near[0]["id"], "hidden-valley-lake-ca")
        self.assertEqual(len({v["id"] for v in near}), 4)
        dists = [km(home, v) for v in near[1:]]
        self.assertEqual(dists, sorted(dists))  # nearest first


class PrescottWatersTest(unittest.TestCase):
    """The Prescott, AZ cluster (added 2026-09-20) keeps its sourcing shape:
    Arizona timezone, Yavapai county, in-state coords, species + note."""

    KEYS = ["watson-lake-az", "willow-lake-az", "goldwater-lake-az",
            "lynx-lake-az", "granite-basin-lake-az", "fain-lake-az",
            "yavapai-lakes-az"]

    def test_prescott_entries_have_core_fields(self):
        reg = webapp.registry()
        for k in self.KEYS:
            v = reg[k]
            self.assertEqual(v.get("id"), k, k)
            self.assertEqual(v.get("tz"), "America/Phoenix", k)
            self.assertEqual(v.get("county"), "Yavapai", k)
            self.assertIn("AZ", v.get("region", ""), k)
            self.assertTrue(31 <= v["lat"] <= 37, k)
            self.assertTrue(-115 <= v["lng"] <= -109, k)
            self.assertTrue(v.get("species"), k)
            self.assertIn("turnover", v, k)
            self.assertIn("note", v, k)


if __name__ == "__main__":
    unittest.main()
