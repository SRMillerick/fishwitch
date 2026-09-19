"""Deterministic scoring tests — the tie-break layer's arithmetic and the
null-safe contract (kb/CONDITIONS.md). No network, no KB mutation."""
import unittest

import tactics as tx


def ctx(**over):
    base = dict(light="bright day", cloud=20, wind_mph=6, temp_f=78, water_f=74,
                hour_ruler="Venus", solunar=None, moon_fruitful="fruitful",
                pressure_word="steady", structure_notes=[], lake_state="",
                bottom=None)
    base.update(over)
    return base


class FitDeltaTest(unittest.TestCase):
    def test_scale_and_caps(self):
        self.assertEqual(tx.FIT_SCALE, 0.25)
        self.assertEqual(tx._fit_delta(0), 0.0)
        self.assertEqual(tx._fit_delta(1), 0.25)
        self.assertEqual(tx._fit_delta(2), 0.5)
        self.assertEqual(tx._fit_delta(3), 0.5)      # capped
        self.assertEqual(tx._fit_delta(-1), -0.25)
        self.assertEqual(tx._fit_delta(-2), -0.5)
        self.assertEqual(tx._fit_delta(-5), -0.5)    # capped

    def test_monotonic(self):
        vals = [tx._fit_delta(f) for f in (-3, -2, -1, 0, 1, 2, 3)]
        self.assertEqual(vals, sorted(vals))


class ScoreEntryTest(unittest.TestCase):
    def test_unknown_bottom_is_null_safe(self):
        for eid in ("dropshot", "trig", "wacky", "neko", "carolina"):
            cat = tx.entry("bass", eid)
            a, _, _ = tx.score_entry(cat, ctx(bottom=None))
            b, _, _ = tx.score_entry(cat, ctx(bottom="cheese"))  # not a registry bottom
            self.assertEqual(a, b, f"{eid}: unknown bottom changed the score")

    def test_cover_fit_is_capped(self):
        """A declared bottom moves a rig by at most the per-dimension cap."""
        for eid in ("trig", "carolina", "dropshot", "wacky", "neko"):
            cat = tx.entry("bass", eid)
            plain, _, _ = tx.score_entry(cat, ctx(bottom=None))
            grassy, _, _ = tx.score_entry(cat, ctx(bottom="grass"))
            self.assertLessEqual(abs(grassy - plain), tx.FIT_CAP + 1e-9, eid)

    def test_deterministic_repeat(self):
        cat = tx.entry("bass", "trig")
        runs = [tx.score_entry(cat, ctx(bottom="grass")) for _ in range(5)]
        self.assertEqual(len({(s, tuple(w)) for s, w, _ in runs}), 1)

    def test_rejection_is_reported(self):
        # walking topwater excludes bright day — out of band, not a silent zero
        cat = tx.entry("bass", "walker")
        sc, why, rej = tx.score_entry(cat, ctx(light="bright day"))
        self.assertEqual(sc, 0.0)
        self.assertTrue(rej)


class RecommendTest(unittest.TestCase):
    def test_order_is_stable_and_descending(self):
        cats = [(tx.entry("bass", e), e) for e in ("trig", "dropshot", "neko", "wacky")]
        got = tx.recommend(ctx(bottom="grass"), cats, top_n=4)
        scores = [s for _, s, _ in got]
        self.assertEqual(scores, sorted(scores, reverse=True))
        again = tx.recommend(ctx(bottom="grass"), cats, top_n=4)
        self.assertEqual([c["id"] for c, _, _ in got], [c["id"] for c, _, _ in again])


if __name__ == "__main__":
    unittest.main()
