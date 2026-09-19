"""Local /log route — writes the same logbook shape as the CLI."""
import tempfile
import unittest
from pathlib import Path

import logbook
import webapp


class LogRouteTest(unittest.TestCase):
    def setUp(self):
        self._local = webapp.LOCAL
        self._book = logbook.BOOK
        webapp.LOCAL = True
        logbook.BOOK = Path(tempfile.mkdtemp(prefix="fw_log_")) / "logbook.jsonl"
        self.c = webapp.app.test_client()

    def tearDown(self):
        webapp.LOCAL = self._local
        logbook.BOOK = self._book

    def test_get_form(self):
        r = self.c.get("/log")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Log a fish", r.get_data(as_text=True))

    def test_post_catch_normalizes_weight(self):
        r = self.c.post("/log", data=dict(
            angler="Sean", lake="hidden-valley-lake-ca", date="2026-09-19", time="18:30",
            species="largemouth bass", lure="drop shot", length="4.5", notes="dock corner"))
        self.assertEqual(r.status_code, 302)
        rows = logbook.load()
        self.assertEqual(len(rows), 1)
        e = rows[0]
        self.assertEqual(e["result"], "catch")
        self.assertEqual(e["length"], "4.5lb")
        self.assertEqual(e["angler"], "Sean")
        self.assertEqual(e["lure"], "drop shot")
        self.assertEqual(e["ts"], "2026-09-19T18:30")

    def test_post_skunk_drops_lure_and_weight(self):
        self.c.post("/log", data=dict(
            angler="Jack", lake="hidden-valley-lake-ca", date="2026-09-19", time="07:00",
            species="largemouth bass", lure="wacky", length="3", notes="nothing", skunk="on"))
        e = logbook.load()[0]
        self.assertEqual(e["result"], "skunk")
        self.assertIsNone(e["lure"])
        self.assertEqual(e["length"], "")

    def test_404_when_not_local(self):
        webapp.LOCAL = False
        self.assertEqual(self.c.get("/log").status_code, 404)

    def test_prefill_from_report_link(self):
        r = self.c.get("/log?lake=hidden-valley-lake-ca&at=2026-09-19%2018:00&lure=Drop%20shot")
        html = r.get_data(as_text=True)
        self.assertIn('value="2026-09-19"', html)
        self.assertIn('value="18:00"', html)
        self.assertIn('value="Drop shot"', html)


if __name__ == "__main__":
    unittest.main()
