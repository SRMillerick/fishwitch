"""KB ingestion adapter — deterministic fetch of lure specs into kb/pending/.

Sources: Shopify catalogs expose open structured JSON (/products.json) —
the cleanest deterministic pipe (no scraping heuristics): title, handle,
product URL, variants, and body_html specs. Currently live: zmanfishing.com.

Pipeline (all deterministic, no LLM anywhere):
  kb/sources.json  →  fetch catalog (cached, sha256-stamped)
                   →  search products by entry search terms
                   →  extract spec quotes by fixed regex (depth/retrieve/rig)
                   →  kb/pending/<species>/<entry_id>.json  (provenance-rich)
                   →  HUMAN review  →  fishwitch kb promote  →  kb/<species>.json

Affiliate note: drafts include canonical product URLs; retailer offers/affiliate
tags attach at the SKU-resolution layer (see kb/README.md) — never in ranking.
"""
from __future__ import annotations
import hashlib
import html as _html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
PENDING = KB / "pending"
CACHE = ROOT / ".cache" / "kb"
UA = {"User-Agent": "fishwitch-mvp/1.0 (tackle KB verification)"}

DEPTH_RE = re.compile(
    r"[^.]*\b(?:dives? to|runs? (?:at|from|over)|running depth|depth range)[:\s]*"
    r"([0-9]+(?:\.[0-9]+)?\s*(?:-\s*[0-9]+(?:\.[0-9]+)?)?\s*"
    r"(?:ft|feet|foot|in|inch|inches|oz|lb|ounce)s?)\b[^.]*\.",
    re.I)
RETRIEVE_RE = re.compile(
    r"[^.]*\b(?:retrieve|slow[- ]roll|burn(?:ing)?|hop|dead[- ]?stick|shake|skip|walk(?:ing)?[- ]the[- ]?dog|pause)\b[^.]*\.",
    re.I)
RIG_RE = re.compile(
    r"[^.]*\b(?:rig|rigging|hook (?:size|set)|leader|weight(?:ed)?|tungsten|line size|swivel)\b[^.]*\.",
    re.I)


def _strip_html(s: str) -> str:
    # style/script CONTENT must go before tag-stripping — Shopify body_html often
    # carries <style> blocks whose CSS leaks into spec extraction
    # ("font-weight:400" was matching the depth regex's 'weight' keyword)
    s = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


# ── Shopify catalog (deterministic) ─────────────────────────────────────────
def shopify_catalog(host: str, pages: int = 4) -> list[dict]:
    """Fetch /products.json with disk cache; returns products with etag info."""
    CACHE.mkdir(parents=True, exist_ok=True)
    products = []
    for page in range(1, pages + 1):
        key = CACHE / f"{host.replace('.', '_')}_p{page}.json"
        if key.exists() and time.time() - key.stat().st_mtime < 86400:
            data = json.loads(key.read_text())
        else:
            r = requests.get(f"https://{host}/products.json",
                             params=dict(limit=250, page=page),
                             headers=UA, timeout=20)
            r.raise_for_status()
            data = r.json()
            key.write_text(json.dumps(data))
        products.extend(data.get("products", []))
    return products


def search_catalog(products: list[dict], terms: str, limit: int = 3) -> list[dict]:
    words = [w.lower() for w in terms.split()]
    scored = []
    for p in products:
        tags = p.get("tags") or ""
        if isinstance(tags, list):
            tags = " ".join(str(t) for t in tags)
        title = (p.get("title", "") or "").lower()
        body = _strip_html(p.get("body_html", "")).lower()
        # title hits dominate — body text mentions everything
        score = (5 * sum(1 for w in words if w in title)
                 + 2 * sum(1 for w in words if w in tags.lower())
                 + 1 * sum(1 for w in words if w in body))
        if score >= 5:  # at least one title hit
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:limit]]


def extract_specs(product: dict, host: str) -> dict:
    body = _strip_html(product.get("body_html", ""))
    sentences = [s.strip() for s in body.split(". ")]
    def best(regex):
        for s in sentences:
            m = regex.search(s + ".")
            if m:
                matched = m.group(1).strip() if (m.lastindex or 0) >= 1 else s[:80]
                return dict(quote=s[:300], match=matched)
        return None
    variants = [v.get("title") for v in (product.get("variants") or [])[:8] if v.get("title")]
    return dict(
        manufacturer=product.get("vendor") or "",
        product_title=product.get("title", ""),
        product_url=f"https://{host}/products/{product.get('handle','')}",
        product_type=product.get("product_type", ""),
        variants=variants,
        depth=best(DEPTH_RE), retrieve=best(RETRIEVE_RE), rigging=best(RIG_RE),
    )


# ── agency technique guides (deterministic) ────────────────────────────────
def page_text(url: str) -> tuple[str, str]:
    """Cached fetch of an agency how-to page → (plain text, page title)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / ("ag_" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt")
    if key.exists() and time.time() - key.stat().st_mtime < 86400:
        pair = json.loads(key.read_text())
    else:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        h = r.text
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
        title = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
        t = re.sub(r"(?is)<(style|script|nav|header|footer)[^>]*>.*?</\1>", " ", h)
        t = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()
        pair = [t, title]
        key.write_text(json.dumps(pair))
    return pair[0], pair[1]


def quote_sentences(text: str, specs: list[dict]) -> list[dict]:
    """First sentence matching each {all_of: [...words]} spec, verbatim."""
    sents = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for spec in specs:
        words = [w.lower() for w in spec.get("all_of", [])]
        hit = next((s for s in sents
                    if all(w in s.lower() for w in words)), None)
        out.append(dict(all_of=words, quote=hit,
                        found=bool(hit)))
    return out


def build_agency_draft(species: str, entry_id: str, source: dict) -> dict:
    text, title = page_text(source["url"])
    quotes = quote_sentences(text, source.get("quotes", []))
    return dict(
        entry_id=entry_id, species_kb=species, status="pending",
        source_type="agency",
        proposed=dict(
            agency=source.get("agency", source.get("host", "")),
            page_title=title, source_url=source["url"],
            quotes=quotes,
        ),
        provenance=dict(
            seed_author="agency-ingest/1.0",
            source=f"{source.get('agency', source.get('host', 'agency'))} technique guide",
            source_url=source["url"],
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            extractor="fixed sentence match (all_of words)",
            confidence="sourced",
        ),
        review=dict(verified_by=None, verified_at=None),
    )


# ── draft builder ───────────────────────────────────────────────────────────
def build_draft(species: str, entry_id: str, source: dict, specs: dict, catalog_sha: str) -> dict:
    return dict(
        entry_id=entry_id, species_kb=species, status="pending",
        proposed=specs,
        provenance=dict(
            seed_author="kb-ingest/1.0",
            source=f"{source['brand']} catalog ({source['host']}, Shopify products.json)",
            source_url=specs["product_url"],
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            catalog_sha256=catalog_sha[:16],
            extractor="shopify-products-json + fixed regex",
            confidence="sourced",
        ),
        review=dict(verified_by=None, verified_at=None),
    )


def ingest(species: str, entry_id: str, refresh: bool = False) -> dict | None:
    sources = json.loads((KB / "sources.json").read_text())
    srcs = [s for s in sources.get(species, {}).get(entry_id, []) if s.get("status") == "live"]
    if not srcs:
        return None
    if not refresh:
        kb_file = KB / f"{species}.json"
        if kb_file.exists():
            cur = next((c for c in json.loads(kb_file.read_text()).get("cats", [])
                        if c["id"] == entry_id), None)
            if cur and (cur.get("provenance") or {}).get("confidence") == "sourced":
                return dict(entry_id=entry_id,
                            skipped="already sourced — use --refresh to re-verify")
    src = srcs[0]
    if src.get("type") == "agency":
        draft = build_agency_draft(species, entry_id, src)
        out = PENDING / species
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{entry_id}.json").write_text(json.dumps(draft, indent=2))
        return draft
    catalog = shopify_catalog(src["host"])
    sha = hashlib.sha256(json.dumps(catalog[:50]).encode()).hexdigest()
    hits = search_catalog(catalog, src["search"])
    excl = [w.lower() for w in src.get("title_excludes", [])]
    if excl:
        hits = [h for h in hits
                if not any(w in (h.get("title", "") or "").lower() for w in excl)]
    if not hits:
        return dict(entry_id=entry_id, error="no catalog match for search terms")
    specs = extract_specs(hits[0], src["host"])
    draft = build_draft(species, entry_id, src, specs, sha)
    out = PENDING / species
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{entry_id}.json").write_text(json.dumps(draft, indent=2))
    return draft


def reject(species: str, entry_id: str, by: str, reason: str = "") -> Path | None:
    """Reject a pending draft: delete it and append the decision to kb/rejected.log
    (append-only — a rejected match stays auditable, unlike a silent rm)."""
    p = PENDING / species / f"{entry_id}.json"
    if not p.exists():
        return None
    draft = json.loads(p.read_text())
    log = KB / "rejected.log"
    with log.open("a") as f:
        f.write(json.dumps(dict(
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            species=species, entry_id=entry_id, by=by, reason=reason or "(none given)",
            entity_id=draft["proposed"].get("entity_id"),
            product=draft["proposed"].get("product_title"),
            source_url=draft["provenance"].get("source_url"))) + "\n")
    p.unlink()
    return log


def _pop_entry(kb: dict, entry_id: str):
    """Remove an entry by id from any collection shape a KB file uses:
    a list of `{"id": …}` dicts (`cats`, `trends`) or a dict keyed by id
    (`entries`). Returns (entry, collection_key) or (None, None)."""
    for key, coll in kb.items():
        if isinstance(coll, list):
            for i, c in enumerate(coll):
                if isinstance(c, dict) and c.get("id") == entry_id:
                    return coll.pop(i), key
        elif isinstance(coll, dict) and isinstance(coll.get(entry_id), dict):
            return coll.pop(entry_id), key
    return None, None


def retire(species: str, entry_id: str, by: str, reason: str = "") -> Path | None:
    """Retire a promoted entry: pull it out of its active collection and
    append the full entry to kb/retired.log. The log is append-only, so the
    data stays auditable and recoverable — unlike reject(), which removes a
    pending draft (also logged). Returns the log path, or None if the entry
    isn't in the KB."""
    kb_file = KB / ("trends.json" if species == "trends" else f"{species}.json")
    if kb_file.exists():
        kb = json.loads(kb_file.read_text())
    else:
        return None
    entry, key = _pop_entry(kb, entry_id)
    if entry is None:
        return None
    log = KB / "retired.log"
    with log.open("a") as f:
        f.write(json.dumps(dict(
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            species=species, entry_id=entry_id, by=by,
            reason=reason or "(none given)", collection=key, entry=entry)) + "\n")
    kb_file.write_text(json.dumps(kb, indent=2) + "\n")
    return log


def review_queue() -> list[Path]:
    return sorted(PENDING.glob("*/*.json")) if PENDING.exists() else []


def promote(species: str, entry_id: str, verified_by: str) -> Path | None:
    """Merge a pending draft into the KB. Two shapes:
      - new_entry: append/replace a full KB entry (with citations + provenance);
        honors target_file / target_key for cross-species files (baits, terminal…)
      - spec draft: graft manufacturer_specs / agency_guidance onto an entry
    Technique text stays human-authored — we only graft citations + data."""
    p = PENDING / species / f"{entry_id}.json"
    if not p.exists():
        return None
    draft = json.loads(p.read_text())
    key = draft.get("target_key") or "cats"
    kb_file = KB / (draft.get("target_file") or f"{species}.json")
    if kb_file.exists():
        kb = json.loads(kb_file.read_text())
    else:
        kb = {key: [],
              "label": draft.get("target_label") or kb_file.stem.replace("-", " ").title(),
              "_note": draft.get("target_note", "")}
    prov = draft["provenance"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if draft.get("new_entry"):
        entry = dict(draft["proposed"])
        entry["citations"] = draft.get("citations", [])
        bits = []
        if prov.get("text_sha256"):
            bits.append(f"text sha {prov['text_sha256']}")
        if prov.get("fetched_at"):
            bits.append(f"fetched {prov['fetched_at']}")
        note = (("; ".join(bits) + "; ") if bits else "") + \
               (draft.get("note") or "new entry from a reviewed draft")
        entry["provenance"] = dict(
            seed_author=prov.get("seed_author", "kb-ingest"),
            source=prov.get("source", ""),
            source_url=prov.get("source_url", ""),
            confidence=draft.get("confidence", "sourced"),
            verified_by=verified_by,
            verified_at=now,
            note=note)
        coll = kb.setdefault(key, [])
        for i, c in enumerate(coll):
            if c["id"] == entry_id:
                coll[i] = entry
                break
        else:
            coll.append(entry)
        kb_file.write_text(json.dumps(kb, indent=2) + "\n")
        p.unlink()
        return kb_file

    if draft.get("patch"):
        coll = kb.setdefault(key, [])
        # collections come in two shapes: species files are lists of entries
        # with ids; cross-species tables (kb/substrate.json `entries`) are
        # dicts keyed by entry id. Support both so a patch can target either.
        if isinstance(coll, dict):
            # dict-keyed tables create the entry on first patch (substrate.json
            # `entries` starts empty for rigs with no seed)
            target = coll.setdefault(entry_id, {})
            for k, v in draft["patch"].items():
                if isinstance(v, dict) and isinstance(target.get(k), dict):
                    target[k] = {**target[k], **v}
                else:
                    target[k] = v
            if draft.get("citations"):
                target.setdefault("citations", []).extend(draft["citations"])
        else:
            for c in coll:
                if c["id"] == entry_id:
                    for k, v in draft["patch"].items():
                        if isinstance(v, dict) and isinstance(c.get(k), dict):
                            c[k] = {**c[k], **v}
                        else:
                            c[k] = v
                    if draft.get("citations"):
                        c.setdefault("citations", []).extend(draft["citations"])
                    break
        kb_file.write_text(json.dumps(kb, indent=2) + "\n")
        p.unlink()
        return kb_file

    specs_field = ("agency_guidance" if draft.get("source_type") == "agency"
                   else "manufacturer_specs")
    for c in kb.setdefault(key, []):
        if c["id"] == entry_id:
            c[specs_field] = draft["proposed"]
            bits = []
            if prov.get("catalog_sha256"):
                bits.append(f"catalog sha {prov['catalog_sha256']}")
            if prov.get("fetched_at"):
                bits.append(f"fetched {prov['fetched_at']}")
            if prov.get("extractor"):
                bits.append(prov["extractor"])
            note = (("; ".join(bits) + "; ") if bits else "") + \
                   "technique text human-edited from spec quotes"
            c["provenance"] = dict(
                seed_author=prov["seed_author"],
                source=prov["source"],
                source_url=prov["source_url"],
                confidence="sourced",
                verified_by=verified_by,
                verified_at=now,
                note=note)
            break
    kb_file.write_text(json.dumps(kb, indent=2) + "\n")
    p.unlink()
    return kb_file
