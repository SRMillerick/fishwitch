#!/usr/bin/env python3
"""fishwitch web — the front door (pre-Associates milestone).

A thin Flask presentation layer over the deterministic pipe. The report path
is untouched: same generate(), same KB, same scoring — the web only renders.

Privacy model (this is the whole point):
  - Angler profiles (birth data = identity-grade PII) are NEVER stored
    server-side. They live in the visitor's browser (localStorage) and travel
    only inside a POST body to render a report. Nothing is written to disk,
    nothing is logged.
  - The logbook + local profiles stay local: /review only exists when the
    server is started with FISHWITCH_LOCAL=1 (a self-hosted session).

Monetization model (Amazon-ready, no account yet):
  - Offers resolve at the END of the pipe (offers.py), always disclosed,
    never visible to ranking. Manufacturer links come from promoted KB
    provenance; affiliate URLs activate once ASINs exist (PA-API).

Run:  ./webapp                 # http://127.0.0.1:7700  (safe default)
      FISHWITCH_LOCAL=1 ./webapp          # + /review calibration panel
      FISHWITCH_WEB_HOST=0.0.0.0 ./webapp # public deploy (your call)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, Response, abort, jsonify, redirect, render_template, request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))          # script-style imports (import logbook)
sys.path.insert(0, str(ROOT.parent))   # package imports (from fishwitch import geo)

import markdown as _md  # noqa: E402  (pip install markdown)
import offers  # noqa: E402
import public_api  # noqa: E402
import telemetry  # noqa: E402
import glyphs  # noqa: E402
import tactics as tx  # noqa: E402
import viz  # noqa: E402
from layers.history import History  # noqa: E402
from report import generate as gen, to_markdown  # noqa: E402
from weather import Weather  # noqa: E402

LOCAL = os.environ.get("FISHWITCH_LOCAL", "") == "1"
CONFIG = ROOT / "config"
LOG = ROOT / "logs" / "out.jsonl"   # aggregate outbound-click counts (no PII)


def _asset_v() -> str:
    """Cache-bust token = newest mtime across static assets + templates. Any
    asset change (a deploy pull, an edit) changes the URL, so the 1-year static
    cache can never serve stale CSS/JS."""
    files = list((ROOT / "web" / "static").glob("*")) + list((ROOT / "web" / "templates").glob("*.html"))
    return str(int(max((f.stat().st_mtime for f in files if f.is_file()), default=0)))


ASSET_V = _asset_v()

app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"),
            static_folder=str(ROOT / "web" / "static"))
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # profiles are small; bigger bodies are abuse
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000  # static assets are URL-versioned (?v=), cache hard


@app.after_request
def _count_page(resp):
    """Aggregate page counts (telemetry.py): path + lake key + external
    referrer host only — no IP, no user agent, no cookies, no query string.
    Best-effort; a telemetry failure must never fail a page."""
    try:
        if (request.method == "GET" and resp.status_code == 200
                and request.args.get("warm") != "1"
                and telemetry.should_count(request.path)):
            telemetry.record(request.path, lake=request.args.get("lake"),
                             ref=request.referrer)
    except Exception:
        pass
    # installed PWAs keep asking for the un-versioned manifest URL; let them
    # revalidate so icon changes actually land (see the versioned icons)
    if request.path == "/static/manifest.webmanifest":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.context_processor
def inject_asset_v():
    return dict(asset_v=ASSET_V, local=LOCAL)


# ── shared, cached data layers (one weather call serves many renders) ───────
_WX: dict[tuple, tuple] = {}


def shared_weather(lat: float, lng: float, days: int = 7) -> Weather:
    key = (round(lat, 3), round(lng, 3), days)
    hit = _WX.get(key)
    if hit and time.time() - hit[1] < 1800:
        return hit[0]
    w = Weather(lat, lng, forecast_days=days)
    _WX[key] = (w, time.time())
    return w


_HIST: dict[tuple, tuple] = {}


def shared_history(lat: float, lng: float, at: datetime) -> History | None:
    key = (round(lat, 3), round(lng, 3), at.date().isoformat())
    hit = _HIST.get(key)
    if hit and time.time() - hit[1] < 3600:
        return hit[0]
    try:
        h = History(lat, lng, at)
    except Exception:
        return None
    _HIST[key] = (h, time.time())
    return h


_RCACHE: dict[str, tuple] = {}


def _cached(key: str, fn):
    """In-memory render cache, 20 min TTL, 128 entries. Keys are hashes —
    profile contents are never stored, only a digest of them."""
    hit = _RCACHE.get(key)
    if hit and time.time() - hit[1] < 1200:
        return hit[0]
    val = fn()
    if len(_RCACHE) > 128:
        _RCACHE.pop(min(_RCACHE.items(), key=lambda kv: kv[1][1])[0], None)
    _RCACHE[key] = (val, time.time())
    return val


# ── helpers ──────────────────────────────────────────────────────────────────
def registry() -> dict:
    p = CONFIG / "lakes.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    for k, v in d.items():
        v["id"] = k   # the registry key is canonical; stored ids can be OSM labels
    return d


def _region(v: dict) -> str:
    """Human location for a water: explicit `region`, else the OSM/Wikidata
    `display` string with its name prefix dropped, else county + CA."""
    r = (v.get("region") or "").strip()
    if r:
        return r
    d = (v.get("display") or "").strip()
    if d:
        name = (v.get("name") or "").lower()
        parts = [p.strip() for p in d.split(",")]
        if parts and name and (name in parts[0].lower() or parts[0].lower() in name):
            parts = parts[1:]
        return ", ".join(parts)
    c = (v.get("county") or "").strip()
    return f"{c} County, CA" if c else ""


def lakes_summary() -> list[dict]:
    out = []
    for k, v in registry().items():
        out.append(dict(id=k, name=v.get("name", k), region=_region(v),
                        lat=v.get("lat"), lng=v.get("lng"),
                        species=v.get("species", [])))
    return out


def resolve_lake(key: str | None) -> dict | None:
    reg = registry()
    if not key:
        return reg.get("hidden-valley-lake-ca") or next(iter(reg.values()), None)
    if key in reg:
        return reg[key]
    for v in reg.values():
        if (v.get("name") or "").lower() == key.lower():
            return v
    return None


def _clamp_at(s: str | None) -> datetime:
    now = datetime.now()
    lo = (now - timedelta(days=2)).replace(hour=0, minute=0)
    hi = (now + timedelta(days=16)).replace(hour=23, minute=59)
    at = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if s:
        try:
            at = datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                at = datetime.strptime(s, "%Y-%m-%d")
            except ValueError:
                pass
    return max(lo, min(hi, at))


def _client_profile(payload: dict) -> tuple[dict, list[str]]:
    """Validate the documented profile shape from the POST body. Returns
    (profile, errors) — never raises, never persists. The server treats every
    incoming profile as untrusted input even though it originates in the
    visitor's own browser."""
    errs: list[str] = []
    p = payload.get("profile")
    if p in (None, {}):
        return {}, []
    if not isinstance(p, dict):
        return {}, ["profile must be a JSON object"]
    out: dict = {}
    name = p.get("name")
    if name is not None:
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 40):
            errs.append("name: 1–40 characters")
        else:
            out["name"] = name.strip()
    sp = p.get("species")
    if sp is not None:
        if not isinstance(sp, str) or len(sp) > 40:
            errs.append("species: string ≤ 40 chars")
        else:
            out["species"] = sp
    ars = p.get("arsenal")
    if ars is not None:
        if (not isinstance(ars, list) or len(ars) > 30
                or not all(isinstance(a, str) and 0 < len(a) <= 60 for a in ars)):
            errs.append("arsenal: list of ≤ 30 strings, each ≤ 60 chars")
        else:
            out["arsenal"] = ars
    kn = p.get("knots")
    if kn is not None:
        if (not isinstance(kn, list) or len(kn) > 30
                or not all(isinstance(a, str) and 0 < len(a) <= 60 for a in kn)):
            errs.append("knots: list of ≤ 30 strings, each ≤ 60 chars")
        else:
            out["knots"] = kn
    ln = p.get("line")
    if ln is not None:
        if (not isinstance(ln, list) or len(ln) > 30
                or not all(isinstance(a, str) and 0 < len(a) <= 60 for a in ln)):
            errs.append("line: list of ≤ 30 strings, each ≤ 60 chars")
        else:
            out["line"] = ln
    bt = p.get("baits")
    if bt is not None:
        if (not isinstance(bt, list) or len(bt) > 30
                or not all(isinstance(a, str) and 0 < len(a) <= 60 for a in bt)):
            errs.append("baits: list of ≤ 30 strings, each ≤ 60 chars")
        else:
            out["baits"] = bt
    su = p.get("setups")
    if su is not None:
        ok = (isinstance(su, dict) and len(su) <= 30
              and all(isinstance(k, str) and 0 < len(k) <= 60 for k in su)
              and all(isinstance(v, dict) and len(v) <= 20
                      and all(isinstance(x, str) and 0 < len(x) <= 120 for x in v.values())
                      for v in su.values()))
        if not ok:
            errs.append("setups: object of rig → object of strings (≤ 30 rigs, ≤ 20 parts, each ≤ 120 chars)")
        else:
            out["setups"] = su
    hl = p.get("home_lake")
    if hl is not None:
        if not isinstance(hl, str) or len(hl) > 60:
            errs.append("home_lake: string ≤ 60 chars")
        else:
            out["home_lake"] = hl
    ad = p.get("astro_display")
    if ad is not None:
        if ad not in ("fisher", "almanac", "astro"):
            errs.append("astro_display: fisher | almanac | astro")
        else:
            out["astro_display"] = ad
    b = p.get("birth")
    if b is not None:
        if not isinstance(b, dict):
            errs.append("birth: object")
        else:
            bd = {}
            date = b.get("date")
            try:
                d = datetime.strptime(str(date), "%Y-%m-%d")
                if not (1850 <= d.year <= 2100):
                    raise ValueError
                bd["date"] = str(date)
            except (TypeError, ValueError):
                errs.append("birth.date: YYYY-MM-DD between 1850 and 2100")
            t = b.get("time")
            try:
                datetime.strptime(str(t), "%H:%M")
                bd["time"] = str(t)
            except (TypeError, ValueError):
                errs.append("birth.time: HH:MM (24h)")
            tk = b.get("time_known")
            bd["time_known"] = bool(tk) if tk is not None else True
            for k, lo, hi in (("lat", -90, 90), ("lng", -180, 180)):
                v = b.get(k, 0)
                try:
                    v = float(v)
                    if not (lo <= v <= hi):
                        raise ValueError
                    bd[k] = v
                except (TypeError, ValueError):
                    errs.append(f"birth.{k}: number {lo}…{hi}")
            tz = b.get("tz")
            if tz is not None:
                if not isinstance(tz, str) or len(tz) > 64:
                    errs.append("birth.tz: string ≤ 64 chars")
                else:
                    bd["tz"] = tz
            pl = b.get("place")
            if pl is not None:
                if not isinstance(pl, str) or len(pl) > 120:
                    errs.append("birth.place: string ≤ 120 chars")
                else:
                    bd["place"] = pl
            out["birth"] = bd
    return out, errs


# ── tiny rate limiter (in-memory; per-IP token window) ──────────────────
_HITS: dict[str, list] = {}


def _rate_ok(bucket: str, limit: int, window_s: int = 3600) -> bool:
    """Anonymous public deploys get 30 reports / 60 geocodes per visitor-hour;
    FISHWITCH_LOCAL sessions are trusted (it's your own machine)."""
    if LOCAL:
        return True
    now = time.time()
    hits = [t for t in _HITS.get(bucket, []) if now - t < window_s]
    if len(hits) >= limit:
        _HITS[bucket] = hits
        return False
    hits.append(now)
    _HITS[bucket] = hits
    return True


_TD_RE = re.compile(r"<td([^>]*)>")


def _responsive_tables(html: str) -> str:
    """Wrap rendered markdown tables for responsive display and tag every cell
    with its column header, so narrow screens can stack rows (label above
    value) instead of forcing horizontal scroll. Desktop rendering is
    unchanged — the data-label is inert until the mobile breakpoint."""
    def fix(m):
        table = m.group(1)
        heads = [re.sub(r"<[^>]+>", "", h).strip().replace('"', "&quot;")
                 for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
        out = []
        for part in table.split("<tr>"):
            if heads and "<td" in part:
                i = [0]

                def label(mo):
                    attrs = mo.group(1)
                    if "data-label" in attrs:
                        return mo.group(0)
                    lbl = heads[i[0] % len(heads)]
                    i[0] += 1
                    return f'<td{attrs} data-label="{lbl}">'
                part = _TD_RE.sub(label, part)
            out.append(part)
        table = "<tr>".join(out)
        return f'<div class="table-scroll"><table>{table}</table></div>'
    return re.sub(r"<table>(.*?)</table>", fix, html, flags=re.S)


def _render_report(profile: dict, lake: dict, at: datetime, hours: float,
                   voice: str | None, species: str | None,
                   bottom: str | None = None, clarity: str | None = None) -> dict:
    wx = shared_weather(lake["lat"], lake["lng"])
    hist = shared_history(lake["lat"], lake["lng"], at)
    m = gen(profile, lake, at, hours=hours, species=species,
            voice=voice or profile.get("astro_display") or "almanac",
            wx=wx, hist=hist, bottom=bottom, clarity=clarity)
    body = _md.markdown(to_markdown(m, emoji=False, show_gap=False, symbols=True),
                        extensions=["tables"])
    body = glyphs.symbolize(_responsive_tables(body))
    prime = m.get("prime")
    owned_ids = m.get("owned_ids") or set()
    has_box = bool(m.get("has_baseline"))
    rods = []
    setups = profile.get("setups") if isinstance(profile.get("setups"), dict) else {}
    for c in m["rods"]:
        mfg = (c.get("manufacturer_specs") or {})
        rod = dict(id=c["id"], label=c["label"],
                   owned=(c["id"] in owned_ids) if has_box else None,
                   spec=tx.rig_spec(c["id"]),
                   spec_line=tx.spec_line(tx.rig_spec(c["id"])),
                   your_setup_line=tx.setup_line(setups.get(c["id"])),
                   verified=c["provenance"].get("confidence") == "verified"
                   or c["provenance"].get("confidence") == "sourced",
                   source=c["provenance"].get("source", "plain-language summary"),
                   source_url=c["provenance"].get("source_url"),
                   product=mfg.get("product_title"),
                   product_url=mfg.get("product_url"),
                   offers=offers.resolve(c["id"]),
                   components=offers.components(c["id"]))
        rods.append(rod)
    gap = []
    for c, s, why in (m.get("gap") or []):
        mfg = (c.get("manufacturer_specs") or {})
        gap.append(dict(id=c["id"], label=c["label"], score=round(s, 1),
                        kind=c.get("kind", "product"),
                        why="; ".join(why),
                        verified=c["provenance"].get("confidence") in ("verified", "sourced"),
                        product=mfg.get("product_title"),
                        product_url=mfg.get("product_url"),
                        offers=offers.resolve(c["id"]),
                        components=offers.components(c["id"])))
    return dict(html=body, timeline=viz.session_timeline_svg(m),
                overall=m["scores"]["overall"],
                lake=lake["name"], at=at, rods=rods, gap=gap,
                shopping=offers.build_shopping(
                    [{"id": r["id"], "label": r["label"], "spec": r.get("spec")} for r in rods]),
                trends=m.get("trends") or [],
                prime_t=prime["start"] if prime else None,
                prime_lab=(prime["light"] if prime else ""),
                moon=m.get("moon") or {},
                moon_svg=_moon_svg((m.get("moon") or {}).get("illum", 0),
                                   (m.get("moon") or {}).get("elong", 0) < 180, size=17),
                picks=[c["label"] for c, _, _ in (prime["picks"] if prime else [])][:2])


def _report_response(payload: dict, anonymous: bool) -> dict:
    lake = resolve_lake(payload.get("lake"))
    if lake is None:
        return dict(error="unknown lake")
    at = _clamp_at(payload.get("at"))
    hours = min(8.0, max(0.5, float(payload.get("hours") or 2.5)))
    voice = payload.get("voice")
    if voice not in ("fisher", "almanac", "astro"):
        voice = None
    species = (payload.get("species") or "").strip()[:40] or None
    bottom = payload.get("bottom")
    if bottom not in ("grass", "muck", "sand", "rock", "wood"):
        bottom = None
    clarity = tx.normalize_clarity(payload.get("clarity")) or None
    profile, errs = ({}, []) if anonymous else _client_profile(payload)
    if errs:
        return dict(error="profile rejected", details=errs)

    def run():
        return _render_report(profile, lake, at, hours, voice, species, bottom, clarity)

    if anonymous:  # cacheable — no personal data involved
        key = "anon:" + json.dumps([str(payload.get("lake")), at.isoformat(),
                                    hours, voice, species, bottom, clarity], default=str)
        return _cached(key, run)
    return run()


# ── pages ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    """The landing ledger. Anonymous visitors get a demo water (Hidden Valley)
    unless `?lake=<id>` names one — the browser layer uses that param to
    re-render for the water nearest the visitor. The nearest-water pick is made
    in the browser; coordinates never reach this server."""
    teaser = None
    ledger = None
    requested = (request.args.get("lake") or "").strip()
    home = resolve_lake(requested or None)
    if home is None:  # unknown name/id: fall back to the demo water
        home = resolve_lake(None)
    lake_id = home.get("id") if home else None
    try:
        tonight = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
        out = _report_response(dict(lake=lake_id, at=tonight.strftime("%Y-%m-%d %H:%M"),
                                     hours="2.5", voice="almanac"), anonymous=True)
        if "error" not in out:
            teaser = out
    except Exception:
        pass
    if home:
        try:
            ledger = _cached(f"ledger:anon:{lake_id}:3:v3",
                             lambda: _ledger(home, 3, None, None, span=0, limit=6))
        except Exception:
            pass
    waters = [dict(id=l["id"], name=l["name"], lat=l["lat"], lng=l["lng"])
              for l in lakes_summary() if l.get("lat") is not None and l.get("lng") is not None]
    return render_template("index.html", lakes=lakes_summary(), local=LOCAL,
                           teaser=teaser, ledger=ledger, home=home,
                           waters_json=json.dumps(waters))


@app.route("/report")
def report_page():
    q = dict(lake=request.args.get("lake") or "",
             at=request.args.get("at") or "",
             hours=request.args.get("hours") or "2.5",
             voice=request.args.get("voice") or "",
             species=request.args.get("species") or "",
             bottom=request.args.get("bottom") or "",
             clarity=request.args.get("clarity") or "")
    out = None
    if q["lake"] or q["at"] or q["species"]:
        out = _report_response(q, anonymous=True)
    return render_template("report.html", lakes=lakes_summary(), q=q, out=out,
                           local=LOCAL)


@app.route("/outlook")
def outlook_page():
    reg = registry()
    lake = resolve_lake(request.args.get("lake"))
    days = max(1, min(16, int(request.args.get("days") or 7)))
    species = (request.args.get("species") or "").strip() or None
    rows, moon = [], []
    err = None
    if lake:
        try:
            rows, moon = _cached(
                f"outlook:{lake['name']}:{days}:{species}",
                lambda: _horizon(lake, days, species))
        except Exception as ex:
            err = str(ex)
    return render_template("outlook.html", lakes=lakes_summary(), lake=lake,
                           days=days, rows=rows, moon=moon, err=err, local=LOCAL)


@app.route("/ledger.ics")
def ledger_ics():
    """Subscribeable calendar of the A/S windows — same horizon scan as
    /outlook, rendered as ICS. No accounts, no email, no tracking."""
    import feeds
    lake = resolve_lake(request.args.get("lake"))
    if not lake:
        abort(404)
    try:
        days = max(1, min(16, int(request.args.get("days") or 10)))
    except ValueError:
        days = 10
    species = (request.args.get("species") or "").strip() or None
    try:
        rows, _ = _cached(f"outlook:{lake['name']}:{days}:{species}",
                          lambda: _horizon(lake, days, species))
    except Exception:
        rows = []
    body = feeds.ical([r for r in rows if r["overall"] >= feeds.MIN_OVERALL], lake)
    return Response(body, mimetype="text/calendar",
                    headers={"Content-Disposition": "inline; filename=baromoon.ics",
                             "Cache-Control": "public, max-age=900"})


@app.route("/outlook.rss")
def outlook_rss():
    """RSS of the same A/S windows for readers/aggregators."""
    import feeds
    lake = resolve_lake(request.args.get("lake"))
    if not lake:
        abort(404)
    try:
        days = max(1, min(16, int(request.args.get("days") or 10)))
    except ValueError:
        days = 10
    species = (request.args.get("species") or "").strip() or None
    try:
        rows, _ = _cached(f"outlook:{lake['name']}:{days}:{species}",
                          lambda: _horizon(lake, days, species))
    except Exception:
        rows = []
    body = feeds.rss([r for r in rows if r["overall"] >= feeds.MIN_OVERALL], lake)
    return Response(body, mimetype="application/rss+xml",
                    headers={"Cache-Control": "public, max-age=900"})


def _horizon(lake: dict, days: int, species: str | None, profile: dict | None = None):
    profile = profile or dict(species=species or "bass", astro_display="almanac",
                              arsenal=[])
    wx = shared_weather(lake["lat"], lake["lng"], days=days)
    hist = shared_history(lake["lat"], lake["lng"], datetime.now())
    from skycalc import Sky
    sky = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)
    results = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(1, days + 1):
        day = today + timedelta(days=d)
        for h in (5, 9, 12, 15, 17, 20):
            start = day.replace(hour=h, minute=30 if h == 17 else 0)
            try:
                m = gen(profile, lake, start, hours=2.0,
                        species=species, voice=profile.get("astro_display") or "fisher",
                        wx=wx, hist=hist)
            except Exception:
                continue
            if not m["blocks"]:
                continue
            prime = m["prime"]
            results.append(dict(
                day=day.date().isoformat(), start=start, end=start + timedelta(hours=2),
                overall=m["scores"]["overall"],
                prime=prime["start"] if prime else None,
                picks=[c["label"] for c, _, _ in (prime["picks"] if prime else [])][:2],
                conf="high" if d <= 3 else ("med" if d <= 7 else "low")))
    results.sort(key=lambda r: -r["overall"])
    moon = []
    for d in range(1, days + 1):
        dd = (today + timedelta(days=d))
        ms = sky.moon_state(sky.jd(dd.replace(hour=12)))
        moon.append((dd.date().isoformat(), ms["phase"], round(ms["illum"]),
                     _moon_svg(ms["illum"], ms["elong"] < 180, size=14)))
    return results[:10], moon


# ── the tier ledger: best upcoming windows across nearby waters ────────────
import math


def _nearest_lakes(home: dict, n: int = 3) -> list[dict]:
    def dist(a, b):
        la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
        return 6371 * math.acos(min(1, math.sin(la1) * math.sin(la2) +
                                    math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1)))
    reg = registry()
    home_key = home.get("id") or home["name"]
    ranked = sorted((v for v in reg.values()
                     if (v.get("id") or v["name"]) != home_key),
                    key=lambda v: dist(home, v))
    return [home] + ranked[:n]


def _tier(overall: float) -> str:
    return "S" if overall >= 7.5 else "A" if overall >= 7.0 else "B" if overall >= 6.5 else "C"


def _moon_svg(illum: float, waxing: bool, size: int = 15) -> str:
    """Vector moon for the illuminated fraction. Drawn, never a font glyph,
    so it renders identically on every system."""
    r, c = 8.0, 10.0
    f = max(0.0, min(1.0, float(illum) / 100.0))
    outer = 1 if waxing else 0
    if waxing:
        term = 0 if f < 0.5 else 1
    else:
        term = 1 if f < 0.5 else 0
    rx = abs(1.0 - 2.0 * f) * r
    d = (f"M{c:g},{c - r:g} A{r:g},{r:g} 0 0,{outer} {c:g},{c + r:g} "
         f"A{rx:.3f},{r:g} 0 0,{term} {c:g},{c - r:g} Z")
    return (f'<svg class="moon-svg" width="{size}" height="{size}" viewBox="0 0 20 20" '
            f'aria-hidden="true" focusable="false">'
            f'<circle cx="{c:g}" cy="{c:g}" r="{r:g}" fill="none" stroke="currentColor" '
            f'stroke-width="1" opacity=".32"/>'
            f'<path d="{d}" fill="currentColor"/></svg>')


def _ledger(home: dict, days: int, species: str | None, profile: dict | None,
            span: int = 3, limit: int = 8) -> list[dict]:
    """Tier-ranked windows across the home water + `span` nearest. Deterministic
    scans; caller caches. span=0 = home water only (fast landing render).
    Windows are deduped by clock — best-scoring water wins each slot — so the
    ledger reads as an edit, not a dump."""
    lakes = [home] if span == 0 else _nearest_lakes(home, span)
    best: dict[tuple, dict] = {}
    for lk in lakes:
        try:
            wins, moon = _horizon(lk, days, species, profile)
        except Exception:
            continue
        moonmap = {d: svg for d, ph, il, svg in moon}
        for w in wins:
            key = (w["day"], w["start"])
            cand = dict(
                tier=_tier(w["overall"]), overall=w["overall"],
                day=w["start"].strftime("%a %b %-d"),
                start=w["start"], end=w["end"], prime=w["prime"],
                lake=lk["name"], lake_id=lk.get("id") or lk["name"],
                rig=w["picks"][0] if w["picks"] else "",
                conf=w["conf"], moon=moonmap.get(w["day"], ""),
                others=0)
            cur = best.get(key)
            if cur is None:
                best[key] = cand
            elif cand["overall"] > cur["overall"]:
                cand["others"] = cur.get("others", 0) + 1
                best[key] = cand
            else:
                cur["others"] = cur.get("others", 0) + 1
    order = {"S": 0, "A": 1, "B": 2, "C": 3}
    rows = sorted(best.values(),
                  key=lambda r: (order[r["tier"]], -r["overall"], r["start"]))
    return rows[:limit]


@app.route("/about")
def about_page():
    return render_template("about.html", local=LOCAL)


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html", local=LOCAL)


@app.route("/disclosure")
def disclosure_page():
    return render_template("disclosure.html", local=LOCAL)


@app.route("/contact")
def contact_page():
    return render_template("contact.html", local=LOCAL)


@app.route("/lake/<lake_id>")
def lake_page(lake_id):
    """One water: location, map, registry facts, the engine's next windows, nearby
    waters. Unique long-tail content ("<lake> fishing report"), cacheable."""
    lake = registry().get(lake_id)
    if not lake:
        abort(404)
    lake = dict(lake, id=lake_id, region=_region(lake))
    try:
        windows = _cached(f"lake:{lake_id}:ledger:v1",
                          lambda: _ledger(lake, 3, None, None, span=0, limit=4))
    except Exception:
        windows = []
    nearby = []
    by_name = {v.get("name"): k for k, v in registry().items()}
    for v in _nearest_lakes(lake, 3)[1:]:
        nid = v.get("id") or by_name.get(v.get("name"))
        if nid:
            nearby.append(dict(id=nid, name=v.get("name", nid), region=_region(v)))
    return render_template("lake.html", lake=lake, windows=windows, nearby=nearby, local=LOCAL)


@app.route("/lakes")
def lakes_page():
    """The registry, on a map. Client-side tiles only — one cacheable page."""
    lakes = lakes_summary()
    waters = [dict(id=l["id"], name=l["name"], region=l["region"],
                   lat=l["lat"], lng=l["lng"]) for l in lakes]
    return render_template("lakes.html", lakes=lakes,
                           waters_json=json.dumps(waters), local=LOCAL)


@app.route("/kb")
def kb_page():
    species = tx.normalize_species(request.args.get("species") or "bass")
    cats = []
    for c in tx.catalog(species):
        p = c["provenance"]
        cats.append(dict(
            id=c["id"], label=c["label"], aliases=c.get("aliases", []),
            style=c.get("style", ""), depth=c.get("depth", ""),
            light=", ".join(c["conditions"]["light"]),
            wind=", ".join(c["conditions"]["wind"]),
            tlo=c["conditions"]["water_temp_f"][0], thi=c["conditions"]["water_temp_f"][1],
            confidence=p.get("confidence", ""),
            source=p.get("source", ""), source_url=p.get("source_url"),
            verified_by=p.get("verified_by", "")))
    return render_template("kb.html", species=species, cats=cats,
                           baits=tx.load_baits().get("baits", []), local=LOCAL)


@app.route("/kb/<entry_id>")
def kb_entry_page(entry_id):
    """Canonical page for one KB entity — the citeable home for a rig/lure:
    conditions, the concrete build, substrate fits, every citation verbatim,
    disclosed offers, and same-purpose alternatives. Cross-species bait
    entities (kb/baits.json) get their own shape."""
    entry_id = re.sub(r"[^a-z0-9_-]", "", (entry_id or "").lower())[:40]
    c = tx.find_entry(entry_id)
    if not c:
        b = tx.bait_entry(entry_id)
        if not b:
            abort(404)
        return render_template(
            "kb_bait.html", b=b,
            citations=list(b.get("citations") or []),
            alternatives=[a for a in tx.alternatives(entry_id)
                          if a.get("id") != entry_id],
            offers_list=[o for o in offers.resolve(entry_id) if o.get("url")],
            components=offers.components(entry_id), local=LOCAL)
    spec = tx.rig_spec(entry_id)
    substrate = {b: v for b, v in
                 ((tx.load_substrate().get("entries") or {}).get(entry_id) or {}).items()
                 if isinstance(v, dict)}
    season = (tx.load_season().get("entries") or {}).get(entry_id) or {}
    spawn = (tx.load_spawn().get("entries") or {}).get(entry_id) or {}
    return render_template(
        "kb_entry.html", c=c, prov=c.get("provenance") or {},
        spec=spec, spec_line=tx.spec_line(spec),
        citations=list(c.get("citations") or []), substrate=substrate, season=season,
        spawn=spawn,
        presentation=tx.presentation_class(entry_id),
        alternatives=tx.alternatives(entry_id),
        offers_list=[o for o in offers.resolve(entry_id) if o.get("url")],
        components=offers.components(entry_id), local=LOCAL)


@app.route("/interview")
def interview_page():
    sugg: set[str] = set()
    for sp in ("bass", "trout", "catfish", "panfish"):
        for c in tx.catalog(sp):
            sugg.add(c["label"])
            for a in c.get("aliases", [])[:3]:
                if len(a) > 3:
                    sugg.add(a)
    line_types = tx.load_line().get("types", [])
    line_suggestions = sorted({t["label"] for t in line_types}
                              | {a for t in line_types for a in t.get("aliases", [])})
    bait_words = ("bait", "worm", "liver", "cricket", "minnow", "powerbait",
                  "salmon egg", "nightcrawler", "stink", "dough")
    baits: set[str] = set()
    for sp in ("bass", "trout", "catfish", "panfish"):
        for c in tx.catalog(sp):
            names = [c["label"]] + [a for a in c.get("aliases", []) if 3 < len(a) <= 60]
            if any(w in n.lower() for n in names for w in bait_words):
                baits.update(names[:4])
    rig_specs = []
    for sp in ("bass", "trout", "catfish", "panfish"):
        for c in tx.catalog(sp):
            spec = tx.rig_spec(c["id"])
            if not spec:
                continue
            rig_specs.append(dict(id=c["id"], species=sp, label=c["label"],
                                  aliases=c.get("aliases", []), parts=tx.spec_parts(spec)))
    return render_template("interview.html", lakes=lakes_summary(),
                           suggestions=sorted(sugg),
                           knot_suggestions=sorted({k["label"] for k in tx.load_knots().get("knots", [])}),
                           line_suggestions=line_suggestions,
                           bait_suggestions=sorted(baits),
                           rig_specs=rig_specs,
                           local=LOCAL)


@app.route("/review")
def review_page():
    if not LOCAL:
        abort(404)
    import review as rv
    graded, skipped = rv.collect()
    rows = []
    for g in graded:
        e = g["entry"]
        rows.append(dict(
            ts=g["ts"].strftime("%a %b %-d %-I:%M %p"), angler=e.get("angler", ""),
            skunk=g["skunk"], species=e.get("species") or "",
            n_fish=e.get("n_fish"), best_lb=e.get("best_lb"),
            total_lb=e.get("total_lb"), lure=e.get("primary_lure") or "",
            notes=(e.get("notes") or "")[:80],
            overall=g["overall"], pres=g["pres"], tim=g["tim"], zon=g["zon"],
            tim_d=g["tim_d"], state=g["state"], prime=(g["prime"]["start"]
                                                        if g["prime"] else None),
            picks=" + ".join(c["label"] for c, _, _ in g["picks"][:2])))
    catches = [g["overall"] for g in graded if not g["skunk"]]
    skunks = [g["overall"] for g in graded if g["skunk"]]
    sep = None
    if catches and skunks:
        sep = round(sum(catches) / len(catches) - sum(skunks) / len(skunks), 1)
    return render_template("review.html", rows=rows, skipped=skipped, sep=sep,
                           n_catch=len(catches), n_skunk=len(skunks),
                           pres_w=rv.weighted_presentation(graded),
                           catch_w=rv.weighted_catch_avg(graded),
                           local=LOCAL)


# ── JSON API (for the browser layer; robots-discouraged) ─────────────────────
@app.route("/sw.js")
def service_worker():
    """Serve the service worker from the ROOT path so its scope is the whole
    site (a copy under /static/ would only control /static/). no-cache so
    updates land immediately; the file itself is in web/static/sw.js."""
    sw = (ROOT / "web" / "static" / "sw.js").read_text()
    return Response(sw, mimetype="text/javascript",
                    headers={"Cache-Control": "no-cache",
                             "Service-Worker-Allowed": "/"})


def _clean_log_entry(f, lake_names: dict) -> dict | None:
    """Normalize a log entry from a form or an imported/exported dict. Accepts
    the form shape (registry lake key + date/time + skunk checkbox) and the
    field-queue shape (lake name + `ts` + `result`)."""
    def g(k, d=""):
        v = f.get(k)
        return d if v is None else v
    angler = str(g("angler")).strip()[:40] or "Angler"
    lake_raw = str(g("lake")).strip()[:80]
    lake = lake_names.get(lake_raw, lake_raw)
    result = str(g("result")).strip().lower()
    skunk = result == "skunk" or str(g("skunk")).strip().lower() in ("on", "1", "true", "yes")
    species = str(g("species")).strip()[:40]
    lure = str(g("lure")).strip()[:60]
    length = str(g("length")).strip()[:20]
    notes = str(g("notes")).strip()[:500]
    ts = str(g("ts")).strip()[:20]
    if ts:
        try:
            ts = datetime.fromisoformat(ts).isoformat(timespec="minutes")
        except ValueError:
            ts = ""
    if not ts:
        try:
            ts = datetime.strptime(f"{str(g('date')).strip()} {str(g('time')).strip()}",
                                   "%Y-%m-%d %H:%M").isoformat(timespec="minutes")
        except ValueError:
            ts = datetime.now().isoformat(timespec="minutes")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", length):
        length += "lb"
    if not (angler or lake):
        return None
    return dict(angler=angler, lake=lake,
                species=None if skunk else (species or "bass"),
                lure=None if skunk else lure,
                length="" if skunk else length,
                notes=notes, result="skunk" if skunk else "catch", ts=ts)


@app.route("/log", methods=["GET", "POST"])
def log_page():
    """Catch log. **LOCAL** writes `config/logbook.jsonl` directly (the same
    shape as `fishwitch log`). **Public/field mode** renders the same form but
    JS keeps entries in this browser and exports them for import on the home
    machine — the server never sees them."""
    import logbook as lb
    reg = registry()
    names = {k: v.get("name") for k, v in reg.items()}
    if request.method == "POST":
        if not LOCAL:
            abort(404)
        entry = _clean_log_entry(request.form, names)
        if entry is None:
            abort(400)
        lb.append(entry)
        q = urlencode(dict(ok="1", angler=entry["angler"], lake=request.form.get("lake", ""),
                           date=entry["ts"][:10], time=entry["ts"][11:16],
                           species=(entry["species"] or "bass"), lure=(entry["lure"] or "")))
        return redirect(f"/log?{q}")

    default_angler = ""
    try:
        default_angler = (json.loads((CONFIG / "profiles" / "default.json").read_text())
                          or {}).get("name", "")
    except Exception:
        pass
    date, time = request.args.get("date") or "", request.args.get("time") or ""
    at = (request.args.get("at") or "").strip()
    if at and not date:
        try:
            dt = datetime.strptime(at, "%Y-%m-%d %H:%M")
            date, time = dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        except ValueError:
            pass
    now = datetime.now()
    booked = lb.load() if LOCAL else []
    lures = sorted({c["label"] for sp in ("bass", "trout", "catfish", "panfish")
                    for c in tx.catalog(sp)})
    return render_template("log.html", local=LOCAL, lakes=lakes_summary(),
                           rows=list(reversed(booked[-8:])),
                           ok=request.args.get("ok"), imported=request.args.get("n"),
                           anglers=sorted({r.get("angler") for r in booked if r.get("angler")}),
                           default_angler=request.args.get("angler") or default_angler,
                           date=date or now.strftime("%Y-%m-%d"),
                           time=time or now.strftime("%H:%M"),
                           lake=request.args.get("lake") or "hidden-valley-lake-ca",
                           species=request.args.get("species") or "largemouth bass",
                           lure=request.args.get("lure") or "", lures=lures)


@app.route("/log/import", methods=["POST"])
def log_import():
    """LOCAL-only: merge a field-queue export (JSON array) into the ledger."""
    if not LOCAL:
        abort(404)
    import logbook as lb
    data = None
    f = request.files.get("file")
    if f is not None:
        try:
            data = json.loads(f.read().decode("utf-8", "replace"))
        except Exception:
            data = None
    if data is None:
        data = request.get_json(silent=True)
    if not isinstance(data, list):
        return redirect("/log?ok=import-error")
    names = {k: v.get("name") for k, v in registry().items()}
    n = 0
    for raw in data[:500]:
        if not isinstance(raw, dict):
            continue
        entry = _clean_log_entry(raw, names)
        if entry:
            lb.append(entry)
            n += 1
    return redirect(f"/log?ok=imported&n={n}")


@app.route("/stats")
def stats_page():
    if not LOCAL:
        abort(404)
    days = max(1, min(365, int(request.args.get("days") or 30)))
    s = telemetry.summarize(days=days)
    return render_template("stats.html", s=s, days=days, local=LOCAL)


@app.route("/styleguide")
def styleguide_page():
    """Local design-system reference: every component under each theme token
    set (loam / first-light / crisp-dark / almanac). Not shipped publicly."""
    if not LOCAL:
        abort(404)
    return render_template("styleguide.html", local=LOCAL, glyphs=glyphs.catalog())


@app.route("/logo")
def logo_page():
    """Local logo sketchpad: mark routes + wordmark studies, at real sizes and
    in both themes. Not shipped publicly."""
    if not LOCAL:
        abort(404)
    return render_template("logo.html", local=LOCAL)


# ── public API v1 (anonymous, read-only, attributed) ────────────────────────
@app.route("/embed/ledger")
def embed_ledger():
    """A minimal, iframe-able ledger for other sites — same cached horizon
    scan as /outlook, no account, absolute links back to baromoon."""
    import feeds
    lake = resolve_lake(request.args.get("lake"))
    if lake is None:
        abort(404)
    try:
        days = max(1, min(16, int(request.args.get("days") or 7)))
    except ValueError:
        days = 7
    species = (request.args.get("species") or "").strip()[:40] or None
    try:
        rows, _ = _cached(f"outlook:{lake['name']}:{days}:{species}",
                          lambda: _horizon(lake, days, species))
    except Exception:
        rows = []
    good = [r for r in rows if r["overall"] >= feeds.MIN_OVERALL]
    body = render_template("embed.html", lake=lake, days=days,
                           rows=good or rows[:3], strict=bool(good),
                           tier=feeds.tier, base="https://baromoon.com")
    return Response(body, mimetype="text/html",
                    headers={"Cache-Control": "public, max-age=900"})


@app.route("/api/v1/report")
def api_v1_report():
    """Public anonymous JSON report — the stable shape in public_api.py."""
    if not _rate_ok(f"v1report:{request.remote_addr}", 60):
        return jsonify(error="rate limit — 60 API reports/hour per visitor"), 429
    lake = resolve_lake(request.args.get("lake"))
    if lake is None:
        return jsonify(error="unknown lake", hint="see /lakes"), 404
    try:
        hours = min(8.0, max(0.5, float(request.args.get("hours") or 2.5)))
    except ValueError:
        hours = 2.5
    at = _clamp_at(request.args.get("at"))
    species = (request.args.get("species") or "").strip()[:40] or "bass"
    voice = request.args.get("voice")
    if voice not in ("fisher", "almanac", "astro"):
        voice = "fisher"
    bottom = request.args.get("bottom")
    if bottom not in ("grass", "muck", "sand", "rock", "wood"):
        bottom = None
    clarity = tx.normalize_clarity(request.args.get("clarity")) or None
    profile = dict(species=species, astro_display=voice, arsenal=[])
    wx = shared_weather(lake["lat"], lake["lng"])
    hist = shared_history(lake["lat"], lake["lng"], at)
    m = gen(profile, lake, at, hours=hours, species=species, voice=voice,
            wx=wx, hist=hist, bottom=bottom, clarity=clarity)
    body = public_api.report(m, lake.get("id"), lake, at, hours, voice, species, bottom,
                             clarity=clarity)
    r = jsonify(public_api.envelope(body))
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Cache-Control"] = "public, max-age=300"
    return r


@app.route("/api/v1/windows")
def api_v1_windows():
    """Public anonymous horizon scan (same cache as /outlook)."""
    if not _rate_ok(f"v1windows:{request.remote_addr}", 120):
        return jsonify(error="rate limit — 120 API scans/hour per visitor"), 429
    lake = resolve_lake(request.args.get("lake"))
    if lake is None:
        return jsonify(error="unknown lake", hint="see /lakes"), 404
    try:
        days = max(1, min(16, int(request.args.get("days") or 7)))
    except ValueError:
        days = 7
    species = (request.args.get("species") or "").strip()[:40] or None
    rows, moon = _cached(f"outlook:{lake['name']}:{days}:{species}",
                         lambda: _horizon(lake, days, species))
    body = public_api.windows(rows, moon, lake.get("id"))
    r = jsonify(public_api.envelope(body))
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Cache-Control"] = "public, max-age=900"
    return r


# ── JSON API (for the browser layer; robots-discouraged) ─────────────────────
@app.route("/api/outlook", methods=["POST"])
def api_outlook():
    """Personalized tier ledger: profile + optional lake → best upcoming
    windows across the home water and its 3 nearest registry neighbors."""
    if not _rate_ok(f"outlook:{request.remote_addr}", 20):
        return jsonify(error="rate limit — 20 ledger builds/hour"), 429
    payload = request.get_json(silent=True) or {}
    days = max(1, min(7, int(payload.get("days") or 5)))
    profile, errs = ({}, []) if not payload.get("profile") else _client_profile(payload)
    if errs:
        return jsonify(error="profile rejected", details=errs), 400
    home = resolve_lake(payload.get("lake") or profile.get("home_lake"))
    if home is None:
        return jsonify(error="unknown lake"), 400
    species = profile.get("species")
    import hashlib as _h
    ph = _h.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:10]
    try:
        rows = _cached(f"ledger:{home['name']}:{days}:{species}:{ph}",
                       lambda: _ledger(home, days, species, profile or None))
    except Exception as ex:
        return jsonify(error=f"ledger failed: {ex}"), 500
    out = []
    for r in rows:
        d = dict(r)  # never mutate the cached row objects
        s, e = d["start"], d["end"]
        d["start"] = s.strftime("%Y-%m-%d %H:%M")
        d["clock"] = f"{s:%-I:%M %p}–{e:%-I %p}"
        d["prime"] = d["prime"].strftime("%-I:%M %p") if d["prime"] else None
        out.append(d)
    return jsonify(rows=out, personalized=bool(profile))


@app.route("/api/report", methods=["POST"])
def api_report():
    if not _rate_ok(f"report:{request.remote_addr}", 30):
        return jsonify(error="rate limit — 30 reports/hour per visitor"), 429
    payload = request.get_json(silent=True) or {}
    out = _report_response(payload, anonymous=False)
    if "error" in out:
        return jsonify(out), 400
    return jsonify(out)


@app.route("/api/geocode", methods=["POST"])
def api_geocode():
    if not _rate_ok(f"geocode:{request.remote_addr}", 60):
        return jsonify(error="rate limit"), 429
    q = ((request.get_json(silent=True) or {}).get("q") or "").strip()
    if not q or len(q) > 120:
        return jsonify([])
    from fishwitch import geo
    cands = geo.geocode_city(q)[:5]
    return jsonify([dict(name=c.get("name"), region=c.get("region", ""),
                         country=c.get("country", ""), lat=c.get("lat"),
                         lng=c.get("lng"), tz=c.get("tz")) for c in cands])


@app.route("/robots.txt")
def robots():
    return ("User-agent: *\nDisallow: /api/\nAllow: /\n"
            "Sitemap: https://baromoon.com/sitemap.xml\n", 200,
            {"Content-Type": "text/plain"})


@app.route("/sitemap.xml")
def sitemap():
    base = "https://baromoon.com"
    urls = ["/", "/report", "/outlook", "/lakes", "/kb", "/interview",
            "/about", "/contact", "/privacy", "/disclosure"]
    urls += [f"/lake/{l['id']}" for l in lakes_summary()]
    urls += [f"/kb/{c['id']}" for sp in ("bass", "trout", "catfish", "panfish")
             for c in tx.catalog(sp)]
    urls += [f"/kb/{b['id']}" for b in tx.load_baits().get("baits", [])]
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f"<url><loc>{base}{u}</loc></url>" for u in urls]
    body.append("</urlset>")
    return Response("\n".join(body), mimetype="application/xml")


@app.route("/out/<entry>/<retailer>")
def out_click(entry, retailer):
    """Outbound link resolver + aggregate click counter. The destination is
    resolved server-side from kb/offers.json or the entry's manufacturer specs —
    never from a user-supplied URL — so this cannot be an open redirect. Logs
    only {ts, entry, retailer, kind, section}: no IP, no UA, no cookies."""
    retailer = re.sub(r"[^a-z0-9_-]", "", retailer.lower())[:24]
    src = re.sub(r"[^a-z0-9_-]", "", (request.args.get("src") or "").lower())[:16]
    entry = re.sub(r"[^a-z0-9_-]", "", entry.lower())[:40]
    comp = re.sub(r"[^a-z0-9_-]", "", (request.args.get("comp") or "").lower())[:32]
    target, kind = None, "manufacturer"
    if retailer == "manufacturer" and not comp:
        cat = tx.find_entry(entry)
        if cat:
            target = (cat.get("manufacturer_specs") or {}).get("product_url")
    else:
        if comp:
            pool = []
            for c in offers.components(entry):
                if c["id"] == comp:
                    pool = c.get("offers", [])
                    break
        else:
            pool = offers.resolve(entry)
        for o in pool:
            if o.get("retailer") == retailer and o.get("url"):
                target, kind = o["url"], o.get("kind", "offer")
                break
    if not target or not str(target).startswith("http"):
        abort(404)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            row = dict(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       entry=entry, retailer=retailer, kind=kind, src=src)
            if comp:
                row["comp"] = comp
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass
    return redirect(target, code=302)


@app.after_request
def resp_headers(resp):
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Anonymous, deterministic HTML renders — let browsers reuse them so the $6
    # droplet serves repeat views without re-rendering. /api is never cached.
    if (request.method == "GET" and resp.status_code == 200
            and not request.path.startswith(("/api/", "/static/"))):
        resp.headers.setdefault("Cache-Control",
                                "public, max-age=300, stale-while-revalidate=900")
    return resp


if __name__ == "__main__":
    host = os.environ.get("FISHWITCH_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("FISHWITCH_WEB_PORT", "7700"))
    print(f"\n  🎣 fishwitch web → http://{host}:{port}"
          + ("   (local mode: /review live)" if LOCAL else "") + "\n")
    app.run(host=host, port=port, debug=False)
