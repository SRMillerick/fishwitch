"""Clarity input — normalize, color selection, precedence."""
import unittest

import tactics as tx


class ClarityTest(unittest.TestCase):
    def test_normalize(self):
        for v in ("clear", "high", "CLEAN", " clean "):
            self.assertEqual(tx.normalize_clarity(v), "high")
        for v in ("stained", "dirty", "muddy", "turbid", "low"):
            self.assertEqual(tx.normalize_clarity(v), "low")
        for v in (None, "", "unknown"):
            self.assertEqual(tx.normalize_clarity(v), "")

    def test_low_clarity_forces_contrast(self):
        p = tx.color_principle(dict(light="moderate day", cloud=10, clarity="stained"))
        self.assertEqual(p["id"], "contrast-over-color")

    def test_high_clarity_allows_color(self):
        p = tx.color_principle(dict(light="moderate day", cloud=10, clarity="clear"))
        self.assertEqual(p["id"], "clear-water-color-vision")

    def test_light_and_turnover_outrank_clarity(self):
        self.assertEqual(tx.color_principle(
            dict(light="night", cloud=10, clarity="clear"))["id"], "low-light-rods")
        self.assertEqual(tx.color_principle(
            dict(light="moderate day", cloud=10, lake_state="post-turnover",
                 clarity="clear"))["id"], "depth-absorbs-long-wavelengths")

    def test_unknown_clarity_keeps_old_behavior(self):
        a = tx.color_principle(dict(light="golden", cloud=10))["id"]
        b = tx.color_principle(dict(light="golden", cloud=10, clarity="unknown"))["id"]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
