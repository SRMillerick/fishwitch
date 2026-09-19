"""ICS/RSS rendering — synthetic rows only (no network, no weather)."""
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime

import feeds

LAKE = {"id": "hidden-valley-lake-ca", "name": "Hidden Valley Lake",
        "tz": "America/Los_Angeles"}
ROWS = [
    dict(start=datetime(2026, 9, 20, 20, 0), end=datetime(2026, 9, 20, 22, 0),
         overall=7.6, prime=datetime(2026, 9, 20, 20, 45),
         picks=["Drop shot", "Wacky, rigged"]),
    dict(start=datetime(2026, 9, 21, 5, 30), end=datetime(2026, 9, 21, 7, 30),
         overall=7.0, prime=None, picks=[]),
]


class IcalTest(unittest.TestCase):
    def test_structure_and_utc(self):
        body = feeds.ical(ROWS, LAKE)
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(body.rstrip().endswith("END:VCALENDAR"))
        self.assertEqual(body.count("BEGIN:VEVENT"), 2)
        # 20:00 PDT == 03:00Z next day; 5:30 PDT == 12:30Z
        self.assertIn("DTSTART:20260921T030000Z", body)
        self.assertIn("DTSTART:20260921T123000Z", body)

    def test_text_escaping(self):
        body = feeds.ical(ROWS, LAKE)
        self.assertIn(r"SUMMARY:baromoon S · 7.6 — Drop shot + Wacky\, rigged", body)
        self.assertIn("https://baromoon.com/report?lake=hidden-valley-lake-ca", body)

    def test_unknown_tz_falls_back_to_utc(self):
        body = feeds.ical(ROWS, {**LAKE, "tz": "Not/AZone"})
        self.assertIn("DTSTART:20260920T200000Z", body)  # naive treated as UTC


class RssTest(unittest.TestCase):
    def test_parses_and_counts(self):
        body = feeds.rss(ROWS, LAKE)
        root = ET.fromstring(body)
        items = root.findall("./channel/item")
        self.assertEqual(len(items), 2)
        self.assertIn("Hidden Valley Lake", root.findtext("./channel/title"))
        self.assertEqual(items[0].findtext("guid"), "20260920T200000-hidden-valley-lake-ca")

    def test_bad_chars_are_escaped(self):
        rows = [dict(start=datetime(2026, 9, 20, 20, 0),
                     end=datetime(2026, 9, 20, 22, 0), overall=7.1, prime=None,
                     picks=["A & B <script>"])]
        root = ET.fromstring(feeds.rss(rows, LAKE))  # must parse despite the payload
        self.assertIn("A & B <script>", root.findtext("./channel/item/description"))


if __name__ == "__main__":
    unittest.main()
