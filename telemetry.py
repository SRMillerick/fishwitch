"""Aggregate page telemetry — the privacy-preserving counterpart to the
outbound-click counter (`logs/out.jsonl`, see `offers.py`).

What is stored: one JSON line per page view — UTC timestamp, route path, the
lake registry key when the route carries one, the *external referrer host*, and
a boolean `bot` flag derived from the request's user agent at write time. No IP
address, no user-agent string, no cookies, no full referrer URL, no query
strings. The bot flag is what lets `fishwitch stats` separate crawlers from
people without ever keeping the thing that identified them. Read with
`fishwitch stats`; the local web app can render the same summary at /stats.

Referrers are classified into channels (search / ai / social / internal / spam /
external / direct) and obvious link-spam hosts are quarantined, so the numbers
that reach an affiliate application are defensible rather than inflated.

This is deliberately dumb (append-only, day-rollable by the reader) so it can
never become a user profile: there is no session id and nothing to join on.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

PAGES = Path(__file__).resolve().parent / "logs" / "pages.jsonl"

# routes that are not "pages" for counting purposes
SKIP_PREFIXES = ("/static/", "/out/", "/api/", "/favicon", "/stats")
SKIP_EXACT = ("/robots.txt", "/sitemap.xml", "/ledger.ics", "/outlook.rss", "/sw.js")

_LAKE_SAFE = re.compile(r"[^a-z0-9-]")

# Crawler user agents (a superset on purpose: the flag only ever excludes a
# view from the *human* read, the raw total keeps everything).
_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|validator|scrape|monitor|uptime|headless|"
    r"lighthouse|pagespeed|curl/|wget|python-requests|httpx|go-http-client|"
    r"libwww|java/|okhttp|facebookexternalhit|whatsapp|telegram|slack|discord|"
    r"semrush|ahrefs|mj12|dotbot|petalbot|bytespider|gptbot|ccbot|claudebot|"
    r"perplexity|amazonbot|applebot|bingpreview|feedfetcher", re.I)

# Referrer channels. Hosts are matched exactly or as a parent domain
# ("www.google.com" matches "google.com"), never by loose substring.
INTERNAL_HOSTS = ("baromoon.com",)
SEARCH_HOSTS = ("google.com", "bing.com", "duckduckgo.com", "search.yahoo.com",
                "yahoo.com", "ecosia.org", "qwant.com", "startpage.com",
                "brave.com", "search.brave.com", "yandex.com", "baidu.com")
# AI assistants that cite/link sources — tracked as their own channel so the
# GEO (generative-engine) funnel is readable, not lumped into "external".
AI_HOSTS = ("chatgpt.com", "chat.openai.com", "openai.com", "perplexity.ai",
            "gemini.google.com", "bard.google.com", "copilot.microsoft.com",
            "claude.ai", "you.com", "poe.com", "phind.com")
SOCIAL_HOSTS = ("t.co", "twitter.com", "x.com", "facebook.com", "reddit.com",
                "instagram.com", "pinterest.com", "linkedin.com", "youtube.com",
                "youtu.be", "news.ycombinator.com", "threads.net", "bsky.app",
                "mastodon.social", "discord.com")
# Known link-spam / SEO-report referrers (they hit the site only to appear in
# analytics). Plus the generic markers below.
SPAM_HOSTS = ("digitizeseo.com", "bulkbacklinkreport.site", "bulkdachecker.store",
              "seoblogchecker.store", "backlinkspace.com", "dataindex.pro",
              "skyrocket-ranking-with-high-quality-backlinks.site", "1seoservices.com",
              "blogbacklinkchecker.shop", "ailinkgenerator.website")
SPAM_MARKERS = ("backlink", "seo", "checker", "rank-", "-rank")

CHANNEL_ORDER = ("search", "ai", "social", "external", "internal", "direct", "spam")


def should_count(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path.startswith(SKIP_PREFIXES) or path in SKIP_EXACT:
        return False
    return True


def normalize_lake(value: str | None) -> str:
    """Registry keys only. Free text, coordinates, and anything over the key
    bound are dropped outright (truncation would let distinct inputs collide
    into one aggregate bucket)."""
    if not value:
        return ""
    v = _LAKE_SAFE.sub("", value.strip().lower())
    return v if 3 <= len(v) <= 64 else ""


def is_bot(user_agent: str | None) -> bool:
    """Coarse crawler check; the UA string itself is never stored."""
    return bool(user_agent and _BOT_RE.search(user_agent))


def _host_matches(host: str, parent: str) -> bool:
    return host == parent or host.endswith("." + parent)


def classify_ref(ref: str | None) -> str:
    """Channel of a stored referrer host. `""` (no referrer) is `direct`.

    Channels: search, ai, social, internal, spam, external, direct.
    """
    host = (ref or "").strip().lower()
    if not host:
        return "direct"
    if any(_host_matches(host, h) for h in INTERNAL_HOSTS):
        return "internal"
    if any(_host_matches(host, h) for h in AI_HOSTS):
        return "ai"
    if any(_host_matches(host, h) for h in SEARCH_HOSTS):
        return "search"
    if any(_host_matches(host, h) for h in SOCIAL_HOSTS):
        return "social"
    if (host in SPAM_HOSTS
            or any(m in host for m in SPAM_MARKERS)
            or host.endswith((".shop", ".store", ".website")) and "link" in host):
        return "spam"
    return "external"


def record(path: str, lake: str | None = None, ref: str | None = None,
           ua: str | None = None, log: Path | None = None) -> None:
    """Append one aggregate view line. Never raises (telemetry is best-effort)."""
    try:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "path": path[:96], "lake": normalize_lake(lake), "ref": _ref_host(ref)}
        if is_bot(ua):
            line["bot"] = True
        with (log or PAGES).open("a") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass


def _ref_host(ref: str | None) -> str:
    if not ref:
        return ""
    try:
        host = (urlparse(ref).netloc or "").lower().split("@")[-1].split(":")[0]
        return host[:64]
    except Exception:
        return ""


def parse(lines: list[str] | tuple[str, ...]) -> list[dict]:
    """Parse JSONL page-view lines, dropping malformed or off-shape rows."""
    rows = []
    for line in lines:
        try:
            r = json.loads(line)
            if isinstance(r, dict) and r.get("path"):
                rows.append(r)
        except Exception:
            pass
    return rows


def read(log: Path | None = None) -> list[dict]:
    p = log or PAGES
    if not p.exists():
        return []
    return parse(p.read_text().splitlines())


def summarize(days: int = 30, log: Path | None = None, top: int = 15,
              rows: list[dict] | None = None) -> dict:
    """Aggregate rows within the trailing `days` window (UTC).

    Pass `rows` to summarize an already-parsed log (e.g. read from the
    production box) instead of reading the local file."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    window = []
    for r in (rows if rows is not None else read(log)):
        try:
            ts = datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                window.append(r)
        except Exception:
            continue
    by_path = Counter(r.get("path") or "?" for r in window)
    by_lake = Counter(r.get("lake") for r in window if r.get("lake"))
    by_day = Counter(str(r.get("ts", ""))[:10] for r in window)
    channels = Counter(classify_ref(r.get("ref")) for r in window)
    # by_ref is the honest external list: internal navigation and known
    # link-spam are broken out into channels / spam_refs instead.
    by_ref = Counter(r.get("ref") for r in window
                     if r.get("ref") and classify_ref(r["ref"]) in
                     ("external", "search", "ai", "social"))
    spam_refs = Counter(r.get("ref") for r in window
                        if r.get("ref") and classify_ref(r["ref"]) == "spam")
    bots = sum(1 for r in window if r.get("bot"))
    return dict(total=len(window), days=days, bots=bots,
                bot_rows=max(0, len(window) - bots),
                channels=[(c, channels[c]) for c in CHANNEL_ORDER if channels.get(c)],
                by_path=by_path.most_common(top),
                by_lake=by_lake.most_common(top),
                by_ref=by_ref.most_common(top),
                spam_refs=spam_refs.most_common(top),
                by_day=sorted(by_day.items()))
