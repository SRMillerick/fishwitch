"""Telemetry contract: aggregate only, no PII, feeds excluded from page counts."""
import tempfile
import unittest
from pathlib import Path

import telemetry


class TelemetryTest(unittest.TestCase):
    def setUp(self):
        self.log = Path(tempfile.mkdtemp(prefix="fw_tel_")) / "pages.jsonl"

    def test_record_read_summarize(self):
        telemetry.record("/", log=self.log)
        telemetry.record("/report", lake="hidden-valley-lake-ca",
                         ref="https://www.google.com/search?q=bass", log=self.log)
        telemetry.record("/report", lake="hidden-valley-lake-ca", log=self.log)
        s = telemetry.summarize(days=1, log=self.log, top=5)
        self.assertEqual(s["total"], 3)
        self.assertEqual(dict(s["by_path"])["/report"], 2)
        self.assertEqual(s["by_lake"][0], ("hidden-valley-lake-ca", 2))
        self.assertEqual(s["by_ref"][0][0], "www.google.com")

    def test_referrer_host_only(self):
        telemetry.record("/", ref="https://example.com/secret/path?token=x", log=self.log)
        rows = telemetry.read(self.log)
        self.assertEqual(rows[0]["ref"], "example.com")

    def test_lake_is_sanitized_and_bounded(self):
        self.assertEqual(telemetry.normalize_lake("Bad Lake!!/etc"), "badlakeetc")
        self.assertEqual(telemetry.normalize_lake("a"), "")
        self.assertEqual(telemetry.normalize_lake("x" * 300), "")

    def test_skip_rules(self):
        for path in ("/static/style.css", "/out/dropshot/amazon",
                     "/ledger.ics", "/outlook.rss", "/robots.txt",
                     "/sitemap.xml", "/api/report", "/stats"):
            self.assertFalse(telemetry.should_count(path), path)
        for path in ("/", "/report", "/outlook", "/lakes", "/lake/x", "/kb"):
            self.assertTrue(telemetry.should_count(path), path)


if __name__ == "__main__":
    unittest.main()
