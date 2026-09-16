"""Report builder — combines all layers into a data model + markdown report.

`generate()` is the clean entry point for a future UI:
    model = generate(profile, lake, at_local, hours, species, voice)
    md = to_markdown(model)

THE TRANSLATION LAYER
─────────────────────
All sky math is always computed identically. `voice` controls presentation:
  "astro"   full disclosure — natal chart, transits, zodiac, planetary hours
  "almanac" traditional almanac framing — moon phase/sign, old-timers' lore,
            planetary hours by name (almanacs publish these), no natal chart
  "fisher"  zero astrology vocabulary — the same events surface as neutral
            "activity windows" (peak-feed / aggressive-feed / quiet-feed...)
The mapping is mechanical (see _t_event / HOUR_FISHER) so nothing is hidden,
just translated for the audience.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, date
from pathlib import Path

from weather import Weather
from skycalc import Sky, phase_name, illum_pct, fmt_sign, planet_lon, SIGNS, SYM
from chart import NatalChart, transit_aspects, voc_moon, moon_note, phase_resonance, HOUR_MEANINGS
import tactics as tx
import logbook as lb

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

# ── the translation layer ───────────────────────────────────────────────────
HOUR_FISHER = {
    "Jupiter": "peak-feed window", "Mars": "aggressive-feed window",
    "Venus": "quiet-feed window", "Moon": "slow-feed window",
    "Sun": "steady-cruise window", "Mercury": "finesse window",
    "Saturn": "grind window",
}
_ASPECT_EVENT = re.compile(r"\w+\s+[☌☍□△⚹]\s+natal\s+\w+ perfects")
_PLANET_HOUR = re.compile(r"\b(Sun|Moon|Mercury|Venus|Mars|Jupiter|Saturn) hour")


def _t_event(label: str, voice: str) -> str:
    if voice != "fisher":
        return label
    out = _ASPECT_EVENT.sub("activity spike", label)
    out = _PLANET_HOUR.sub(lambda m: HOUR_FISHER[m.group(1)], out)
    out = out.replace("moon leaves void-of-course", "feed window reopens")
    return out


def _fmt_ampm(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p") if hasattr(dt, "strftime") else str(dt)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ─────────────────────────────────────────────────────────────────────────────
def generate(profile: dict, lake: dict, at_local: datetime, hours: float = 2.5,
             species: str | None = None, voice: str | None = None,
             wx: Weather | None = None, hist=None) -> dict:
    species = tx.normalize_species(species or profile.get("species", "bass"))
    voice = voice or profile.get("astro_display") or "astro"
    if voice not in ("fisher", "almanac", "astro"):
        voice = "astro"
    wx = wx or Weather(lake["lat"], lake["lng"])
    sky = Sky(lake["lng"], lake["lat"], lake.get("alt_m", 300), wx.utc_offset)
    start, end = at_local, at_local + timedelta(hours=hours)

    sun = sky.sun_events_for_day(start)
    ms = sky.moon_state(sky.jd(start))
    moonrise, moonset = sky.moon_rise_set(start.replace(hour=0, minute=0))
    solunar = sky.solunar(start)
    phase_q, phase_q_label = sky.phase_quality(sky.jd(start))

    wxs = wx.at(start)
    wscore = wx.score(start, end)
    water_f = wx.est_water_f(start)
    win = wx.series(start, end)
    tmax = max(w["temp_f"] for w in win); tmin = min(w["temp_f"] for w in win)

    # ── lake state: manual flag > station data > inferred from history ──
    from layers.history import History
    from layers import watertemp as wt, stocking as stk
    lake_state_parts, state_basis = [], None
    days_since_turnover = None
    streak = 0
    real_temp = None
    try:
        hist = hist if hist is not None else History(lake["lat"], lake["lng"], start)
        streak = hist.heat_streak()
        tcfg = lake.get("turnover") or {}
        trig = tcfg.get("trigger_f", 68.0)
        bias = tcfg.get("surface_bias_f", 4.0)
        inf = hist.infer_turnover(trigger_f=trig, bias_f=bias)
        turnover = (lake.get("state") or {}).get("turned_over")
        tdate = None
        if turnover:
            try:
                tdate = date.fromisoformat(turnover)
                state_basis = "reported"
            except ValueError:
                pass
        if inf and not tdate:
            tdate = inf["date"].date()
            state_basis = inf["confidence"]
        if tdate:
            days_since_turnover = (start.date() - tdate).days
            if 0 <= days_since_turnover <= 21:
                lake_state_parts.append("post-turnover")
    except Exception:
        pass  # history layer offline → manual flags still work
    if streak >= 2:
        lake_state_parts.append("heat-streak")
    lake_state = "+".join(lake_state_parts) or None

    # real water temp where a gauge exists, else estimate
    real_temp = wt.nearest_water_temp(lake["lat"], lake["lng"])
    if real_temp:
        water_f = real_temp[1]
    stocking = stk.recent(lake)

    # access rules: documented in registry, enforced only when asked
    acc_note = None
    if lake.get("access") and (profile.get("enforce_access")
                                or (lake.get("access") or {}).get("enforce")):
        _acc = sky.access_window(start, lake.get("access"))
        if _acc:
            ao, ac, note = _acc
            acc_note = f"on-water {ao:%-I:%M %p}–{ac:%-I:%M %p} ({note}) — per registry access rules"
            if end > ac:
                end = ac
                acc_note += " · session clamped to close"

    natal = aspects = voc = mn = resonance = None
    if profile.get("birth"):
        natal = NatalChart(profile["birth"])
        aspects = transit_aspects(natal, sky.jd(start), hours + 2)
        voc = voc_moon(sky.jd(start), sky)
        mn = moon_note(sky.jd(start))
        resonance = phase_resonance(natal, sky.jd(start))

    arsenal = profile.get("arsenal") or []
    match = tx.match_arsenal(arsenal, species)
    if not match["matched"]:
        match = tx.match_arsenal(["chatterbait", "squarebill", "drop shot", "senko",
                                  "jig", "walking bait"], species)

    events = []
    events.append((start, "launch", "session"))
    events.append((end, "pack out", "session"))
    for key, lab in [("sunset", "sunset"), ("civil_dusk", "end of light (civil dusk)"),
                     ("sunrise", "sunrise"), ("civil_dawn", "first light (civil dawn)")]:
        t = sun.get(key) or sky.sun_events_for_day(start + timedelta(days=1)).get(key)
        if t and start - timedelta(minutes=90) <= t <= end + timedelta(minutes=30):
            events.append((t, lab, "light"))
    for e in solunar:
        if start - timedelta(minutes=60) <= e["start"] <= end:
            events.append((e["start"], f"{e['label']} begins", "solunar"))
        if start <= e["end"] <= end:
            events.append((e["end"], f"{e['label']} ends", "solunar"))
    for t, lab in ((moonrise, "moonrise"), (moonset, "moonset")):
        if t and start <= t <= end:
            events.append((t, lab, "moon"))
    for h in sky.planetary_hours(start):
        if start < h["start"] < end:
            events.append((h["start"], f"{h['ruler']} hour", "hour"))
    if aspects:
        for a in aspects:
            if a["perfect_jd"] is None:
                continue
            t = sky.loc(a["perfect_jd"])
            if start - timedelta(minutes=120) <= t <= end + timedelta(hours=12):
                events.append((t, f"{a['transit']} {a['sym']} natal {a['natal']} perfects", "aspect"))
    if voc and voc["void"] and voc["ends"] and start <= voc["ends"] <= end:
        events.append((voc["ends"], "moon leaves void-of-course", "moon"))

    events.sort(key=lambda e: e[0])
    merged = []
    for t, lab, kind in events:
        if merged and (t - merged[-1][0]).total_seconds() < 300:
            merged[-1] = (merged[-1][0], merged[-1][1] + f" + {lab}", kind)
        else:
            merged.append((t, lab, kind))
    pts = sorted(set([start] + [t for t, _, _ in merged if start < t < end] + [end]))
    blocks = []
    for a, b in zip(pts, pts[1:]):
        if (b - a).total_seconds() < 8 * 60:
            continue
        mid = a + (b - a) / 2
        light, sun_alt = sky.light_level(sky.jd(mid))
        w = wx.at(mid)
        hour = sky.hour_at(mid)
        sol = next((e["kind"] for e in solunar if e["start"] <= mid <= e["end"]), None)
        ev_notes = [lab for t, lab, k in merged if a <= t <= b and k != "session"
                    and not (k == "hour" and lab.split()[0] == hour["ruler"])]
        ctx = dict(light=light, cloud=w["cloud"], wind_mph=w["wind_mph"],
                   temp_f=w["temp_f"], water_f=water_f, hour_ruler=hour["ruler"],
                   solunar=sol, moon_fruitful=(mn["fruitful"] if mn else None),
                   pressure_word=wscore["trend"]["word"],
                   structure_notes=lake.get("structure", []),
                   lake_state=lake_state)
        picks = tx.recommend(ctx, match["matched"], top_n=2)
        blocks.append(dict(start=a, end=b, light=light, sun_alt=round(sun_alt, 1),
                           hour=hour, solunar=sol, events=ev_notes, picks=picks, wx=w))

    major_in = any(e["kind"] == "major" and e["start"] <= end and e["end"] >= start
                   for e in solunar)
    minor_in = any(e["kind"] == "minor" and e["start"] <= end and e["end"] >= start
                   for e in solunar)
    dusk_major = any(e["kind"] == "major" and abs((e["peak"] - sun["sunset"]).total_seconds())
                     < 3 * 3600 for e in solunar)
    sol_score = min(10, 5 + phase_q * 2 + (2 if major_in else 0) + (1 if minor_in else 0)
                    + (1 if dusk_major else 0))

    astro_score, astro_notes = 5.0, []
    perfecting = [a for a in (aspects or []) if a["perfect_jd"]]
    if perfecting:
        good = [a for a in perfecting if a["natal"] in ("Moon", "Venus", "Jupiter", "Sun")
                or a["transit"] in ("Venus", "Jupiter")]
        astro_score += 2 if good else 1
        astro_notes.append("live transit perfecting inside the session")
    if resonance:
        astro_score += 1; astro_notes.append("natal lunar-phase resonance")
    if voc and voc["void"]:
        astro_score -= 2; astro_notes.append("void-of-course moon at launch")
    if mn:
        if mn["fruitful"] == "fruitful":
            astro_score += 1.5; astro_notes.append(f"Moon in fruitful {mn['sign']}")
        elif mn["fruitful"] == "barren":
            astro_score -= 1; astro_notes.append(f"Moon in barren {mn['sign']} (lore)")
    astro_score = max(0, min(10, astro_score))

    overall = round(0.45 * wscore["score"] + 0.30 * sol_score + 0.25 * astro_score, 1)

    agg = {}
    for blk in blocks:
        dur = (blk["end"] - blk["start"]).total_seconds()
        weight = dur * (1.5 if blk["light"] in ("dusk/dawn", "night") else 1)
        for cat, sc, _ in blk["picks"]:
            agg[cat["id"]] = agg.get(cat["id"], 0) + weight * sc
    cat_by_id = {c["id"]: c for c, _ in match["matched"]}
    rods = [cat_by_id[i] for i, _ in sorted(agg.items(), key=lambda kv: -kv[1])][:5]

    def prime_score(blk):
        s = sum(p[1] for p in blk["picks"]) or 0
        if blk["solunar"] == "major": s += 2
        if blk["light"] in ("golden", "dusk/dawn", "sunset/sunrise", "night"): s += 2
        # a transit perfecting INSIDE the block outranks generic light favor —
        # that's the event the whole session is pointed at (validated 9/9/26:
        # Moon ☍ natal Venus perfected 7:41 PM, fish at 7:45 PM)
        for lab in blk["events"]:
            if "perfects" in lab:
                s += 3
                if any(b in lab for b in ("Venus", "Jupiter", "Moon", "Sun")):
                    s += 1
                break
        return s
    prime = max(blocks, key=prime_score) if blocks else None
    prime_s = round(prime_score(prime), 1) if prime else None

    # ── the gap lane: high scorers the angler DOESN'T own ────────────────
    # Display/monetization surface only — computed after all ranking is done,
    # never fed back into picks or scores (principle 4). Skipped for anonymous
    # renders (a gap against the generic fallback arsenal means nothing).
    gap = []
    if profile.get("arsenal") and prime is not None:
        pblk = prime
        pmid = pblk["start"] + (pblk["end"] - pblk["start"]) / 2
        pw = wx.at(pmid)
        gap_ctx = dict(light=pblk["light"], cloud=pw["cloud"], wind_mph=pw["wind_mph"],
                       temp_f=pw["temp_f"], water_f=water_f, hour_ruler=pblk["hour"]["ruler"],
                       solunar=pblk["solunar"], moon_fruitful=(mn["fruitful"] if mn else None),
                       pressure_word=wscore["trend"]["word"],
                       structure_notes=lake.get("structure", []), lake_state=lake_state)
        owned = {c["id"] for c, _ in match["matched"]}
        full = [(c, s, why) for c, s, why in
                tx.recommend(gap_ctx, [(c, c["label"]) for c in tx.catalog(species)
                                       if c["id"] not in owned], top_n=5)
                if s >= 5.0]
        gap = full[:3]


    return dict(
        profile=profile, lake=lake, start=start, end=end, hours=hours,
        species=species, voice=voice, sun=sun,
        moon=dict(ms, moonrise=moonrise, moonset=moonset, phase_quality=phase_q_label),
        solunar=solunar, weather=dict(score=wscore, start=wxs, tmax=tmax, tmin=tmin,
                                      water_f=water_f),
        natal=natal, aspects=(aspects or [])[:8], perfecting=perfecting,
        voc=voc, moon_note=mn, resonance=resonance, match=match,
        blocks=blocks, rods=rods, prime=prime, prime_score=prime_s, utc_off=wx.utc_offset,
        gap=gap,
        logbook=lb.summary_for(lake.get("name", ""), angler=profile.get("name")),
        lake_state=lake_state, days_since_turnover=days_since_turnover,
        heat_streak=streak, state_basis=state_basis, access_note=acc_note,
        water_temp_source=bool(real_temp), stocking=stocking,
        scores=dict(weather=wscore["score"], solunar=round(sol_score, 1),
                    astro=round(astro_score, 1), overall=overall,
                    astro_notes=astro_notes),
    )


LIGHT_LABELS = {"bright day": "high sun", "moderate day": "afternoon sun",
               "golden": "golden hour", "sunset/sunrise": "sunset",
               "dusk/dawn": "dusk", "night": "dark"}


def _perf_local(m: dict, a: dict) -> datetime:
    if "_sky" not in m:
        m["_sky"] = Sky(m["lake"]["lng"], m["lake"]["lat"], m["lake"].get("alt_m", 300),
                        m.get("utc_off", 0))
    return m["_sky"].loc(a["perfect_jd"])


# ─────────────────────────────────────────────────────────────────────────────
def to_markdown(m: dict, emoji: bool = True, show_gap: bool = True) -> str:
    def e(prefix: str) -> str:
        return prefix if emoji else ""
    voice = m["voice"]
    L = []
    wk = m["start"].strftime("%A").upper()
    date = m["start"].strftime("%b %-d").upper()
    if voice == "fisher":
        head = m["moon"]["phase"] + f" ({m['moon']['illum']:.0f}%)"
        if m["prime"]:
            head += f" | prime window {_fmt_ampm(m['prime']['start'])}"
    elif voice == "almanac" and m["moon_note"]:
        head = f"{m['moon']['phase']} ({m['moon']['illum']:.0f}%) | Moon in {m['moon_note']['sign']}"
    else:
        head = (m["moon"]["phase"] + f" ({m['moon']['illum']:.0f}%)")
        if m["moon_note"]:
            head += f" | Moon in {m['moon_note']['sign']}"
        if m["perfecting"]:
            a = m["perfecting"][0]
            amark = f"{a['sym']} " if emoji else ""
            head += f" | {a['transit']} {amark}{a['aspect']} natal {a['natal']}"
    L.append(f"# {e('🎣 ')}{wk} {date} — {_fmt_ampm(m['start'])} SESSION")
    L.append(f"### {m['lake']['name']}" +
             (f", {m['lake']['region']}" if m["lake"].get("region") else "") + " | " + head)
    L.append("")

    sun = m["sun"]
    moon_row = f"{m['moon']['phase']}, {m['moon']['illum']:.0f}% lit"
    if m["moon"]["moonset"]:
        moon_row += f", sets **{_fmt_ampm(m['moon']['moonset'])}**"
    if m["moon"]["moonrise"]:
        moon_row += f", rises {_fmt_ampm(m['moon']['moonrise'])}"
    score_name = "astro" if voice != "fisher" else "activity"
    rows = [
        ("Launch", f"**{_fmt_ampm(m['start'])}** / sunset **{_fmt_ampm(sun['sunset'])}** / dark ~"
         + _fmt_ampm(sun['civil_dusk'])),
        ("Moon", moon_row),
        ("Air", f"{m['weather']['start']['temp_f']:.0f}°F at launch / window {m['weather']['tmin']:.0f}–{m['weather']['tmax']:.0f}°F"),
    ]
    if m["weather"]["water_f"]:
        src = "USGS gauge" if m.get("water_temp_source") else "air-temp estimate — small-lake assumption"
        rows.append(("Water", f"~{m['weather']['water_f']:.0f}°F ({src})"))
    lake_sp = [s.lower() for s in m["lake"].get("species", [])]
    sp_word = m["species"].split()[0]
    if lake_sp and not any(sp_word in s for s in lake_sp):
        rows.append(("Species check", f"{e('⚠️ ')}lake registry does not list {m['species']} for this water — verify before trusting the tactics"))
    elif lake_sp:
        logged = any(sp_word in (str(r.get("species") or "")).lower()
                     for r in lb.load() if r.get("result") != "skunk"
                     and (r.get("lake") or "").lower() in m["lake"]["name"].lower())
        presence = (("✅ " if emoji else "") + "angler-verified in logbook") if logged \
            else (("🟡 " if emoji else "") + "not yet confirmed by a logged catch")
        rows.append(("Species presence", "listed in registry · " + presence))
    if m.get("stocking"):
        s = m["stocking"][-1]
        rows.append(("Stocking", f"{s['species']} planted {s['date']:%b %-d} — fresh stockers = shallow forage event"))
    if m["logbook"]:
        rows.append(("Your logbook", f"{m['logbook']['n']} logged catches here"
                     + (f", best producer {m['logbook']['best_lure']}" if m["logbook"]["best_lure"] else "")))
    w = m["weather"]["start"]
    ls_bits = []
    if m.get("days_since_turnover") is not None and m.get("lake_state") and "post-turnover" in m["lake_state"]:
        basis = m.get("state_basis") or "reported"
        ls_bits.append(f"turned over **{m['days_since_turnover']} days ago** ({basis})")
    if m.get("heat_streak", 0) >= 2:
        ls_bits.append(f"{m['heat_streak']}-day ≥90°F heat streak")
    if ls_bits:
        rows.append(("Lake state", " · ".join(ls_bits) + " — fish position altered, see rules"))
    if m.get("access_note"):
        rows.append((("Lake hours 🚤" if emoji else "Lake hours"), m["access_note"]))
    rows.append(("Sky/wind", f"{w['cloud']}% cloud, {w['wind_mph']:.0f} mph wind, "
                 f"{m['weather']['score']['trend']['word']} barometer ({m['weather']['score']['trend']['now']:.0f} hPa)"))
    if m["solunar"]:
        in_win = [e for e in m["solunar"] if e["end"] >= m["start"] and e["start"] <= m["end"]]
        near = [e for e in m["solunar"] if e not in in_win]
        evs = in_win + near
        rows.append(("Solunar", "; ".join(
            ("→ " if e in in_win else "") + f"{e['label']} ~{_fmt_ampm(e['peak'])}"
            for e in evs[:3]) or "quiet day"))
    rows.append(("Scores", f"weather {m['scores']['weather']:.0f}/10 · solunar {m['scores']['solunar']:.0f}/10 · "
                 f"{score_name} {m['scores']['astro']:.0f}/10 → **overall {m['scores']['overall']}/10**"))
    # data completeness — which tiers this report actually had
    if emoji:
        tiers = [
            "✅ sky+weather",
            "✅ history→lake-state" if (m.get("state_basis") or m.get("lake_state"))
            else "⚠️ no lake state (manual flag?)",
            "✅ gauge water temp" if m.get("water_temp_source") else "🟡 est. water temp",
            "✅ stocking data" if m.get("stocking") else "🟡 no stocking intel",
            ('✅' if m.get('logbook') else '🟡') + " logbook"
            + (f" ({m['logbook']['n']})" if m.get("logbook") else ""),
            "🟡 bathymetry (registry notes only)",
        ]
    else:
        tiers = [
            "sky + weather",
            "history → lake-state" if (m.get("state_basis") or m.get("lake_state"))
            else "no lake-state inference",
            "gauge water temp" if m.get("water_temp_source") else "water temp estimated",
            "stocking data" if m.get("stocking") else "no stocking intel",
            "logbook" + (f" ({m['logbook']['n']})" if m.get("logbook") else " (none)"),
            "bathymetry: registry notes only",
        ]
    rows.append(("Data layers", " · ".join(tiers)))
    L.append(f"## {e('🔒 ')}The locked numbers")
    L.append("| | |"); L.append("|---|---|")
    for k, v in rows:
        L.append(f"| {k} | {v} |")
    L.append("")

    L.append(f"## {e('🌤 ')}Weather layer")
    for n in m["weather"]["score"]["notes"]:
        L.append(f"- {n}")
    if m.get("lake_state"):
        L.append(f"- {e('⚠️ ')}**Lake state: {m['lake_state']}** — turnover redistributes oxygen and bait;"
                 " deep presentations lead until the lake re-stratifies")
    # species thermal fit: is the water inside the KB band of the top picks?
    if m["weather"]["water_f"] and m["rods"]:
        hi = max(c["conditions"]["water_temp_f"][1] for c in m["rods"])
        lo = min(c["conditions"]["water_temp_f"][0] for c in m["rods"])
        wf = m["weather"]["water_f"]
        if wf > hi + 3:
            L.append(f"- {e('⚠️ ')}water ~{wf:.0f}°F is **above the comfort band** for this species' tactics (KB tops out {hi}°F) — expect deep, dormant, or absent fish")
        elif wf < lo - 3:
            L.append(f"- {e('⚠️ ')}water ~{wf:.0f}°F is **below the band** for these tactics (KB floor {lo}°F) — slow presentations only")
    L.append("")

    if voice == "fisher":
        L.append(f"## {e('🫧 ')}Activity windows")
        L.append("- computed from lunar/solar position and feeding-window models — no mysticism required")
        if m["prime"]:
            L.append(f"- **prime window: {_fmt_ampm(m['prime']['start'])}–{_fmt_ampm(m['prime']['end'])}** ({m['prime']['light']})")
        spikes = [_t_event(lab, voice) for blk in m["blocks"] for lab in blk["events"]
                  if "perfects" in lab or "hour" in lab.lower()]
        for s in dict.fromkeys(spikes):
            L.append(f"- {s}")
    elif voice == "almanac":
        L.append(f"## {e('🌙 ')}Almanac layer (the old-timers' calendar)")
        mn = m["moon_note"]
        if mn:
            L.append(f"- **Moon in {mn['sign']}** — {mn['quip']} *(almanac tradition, honored as lore)*")
        L.append(f"- {m['moon']['phase_quality'].capitalize()} — the almanac rates this a strong-feeding stretch")
        if m["voc"]:
            L.append(f"- {e('⚠️ ') if m['voc']['void'] else ''}{_t_event(m['voc']['note'].split(' — ')[0], voice)}"
                     + (" — quiet hours, almanacs say fish pick at baits" if m["voc"]["void"] else ""))
        h0 = m["blocks"][0]["hour"] if m["blocks"] else None
        if h0:
            L.append(f"- Planetary hour at launch: **{h0['ruler']}** — {HOUR_MEANINGS[h0['ruler']]} *(published in almanacs for centuries)*")
    elif m["natal"]:
        L.append(f"## {e('🌙 ')}Astrology layer (vs. your chart)")
        mn = m["moon_note"]
        L.append(f"- **Moon {mn['fmt'] if emoji else mn.get('fmt_plain', mn['fmt'])} — in natal house {m['natal'].house_of(mn['lon'])}** · {mn['lore']}: {mn['quip']}")
        if m["resonance"]:
            L.append(f"- **{m['resonance']}**")
        L.append(f"- Chart: {m['natal'].sect} chart · natal lunar phase {m['natal'].natal_phase}")
        for d in m["natal"].dignity_notes(emoji)[:4]:
            L.append(f"- {d}")
        hour0 = m["blocks"][0]["hour"] if m["blocks"] else None
        if hour0:
            L.append(f"- Planetary day/hour at launch: **{hour0['ruler']}** — {HOUR_MEANINGS[hour0['ruler']]}")
        if m["voc"]:
            L.append(f"- Moon: {e('⚠️ ') if m['voc']['void'] else e('✅ ')}{m['voc']['note']}")
        if m["aspects"]:
            L.append("")
            L.append("| Transit | Aspect | Natal point | Orb | Perfects |")
            L.append("|---|---|---|---|---|")
            for a in m["aspects"][:6]:
                if a["perfect_jd"]:
                    perf = f"**{_fmt_ampm(_perf_local(m, a))}**"
                else:
                    perf = "applying" if a["applying"] else "separating"
                asym = f"{a['sym']} {a['aspect']}" if emoji else a["aspect"]
                L.append(f"| {a['transit']} | {asym} | {a['natal']} | "
                         f"{a['orb']:.2f}° | {perf} |")
    L.append("")

    L.append(f"## {e('⏱ ')}The session, hour-by-hour")
    L.append("| Time | Window | Sky | Do this |")
    L.append("|---|---|---|---|")
    for b in m["blocks"]:
        stars = e("⭐ ") if b is m["prime"] else ""
        astro = []
        if b["hour"]:
            astro.append(HOUR_FISHER[b["hour"]["ruler"]] if voice == "fisher"
                         else b["hour"]["ruler"])
        if b["solunar"]:
            astro.append(f"{b['solunar']} ON")
        for lab in b["events"][:3]:
            astro.append(_t_event(lab, voice))
        pick_txt = "<br>".join(
            f"**{c['label']}** — {c['technique']}"
            + (f" · {tx.zone_hint(c, b['light'])}" if tx.zone_hint(c, b['light']) else "")
            + (f" ({tx.color_hint(c, dict(light=b['light'], cloud=b['wx']['cloud']))})"
               if tx.color_hint(c, dict(light=b['light'], cloud=b['wx']['cloud'])) else "")
            for c, s, why in b["picks"]) or "keep casting — transition block"
        zone = (f"{e('🎯 ')}deep water / first break, slow"
                if m.get("lake_state") and "post-turnover" in m["lake_state"]
                and b["light"] != "night" else None)
        if zone:
            pick_txt = f"*{zone}*<br>" + pick_txt
        L.append(f"| {stars}{_fmt_ampm(b['start'])}–{_fmt_ampm(b['end'])} | "
                 f"{' · '.join(dict.fromkeys(a for a in astro if a)) or '—'} | "
                 f"{LIGHT_LABELS.get(b['light'], b['light'])} | {pick_txt} |")
    L.append("")

    L.append(f"## {e('🎣 ')}Rods tied")
    for c in m["rods"]:
        L.append(f"- {c['label']}" + (f" — {c['note']}" if c.get("note") else ""))
    unmatched = m["match"]["unmatched"]
    if unmatched:
        L.append(f"- *(no match in the KB for: {', '.join(unmatched)} — still bring them)*")
    L.append("")

    if show_gap and m.get("gap"):
        products = [g for g in m["gap"] if g[0].get("kind", "product") != "rig"]
        rigs = [g for g in m["gap"] if g[0].get("kind", "product") == "rig"]

        def _gap_line(c, s, why):
            p = c["provenance"]
            badge = "✅" if p.get("confidence") in ("verified", "sourced") else "🟡"
            return (f"- {badge} **{c['label']}** — scores {s:.1f} here"
                    + (f" · {'; '.join(why)}" if why else "")
                    + (f" · *{c['note']}*" if c.get("note") else ""))

        if products:
            L.append(f"## {e('🧭 ')}The gap in your tackle box")
            L.append("*Scored by the same pipe for these exact conditions — you don't own these yet. "
                     "Offers attach after ranking, never before.*")
            for c, s, why in products:
                L.append(_gap_line(c, s, why))
            L.append("")
        if rigs:
            L.append(f"## {e('🧵 ')}Rig & technique gaps")
            L.append("*Rigging patterns these conditions favor that aren't in your box — built "
                     "from hooks, weights, and plastics you mostly own. A how-to, not a purchase.*")
            for c, s, why in rigs:
                L.append(_gap_line(c, s, why))
            L.append("")

    ctx = dict(wind_mph=m["weather"]["start"]["wind_mph"], cloud=m["weather"]["start"]["cloud"],
               moon_fruitful=(m["moon_note"]["fruitful"] if m["moon_note"] else None),
               pressure_word=m["weather"]["score"]["trend"]["word"],
               structure_notes=m["lake"].get("structure", []),
               lake_state=m.get("lake_state"))
    L.append(f"## {e('🧠 ')}Decision rules")
    for r in tx.decision_rules(ctx, [c["label"] for c in m["rods"]]):
        if voice == "fisher":
            r = r.replace("barren-sign evenings backload — the payoff window is late",
                          "slow starts backload the payoff window on dark moons")
        L.append(f"- {r}")
    for lore in m["lake"].get("lore", [])[:2]:
        L.append(f"- Lake lore: {lore}")
    L.append("")

    L.append(f"## {e('🎯 ')}One-paragraph version")
    parts = [f"Launch at **{_fmt_ampm(m['start'])}**"]
    if m["blocks"]:
        h0 = m["blocks"][0]["hour"]
        parts[0] += (f" into a **{HOUR_FISHER[h0['ruler']]}**" if voice == "fisher"
                     else f" into a **{h0['ruler']} hour**")
    if m["prime"]:
        top = m["prime"]["picks"][0] if m["prime"]["picks"] else None
        parts.append(f"— the window that matters is **{_fmt_ampm(m['prime']['start'])}–{_fmt_ampm(m['prime']['end'])}"
                     + f" ({m['prime']['light']})" + "**")
        if top:
            parts.append(f"parked on the **{top[0]['label'].lower()}**")
    if m["perfecting"]:
        a = m["perfecting"][0]
        amark = f"{a['sym']} " if emoji else ""
        parts.append(("with the activity spike landing mid-session" if voice == "fisher"
                      else f"while {a['transit']} {amark}{a['aspect']} natal {a['natal']} perfects on the water"))
    sc = m["scores"]["overall"]
    if sc >= 7.5:
        parts.append(f"Overall **{sc}/10** — a genuinely good hand; cash it")
    elif sc >= 5.5:
        parts.append(f"Overall **{sc}/10** — solid conditions with one clear prime window; be there for it")
    else:
        parts.append(f"Overall **{sc}/10** — a grind-it-out session; let the finesse baits earn it")
    L.append(", ".join(parts[:-1]) + ". " + parts[-1] + ".")
    L.append("")
    L.append("---")
    core = "fishwitch mvp — weather via Open-Meteo · sky via Swiss Ephemeris · "
    if voice == "fisher":
        credit = core + "lunar/solar feeding-window model."
    elif voice == "almanac":
        credit = core + "solunar + almanac tradition (fruitful/barren signs are old lore, honored but labeled)."
    else:
        credit = core + "astrology vs. your natal chart · solunar & planetary-hour timing · fruitful/barren signs are traditional almanac lore, honored but labeled."
    L.append(f"*{credit}*")
    return "\n".join(L)


def save(m: dict, md: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    slug = _slug(f"{m['lake']['name']} {m['start'].strftime('%Y-%m-%d %H%M')}")
    p = REPORTS_DIR / f"{slug}.md"
    p.write_text(md)
    return p
