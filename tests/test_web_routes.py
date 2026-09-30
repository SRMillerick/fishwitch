"""Web routes that don't touch the network — canonical KB entity pages."""
import os
import re
import tempfile
import unittest
from pathlib import Path
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
        xml = self.c.get("/sitemap-pages.xml").get_data(as_text=True)
        self.assertIn("/kb/dropshot", xml)
        self.assertIn("/kb/carolina", xml)


class SeoHeadTest(unittest.TestCase):
    """Head hygiene: unique titles/descriptions, self-canonicals, robots policy,
    structured data, sitemap lastmod, llms.txt, and the IndexNow key file."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _body(self, path):
        return self.c.get(path).get_data(as_text=True)

    def test_pages_have_unique_titles_and_descriptions(self):
        pages = ["/", "/report", "/outlook", "/lakes", "/kb", "/interview",
                 "/about", "/method", "/developers", "/contact", "/privacy", "/disclosure",
                 "/lake/hidden-valley-lake-ca", "/kb/dropshot", "/kb/abstract"]
        titles, descs = set(), set()
        for p in pages:
            h = self._body(p)
            t = re.search(r"<title>(.*?)</title>", h, re.S).group(1)
            d = re.search(r'<meta name="description" content="([^"]*)"', h).group(1)
            c = re.search(r'<link rel="canonical" href="([^"]*)"', h).group(1)
            self.assertTrue(d, p)
            self.assertNotIn(t, titles, p)
            self.assertNotIn(d, descs, p)
            self.assertTrue(c.startswith("https://baromoon.com/"), p)
            titles.add(t)
            descs.add(d)

    def test_query_report_variants_are_noindex_follow(self):
        h = self._body("/report?lake=hidden-valley-lake-ca&at=2026-09-30T07:00")
        self.assertIn('name="robots" content="noindex,follow"', h)
        self.assertIn('<link rel="canonical" href="https://baromoon.com/report">', h)

    def test_structured_data_entities(self):
        self.assertIn('"@type": "Organization"', self._body("/"))
        self.assertIn('"@type": "WebSite"', self._body("/"))
        lake = self._body("/lake/hidden-valley-lake-ca")
        for t in ('"@type": "Place"', '"@type": "BreadcrumbList"'):
            self.assertIn(t, lake)
        self.assertIn('"@type": "Article"', self._body("/kb/dropshot"))

    def test_sitemap_lastmod_on_lakes(self):
        xml = self._body("/sitemap-lakes.xml")
        self.assertIn("<lastmod>", xml)
        self.assertIn("/lake/hidden-valley-lake-ca</loc>", xml)

    def test_lake_page_is_answer_first_with_faq_schema(self):
        h = self._body("/lake/hidden-valley-lake-ca")
        self.assertIn("Short answer:", h)
        self.assertIn("Quick answers", h)
        self.assertIn('"@type": "FAQPage"', h)
        self.assertIn("What fish are in Hidden Valley Lake?", h)

    def test_social_card_is_served_and_declared(self):
        r = self.c.get("/static/og-card.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/png")
        self.assertIn("static/og-card.png", self._body("/"))

    def test_sitemap_and_llms_include_new_pages(self):
        sitemap, llms = self._body("/sitemap-pages.xml"), self._body("/llms.txt")
        for page in ("/method", "/developers"):
            self.assertIn(page, sitemap)
            self.assertIn("baromoon.com" + page, llms)

    def test_llms_txt_and_indexnow_key(self):
        r = self.c.get("/llms.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("deterministic", r.get_data(as_text=True))
        if webapp.INDEXNOW_KEY:
            r = self.c.get(f"/{webapp.INDEXNOW_KEY}.txt")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_data(as_text=True).strip(), webapp.INDEXNOW_KEY)


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

    def test_step_rail_and_nav_carry_the_lake(self):
        html, _ = self._get("/?lake=hidden-valley-lake-ca")
        self.assertIn('class="stepbar', html)          # water → plan → ahead → log
        self.assertIn('href="/report?lake=hidden-valley-lake-ca"', html)
        self.assertIn('href="/outlook?lake=hidden-valley-lake-ca"', html)

    def test_landing_without_lake_has_no_step_rail(self):
        html, _ = self._get("/")
        self.assertNotIn('class="stepbar', html)
        self.assertIn('data-lake-link="/report"', html)  # JS can still fill it

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


class LakeMapTileTest(unittest.TestCase):
    """Water pages must use keyless OSM tiles: CARTO's basemaps now require an
    API key (they watermark without one), and the site's global no-referrer
    policy is overridden per tile with an origin-only Referer."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _html(self, path):
        r = self.c.get(path)
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def test_waters_map_uses_keyless_osm_tiles(self):
        html = self._html("/lakes")
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", html)
        self.assertIn("referrerPolicy: 'origin'", html)
        self.assertNotIn("cartocdn.com", html)

    def test_lake_map_uses_keyless_osm_tiles(self):
        with mock.patch.object(webapp, "_ledger", return_value=[]):
            html = self._html("/lake/hidden-valley-lake-ca")
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", html)
        self.assertIn("referrerPolicy: 'origin'", html)
        self.assertNotIn("cartocdn.com", html)


class LakeFactsHeaderTest(unittest.TestCase):
    """The facts row names the water's location, not its data source: the
    Location link shows coordinates (OSM is the destination, and the map
    carries the attribution), and the County carries the water's own state
    (AZ waters used to say ', CA')."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _lake(self, lake_id):
        with mock.patch.object(webapp, "_ledger", return_value=[]):
            r = self.c.get(f"/lake/{lake_id}")
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def test_location_shows_coordinates_not_the_source(self):
        html = self._lake("hidden-valley-lake-ca")
        m = re.search(
            r'href="https://www\.openstreetmap\.org/\?mlat=[^"]+"[^>]*>([^<]+)</a>',
            html)
        self.assertIsNotNone(m, "no OSM coordinate link on the lake page")
        self.assertRegex(m.group(1), r"38\.8105,\s*-122\.5640")

    def test_county_uses_the_waters_state(self):
        az = self._lake("watson-lake-az")
        self.assertIn("Yavapai, AZ", az)
        self.assertNotIn("Yavapai, CA", az)
        ca = self._lake("hidden-valley-lake-ca")
        self.assertIn("Lake, CA", ca)


class OutClickResolutionTest(unittest.TestCase):
    """The shopping list stamps every outbound link with comp=<row id>. Rows
    whose offer lives on a product entry (e.g. egg-sinker) carry no component
    bundle under that id, so /out must fall back to the entry's own offers;
    rig rows still resolve from their component bundle."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def _get(self, url):
        log = Path(tempfile.gettempdir()) / "fishwitch-out-test.jsonl"
        with mock.patch.dict(os.environ, {"FISHWITCH_AMZ_TAG": "baromoon-20"}), \
                mock.patch.object(webapp, "LOG", new=log):
            return self.c.get(url)

    def test_product_entry_with_comp_resolves(self):
        r = self._get("/out/egg-sinker/amazon?comp=egg-sinker&src=shopping")
        self.assertEqual(r.status_code, 302)
        self.assertIn("amazon.com/dp/", r.headers["Location"])
        self.assertIn("tag=baromoon-20", r.headers["Location"])

    def test_rig_component_still_resolves_from_bundle(self):
        r = self._get("/out/wacky/amazon?comp=soft-plastic&src=tackle")
        self.assertEqual(r.status_code, 302)
        self.assertIn("amazon.com/dp/", r.headers["Location"])

    def test_unknown_comp_still_404s(self):
        r = self._get("/out/wacky/amazon?comp=not-a-part&src=tackle")
        self.assertEqual(r.status_code, 404)

    def test_crawler_click_is_flagged(self):
        import json
        log = Path(tempfile.mkdtemp(prefix="fw_out_")) / "out.jsonl"
        with mock.patch.dict(os.environ, {"FISHWITCH_AMZ_TAG": "baromoon-20"}), \
                mock.patch.object(webapp, "LOG", new=log):
            r = self.c.get("/out/egg-sinker/amazon?comp=egg-sinker&src=shopping",
                           headers={"User-Agent":
                                    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"})
        self.assertEqual(r.status_code, 302)
        row = json.loads(log.read_text().splitlines()[0])
        self.assertTrue(row.get("bot"))


if __name__ == "__main__":
    unittest.main()
