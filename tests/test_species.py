"""Lake-aware species selection: a trout water must not default to bass
tactics, and an explicit request must always win."""
import unittest

import tactics as tx


class SpeciesForLakeTest(unittest.TestCase):
    def test_explicit_request_always_wins(self):
        lake = {"species": ["Rainbow Trout", "Brown Trout"]}
        self.assertEqual(tx.species_for_lake(lake, "catfish"), "catfish")
        self.assertEqual(tx.species_for_lake(lake, "largemouth bass"), "bass")

    def test_trout_only_lake_gets_trout(self):
        lake = {"species": ["Rainbow Trout"]}
        self.assertEqual(tx.species_for_lake(lake), "trout")
        lake = {"species": ["rainbow trout", "brown trout", "brook trout"]}
        self.assertEqual(tx.species_for_lake(lake), "trout")

    def test_mixed_lake_prefers_bass_catalog(self):
        lake = {"species": ["Largemouth Bass", "Rainbow Trout"]}
        self.assertEqual(tx.species_for_lake(lake), "bass")

    def test_catfish_before_panfish(self):
        lake = {"species": ["Channel Catfish", "Bluegill"]}
        self.assertEqual(tx.species_for_lake(lake), "catfish")

    def test_panfish_lake(self):
        lake = {"species": ["Bluegill", "Black Crappie"]}
        self.assertEqual(tx.species_for_lake(lake), "panfish")

    def test_no_species_list_keeps_bass_default(self):
        self.assertEqual(tx.species_for_lake(None), "bass")
        self.assertEqual(tx.species_for_lake({}), "bass")
        self.assertEqual(tx.species_for_lake({"species": []}), "bass")

    def test_unknown_names_fall_back_to_bass(self):
        lake = {"species": ["Kokanee Salmon", "Walleye"]}
        self.assertEqual(tx.species_for_lake(lake), "bass")

    def test_striped_bass_is_bass(self):
        lake = {"species": ["Striped Bass", "Rainbow Trout"]}
        self.assertEqual(tx.species_for_lake(lake), "bass")


if __name__ == "__main__":
    unittest.main()
