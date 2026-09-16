"""Astronomy layer — Swiss Ephemeris (bundled with kerykeion's venv).

Convention: all public datetimes are NAIVE LOCAL (lake tz). Internally we work
in Julian Days (UT) using utc_offset_seconds. Geopos order for pyswisseph is
(longitude, latitude, altitude).
"""
from __future__ import annotations
import math
import os
from datetime import datetime, timedelta

import swisseph as swe
import kerykeion

swe.set_ephe_path(os.path.join(os.path.dirname(kerykeion.__file__), "sweph"))

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
         "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
SYM = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"]
ABBR = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]

PLANETS = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
           "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
           "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
           "Pluto": swe.PLUTO}

# Chaldean order — hour rulers advance through this list cyclically
CHALDEAN = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
DAY_RULER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]  # Mon-first below


def day_ruler(d: datetime) -> str:
    """Planetary day ruler. d = local date (weekday: Mon=0)."""
    return ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"][d.weekday()]


def phase_name(elong: float) -> str:
    e = elong % 360
    for lo, hi, name in [(337.5, 360, "Balsamic (dark) moon"), (0, 22.5, "New moon"),
                         (22.5, 67.5, "Waxing crescent"), (67.5, 112.5, "First quarter"),
                         (112.5, 157.5, "Waxing gibbous"), (157.5, 202.5, "Full moon"),
                         (202.5, 247.5, "Waning gibbous"), (247.5, 292.5, "Last quarter"),
                         (292.5, 337.5, "Waning crescent")]:
        if lo <= e < hi:
            return name
    return "New moon"


def illum_pct(elong: float) -> float:
    return (1 - math.cos(math.radians(elong % 360))) / 2 * 100


def planet_lon(jd: float, name: str) -> tuple[float, float]:
    """(ecliptic lon, lon speed deg/day)"""
    (lon, _lat, _dist, lsp, *_), _ = swe.calc_ut(jd, PLANETS[name],
                                                 swe.FLG_SWIEPH | swe.FLG_SPEED)
    return lon % 360, lsp


def fmt_sign(lon: float, symbols: bool = True) -> str:
    lon %= 360
    i = int(lon // 30)
    d = lon - i * 30
    sym = f"{SYM[i]} " if symbols else ""
    return f"{sym}{ABBR[i]} {int(d):2d}°{int(round((d - int(d)) * 60)):02d}"


class Sky:
    _sun_cache: dict = {}
    _ph_cache: dict = {}

    def __init__(self, lng: float, lat: float, alt_m: float, utc_offset_sec: int):
        self.geo = (lng, lat, alt_m)
        self.off = utc_offset_sec / 86400.0

    # ── time conversions ─────────────────────────────────────────────────
    def jd(self, local: datetime) -> float:
        """naive local -> JD(UT)."""
        ut = local - timedelta(seconds=self.off * 86400)
        return swe.julday(ut.year, ut.month, ut.day,
                          ut.hour + ut.minute / 60 + ut.second / 3600)

    def loc(self, jd: float) -> datetime:
        y, m, d, h = swe.revjul(jd)
        ut = datetime(y, m, d) + timedelta(hours=h)
        return ut + timedelta(seconds=self.off * 86400)

    # ── sun ──────────────────────────────────────────────────────────────
    def sun_rise_set(self, after_local: datetime) -> tuple[datetime, datetime]:
        """Next (sunrise, sunset) strictly after `after_local`."""
        jd0 = self.jd(after_local)
        rise = swe.rise_trans(jd0, swe.SUN, swe.CALC_RISE, self.geo)[1][0]
        sett = swe.rise_trans(jd0, swe.SUN, swe.CALC_SET, self.geo)[1][0]
        return self.loc(rise), self.loc(sett)

    def sun_alt(self, jd: float) -> float:
        lon, _ = planet_lon(jd, "Sun")
        return swe.azalt(jd, swe.ECL2HOR, self.geo, 0, 0, (lon, 0.0, 1.0))[1]

    def sun_events_for_day(self, local_date: datetime) -> dict:
        """Sunrise/sunset/civil-twilights for the local date containing local_date.
        Memoized per (site, local day): the ledger scans the same day many times."""
        midnight = local_date.replace(hour=0, minute=0, second=0, microsecond=0)
        key = (self.geo, round(self.off, 9), midnight)
        hit = Sky._sun_cache.get(key)
        if hit is not None:
            return hit
        jd0 = self.jd(midnight)
        rise = swe.rise_trans(jd0, swe.SUN, swe.CALC_RISE, self.geo)[1][0]
        sett = swe.rise_trans(jd0, swe.SUN, swe.CALC_SET, self.geo)[1][0]
        cd = self._alt_crossing(jd0, -6.0, downward=True)      # evening civil dusk
        cn = self._alt_crossing(jd0, -6.0, downward=False)     # morning civil dawn
        out = dict(sunrise=self.loc(rise), sunset=self.loc(sett),
                   civil_dusk=self.loc(cd), civil_dawn=self.loc(cn))
        if len(Sky._sun_cache) > 1024:
            Sky._sun_cache.clear()
        Sky._sun_cache[key] = out
        return out

    def _alt_crossing(self, jd_start: float, target: float, downward: bool) -> float:
        step = 1 / 48  # 30 min
        jd = jd_start
        prev = self.sun_alt(jd)
        for _ in range(200):
            nxt = jd + step
            cur = self.sun_alt(nxt)
            crossed = (prev - target) * (cur - target) < 0
            going_down = prev > cur
            if crossed and (going_down == downward):
                a, b = jd, nxt
                for _ in range(50):
                    m = (a + b) / 2
                    if (self.sun_alt(a) - target) * (self.sun_alt(m) - target) <= 0:
                        b = m
                    else:
                        a = m
                return (a + b) / 2
            prev, jd = cur, nxt
        return jd_start + 0.5

    def light_level(self, jd: float) -> tuple[str, float]:
        alt = self.sun_alt(jd)
        if alt >= 30: return "bright day", alt
        if alt >= 12: return "moderate day", alt
        if alt >= 2: return "golden", alt
        if alt >= -0.8: return "sunset/sunrise", alt
        if alt >= -6: return "dusk/dawn", alt
        return "night", alt

    # ── moon ─────────────────────────────────────────────────────────────
    def moon_rise_set(self, after_local: datetime) -> tuple[datetime | None, datetime | None]:
        jd0 = self.jd(after_local)
        try:
            rise = swe.rise_trans(jd0, swe.MOON, swe.CALC_RISE, self.geo)[1][0]
        except Exception:
            rise = None
        try:
            sett = swe.rise_trans(jd0, swe.MOON, swe.CALC_SET, self.geo)[1][0]
        except Exception:
            sett = None
        return (self.loc(rise) if rise else None, self.loc(sett) if sett else None)

    def moon_alt(self, jd: float) -> float:
        lon, _ = planet_lon(jd, "Moon")
        return swe.azalt(jd, swe.ECL2HOR, self.geo, 0, 0, (lon, 0.0, 1.0))[1]

    def moon_transits(self, center_local: datetime, span_days: float = 1.5) -> list[tuple[datetime, float]]:
        """(time, altitude) of upper & lower culminations near center_local."""
        jd0, jd1 = self.jd(center_local) - span_days / 2, self.jd(center_local) + span_days / 2
        step = 1 / 96  # 15 min
        out, jd = [], jd0
        prev_alt = self.moon_alt(jd)
        prev_slope = None
        while jd < jd1:
            alt = self.moon_alt(jd + step)
            slope = alt - prev_alt
            if prev_slope is not None and slope * prev_slope < 0:
                a, b = jd, jd + step
                for _ in range(50):  # golden-section on |slope|
                    m1, m2 = a + (b - a) / 3, b - (b - a) / 3
                    f1 = abs(self.moon_alt(m1 + 1e-4) - self.moon_alt(m1))
                    f2 = abs(self.moon_alt(m2 + 1e-4) - self.moon_alt(m2))
                    a, b = (m1, b) if f1 > f2 else (a, m2)
                t = (a + b) / 2
                out.append((self.loc(t), self.moon_alt(t)))
            prev_alt, prev_slope, jd = alt, slope, jd + step
        return out

    def moon_state(self, jd: float) -> dict:
        mlon, _ = planet_lon(jd, "Moon")
        slon, _ = planet_lon(jd, "Sun")
        elong = (mlon - slon) % 360
        return dict(lon=mlon, sign=SIGNS[int(mlon // 30)], elong=elong,
                    phase=phase_name(elong), illum=illum_pct(elong))

    def moon_ingress(self, jd: float, max_days: float = 2.5) -> datetime | None:
        """When the Moon next changes sign after jd."""
        target = (int(planet_lon(jd, "Moon")[0] // 30) + 1) % 12 * 30
        a, b = jd, jd + max_days
        for _ in range(60):
            m = (a + b) / 2
            lon, _ = planet_lon(m, "Moon")
            phase = (lon - target) % 360
            if phase > 180:  # not yet reached target
                a = m
            else:
                b = m
        return self.loc((a + b) / 2)

    # ── solunar ──────────────────────────────────────────────────────────
    def solunar(self, date_local: datetime) -> list[dict]:
        """Majors (moon overhead/underfoot ±1h) and minors (rise/set ±45m)."""
        events = []
        for t, alt in self.moon_transits(date_local):
            which = "overhead" if alt > 0 else "underfoot"
            events.append(dict(kind="major", label=f"Moon {which} (major)",
                               start=t - timedelta(minutes=60),
                               end=t + timedelta(minutes=60), peak=t))
        rise, sett = self.moon_rise_set(date_local.replace(hour=0, minute=0))
        for t, lab in ((rise, "Moonrise (minor)"), (sett, "Moonset (minor)")):
            if t:
                events.append(dict(kind="minor", label=lab,
                                   start=t - timedelta(minutes=45),
                                   end=t + timedelta(minutes=45), peak=t))
        return [e for e in events if abs((e["peak"] - date_local).total_seconds()) < 36 * 3600]

    # ── planetary hours ──────────────────────────────────────────────────
    def planetary_hours(self, date_local: datetime) -> list[dict]:
        """Hour spans covering date_local's day ±1 day (unbroken Chaldean
        sequence; day ruler rules hour 1 at sunrise). Memoized per (site, day)."""
        d0 = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
        key = (self.geo, round(self.off, 9), d0)
        hit = Sky._ph_cache.get(key)
        if hit is not None:
            return hit
        spans = []
        for delta in (-1, 0, 1):
            d = d0 + timedelta(days=delta)
            ev = self.sun_events_for_day(d)
            sr, ss = ev["sunrise"], ev["sunset"]
            nxt = self.sun_events_for_day(d + timedelta(days=1))["sunrise"]
            ruler = day_ruler(d)
            idx = CHALDEAN.index(ruler)
            day_len = (ss - sr).total_seconds() / 12
            night_len = (nxt - ss).total_seconds() / 12
            for i in range(12):  # day hours
                r = CHALDEAN[(idx + i) % 7]
                spans.append(dict(start=sr + timedelta(seconds=i * day_len),
                                  end=sr + timedelta(seconds=(i + 1) * day_len),
                                  ruler=r, kind="day", number=i + 1))
            for i in range(12):  # night hours
                r = CHALDEAN[(idx + 12 + i) % 7]
                spans.append(dict(start=ss + timedelta(seconds=i * night_len),
                                  end=ss + timedelta(seconds=(i + 1) * night_len),
                                  ruler=r, kind="night", number=i + 1))
        spans.sort(key=lambda s: s["start"])
        if len(Sky._ph_cache) > 512:
            Sky._ph_cache.clear()
        Sky._ph_cache[key] = spans
        return spans

    def hour_at(self, dt_local: datetime) -> dict:
        for h in self.planetary_hours(dt_local):
            if h["start"] <= dt_local < h["end"]:
                return dict(h)   # copy — cached spans are shared
        return dict(start=dt_local, end=dt_local + timedelta(hours=1), ruler="?",
                    kind="night", number=0)

    # ── legal access window (registry access rules) ────────────────────
    def access_window(self, day, access_cfg: dict | None):
        """(open_dt, close_dt, note) from registry offsets vs sunrise/sunset.
        Summer variant via summer_dates ['MM-DD','MM-DD']. None if no rule."""
        from datetime import timedelta
        if not access_cfg:
            return None
        summer = False
        if access_cfg.get("summer_dates"):
            mmdd = day.strftime("%m-%d")
            a, b = access_cfg["summer_dates"]
            summer = a <= mmdd <= b
        o = access_cfg.get("summer_open_offset_min" if summer else "open_offset_min", 30)
        c = access_cfg.get("summer_close_offset_min" if summer else "close_offset_min", 30)
        ev = self.sun_events_for_day(day)
        return (ev["sunrise"] - timedelta(minutes=o),
                ev["sunset"] + timedelta(minutes=c),
                ("summer hours" if summer else "standard hours")
                + f" (±{o} min sunrise / +{c} min sunset)")

    # ── moon overhead for solunar rating ─────────────────────────────────
    def phase_quality(self, jd: float) -> tuple[float, str]:
        """0..1 bonus + label — dark & full moons score best (solunar lore)."""
        e = self.moon_state(jd)["elong"]
        dist_new = min(e, 360 - e)
        dist_full = abs(e - 180)
        if dist_new <= 45:
            return 1.0, "dark-moon window (solunar peak)"
        if dist_full <= 45:
            return 1.0, "full-moon window (solunar peak)"
        if min(dist_new, dist_full) <= 80:
            return 0.6, "near-quarter moon (transition)"
        return 0.3, "off-quarter moon (neutral)"
