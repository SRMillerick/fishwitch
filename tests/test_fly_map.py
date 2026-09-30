"""Conventional → fly mapping (kb/fly_map.json): integrity of the T5 table and
the display helper. The map is editorial and display-only — it must never score."""
import json
import unittest
from pathlib import Path

import tactics as tx

KB = Path(__file__).resolve().parent.parent / "kb"


class FlyMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmap = json.loads((KB / "fly_map.json").read_text())
        cls.bass = json.loads((KB / "bass.json").read_text())
        cls.ids = {c["id"] for c in cls.bass["cats"]}
        pend = KB / "pending" / "bass"
        cls.pending = {p.stem for p in pend.glob("*.json")} if pend.exists() else set()

    def test_every_mapping_points_at_a_real_or_pending_fly(self):
        for conv, m in self.fmap["mappings"].items():
            self.assertIn(conv, self.ids, f"{conv}: conventional entry missing")
            self.assertIn(m["fly"], self.ids | self.pending,
                          f"{conv}: unknown fly {m['fly']} (not promoted or drafted)")
            self.assertTrue(m.get("note"), f"{conv}: mapping has no note")

    def test_the_anglers_trio_maps(self):
        tx._FLY_MAP = None
        self.assertEqual(tx.fly_counterpart("wacky")["fly"], "fly-nymph")
        self.assertEqual(tx.fly_counterpart("dropshot")["fly"], "fly-nymph")
        self.assertEqual(tx.fly_counterpart("urchin")["fly"], "fly-crayfish")

    def test_helper_falls_back_to_the_map_label(self):
        tx._FLY_MAP = None
        fc = tx.fly_counterpart("urchin")
        self.assertIn("Crayfish", fc["fly_label"])
        self.assertEqual(fc["confidence"], "verified")
        self.assertIsNone(tx.fly_counterpart("not-a-rig"))

    def test_mapping_is_human_verified_but_display_only(self):
        # the mappings are editorial synthesis, reviewed by the human
        self.assertEqual(self.fmap["provenance"]["confidence"], "verified")
        self.assertEqual(self.fmap["provenance"]["verified_by"], "sean")
        for m in self.fmap["mappings"].values():
            self.assertEqual(set(m) - {"fly", "fly_label", "note"}, set(),
                             "the map should carry display fields only")


if __name__ == "__main__":
    unittest.main()
