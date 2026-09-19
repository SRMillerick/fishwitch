# The knowledge base — sources of truth for lures & rigging

Every entry in `kb/<species>.json` carries `provenance`:

```json
"provenance": {
  "seed_author": "who/what created this entry",
  "source":      "human-readable source name",
  "source_url":  "url of the source of truth",
  "confidence":  "verified | sourced | unverified-editorial",
  "verified_by": "who checked it against the source",
  "note":        "free text"
}
```

## Rules
1. **No runtime invention.** The engine (tactics.py) only reads and scores.
   It never synthesizes lure facts. If the KB lacks an entry, the report says so.
2. **AI agents navigate, never author.** An agent may query (`fishwitch kb`)
   and may *draft* entries — drafts land in `kb/pending/` with citations for
   human review before promotion into a species file.
3. **Unverified entries are labeled in output.** Anything with
   `confidence != "verified"` shows 🟡 in reports and kb listings until a
   human checks it against the cited source.

## Entry kind: product vs rig

Every entry also carries `kind`:

```json
"kind": "product"   // product | rig
```

- **`product`** — a discrete purchasable item (crankbait, spinnerbait, skirted
  jig, swimbait, spoon, fly). This is the affiliate surface: a gap here is
  something to buy.
- **`rig`** — a rigging pattern built from hooks, weights and plastics the
  angler mostly owns (Texas, drop shot, wacky, Carolina, Neko, Ned; catfish
  bait rigs). A gap here is a how-to/content opportunity, **not** a purchase.

The report's gap lane renders the two separately and attaches no offers to
`rig` entries.

## Offers schema v2 (`kb/offers.json`)

Retailers are a registry; entries list offers per retailer; rigs list the
components they are built from.

- **`retailers`** — `{id: {label, kind: manufacturer|affiliate, dp_template?, tag_env?, subtag?}}`.
  Amazon-style links are built from `dp_template` + the env tag
  (`FISHWITCH_AMZ_TAG`, plus `ascsubtag=<entry>` for attribution); network
  retailers (Tackle Warehouse, TackleDirect…) store their tracked URL per entry.
- **`entries`** — `{entry_id: {kind: product|rig, offers: [...], components: [...]}}`
  - `offers`: `{retailer, url | asin, note}` — **multi-retailer by design**, so a
    pick can offer Amazon *and* a tackle retailer side by side.
  - `components`: `{id, label, offers: [...]}` — what it takes to build a rig
    (hooks, weights, beads, plastics). This monetizes the **rig gap** through
    parts without pretending the rig itself is a product.
- Every link resolves through `/out/<entry>/<retailer>[?comp=<component>]` for
  aggregate click counting; destinations are resolved server-side (no open redirect).
- `fishwitch offers --entry <id>` prints offers + components. `--add-url` /
  `--asin` register **data only** — links go live with no code change.
- Affiliate tags/IDs live in env, never in code. Ranking never sees any of this.

## Terminal tackle (`kb/terminal.json`)

Hooks, weights, jig heads and hardware as entities:
`{id, label, category: hook|weight|jighead|terminal, citations, provenance}`.
Sourced claims are verbatim quotes (fetched_at + sha256); entries with no
source are labelled `unverified-editorial`. The rig component bundles in
`offers.json` reuse these ids where they overlap, so a "build it" part can
become a real KB entity. CLI: `fishwitch terminal [--category hook]`.

## Rig specs (`spec` on a species entry)

A rig entry can carry a structured **tackle-system spec** — the concrete build
the report and shopping list print:

```json
"spec": {
  "hook":   {"ref": "jungle-wacky", "sizes": ["1/0"], "note": "weedless"},
  "weight": {"type": "drop-shot weight", "sizes": ["1/8 oz"]},
  "ring":   {"type": "VMC 6mm O-ring"},
  "bait":   {"ref": "abstract", "sizes": ["24mm"]},
  "line":   {"main": "fluorocarbon", "leader": "none", "rod": "medium-heavy"},
  "source": "owner field observation (sean, 2026-09-18)",
  "confidence": "unverified-editorial"
}
```

- `ref` points at a `kb/terminal.json` or `kb/baits.json` entity id; the report
  resolves it to the entity label so the build reads
  *“Owner Jungle Wacky 1/0 · VMC 6mm O-ring · The Abstract 24mm · fluorocarbon”*
  (`tactics.rig_spec()` / `tactics.spec_line()`).
- **Profile `setups` override the reference:** when the angler's profile carries
  `setups[rig_id]` (a plain object of part → string), the report prints
  *“your build: …”* from the profile instead of the KB *“build: …”* reference.

## Presentation classes (`kb/presentation.json`)

`{entries: {entry_id: topwater|swim|suspend|fall|bottom}}` — a T5 editorial
derivation from each entry's cited `technique` string (drop shot hovers =
suspend; wacky dead-sticks the fall = fall; trig drags = bottom). The scorer
uses it under post-turnover (suspended fish): suspend +0.5, fall +0.25. It is
the seed for future clarity/depth dimensions; source each class in a later
pass. The planetary-hour style bonus is a **+0.25 tint, not a driver** — the
ledger has counterexamples in both directions (reaction in a finesse hour 9/5,
finesse in reaction hours 9/17), so it colors ties instead of overriding the
conditions.
- Every component is optional. Sizes are display ranges, not prescriptions.
- `source`/`confidence` label owner builds (T5) vs sourced maker specs (T1).
  Owner builds that differ from a maker's spec live in the entry anyway,
  labelled — the report distinguishes KB best-fit from the concrete build.
- Specs are patched through the same pending queue: a draft
  `{"patch": {"spec": {...}}, "citations": [...]}` is shallow-merged into the
  entry by `kb-promote` (the patch object is exactly the set of top-level keys
  to merge — keep the `spec` nesting).

## Color & clarity principles (`kb/principles.json`)

`{id, label, when, rule, citations, provenance}`. Each `rule` is an **editorial
synthesis** (labelled), while `citations` are verbatim fish-vision science
(Wikipedia — *Vision in fish*): long wavelengths are absorbed first, blue/green
reach deepest, true colors exist only near the surface, contrast beats color,
low light runs on rods, clear water rewards color. `tactics.color_principle(ctx)`
picks one per session (light/cloud/lake-state) and the report renders it as a
**Color** row in the locked numbers. CLI: `fishwitch colors`.

## Candidate sources of truth to wire in (deterministic ingestion)
- **Manufacturer product pages** (Rapala, Zoom, Yamamoto, Roboworm, Z-Man…):
  stated retrieve, depth range, rigging — the primary source for
  lure-specific mechanics. Scrape/cache per SKU; cite URL + access date.
- **State agency technique guides** (CDFW, TPWD, MN DNR — public domain-ish):
  species patterns, seasonal presentation guidance by region.
- **Retailer catalogs** (Tackle Warehouse / Bass Pro product APIs & feeds):
  structured lure attributes (category, depth, action) for the matching layer.
- **Sonar-manufacturer rigging guides** (Garmin/Lowrance/Humminbird docs):
  sonar-driven presentation selection.
- **Our own calibrated logbook** (config/logbook.jsonl): personal ground truth
  that outranks editorial entries once N catches accumulate per technique.

Ingestion scripts belong in `adapters/` (deterministic fetchers) and write
into `kb/pending/` with full provenance for review.
