"""Offers URL construction: network deep links, Amazon tags, disclosure.

No network, no writes — the real `kb/offers.json` is only smoke-tested for
shape. IDs and ASINs live in fixtures, never in code.
"""
import os
import unittest
from unittest import mock

import offers


RAKUTEN_REG = {
    "scheels": {
        "label": "Scheels",
        "kind": "affiliate",
        "deeplink_template":
            "https://click.linksynergy.com/deeplink?id=SID0000000&mid=53843&murl={url}",
        "subtag_param": "u1",
    },
    "tacklewarehouse": {"label": "Tackle Warehouse", "kind": "affiliate"},
}

AMAZON_REG = {
    "amazon": {
        "label": "Amazon",
        "kind": "affiliate",
        "dp_template": "https://www.amazon.com/dp/{asin}",
        "tag_env": "FISHWITCH_AMZ_TAG",
        "subtag": True,
    },
}


class NetworkDeeplinkTest(unittest.TestCase):
    def test_deeplink_encodes_destination_and_carries_entry_subtag(self):
        url = offers._offer_url(
            "dropshot", {"retailer": "scheels", "url": "https://www.scheels.com/p/foo bar?x=1"},
            RAKUTEN_REG)
        self.assertTrue(url.startswith("https://click.linksynergy.com/deeplink?"))
        self.assertIn("mid=53843", url)
        self.assertIn("murl=https%3A%2F%2Fwww.scheels.com%2Fp%2Ffoo%20bar%3Fx%3D1", url)
        self.assertTrue(url.endswith("u1=dropshot"))

    def test_deeplink_without_destination_is_pending(self):
        self.assertIsNone(offers._offer_url(
            "dropshot", {"retailer": "scheels", "url": None}, RAKUTEN_REG))

    def test_deeplink_without_subtag_param(self):
        reg = {"scheels": {"kind": "affiliate",
                           "deeplink_template": "https://click.example/d?murl={url}"}}
        url = offers._offer_url("wacky", {"retailer": "scheels",
                                          "url": "https://www.scheels.com/p/1"}, reg)
        self.assertEqual(url, "https://click.example/d?murl=https%3A%2F%2Fwww.scheels.com%2Fp%2F1")

    def test_stored_url_passthrough_is_not_double_wrapped(self):
        # a pre-built tracked link (no template) is used verbatim
        url = offers._offer_url("wacky", {"retailer": "tacklewarehouse",
                                          "url": "https://track.example/abc"}, RAKUTEN_REG)
        self.assertEqual(url, "https://track.example/abc")

    def test_resolve_attaches_affiliate_disclosure(self):
        row = offers._resolve("dropshot", {"retailer": "scheels",
                                           "url": "https://www.scheels.com/p/1"}, RAKUTEN_REG)
        self.assertIn("commission", row["disclosure"])
        self.assertEqual(row["retailer_label"], "Scheels")


class AmazonTemplateTest(unittest.TestCase):
    def test_tag_from_env_plus_ascsubtag(self):
        with mock.patch.dict(os.environ, {"FISHWITCH_AMZ_TAG": "baromoon-20"}):
            url = offers._offer_url("dropshot", {"retailer": "amazon", "asin": "B0TEST"},
                                    AMAZON_REG)
        self.assertEqual(url, "https://www.amazon.com/dp/B0TEST?tag=baromoon-20&ascsubtag=dropshot")

    def test_no_tag_env_keeps_the_link_pending(self):
        # a tagged retailer must never emit an untagged link
        with mock.patch.dict(os.environ, {}, clear=True):
            url = offers._offer_url("dropshot", {"retailer": "amazon", "asin": "B0TEST"},
                                    AMAZON_REG)
        self.assertIsNone(url)

    def test_missing_asin_is_pending(self):
        self.assertIsNone(offers._offer_url("dropshot", {"retailer": "amazon"}, AMAZON_REG))


class RegistryShapeTest(unittest.TestCase):
    def test_real_registry_resolves_without_network(self):
        for entry in ("dropshot", "wacky", "carolina"):
            rows = offers.resolve(entry)
            self.assertIsInstance(rows, list)


if __name__ == "__main__":
    unittest.main()
