"""Glossary integrity — every explainer's facts resolve to a promoted KB quote.

`kb/glossary.json` stores `{file, find}` refs, not quotes; the loader pulls the
canonical citation (tier, url, fetched_at, sha256) from the KB. This locks it:
if a source quote is edited or removed, an explainer's prose can no longer
silently outrun its evidence.
"""
import unittest

import tactics as tx


class TestGlossary(unittest.TestCase):
    def test_every_source_ref_resolves(self):
        for t in tx.glossary_terms():
            with self.subTest(term=t["id"]):
                self.assertTrue(t.get("sources"), f"{t['id']}: no sources")
                self.assertEqual(len(t["citations"]), len(t["sources"]),
                                 f"{t['id']}: a source ref did not resolve")
                for c in t["citations"]:
                    self.assertTrue(c.get("quote"))
                    self.assertTrue(c.get("url"))
                    self.assertTrue(c.get("sha256"), f"{t['id']}: citation without sha256")
                    self.assertTrue(c.get("fetched_at"),
                                    f"{t['id']}: citation without fetched_at")
                    self.assertIn(c.get("tier"), ("T1", "T2", "T3", "T4", "T5"))

    def test_ids_unique_and_categorised(self):
        d = tx.load_glossary()
        ids = [t["id"] for t in d["terms"]]
        self.assertEqual(len(ids), len(set(ids)))
        cats = {c["id"] for c in d.get("categories", [])}
        for t in d["terms"]:
            self.assertIn(t.get("category"), cats, t["id"])
            self.assertTrue(t.get("question"))
            self.assertTrue(t.get("short"))

    def test_term_lookup(self):
        self.assertIsNotNone(tx.glossary_term("bass-water-temperature"))
        self.assertIsNone(tx.glossary_term("no-such-term"))

    def test_pages_render(self):
        import webapp
        c = webapp.app.test_client()
        for path in ("/glossary", "/glossary/bass-water-temperature",
                     "/glossary/lure-color-water-clarity"):
            self.assertEqual(c.get(path).status_code, 200, path)
        self.assertEqual(c.get("/glossary/no-such-term").status_code, 404)


if __name__ == "__main__":
    unittest.main()
