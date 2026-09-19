"""Web routes that don't touch the network — canonical KB entity pages."""
import unittest

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

    def test_service_worker_served_at_root_scope(self):
        r = self.c.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Service-Worker-Allowed"), "/")
        self.assertIn("fetch", r.get_data(as_text=True))

    def test_sitemap_includes_entities(self):
        xml = self.c.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/kb/dropshot", xml)
        self.assertIn("/kb/carolina", xml)


if __name__ == "__main__":
    unittest.main()
