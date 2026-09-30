"""Affiliate summary: window filter, bot split, commissioned-only counting,
and the 3-sale deadline."""
import unittest
from datetime import date, datetime, timedelta, timezone

import affiliate


def _row(days_ago=1, retailer="amazon", entry="wacky", src="tackle", bot=False):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    r = dict(ts=ts, entry=entry, retailer=retailer, src=src)
    if bot:
        r["bot"] = True
    return r


class AffiliateSummaryTest(unittest.TestCase):
    def test_window_bot_split_and_commissioned_only(self):
        rows = [
            _row(1),                                            # amazon, in window
            _row(2, retailer="manufacturer", entry="dropshot"),  # no commission
            _row(3, retailer="zman", entry="senko"),             # no commission
            _row(1, bot=True, entry="egg-sinker"),               # crawler follow
            _row(10, entry="old"),                               # outside the window
        ]
        s = affiliate.summarize(rows, days=7)
        self.assertEqual(s["total"], 3)          # bot + old excluded
        self.assertEqual(s["bots"], 1)
        self.assertEqual(s["amazon"], 1)
        self.assertEqual(s["by_entry"], [("wacky", 1)])
        self.assertCountEqual(s["other"], [("manufacturer", 1), ("zman", 1)])

    def test_empty_log_is_safe(self):
        s = affiliate.summarize([], days=7)
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["share"], 0.0)

    def test_deadline_is_the_180_day_clock(self):
        self.assertEqual(affiliate.DEADLINE.isoformat(), "2027-03-27")
        self.assertEqual(affiliate.DEADLINE, affiliate.APPROVED + timedelta(days=180))
        self.assertEqual(affiliate.TARGET, 3)

    def test_share_math(self):
        rows = [_row(1), _row(1, retailer="manufacturer")]
        s = affiliate.summarize(rows, days=7)
        self.assertEqual(s["amazon"], 1)
        self.assertAlmostEqual(s["share"], 0.5)


if __name__ == "__main__":
    unittest.main()
