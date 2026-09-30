"""Historical agreement replay — the pure run-selection math (no network)."""
import unittest
from datetime import datetime, timezone

from tools import calibration_confidence as cc


class CandidateRunsTest(unittest.TestCase):
    def test_runs_snap_to_the_six_hour_cadence(self):
        # planning 21:00 UTC, GFS lag 4h → 17:00 → snap down to 12:00
        when = datetime(2026, 9, 17, 21, 0, tzinfo=timezone.utc)
        runs = cc._candidate_runs(when, "gfs_seamless")
        self.assertEqual(runs[0], datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(all(r.hour in (0, 6, 12, 18) for r in runs))
        self.assertEqual(len({r for r in runs}), len(runs))
        self.assertEqual(runs, sorted(runs, reverse=True))

    def test_ecmwf_lag_is_longer_than_gfs(self):
        when = datetime(2026, 9, 17, 21, 0, tzinfo=timezone.utc)
        gfs = cc._candidate_runs(when, "gfs_seamless")[0]
        ecmwf = cc._candidate_runs(when, "ecmwf_ifs025")[0]
        self.assertLessEqual(ecmwf, gfs)


if __name__ == "__main__":
    unittest.main()
