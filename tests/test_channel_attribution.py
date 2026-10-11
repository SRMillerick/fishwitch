"""Channel attribution for the distribution test (plan §10).

A community post links to a tagged landing URL (`?src=<post-id>`). The tag is
only worth anything if it survives two hops:

    landing URL -> page log `src`      (did the post drive a session?)
    landing URL -> /out/ -> ascsubtag  (did it drive an affiliate click/sale?)

The second hop matters twice over: Facebook strips referrers on outbound links,
so an untagged post is indistinguishable from direct traffic, and Amazon's
Sub-Tag report — not our own `/out/` log — is the arbiter of a click or a sale.

Untagged traffic must behave exactly as it did before this existed: the section
token alone. Organic reports must not shift under the distribution test.
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import offers
import telemetry
import webapp


AMAZON_REG = {
    "amazon": {
        "label": "Amazon",
        "kind": "affiliate",
        "dp_template": "https://www.amazon.com/dp/{asin}",
        "tag_env": "FISHWITCH_AMZ_TAG",
        "subtag": True,
    },
}

TAG = {"FISHWITCH_AMZ_TAG": "baromoon-20"}

# /out/ src tokens as the page actually rendered them.
_OUT_SRC = re.compile(r'/out/[^"]*?[?&]src=([a-z0-9_-]*)')


def _out_tokens(html: str) -> set:
    return set(_OUT_SRC.findall(html))


class SubtagTest(unittest.TestCase):
    def test_channel_precedes_entry(self):
        self.assertEqual(offers._subtag("tackle-fb-hvl", "wacky"),
                         "tackle-fb-hvl-wacky")

    def test_no_channel_is_just_the_entry(self):
        self.assertEqual(offers._subtag(None, "wacky"), "wacky")
        self.assertEqual(offers._subtag("", "wacky"), "wacky")

    def test_missing_entry_is_just_the_channel(self):
        self.assertEqual(offers._subtag("tackle-fb-hvl", ""), "tackle-fb-hvl")


class SubtagInUrlTest(unittest.TestCase):
    def test_ascsubtag_carries_the_channel(self):
        with mock.patch.dict(os.environ, TAG):
            url = offers._offer_url("wacky", {"retailer": "amazon", "asin": "B0TEST"},
                                    AMAZON_REG, src="tackle-fb-hvl")
        self.assertIn("ascsubtag=tackle-fb-hvl-wacky", url)

    def test_ascsubtag_without_a_channel_is_unchanged(self):
        """Organic clicks keep the historical sub-tag — no break in the report."""
        with mock.patch.dict(os.environ, TAG):
            url = offers._offer_url("wacky", {"retailer": "amazon", "asin": "B0TEST"},
                                    AMAZON_REG)
        self.assertIn("ascsubtag=wacky", url)
        self.assertNotIn("ascsubtag=-", url)

    def test_resolve_any_threads_the_channel(self):
        with mock.patch.dict(os.environ, TAG):
            rows = offers.resolve_any("offset-hook", src="tackle-fb-hvl")
        amz = [r for r in rows if r.get("retailer") == "amazon" and r.get("url")]
        self.assertTrue(amz, "offset-hook should resolve an Amazon URL")
        self.assertIn("ascsubtag=tackle-fb-hvl-offset-hook", amz[0]["url"])

    def test_components_thread_the_channel(self):
        """The 'build it:' bundles resolve through a different path than resolve()."""
        with mock.patch.dict(os.environ, TAG):
            comps = offers.components("dropshot", src="shopping-fb-hvl")
        urls = [o["url"] for c in comps for o in c.get("offers", []) if o.get("url")]
        tagged = [u for u in urls if "ascsubtag=shopping-fb-hvl-" in u]
        self.assertTrue(tagged, f"no component offer carried the channel: {urls[:3]}")


class LandingChannelTest(unittest.TestCase):
    """The landing URL's ?src= must reach the /out/ links the page renders."""

    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def test_kb_links_carry_the_channel(self):
        html = self.c.get("/kb/dropshot?src=fb-hvl").get_data(as_text=True)
        self.assertIn("kb-fb-hvl", _out_tokens(html))

    def test_tying_links_carry_the_channel(self):
        html = self.c.get("/tying?src=reddit-hvl-w1").get_data(as_text=True)
        self.assertIn("tying-reddit-hvl-w1", _out_tokens(html))

    def test_untagged_landing_renders_the_bare_section(self):
        """Organic visits render exactly what they did before this shipped."""
        self.assertEqual(_out_tokens(self.c.get("/kb/dropshot").get_data(as_text=True)),
                         {"kb"})
        self.assertEqual(_out_tokens(self.c.get("/tying").get_data(as_text=True)),
                         {"tying"})

    def test_unsafe_channel_is_stripped_not_escaped_through(self):
        html = self.c.get("/kb/dropshot?src=%3Cscript%3Ebad%21").get_data(as_text=True)
        self.assertIn("kb-scriptbad", _out_tokens(html))
        self.assertNotIn("<script>bad", html)

    def test_overlong_channel_is_capped(self):
        html = self.c.get("/kb/dropshot?src=" + "x" * 60).get_data(as_text=True)
        self.assertIn("kb-" + "x" * 24, _out_tokens(html))


class OutRedirectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = webapp.app.test_client()

    def test_redirect_carries_channel_into_ascsubtag(self):
        with mock.patch.dict(os.environ, TAG):
            r = self.c.get("/out/offset-hook/amazon?src=tackle-fb-hvl")
        self.assertEqual(r.status_code, 302)
        self.assertIn("ascsubtag=tackle-fb-hvl-offset-hook", r.headers["Location"])

    def test_redirect_without_channel_is_unchanged(self):
        with mock.patch.dict(os.environ, TAG):
            r = self.c.get("/out/offset-hook/amazon")
        self.assertIn("ascsubtag=offset-hook", r.headers["Location"])
        self.assertNotIn("ascsubtag=-", r.headers["Location"])


class PageSourceTest(unittest.TestCase):
    """The landing tag must also land in the page log, or 'did this post drive a
    session at all?' is unanswerable."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "pages.jsonl"
        self.c = webapp.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        return [json.loads(x) for x in self.log.read_text().splitlines() if x.strip()]

    def test_landing_channel_is_recorded(self):
        with mock.patch.object(telemetry, "PAGES", self.log):
            self.c.get("/kb/dropshot?src=fb-hvl")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["src"], "fb-hvl")

    def test_untagged_view_records_no_src(self):
        with mock.patch.object(telemetry, "PAGES", self.log):
            self.c.get("/kb/dropshot")
        self.assertNotIn("src", self._rows()[0])

    def test_ondemand_tag_still_applies(self):
        with mock.patch.object(telemetry, "PAGES", self.log):
            self.c.get("/report?lat=38.9&lng=-122.6")
        self.assertEqual(self._rows()[0]["src"], "ondemand")

    def test_explicit_channel_wins_over_ondemand(self):
        with mock.patch.object(telemetry, "PAGES", self.log):
            self.c.get("/report?lat=38.9&lng=-122.6&src=fb-hvl")
        self.assertEqual(self._rows()[0]["src"], "fb-hvl")


if __name__ == "__main__":
    unittest.main()
