#!/usr/bin/env python3
"""fishwitch — the fishing report apparatus (MVP CLI).

  interview          answer questions, save an angler profile
  report             generate a layered fishing report
  lakes              list water bodies in the local registry
  arsenal            list known lure/rig categories per species

Examples:
  ./fishwitch interview
  ./fishwitch report
  ./fishwitch report --at "2026-09-10 18:00" --hours 3
  ./fishwitch report --lake "Clear Lake, CA" --species bass \
      --arsenal "drop shot, senko, chatterbait, squarebill" \
      --birth "1988-01-18 17:35" --place "Santa Rosa, CA, US"
"""
from __future__ import annotations
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fishwitch import geo, tactics as tx
from fishwitch.report import generate, to_markdown, save

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
PROFILES = CONFIG / "profiles"
REMOTE_DIR = "/srv/fishwitch"


def _baromoon_host() -> str:
    """Production ssh target: $BAROMOON_HOST, else root@deploy/host.txt (as deploy.sh)."""
    host = os.environ.get("BAROMOON_HOST", "").strip()
    if not host:
        f = ROOT / "deploy" / "host.txt"
        ip = f.read_text().strip() if f.exists() else ""
        if ip:
            host = f"root@{ip}"
    if not host:
        sys.exit("  no remote host set — use BAROMOON_HOST or deploy/host.txt")
    return host


def _remote_lines(path: str) -> list[str]:
    """Read an aggregate log file from production over ssh (read-only)."""
    host = _baromoon_host()
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             host, f"cat {shlex.quote(path)}"],
            capture_output=True, text=True, timeout=60)
    except Exception as e:
        sys.exit(f"  remote read failed ({host}): {e}")
    if p.returncode != 0:
        sys.exit(f"  remote read failed ({host}): {(p.stderr or '').strip()[:200]}")
    return p.stdout.splitlines()


def _jsonl(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        try:
            r = json.loads(line)
            if isinstance(r, dict):
                rows.append(r)
        except Exception:
            pass
    return rows


def load_json(p: Path, default=None):
    if p.exists():
        return json.loads(p.read_text())
    return default


def resolve_lake(name: str) -> dict | None:
    """Registry id/name first, then Nominatim, else None."""
    lakes = load_json(CONFIG / "lakes.json", {})
    for key, lk in lakes.items():
        if key.lower() == name.strip().lower() or lk["name"].lower() == name.strip().lower():
            lk = dict(lk); lk["id"] = key
            return lk
    # partial registry match
    for key, lk in lakes.items():
        if name.strip().lower() in lk["name"].lower():
            lk = dict(lk); lk["id"] = key
            return lk
    cands = geo.geocode_waterbody(name)
    if not cands:
        return None
    c = cands[0]
    tz, _ = geo.tz_for(c["lat"], c["lng"])
    return dict(name=c["name"], region=c["display"].split(",")[1].strip() if "," in c["display"] else "",
                lat=c["lat"], lng=c["lng"], alt_m=300, tz=tz, type=c.get("type", "water"),
                structure=[], lore=[], geocoded=True)


# ── interview ───────────────────────────────────────────────────────────────
def ask(prompt: str, default: str | None = None) -> str:
    suf = f" [{default}]" if default else ""
    v = input(f"{prompt}{suf}: ").strip()
    return v or (default or "")


def pick_from(opts: list[dict], what: str) -> dict | None:
    if not opts:
        return None
    if len(opts) == 1:
        print(f"  {what}: found {opts[0].get('name', opts[0].get('display', '?'))}")
        return opts[0]
    for i, o in enumerate(opts[:5], 1):
        label = o.get("display") or f"{o.get('name')} · {o.get('region','')} · {o.get('country','')}"
        print(f"  {i}) {label}")
    while True:
        c = ask(f"pick {what} (1-{min(5, len(opts))})", "1")
        if c.isdigit() and 1 <= int(c) <= min(5, len(opts)):
            return opts[int(c) - 1]
        if c == "":
            return opts[0]


def interview(profile_path: Path):
    print("═" * 60)
    print("  FISHWITCH INTERVIEW — the questions the UI will ask someday")
    print("═" * 60)
    name = ask("angler name", "friend")
    bdate = ask("birth date (YYYY-MM-DD)")
    while not (len(bdate) == 10 and bdate[4] == "-" and bdate[7] == "-"):
        bdate = ask("  birth date again, format YYYY-MM-DD")
    btime = ask("birth time (HH:MM, 24h — or 'unknown')")
    time_known = btime.lower() not in ("unknown", "u", "?", "")
    if not time_known:
        btime = "12:00"
        print("  (noon used as stand-in; houses/Asc hidden in the report)")
    bplace = ask("birth place (city, state, country)")
    cand = pick_from(geo.geocode_city(bplace), "birth place") if bplace else None
    if not cand:
        lat_s = ask("  no geocode — enter latitude"); lng_s = ask("  longitude")
        cand = dict(lat=float(lat_s or 0), lng=float(lng_s or 0), tz="UTC", name=bplace)
    species = ask("species you're usually after", "largemouth bass")
    arsenal = [s.strip() for s in ask("your lures/rigs (comma-separated)",
                                      "drop shot, wacky senko, chatterbait, squarebill, walking bait, jig").split(",") if s.strip()]
    baits = [s.strip() for s in ask("baits you use (live/cut/prepared, comma-separated — blank if artificials-only)",
                                    "").split(",") if s.strip()]
    line = [s.strip() for s in ask("line you spool (comma-separated: fluorocarbon, braid, monofilament, copolymer)",
                                   "fluorocarbon").split(",") if s.strip()]
    voice = ask("sky layer presentation: fisher / almanac / astro", "almanac").lower()
    if voice not in ("fisher", "almanac", "astro"):
        voice = "almanac"
    lake_name = ask("home water (name + state, or registry id)", "hidden-valley-lake-ca")
    profile = dict(
        name=name,
        birth=dict(date=bdate, time=btime, time_known=time_known,
                   place=bplace, lat=cand["lat"], lng=cand["lng"],
                   tz=cand.get("tz", "UTC")),
        species=species, arsenal=arsenal, baits=baits, line=line, home_lake=lake_name,
        astro_display=voice,
        created=datetime.now().isoformat(timespec="seconds"),
    )
    PROFILES.mkdir(parents=True, exist_ok=True)
    out = profile_path or (PROFILES / f"{name.lower().replace(' ', '-')}.json")
    out.write_text(json.dumps(profile, indent=2))
    print(f"\n✅ saved {out}\n   generate with: ./fishwitch report --profile {out}")
    return out


# ── report ─────────────────────────────────────────────────────────────────
def cmd_report(args):
    profile = load_json(Path(args.profile)) if args.profile else None
    if profile is None:
        if args.birth is None:
            sys.exit("no profile found — run `./fishwitch interview`, or pass --birth/--place/--arsenal")
        # full flag-mode: everything from the command line
        lat = lng = None; tz = "UTC"
        if args.place:
            c = pick_from(geo.geocode_city(args.place), "birth place")
            if c:
                lat, lng, tz = c["lat"], c["lng"], c["tz"]
        bd, bt = args.birth.split()
        profile = dict(name=args.name or "Angler",
                       birth=dict(date=bd, time=bt, time_known=True,
                                  place=args.place or "?", lat=lat or 0, lng=lng or 0, tz=tz),
                       species=args.species or "bass",
                       arsenal=[s.strip() for s in (args.arsenal or "chatterbait, squarebill, drop shot, senko, jig").split(",") if s.strip()])
    if args.arsenal:
        profile["arsenal"] = [s.strip() for s in args.arsenal.split(",") if s.strip()]
    if args.baits:
        profile["baits"] = [s.strip() for s in args.baits.split(",") if s.strip()]
    if args.line:
        profile["line"] = [s.strip() for s in args.line.split(",") if s.strip()]
    if args.species:
        profile["species"] = args.species

    # birth override on an existing profile
    if args.birth and profile.get("birth") is None:
        pass

    lake_name = args.lake or profile.get("home_lake") or "hidden-valley-lake-ca"
    lake = resolve_lake(lake_name)
    if lake is None:
        sys.exit(f"could not find water body '{lake_name}' — add it to config/lakes.json or pass --lat/--lng")
    if args.lat and args.lng:
        lake["lat"], lake["lng"] = float(args.lat), float(args.lng)
    if args.turnover:
        lake.setdefault("state", {})["turned_over"] = args.turnover
        # persist to registry so future reports remember the lake's state
        reg = load_json(CONFIG / "lakes.json", {})
        if lake.get("id") in reg:
            reg[lake["id"]].setdefault("state", {})["turned_over"] = args.turnover
            (CONFIG / "lakes.json").write_text(json.dumps(reg, indent=2))
            print(f"🌊 lake state saved: {lake['name']} turned over {args.turnover}", file=sys.stderr)

    at = datetime.strptime(args.at, "%Y-%m-%d %H:%M") if args.at else None
    if at is None:
        now = datetime.now()
        at = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if now.hour >= 20:
            at += __import__("datetime").timedelta(days=1)
    hours = float(args.hours)
    if args.until:
        # the angler's real constraint — e.g. off the water at 20:00
        if len(args.until) <= 5:
            end_t = datetime.strptime(args.until, "%H:%M").replace(
                year=at.year, month=at.month, day=at.day)
            if end_t <= at:
                end_t += __import__("datetime").timedelta(days=1)
        else:
            end_t = datetime.strptime(args.until, "%Y-%m-%d %H:%M")
        hours = max(0.5, (end_t - at).total_seconds() / 3600)

    model = generate(profile, lake, at, hours=hours,
                     species=args.species or profile.get("species"),
                     voice=args.voice or profile.get("astro_display"),
                     bottom=args.bottom, clarity=args.clarity)
    md = to_markdown(model)
    print(md)
    p = save(model, md)
    print(f"\n📝 saved: {p}", file=sys.stderr)
    if args.gpx:
        export_gpx_from_model(model, args.gpx, args.lat, args.lng)


def export_gpx_from_model(model, out, lat=None, lng=None):
    """Prime-window waypoints loadable on any chartplotter."""
    from adapters import gpx
    lake = model["lake"]
    la = float(lat) if lat else lake["lat"]
    lo = float(lng) if lng else lake["lng"]
    wpts = [dict(name=f"launch {_fmt(model['start'])}", lat=la, lng=lo,
                 desc="fishwitch session start", sym="Anchor")]
    if model["prime"]:
        wpts.append(dict(name=f"prime {_fmt(model['prime']['start'])}", lat=la, lng=lo,
                         desc="; ".join(c["label"] for c, _, _ in model["prime"]["picks"]),
                         sym="Fish"))
    for e in model["solunar"]:
        if e["end"] >= model["start"] and e["start"] <= model["end"]:
            wpts.append(dict(name=f"{e['label'].split()[0]} {_fmt(e['peak'])}", lat=la, lng=lo,
                             desc=e["label"], sym="Fish"))
    gpx.export_gpx(out, wpts)
    print(f"🗺  GPX saved: {out} ({len(wpts)} waypoints)", file=sys.stderr)


def _access_window(sky, day, lake):
    return sky.access_window(day, lake.get("access"))


def _bound_dt(sky, day, name: str, after):
    """Named day boundary -> datetime. If it's already past `after`, resolve
    to its next occurrence (e.g. dawn of the following day)."""
    from datetime import timedelta
    ev = sky.sun_events_for_day(day)
    table = {'civil-dawn': ev['civil_dawn'], 'dawn': ev['civil_dawn'],
             'sunrise': ev['sunrise'],
             'noon': ev['sunrise'] + (ev['sunset'] - ev['sunrise']) / 2,
             'sunset': ev['sunset'], 'civil-dusk': ev['civil_dusk'], 'dusk': ev['civil_dusk']}
    if name in table:
        t = table[name]
        if t <= after:
            return _bound_dt(sky, day + timedelta(days=1), name, after)
        return t
    hh, mm = map(int, name.split(':'))
    t = day.replace(hour=hh, minute=mm)
    return t + timedelta(days=1) if t <= after else t


def _candidate_starts(t_from, t_to, window_h: float, step_min: int = 60):
    from datetime import timedelta
    starts, t = [], t_from
    while t + timedelta(hours=window_h) <= t_to:
        starts.append(t)
        t += timedelta(minutes=step_min)
    return starts or [t_from]


def _session_bounds(args, sky, day, window_h: float):
    """Resolve --from/--to/--daylight/--dark into (from_dt, to_dt)."""
    from datetime import timedelta
    day = day.replace(hour=0, minute=0)
    if getattr(args, 'daylight', False):
        f, t = _bound_dt(sky, day, 'civil-dawn', day), _bound_dt(sky, day, 'civil-dusk', day)
    elif getattr(args, 'dark', False):
        f = _bound_dt(sky, day, 'civil-dusk', day)
        t = _bound_dt(sky, day, 'civil-dawn', f)  # next morning's dawn
    else:
        f = _bound_dt(sky, day, args.time_from, day) if getattr(args, 'time_from', None) else day.replace(hour=4)
        t = _bound_dt(sky, day, args.time_to, f) if getattr(args, 'time_to', None) else day.replace(hour=22)
    return f, min(t, f + timedelta(hours=20))


def cmd_best(args):
    """Scan a whole day: score every candidate window, rank, de-overlap."""
    from datetime import timedelta
    from weather import Weather
    from skycalc import Sky
    from layers.history import History
    from report import generate as gen

    profile = load_json(Path(args.profile)) or {}
    lake = resolve_lake(args.lake or profile.get("home_lake") or "hidden-valley-lake-ca")
    if lake is None:
        sys.exit("lake not found")
    day = datetime.strptime(args.date, "%Y-%m-%d") if args.date else \
        (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0)
    win = float(args.window)

    print(f"\n🌅 DAY SCAN — {day.strftime('%A %b %-d')} · {lake['name']}")

    wx = Weather(lake["lat"], lake["lng"])   # one fetch, reused
    hist = None
    try:
        hist = History(lake["lat"], lake["lng"], day)
    except Exception:
        pass

    results = []
    sky_shared = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)
    t_from, t_to = _session_bounds(args, sky_shared, day, win)
    if getattr(args, 'enforce_access', False):
        acc = _access_window(sky_shared, day, lake)
        if acc:
            ao, ac, note = acc
            t_from, t_to = max(t_from, ao), min(t_to, ac)
            print(f"  🚤 lake hours ({note}): on the water {ao:%-I:%M %p}–{ac:%-I:%M %p}")
    for start in _candidate_starts(t_from, t_to, win):
        try:
            m = gen(profile, lake, start, hours=win,
                    species=args.species or profile.get("species"),
                    wx=wx, hist=hist)
        except Exception:
            continue
        if not m["blocks"]:
            continue
        prime = m["prime"]
        results.append(dict(
            start=start, end=start + timedelta(hours=win),
            overall=m["scores"]["overall"], ps=m.get("prime_score") or 0,
            prime_t=prime["start"] if prime else None,
            prime_lab=(prime["light"] if prime else ""),
            prime_ev="; ".join(prime["events"][:2]) if prime else "",
            picks=[c["label"] for c, _, _ in prime["picks"]][:2] if prime else [],
            solunar=next((f"{e['label'].split()[0]} {e['peak']:%-I:%M %p}"
                          for e in m["solunar"]
                          if e["end"] >= start and e["start"] <= start + timedelta(hours=win)), ""),
        ))
    if not results:
        sys.exit("no scorable windows — outside forecast range (±3 days)?")

    results.sort(key=lambda r: (-r["overall"], -r["ps"]))
    picked = []
    for r in results:
        if all(r["end"] <= p["start"] or r["start"] >= p["end"] for p in picked):
            picked.append(r)
        if len(picked) == 3:
            break
    moment = max(results, key=lambda r: r["ps"])

    for i, r in enumerate(picked, 1):
        medal = "🥇🥈🥉"[i - 1]
        print(f"\n  {medal} {r['start']:%-I:%M %p}–{r['end']:%-I:%M %p}  "
              f"({r['prime_lab']}) · overall {r['overall']}/10")
        if r["prime_t"]:
            print(f"     prime moment ~{r['prime_t']:%-I:%M %p}"
                  + (f" · {r['solunar']}" if r["solunar"] else ""))
        if r["prime_ev"]:
            print(f"     sky events: {r['prime_ev']}")
        if r["picks"]:
            print(f"     approach: {' + '.join(r['picks'])}")

    if moment["prime_t"]:
        print(f"\n  ⚡ Moment of the day: {moment['prime_t']:%-I:%M %p} "
              f"(window {moment['start']:%-I %p}–{moment['end']:%-I %p}, score {moment['overall']}/10)")
    print()


def cmd_outlook(args):
    """Rank days+windows across an N-day horizon (16-day free weather cap)."""
    from datetime import timedelta, date as _date
    from weather import Weather
    from layers.history import History
    from skycalc import Sky, phase_name
    from report import generate as gen

    profile = load_json(Path(args.profile)) or {}
    lake = resolve_lake(args.lake or profile.get("home_lake") or "hidden-valley-lake-ca")
    if lake is None:
        sys.exit("lake not found")
    today = datetime.now().replace(hour=0, minute=0)
    n_days = min(int(args.days), 16)

    print(f"\n📅 {n_days}-DAY OUTLOOK — {profile.get('name', 'you')} @ {lake['name']}")
    wx = Weather(lake["lat"], lake["lng"], forecast_days=n_days)
    hist = None
    try:
        hist = History(lake["lat"], lake["lng"], today)
    except Exception:
        pass
    sky = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)

    results, moon_by_day = [], {}
    for d in range(1, n_days + 1):
        day = today + timedelta(days=d)
        ms = sky.moon_state(sky.jd(day.replace(hour=12)))
        moon_by_day[day.date()] = (ms["phase"], ms["illum"])
        t_from, t_to = _session_bounds(args, sky, day, 2.0)
        starts = _candidate_starts(t_from, t_to, 2.0) \
            if (getattr(args, 'daylight', False) or getattr(args, 'dark', False)
                or getattr(args, 'time_from', None) or getattr(args, 'time_to', None)) \
            else [day.replace(hour=h, minute=30 if h == 17 else 0) for h in (5, 9, 12, 15, 17, 20)]
        if getattr(args, 'enforce_access', False):
            acc = _access_window(sky, day, lake)
            if acc:
                starts = [s for s in starts
                          if acc[0] <= s and s + timedelta(hours=2) <= acc[1]]
        for start in starts:
            try:
                m = gen(profile, lake, start, hours=2.0,
                        species=args.species or profile.get("species"), wx=wx, hist=hist)
            except Exception:
                continue
            if not m["blocks"]:
                continue
            prime = m["prime"]
            conf = "high" if d <= 3 else ("med" if d <= 7 else "low")
            results.append(dict(
                day=day.date(), start=start, end=start + timedelta(hours=2),
                overall=m["scores"]["overall"], ps=m.get("prime_score") or 0,
                prime_t=prime["start"] if prime else None,
                prime_ev="; ".join(prime["events"][:2]) if prime else "",
                picks=[c["label"] for c, _, _ in prime["picks"]][:2] if prime else [],
                solunar=next((f"{e['label'].split()[0]} {e['peak']:%-I:%M %p}"
                              for e in m["solunar"]
                              if e["end"] >= start and e["start"] <= start + timedelta(hours=2)), ""),
                conf=conf, state=m.get("lake_state") or ""))
    if not results:
        sys.exit("no scorable windows in range")

    results.sort(key=lambda r: (-r["overall"], -r["ps"]))
    print("\n  TOP SESSIONS OF THE HORIZON")
    for i, r in enumerate(results[:8], 1):
        print(f"  {i}) {r['day']:%a %b %-d} · {r['start']:%-I:%M %p}–{r['end']:%-I %p} · "
              f"{r['overall']}/10 ({r['conf']} confidence)")
        if r["prime_t"]:
            print(f"      prime ~{r['prime_t']:%-I:%M %p}"
                  + (f" · {r['solunar']}" if r["solunar"] else ""))
        if r["prime_ev"]:
            print(f"      {r['prime_ev']}")
        if r["picks"]:
            print(f"      approach: {' + '.join(r['picks'])}")

    print("\n  BEST WINDOW PER DAY")
    seen = set()
    for r in results:
        if r["day"] in seen:
            continue
        seen.add(r["day"])
        ph, il = moon_by_day[r["day"]]
        print(f"  {r['day']:%a %b %-d}  {r['start']:%-I %p}–{r['end']:%-I %p}  {r['overall']}/10 "
              f"· {ph} ({il:.0f}%)")

    # lunar peaks beyond/outside weather horizon
    print("\n  LUNAR CALENDAR (solunar peaks: new & full moons ±3 days)")
    for dd, (ph, il) in sorted(moon_by_day.items()):
        if "New" in ph or "Full" in ph or il < 8 or il > 92:
            print(f"  {dd:%a %b %-d} — {ph} ({il:.0f}%)")
    print("\n  (weather confidence: ≤3d high · 4-7d med · 8+d low; "
          "astro/solunar timing holds at all ranges)\n")


def cmd_days(args):
    """Day lens: pressure phase + lunar forcing per day — the recipe explorer.
    Born from the 2026-09-13/14 A/B (see STATE.md ledger): every good session
    fell 40h+ after a pressure minimum on a rising barometer; the dead day was
    fished descending INTO the trough. Exploratory navigator — does NOT feed
    report scoring (that gate stays with `review` calibration)."""
    from datetime import timedelta
    import math
    import swisseph as swe
    from weather import Weather
    from skycalc import Sky, planet_lon

    profile = load_json(Path(PROFILES / "default.json")) or {}
    lake = resolve_lake(args.lake or profile.get("home_lake") or "hidden-valley-lake-ca")
    if lake is None:
        sys.exit("lake not found")
    n = max(1, min(int(args.days), 16))
    wx = Weather(lake["lat"], lake["lng"], forecast_days=n + 2, past_days=3)
    sky = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)

    def w(at):
        return min(wx.hourly, key=lambda x: abs((x["dt"] - at).total_seconds()))

    print(f"\n🌡 DAY LENS — {lake['name']} · next {n} days (pressure phase + lunar forcing)")
    print("  recipe (ledger 2026-09-14, n=1 epic — hypothesis): trough ≥36h past · "
          "Δ24h ≥ +1.5 · illum <15% · major near session")
    for d in range(n):
        at = (datetime.now() + timedelta(days=d)).replace(hour=15, minute=0)
        x = w(at)
        d24 = x["press"] - w(at - timedelta(hours=24))["press"]
        win = wx.series(at - timedelta(hours=48), at + timedelta(hours=12))
        if win:
            pmin = min(win, key=lambda h: h["press"])
            hrs = (at - pmin["dt"]).total_seconds() / 3600
            pmin_s = f"{pmin['dt']:%a %-I %p}@{pmin['press']:.0f} ({hrs:+.0f}h)"
        else:
            pmin_s, hrs = "?", 0
        jd = sky.jd(at)
        (mlon, _mla, dist, *_), _ = swe.calc_ut(jd, swe.MOON, swe.FLG_SWIEPH)
        slon, _ = planet_lon(jd, "Sun")
        elong = ((mlon - slon + 180) % 360) - 180
        illum = (1 - math.cos(math.radians(elong))) / 2 * 100
        tr = [t for t in sky.moon_transits(at) if abs((t[0] - at).total_seconds()) < 20 * 3600]
        tr_up = max(tr, key=lambda t: t[1]) if tr else (None, 0)
        major_s = f"{tr_up[0]:%-I:%M %p} @ {tr_up[1]:.0f}°" if tr_up[0] else "—"
        hits = sum([hrs >= 36, d24 >= 1.5, illum < 15,
                    bool(tr_up[0]) and abs((tr_up[0] - at).total_seconds()) < 3 * 3600])
        stars = "●" * hits + "○" * (4 - hits)
        print(f"  {at:%a %b %-d}  press {x['press']:.0f} (Δ24h {d24:+.1f}) · trough {pmin_s}"
              f" · moon {illum:3.0f}% dist {dist*149597870.7:6.0f} km · major {major_s}"
              f"  {stars} {hits}/4")
    print()


def _fmt(dt):
    return dt.strftime("%H%M")


def cmd_log(args):
    import logbook as lb
    profile = load_json(Path(PROFILES / "default.json")) or {}
    angler = args.angler or profile.get("name", "Angler")
    lake = args.lake or profile.get("home_lake", "")
    if lake and lake in load_json(CONFIG / "lakes.json", {}):
        lake = load_json(CONFIG / "lakes.json", {})[lake]["name"]
    entry = dict(angler=angler, lake=lake,
                 species=(None if args.skunk else (args.species or "bass")),
                 lure=(None if args.skunk else (args.lure or "")),
                 length=args.length or "",
                 notes=args.notes or "",
                 result=("skunk" if args.skunk else "catch"))
    if args.time:
        entry["ts"] = args.time
    if args.lat:
        entry["lat"], entry["lng"] = float(args.lat), float(args.lng)
    lb.append(entry)
    print(f"✅ logged: {angler} — " + ("skunk (effort counts too)" if args.skunk
          else f"{entry['species']}" + (f" on {entry['lure']}" if entry["lure"] else "")))
    s = lb.summary_for(lake, angler)
    if s:
        print(f"   {angler}'s logbook at this lake: {s['n']} catches" +
              (f", best producer {s['best_lure']} ({s['best_lure_n']})" if s["best_lure"] else ""))


def _add_time_filters(p):
    p.add_argument("--from", dest="time_from", metavar="BOUND",
                   help="civil-dawn|sunrise|noon|sunset|civil-dusk|HH:MM")
    p.add_argument("--to", dest="time_to", metavar="BOUND",
                   help="civil-dawn|sunrise|noon|sunset|civil-dusk|HH:MM")
    p.add_argument("--daylight", action="store_true",
                   help="civil-dawn → civil-dusk (twilight-to-twilight daylight)")
    p.add_argument("--dark", action="store_true",
                   help="civil-dusk → next civil-dawn (night sessions)")
    p.add_argument("--enforce-access", action="store_true",
                   help="clamp scans to lake access-hour rules (registry 'access')")


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="fishwitch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("interview", help="Q&A → save an angler profile") \
        .add_argument("--out", default=None, help="profile json path")

    rp = sub.add_parser("report", help="generate a fishing report")
    rp.add_argument("--profile", default=str(PROFILES / "default.json"),
                    help="angler profile json (default config/profiles/default.json)")
    rp.add_argument("--lake", help="registry id/name or geocodable water body")
    rp.add_argument("--at", help="session start 'YYYY-MM-DD HH:MM' (lake local tz, default today 18:00)")
    rp.add_argument("--hours", default="2.5", help="session length in hours (default 2.5)")
    rp.add_argument("--until", help="hard off-water time 'HH:MM' or 'YYYY-MM-DD HH:MM' — overrides --hours")
    rp.add_argument("--species", help="e.g. largemouth bass, trout, catfish, panfish")
    rp.add_argument("--arsenal", help="comma-separated lures/rigs you own")
    rp.add_argument("--baits", help="comma-separated live/cut/prepared baits you use")
    rp.add_argument("--line", help="comma-separated line types you spool (fluorocarbon, braid, …)")
    rp.add_argument("--birth", help="flag-mode: 'YYYY-MM-DD HH:MM'")
    rp.add_argument("--place", help="flag-mode birthplace 'City, State, Country'")
    rp.add_argument("--name", help="angler name (flag-mode)")
    rp.add_argument("--lat"); rp.add_argument("--lng", help="manual lake coordinates override")
    rp.add_argument("--turnover", help="'YYYY-MM-DD' — lake turnover date; persists to registry")
    rp.add_argument("--voice", choices=["fisher", "almanac", "astro"],
                    help="sky-layer presentation (default: profile setting, else astro)")
    rp.add_argument("--bottom", choices=["grass", "muck", "sand", "rock", "wood"],
                    help="bottom you're fishing — applies substrate presentation fit")
    rp.add_argument("--clarity", choices=["clear", "stained"],
                    help="declared water clarity — color vs contrast selection")
    rp.add_argument("--gpx", help="also export prime-window waypoints to this GPX path")

    bp = sub.add_parser("best", help="scan a day for optimal fishing windows")
    bp.add_argument("--date", help="YYYY-MM-DD (default tomorrow)")
    bp.add_argument("--lake")
    bp.add_argument("--profile", default=str(PROFILES / "default.json"))
    bp.add_argument("--window", default="2", help="candidate session length in hours")
    bp.add_argument("--species")
    _add_time_filters(bp)

    op = sub.add_parser("outlook", help="rank best days/windows over the next N days")
    op.add_argument("--days", default="16", help="horizon in days (max 16 with free weather)")
    op.add_argument("--lake")
    op.add_argument("--profile", default=str(PROFILES / "default.json"))
    op.add_argument("--species")
    _add_time_filters(op)

    lg = sub.add_parser("log", help="log a catch (feeds the report feedback loop)")
    lg.add_argument("--angler", help="who caught it (default: default profile's name)")
    lg.add_argument("--lake", help="lake name (default home lake)")
    lg.add_argument("--species", default="bass")
    lg.add_argument("--lure", help="what it ate")
    lg.add_argument("--skunk", action="store_true", help="log a fishless effort session")
    lg.add_argument("--length", help="length/weight if measured")
    lg.add_argument("--time", help="'YYYY-MM-DD HH:MM' (default now)")
    lg.add_argument("--lat"); lg.add_argument("--lng"); lg.add_argument("--notes")

    dl = sub.add_parser("days", help="pressure-phase + lunar-forcing day lens (exploratory)")
    dl.add_argument("--days", default="10")
    dl.add_argument("--lake")

    rv = sub.add_parser("review", help="replay logged trips vs what the model said — calibration")
    rv.add_argument("--angler", help="grade one angler’s sessions")
    rv.add_argument("--since", help="YYYY-MM-DD")
    rv.add_argument("--lake")
    rv.add_argument("--hours", default="2", help="replay window centered on each stamp (default 2)")
    rv.add_argument("--species", help="override species (default: entry/profile)")

    lp = sub.add_parser("lakes", help="list registry / auto-characterize a new lake")
    lp.add_argument("--auto", metavar="NAME", help="build a lake card from public data and cache it")
    ap_ = sub.add_parser("arsenal", help="list lure/rig categories")
    ap_.add_argument("--species", default="bass")

    kb_ = sub.add_parser("kb", help="query the cited lure/rig knowledge base")
    kb_.add_argument("--species", default="bass")
    kb_.add_argument("--show", help="entry id — full record incl. provenance")
    kb_.add_argument("--conditions", help="filter tokens e.g. 'dusk chop 70f'")

    ki = sub.add_parser("kb-ingest", help="fetch manufacturer specs into kb/pending (deterministic)")
    ki.add_argument("--species", default="bass")
    ki.add_argument("--entry", help="single entry id (default: all with live sources)")
    ki.add_argument("--refresh", action="store_true", help="re-ingest entries already sourced")

    kr = sub.add_parser("kb-review", help="list pending ingestion drafts")
    kj = sub.add_parser("kb-reject", help="reject a pending draft — logged, draft deleted")
    kj.add_argument("--species", default="bass", required=True)
    kj.add_argument("--entry", required=True)
    kj.add_argument("--by", default="human reviewer")
    kj.add_argument("--reason", help="why (matched wrong product, etc.)")
    kp = sub.add_parser("kb-promote", help="merge a reviewed draft into the KB")
    kp.add_argument("--species", default="bass", required=True)
    kp.add_argument("--entry", required=True)
    kp.add_argument("--by", default="human reviewer", help="who verified it")

    of = sub.add_parser("offers", help="resolve retailer links for a KB entry (disclosure included)")
    of.add_argument("--entry")
    of.add_argument("--category", help="high-AOV category: electronics | rods-reels | kayaks | trips")
    of.add_argument("--shopping-list", action="store_true",
                    help="aggregate components across --entry a,b,c into one shopping list")
    of.add_argument("--add-url", help="register an offer URL")
    of.add_argument("--retailer", default="manufacturer-site")
    of.add_argument("--kind", choices=["manufacturer", "affiliate"], default="manufacturer")
    of.add_argument("--asin", help="amazon ASIN (affiliate kind)")

    tr = sub.add_parser("trends", help="trend signals (what's winning) — list, refresh, or show one")
    tr.add_argument("--refresh", action="store_true",
                    help="poll tournament feeds + creator channels into kb/pending/trends")
    tr.add_argument("--show", help="entity id — trends for one entity")

    cl = sub.add_parser("clicks", help="aggregate outbound-link click counts (no PII)")
    cl.add_argument("--src", help="filter by page section (tackle|gap)")
    cl.add_argument("--top", type=int, default=20)
    cl.add_argument("--remote", action="store_true",
                    help="read the production log over ssh (default: local)")

    st = sub.add_parser("stats", help="aggregate page-view counts (no PII)")
    st.add_argument("--days", type=int, default=30)
    st.add_argument("--top", type=int, default=15)
    st.add_argument("--remote", action="store_true",
                    help="read the production log over ssh (default: local)")

    tp = sub.add_parser("terminal", help="terminal tackle KB (hooks, weights, jig heads)")
    tp.add_argument("--show", help="entry id to print")
    tp.add_argument("--category", help="hook|weight|jighead|terminal")

    cp = sub.add_parser("colors", help="color/clarity principles (cited fish-vision science)")

    args = ap.parse_args()
    if args.cmd == "best":
        cmd_best(args)
    elif args.cmd == "outlook":
        cmd_outlook(args)
    elif args.cmd == "interview":
        interview(Path(args.out) if args.out else None)
    elif args.cmd == "report":
        cmd_report(args)
    elif args.cmd == "log":
        cmd_log(args)
    elif args.cmd == "review":
        import review
        since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
        review.run(angler=args.angler, since=since, lake=args.lake,
                   hours=float(args.hours), species=args.species)
    elif args.cmd == "days":
        cmd_days(args)
    elif args.cmd == "lakes":
        if args.auto:
            from layers.morphology import build_card
            card = build_card(args.auto)
            if not card:
                sys.exit(f"could not characterize '{args.auto}'")
            card["id"] = re.sub(r"[^a-z0-9]+", "-", card["name"].lower()).strip("-")
            print("─" * 56)
            print(f"  AUTO LAKE CARD — {card['name']}")
            print("─" * 56)
            print(f"  location : {card['lat']:.4f}, {card['lng']:.4f}  elev {card.get('alt_m') or '?'} m")
            print(f"  region   : {card['display']}")
            print(f"  area     : {card.get('area_acres', '?')} acres"
                  + f" ({card.get('area_source', 'osm')})" if card.get("area_acres") else "  area     : ? acres (unknown)")
            print(f"  depth    : {card['depth_class']} (est max ~{card.get('est_max_depth_ft') or '?'} ft)")
            print(f"  mixing   : {card['mixing']}")
            t = card["turnover"]
            print(f"  turnover : trigger {t['trigger_f']}°F · surface bias {t['surface_bias_f']}°F")
            print(f"            ({t['basis']})")
            reg = load_json(CONFIG / "lakes.json", {})
            reg[card["id"]] = card
            (CONFIG / "lakes.json").write_text(json.dumps(reg, indent=2))
            print(f"  ✅ cached to registry as '{card['id']}' — report with: ./fishwitch report --lake {card['id']}")
        else:
            for k, v in load_json(CONFIG / "lakes.json", {}).items():
                auto = "auto-card" if v.get("turnover", {}).get("basis", "").startswith("morphology") else ""
                print(f"{k:32s} {v['name']}, {v.get('region','')}  ({v['lat']:.3f},{v['lng']:.3f}) {auto}")
    elif args.cmd == "arsenal":
        sp = tx.normalize_species(args.species)
        for c in tx.catalog(sp):
            badge = "✅" if c["provenance"]["confidence"] == "verified" else "🟡"
            print(f"  {badge} {c['label']:40s} aliases: {', '.join(c['aliases'])}")

    elif args.cmd == "kb-ingest":
        from adapters import kb_ingest
        sources = json.loads((CONFIG.parent / "kb" / "sources.json").read_text())
        ids = [args.entry] if args.entry else list(sources.get(args.species, {}).keys())
        for eid in ids:
            d = kb_ingest.ingest(args.species, eid, refresh=args.refresh)
            if d is None:
                print(f"  ⊘ {eid}: no live source configured")
            elif "error" in d:
                print(f"  ✗ {eid}: {d['error']}")
            elif "skipped" in d:
                print(f"  = {eid}: {d['skipped']}")
            else:
                p = d["proposed"]
                if "quotes" in p:
                    print(f"  ✓ {eid}: {p['agency']} — {p['page_title']}")
                    print(f"      {p['source_url']}")
                    for q in p["quotes"]:
                        mark = "✓" if q["found"] else "✗ NOT FOUND"
                        print(f"      {mark} [{', '.join(q['all_of'])}]: “{(q['quote'] or '')[:88]}…”")
                else:
                    print(f"  ✓ {eid}: {p['product_title']}")
                    print(f"      {p['product_url']}")
                    for f in ("depth", "retrieve", "rigging"):
                        if p.get(f):
                            print(f"      {f}: “{p[f]['match']}”  ← “{p[f]['quote'][:90]}…”")
                print(f"      draft → kb/pending/{args.species}/{eid}.json (confidence: sourced)")

    elif args.cmd == "kb-review":
        from adapters import kb_ingest
        drafts = kb_ingest.review_queue()
        if not drafts:
            print("  queue empty — run `fishwitch kb-ingest` first")
        for p in drafts:
            d = json.loads(p.read_text())
            prop = d["proposed"]
            if d.get("new_entry"):
                print(f"  {d['species_kb']}/{d['entry_id']}: NEW — {prop.get('label', d['entry_id'])}")
                print(f"      source: {d['provenance'].get('source_url')}")
            elif "quotes" in prop:
                print(f"  {d['species_kb']}/{d['entry_id']}: {prop['agency']} — {prop['page_title']}")
                print(f"      source: {prop['source_url']}")
            else:
                print(f"  {d['species_kb']}/{d['entry_id']}: {prop['product_title']}")
                print(f"      source: {prop['source_url']}")
            print(f"      review with: fishwitch kb-promote --species {d['species_kb']} --entry {d['entry_id']} --by <you>")

    elif args.cmd == "kb-promote":
        from adapters import kb_ingest
        out = kb_ingest.promote(args.species, args.entry, args.by)
        if out:
            print(f"  ✅ promoted {args.entry} → {out} (verified_by: {args.by})")
        else:
            sys.exit(f"no pending draft for {args.species}/{args.entry}")

    elif args.cmd == "kb-reject":
        from adapters import kb_ingest
        log = kb_ingest.reject(args.species, args.entry, args.by, args.reason or "")
        if log:
            print(f"  🗑 rejected {args.entry} — decision logged to {log}")
        else:
            sys.exit(f"no pending draft for {args.species}/{args.entry}")

    elif args.cmd == "offers":
        import offers
        if getattr(args, "category", None):
            cats = offers.categories()
            if args.category not in cats:
                print("  categories:", ", ".join(cats) or "(none registered)")
                return
            cat = cats[args.category]
            print(f"  {cat.get('label', args.category)} — {cat.get('note', '')}")
            for e in offers.category_entries(args.category):
                print(f"  - {e.get('label', e.get('id'))}")
                for o in offers.resolve_category(args.category, e["id"]):
                    print(f"      [{o['retailer_label']:16s}] {o.get('url') or '(pending)'}")
                    print(f"                        {o['disclosure']}")
            return
        if not args.entry:
            print("  pass --entry <id> or --category <id>")
            return
        if args.shopping_list:
            ids = [s.strip() for s in args.entry.split(",") if s.strip()]
            entries = []
            for i in ids:
                c = tx.find_entry(i)
                entries.append(dict(id=i, label=(c or {}).get("label", i),
                                    spec=tx.rig_spec(i)))
            rows = offers.build_shopping(entries)
            if not rows:
                print("  no component bundles registered for those entries")
            for r in rows:
                links = " ".join(f"[{o['retailer_label']}]" for o in r["offers"] if o.get("url"))
                print(f"  {r['label']:44s} for {', '.join(r['for_labels'])}"
                      + (f"  {links}" if links else "  (no links yet)"))
            return
        if args.add_url:
            offers.add(args.entry, args.retailer, args.add_url, args.kind, args.asin)
            print(f"  ✅ offer registered: {args.entry} @ {args.retailer} ({args.kind})")
        rows = offers.resolve(args.entry)
        if not rows:
            print(f"  no offers registered for '{args.entry}' — add with --add-url")
        for o in rows:
            print(f"  [{o['retailer_label']:16s}] {o.get('url') or '(pending)'}")
            print(f"                    {o['disclosure']}")
        comps = offers.components(args.entry)
        if comps:
            print(f"  components ({len(comps)}):")
            for c in comps:
                linked = [o for o in c.get("offers", []) if o.get("url")]
                print(f"    {c['label']:34s} " + (f"{len(linked)} live link(s)" if linked else "(no links yet)"))

    elif args.cmd == "trends":
        from adapters import trends as tra
        if args.refresh:
            paths = tra.draft()
            print(f"  wrote {len(paths)} draft(s) → kb/pending/trends/")
            for p in paths:
                print(f"    - {p.name}")
            print("  review with `fishwitch kb-review`; promote with `kb-promote --species trends --entry <id>`")
            return
        rows = tx.load_trends().get("trends", [])
        if args.show:
            rows = [t for t in rows if t.get("entity_id") == args.show]
        if not rows:
            print("  no trends promoted yet — `fishwitch trends --refresh` drafts candidates")
            return
        for t in rows:
            print(f"  {t.get('entity_id','?'):<12} {str(t.get('observed_at',''))[:16]:<16} "
                  f"{t.get('signal',''):<10} {t.get('source','')[:44]}")
            print(f"      “{(t.get('quote') or '')[:100]}”")

    elif args.cmd == "clicks":
        from collections import Counter
        if args.remote:
            host = _baromoon_host()
            src = f"production — {host}:{REMOTE_DIR}/logs/out.jsonl"
            rows = _jsonl(_remote_lines(f"{REMOTE_DIR}/logs/out.jsonl"))
        else:
            log = ROOT / "logs" / "out.jsonl"
            if not log.exists():
                sys.exit(f"no clicks logged yet ({log})")
            src = "local — logs/out.jsonl"
            rows = _jsonl(log.read_text().splitlines())
        if args.src:
            rows = [r for r in rows if r.get("src") == args.src]
        print(f"  source: {src}")
        print(f"  {len(rows)} outbound clicks" + (f" (src={args.src})" if args.src else ""))
        for (entry, retailer), n in Counter(
                (r.get("entry"), r.get("retailer")) for r in rows).most_common(args.top):
            print(f"  {n:5d}  {entry:18s} {retailer}")
        by_src = Counter(r.get("src") or "?" for r in rows)
        if by_src:
            print("  by section:", ", ".join(f"{k}={v}" for k, v in by_src.most_common()))

    elif args.cmd == "stats":
        from telemetry import parse, summarize
        if args.remote:
            host = _baromoon_host()
            src = f"production — {host}:{REMOTE_DIR}/logs/pages.jsonl"
            rows = parse(_remote_lines(f"{REMOTE_DIR}/logs/pages.jsonl"))
        else:
            src = "local — logs/pages.jsonl"
            rows = None
        s = summarize(days=args.days, top=args.top, rows=rows)
        if not s["total"]:
            sys.exit(f"no page views logged yet ({src})")
        print(f"  source: {src}")
        print(f"  {s['total']} page views in the trailing {s['days']} days")
        print("  by page:")
        for path, n in s["by_path"]:
            print(f"    {n:5d}  {path}")
        if s["by_lake"]:
            print("  report views by lake:")
            for lake, n in s["by_lake"]:
                print(f"    {n:5d}  {lake}")
        if s["by_ref"]:
            print("  external referrers:")
            for ref, n in s["by_ref"]:
                print(f"    {n:5d}  {ref}")
        print("  by day: " + ", ".join(f"{d}:{n}" for d, n in s["by_day"]))

    elif args.cmd == "terminal":
        rows = tx.load_terminal().get("terminal", [])
        if args.show:
            e = next((x for x in rows if x["id"] == args.show), None)
            if not e:
                sys.exit(f"no terminal entry '{args.show}'")
            print(json.dumps(e, indent=2))
        else:
            for e in rows:
                if args.category and e.get("category") != args.category:
                    continue
                badge = "✅" if e.get("provenance", {}).get("confidence") == "sourced" else "🟡"
                print(f"  {badge} {e['id']:16s} {e['label']:34s} {e.get('category','')}")

    elif args.cmd == "colors":
        for p in tx.load_principles().get("principles", []):
            print(f"\n  {p['label']}  [{p['id']}]")
            print(f"    {p['rule']}")
            for c in p.get("citations", [])[:1]:
                print(f"    — {c['source']}: “{c['quote'][:110]}…”")

    elif args.cmd == "kb":
        sp = tx.normalize_species(args.species)
        if args.show:
            e = tx.entry(sp, args.show)
            if not e:
                sys.exit(f"no entry '{args.show}' in kb/{sp}.json")
            print(json.dumps(e, indent=2))
        else:
            cats = tx.catalog(sp)
            if args.conditions:
                toks = args.conditions.lower().split()
                def hit(c):
                    cond = c["conditions"]
                    for t in toks:
                        if t.rstrip("f").replace("°", "").isdigit():
                            t_f = float(t.rstrip("f").replace("°", ""))
                            lo, hi = cond["water_temp_f"]
                            if not (lo - 8 <= t_f <= hi + 8):
                                return False
                        elif any(t in band for band in cond["light"] + cond["wind"]):
                            continue
                    return True
                cats = [c for c in cats if hit(c)]
            for c in cats:
                p = c["provenance"]
                badge = "✅" if p["confidence"] == "verified" else "🟡"
                src = p["source"] if p["confidence"] == "verified" else p["confidence"]
                print(f"  {badge} {c['label']:44s} [{src}]")
                print(f"      light={','.join(c['conditions']['light'])[:60]} "
                      f"wind={','.join(c['conditions']['wind'])[:30]} "
                      f"temp={c['conditions']['water_temp_f'][0]}-{c['conditions']['water_temp_f'][1]}F")
            print(f"\n  {len(cats)} entries · kb file: {tx.kb_path(sp)} · add cited entries per kb/README.md")


if __name__ == "__main__":
    main()
