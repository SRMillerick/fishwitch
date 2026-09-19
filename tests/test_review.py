"""Weight-weighted calibration — the ledger's size-variance correction."""
import unittest

from review import session_weight, weighted_catch_avg, weighted_presentation


def row(pres, overall, lb=None, skunk=False):
    e = {}
    if lb is not None:
        e["total_lb"] = lb
    return dict(skunk=skunk, pres=pres, overall=overall, entry=e)


class SessionWeightTest(unittest.TestCase):
    def test_known_weight_wins(self):
        self.assertEqual(session_weight(row("exact", 7.0, lb=4.5)), 4.5)
        self.assertEqual(session_weight(row("exact", 7.0)), 1.0)

    def test_best_lb_fallback(self):
        g = row("exact", 7.0)
        g["entry"]["best_lb"] = 3.2
        self.assertEqual(session_weight(g), 3.2)


class WeightedMetricsTest(unittest.TestCase):
    ROWS = [row("miss", 6.3, lb=4.5),          # light fish, low score
            row("style", 6.4, lb=36.0),        # the bag that matters
            row("exact", 7.0, lb=1.0),
            dict(skunk=True, pres=None, overall=6.5, entry={})]

    def test_weighted_presentation_dominates_with_the_big_bag(self):
        shares = weighted_presentation(self.ROWS)
        self.assertEqual(shares["style"], round(100 * 36 / 41.5))
        self.assertLess(shares["miss"], 15)

    def test_weighted_catch_avg(self):
        # (6.3*4.5 + 6.4*36 + 7.0*1.0) / 41.5
        expected = round((6.3 * 4.5 + 6.4 * 36 + 7.0) / 41.5, 1)
        self.assertEqual(weighted_catch_avg(self.ROWS), expected)

    def test_unweighted_fallback(self):
        rows = [row("exact", 8.0), row("miss", 6.0)]
        self.assertEqual(weighted_presentation(rows), {"exact": 50, "miss": 50})
        self.assertEqual(weighted_catch_avg(rows), 7.0)

    def test_empty(self):
        self.assertEqual(weighted_presentation([]), {})
        self.assertIsNone(weighted_catch_avg([]))


if __name__ == "__main__":
    unittest.main()
