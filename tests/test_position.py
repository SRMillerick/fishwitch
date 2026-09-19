"""Derived fish-position state — trigger null-safety + T5 class fits
(kb/position.json, kb/CONDITIONS.md). No network, no KB mutation."""
import unittest

import tactics as tx

MIX_STRAT = "warm-monomictic — one big fall turnover"
MIX_POLY = "polymictic — mixes on any strong front"


def ctx(**over):
    base = dict(light="bright day", cloud=20, wind_mph=6, temp_f=78, water_f=78,
                hour_ruler="Venus", solunar=None, moon_fruitful="fruitful",
                pressure_word="steady", structure_notes=[], lake_state="",
                bottom=None, month=7)
    base.update(over)
    return base


class PositionStateTest(unittest.TestCase):
    def test_derives_only_for_stratifying_lakes_in_warm_water(self):
        self.assertEqual(tx.position_state(MIX_STRAT, 78, 7), "stratified")
        self.assertEqual(tx.position_state(MIX_STRAT, 75, 9), "stratified")
        self.assertEqual(tx.position_state(MIX_POLY, 78, 7), "")
        self.assertEqual(tx.position_state(MIX_STRAT, 70, 7), "")
        self.assertEqual(tx.position_state(MIX_STRAT, 78, 1), "")

    def test_null_safe_without_inputs(self):
        self.assertEqual(tx.position_state(None, 78, 7), "")
        self.assertEqual(tx.position_state("", 78, 7), "")
        self.assertEqual(tx.position_state(MIX_STRAT, None, 7), "")
        self.assertEqual(tx.position_state(MIX_STRAT, 78, None), "")
        self.assertEqual(tx.position_state(MIX_STRAT, "nope", 7), "")

    def test_yields_to_other_position_owners(self):
        self.assertEqual(tx.position_state(MIX_STRAT, 78, 7, "post-turnover"), "")
        self.assertEqual(tx.position_state(MIX_STRAT, 78, 7, "hot-streak"), "")
        self.assertEqual(tx.position_state(MIX_STRAT, 78, 7, "", "post-spawn"), "")


class PositionFitTest(unittest.TestCase):
    def test_suspend_leads_the_fall_class(self):
        suspend, _ = tx.position_fit("dropshot", "stratified")
        fall, _ = tx.position_fit("wacky", "stratified")
        bottom, _ = tx.position_fit("neko", "stratified")
        self.assertGreater(suspend, fall)
        self.assertGreater(fall, bottom)
        self.assertEqual(bottom, 0.0)

    def test_no_state_is_a_noop(self):
        for eid in ("dropshot", "wacky", "neko"):
            self.assertEqual(tx.position_fit(eid, ""), (0.0, ""))


class PositionScoringTest(unittest.TestCase):
    def _score(self, eid, **over):
        return tx.score_entry(tx.entry("bass", eid), ctx(**over))[0]

    def test_class_deltas_are_capped_and_ordered(self):
        dropshot = self._score("dropshot", position="stratified") - self._score("dropshot")
        wacky = self._score("wacky", position="stratified") - self._score("wacky")
        neko = self._score("neko", position="stratified") - self._score("neko")
        self.assertAlmostEqual(dropshot, tx.FIT_CAP, places=6)     # fit 2 → +0.5
        self.assertAlmostEqual(wacky, tx.FIT_SCALE, places=6)      # fit 1 → +0.25
        self.assertEqual(neko, 0.0)                                # bottom drag: no claim

    def test_no_position_context_is_unchanged(self):
        for eid in ("dropshot", "wacky", "neko"):
            self.assertEqual(self._score(eid), self._score(eid, position=""), eid)

    def test_position_stays_within_the_total_tiebreak_cap(self):
        for eid in ("dropshot", "wacky", "neko", "trig", "carolina"):
            plain = self._score(eid, month=10, bottom=None)
            loaded = self._score(eid, month=10, bottom="grass", position="stratified")
            self.assertLessEqual(abs(loaded - plain), tx.TIEBREAK_CAP + 1e-9, eid)


if __name__ == "__main__":
    unittest.main()
