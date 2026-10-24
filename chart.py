"""Astrology layer — natal chart (kerykeion/Swiss Ephemeris), live transits
against the angler's chart, void-of-course moon, dignities, hour meanings.

Almanac framing is honored but always labeled: fruitful/barren moon signs are
traditional lore, presented alongside the computed chart data.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError
import math
import re

from kerykeion import AstrologicalSubjectFactory
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


def precise_birth(birth: dict | None) -> bool:
    """Require a clock time; honor unknown precision, including legacy profiles."""
    return bool(birth and birth.get("time") and birth.get("time_known", True) is True)


def normalize_birth(raw: dict) -> dict:
    """One validation contract for legacy profiles and canonical forecasts."""
    if not isinstance(raw, dict):
        raise ValueError("birth: expected an object")
    result = {}
    date = raw.get("date")
    try:
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError
        parsed = datetime.strptime(date, "%Y-%m-%d")
        if not 1850 <= parsed.year <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("birth.date: YYYY-MM-DD between 1850 and 2100") from None
    result["date"] = date
    known = raw.get("time_known", True)
    if type(known) is not bool:
        raise ValueError("birth.time_known: boolean")
    result["time_known"] = known
    clock = raw.get("time")
    if known:
        try:
            if not isinstance(clock, str) or not re.fullmatch(r"\d{2}:\d{2}", clock):
                raise ValueError
            datetime.strptime(clock, "%H:%M")
        except (TypeError, ValueError):
            raise ValueError("birth.time: HH:MM (24h)") from None
    result["time"] = clock if known else None
    for field, lo, hi in (("lat", -90, 90), ("lng", -180, 180)):
        try:
            value = float(raw[field])
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ValueError(f"birth.{field}: a resolved coordinate between {lo} and {hi} is required") from None
        result[field] = value
    tz = raw.get("tz")
    try:
        if not isinstance(tz, str) or not tz or len(tz) > 64:
            raise ValueError
        ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("birth.tz: a resolved IANA timezone is required") from None
    result["tz"] = tz
    place = raw.get("place")
    if place is not None:
        if not isinstance(place, str) or len(place) > 120:
            raise ValueError("birth.place: string up to 120 characters")
        result["place"] = place.strip()
    if known:
        birth_datetime(result)
    return result


def birth_datetime(birth: dict) -> datetime:
    """Resolve the historical offset; reject clock gaps and unresolved folds."""
    if not precise_birth(birth):
        raise ValueError("birth.time: a known birth time is required")
    local = datetime.fromisoformat(f"{birth['date']}T{birth['time']}")
    if local.tzinfo is not None:
        raise ValueError("birth.time: use local HH:MM without an offset")
    zone = ZoneInfo(birth["tz"])
    choices = []
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == local:
            if not choices or candidate.utcoffset() != choices[0].utcoffset():
                choices.append(candidate)
    if not choices:
        raise ValueError("birth.time: this local time did not exist; check the clock time")
    if len(choices) > 1:
        raise ValueError("birth.time: ambiguous local time; confirm the time or use shared-only")
    return choices[0]


class NatalChart:
    def __init__(self, birth: dict):
        """birth = {name, date:'YYYY-MM-DD', time:'HH:MM'|None, time_known:bool,
                   place:str, lat, lng, tz}"""
        local = birth_datetime(birth)
        self.birth = birth
        self.birth_local = local
        # Resolve once with ZoneInfo, then give Kerykeion that exact UTC instant.
        # Historical offsets can include seconds, which the old wall-time/pytz
        # compatibility wrapper rounded differently. The pinned factory accepts
        # seconds and avoids a second, potentially different timezone resolution.
        utc = local.astimezone(timezone.utc)
        subj = AstrologicalSubjectFactory.from_birth_data(
            birth.get("name", "Angler"), utc.year, utc.month, utc.day, utc.hour, utc.minute,
            seconds=utc.second, city=birth.get("place", "?").split(",")[0],
            nation=birth.get("country", ""), lng=birth["lng"], lat=birth["lat"],
            tz_str="Etc/UTC", online=False, active_points=BODIES + ["Ascendant", "Medium_Coeli"],
            calculate_lunar_phase=False)
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
        self.time_known = True

    def dignity_notes(self, symbols: bool = True) -> list[str]:
        out = []
        for p in ("Sun", "Moon", "Venus", "Jupiter"):
            sign = SIGNS[int(self.points[p] // 30)]
            if DIGNITY.get((p, sign)) in ("domicile", "exalted"):
                mark = f" ({SYM[SIGNS.index(sign)]})" if symbols else ""
                out.append(f"natal {p} {DIGNITY[(p, sign)]} in {sign}{mark} — a chart strength")
        for p in ("Sun", "Moon", "Venus"):
            sign = SIGNS[int(self.points[p] // 30)]
            mark = f" ({SYM[SIGNS.index(sign)]})" if symbols else ""
            if DETRIMENT_OF.get(sign) == p:
                out.append(f"natal {p} in detriment in {sign}{mark} — works against the grain; patience")
            elif FALL_OF.get(sign) == p:
                out.append(f"natal {p} in fall in {sign}{mark} — humility bait works")
        return out

    def house_of(self, lon: float) -> int:
        """Whole-sign house of any ecliptic longitude relative to natal Asc."""
        return (int(lon // 30) - int(self.points["Asc"] // 30)) % 12 + 1


# ── transits ───────────────────────────────────────────────────────────────
def _sep(t_lon, n_lon):
    """signed angular separation t-n in (-180,180]."""
    return ((t_lon - n_lon + 180) % 360) - 180


def _aspect_delta(t_lon: float, n_lon: float, angle: float) -> float:
    """Signed error to the nearer orientation of an undirected aspect."""
    return min((_sep(t_lon, n_lon + angle), _sep(t_lon, n_lon - angle)), key=abs)


def transit_aspects(natal: NatalChart, jd: float,
                    window_hours: float = 3.0) -> list[dict]:
    """Transit→natal aspects near jd. Each dict: planets, aspect, orb,
    applying, perfect_jd (if it perfects within the window, scan-refined)."""
    if not natal.time_known:
        return []
    out = []
    win = window_hours / 24

    def g(tp, n_lon, angle, t):
        """wrap-safe signed distance from exact aspect, in (-180,180]."""
        lon, _ = planet_lon(t, tp)
        return _aspect_delta(lon, n_lon, angle)

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
                horizon = jd + win
                step = 0.25 / 24
                t_prev, g_prev = jd, g0
                t = jd
                while t < horizon:
                    t = min(t + step, horizon)
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
                        root = t if g_cur == 0 else (t_prev if g_prev == 0 else (a + b) / 2)
                        # Exact perfections use [start, end), including launch.
                        if jd <= root < horizon and abs(g(tp, n_lon, angle, root)) < 1e-7:
                            perfect = root
                        break
                    t_prev, g_prev = t, g_cur
                    if t - jd > 2.0 and perfect is None and orb > 2.5:
                        break  # slow body far from exact — don't scan forever
                # applying = orb shrinking over the next hour
                g1 = g(tp, n_lon, angle, jd + 1 / 24)
                out.append(dict(transit=tp, natal=np_, aspect=name, sym=sym,
                                orb=orb, applying=abs(g1) < abs(g0),
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
        t_prev = t
        t = min(t + step, ingress, jd + horizon_hours / 24)
        cur = {p: _sep(planet_lon(t, "Moon")[0], planet_lon(t, p)[0]) for p in BODIES if p != "Moon"}
        for p, s in cur.items():
            for _n, angle, sym in ASPECTS:
                g0 = _aspect_delta(prev[p], 0, angle)
                g1 = _aspect_delta(s, 0, angle)
                if abs(g0) >= 45 or abs(g1) >= 45:
                    continue
                if g0 * g1 <= 0:
                    a, b = t_prev, t
                    for _ in range(50):
                        m = (a + b) / 2
                        gm = _aspect_delta(planet_lon(m, "Moon")[0],
                                           planet_lon(m, p)[0], angle)
                        g_a = _aspect_delta(planet_lon(a, "Moon")[0],
                                            planet_lon(a, p)[0], angle)
                        if g_a * gm <= 0:
                            b = m
                        else:
                            a = m
                    pjd = (a + b) / 2
                    if jd < pjd < ingress:
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
    if not natal.time_known:
        return None
    elong = (planet_lon(jd, "Moon")[0] - planet_lon(jd, "Sun")[0]) % 360
    diff = min((elong - natal.natal_elong) % 360,
               (natal.natal_elong - elong) % 360)
    if diff <= 40:
        return (f"tonight's moon phase ({phase_name(elong)}) mirrors your natal "
                f"{natal.natal_phase} — you were born under this moon-shape")
    return None
