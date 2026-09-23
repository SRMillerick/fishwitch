"""Astro glyphs — drawn, single-ink, and complete across the three sets."""
import unittest

import glyphs


class GlyphTest(unittest.TestCase):
    def test_all_keys_have_drawings(self):
        self.assertEqual(len(glyphs.ZODIAC), 12)
        self.assertEqual(len(glyphs.PLANETS), 10)
        self.assertEqual(len(glyphs.ASPECTS), 5)
        for k in glyphs.GLYPHS:
            svg = glyphs.svg(k)
            self.assertTrue(svg.startswith("<svg"), k)
            self.assertIn("currentColor", svg, k)
            self.assertIn("viewBox=\"0 0 24 24\"", svg, k)

    def test_no_hardcoded_colours(self):
        # every glyph must follow the theme tokens
        for k in glyphs.GLYPHS:
            svg = glyphs.svg(k)
            self.assertNotRegex(svg, r"#[0-9a-fA-F]{3,6}", k)
            self.assertNotIn("rgb(", svg, k)

    def test_char_and_prefix(self):
        self.assertEqual(glyphs.char("aries"), "♈")
        self.assertEqual(glyphs.char("Sun"), "☉")           # case-insensitive
        self.assertEqual(glyphs.prefix("Jupiter"), "♃ ")
        self.assertEqual(glyphs.prefix("Jupiter", symbols=False), "")
        self.assertEqual(glyphs.char("not-a-glyph"), "")

    def test_symbolize_swaps_unicode_for_svg(self):
        out = glyphs.symbolize("Moon ♌ Leo · ☍ opposition · ♃ Jupiter")
        for ch in ("♌", "☍", "♃"):
            self.assertNotIn(ch, out)
        self.assertEqual(out.count("<svg"), 3)
        self.assertIn("Leo", out)

    def test_catalog_covers_every_glyph(self):
        cat = glyphs.catalog()
        self.assertEqual(len(cat), 27)
        self.assertEqual(len({c["key"] for c in cat}), 27)


if __name__ == "__main__":
    unittest.main()
