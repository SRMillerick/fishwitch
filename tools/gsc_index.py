#!/usr/bin/env python3
"""GSC index-coverage reader — the whole registry in one view.

URL Inspection is the only index-coverage API Google exposes, and it works one
URL at a time. This loops the registry's content pages + every `/lake/<id>` and
groups them by `coverageState`, so "where are we going?" has a number instead of
a hunch. Results cache in `reports/gsc-index.json` (gitignored) so repeat runs
only inspect what is new or uncrawled; `--refresh` re-inspects everything.

    ~/.astro-venv/bin/python tools/gsc_index.py
    ~/.astro-venv/bin/python tools/gsc_index.py --urls-only
    ~/.astro-venv/bin/python tools/gsc_index.py --refresh --limit 20

Credentials: same service account as tools/gsc_read.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.gsc_read import (CREDS_DEFAULT, CREDS_ENV, SITE, access_token,  # noqa: E402
                            inspect)

CACHE = ROOT / "reports" / "gsc-index.json"

STATIC_PAGES = [
    "/", "/lakes", "/lakes/ca", "/lakes/az", "/kb", "/tying",
    "/method", "/developers", "/about", "/contact", "/outlook", "/report",
    "/sitemap.xml", "/sitemap-pages.xml", "/sitemap-lakes.xml",
]


def registry_urls() -> list[str]:
    lakes = json.loads((ROOT / "config" / "lakes.json").read_text())
    return [f"https://baromoon.com{l}" for l in STATIC_PAGES] + \
           [f"https://baromoon.com/lake/{key}" for key in lakes]


def _classify(state: str) -> str:
    s = (state or "").lower()
    if "indexed" in s and "not indexed" not in s:
        return "indexed"
    if "not indexed" in s:
        return "not-indexed"
    if "alternate" in s or "redirect" in s or "canonical" in s:
        return "other"
    return "unknown"


def _inspect_one(token: str, site: str, url: str) -> tuple[str, dict]:
    res = inspect(token, site, url).get("inspectionResult", {})
    st = res.get("indexStatusResult", {}) or {}
    return url, {
        "coverage": st.get("coverageState", ""),
        "verdict": st.get("verdict", ""),
        "lastCrawl": st.get("lastCrawlTime", ""),
        "canonical": st.get("googleCanonical", ""),
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="inspect at most N URLs")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--urls-only", action="store_true", help="print the URL list")
    ap.add_argument("--site", default=SITE)
    args = ap.parse_args()

    urls = registry_urls()
    if args.urls_only:
        print("\n".join(urls))
        return 0

    creds = Path(os.environ.get(CREDS_ENV) or CREDS_DEFAULT)
    if not creds.exists():
        print(f"gsc_index: no service-account key at {creds}", file=sys.stderr)
        return 2
    token = access_token(json.loads(creds.read_text()))

    cache = _load_cache()
    todo = urls if args.refresh else [u for u in urls if u not in cache]
    if args.limit:
        todo = todo[:args.limit]

    print(f"GSC index coverage — {args.site} · inspecting {len(todo)} of {len(urls)} URLs"
          + ("" if todo else " (all cached)"))
    if todo:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_inspect_one, token, args.site, u): u for u in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    url, row = fut.result()
                    cache[url] = row
                except RuntimeError as e:
                    print(f"  ! {futs[fut]}: {e}", file=sys.stderr)
                if i % 10 == 0 or i == len(todo):
                    print(f"  … {i}/{len(todo)}")
    _save_cache(cache)

    # ---- report -------------------------------------------------------------
    buckets: dict[str, list[str]] = {"indexed": [], "not-indexed": [], "other": [], "unknown": []}
    for url in urls:
        row = cache.get(url)
        buckets[_classify(row.get("coverage") if row else "")].append(url)

    def short(u: str) -> str:
        return u.replace("https://baromoon.com", "") or "/"

    indexed = len(buckets["indexed"])
    print(f"\n  indexed        {indexed:3d}")
    print(f"  not-indexed    {len(buckets['not-indexed']):3d}")
    print(f"  other/unknown  {len(buckets['other']) + len(buckets['unknown']):3d}")
    print(f"  ─────────────────────")
    print(f"  index ratio    {indexed}/{len(urls)} "
          f"({100 * indexed / max(1, len(urls)):.0f}%)")

    for name, label in (("indexed", "INDEXED"), ("not-indexed", "NOT INDEXED"),
                        ("other", "OTHER"), ("unknown", "UNKNOWN / never crawled")):
        if not buckets[name]:
            continue
        print(f"\n  {label}:")
        for u in buckets[name]:
            row = cache.get(u, {})
            state = row.get("coverage", "")
            crawl = (row.get("lastCrawl") or "")[:10]
            print(f"    {short(u):44s} {state:38s} crawl={crawl or '-'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"gsc_index: {e}", file=sys.stderr)
        raise SystemExit(1)
