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
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))          # script-style imports (import logbook)
sys.path.insert(0, str(ROOT.parent))   # package imports (from fishwitch import geo)

import markdown as _md  # noqa: E402  (pip install markdown)
import offers  # noqa: E402
import tactics as tx  # noqa: E402
from layers.history import History  # noqa: E402
from report import generate as gen, to_markdown  # noqa: E402
from weather import Weather  # noqa: E402

LOCAL = os.environ.get("FISHWITCH_LOCAL", "") == "1"
CONFIG = ROOT / "config"

app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"),
            static_folder=str(ROOT / "web" / "static"))
app.config["JSON_SORT_KEYS"] = False


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
    return json.loads(p.read_text()) if p.exists() else {}


def lakes_summary() -> list[dict]:
    return [dict(id=k, name=v.get("name", k), region=v.get("region", ""))
            for k, v in registry().items()]


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


def _client_profile(payload: dict) -> dict:
    """Accept only the documented profile shape from the POST body. The dict
    is used in-memory by generate() and then discarded — never persisted."""
    p = payload.get("profile")
    if not isinstance(p, dict):
        return {}
    out = {k: p[k] for k in ("name", "species", "arsenal", "home_lake",
                             "astro_display") if k in p}
    b = p.get("birth")
    if isinstance(b, dict):
        out["birth"] = {k: b[k] for k in ("date", "time", "time_known",
                                          "place", "lat", "lng", "tz") if k in b}
    return out


def _render_report(profile: dict, lake: dict, at: datetime, hours: float,
                   voice: str | None, species: str | None) -> dict:
    wx = shared_weather(lake["lat"], lake["lng"])
    hist = None
    try:
        hist = History(lake["lat"], lake["lng"], at)
    except Exception:
        pass
    m = gen(profile, lake, at, hours=hours, species=species,
            voice=voice or profile.get("astro_display") or "almanac",
            wx=wx, hist=hist)
    body = _md.markdown(to_markdown(m), extensions=["tables"])
    rods = []
    for c in m["rods"]:
        mfg = (c.get("manufacturer_specs") or {})
        rod = dict(id=c["id"], label=c["label"],
                   verified=c["provenance"].get("confidence") == "verified"
                   or c["provenance"].get("confidence") == "sourced",
                   source=c["provenance"].get("source", "editorial consensus"),
                   source_url=c["provenance"].get("source_url"),
                   product=mfg.get("product_title"),
                   product_url=mfg.get("product_url"),
                   offers=offers.resolve(c["id"]))
        rods.append(rod)
    return dict(html=body, overall=m["scores"]["overall"],
                lake=lake["name"], at=at, rods=rods)


def _report_response(payload: dict, anonymous: bool) -> dict:
    lake = resolve_lake(payload.get("lake"))
    if lake is None:
        return dict(error="unknown lake")
    at = _clamp_at(payload.get("at"))
    hours = min(8.0, max(0.5, float(payload.get("hours") or 2.5)))
    voice = payload.get("voice")
    if voice not in ("fisher", "almanac", "astro"):
        voice = None
    species = (payload.get("species") or "").strip() or None
    profile = {} if anonymous else _client_profile(payload)

    def run():
        return _render_report(profile, lake, at, hours, voice, species)

    if anonymous:  # cacheable — no personal data involved
        key = "anon:" + json.dumps([str(payload.get("lake")), at.isoformat(),
                                    hours, voice, species], default=str)
        return _cached(key, run)
    return run()


# ── pages ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", lakes=lakes_summary(), local=LOCAL)


@app.route("/report")
def report_page():
    q = dict(lake=request.args.get("lake") or "",
             at=request.args.get("at") or "",
             hours=request.args.get("hours") or "2.5",
             voice=request.args.get("voice") or "",
             species=request.args.get("species") or "")
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


def _horizon(lake: dict, days: int, species: str | None):
    profile = dict(species=species or "bass", astro_display="almanac",
                   arsenal=[])
    wx = shared_weather(lake["lat"], lake["lng"], days=days)
    hist = None
    try:
        hist = History(lake["lat"], lake["lng"], datetime.now())
    except Exception:
        pass
    from skycalc import Sky
    sky = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)
    results = []
    today = datetime.now().replace(hour=0, minute=0)
    for d in range(1, days + 1):
        day = today + timedelta(days=d)
        for h in (5, 9, 12, 15, 17, 20):
            start = day.replace(hour=h, minute=30 if h == 17 else 0)
            try:
                m = gen(profile, lake, start, hours=2.0,
                        species=species, voice="fisher", wx=wx, hist=hist)
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
        moon.append((dd.date().isoformat(), ms["phase"], round(ms["illum"])))
    return results[:10], moon


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
    return render_template("kb.html", species=species, cats=cats, local=LOCAL)


@app.route("/interview")
def interview_page():
    return render_template("interview.html", lakes=lakes_summary(), local=LOCAL)


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
                           local=LOCAL)


# ── JSON API (for the browser layer; robots-discouraged) ─────────────────────
@app.route("/api/report", methods=["POST"])
def api_report():
    payload = request.get_json(silent=True) or {}
    out = _report_response(payload, anonymous=False)
    if "error" in out:
        return jsonify(out), 400
    return jsonify(out)


@app.route("/api/geocode", methods=["POST"])
def api_geocode():
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
    return "User-agent: *\nDisallow: /api/\nAllow: /\n", 200, {"Content-Type": "text/plain"}


@app.after_request
def resp_headers(resp):
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


if __name__ == "__main__":
    host = os.environ.get("FISHWITCH_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("FISHWITCH_WEB_PORT", "7700"))
    print(f"\n  🎣 fishwitch web → http://{host}:{port}"
          + ("   (local mode: /review live)" if LOCAL else "") + "\n")
    app.run(host=host, port=port, debug=False)
