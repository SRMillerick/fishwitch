# Condition depth & the tie-break layer

*v0.1 — 2026-09-18. Design contract for separating same-class rigs. Read with
`kb/SOURCES.md` (sourcing policy) and `kb/README.md` (file schemas).*

## Why this exists

Conditions-first ranking already fixed **ownership bias**: the best rigs rank
first for every angler and the profile only tags *(yours)* / *(gap)*. The
remaining gap is **separation** — drop shot, Texas, Neko, wacky and Carolina
all carry the same `finesse` style and wide light/wind/temp bands, so the board
clusters on ties and "a better fit for these conditions" is hard to defend.
This layer deepens the cited condition fields so same-class picks separate
deterministically, without letting any one signal drive a tie.

## The two score layers

1. **Condition layer** — base + light band + wind band + water-temp band +
   solunar + planetary-hour tint + lake state (turnover / heat streak) +
   low-light topwater. This is the ranking proper.
2. **Tie-break layer** — small, capped deltas from fitted dimensions
   (cover now; season/mood as sourced). It *orders* near-equal condition
   scores; it never overturns a condition rejection or a large condition
   swing.

## Architecture rule: one home per signal

| Dimension | Home (data) | Input that activates it | Score role |
|---|---|---|---|
| **Cover** | `kb/substrate.json` (`entries[id][bottom]`) | `--bottom grass\|muck\|sand\|rock\|wood` (CLI + web form) | tie-break fit, this pass |
| **Mood** | `kb/presentation.json` (classes) | `lake_state` (post-turnover → suspended fish) | existing: suspend +0.5, fall +0.25 |
| **Clarity** | `kb/principles.json` (color rules) | light + cloud + lake_state | color selection only — **no rig score** (a rig fit here would double-count light/cloud) |
| **Season** | `kb/season.json` *(future)* | date / water temp | deferred until T1/T2 evidence separates the tied rigs |

`purpose` groups in `kb/terminal.json` / `kb/baits.json` remain the
deterministic "also:" alternatives and are **never** scored — no double count.

## Weights and caps (the style-hour lesson)

- Fit values in the data stay on the intuitive **−2…+2** scale.
- The scorer converts: **1 fit unit = 0.25 score points** (`FIT_SCALE`).
- **Per-dimension cap: ±0.5.** **Total tie-break cap: ±1.0** per entry —
  no single term may dominate a tie (the planetary-hour bonus was demoted
  +1.0 → +0.25 for exactly this reason; the ledger has counterexamples both
  ways).
- The 0.25 grid is deliberate: ties are broken by one or two steps, and the
  condition layer (multi-point swings) still dominates.
- **Null-safe:** unknown bottom, missing entry, missing fit ⇒ 0. Never guess.

## Provenance rules

- A fit carries `confidence` and, when sourced, a `citations` array of
  `{claim, tier, source, url, quote, found, fetched_at, sha256}` objects
  (T1/T2 workhorses) → it is a *sourced fit*. Fit keys: `fit`, `note`,
  `confidence`, `source`/`tier` (T5), `citations` (T1/T2).
- A fit with no source is **`unverified-editorial`** (T5), labelled, and may
  only live in this capped tie-break layer — never in the condition layer.
- Magnitudes are an editorial translation of the cited claim (the source
  states a use, not a score); the `quote` is the fact that must hold. Keep
  the note short and verbatim-adjacent.
- **`sha256` convention:** SHA-256 of the raw HTTP response body, first 16
  hex chars, computed at `fetched_at` (same as `adapters/trends.py`). Re-fetch
  to re-verify; a changed page invalidates the draft, not the promoted entry.
  Older citations in the KB used an unreproducible cached/browser hash —
  treat those as labels and re-verify on the next touching pass.

## v1 sourcing — the five tied rigs (cover / substrate)

| Rig | grass | wood | source |
|---|---|---|---|
| Texas-rigged worm | **+2** | **+1** | T2 Take Me Fishing — "close to or in cover such as weeds"; "worked through weeds or heavy cover without getting snagged" |
| Carolina rig | **+1** | — | T2 Take Me Fishing — "Lighter sinkers help the rig pass through weeds or grass"; MN bass article — "Short leaders work best in shallow or weedy waters" |
| Drop shot | +2 *(T5 owner)* | — | owner field observation — keeps the bait suspended above the canopy |
| Wacky-rigged Senko | +2 *(T5 owner)* | — | owner field observation — weightless bait rests on the grass |
| Neko rig | −2 *(T5 owner)* | — | owner field observation — effective, but the grass swallows it |
| Ned rig | −2 *(T5 owner)* | — | owner field observation; T2 season claim recorded below |

The T5 owner seeds keep their raw values; the scorer's cap normalizes them to
the same ±0.5 layer as sourced fits. `kb/pending/substrate/` holds the
promotion drafts (one per entry) that label each fit and add the T2 fits.

## Deferred dimensions (evidence recorded, not scored)

- **Season.** T2 Take Me Fishing: the Ned rig "can be one of the best fishing
  rigs to use during the fall and winter months when largemouth get
  lethargic." Strong, but Ned is not in the tie cluster; no comparable T2
  claim yet for the tied five. `kb/season.json` waits for that evidence.
- **Mood.** T2 Take Me Fishing: the drop shot presents a bait "above the
  bottom to bass that are suspended just above the bottom"; T2 Minnesota
  article: Carolina "works well for bottom-hugging bass". These fit
  `kb/presentation.json` classes, which already score under post-turnover —
  source the class derivations when the clarity/season passes run.
- **Clarity.** The existing color principles already carry the clarity rules
  (contrast vs. color, clear water rewards color). Wiring a clarity *input*
  (lake registry or angler) is a later data-layer task; until then, no rig
  score.

## Acceptance test

1. **Regression guard:** `fishwitch review` (12 sessions) must hold
   **5 exact / 3 style / 2 miss**. The replay passes no bottom, so it is
   expected to be unchanged — that is the point: the new layer cannot touch
   the calibration ledger.
2. **Evidence:** before/after `fishwitch report --bottom <type>` diffs on the
   tied rigs — a declared bottom must order them on the 0.25 grid instead of
   clustering, e.g. grass: drop shot > wacky > Texas > Carolina > Neko.
3. Promote drafts only through `fishwitch kb-promote --species substrate
   --entry <id> --by <you>` (human gate). Reject with `kb-reject` (logged).
