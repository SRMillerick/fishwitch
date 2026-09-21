"""Trend adapter dedupe — promoted URLs must never come back as drafts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters import trends as tra


class TrendDraftTest(unittest.TestCase):
    def _write(self, url, promoted, rejected=None):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(tra, "PENDING", Path(td)):
                p = tra._write_draft(
                    "dropshot", "MLF — story", url, "a quote", "a title",
                    "tournament", "2026-09-20", None,
                    slug_hint="mlf-2026-09-20", promoted_urls=promoted,
                    rejected_pairs=rejected)
                if p is None:
                    return None, None
                return p, json.loads(p.read_text())

    def test_promoted_url_is_skipped(self):
        p, _ = self._write("https://x.test/promoted",
                           {"https://x.test/promoted", "https://x.test/other"})
        self.assertIsNone(p)

    def test_rejected_entity_url_pair_is_skipped(self):
        p, _ = self._write("https://x.test/press", set(),
                           {("dropshot", "https://x.test/press")})
        self.assertIsNone(p)

    def test_rejected_url_for_another_entity_still_drafts(self):
        p, d = self._write("https://x.test/press", set(),
                           {("urchin", "https://x.test/press")})
        self.assertIsNotNone(p)
        self.assertEqual(d["proposed"]["url"], "https://x.test/press")

    def test_new_url_is_drafted(self):
        p, d = self._write("https://x.test/new", {"https://x.test/old"})
        self.assertIsNotNone(p)
        self.assertEqual(d["proposed"]["url"], "https://x.test/new")
        self.assertEqual(d["target_key"], "trends")


class RetiredUrlTest(unittest.TestCase):
    def test_retired_log_urls_are_collected(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "retired.log").write_text(json.dumps({
                "entry_id": "old",
                "entry": {"url": "https://x.test/gone"}}) + "\n")
            with mock.patch.object(tra, "KB", Path(td)):
                self.assertIn("https://x.test/gone", tra.retired_urls())


if __name__ == "__main__":
    unittest.main()
