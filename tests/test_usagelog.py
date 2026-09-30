"""External API usage log — aggregate budget counts, no PII."""
import tempfile
import unittest
from pathlib import Path

import usagelog


class UsageLogTest(unittest.TestCase):
    def setUp(self):
        self.log = Path(tempfile.mkdtemp(prefix="fw_usage_")) / "usage.jsonl"

    def test_location_calls_are_counted(self):
        usagelog.record("open-meteo", "forecast-batch", locations=4, log=self.log)
        usagelog.record("open-meteo", "archive", locations=1, status=200, log=self.log)
        rows = usagelog.parse(self.log.read_text().splitlines())
        s = usagelog.summarize(days=1, rows=rows)
        self.assertEqual(s["requests"], 2)
        self.assertEqual(s["calls"], 5)
        self.assertEqual(dict(s["by_service"])["open-meteo"], 5)
        self.assertEqual(s["today_calls"], 5)

    def test_malformed_rows_are_dropped(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.log.write_text("not json\n"
                            + '{"ts": "%s", "service": "x", "locations": 2}\n' % now)
        rows = usagelog.parse(self.log.read_text().splitlines())
        self.assertEqual(len(rows), 1)
        s = usagelog.summarize(days=1, rows=rows)
        self.assertEqual(s["calls"], 2)


if __name__ == "__main__":
    unittest.main()
