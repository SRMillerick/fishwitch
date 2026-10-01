"""GSC index-coverage reader — classification and URL list."""
import unittest

from tools import gsc_index


class TestGscIndex(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(gsc_index._classify("Submitted and indexed"), "indexed")
        self.assertEqual(gsc_index._classify("Discovered - currently not indexed"),
                         "not-indexed")
        self.assertEqual(gsc_index._classify("URL is unknown to Google"), "unknown")
        self.assertEqual(gsc_index._classify(""), "unknown")

    def test_registry_urls_covers_pages_and_waters(self):
        urls = gsc_index.registry_urls()
        self.assertIn("https://baromoon.com/", urls)
        self.assertIn("https://baromoon.com/method", urls)
        self.assertIn("https://baromoon.com/lake/hidden-valley-lake-ca", urls)
        self.assertEqual(len(urls), len(set(urls)), "registry_urls has duplicates")


if __name__ == "__main__":
    unittest.main()
