"""Canonical personal-window calculation. No network or wall-clock reads.

All intervals are UTC, half-open, and retain precision until presentation.
Acquisition belongs in forecast_weather.py; neither report.py nor layers/ is
part of this path. Policy window-1 implements PRODUCT_RESET.md §12 as approved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
import importlib.metadata
import math
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe
from fishwitch.chart import NatalChart, birth_datetime, normalize_birth
from fishwitch import reading as reading_engine
from fishwitch.skycalc import Sky, PLANETS

UTC = timezone.utc
RULE_VERSION = "window-1"
CALC_VERSION = "window-calc-1"
BACKEND = swe.FLG_MOSEPH  # Explicit existing backend; never an implicit fallback.
MAX_CANDIDATES = 1024
GRID = timedelta(minutes=30)
SCAN = timedelta(minutes=15)
FRESH_FOR = timedelta(minutes=30)
ASPECTS = (("sextile", 60, 1), ("trine", 120, 1),
           ("square", 90, -1), ("opposition", 180, -1))
NATAL_BODIES = ("Moon", "Venus", "Jupiter")


class InputError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class CalculationError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("Expected an increasing interval with explicit timezone")


@dataclass(frozen=True)
class Water:
    id: str
    name: str
    lat: float
    lng: float
    tz: str
    altitude: float
    access: dict


@dataclass(frozen=True)
class ForecastRequest:
    water: Water
    availability: tuple[Interval, ...]
    duration: timedelta
    daylight: bool
    birth: dict | None
    precision: str
    evaluated_at: datetime
    request_id: str


@dataclass(frozen=True)
class WeatherHour:
    start: datetime
    wind_mph: float | None
    gust_mph: float | None
    precipitation_mm: float | None
    code: int | None
    temperature_f: float | None


@dataclass(frozen=True)
class WeatherSnapshot:
    lat: float
    lng: float
    acquired_at: datetime
    hours: tuple[WeatherHour, ...]
    provider: str = "open-meteo-forecast-v1"


@dataclass(frozen=True)
class SharedEvent:
    kind: str
    interval: Interval
    exact: datetime


@dataclass(frozen=True)
class PersonalEvent:
    rule: str
    body: str
    aspect: str
    exact: datetime
    contribution: int


@dataclass(frozen=True)
class SkyData:
    feasible: tuple[Interval, ...]
    shared: tuple[SharedEvent, ...]
    personal: tuple[PersonalEvent, ...]
    environment: dict
    # Natal longitudes, present only when a birth chart was actually built.
    points: dict | None = None


@dataclass(frozen=True)
class Session:
    interval: Interval
    band: int
    personal: int
    events: tuple[PersonalEvent, ...]
    shared_events: tuple[SharedEvent, ...]
    major_seconds: float
    minor_seconds: float
    gust_mph: float
    wind_mph: float
    precipitation_mm: float
    max_rain_mm: float
    temperature_f: float | None

    @property
    def rank(self):
        return (self.band, -self.personal, -self.major_seconds, -self.minor_seconds,
                self.gust_mph, self.precipitation_mm, self.interval.start)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("An explicit evaluation timezone is required")
    return value.astimezone(UTC)


def resolve_local(value: str, zone: ZoneInfo, field: str) -> datetime:
    try:
        if not isinstance(value, str) or "T" not in value:
            raise ValueError
        local = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise InputError(field, "Choose a valid date and local time.") from None
    if local.tzinfo is not None:
        # Explicit offsets can resolve a fold, but must agree with this water.
        if local.utcoffset() != local.astimezone(zone).utcoffset():
            raise InputError(field, "The UTC offset does not match the water's timezone.")
        return local.astimezone(UTC)
    choices = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold)
        utc = candidate.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            choices.add(utc)
    if not choices:
        raise InputError(field, "This clock time does not exist during the daylight-saving change. Choose another time.")
    if len(choices) != 1:
        raise InputError(field, "This clock time occurs twice. Choose another time or specify the confirmed UTC offset.")
    return choices.pop()


def merge_intervals(intervals) -> tuple[Interval, ...]:
    merged = []
    for interval in sorted(intervals):
        if merged and interval.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return tuple(merged)


def normalize_request(payload: dict, waters: dict, evaluated_at: datetime) -> ForecastRequest:
    now = aware(evaluated_at)
    if not isinstance(payload, dict):
        raise InputError("request", "Expected a JSON object.")
    water_id = payload.get("water_id")
    if not isinstance(water_id, str) or water_id not in waters:
        raise InputError("water_id", "Choose an existing registry water.")
    lake = waters[water_id]
    try:
        lat, lng = float(lake["lat"]), float(lake["lng"])
        zone = ZoneInfo(lake["tz"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
        altitude = float(lake.get("alt_m") or 0)
        if not math.isfinite(altitude):
            raise ValueError
    except (KeyError, ValueError, TypeError, ZoneInfoNotFoundError):
        raise InputError("water_id", "This water needs a confirmed location and timezone. Choose another water.") from None
    water = Water(water_id, lake["name"], lat, lng, zone.key, altitude, dict(lake.get("access") or {}))
    raw_intervals = payload.get("availability")
    if not isinstance(raw_intervals, list) or not 1 <= len(raw_intervals) <= 14:
        raise InputError("availability", "Choose between one and fourteen available intervals, within seven days.")
    today = now.astimezone(zone).date()
    limit = datetime.combine(today + timedelta(days=7), time(), zone).astimezone(UTC)
    intervals = []
    for raw in raw_intervals:
        if not isinstance(raw, dict):
            raise InputError("availability", "Choose a start and end for every interval.")
        start = resolve_local(raw.get("start"), zone, "availability")
        end = resolve_local(raw.get("end"), zone, "availability")
        if start >= end:
            raise InputError("availability", "The end must follow the start, including overnight trips.")
        if start.astimezone(zone).date() < today or end > limit:
            last_date = today + timedelta(days=6)
            deadline = today + timedelta(days=7)
            raise InputError("availability", f"Choose availability from {today.isoformat()} through {last_date.isoformat()}, both dates included, in {zone.key}. End no later than {deadline.isoformat()} at 00:00; choose an earlier last date for an overnight trip.")
        if end > now:
            intervals.append(Interval(max(start, now), end))
    if not intervals:
        raise InputError("availability", "That availability has passed. Choose new dates.")
    minutes = payload.get("duration_minutes", 120)
    if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 30 <= minutes <= 480:
        raise InputError("duration_minutes", "Choose a session between 30 minutes and eight hours.")
    daylight = payload.get("daylight", True)
    if type(daylight) is not bool:
        raise InputError("daylight", "Choose whether to use daylight only.")
    birth, precision = None, "none"
    raw_birth = payload.get("birth")
    if raw_birth is not None:
        if not isinstance(raw_birth, dict):
            raise InputError("birth", "Check the birth details or continue shared-only.")
        if raw_birth.get("time_known", True) is False:
            precision = "unknown"
        else:
            try:
                birth = normalize_birth(raw_birth)
                if not birth.get("place"):
                    raise ValueError("birth.place: Select and confirm a resolved birthplace.")
            except ValueError as exc:
                field, _, message = str(exc).partition(":")
                raise InputError(field, message.strip()) from None
            precision = "known"
            if birth_datetime(birth).astimezone(UTC) > now:
                raise InputError("birth.date", "Birth details must describe a time in the past.")
    request_id = payload.get("request_id", "")
    if not isinstance(request_id, str) or len(request_id) > 80 or any(not (c.isalnum() or c in "-_") for c in request_id):
        raise InputError("request_id", "Use a short request identifier without personal details.")
    return ForecastRequest(water, merge_intervals(intervals), timedelta(minutes=minutes),
                           daylight, birth, precision, now, request_id)


@lru_cache(maxsize=1)
def environment() -> dict:
    expected = {"kerykeion": "5.12.9", "pyswisseph": "2.10.3.2"}
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise CalculationError("The calculation environment needs validation after a dependency change.")
    digest = hashlib.sha256(Path(swe.__file__).read_bytes()).hexdigest()
    return dict(backend="Moshier (explicit)", swiss_ephemeris=swe.version,
                pyswisseph=expected["pyswisseph"], kerykeion=expected["kerykeion"],
                ephemeris_binary_sha256=digest, calculation=CALC_VERSION)


def timezone_fingerprint(zones) -> str:
    digest = hashlib.sha256()
    for name in sorted(set(zones)):
        for root in TZPATH:
            path = Path(root) / name
            if path.is_file():
                digest.update(name.encode())
                digest.update(path.read_bytes())
                break
        else:
            raise CalculationError("Timezone data must be identified before calculating.")
    return digest.hexdigest()


def longitude(jd: float, body: str) -> float:
    values, flags = swe.calc_ut(jd, PLANETS[body], BACKEND | swe.FLG_SPEED)
    if flags & (swe.FLG_JPLEPH | swe.FLG_SWIEPH | swe.FLG_MOSEPH) != BACKEND:
        raise CalculationError("The ephemeris backend changed; calculation stopped.")
    return values[0] % 360


def angular_error(lon: float, target: float) -> float:
    return (lon - target + 180) % 360 - 180


def personal_events(start: datetime, end: datetime, points: dict) -> tuple[PersonalEvent, ...]:
    """One shared lunar scan for all approved natal targets; no launch-orb filter."""
    clock = Sky(0, 0, 0, 0)
    jd0, jd1 = clock.jd(start.replace(tzinfo=None)), clock.jd(end.replace(tzinfo=None))
    targets = []
    for body in NATAL_BODIES:
        for name, angle, contribution in ASPECTS:
            for orientation in ({angle, -angle} if angle != 180 else {angle}):
                rule = "P4" if contribution < 0 else f"P{NATAL_BODIES.index(body) + 1}"
                targets.append((body, name, contribution, rule, (points[body] + orientation) % 360))
    out = []
    previous_jd = jd0
    previous_lon = longitude(jd0, "Moon")
    while previous_jd < jd1:
        current_jd = min(jd1, previous_jd + SCAN.total_seconds() / 86400)
        current_lon = longitude(current_jd, "Moon")
        for body, aspect, contribution, rule, target in targets:
            before, after = angular_error(previous_lon, target), angular_error(current_lon, target)
            if before * after > 0 or max(abs(before), abs(after)) >= 10:
                continue
            left, right, left_error = previous_jd, current_jd, before
            for _ in range(30):
                mid = (left + right) / 2
                if mid in (left, right):
                    break
                error = angular_error(longitude(mid, "Moon"), target)
                if left_error * error <= 0:
                    right = mid
                else:
                    left, left_error = mid, error
            exact_jd = (previous_jd if before == 0 else current_jd if after == 0 else (left + right) / 2)
            if jd0 <= exact_jd < jd1:
                exact = start if exact_jd == jd0 else clock.loc(exact_jd).replace(tzinfo=UTC)
                event = PersonalEvent(rule, body, aspect, exact, contribution)
                if event not in out:
                    out.append(event)
        previous_jd, previous_lon = current_jd, current_lon
    return tuple(sorted(out, key=lambda e: (e.exact, e.rule, e.body, e.aspect)))


def _rise_after(at: datetime, water: Water, body: str, mode: int) -> datetime | None:
    clock = Sky(0, 0, 0, 0)
    jd = clock.jd(at.replace(tzinfo=None))
    status, times = swe.rise_trans(jd, PLANETS[body], mode,
                                   (water.lng, water.lat, water.altitude), flags=BACKEND)
    return clock.loc(times[0]).replace(tzinfo=UTC) if status == 0 else None


def compute_sky(req: ForecastRequest) -> SkyData:
    env = dict(environment())
    zones = [req.water.tz] + ([req.birth["tz"]] if req.birth else [])
    env["timezone_sha256"] = timezone_fingerprint(zones)
    zone = ZoneInfo(req.water.tz)
    start, end = req.availability[0].start, req.availability[-1].end
    clock = Sky(0, 0, 0, 0)
    longitude(clock.jd(start.replace(tzinfo=None)), "Moon")  # Verify backend even in shared mode.
    day = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    allowed = []
    while day <= last:
        midnight = datetime.combine(day, time(), zone).astimezone(UTC)
        next_midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)
        sunrise = _rise_after(midnight, req.water, "Sun", swe.CALC_RISE)
        sunset = _rise_after(midnight, req.water, "Sun", swe.CALC_SET)
        lo, hi = midnight, next_midnight
        if req.daylight or req.water.access:
            if sunrise is None or sunset is None or not (midnight <= sunrise < sunset <= next_midnight):
                # Polar-night/day and unavailable rise/set data are explicit no-fit,
                # never fabricated dawn/dusk values.
                day += timedelta(days=1)
                continue
            if req.daylight:
                lo, hi = max(lo, sunrise), min(hi, sunset)
            if req.water.access:
                cfg = req.water.access
                summer = bool(cfg.get("summer_dates") and cfg["summer_dates"][0] <= day.strftime("%m-%d") <= cfg["summer_dates"][1])
                opening = cfg.get("summer_open_offset_min" if summer else "open_offset_min", 30)
                closing = cfg.get("summer_close_offset_min" if summer else "close_offset_min", 30)
                lo = max(lo, sunrise - timedelta(minutes=opening))
                hi = min(hi, sunset + timedelta(minutes=closing))
        if lo < hi:
            allowed.append(Interval(lo, hi))
        day += timedelta(days=1)
    # Merge at midnight so overnight sessions can fit when daylight/access allow.
    allowed = merge_intervals(allowed)
    feasible = []
    for available in req.availability:
        for limit in allowed:
            lo, hi = max(available.start, limit.start), min(available.end, limit.end)
            if hi - lo >= req.duration:
                feasible.append(Interval(lo, hi))
    shared = []
    for mode, kind, radius in ((swe.CALC_MTRANSIT, "major", 60),
                               (swe.CALC_ITRANSIT, "major", 60),
                               (swe.CALC_RISE, "minor", 45),
                               (swe.CALC_SET, "minor", 45)):
        cursor = start - timedelta(hours=1)
        for _ in range(10):  # Seven days plus both edge overlaps.
            exact = _rise_after(cursor, req.water, "Moon", mode)
            if exact is None or exact >= end + timedelta(hours=1):
                break
            delta = timedelta(minutes=radius)
            shared.append(SharedEvent(kind, Interval(exact - delta, exact + delta), exact))
            cursor = exact + timedelta(seconds=1)
    personal = ()
    points = None
    if req.birth and feasible:
        natal = NatalChart(req.birth)  # Exactly once, never once per candidate.
        birth_jd = clock.jd(birth_datetime(req.birth).astimezone(UTC).replace(tzinfo=None))
        for body in NATAL_BODIES:
            if abs(angular_error(natal.points[body], longitude(birth_jd, body))) > 1e-7:
                raise CalculationError("Natal chart and explicit ephemeris backend disagree.")
        personal = personal_events(start, end, natal.points)
        points = dict(natal.points)
    return SkyData(tuple(feasible), tuple(sorted(set(shared), key=lambda e: (e.exact, e.kind))), personal, env, points)


def candidates(req: ForecastRequest, sky: SkyData) -> tuple[Interval, ...]:
    starts = set()
    for interval in sky.feasible:
        last = interval.end - req.duration
        if interval.start > last:
            continue
        starts.update((interval.start, last))
        cursor = interval.start
        while cursor <= last:
            starts.add(cursor)
            if len(starts) > MAX_CANDIDATES:
                raise InputError("availability", "Too many candidate sessions. Narrow your availability.")
            cursor += GRID
        for event in sky.personal:
            if interval.start <= event.exact < interval.end:
                for candidate in (event.exact, event.exact - req.duration / 2):
                    starts.add(max(interval.start, min(last, candidate)))
        if len(starts) > MAX_CANDIDATES:
            raise InputError("availability", "Too many candidate sessions. Narrow your availability.")
    return tuple(Interval(start, start + req.duration) for start in sorted(starts))


def overlap(a: Interval, b: Interval) -> float:
    return max(0.0, (min(a.end, b.end) - max(a.start, b.start)).total_seconds())


def weather_for(interval: Interval, snapshot: WeatherSnapshot) -> dict | None:
    rows = []
    coverage = interval.start
    for row in snapshot.hours:
        end = row.start + timedelta(hours=1)
        if end <= interval.start or row.start >= interval.end:
            continue
        values = (row.wind_mph, row.gust_mph, row.precipitation_mm, row.code)
        if row.start > coverage or any(value is None or not math.isfinite(value) or value < 0 for value in values):
            return None
        coverage = max(coverage, end)
        rows.append(row)
    if coverage < interval.end or not rows:
        return None
    wind = max(r.wind_mph for r in rows)
    # Gusts are a separate model parameter and can land a few tenths of a mph
    # below the sustained sample. The reported peak must never be lower than
    # the reported wind, so ranking, exclusions and the displayed sentence all
    # use one monotonic value.
    gust = max(max(r.gust_mph for r in rows), wind)
    rain = max(r.precipitation_mm for r in rows)
    excluded = any(r.code in (95, 96, 99) for r in rows) or gust >= 25 or rain >= 4
    total = sum(r.precipitation_mm * overlap(interval, Interval(r.start, r.start + timedelta(hours=1))) / 3600 for r in rows)
    temperatures = [r.temperature_f for r in rows if r.temperature_f is not None and math.isfinite(r.temperature_f)]
    return dict(band=2 if excluded else 0 if wind <= 12 and rain <= 0.5 else 1,
                gust_mph=gust, wind_mph=wind, precipitation_mm=total,
                max_rain_mm=rain, temperature_f=sum(temperatures) / len(temperatures) if temperatures else None)


def rank_candidates(req: ForecastRequest, snapshot: WeatherSnapshot, sky: SkyData,
                    sessions: tuple[Interval, ...] | None = None) -> tuple[Session, ...]:
    ranked = []
    for interval in candidates(req, sky) if sessions is None else sessions:
        wx = weather_for(interval, snapshot)
        if wx is None or wx["band"] == 2:
            continue
        events = tuple(e for e in sky.personal if interval.start <= e.exact < interval.end)
        shared = tuple(e for e in sky.shared if overlap(interval, e.interval) > 0)
        personal = max(-2, min(2, sum(e.contribution for e in events)))
        # Union within each kind: overlapping shared windows never double-count.
        spans = {kind: merge_intervals(e.interval for e in shared if e.kind == kind) for kind in ("major", "minor")}
        ranked.append(Session(interval, personal=personal, events=events, shared_events=shared,
                              major_seconds=sum(overlap(interval, s) for s in spans["major"]),
                              minor_seconds=sum(overlap(interval, s) for s in spans["minor"]), **wx))
    return tuple(sorted(ranked, key=lambda session: session.rank))


def event_reason(event: PersonalEvent, zone: ZoneInfo) -> str:
    clock = event.exact.astimezone(zone).strftime("%a %b %-d, %-I:%M %p %Z")
    if event.contribution > 0:
        return f"The Moon is {event.aspect} your natal {event.body}, exact at {clock}. This method counts that as a favorable contact."
    return f"The Moon is {event.aspect} your natal {event.body}, exact at {clock}. This method counts that as a demanding contact."


def _serialize(session: Session, zone: ZoneInfo, reading: dict | None = None) -> dict:
    event_data = [dict(rule=e.rule, transit="Moon", natal=e.body, aspect=e.aspect,
                       exact=e.exact.astimezone(zone).isoformat(), contribution=e.contribution,
                       explanation=event_reason(e, zone)) for e in session.events]
    shared_data = [dict(kind=e.kind, exact=e.exact.astimezone(zone).isoformat(),
                        start=e.interval.start.astimezone(zone).isoformat(),
                        end=e.interval.end.astimezone(zone).isoformat()) for e in session.shared_events]
    rain = ("no precipitation forecast (hourly estimate)" if session.precipitation_mm == 0
            else f"about {session.precipitation_mm:.1f} mm of precipitation (hourly estimate)")
    if round(session.gust_mph) > round(session.wind_mph):
        practical = f"Wind up to {session.wind_mph:.0f} mph, gusting to {session.gust_mph:.0f} mph; {rain}."
    else:
        practical = f"Wind up to {session.wind_mph:.0f} mph, with no stronger gusts forecast; {rain}."
    return dict(start=session.interval.start.astimezone(zone).isoformat(),
                end=session.interval.end.astimezone(zone).isoformat(),
                personal_contribution=session.personal, personal_events=event_data,
                shared=dict(major_overlap_seconds=session.major_seconds,
                            minor_overlap_seconds=session.minor_seconds, events=shared_data),
                weather=dict(band="calmer" if session.band == 0 else "less calm",
                             wind_mph=session.wind_mph, gust_mph=session.gust_mph,
                             precipitation_mm=session.precipitation_mm, temperature_f=session.temperature_f),
                practical=practical, reading=reading)


def calculate(req: ForecastRequest, snapshot: WeatherSnapshot | None, sky: SkyData | None = None) -> dict:
    """One deterministic operation shared by web and CLI. Never cache its output."""
    zone = ZoneInfo(req.water.tz)
    result = dict(request_id=req.request_id, status="unavailable", recommended=None,
                  alternatives=[], personalized=False, reason="", limitations=[],
                  water=dict(id=req.water.id, name=req.water.name, timezone=req.water.tz),
                  evaluated_at=req.evaluated_at.isoformat(), rule_version=RULE_VERSION,
                  calculation_version=CALC_VERSION, environment=None,
                  weather_acquired_at=snapshot.acquired_at.isoformat() if snapshot else None,
                  provider=snapshot.provider if snapshot else None)
    if req.precision != "known":
        result["limitations"].append("Birth time unknown: shared local almanac only; no natal timing." if req.precision == "unknown"
                                      else "Shared local almanac only; no birth details used.")
    if snapshot is None or (snapshot.lat, snapshot.lng) != (req.water.lat, req.water.lng):
        result["reason"] = "Weather is unavailable for this water. Try again shortly."
        return result
    age = req.evaluated_at - aware(snapshot.acquired_at)
    if age < timedelta(0) or age > FRESH_FOR:
        result["reason"] = "Weather is stale or has an invalid update time. Refresh the forecast."
        return result
    sky = sky if sky is not None else compute_sky(req)
    result["environment"] = sky.environment
    generated = candidates(req, sky)
    result["candidate_count"] = len(generated)
    ranked = rank_candidates(req, snapshot, sky, generated)
    result["eligible_count"] = len(ranked)
    result["personalized"] = req.precision == "known" and bool(generated)
    if not generated:
        result.update(status="no_session", reason="No session of this duration fits your availability, daylight, and documented access. Change your hours or duration.")
        return result
    if not ranked:
        incomplete = any(weather_for(interval, snapshot) is None for interval in generated)
        result.update(status="unavailable" if incomplete else "excluded",
                      reason="Weather coverage is incomplete. Try refreshing or choose nearer dates." if incomplete
                      else "All available sessions meet a weather exclusion in this policy. Choose different availability.")
        return result
    picked = []
    for session in ranked:
        if all(overlap(session.interval, other.interval) == 0 for other in picked):
            picked.append(session)
        if len(picked) == 3:
            break
    winner = picked[0]
    same_band = [s for s in ranked if s.band == winner.band]
    distinguishes = len({s.personal for s in same_band}) > 1
    if req.precision != "known":
        reason = "A shared local almanac window, ranked by weather and Moon timing; no birth personalization."
    elif not distinguishes:
        reason = "Your chart gives these times about equal weight. Weather and Moon timing decide between them."
    elif winner.personal == 0:
        reason = "Your chart adds nothing here, but the other times carry a demanding contact. In comparable weather this one is the calmer choice."
    else:
        event = min(winner.events, key=lambda e: (-abs(e.contribution), e.exact, e.rule, e.body, e.aspect))
        reason = event_reason(event, zone)
    readings = []
    if req.precision == "known" and sky.points:
        clock = Sky(0, 0, 0, 0)
        midpoints = [s.interval.start + (s.interval.end - s.interval.start) / 2 for s in picked]
        transits = [{body: longitude(clock.jd(mid.replace(tzinfo=None)), body)
                     for body in reading_engine.TRANSITS} for mid in midpoints]
        readings = reading_engine.select(transits, {target: sky.points[target]
                                                    for target in reading_engine.TARGETS})
        result["reading_version"] = reading_engine.VERSION
    readings += [None] * (len(picked) - len(readings))
    result.update(status="ok", recommended=_serialize(winner, zone, readings[0]),
                  alternatives=[_serialize(s, zone, r) for s, r in zip(picked[1:], readings[1:])],
                  reason=reason)
    if len({s.contribution for s in winner.events}) > 1:
        result["limitations"].append("This session has both favorable and challenging personal alignments; their contributions are combined.")
    if len(ranked) < len(generated):
        result["limitations"].append("Some sessions were omitted because weather was incomplete or met an exclusion.")
    result["limitations"].append("Astrological interpretation is not an established catch probability. Weather screening is not a safety guarantee; check local warnings and access.")
    return result
