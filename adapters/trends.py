"""Trend adapter — tournament feeds + creator channels → trend drafts (no LLM).

A *trend* is a dated, sourced claim about what is winning or being pushed:
"Day-1 leader threw a glide bait", "chatterbait won the MLF event", "Tom
Redington posted a Carolina Rig masterclass". It is NOT a fact about conditions
and it NEVER enters ranking or offers. The adapter is deterministic: fetch
feeds/channels, find KB-entity mentions, and drop drafts in
`kb/pending/trends/` for human review. Promote with
`fishwitch kb-promote --species trends --entry <id>`.

Sources:
  - tournament/news RSS (MLF, Wired2Fish) — article text + quote
  - registered creator channels (kb/creators.json) — latest upload titles

Policy: creator media is T5 trend/practice, labelled, never a fact tier. A
"how to run it" note stays editorial until a human promotes it; social pushes
get a URL + date and never pay for placement (DESIGN.md).
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

KB = Path(__file__).resolve().parent.parent / "kb"
PENDING = KB / "pending" / "trends"
UA = {"User-Agent": "fishwitch-trends/1.0 (+https://baromoon.com)"}

FEEDS = {
    "mlf": "https://majorleaguefishing.com/feed/",
    "wired2fish": "https://www.wired2fish.com/feed/",
}

# aliases that are also place names / common nouns and create false positives
STOP_ALIASES = {
    "carolina", "texas", "florida", "alabama", "georgia", "tennessee",
    "bait", "fly", "spoon", "worm", "jig", "frog", "crank", "craw",
    "sunfish", "minnow", "shad", "cricket",
}

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_WS = re.compile(r"\s+")
_YTI = re.compile(r"ytInitialData = (\{.*?\});</script>", re.S)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_creators() -> list[dict]:
    p = KB / "creators.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("creators", [])


def _text(url: str) -> tuple[str, str]:
    """(plain text, sha256 of the response) for an article page."""
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    txt = _TAG.sub(" ", r.text)
    return _WS.sub(" ", txt).strip(), hashlib.sha256(r.content).hexdigest()[:16]


def kb_index() -> dict[str, str]:
    """alias (lowercase) -> entity id, across every species + baits."""
    index: dict[str, str] = {}
    try:
        import tactics as tx
        for sp in ("bass", "trout", "catfish", "panfish"):
            for c in tx.catalog(sp):
                for n in [c["label"], c["id"]] + c.get("aliases", []):
                    n = (n or "").strip().lower()
                    if len(n) >= 4 and n not in STOP_ALIASES and n not in index:
                        index[n] = c["id"]
        for b in tx.load_baits().get("baits", []):
            for n in [b["label"], b["id"]]:
                n = (n or "").strip().lower()
                if len(n) >= 4 and n not in index:
                    index[n] = b["id"]
    except Exception:
        pass
    return index


def poll(feeds: dict[str, str] | None = None) -> list[dict]:
    """Latest items from the trend feeds."""
    out = []
    for key, url in (feeds or FEEDS).items():
        try:
            r = requests.get(url, headers=UA, timeout=25)
            root = ET.fromstring(r.content)
        except Exception:
            continue
        for it in root.findall(".//item")[:12]:
            out.append(dict(
                feed=key,
                title=(it.findtext("title") or "").strip(),
                url=(it.findtext("link") or "").strip(),
                date=(it.findtext("pubDate") or "").strip(),
                categories=", ".join((c.text or "") for c in it.findall("category")),
            ))
    return out


def creator_videos(channel_id: str, limit: int = 8) -> list[dict]:
    """Latest uploads for a YouTube channel (lockupViewModel parse; no API key).
    Titles only — descriptions/transcripts are a later drafting step."""
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    try:
        r = requests.get(url, headers={**UA, "Accept-Language": "en-US,en;q=0.9"},
                         timeout=25, cookies={"CONSENT": "YES+1"})
        m = _YTI.search(r.text)
        if not m:
            return []
        data = json.loads(m.group(1))
    except Exception:
        return []
    out: list[dict] = []

    def walk(o):
        if isinstance(o, dict):
            lv = o.get("lockupViewModel")
            if lv:
                meta = (lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}
                title = (meta.get("title") or {}).get("content")
                published = ""
                try:
                    rows = meta["metadata"]["contentMetadataViewModel"]["metadataRows"]
                    parts = rows[0].get("metadataParts") or []
                    texts = [(x.get("text") or {}).get("content", "") for x in parts]
                    published = next((t for t in texts if "ago" in t.lower()), "")
                except Exception:
                    pass
                if lv.get("contentId") and title:
                    out.append(dict(video_id=lv["contentId"], title=title, published=published))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return out[:limit]


def _pat(alias: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(alias) + r"s?\b", re.I)


def _sentences(text: str, alias: str) -> list[str]:
    pat = _pat(alias)
    out = []
    for m in pat.finditer(text):
        a = text.rfind(".", 0, m.start()) + 1
        b = text.find(".", m.end())
        sent = text[a:b + 1].strip() if b >= 0 else text[m.start():m.end() + 160].strip()
        if sent and sent not in out:
            out.append(sent)
    return out


def _write_draft(entity_id: str, source: str, url: str, quote: str, title: str,
                 signal: str, observed_at: str, sha: str | None,
                 slug_hint: str = "", promoted_urls: set[str] | None = None,
                 rejected_pairs: set[tuple[str, str]] | None = None) -> Path | None:
    slug = re.sub(r"[^a-z0-9]+", "-",
                  f"{slug_hint or source}-{entity_id}".lower()).strip("-")
    path = PENDING / f"{slug}.json"
    if (path.exists()
            or (promoted_urls and url in promoted_urls)
            or (rejected_pairs and (entity_id, url) in rejected_pairs)):
        return None
    now = _now()
    draft = {
        "species_kb": "trends", "entry_id": slug, "new_entry": True,
        "target_file": "trends.json", "target_key": "trends",
        "target_label": "Trend signals",
        "target_note": ("Dated, sourced claims about what is winning or being pushed "
                        "(tournament results, creator instruction, viral tackle). Not "
                        "conditions facts; the rank never reads them; the report labels "
                        "them as trend."),
        "source_type": "trend", "confidence": "unverified-editorial",
        "note": f"{title} — {signal} signal from {source}",
        "provenance": {"seed_author": "trends/1.0", "source": source,
                       "source_url": url, "fetched_at": now, "text_sha256": sha},
        "citations": [dict(claim=f"{signal} mention", tier="T5", source=source, url=url,
                           quote=quote[:280], found=True, fetched_at=now, sha256=sha)],
        "proposed": {"id": slug, "entity_id": entity_id, "signal": signal,
                     "source": source, "url": url, "observed_at": observed_at,
                     "quote": quote[:280], "note": title},
    }
    path.write_text(json.dumps(draft, indent=2) + "\n")
    return path


def promoted_urls() -> set[str]:
    """URLs already promoted in kb/trends.json — never re-draft them."""
    try:
        import tactics as tx
        return {t.get("url") for t in tx.load_trends().get("trends", []) if t.get("url")}
    except Exception:
        return set()


def retired_urls() -> set[str]:
    """URLs of retired trends (kb/retired.log) — never re-draft those either."""
    out: set[str] = set()
    try:
        for line in (KB / "retired.log").read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            url = (r.get("entry") or {}).get("url")
            if url:
                out.add(url)
    except Exception:
        pass
    return out


def rejected_pairs() -> set[tuple[str, str]]:
    """(entity_id, url) pairs a human rejected — never re-draft those either."""
    out: set[tuple[str, str]] = set()
    try:
        for line in (KB / "rejected.log").read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("entity_id") and r.get("source_url"):
                out.add((r["entity_id"], r["source_url"]))
    except Exception:
        pass
    return out


def draft(limit_per_feed: int = 4, limit_per_creator: int = 8) -> list[Path]:
    """Fetch feeds + creator channels, find KB entities, write trend drafts."""
    PENDING.mkdir(parents=True, exist_ok=True)
    index = kb_index()
    by_len = sorted(index.items(), key=lambda kv: -len(kv[0]))
    written: list[Path] = []
    promoted = promoted_urls() | retired_urls()
    rejected = rejected_pairs()

    for item in poll()[:limit_per_feed * len(FEEDS)]:
        url = item.get("url")
        if not url:
            continue
        try:
            text, sha = _text(url)
        except Exception:
            continue
        seen_entities: set[str] = set()
        for alias, eid in by_len:
            if eid in seen_entities:
                continue
            sents = _sentences(text, alias)
            if sents:
                seen_entities.add(eid)
                src = item["feed"].upper() if item["feed"] == "mlf" else item["feed"].title()
                p = _write_draft(eid, f"{src} — {item['title'][:70]}", url, sents[0],
                                 item["title"], "tournament", item.get("date", "")[:16],
                                 sha, slug_hint=f"{item['feed']}-{item.get('date','')[:10]}",
                                 promoted_urls=promoted, rejected_pairs=rejected)
                if p:
                    written.append(p)

    for c in load_creators():
        for v in creator_videos(c["channel_id"], limit=limit_per_creator):
            for alias, eid in by_len:
                if _pat(alias).search(v["title"]):
                    url = f"https://www.youtube.com/watch?v={v['video_id']}"
                    p = _write_draft(eid, f"YouTube — {c['name']}", url, v["title"],
                                     v["title"], "creator", v.get("published") or _now()[:10],
                                     None, slug_hint=f"yt-{c['id']}", promoted_urls=promoted,
                                     rejected_pairs=rejected)
                    if p:
                        written.append(p)
                    break
    return written
