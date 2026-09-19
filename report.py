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

from weather import Weather, model_agreement
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
             wx: Weather | None = None, hist=None, bottom: str | None = None) -> dict:
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

    # real water temp where a gauge exists (distance-guarded), else estimate
    real_temp = wt.nearest_water_temp(lake["lat"], lake["lng"])
    water_temp_label = None
    if real_temp:
        water_f = real_temp[1]
        water_temp_label = real_temp[2]
    stocking = stk.recent(lake)
    # multi-model agreement: display-only confidence, never scoring
    try:
        forecast = model_agreement(lake["lat"], lake["lng"], start, end)
    except Exception:
        forecast = None
    # bass spawn phase: T2 water-temp triggers during the warming half of the
    # year; T5 rig fits ride the capped tie-break layer (kb/spawn.json). The
    # 7-day water trend vetoes a phase in actively cooling water.
    water_trend = None
    try:
        water_trend = wx.water_trend_f_per_week(start)
    except Exception:
        water_trend = None
    bass_phase = tx.spawn_phase(water_f, start.month, water_trend)
    # wind exposure from the cached OSM shoreline: where the wind stacks bait
    shoreline = None
    try:
        from layers import shoreline as _shore
        if (wxs.get("wind_mph") or 0) >= 5:
            shoreline = _shore.wind_shore(lake.get("id"), wxs.get("dir"))
    except Exception:
        shoreline = None

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
    baits = profile.get("baits") or []
    # the angler's baseline (lures/rigs + live/cut/prepared baits) is a LENS,
    # not a filter: every cited KB entry is scored for the conditions and the
    # best rigs rank first for everyone. Ownership only tags which picks are
    # already in the angler's box.
    baseline = tx.match_arsenal(list(arsenal) + list(baits), species)
    owned_ids = {c["id"] for c, _ in baseline["matched"]}
    has_baseline = bool(arsenal or baits)
    candidates = [(c, c["label"]) for c in tx.catalog(species)]

    # the angler's knot repertoire (like the arsenal): their knots come first,
    # and any better-fit knot they don't tie is surfaced as "worth learning"
    angler_knots = tx.match_knots(profile.get("knots") or [])
    known_knot_ids = {k["id"] for k in angler_knots}

    # the angler's line kit (same idea): the condition pick is flagged when it
    # isn't already on their spools
    angler_line = tx.match_line(profile.get("line") or [])
    known_line_ids = {t["id"] for t in angler_line}

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
                   structure_notes=lake.get("structure", []), month=mid.month,
                   lake_state=lake_state, bottom=bottom)
        picks = tx.recommend(ctx, candidates, top_n=2)
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
    cat_by_id = {c["id"]: c for c, _ in candidates}
    rods = [cat_by_id[i] for i, _ in sorted(agg.items(), key=lambda kv: -kv[1])][:5]

    # knots for the rods actually recommended (cited facts; see kb/knots.json);
    # prefer the angler's own knots, surface better fits they don't tie
    knots, _seen_knots = [], set()
    for c in rods:
        for k in tx.knots_for(c["id"], limit=2, known=known_knot_ids or None):
            if k["id"] not in _seen_knots:
                _seen_knots.add(k["id"])
                kk = dict(k)
                kk["mine"] = (not known_knot_ids) or (k["id"] in known_knot_ids)
                knots.append(kk)
    knots = knots[:3]
    knot_notes = (tx.load_knots().get("repertoire", {}) or {}).get("practices", [])
    line = tx.recommend_line(rods, known=known_line_ids or None)

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

    # ── trend watch: market signals, scored against the prime window ────────
    # Post-ranking only. A trend never changes a score; it tells the angler
    # what's winning and whether these conditions actually favor it.
    trends = []
    if prime:
        pmid = prime["start"] + (prime["end"] - prime["start"]) / 2
        pw = wx.at(pmid)
        pctx = dict(light=prime["light"], cloud=pw["cloud"], wind_mph=pw["wind_mph"],
                    temp_f=pw["temp_f"], water_f=water_f, hour_ruler=prime["hour"]["ruler"],
                    solunar=prime["solunar"], moon_fruitful=(mn["fruitful"] if mn else None),
                    pressure_word=wscore["trend"]["word"], month=prime["start"].month,
                    structure_notes=lake.get("structure", []), lake_state=lake_state,
                    bottom=bottom)
        for c in tx.catalog(species):
            entries = tx.trends_for(c["id"])
            if not entries:
                continue
            sc, _why, rej = tx.score_entry(c, pctx)
            if rej or sc <= 0:
                continue   # out of band for this window — trend not shown
            for t in entries:
                trends.append(dict(label=c["label"], score=round(sc, 1), fits=(sc >= 5.0),
                                   signal=t.get("signal", ""), source=t.get("source", ""),
                                   url=t.get("url"), observed_at=t.get("observed_at", ""),
                                   quote=t.get("quote", ""), note=t.get("note", "")))
        trends.sort(key=lambda x: -x["score"])

    # ── the gap lane: the best scorers the angler DOESN'T own ────────────
    # Display/monetization surface only — computed after all ranking is done,
    # never fed back into picks or scores (principle 4). Skipped when the
    # angler gave no baseline (a "gap" against nothing means nothing).
    gap = []
    box_check = []
    if has_baseline and prime is not None:
        pblk = prime
        pmid = pblk["start"] + (pblk["end"] - pblk["start"]) / 2
        pw = wx.at(pmid)
        gap_ctx = dict(light=pblk["light"], cloud=pw["cloud"], wind_mph=pw["wind_mph"],
                       temp_f=pw["temp_f"], water_f=water_f, hour_ruler=pblk["hour"]["ruler"],
                       solunar=pblk["solunar"], moon_fruitful=(mn["fruitful"] if mn else None),
                       pressure_word=wscore["trend"]["word"], month=pblk["start"].month,
                       structure_notes=lake.get("structure", []), lake_state=lake_state,
                       bottom=bottom)
        owned = owned_ids
        full = [(c, s, why) for c, s, why in
                tx.recommend(gap_ctx, [(c, c["label"]) for c in tx.catalog(species)
                                       if c["id"] not in owned], top_n=5)
                if s >= 5.0]
        gap = full[:3]

        # your box vs the board: the engine already scored every bait the
        # angler owns for the prime window, including the ones that lost.
        # Surface the reasons (rejection or the top cited fits) — display
        # only, computed after all ranking, never fed back into picks.
        pick_ids = {c["id"] for c, _, _ in prime["picks"]}
        top_score = max((s for _, s, _ in prime["picks"]), default=0.0)
        lost = []
        for c, _label in baseline["matched"]:
            if c["id"] in pick_ids:
                continue
            sc, why, rej = tx.score_entry(c, gap_ctx)
            if rej:
                reason, out = rej, True
            else:
                reason, out = ("; ".join(why[:2]) or
                               ("fits — the top picks edge it" if sc >= top_score
                                else "in the conditions band — the top picks score higher")), False
            lost.append(dict(label=c["label"], id=c["id"], score=round(sc, 1),
                             reason=reason, out=out))
        lost.sort(key=lambda r: (-r["score"], r["label"]))
        box_check = lost[:6]


    _cb = prime or (blocks[0] if blocks else None)
    color = tx.color_principle(dict(
        light=(_cb or {}).get("light"),
        cloud=((_cb or {}).get("wx") or {}).get("cloud", 0),
        lake_state=lake_state)) if _cb else None

    return dict(
        profile=profile, lake=lake, start=start, end=end, hours=hours,
        species=species, voice=voice, sun=sun,
        moon=dict(ms, moonrise=moonrise, moonset=moonset, phase_quality=phase_q_label),
        solunar=solunar, weather=dict(score=wscore, start=wxs, tmax=tmax, tmin=tmin,
                                      water_f=water_f),
        natal=natal, aspects=(aspects or [])[:8], perfecting=perfecting,
        voc=voc, moon_note=mn, resonance=resonance, match=baseline,
        blocks=blocks, rods=rods, prime=prime, prime_score=prime_s, utc_off=wx.utc_offset,
        knots=knots, knot_notes=knot_notes, angler_knots=angler_knots, line=line, color=color, gap=gap,
        angler_line=angler_line, owned_ids=owned_ids, has_baseline=has_baseline,
        bottom=bottom, trends=trends, box_check=box_check,
        logbook=lb.summary_for(lake.get("name", ""), angler=profile.get("name")),
        lake_state=lake_state, days_since_turnover=days_since_turnover,
        heat_streak=streak, state_basis=state_basis, access_note=acc_note,
        water_temp_source=bool(real_temp), water_temp_label=water_temp_label,
        stocking=stocking, forecast=forecast, shoreline=shoreline,
        bass_phase=bass_phase, water_trend=water_trend,
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


def _lead_paragraph(m: dict, voice: str, emoji: bool, has_box: bool, owned: set) -> str:
    """The report's opening read: launch hour, the one window that matters,
    the top pick, the sky event, and the overall call."""
    lead = f"Launch at **{_fmt_ampm(m['start'])}**"
    if m["blocks"]:
        h0 = m["blocks"][0]["hour"]
        phrase = (HOUR_FISHER.get(h0["ruler"], f"{h0['ruler']} hour") if voice == "fisher"
                  else f"{h0['ruler']} hour")
        art = "an" if phrase[:1].lower() in "aeiou" else "a"
        lead += f" into {art} **{phrase}**"
    mids = []
    if m["prime"]:
        light = LIGHT_LABELS.get(m["prime"]["light"], m["prime"]["light"])
        mids.append(f"the window that matters is **{_fmt_ampm(m['prime']['start'])}–"
                    f"{_fmt_ampm(m['prime']['end'])}** ({light})")
        top = m["prime"]["picks"][0] if m["prime"]["picks"] else None
        if top:
            gap_note = " (a gap — not in your box)" if has_box and top[0]["id"] not in owned else ""
            mids.append(f"parked on the **{top[0]['label'].lower()}**{gap_note}")
    if m["perfecting"]:
        a = m["perfecting"][0]
        amark = f"{a['sym']} " if emoji else ""
        mids.append("the activity spike lands mid-session" if voice == "fisher"
                    else f"{a['transit']} {amark}{a['aspect']} natal {a['natal']} perfects on the water")
    sc = m["scores"]["overall"]
    if sc >= 7.5:
        call = f"Overall **{sc}/10** — a genuinely good hand; cash it"
    elif sc >= 5.5:
        call = f"Overall **{sc}/10** — solid conditions with one clear prime window; be there for it"
    else:
        call = f"Overall **{sc}/10** — a grind-it-out session; let the finesse baits earn it"
    out = lead
    if mids:
        out += "; " + ", ".join(mids)
    return out + ". " + call + "."


# ─────────────────────────────────────────────────────────────────────────────
def to_markdown(m: dict, emoji: bool = True, show_gap: bool = True) -> str:
    def e(prefix: str) -> str:
        return prefix if emoji else ""
    voice = m["voice"]
    owned = m.get("owned_ids") or set()
    has_box = bool(m.get("has_baseline"))

    def _box(c: dict, short: bool = False) -> str:
        """Ownership tag — the personal lens on top of the conditions rank."""
        if not has_box:
            return ""
        if c["id"] in owned:
            return " *(yours)*" if short else " — *in your box*"
        return " *(gap)*" if short else " — *not in your box (gap)*"

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
    L.append(f"## {e('🎯 ')}One-paragraph version")
    L.append(_lead_paragraph(m, voice, emoji, has_box, owned))
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
        src = ((m.get("water_temp_label") or "gauge") if m.get("water_temp_source")
               else "air-temp lag — small-lake estimate, no gauge within 30 km")
        _wt = m.get("water_trend")
        if _wt is not None:
            src += (f"; {'warming' if _wt > 0 else ('cooling' if _wt < 0 else 'steady')} "
                    f"{_wt:+.1f}°F/wk")
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
    if m.get("bass_phase"):
        _pnote, _ = tx.spawn_note(m["bass_phase"])
        rows.append(("Bass phase", f"**{m['bass_phase']}** — {_pnote}"))
    if m.get("access_note"):
        rows.append((("Lake hours 🚤" if emoji else "Lake hours"), m["access_note"]))
    rows.append(("Sky/wind", f"{w['cloud']}% cloud, {w['wind_mph']:.0f} mph wind, "
                 f"{m['weather']['score']['trend']['word']} barometer ({m['weather']['score']['trend']['now']:.0f} hPa)"))
    if m.get("forecast"):
        rows.append(("Forecast", f"{m['forecast']['label']} agreement — {m['forecast']['summary']}"))
    if m.get("color"):
        rows.append(("Color", m["color"]["rule"]))
    if m.get("bottom"):
        rows.append(("Bottom", f"**{m['bottom']}** — substrate fit applied as a capped tie-break (kb/CONDITIONS.md)"))
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
            ("✅ " + m["forecast"]["summary"] + f" ({m['forecast']['label']} agreement)")
            if m.get("forecast") else "🟡 forecast agreement unavailable",
            "✅ history→lake-state" if (m.get("state_basis") or m.get("lake_state"))
            else "⚠️ no lake state (manual flag?)",
            ("✅ " + (m.get("water_temp_label") or "gauge water temp"))
            if m.get("water_temp_source") else "🟡 est. water temp (no gauge nearby)",
            "✅ stocking data" if m.get("stocking") else "🟡 no stocking intel",
            ('✅' if m.get('logbook') else '🟡') + " logbook"
            + (f" ({m['logbook']['n']})" if m.get("logbook") else ""),
            "🟡 bathymetry (registry notes only)",
        ]
    else:
        tiers = [
            "sky + weather",
            (m["forecast"]["summary"] + f" ({m['forecast']['label']} agreement)")
            if m.get("forecast") else "forecast agreement unavailable",
            "history → lake-state" if (m.get("state_basis") or m.get("lake_state"))
            else "no lake-state inference",
            (m.get("water_temp_label") or "gauge water temp") if m.get("water_temp_source")
            else "water temp estimated (no gauge nearby)",
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
            f"**{c['label']}**{_box(c, short=True)} — {c['technique']}"
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

    L.append(f"## {e('🎣 ')}Best rigs for these conditions")
    for c in m["rods"]:
        _, sfit = tx.substrate_fit(c["id"], m.get("bottom"))
        L.append(f"- {c['label']}" + (f" — {c['note']}" if c.get("note") else "") + _box(c)
                 + (f" — *{sfit}*" if sfit else ""))
        setups = (m.get("profile") or {}).get("setups") or {}
        setup = setups.get(c["id"]) if isinstance(setups, dict) else None
        spec = tx.rig_spec(c["id"])
        if setup:
            L.append(f"    - *your build: {tx.setup_line(setup)}*")
        elif spec:
            L.append(f"    - *build: {tx.spec_line(spec)}*")
            if spec.get("source"):
                L.append(f"      *({spec['source']})*")
    unmatched = m["match"]["unmatched"]
    if unmatched:
        L.append(f"- *(no match in the KB for: {', '.join(unmatched)} — still bring them)*")
    L.append("")

    if m.get("box_check"):
        _picks = (m.get("prime") or {}).get("picks") or []
        _top = max((s for _, s, _ in _picks), default=None)
        L.append(f"## {e('🔎 ')}Why not your usual?")
        L.append("*Every bait in your box was scored for the prime window"
                 + (f" (top pick {_top:g})" if _top is not None else "")
                 + " — the notes are the engine's own fit reasons.*")
        for r in m["box_check"]:
            if r["out"]:
                L.append(f"- **{r['label']}** — out of band: {r['reason']}")
            else:
                L.append(f"- **{r['label']}** — {r['score']:g} · {r['reason']}")
        L.append("")

    if m.get("trends"):
        L.append(f"## {e('📈 ')}Trend watch — what's winning (market signal, not science)")
        L.append("*Dated tournament/creator signals for rigs that already fit these conditions — "
                 "shown after ranking and never scored into it.*")
        for t in m["trends"][:4]:
            src = f"[{t['source']}]({t['url']})" if t.get("url") else t["source"]
            fit = (f"fits these conditions (scores {t['score']})" if t.get("fits")
                   else f"not favored in this window (scores {t['score']})")
            L.append(f"- **{t['label']}** — {fit} · {src} ({t['observed_at']})")
            if t.get("quote"):
                L.append(f"    - *“{t['quote'][:180]}”*")
        L.append("")

    if m.get("knots") or m.get("line"):
        head = ("Line & your knots for these rigs" if m.get("angler_knots")
                else "Line & knots for these rigs")
        L.append(f"## {e('🪢 ')}{head}")
        if m.get("line"):
            ln = m["line"]
            extra = ""
            if ln.get("mine") is False:
                have = ", ".join(t["label"] for t in (m.get("angler_line") or []))
                extra = f" — *not in your kit (you spool {have}); worth spooling for these rigs*"
            elif ln.get("mine") is True:
                extra = " — *that's your line*"
            L.append(f"- **{ln['label']}** — {ln['why']}{extra}")
        if m.get("knots"):
            L.append("*Knots quoted from the cited guides — facts, not folklore.*")
        for k in m["knots"]:
            q = next((c["quote"] for c in k.get("citations", []) if c.get("quote")), "")
            src = next((c["source"] for c in k.get("citations", []) if c.get("quote")), "")
            conn = k.get("connection")
            conn = ", ".join(conn) if isinstance(conn, list) else (conn or "")
            extra = "" if k.get("mine", True) else " — *not in your repertoire; worth learning*"
            L.append(f"- **{k['label']}**" + (f" ({conn})" if conn else "")
                     + (f" — {q}" if q else "") + (f" *({src})*" if src else "") + extra)
        if m.get("knot_notes"):
            L.append("*Practice: " + "; ".join(m["knot_notes"]) + ".*")
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
               wind_dir=m["weather"]["start"].get("dir"),
               water_f=m["weather"].get("water_f"), month=m["start"].month,
               water_trend=m.get("water_trend"),
               moon_fruitful=(m["moon_note"]["fruitful"] if m["moon_note"] else None),
               pressure_word=m["weather"]["score"]["trend"]["word"],
               structure_notes=m["lake"].get("structure", []),
               lake_key=m["lake"].get("id"), shoreline=m.get("shoreline"),
               lake_state=m.get("lake_state"))
    L.append(f"## {e('🧠 ')}Decision rules")
    for r in tx.decision_rules(ctx, [c["label"] for c in m["rods"]]):
        if voice == "fisher":
            r = r.replace("barren-sign evenings backload — the payoff window is late",
                          "slow starts backload the payoff window on dark moons")
        L.append(f"- {r}")
    if m.get("shoreline"):
        L.append("*(shoreline wind model — © OpenStreetMap contributors, ODbL)*")
    for lore in m["lake"].get("lore", [])[:2]:
        L.append(f"- Lake lore: {lore}")
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
