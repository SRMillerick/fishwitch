"""Catalog/on-demand tier: the data-threshold rule, the shipped inventory,
the state hubs, and the segmented sitemap. No network — the pin report test
mocks the report builder."""
import unittest
from unittest import mock

import catalog
import webapp


class ThresholdRuleTest(unittest.TestCase):
    def _entry(self, **over):
        e = dict(coords_verified=True, species_sourced=True,
                 area_acres=100, est_max_depth_ft=30)
        e.update(over)
        return e

    def test_all_fields_indexable(self):
        ok, blockers = catalog.threshold(self._entry())
        self.assertTrue(ok)
        self.assertEqual(blockers, [])

    def test_each_missing_field_blocks(self):
        cases = [
            dict(coords_verified=False, species_sourced=True, area_acres=100, est_max_depth_ft=30),
            dict(coords_verified=True, species_sourced=False, area_acres=100, est_max_depth_ft=30),
            dict(coords_verified=True, species_sourced=True, area_acres=None, est_max_depth_ft=30),
            dict(coords_verified=True, species_sourced=True, area_acres=100, est_max_depth_ft=None),
        ]
        for e in cases:
            ok, blockers = catalog.threshold(e)
            self.assertFalse(ok, e)
            self.assertEqual(len(blockers), 1, e)
        # annotate stamps the verdict
        e = catalog.annotate(self._entry(coords_verified=False))
        self.assertFalse(e["index"])
        self.assertTrue(e["index_blockers"])


class ShippedCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.waters = catalog.load_catalog("CA")
        cls.summary = catalog.summary("CA")

    def test_inventory_present_and_consistent(self):
        self.assertGreater(len(self.waters), 1000)
        self.assertEqual(self.summary["inventory"], len(self.waters))
        self.assertEqual(self.summary["stocked"],
                         sum(1 for e in self.waters if e.get("stocked")))
        self.assertEqual(self.summary["indexable"],
                         sum(1 for e in self.waters if e.get("index")))

    def test_every_entry_matches_the_threshold(self):
        for e in self.waters:
            ok, _ = catalog.threshold(e)
            self.assertEqual(bool(e.get("index")), ok, e.get("name"))

    def test_catalog_coordinates_are_unverified_by_design(self):
        # GNIS points are not shoreline-verified; nothing is indexable yet.
        self.assertEqual(self.summary["indexable"], 0)
        self.assertFalse(any(e.get("coords_verified") for e in self.waters))

    def test_match_by_point_resolves_an_inventory_water(self):
        hit = catalog.match_by_point(33.6802, -117.0291)   # Diamond Valley Lake
        self.assertIsNotNone(hit)
        self.assertEqual(hit["name"], "Diamond Valley Lake")
        self.assertTrue(hit["featured"])
        self.assertIsNone(catalog.match_by_point(0.0, 0.0))   # open ocean


class StateHubTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def test_california_hub_lists_covered_waters(self):
        r = self.c.get("/lakes/ca")
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn("California fishing lakes", h)
        self.assertIn('href="/lake/diamond-valley-lake-ca"', h)
        self.assertIn("Run a report", h)

    def test_arizona_hub(self):
        r = self.c.get("/lakes/az")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/lake/yavapai-lakes-az"', r.get_data(as_text=True))

    def test_unknown_state_404(self):
        self.assertEqual(self.c.get("/lakes/zz").status_code, 404)


class SitemapSegmentationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _xml(self, path):
        return self.c.get(path).get_data(as_text=True)

    def test_root_is_an_index_of_chunks(self):
        xml = self._xml("/sitemap.xml")
        self.assertIn("<sitemapindex", xml)
        self.assertIn("/sitemap-pages.xml", xml)
        self.assertIn("/sitemap-lakes.xml", xml)

    def test_pages_chunk_has_static_pages_hubs_and_kb(self):
        xml = self._xml("/sitemap-pages.xml")
        self.assertIn("<urlset", xml)
        for u in ("/method", "/developers", "/lakes/ca", "/lakes/az", "/kb/dropshot"):
            self.assertIn(u, xml)

    def test_lakes_chunk_has_lastmod_and_only_registry_waters(self):
        xml = self._xml("/sitemap-lakes.xml")
        self.assertIn("<lastmod>", xml)
        self.assertIn("/lake/hidden-valley-lake-ca</loc>", xml)
        # a catalog-only water (no page, no route) must never be listed
        self.assertNotIn("Sandy Wool Lake", xml)
        self.assertNotIn("?lat=", xml)


class PinReportSeoTest(unittest.TestCase):
    """The dropped-pin report is ephemeral (noindex) and renders the pin
    branch of the form; the heavy report builder is mocked."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def test_pin_variant_is_noindex_and_carries_the_pin(self):
        from datetime import datetime
        fake = dict(lake="Diamond Valley Lake", overall=6.2, moon_svg="", moon={},
                    prime_t=None, picks=["Drop shot"], at=datetime(2026, 9, 30, 18, 0),
                    timeline="", html="", gap=[], rods=[], shopping=[], trends=[], has_box=False)
        with mock.patch.object(webapp, "_report_response", return_value=fake):
            h = self.c.get("/report?lat=33.6802&lng=-117.0291").get_data(as_text=True)
        self.assertIn('name="robots" content="noindex,follow"', h)
        self.assertIn('<link rel="canonical" href="https://baromoon.com/report">', h)
        self.assertIn('name="lat"', h)
        self.assertIn("This water isn't in the registry", h)

    def test_pin_view_is_tagged_on_demand(self):
        from datetime import datetime
        fake = dict(lake="Diamond Valley Lake", overall=6.2, moon_svg="", moon={},
                    prime_t=None, picks=["Drop shot"], at=datetime(2026, 9, 30, 18, 0),
                    timeline="", html="", gap=[], rods=[], shopping=[], trends=[], has_box=False)
        with mock.patch.object(webapp, "_report_response", return_value=fake), \
                mock.patch.object(webapp.telemetry, "record") as rec, \
                mock.patch.object(webapp.telemetry, "should_count", return_value=True):
            self.c.get("/report?lat=33.6802&lng=-117.0291")
        self.assertTrue(rec.called)
        self.assertEqual(rec.call_args.kwargs.get("src"), "ondemand")
        # a registry-lake report is not tagged on-demand
        with mock.patch.object(webapp, "_report_response", return_value=fake), \
                mock.patch.object(webapp.telemetry, "record") as rec2, \
                mock.patch.object(webapp.telemetry, "should_count", return_value=True):
            self.c.get("/report?lake=hidden-valley-lake-ca")
        self.assertIsNone(rec2.call_args.kwargs.get("src"))
