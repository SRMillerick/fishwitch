"""Telemetry contract: aggregate only, no PII, feeds excluded from page counts."""
import tempfile
import unittest
from datetime import datetime, timezone
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
    def test_parse_drops_malformed_and_offshape(self):
        rows = telemetry.parse(['{"path": "/"}', "not json",
                                '{"lake": "x"}', '{"path": "/kb"}'])
        self.assertEqual([r["path"] for r in rows], ["/", "/kb"])

    def test_summarize_accepts_preparsed_rows(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = telemetry.parse([
            '{"ts": "%s", "path": "/", "lake": "", "ref": ""}' % now,
            "not json",
        ])
        s = telemetry.summarize(days=1, rows=rows)
        self.assertEqual(s["total"], 1)
        self.assertEqual(s["by_path"][0], ("/", 1))

    def test_channels_classify_and_quarantine_spam(self):
        telemetry.record("/", log=self.log)                                    # direct
        telemetry.record("/", ref="https://www.google.com/search?q=o", log=self.log)
        telemetry.record("/report", ref="https://baromoon.com/outlook", log=self.log)
        telemetry.record("/", ref="https://t.co/abc", log=self.log)
        telemetry.record("/", ref="https://backlinkspace.com/", log=self.log)
        telemetry.record("/", ref="https://example.com/page", log=self.log)
        s = telemetry.summarize(days=1, log=self.log, top=10)
        self.assertEqual(dict(s["channels"]),
                         {"search": 1, "social": 1, "external": 1,
                          "internal": 1, "direct": 1, "spam": 1})
        self.assertEqual(s["spam_refs"], [("backlinkspace.com", 1)])
        self.assertEqual(dict(s["by_ref"]),
                         {"www.google.com": 1, "t.co": 1, "example.com": 1})

    def test_bot_flag_derived_from_ua_never_stores_the_ua(self):
        telemetry.record("/", ua="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", log=self.log)
        telemetry.record("/", ua="Mozilla/5.0 (Macintosh) Safari/605", log=self.log)
        raw = self.log.read_text()
        self.assertNotIn("Googlebot", raw)
        self.assertNotIn("Mozilla", raw)
        rows = telemetry.read(self.log)
        self.assertTrue(rows[0]["bot"])
        self.assertNotIn("bot", rows[1])
        s = telemetry.summarize(days=1, log=self.log)
        self.assertEqual(s["bots"], 1)
        self.assertEqual(s["bot_rows"], 1)

    def test_classify_ref(self):
        cases = {"": "direct", "www.google.com": "search",
                 "news.ycombinator.com": "social", "www.baromoon.com": "internal",
                 "digitizeseo.com": "spam", "fishingforum.example": "external"}
        for host, channel in cases.items():
            self.assertEqual(telemetry.classify_ref(host), channel, host)


if __name__ == "__main__":
    unittest.main()
