# baromoon — Design System

*v1.0 — 2026-09-15. Structure owes a debt to adoraway's UI doc; the soul is
deliberately nothing like it. Baromoon is not a SaaS product wearing a theme —
it is a moon-ledger: an old field journal kept by someone who fishes by the
almanac and means it.*

## Design Principles

1. **Almanac restraint.** The page is a ledger. Quiet dark surfaces, thin
   manuscript rules, generous margins. Ornament whispers — one spiral, a lunar
   glyph, a double rule — and never shouts. If it could be described as
   "Celtic-themed," it has already failed; the feel should read as *old paper
   kept near water*, not costume.
2. **Peat, bone, and moonlight.** Colors come from a North Bay lake at last
   light: loam-black water, moss shadow, dry-rush gray, bone text, one
   tarnished-brass moon accent, one lichen green for good days. No tech blue,
   no cyan, no gradients.
3. **The angler's flow.** Every screen answers, in descending order of
   decisiveness: *when do I go, where do I go, what do I tie on.* The tier
   ledger is the front door; everything else is depth. No decorative dead ends.

## Layout Model

- **Home** — hero question → the tier ledger (best upcoming windows) → how it
  works. Anonymous visitors get the ledger for the demo water; a profile makes
  it theirs (nearest waters, their transits, their arsenal).
- **Report** — the deep read for one window: locked numbers, hour-by-hour,
  tackle with provenance.
- **Knowledge base / interview** — secondary, one hop from the flow.

## Design Tokens

Dark-first and dark-only (deliberate: this is read at first light and at dusk).
CSS custom properties in `web/static/style.css`.

### Surfaces
| Token | Value | Meaning |
|---|---|---|
| `--bg` | `#141810` | loam — page background |
| `--panel` | `#1b2117` | moss shadow — cards, tables |
| `--panel2` | `#222a1c` | raised moss — hovers, chips |

### Text
| Token | Value | Meaning |
|---|---|---|
| `--ink` | `#e8e3d2` | bone |
| `--dim` | `#a09c85` | dry rush — secondary |
| `--gold` | `#d3aa5f` | moon-brass — the ONE accent |
| `--lichen` | `#93b36b` | good / S-tier-adjacent green |
| `--water` | `#8fa7b8` | twilight water — moon/sky data only |
| `--ember` | `#c98a52` | caution |
| `--error` | `#c0604a` | errors |

### Lines
`--line: #37402c` (bracken) · `--line2: #2a321f` (under-rule). Manuscript
double rules: 1px bracken over 1px darker, 2px apart — used under section
heads, never as box borders everywhere.

### Typography
| Use | Face | Notes |
|---|---|---|
| Display / headings | **Cormorant Garamond** (Google Fonts) | 500/600/700; small-caps for section labels; tight leading |
| Body | system sans stack | 16–17px, quiet; the ledger's "hand" |
| Numbers / scores / times | ui-monospace stack, tabular-nums | scores, hours, temps — data is set like a table in a logbook |

### Tier language (the ledger's ranking)
| Tier | Meaning | Color |
|---|---|---|
| **S** | drop everything | moon-brass |
| **A** | plan around it | lichen |
| **B** | worth being out | twilight water |
| **C** | the fish have other plans | dry rush |

Bands (deterministic, from `overall`): S ≥ 7.5 · A ≥ 7.0 · B ≥ 6.5 · C below.

## Ornament Language (the whole Celtic budget)

- **Triskele mark** — one small three-arm spiral SVG. Uses: centered section
  divider (24px, 60% opacity brass), footer mark. Nowhere else.
- **Manuscript double rules** under section heads (`.rule-double`).
- **Lunar glyphs** (●◐☾◑) in the moon calendar and tier rows — data, not
  decoration, so they're exempt from restraint.
- Small-caps labels with wide tracking (`letter-spacing: .08em`).
- Border radius: 4–6px max — carved wood, not pill-shaped SaaS.
- Forbidden: knotwork borders, claddaghs, "Irish" greens, harp emoji, Papyrus,
  gradients, glows, drop shadows heavier than a deep dusk.

## Voice & Tone

Almanac voice: plain, weathered, a little wry. Short sentences. The moon is a
noun, not a brand asset. Numbers keep their clothes on (7.2/10, not "amazing!").
Disclosures stated once, plainly, like a shopkeeper's sign.

## Monetization & sponsorship (the table stays level)

The product is free; affiliate commissions and, at scale, disclosed sponsorships
keep it that way. Rank is sacred:

1. **Ranking never sees money, relationships, or brand.** The conditions score
   is computed before offers exist (`offers.py`); no placement, ordering, or
   tie-break may consult a retailer, a partner, or a payment.
2. **Paid placement is a labeled block, never a rank change.** A sponsor may buy
   a clearly marked *sponsored* slot in an offer surface — never a
   recommendation, a "best rig", a gap-lane position, or an alternative order.
3. **No free favors either.** Nobody gets placement or priority for a discount,
   a relationship, or a promise; if it isn't a disclosed paid slot, it isn't there.
4. **Alternatives are deterministic.** "Also:" options come from the KB's
   `purpose` grouping in catalog order, not affiliation.
5. **Sponsorship activates only when users exist.** Until then, only commission
   links — and those still resolve after ranking.

## Forbidden Patterns

- No spinners — pulsing "casting…" text or skeleton rows.
- No modals, no toasts — inline messages.
- No horizontal scroll on main content — tables wrap on desktop and stack into
  labeled rows on narrow screens (≤46rem).
- No light mode (yet) — first-light/dusk tool; revisit if users demand it.
- No animation beyond 400ms fades; respect `prefers-reduced-motion`.
