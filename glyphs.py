"""Astrology glyphs — drawn, never font glyphs.

Unicode astrological characters (♈ ☿ ☌ …) render as tofu or colour emoji
depending on the device font; the moon already taught the project to draw
instead. These are single-ink line glyphs on a 24 × 24 grid, coloured by
``currentColor`` so they follow the theme tokens.

Web reports emit inline SVG (``mode="svg"``), the CLI keeps the Unicode text
glyphs (``mode="text"``) for terminals that have them. ``inline_svg()`` swaps
``[[sym|key]]`` tokens left in rendered HTML for the real drawings.
"""
from __future__ import annotations

# every shape is inner SVG markup; the wrapper carries stroke=currentColor
GLYPHS: dict[str, str] = {
    # ── zodiac ──────────────────────────────────────────────────────────
    "aries": ('<path d="M12 19C12 13 10 7 6.5 7C4.5 7 3.5 9 4.5 11'
              'C5.3 12.6 7.5 12.3 8.2 10.5"/>'
              '<path d="M12 19C12 13 14 7 17.5 7C19.5 7 20.5 9 19.5 11'
              'C18.7 12.6 16.5 12.3 15.8 10.5"/>'),
    "taurus": ('<circle cx="12" cy="15.5" r="4.2"/>'
               '<path d="M6.5 7.5C7.5 11.5 10 11.5 12 9.5C14 11.5 16.5 11.5 17.5 7.5"/>'),
    "gemini": ('<path d="M7.5 5H16.5M7.5 19H16.5M10 5V19M14 5V19"/>'),
    "cancer": ('<circle cx="8.5" cy="8" r="3"/>'
               '<path d="M5.5 8C4 8 3 9.5 3 11C3 13.5 5 14.5 7 14.5"/>'
               '<circle cx="15.5" cy="16" r="3"/>'
               '<path d="M18.5 16C20 16 21 14.5 21 13C21 10.5 19 9.5 17 9.5"/>'),
    "leo": ('<circle cx="7.5" cy="16.5" r="2.6"/>'
            '<path d="M9.8 15.8C13 15.8 11 7 15 6.2C17.5 5.7 19.8 7.6 18.8 10.6'
            'C17.9 13.2 15.6 14.2 14.6 15.8C15.8 17.4 18.4 17.2 20 15"/>'),
    "virgo": ('<path d="M4 17V10C4 7.5 6 7 7 8.5C8.2 10.3 8 14 8 17'
              'C8 10 10 7.5 11.5 8.5C13 9.5 13 13.5 13 17'
              'C13 9.5 15 7.5 16.5 8.7C18 9.9 17.5 13.5 16 15.5'
              'C14.5 17.5 13.5 18.5 13.5 21"/>'),
    "libra": ('<path d="M4 18H20M8 18A4 4 0 0 1 16 18M7.5 13.6H16.5"/>'),
    "scorpio": ('<path d="M4 18V12L6.5 18L9 12V18L11.5 12V18L14 12L16.5 18V10"/>'
                '<path d="M14.5 12L16.5 10L18.5 12"/>'),
    "sagittarius": ('<path d="M5 19L18 6M12 6H18V12M8.5 11.5L12.5 15.5"/>'),
    "capricorn": ('<path d="M4 19C4 13 4 9 7 8C9 7.3 10.5 9 11 11L12 14'
                  'C12.5 9 15 7 17 8.5C18.8 9.8 18 12.5 16 12.5'
                  'C14.7 12.5 14.2 11.4 15 10.3"/>'
                  '<path d="M4 19C7 19.5 10 19 12 17"/>'),
    "aquarius": ('<path d="M4 10L7 7.5L10 10L13 7.5L16 10L19 7.5"/>'
                 '<path d="M4 16L7 13.5L10 16L13 13.5L16 16L19 13.5"/>'),
    "pisces": ('<path d="M9 5C5 9 5 15 9 19M15 5C19 9 19 15 15 19M5 12H19"/>'),
    # ── planets ─────────────────────────────────────────────────────────
    "sun": ('<circle cx="12" cy="12" r="5"/>'
            '<circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/>'),
    "moon": ('<path d="M15.5 4.5A8.5 8.5 0 1 0 15.5 19.5A10 10 0 0 1 15.5 4.5Z" '
             'fill="currentColor" stroke="none"/>'),
    "mercury": ('<circle cx="12" cy="11" r="3.2"/>'
                '<path d="M12 14.2V20M9 17H15"/>'
                '<path d="M8.5 5.5C8.5 3.5 10 2.8 12 4.5C14 2.8 15.5 3.5 15.5 5.5"/>'),
    "venus": ('<circle cx="12" cy="8.5" r="4"/>'
              '<path d="M12 12.5V20M8.5 16.5H15.5"/>'),
    "mars": ('<circle cx="9.5" cy="14.5" r="4"/>'
             '<path d="M12.3 11.7L19 5M14.5 5H19V9.5"/>'),
    "jupiter": ('<path d="M4 15H13M8.5 4V20"/>'
                '<path d="M8.5 5C16.5 5 18.5 10.5 16.5 13.5'
                'C15 15.7 12.2 15 12.8 12.9"/>'),
    "saturn": ('<path d="M12 8V20M7.5 12.5H16.5"/>'
               '<path d="M12 8C9.5 8 8.3 6 9.6 4.4C10.8 3 13 3.6 12.9 5.6"/>'),
    "uranus": ('<path d="M9 20V13M15 20V13M9 15.5H15M12 13V4.5"/>'
               '<path d="M10 6.5L12 4.5L14 6.5"/>'),
    "neptune": ('<path d="M12 4V21M15.5 8.5C15.5 14 8.5 14 8.5 8.5"/>'
                '<path d="M8.5 8.5V5M15.5 8.5V5M9.5 11.8H14.5"/>'),
    "pluto": ('<circle cx="12" cy="7" r="3.5"/>'
              '<path d="M12 10.5V13"/>'
              '<path d="M5.5 13C7 18 17 18 18.5 13Z"/>'),
    # ── aspects ─────────────────────────────────────────────────────────
    "conjunction": ('<circle cx="9.5" cy="12" r="4"/><path d="M13.5 12H20"/>'),
    "opposition": ('<circle cx="6" cy="12" r="3.5"/><circle cx="18" cy="12" r="3.5"/>'
                   '<path d="M6 12H18"/>'),
    "square": '<path d="M7 7H17V17H7Z"/>',
    "trine": '<path d="M12 6L19.5 18.5H4.5Z"/>',
    "sextile": '<path d="M12 4.5V19.5M5.5 8.25L18.5 15.75M5.5 15.75L18.5 8.25"/>',
}

UNICODE: dict[str, str] = {
    "aries": "♈", "taurus": "♉", "gemini": "♊", "cancer": "♋",
    "leo": "♌", "virgo": "♍", "libra": "♎", "scorpio": "♏",
    "sagittarius": "♐", "capricorn": "♑", "aquarius": "♒", "pisces": "♓",
    "sun": "☉", "moon": "☽", "mercury": "☿", "venus": "♀", "mars": "♂",
    "jupiter": "♃", "saturn": "♄", "uranus": "♅", "neptune": "♆", "pluto": "♇",
    "conjunction": "☌", "opposition": "☍", "square": "□", "trine": "△",
    "sextile": "⚹",
}

ZODIAC = ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
          "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
PLANETS = ["sun", "moon", "mercury", "venus", "mars", "jupiter",
           "saturn", "uranus", "neptune", "pluto"]
ASPECTS = ["conjunction", "opposition", "square", "trine", "sextile"]

LABELS = {k: k.capitalize() for k in GLYPHS}


def key_for(value: str) -> str:
    """Normalize a sign/planet/aspect name (or already-lowercase key)."""
    return (value or "").strip().lower().replace(" ", "-")


def svg(key: str, size: float = 14, cls: str = "astro-sym") -> str:
    """Inline SVG for one glyph; '' when the key is unknown."""
    body = GLYPHS.get(key_for(key))
    if not body:
        return ""
    return (f'<svg class="{cls}" width="{size:g}" height="{size:g}" '
            f'viewBox="0 0 24 24" aria-hidden="true" focusable="false" '
            f'fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def char(key: str) -> str:
    """Unicode glyph (CLI/terminal); '' when the key is unknown."""
    return UNICODE.get(key_for(key), "")


def prefix(key: str, symbols: bool = True) -> str:
    """'♃ ' style prefix — empty when symbols are off or the key is unknown."""
    c = char(key) if symbols else ""
    return f"{c} " if c else ""


_CHAR_SVG = {v: svg(k) for k, v in UNICODE.items() if v}


def symbolize(html: str) -> str:
    """Replace the Unicode astro characters in rendered HTML with drawings.
    The set is distinctive (zodiac/planet/aspect glyphs only), so this is
    safe to run over a whole report body."""
    for ch, drawing in _CHAR_SVG.items():
        if ch in html:
            html = html.replace(ch, drawing)
    return html


def catalog() -> list[dict]:
    """Every glyph with its label and drawing — used by the local styleguide."""
    return [dict(key=k, label=LABELS[k], svg=svg(k, size=40), group=g)
            for g, keys in (("zodiac", ZODIAC), ("planet", PLANETS), ("aspect", ASPECTS))
            for k in keys]
