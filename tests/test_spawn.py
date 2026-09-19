"""Spawn phase — T2 water-temp bands, warming gate, supersession, separation."""
import unittest

import tactics as tx


def ctx(**over):
    base = dict(light="moderate day", cloud=30, wind_mph=6, temp_f=70, water_f=60,
                hour_ruler="Venus", solunar=None, moon_fruitful="fruitful",
                pressure_word="steady", structure_notes=[], lake_state="",
                bottom=None, month=4)
    base.update(over)
    return base


class SpawnPhaseTest(unittest.TestCase):
    def test_phase_bands(self):
        self.assertEqual(tx.spawn_phase(47, 4), "")
        self.assertEqual(tx.spawn_phase(48, 4), "pre-spawn")
        self.assertEqual(tx.spawn_phase(59, 4), "pre-spawn")
        self.assertEqual(tx.spawn_phase(60, 4), "spawn")
        self.assertEqual(tx.spawn_phase(74, 4), "spawn")
        self.assertEqual(tx.spawn_phase(75, 4), "post-spawn")
        self.assertEqual(tx.spawn_phase(90, 6), "post-spawn")
        self.assertEqual(tx.spawn_phase(96, 6), "")

    def test_warming_months_gate(self):
        self.assertEqual(tx.spawn_phase(64, 10), "")   # fall water temp is not spawn
        self.assertEqual(tx.spawn_phase(64, 1), "")
        self.assertEqual(tx.spawn_phase(64, 2), "spawn")

    def test_null_safety(self):
        self.assertEqual(tx.spawn_phase(None, 4), "")
        self.assertEqual(tx.spawn_phase(64, None), "")
        self.assertEqual(tx.spawn_phase("nope", 4), "")

    def test_fits_are_t5_and_missing_phases_are_zero(self):
        self.assertGreater(tx.spawn_fit("trig", "pre-spawn")[0],
                           tx.spawn_fit("dropshot", "pre-spawn")[0])
        self.assertGreater(tx.spawn_fit("wacky", "spawn")[0],
                           tx.spawn_fit("trig", "spawn")[0])
        self.assertGreater(tx.spawn_fit("dropshot", "post-spawn")[0],
                           tx.spawn_fit("wacky", "post-spawn")[0])
        self.assertEqual(tx.spawn_fit("trig", ""), (0.0, ""))
        self.assertEqual(tx.spawn_fit("missing", "spawn"), (0.0, ""))

    def test_phase_notes_are_cited(self):
        for phase in ("pre-spawn", "spawn", "post-spawn"):
            note, cits = tx.spawn_note(phase)
            self.assertTrue(note)
            self.assertTrue(cits)
            for c in cits:
                self.assertTrue(c.get("quote") and c.get("url"))


class SpawnScoringTest(unittest.TestCase):
    def _score(self, eid, **over):
        return tx.score_entry(tx.entry("bass", eid), ctx(**over))[0]

    def test_each_phase_separates(self):
        water, month = 56, 3
        self.assertGreater(self._score("trig", water_f=water, month=month),
                           self._score("dropshot", water_f=water, month=month))
        water, month = 66, 4
        self.assertGreater(self._score("wacky", water_f=water, month=month),
                           self._score("trig", water_f=water, month=month))
        water, month = 80, 6
        self.assertGreater(self._score("dropshot", water_f=water, month=month),
                           self._score("wacky", water_f=water, month=month))

    def test_spawn_supersedes_season(self):
        # June is both a summer month and a warming month: spawn (the specific
        # signal) must win, and the season fit must not appear in the reasons
        _, why, _ = tx.score_entry(tx.entry("bass", "trig"), ctx(water_f=66, month=6))
        self.assertFalse(any(w.startswith("summer:") for w in why), why)
        _, why_w, _ = tx.score_entry(tx.entry("bass", "wacky"), ctx(water_f=66, month=6))
        self.assertTrue(any(w.startswith("spawn:") for w in why_w), why_w)

    def test_total_tiebreak_cap_with_cover(self):
        plain = self._score("trig", water_f=56, month=3, bottom=None)
        both = self._score("trig", water_f=56, month=3, bottom="grass")
        self.assertLessEqual(abs(both - plain), tx.TIEBREAK_CAP + 1e-9)

    def test_cooling_season_still_uses_season_fits(self):
        # October is not a warming month: the fall season fit must still apply
        _, why, _ = tx.score_entry(tx.entry("bass", "trig"), ctx(water_f=64, month=10))
        self.assertTrue(any(w.startswith("fall:") for w in why), why)


if __name__ == "__main__":
    unittest.main()
