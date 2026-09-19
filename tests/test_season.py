"""Season-phase tie-break — sourced summer/fall fits, null-safe elsewhere."""
import unittest

import tactics as tx


def ctx(**over):
    base = dict(light="bright day", cloud=20, wind_mph=6, temp_f=78, water_f=74,
                hour_ruler="Venus", solunar=None, moon_fruitful="fruitful",
                pressure_word="steady", structure_notes=[], lake_state="",
                bottom=None, month=7)
    base.update(over)
    return base


class SeasonPhaseTest(unittest.TestCase):
    def test_month_mapping(self):
        self.assertEqual(tx.season_phase(1), "winter")
        self.assertEqual(tx.season_phase(3), "spring")
        self.assertEqual(tx.season_phase(7), "summer")
        self.assertEqual(tx.season_phase(10), "fall")
        self.assertEqual(tx.season_phase(12), "winter")
        self.assertEqual(tx.season_phase(None), "")
        self.assertEqual(tx.season_phase("nope"), "")

    def test_sourced_fits(self):
        trig_summer, _ = tx.season_fit("trig", 7)
        carolina_summer, _ = tx.season_fit("carolina", 7)
        trig_fall, _ = tx.season_fit("trig", 10)
        neko_fall, _ = tx.season_fit("neko", 10)
        self.assertGreater(trig_summer, 0)
        self.assertGreater(carolina_summer, 0)
        self.assertLess(trig_fall, 0)
        self.assertLess(neko_fall, 0)

    def test_unsourced_phases_and_rigs_are_null(self):
        for eid in ("dropshot", "wacky", "neko"):
            self.assertEqual(tx.season_fit(eid, 7)[0], 0.0, eid)   # no summer claim
        for eid in ("dropshot", "wacky"):
            self.assertEqual(tx.season_fit(eid, 10)[0], 0.0, eid)  # not bottom-crawling
        self.assertEqual(tx.season_fit("trig", 4)[0], 0.0)          # spring unsourced
        self.assertEqual(tx.season_fit("trig", 1)[0], 0.0)          # winter unsourced


class SeasonScoringTest(unittest.TestCase):
    def _score(self, eid, **over):
        return tx.score_entry(tx.entry("bass", eid), ctx(**over))[0]

    def test_summer_separates_texas_and_carolina(self):
        trig = self._score("trig", month=7)
        carolina = self._score("carolina", month=7)
        dropshot = self._score("dropshot", month=7)
        self.assertGreater(trig, dropshot)
        self.assertGreater(carolina, dropshot)

    def test_fall_penalizes_bottom_crawlers(self):
        dropshot = self._score("dropshot", month=10)
        wacky = self._score("wacky", month=10)
        trig = self._score("trig", month=10)
        neko = self._score("neko", month=10)
        self.assertGreater(dropshot, trig)
        self.assertGreaterEqual(wacky, neko)

    def test_month_is_null_safe(self):
        # month=None / 0 → no phase → identical to the no-season baseline
        for eid in ("trig", "carolina", "neko", "dropshot", "wacky"):
            self.assertEqual(self._score(eid, month=None), self._score(eid, month=0), eid)

    def test_total_tiebreak_cap(self):
        # season + cover together must stay within the total cap
        for eid in ("trig", "carolina", "neko", "dropshot", "wacky"):
            plain = self._score(eid, month=7, bottom=None)
            both = self._score(eid, month=10, bottom="grass")
            self.assertLessEqual(abs(both - plain), tx.TIEBREAK_CAP + 1e-9, eid)


if __name__ == "__main__":
    unittest.main()
