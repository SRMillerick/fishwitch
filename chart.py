"""Astrology layer — natal chart (kerykeion/Swiss Ephemeris), live transits
against the angler's chart, void-of-course moon, dignities, hour meanings.

Almanac framing is honored but always labeled: fruitful/barren moon signs are
traditional lore, presented alongside the computed chart data.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kerykeion import AstrologicalSubject
from fishwitch.skycalc import (Sky, SIGNS, SYM, ABBR, planet_lon, fmt_sign,
                        phase_name, illum_pct)

BODIES = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
          "Uranus", "Neptune", "Pluto"]
ANGLES = ["Asc", "MC"]

ASPECTS = [("conjunction", 0, "☌"), ("sextile", 60, "⚹"), ("square", 90, "□"),
           ("trine", 120, "△"), ("opposition", 180, "☍")]

# almanac lore: which moon signs "feed"
FRUITFUL = {"Cancer": "fruitful", "Scorpio": "fruitful", "Pisces": "fruitful",
            "Taurus": "semi-fruitful", "Libra": "semi-fruitful", "Capricorn": "semi-fruitful"}
BARREN = {"Aries", "Gemini", "Leo", "Virgo", "Sagittarius", "Aquarius"}

SIGN_QUIPS = {
    "Cancer": "moon at home — feeding near cover, tides of appetite run strong",
    "Scorpio": "deep-water hunters on the prowl — fish the breaks and drop-offs",
    "Pisces": "the Fish rules — the classic 'dream bite' sign",
    "Taurus": "steady feeders — slow, deliberate presentations win",
    "Libra": "balanced bite — finesse over force",
    "Capricorn": "structured feeders — work the main-lake structure patiently",
    "Aries": "spooky, quick strikes — reaction baits, fast moves",
    "Gemini": "scattered fish — cover water, expect schools not singles",
    "Leo": "proud and picky — match the hatch precisely",
    "Virgo": "barren sign in the old lore — quality over quantity, perfectionist finesse",
    "Sagittarius": "roamers — long casts to wandering fish",
    "Aquarius": "unpredictable — try what nobody else is throwing",
}

HOUR_MEANINGS = {
    "Sun": "visibility — fish the water you can see, stand tall on the bow",
    "Moon": "quiet intuition — slow down, feel the subtle takes",
    "Mercury": "skillful hands — knots, skips and hooksets are dialed",
    "Venus": "pleasure & luck through finesse — savor it, fish pretty",
    "Mars": "aggression — burn reaction baits, set the hook hard",
    "Jupiter": "big fortune — make the big cast, hunt the kicker fish",
    "Saturn": "the grind — methodical, thorough, slow-work every piece of structure",
}

DIGNITY = {
    ("Sun", "Leo"): "domicile", ("Moon", "Cancer"): "domicile",
    ("Mercury", "Gemini"): "domicile", ("Mercury", "Virgo"): "domicile",
    ("Venus", "Taurus"): "domicile", ("Venus", "Libra"): "domicile",
    ("Mars", "Aries"): "domicile", ("Mars", "Scorpio"): "domicile",
    ("Jupiter", "Sagittarius"): "domicile", ("Jupiter", "Pisces"): "domicile",
    ("Saturn", "Capricorn"): "domicile", ("Saturn", "Aquarius"): "domicile",
    ("Sun", "Aries"): "exalted", ("Moon", "Taurus"): "exalted",
    ("Mercury", "Virgo"): "exalted", ("Venus", "Pisces"): "exalted",
    ("Mars", "Capricorn"): "exalted", ("Jupiter", "Cancer"): "exalted",
    ("Saturn", "Libra"): "exalted",
}
# fall = sign opposite the exaltation sign; detriment = sign opposite the domicile
FALL_OF = {"Libra": "Sun", "Scorpio": "Moon", "Pisces": "Mercury", "Virgo": "Venus",
           "Cancer": "Mars", "Capricorn": "Jupiter", "Aries": "Saturn"}
DETRIMENT_OF = {"Aquarius": "Sun", "Capricorn": "Moon", "Sagittarius": "Mercury",
                "Pisces": "Mercury", "Scorpio": "Venus", "Aries": "Venus",
                "Libra": "Mars", "Taurus": "Mars", "Gemini": "Jupiter",
                "Virgo": "Jupiter", "Cancer": "Saturn", "Leo": "Saturn"}


class NatalChart:
    def __init__(self, birth: dict):
        """birth = {name, date:'YYYY-MM-DD', time:'HH:MM'|None, time_known:bool,
                   place:str, lat, lng, tz}"""
        self.birth = birth
        t = birth.get("time") or "12:00"
        hh, mm = map(int, t.split(":"))
        y, mo, d = map(int, birth["date"].split("-"))
        local = datetime(y, mo, d, hh, mm, tzinfo=ZoneInfo(birth["tz"]))
        self.birth_local = local
        subj = AstrologicalSubject(birth.get("name", "Angler"), y, mo, d, hh, mm,
                                   city=birth.get("place", "?").split(",")[0],
                                   nation=birth.get("country", ""),
                                   lng=birth["lng"], lat=birth["lat"],
                                   tz_str=birth["tz"], online=False)
        self.points = {}
        for b in BODIES:
            self.points[b] = getattr(subj, b.lower()).abs_pos % 360
        self.points["Asc"] = subj.first_house.abs_pos % 360
        self.points["MC"] = subj.tenth_house.abs_pos % 360
        # natal lunar phase
        self.natal_elong = (self.points["Moon"] - self.points["Sun"]) % 360
        self.natal_phase = phase_name(self.natal_elong)
        self.natal_illum = illum_pct(self.natal_elong)
        # sect: sun above horizon at birth?
        sky = Sky(birth["lng"], birth["lat"], 50, 
                  int(local.utcoffset().total_seconds()))
        self.sun_alt_birth = sky.sun_alt(sky.jd(local.replace(tzinfo=None)))
        self.sect = "day" if self.sun_alt_birth > 0 else "night"
        self.time_known = birth.get("time_known", True)

    def dignity_notes(self, symbols: bool = True) -> list[str]:
        out = []
        for p in ("Sun", "Moon", "Venus", "Jupiter"):
            sign = SIGNS[int(self.points[p] // 30)]
            if DIGNITY.get((p, sign)) in ("domicile", "exalted"):
                mark = f" ({SYM[SIGNS.index(sign)]})" if symbols else ""
                out.append(f"natal {p} {DIGNITY[(p, sign)]} in {sign}{mark} — a chart strength")
        for p in ("Sun", "Moon", "Venus"):
            sign = SIGNS[int(self.points[p] // 30)]
            if DETRIMENT_OF.get(sign) == p:
                out.append(f"natal {p} in detriment in {sign} — works against the grain; patience")
            elif FALL_OF.get(sign) == p:
                out.append(f"natal {p} in fall in {sign} — humility bait works")
        return out

    def house_of(self, lon: float) -> int:
        """Whole-sign house of any ecliptic longitude relative to natal Asc."""
        return (int(lon // 30) - int(self.points["Asc"] // 30)) % 12 + 1


# ── transits ───────────────────────────────────────────────────────────────
def _sep(t_lon, n_lon):
    """signed angular separation t-n in (-180,180]."""
    return ((t_lon - n_lon + 180) % 360) - 180


def transit_aspects(natal: NatalChart, jd: float,
                    window_hours: float = 3.0) -> list[dict]:
    """Transit→natal aspects near jd. Each dict: planets, aspect, orb,
    applying, perfect_jd (if it perfects within the window, scan-refined)."""
    out = []
    win = window_hours / 24

    def g(tp, n_lon, angle, t):
        """wrap-safe signed distance from exact aspect, in (-180,180]."""
        lon, _ = planet_lon(t, tp)
        return (((lon - n_lon - angle) + 180) % 360) - 180

    for tp in BODIES:
        for np_ in BODIES + ANGLES:
            if tp == np_:
                continue
            n_lon = natal.points[np_]
            for name, angle, sym in ASPECTS:
                g0 = g(tp, n_lon, angle, jd)
                orb = abs(g0)
                max_orb = 4.0 if tp in ("Moon", "Sun") else 3.0
                if orb > max_orb:
                    continue
                # scan forward for the wrap-safe zero crossing
                perfect = None
                horizon = jd + win + 0.5
                step = 0.25 / 24
                t_prev, g_prev = jd, g0
                t = jd
                while t < horizon:
                    t += step
                    g_cur = g(tp, n_lon, angle, t)
                    if g_prev * g_cur <= 0 and abs(g_prev) < 45 and abs(g_cur) < 45:
                        a, b, fa = t_prev, t, g_prev
                        for _ in range(60):
                            m = (a + b) / 2
                            fm = g(tp, n_lon, angle, m)
                            if fa * fm <= 0:
                                b = m
                            else:
                                a, fa = m, fm
                        perfect = (a + b) / 2
                        break
                    t_prev, g_prev = t, g_cur
                    if t - jd > 2.0 and perfect is None and orb > 2.5:
                        break  # slow body far from exact — don't scan forever
                # applying = orb shrinking over the next hour
                g1 = g(tp, n_lon, angle, jd + 1 / 24)
                out.append(dict(transit=tp, natal=np_, aspect=name, sym=sym,
                                orb=round(orb, 2), applying=abs(g1) < abs(g0),
                                perfect_jd=perfect))
    out.sort(key=lambda a: (a["perfect_jd"] is None, a["orb"]))
    return out


def voc_moon(jd: float, sky: Sky, horizon_hours: float = 36) -> dict:
    """Is the Moon void-of-course? (no Ptolemaic aspect before leaving sign)."""
    moon_lon, _ = planet_lon(jd, "Moon")
    ingress = sky.jd(sky.moon_ingress(jd))
    # scan forward for any aspect perfection before ingress
    step = 2 / 24
    t = jd
    prev = {p: _sep(planet_lon(jd, "Moon")[0], planet_lon(jd, p)[0]) for p in BODIES if p != "Moon"}
    while t < min(ingress, jd + horizon_hours / 24):
        t += step
        cur = {p: _sep(planet_lon(t, "Moon")[0], planet_lon(t, p)[0]) for p in BODIES if p != "Moon"}
        for p, s in cur.items():
            for _n, angle, sym in ASPECTS:
                if angle == 0 and p == "Sun" and False:
                    continue
                g0 = prev[p] - angle
                g1 = s - angle
                if abs(g0 - g1) > 180:  # wrapped
                    continue
                if g0 * g1 <= 0 and abs(g0) < 60:
                    a, b = t - step, t
                    for _ in range(50):
                        m = (a + b) / 2
                        gm = _sep(planet_lon(m, "Moon")[0],
                                  planet_lon(m, p)[0]) - angle
                        g_a = _sep(planet_lon(a, "Moon")[0],
                                   planet_lon(a, p)[0]) - angle
                        if g_a * gm <= 0:
                            b = m
                        else:
                            a = m
                    pjd = (a + b) / 2
                    if pjd > jd:
                        return dict(void=False, ends=None,
                                    next_aspect=f"{sym} {p} at {sky.loc(pjd):%H:%M}",
                                    note="moon is applying — the schedule holds")
        prev = cur
    return dict(void=True, ends=sky.loc(ingress),
                next_aspect=None,
                note=f"void-of-course until Moon enters the next sign at {sky.loc(ingress):%H:%M} — 'nothing comes of it' hours; keep casting anyway")


def moon_note(jd: float) -> dict:
    lon, _ = planet_lon(jd, "Moon")
    sign = SIGNS[int(lon // 30)]
    fruit = FRUITFUL.get(sign, "barren")
    return dict(sign=sign, sym=SYM[SIGNS.index(sign)], lon=lon, fmt=fmt_sign(lon),
                fmt_plain=fmt_sign(lon, symbols=False),
                fruitful=fruit,
                quip=SIGN_QUIPS[sign],
                lore=f"{sign} is a {fruit} sign in the almanac tradition")


def phase_resonance(natal: NatalChart, jd: float) -> str | None:
    """Does tonight's lunar phase echo the angler's natal phase?"""
    elong = (planet_lon(jd, "Moon")[0] - planet_lon(jd, "Sun")[0]) % 360
    diff = min((elong - natal.natal_elong) % 360,
               (natal.natal_elong - elong) % 360)
    if diff <= 40:
        return (f"tonight's moon phase ({phase_name(elong)}) mirrors your natal "
                f"{natal.natal_phase} — you were born under this moon-shape")
    return None
