"""retire() — promoted entries leave the active collection but stay audited."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from adapters import kb_ingest


class RetireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fw_retire_"))
        (self.tmp / "trends.json").write_text(json.dumps({
            "label": "Trend signals",
            "trends": [
                {"id": "keep-me", "url": "https://x.test/keep"},
                {"id": "retire-me", "url": "https://x.test/old",
                 "signal": "tournament", "quote": "a stale signal"},
            ]}))
        self._kb = kb_ingest.KB
        kb_ingest.KB = self.tmp

    def tearDown(self):
        kb_ingest.KB = self._kb
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retire_removes_entry_and_logs_it(self):
        log = kb_ingest.retire("trends", "retire-me", "tester", "superseded")
        self.assertIsNotNone(log)
        kb = json.loads((self.tmp / "trends.json").read_text())
        self.assertEqual([t["id"] for t in kb["trends"]], ["keep-me"])
        row = json.loads((self.tmp / "retired.log").read_text().splitlines()[-1])
        self.assertEqual(row["entry_id"], "retire-me")
        self.assertEqual(row["by"], "tester")
        self.assertEqual(row["reason"], "superseded")
        self.assertEqual(row["collection"], "trends")
        self.assertEqual(row["entry"]["url"], "https://x.test/old")
        self.assertEqual(row["entry"]["quote"], "a stale signal")

    def test_retire_missing_returns_none(self):
        self.assertIsNone(kb_ingest.retire("trends", "not-there", "tester"))
        self.assertEqual(
            [t["id"] for t in json.loads((self.tmp / "trends.json").read_text())["trends"]],
            ["keep-me", "retire-me"])


if __name__ == "__main__":
    unittest.main()
