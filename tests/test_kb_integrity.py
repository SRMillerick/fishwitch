"""KB schema invariants — the checks a human reviewer would otherwise have to
remember, especially after a promote() merge (list and dict collections).
These do not freeze content; they freeze shape and provenance discipline."""
import json
import unittest
from pathlib import Path

KB = Path(__file__).resolve().parent.parent / "kb"
CONFIDENCE = {"verified", "sourced", "unverified-editorial"}
CITATION_KEYS = {"claim", "tier", "source", "quote", "found"}


def entries_of(path: Path):
    d = json.loads(path.read_text())
    if isinstance(d.get("cats"), list):
        return [(c.get("id"), c) for c in d["cats"]]
    if isinstance(d.get("entries"), dict):
        return list(d["entries"].items())
    return [(e.get("id"), e) for e in d.get("trends", []) + d.get("principles", [])]


class KBSchemaTest(unittest.TestCase):
    def test_species_entries_have_provenance(self):
        for name in ("bass", "trout", "catfish", "panfish"):
            p = KB / f"{name}.json"
            if not p.exists():
                continue
            entries = entries_of(p)
            self.assertTrue(entries, name)
            for eid, e in entries:
                self.assertTrue(eid, f"{name}: entry without id")
                self.assertIn((e.get("provenance") or {}).get("confidence"),
                              CONFIDENCE, f"{name}/{eid}: bad confidence")
                for cit in e.get("citations", []) or []:
                    missing = CITATION_KEYS - set(cit)
                    self.assertFalse(missing, f"{name}/{eid}: citation missing {missing}")

    def test_substrate_fits_are_capped_scale_and_labelled(self):
        d = json.loads((KB / "substrate.json").read_text())
        for eid, bottoms in d.get("entries", {}).items():
            for bottom, fit in bottoms.items():
                self.assertIn(bottom, d.get("bottoms", []), f"{eid}: unknown bottom {bottom}")
                v = fit.get("fit")
                self.assertIsInstance(v, (int, float), f"{eid}/{bottom}: fit not numeric")
                self.assertLessEqual(abs(v), 2, f"{eid}/{bottom}: fit off the -2..+2 scale")
                self.assertIn(fit.get("confidence"), CONFIDENCE | {None},
                              f"{eid}/{bottom}: unlabelled fit")
                if fit.get("confidence") == "sourced":
                    cits = fit.get("citations") or []
                    self.assertTrue(cits, f"{eid}/{bottom}: sourced fit without citations")
                    for c in cits:
                        self.assertTrue(c.get("sha256"), f"{eid}/{bottom}: sourced quote without sha256")
                        self.assertTrue(c.get("fetched_at"), f"{eid}/{bottom}: sourced quote without fetched_at")

    def test_rig_spec_refs_resolve(self):
        """Every spec `ref` must resolve in terminal.json or baits.json."""
        import tactics as tx
        terminal = {e["id"] for e in tx.load_terminal().get("terminal", [])}
        baits = {e["id"] for e in tx.load_baits().get("baits", [])}
        for name in ("bass",):
            for eid, e in entries_of(KB / f"{name}.json"):
                spec = e.get("spec") or {}
                for part, field in spec.items():
                    if not isinstance(field, dict):
                        continue
                    ref = field.get("ref")
                    if ref:
                        self.assertIn(ref, terminal | baits, f"{name}/{eid}.{part}: dangling ref {ref}")

    def test_season_table_is_narrow_and_sourced(self):
        d = json.loads((KB / "season.json").read_text())
        self.assertEqual(set(d.get("month_phase", {})), {str(m) for m in range(1, 13)})
        self.assertEqual(set(d.get("phases", [])), {"spring", "summer", "fall", "winter"})
        for eid, phases in (d.get("entries") or {}).items():
            for phase, fit in phases.items():
                self.assertIn(phase, d["phases"], f"{eid}: unknown phase {phase}")
                self.assertLessEqual(abs(fit.get("fit", 0)), 2, f"{eid}/{phase}")
                self.assertIn(fit.get("confidence"), CONFIDENCE, f"{eid}/{phase}")
                if fit.get("confidence") == "sourced":
                    cits = fit.get("citations") or []
                    self.assertTrue(cits, f"{eid}/{phase}: sourced without citations")
                    for c in cits:
                        self.assertTrue(c.get("sha256"), f"{eid}/{phase}: no sha256")
                        self.assertTrue(c.get("fetched_at"), f"{eid}/{phase}: no fetched_at")

    def test_spawn_table_is_sourced_and_narrow(self):
        d = json.loads((KB / "spawn.json").read_text())
        self.assertEqual(set(d.get("phases", [])),
                         {"pre-spawn", "spawn", "post-spawn"})
        for m in d.get("warming_months", []):
            self.assertTrue(1 <= m <= 12)
        for phase in d["phases"]:
            band = (d.get("triggers") or {}).get(phase, {}).get("water_f")
            self.assertEqual(len(band), 2, f"{phase}: missing band")
            self.assertTrue((d.get("phase_notes") or {}).get(phase, {}).get("citations"),
                            f"{phase}: no phase-note citations")
        for eid, phases in (d.get("entries") or {}).items():
            for phase, fit in phases.items():
                self.assertIn(phase, d["phases"], f"{eid}: unknown phase {phase}")
                self.assertLessEqual(abs(fit.get("fit", 0)), 2, f"{eid}/{phase}")
                self.assertIn(fit.get("confidence"), CONFIDENCE, f"{eid}/{phase}")
        for c in d.get("citations", []):
            self.assertTrue(c.get("sha256") and c.get("fetched_at") and c.get("quote"),
                            "spawn citation missing provenance")

    def test_presentation_classes_are_known(self):
        d = json.loads((KB / "presentation.json").read_text())
        classes = set(d.get("classes") or [])
        for eid, cls in (d.get("entries") or {}).items():
            self.assertIn(cls, classes, f"{eid}: {cls} not in the class list")

    def test_every_presentation_class_is_sourced(self):
        d = json.loads((KB / "presentation.json").read_text())
        sources = d.get("class_sources") or {}
        for cls in d.get("classes") or []:
            src = sources.get(cls) or {}
            self.assertTrue(src.get("quote"), f"{cls}: no class source quote")
            self.assertTrue(src.get("sha256"), f"{cls}: no class source sha256")
            self.assertTrue(src.get("url"), f"{cls}: no class source url")


if __name__ == "__main__":
    unittest.main()
