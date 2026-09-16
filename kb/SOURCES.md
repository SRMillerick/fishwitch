# Sources of truth — the baromoon knowledge policy

*Draft v0.1, 2026-09-16. This is the policy the ingest adapters and reviewers
follow. It is deliberately conservative: the engine's reputation rests on
being able to point at a source for every factual claim.*

## The rule

1. **`kb/*.json` is the engine's only source of truth.** `tactics.py` and
   `report.py` read it and score it; they never hardcode a tackle fact.
2. **Every fact traces to a citation.** A promoted entry carries `provenance`
   (source, URL, confidence, verified_by) and, where the fact is a quote,
   verbatim support.
3. **Adapters draft, humans promote.** Deterministic fetchers land cited
   drafts in `kb/pending/`; nothing enters a species file without a human
   review (`kb-promote --by <you>`). Rejects are logged.
4. **When no authority exists, say so.** That content is `editorial`, labeled
   in output, and must earn its place through the calibration ledger.

## Authority tiers

| Tier | What it is | Use for |
|---|---|---|
| **T1 — Manufacturer primary** | The maker's own product page/catalog/manual for *their* product | Dimensions, weights, depth, action, rigging, materials, color names |
| **T2 — Public agency** | State/federal fisheries guides (Iowa DNR, TPWD, MN DNR, CDFW, USGS) | Species behavior, seasonal patterns, rigs, baits, hook regulations |
| **T3 — Standards & institutions** | IGFA (line classes, rules), Wikipedia (knot mechanics/history, fish vision index) | Line classes, knot identity, vision science pointers |
| **T4 — Independent testing** | e.g. TackleTour measured line tests | Measured strength/diameter vs. labeled — cite methodology |
| **T5 — Editorial synthesis** | Human-written, labelled `editorial` | Color rules and "when to throw what" where no single authority exists; validated by the logbook |

T1–T2 are the workhorses. T4 is used only for *measured* claims. T5 is
allowed but never presented as sourced.

## Domain map

| Domain | Primary source | Ingest path | Status |
|---|---|---|---|
| **Lures / hard baits / plastics** | T1 manufacturer catalog | Shopify `/products.json` (2 hosts live: 6th Sense, Z-Man); JSON-LD/HTML scraper for the rest; manual with URL otherwise | partial |
| **Rigs** | T2 agency technique guides + T1 maker rigging guides | agency quote extractor (live for Iowa DNR); probe TPWD / MN DNR / CDFW | partial |
| **Baits (live/cut/prepared)** | T2 agency guides; T1 prepared-bait makers | agency quote extractor | partial |
| **Knots** | T1 line-maker guides (Seaguar `/blogs/knot-guide`, Sunline `/pages/knots`) + T2 Take Me Fishing + T3 Wikipedia | new `wikipedia` + generic HTML adapters | **DRAFT `kb/knots.json`** (9 knots, 17 live-verified quotes) |
| **Line** | T1 manufacturer spec sheets; T3 IGFA line classes; T4 TackleTour tests | manual/spec-page adapter; cite test methodology | not modelled |
| **Terminal tackle** (hooks, weights, jig heads) | T1 manufacturer specs (Gamakatsu, VMC, Mustad, Owner) | spec-page adapter | not modelled |
| **Colors / clarity** | T3 fish-vision science (Wikipedia *Vision in fish* → primary papers) + T1 manufacturer color guidance + T2 agency | `principles` entries; T5 synthesis labelled | editorial today |
| **Species conditions** (temp bands, depth, season) | T2 agency species profiles + T3 fisheries science | agency quote extractor | editorial today |

## Proposed file taxonomy

Species files stay the home of condition-scored entities. Cross-species
knowledge gets its own files so it can be shared and cited once:

```
kb/bass.json          # lures + rigs + baits (condition-scored; exists)
kb/trout.json         # exists
kb/catfish.json       # exists
kb/panfish.json       # exists
kb/knots.json         # NEW: knot entities (identity, use, line types, steps)
kb/line.json          # NEW: line types/brands (material, test, diam, stretch)
kb/terminal.json      # NEW: hooks / weights / jig heads
kb/principles.json    # NEW: color + clarity selection rules (cited)
kb/sources.json       # machine-readable source registry (exists)
kb/pending/           # drafts awaiting human review (exists)
kb/rejected.log       # append-only decisions (exists)
```

Entities that are **scored by conditions** (lures, rigs, baits) live in the
species files. Entities that are **looked up by context** (knots by line type
+ connection; line by technique/cover/clarity) live in the shared files, as
tables the engine can query deterministically.

## Citation shape (proposed extension)

Today an entry carries one `provenance`. For entries assembled from several
claims, add an optional per-claim list:

```json
"citations": [
  { "claim": "Palomar is a strong braid-to-hook knot",
    "source": "Seaguar knot guide", "tier": "T1",
    "source_url": "https://seaguar.com/blogs/knot-guide",
    "quote": "…", "fetched_at": "…", "sha256": "…" }
]
```

`provenance.confidence` remains the entry-level summary
(`sourced | verified | unverified-editorial`).

## Verified source registry (checked live 2026-09-16)

| Domain | Source | URL | Mode |
|---|---|---|---|
| Knots | Take Me Fishing (RBFF) | `takemefishing.org/how-to-fish/how-tie-fishing-knots/…` | **quote** (server-rendered, verified) |
| Knots | Wikipedia | `en.wikipedia.org/wiki/<Knot>` + REST summary API | **quote** (CC BY-SA — cite, never bulk-copy) |
| Knots | Seaguar, Sunline America | `seaguar.com/blogs/knot-guide`, `sunlineamerica.com/pages/knots` | **link-out** (JS-rendered; no quote extraction) |
| Line | TackleTour line tests | `tackletour.com/menulines.html` | measured data (T4) |
| Line | IGFA | `igfa.org/line-class-records/` | line classes (T3) |
| Rigs/baits | State agencies | Iowa DNR (in use); TPWD, MN DNR, CDFW reachable | agency quote extractor |
| Lures | Manufacturer catalogs | 6th Sense, Z-Man Shopify JSON (in use) | catalog adapter |

## Decisions (2026-09-16)

1. **Colors** — T5 labelled rules (fish-vision + contrast), calibrated by the logbook later. Start small.
2. **Line** — model material **types** (mono/fluoro/braid/copoly properties), not per-brand products.
3. **Knots** — identity / use / selection / strength-retention only, with a **link out**; do not copy step-by-step illustrations.
4. **Build order** — **knots + line first** (fills the blank, plugs into rig recommendations), then deepen baits/rigs.

## Freshness & verification

- Store `fetched_at` + content hash with every draft (already done).
- Catalogs change: re-fetch on demand (`kb-ingest --refresh`), never silently.
- Quotes are matched verbatim; a changed page invalidates the draft, not the
  promoted entry — re-verify and re-promote.
- A human `verified_by` is the attestation; the calibration ledger
  (`fishwitch review`) is the court where editorial claims are judged.

## What we do NOT use

- Retailer marketing copy, influencer videos, forum posts, SEO listicles.
- Prices or "best/cheapest" claims (they change; Amazon owns pricing).
- Unattributed consensus. If it can't be cited, it's `editorial` and labelled.

