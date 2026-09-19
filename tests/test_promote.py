"""promote() round-trips — the KB merge paths that a bad draft could corrupt.

List collections (species `cats`) match by id; dict collections (substrate
`entries`) key by id and are created on first patch. Uses a throwaway KB copy;
the real kb/ is never touched.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from adapters import kb_ingest


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fw_promote_"))
        (self.tmp / "pending" / "substrate").mkdir(parents=True)
        (self.tmp / "pending" / "bass").mkdir(parents=True)
        (self.tmp / "bass.json").write_text(json.dumps({
            "label": "bass", "cats": [{"id": "carolina", "label": "Carolina rig",
                                       "conditions": {}, "provenance": {"confidence": "sourced"}}]}))
        (self.tmp / "substrate.json").write_text(json.dumps({
            "label": "Substrate", "bottoms": ["grass"],
            "entries": {"dropshot": {"grass": {"fit": 2, "note": "seed"}}}}))
        self._kb, self._pending = kb_ingest.KB, kb_ingest.PENDING
        kb_ingest.KB, kb_ingest.PENDING = self.tmp, self.tmp / "pending"

    def tearDown(self):
        kb_ingest.KB, kb_ingest.PENDING = self._kb, self._pending
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _draft(self, kind, entry_id, patch, target_key=None, target_file=None):
        d = {"entry_id": entry_id, "species_kb": kind, "status": "pending",
             "patch": patch,
             "provenance": {"seed_author": "test", "source": "unit test"},
             "review": {}}
        if target_key:
            d["target_key"] = target_key
        if target_file:
            d["target_file"] = target_file
        p = self.tmp / "pending" / kind / f"{entry_id}.json"
        p.write_text(json.dumps(d))
        return p

    def test_dict_patch_merges_existing(self):
        self._draft("substrate", "dropshot", {"grass": {"fit": 1, "note": "updated"}},
                    target_key="entries", target_file="substrate.json")
        kb_ingest.promote("substrate", "dropshot", "tester")
        sub = json.loads((self.tmp / "substrate.json").read_text())
        self.assertEqual(sub["entries"]["dropshot"]["grass"]["fit"], 1)
        self.assertEqual(sub["entries"]["dropshot"]["grass"]["note"], "updated")

    def test_dict_patch_creates_missing_entry(self):
        self._draft("substrate", "trig", {"grass": {"fit": 2, "confidence": "sourced"}},
                    target_key="entries", target_file="substrate.json")
        kb_ingest.promote("substrate", "trig", "tester")
        sub = json.loads((self.tmp / "substrate.json").read_text())
        self.assertIn("trig", sub["entries"])
        self.assertEqual(sub["entries"]["trig"]["grass"]["fit"], 2)
        self.assertFalse((self.tmp / "pending" / "substrate" / "trig.json").exists(),
                         "draft should be consumed")

    def test_list_patch_still_merges(self):
        self._draft("bass", "carolina", {"note": "promoted note"})
        kb_ingest.promote("bass", "carolina", "tester")
        b = json.loads((self.tmp / "bass.json").read_text())
        c = next(x for x in b["cats"] if x["id"] == "carolina")
        self.assertEqual(c["note"], "promoted note")

    def test_missing_draft_returns_none(self):
        self.assertIsNone(kb_ingest.promote("bass", "nope", "tester"))


if __name__ == "__main__":
    unittest.main()
