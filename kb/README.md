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
