# baromoon — Design System

*v1.0 — 2026-09-15. Structure owes a debt to adoraway's UI doc; the soul is
deliberately nothing like it. Baromoon is not a SaaS product wearing a theme —
it is a moon-ledger: an old field journal kept by someone who fishes by the
almanac and means it.*

## Design Principles

1. **Almanac restraint.** The page is a ledger. Quiet surfaces, thin
   manuscript rules, generous margins. Ornament whispers — one spiral, a lunar
   glyph, a double rule — and never shouts. The <em>mark</em> carries a Celtic
   motif — the triple-spiral triskelion — but the page itself never costumes:
   no knotwork borders, no claddaghs, no "Irish" greens (see Ornament Language).
   The feel should read as *old paper kept near water*, not a Ren-faire booth.
2. **Paper, water, and moonlight.** Two modes, one palette logic. **First
   light** (default): paper ground, deep-water ink, a water-teal primary, one
   tarnished-brass moon accent, lichen green for good days. **Crisp dark**: the
   same language after dusk — stepped blue-black surfaces, bone text, a
   water-cyan data accent. No gradients, no glows.
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

A light/dark pair — **First light** is the default; **Crisp dark** takes over
when the system prefers dark or the angler flips the header toggle (stored in
`bm-theme-v2`; `?theme=first-light|crisp-dark|loam|almanac|system` overrides).
CSS custom properties in `web/static/style.css`; `/styleguide` (local) renders
every component under each set with live contrast readouts. `loam` (the
previous dark field-notebook) and `almanac` (print study) survive only as
styleguide variants.

### First light (default)
| Token | Value | Meaning |
|---|---|---|
| `--bg` | `#f7f5ef` | paper |
| `--panel` | `#fffdf8` | card |
| `--ink` | `#14232a` | deep-water ink |
| `--dim` | `#4e5c5f` | secondary |
| `--faint` | `#68726e` | fine print (4.5:1) |
| `--line` | `#b8b2a0` | hairline (~2:1) |
| `--gold` | `#8a5f16` | brass — the ONE accent |
| `--water` | `#17606f` | water-teal — sky/moon data |
| `--lichen` | `#33663a` | good / S-tier-adjacent green |
| `--ember` | `#a9551f` | caution |
| `--error` | `#9c2f22` | errors |

### Crisp dark
| Token | Value | Meaning |
|---|---|---|
| `--bg` | `#0a0f12` | night water |
| `--panel` | `#16232a` | stepped surface |
| `--ink` | `#f2efe6` | bone |
| `--dim` | `#a9b2ab` | secondary |
| `--faint` | `#7e8b86` | fine print (5.4:1) |
| `--line` | `#3a5057` | hairline (~2:1) |
| `--gold` | `#e2b35f` | brass moon — the ONE accent |
| `--water` | `#8ccadd` | water-cyan — sky data |
| `--lichen` | `#9ed07b` | good |
| `--ember` | `#dd9560` | caution |
| `--error` | `#e3735c` | errors |

### Lines
Hairlines are ~2:1 against their surface in both modes (`--line`), with a
lighter under-rule (`--line-2`). Manuscript double rules: 1px line over 1px
under-rule, 2px apart — used under section heads, never as box borders
everywhere.

### Typography
| Use | Face | Notes |
|---|---|---|
| Display / headings | **Cormorant Garamond** (Google Fonts) | 500/600/700; small-caps for section labels; tight leading |
| Body | system sans stack | 16–17px, quiet; the ledger's "hand" |
| Numbers / scores / times | ui-monospace stack, tabular-nums | scores, hours, temps — data is set like a table in a logbook |

### Tier language (the ledger's ranking)
| Tier | Meaning | Color |
|---|---|---|
| **S** | drop everything | moon-brass (`--gold`) |
| **A** | plan around it | lichen (`--lichen`) |
| **B** | worth being out | water (`--water`) |
| **C** | the fish have other plans | dim (`--dim`) |

Bands (deterministic, from `overall`): S ≥ 7.5 · A ≥ 7.0 · B ≥ 6.5 · C below.

## Ornament Language (the whole Celtic budget)

- **The mark** — a traced Celtic triskelion (triple spiral), vectorised from
  the reference decal: `web/static/triskelion.svg` (faithful), `-bold.svg`
  (header/footer), `-favicon.svg` (favicon/PWA). Single-ink via CSS mask,
  coloured by the theme. Uses: header lockup, footer mark, favicon/PWA tiles,
  and — at reduced opacity — the centered section divider. Nowhere else.
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
- No animation beyond 400ms fades; respect `prefers-reduced-motion`.
