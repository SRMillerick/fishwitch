"""Gradual window policy: frozen synthetic data, no provider or real profiles."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import re
import unittest
from unittest import mock

from fishwitch import forecast as fc
from fishwitch import forecast_weather as fw

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 0, tzinfo=UTC)
WATERS = {"synthetic": dict(name="Synthetic", lat=38, lng=-122, tz="America/Los_Angeles")}
BIRTH = dict(date="1990-01-15", time="08:30", time_known=True, place="Synthetic", lat=38, lng=-122, tz="America/Los_Angeles")


def request(**changes):
    payload = dict(water_id="synthetic", availability=[dict(start="2026-10-23T08:00", end="2026-10-23T16:00")],
                   birth=BIRTH, duration_minutes=120, daylight=False, request_id="fixture-1")
    payload.update(changes)
    return fc.normalize_request(payload, WATERS, NOW)


def snapshot(req=None):
    req = req or request()
    return fc.WeatherSnapshot(req.water.lat, req.water.lng, NOW,
                             tuple(fc.WeatherHour(NOW + timedelta(hours=i), 5, 8, 0, 0, 60) for i in range(192)))


def sky(req, personal=(), shared=()):
    points = None
    if personal:
        # Analytic Moon path used by RankingPolicyTest: 1 degree per hour.
        base = (req.availability[0].start - NOW).total_seconds() / 3600
        points = {body: base for body in ('Moon', 'Mercury', 'Mars', 'Venus', 'Jupiter')}
        angles = {name: angle for name, angle, sign in fc.ASPECTS}
        for e in personal:
            points[e.body] = ((e.exact - NOW).total_seconds() / 3600 - angles[e.aspect]) % 360
    return fc.SkyData(req.availability, tuple(shared), tuple(personal), {"fixture": "synthetic-v1"}, points)


def event(req, minutes=60, contribution=1, body="Venus", aspect="sextile"):
    return fc.PersonalEvent("P4" if contribution < 0 else "P2", body, aspect,
                            req.availability[0].start + timedelta(minutes=minutes), contribution)


class InputContractTest(unittest.TestCase):
    def test_unknown_time_needs_no_placeholder_or_chart(self):
        for birth, precision in ((None, "none"), ({"time_known": False}, "unknown")):
            req = request(birth=birth)
            self.assertEqual(req.precision, precision)
            with mock.patch.object(fc, "NatalChart", side_effect=AssertionError("natal called")):
                got = fc.calculate(req, snapshot(req))
            self.assertFalse(got["personalized"])
            self.assertEqual(got["status"], "ok")

    def test_unknown_precision_string_is_rejected(self):
        with self.assertRaises(fc.InputError):
            request(birth=dict(BIRTH, time_known="false"))
        with self.assertRaises(fc.InputError):
            request(birth=dict(BIRTH, date="2090-01-15"))

    def test_explicit_water_and_timezone_required(self):
        for change in ({"water_id": "missing"}, {"water_id": ""}, {"duration_minutes": 0}, {"duration_minutes": "120"}):
            with self.assertRaises(fc.InputError):
                request(**change)
        for missing in ("lat", "tz"):
            water = dict(WATERS["synthetic"])
            del water[missing]
            with self.assertRaises(fc.InputError):
                fc.normalize_request(dict(water_id="synthetic"), {"synthetic": water}, NOW)

    def test_expired_seven_day_cap_and_no_fit(self):
        for start, end in (("2026-10-20T08:00", "2026-10-20T10:00"),
                           ("2026-11-01T08:00", "2026-11-01T10:00")):
            with self.assertRaises(fc.InputError):
                request(availability=[dict(start=start, end=end)])
        req = request(availability=[dict(start="2026-10-23T08:00", end="2026-10-23T09:00")])
        self.assertEqual(fc.calculate(req, snapshot(req), sky(req))["status"], "no_session")

    def test_seven_calendar_dates_and_exact_midnight_deadline_are_allowed(self):
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(WATERS["synthetic"]["tz"])
        today = NOW.astimezone(zone).date()
        last = today + timedelta(days=6)
        intervals = [dict(start=f"{today + timedelta(days=i)}T08:00", end=f"{today + timedelta(days=i)}T20:00")
                     for i in range(7)]
        req = request(availability=intervals, birth=None)
        self.assertEqual(len(req.availability), 7)
        self.assertEqual(req.availability[-1].end.astimezone(zone).date(), last)
        deadline = last + timedelta(days=1)
        overnight = request(availability=[dict(start=f"{last}T22:00", end=f"{deadline}T00:00")], birth=None)
        self.assertEqual(overnight.availability[-1].end.astimezone(zone).isoformat(), f"{deadline}T00:00:00-07:00")

    def test_forecast_horizon_errors_name_dates_timezone_and_overnight_deadline(self):
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(WATERS["synthetic"]["tz"])
        today = NOW.astimezone(zone).date()
        last = today + timedelta(days=6)
        deadline = today + timedelta(days=7)
        for start, end in ((f"{deadline}T08:00", f"{deadline}T10:00"),
                           (f"{last}T22:00", f"{deadline}T00:01")):
            with self.subTest(start=start, end=end), self.assertRaises(fc.InputError) as caught:
                request(availability=[dict(start=start, end=end)], birth=None)
            self.assertEqual(caught.exception.field, "availability")
            for text in (str(today), str(last), "both dates included", zone.key, f"{deadline} at 00:00", "overnight"):
                self.assertIn(text, caught.exception.message)

    def test_dst_gap_fold_offsets_and_elapsed_duration(self):
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("America/Los_Angeles")
        for value in ("2026-03-08T02:30", "2026-11-01T01:30"):
            with self.assertRaises(fc.InputError):
                fc.resolve_local(value, zone, "availability")
        early = fc.resolve_local("2026-11-01T01:30-07:00", zone, "availability")
        late = fc.resolve_local("2026-11-01T01:30-08:00", zone, "availability")
        self.assertEqual(late - early, timedelta(hours=1))
        with self.assertRaises(fc.InputError):
            fc.resolve_local("2026-11-01T01:30-06:00", zone, "availability")

    def test_overnight_duration_is_preserved(self):
        req = request(availability=[dict(start="2026-10-23T22:00", end="2026-10-24T03:00")])
        got = fc.calculate(req, snapshot(req))
        self.assertEqual(got["status"], "ok")
        session = got["recommended"]
        self.assertEqual(datetime.fromisoformat(session["end"]) - datetime.fromisoformat(session["start"]), timedelta(hours=2))

    def test_full_search_across_both_dst_changes_uses_elapsed_time(self):
        from zoneinfo import ZoneInfo
        for evaluated, start, end, hours in (
                (datetime(2026, 10, 31, tzinfo=UTC), "2026-10-31T22:00", "2026-11-01T03:00", 6),
                (datetime(2026, 3, 7, tzinfo=UTC), "2026-03-07T22:00", "2026-03-08T04:00", 5)):
            req = fc.normalize_request(dict(water_id="synthetic", daylight=False, birth=None,
                                           availability=[dict(start=start, end=end)]), WATERS, evaluated)
            wx = fc.WeatherSnapshot(38, -122, evaluated, tuple(fc.WeatherHour(evaluated + timedelta(hours=i), 5, 8, 0, 0, 60) for i in range(120)))
            self.assertEqual(req.availability[0].end - req.availability[0].start, timedelta(hours=hours))
            data = fc.compute_sky(req)
            generated = fc.candidates(req, data)
            zone = ZoneInfo(req.water.tz)
            self.assertTrue(any(s.start.astimezone(zone).utcoffset() != s.end.astimezone(zone).utcoffset() for s in generated))
            self.assertTrue(all(s.end - s.start == timedelta(hours=2) for s in generated))
            self.assertEqual(fc.calculate(req, wx, data)["status"], "ok")

    def test_identifiers_cannot_echo_arbitrary_birth_text(self):
        with self.assertRaises(fc.InputError):
            request(request_id="private date, place & time")


class EventScanTest(unittest.TestCase):
    def test_both_orientations_wrap_and_exact_boundaries(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        clock = fc.Sky(0, 0, 0, 0)
        jd = clock.jd(start.replace(tzinfo=None))
        for angle in (60, -60, 120, -120, 90, -90, 180):
            with self.subTest(angle=angle), mock.patch.object(fc, "NATAL_BODIES", ("Moon",)), \
                    mock.patch.object(fc, "longitude", side_effect=lambda at, body: (359.9 + angle + (at - jd - 1 / 24) * 12) % 360):
                events = fc.personal_events(start, start + timedelta(hours=2), {"Moon": 359.9})
                self.assertEqual(len(events), 1)
                self.assertLess(abs((events[0].exact - start).total_seconds() - 3600), .001)
        with mock.patch.object(fc, "NATAL_BODIES", ("Moon",)), \
                mock.patch.object(fc, "longitude", side_effect=lambda at, body: (60 + (at - jd) * 12) % 360):
            events = fc.personal_events(start, start + timedelta(hours=1), {"Moon": 0})
            self.assertEqual(events[0].exact, start)
        with mock.patch.object(fc, "NATAL_BODIES", ("Moon",)), \
                mock.patch.object(fc, "longitude", side_effect=lambda at, body: (60 + (at - jd - 1 / 24) * 12) % 360):
            self.assertEqual(fc.personal_events(start, start + timedelta(hours=1), {"Moon": 0}), ())

    def test_far_from_launch_orb_is_not_lost(self):
        req = request()
        start = req.availability[0].start
        jd = fc.Sky(0, 0, 0, 0).jd(start.replace(tzinfo=None))
        with mock.patch.object(fc, "NATAL_BODIES", ("Moon",)), \
                mock.patch.object(fc, "longitude", side_effect=lambda at, body: 50 + (at - jd) * 48):
            events = fc.personal_events(start, start + timedelta(hours=8), {"Moon": 0})
            self.assertTrue(any(e.aspect == "sextile" for e in events))

    def test_chart_is_constructed_once_and_no_enrichments_execute(self):
        req = request()
        with mock.patch.object(fc, "NatalChart", wraps=fc.NatalChart) as natal, \
                mock.patch("requests.sessions.Session.request", side_effect=AssertionError("network")), \
                mock.patch("report.generate", side_effect=AssertionError("legacy report")), \
                mock.patch("layers.history.History", side_effect=AssertionError("history")), \
                mock.patch("layers.watertemp.nearest_water_temp", side_effect=AssertionError("gauge")), \
                mock.patch("layers.stocking.recent", side_effect=AssertionError("stocking")), \
                mock.patch("layers.shoreline.wind_shore", side_effect=AssertionError("shoreline")), \
                mock.patch("weather.model_agreement", side_effect=AssertionError("models")), \
                mock.patch("tactics.catalog", side_effect=AssertionError("tackle")):
            first = fc.calculate(req, snapshot(req))
            self.assertEqual(natal.call_count, 1)
            second = fc.calculate(req, snapshot(req))
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["environment"]["backend"], "Moshier (explicit)")
        self.assertNotIn(BIRTH["date"], json.dumps(first))

    def test_real_synthetic_profiles_can_differ_or_share_the_winner(self):
        req = request(availability=[dict(start="2026-10-23T06:00", end="2026-10-25T20:00")], daylight=True)
        other = replace(req, birth=dict(BIRTH, date="1991-06-15"))
        self.assertNotEqual(fc.calculate(req, snapshot(req))["recommended"]["start"],
                            fc.calculate(other, snapshot(other))["recommended"]["start"])
        fixed = request(availability=[dict(start="2026-10-23T08:00", end="2026-10-23T10:00")])
        other = replace(fixed, birth=dict(BIRTH, date="1991-06-15"))
        self.assertEqual(fc.calculate(fixed, snapshot(fixed))["recommended"]["start"],
                         fc.calculate(other, snapshot(other))["recommended"]["start"])

    def test_seconds_in_historical_birth_offset_are_preserved(self):
        req = request(birth=dict(BIRTH, date="1850-01-15"))
        self.assertEqual(fc.calculate(req, snapshot(req))["status"], "ok")

    def test_backend_change_stops_calculation(self):
        with mock.patch.object(fc.swe, "calc_ut", return_value=((0,) * 6, fc.swe.FLG_SWIEPH)):
            with self.assertRaises(fc.CalculationError):
                fc.longitude(100, "Moon")


class RankingPolicyTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(fc, 'position_at', side_effect=lambda body, at:
                                    (((at - NOW).total_seconds() / 3600) % 360, 24)
                                    if body == 'Moon' else (45, 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_data_produces_same_ranking_and_text(self):
        req = request()
        data = sky(req, [event(req)])
        self.assertEqual(fc.calculate(req, snapshot(req), data), fc.calculate(req, snapshot(req), data))

    def test_half_open_exact_metadata_does_not_gate_gradual_scoring(self):
        req = request()
        base = req.availability[0].start
        intervals = (fc.Interval(base, base + timedelta(hours=2)),
                     fc.Interval(base + timedelta(hours=2), base + timedelta(hours=4)))
        events = [event(req, minutes=120), event(req, minutes=0),
                  event(req, minutes=1, contribution=-1, aspect="square")]
        ranked = fc.rank_candidates(req, snapshot(req), sky(req, events), intervals)
        self.assertEqual(sum(len(s.events) for s in ranked), 3)
        # The exact at 120 minutes belongs only to the second session; both
        # sessions nevertheless contain nearby geometry and can receive weight.
        boundary = sky(req, [event(req, minutes=120)])
        rows = fc.rank_candidates(req, snapshot(req), boundary, intervals)
        self.assertEqual([len(s.events) for s in rows], [0, 1])
        self.assertEqual([s.personal for s in rows], [.5, .5])

    def test_signed_averages_combine_and_final_score_is_capped(self):
        req = request()
        points = dict(Moon=0, Venus=0, Jupiter=0)
        data = replace(sky(req), points=points)
        with mock.patch.object(fc, 'position_at', return_value=(60, 0)):
            self.assertEqual(fc.rank_candidates(req, snapshot(req), data)[0].personal, 2)
            mixed = replace(data, points=dict(Moon=0, Venus=0, Jupiter=150))
            row = fc.rank_candidates(req, snapshot(req), mixed)[0]
            self.assertEqual(row.personal, 1)
            self.assertEqual(len(row.timing_contacts), 3)
            negative = replace(data, points=dict(Moon=150, Venus=150, Jupiter=150))
            self.assertEqual(fc.rank_candidates(req, snapshot(req), negative)[0].personal, -2)

    def test_peak_just_outside_session_counts_without_a_score_jump(self):
        req = request()
        base = req.availability[0].start
        interval = (fc.Interval(base, base + req.duration),)
        scores = []
        for seconds in (-1, 0, 1):
            peak = replace(event(req, minutes=120), exact=base + req.duration + timedelta(seconds=seconds))
            row, = fc.rank_candidates(req, snapshot(req), sky(req, [peak]), interval)
            scores.append(row.personal)
            if seconds >= 0:
                self.assertEqual(row.events, ())
                self.assertTrue(row.timing_contacts)
                self.assertGreater(row.personal, .49)
        self.assertLess(max(scores) - min(scores), .001)
        self.assertAlmostEqual(scores[1], .5, places=8)

    def test_winner_can_have_no_exact_events_anywhere_in_availability(self):
        req = request()
        result = fc.calculate(req, snapshot(req), sky(req, [event(req, minutes=481)]))
        winner = result['recommended']
        self.assertGreater(winner['personal_contribution'], 0)
        self.assertEqual(winner['personal_events'], [])
        self.assertTrue(winner['personal_timing'])
        self.assertIn('average chart timing', result['reason'])

    def test_sustained_closeness_beats_brief_exact_peak_and_duration_is_normalized(self):
        req = request()
        base = req.availability[0].start
        data = replace(sky(req), points=dict(Moon=0, Venus=60, Jupiter=60))
        sessions = (fc.Interval(base, base + timedelta(hours=2)),
                    fc.Interval(base + timedelta(hours=4), base + timedelta(hours=6)))
        def position(body, at):
            hours = (at - base).total_seconds() / 3600
            return (59, 0) if hours <= 2 else (52 + 8 * (hours - 4), 192)
        with mock.patch.object(fc, 'position_at', side_effect=position):
            first, second = fc.rank_candidates(req, snapshot(req), data, sessions)
            self.assertEqual(first.interval, sessions[0])
            self.assertAlmostEqual(first.personal, .5)
            self.assertAlmostEqual(second.personal, .125)
            shorter, = fc.rank_candidates(req, snapshot(req), data,
                                          (fc.Interval(base, base + timedelta(hours=1)),))
            self.assertAlmostEqual(shorter.personal, first.personal)

    def test_unknown_birth_does_not_compute_personal_timing_even_with_points(self):
        req = request(birth=None)
        data = replace(sky(req), points=dict(Moon=0, Venus=0, Jupiter=0))
        with mock.patch.object(fc, 'position_at', side_effect=AssertionError('personal positions')):
            rows = fc.rank_candidates(req, snapshot(req), data)
        self.assertTrue(all(s.personal == 0 and not s.timing_contacts for s in rows))

    def test_personal_difference_and_legitimate_identical_recommendation(self):
        req = request()
        shared = sky(req)
        times = fc.candidates(req, shared)
        baseline = fc.rank_candidates(req, snapshot(req), shared, times)
        personal_sky = sky(req, [event(req, minutes=300)])
        personal = fc.rank_candidates(req, snapshot(req), personal_sky, times)
        self.assertNotEqual(baseline[0].interval, personal[0].interval)
        same = fc.rank_candidates(req, snapshot(req), sky(req, [event(req, minutes=0)]), times)
        self.assertEqual(baseline[0].interval, same[0].interval)
        # Full searches also allow both outcomes, without manufacturing changes.
        self.assertNotEqual(fc.calculate(req, snapshot(req), shared)["recommended"]["start"],
                            fc.calculate(req, snapshot(req), personal_sky)["recommended"]["start"])
        self.assertEqual(fc.calculate(req, snapshot(req), shared)["recommended"]["start"],
                         fc.calculate(req, snapshot(req), sky(req, [event(req, minutes=0)]))["recommended"]["start"])

    def test_event_candidates_fit_preserve_duration_and_alternatives_do_not_overlap(self):
        req = request()
        data = sky(req, [event(req, minutes=63.25)])
        sessions = fc.candidates(req, data)
        self.assertTrue(any(s.start == data.personal[0].exact for s in sessions))
        for session in sessions:
            self.assertEqual(session.end - session.start, req.duration)
            self.assertGreaterEqual(session.start, req.availability[0].start)
            self.assertLessEqual(session.end, req.availability[0].end)
        result = fc.calculate(req, snapshot(req), data)
        rows = [result["recommended"], *result["alternatives"]]
        intervals = [fc.Interval(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]
        for a, b in zip(intervals, intervals[1:]):
            self.assertEqual(fc.overlap(a, b), 0)

    def test_grid_candidate_cap_is_explicit(self):
        req = request()
        with mock.patch.object(fc, "MAX_CANDIDATES", 2):
            with self.assertRaises(fc.InputError):
                fc.candidates(req, sky(req))

    def test_weather_band_precedes_personal_and_thresholds_are_inclusive(self):
        req = request()
        data = sky(req, [event(req, minutes=300)])
        wx = snapshot(req)
        cutoff = req.availability[0].start + timedelta(hours=2)
        changed = replace(wx, hours=tuple(replace(row, wind_mph=13) if row.start >= cutoff else row for row in wx.hours))
        self.assertEqual(fc.calculate(req, changed, data)["recommended"]["personal_contribution"], 0)
        for field, value in (("gust_mph", 25), ("precipitation_mm", 4), ("code", 95)):
            bad = replace(wx, hours=tuple(replace(row, **{field: value}) for row in wx.hours))
            self.assertEqual(fc.calculate(req, bad, data)["status"], "excluded")

    def test_reported_peak_is_never_below_sustained_wind(self):
        req = request()
        data = sky(req)
        for wind, gust, excluded, gust_phrase in ((6, 5, False, False), (5, 3, False, False),
                                                  (6, 12, False, True), (25, 23, True, None),
                                                  (24.6, 24.4, False, False)):
            with self.subTest(wind=wind, gust=gust):
                wx = snapshot(req)
                wx = replace(wx, hours=tuple(replace(row, wind_mph=wind, gust_mph=gust) for row in wx.hours))
                session = fc.weather_for(req.availability[0], wx)
                self.assertGreaterEqual(session["gust_mph"], session["wind_mph"])
                result = fc.calculate(req, wx, data)
                self.assertEqual(result["status"], "excluded" if excluded else "ok")
                if excluded:
                    continue
                shown = result["recommended"]["weather"]
                self.assertGreaterEqual(shown["gust_mph"], shown["wind_mph"])
                practical = result["recommended"]["practical"]
                match = re.fullmatch(r"Wind up to (\d+) mph(?:, gusting to (\d+) mph|, with no stronger gusts(?: forecast)?); .*", practical)
                self.assertIsNotNone(match, practical)
                wind_text, gust_text = match.group(1), match.group(2) or match.group(1)
                self.assertGreaterEqual(int(gust_text), int(wind_text))
                self.assertEqual(bool(match.group(2)), gust_phrase, practical)

    def test_stale_missing_null_and_wrong_location_weather_are_explicit(self):
        req = request()
        wx = snapshot(req)
        for missing in (None, replace(wx, lat=39), replace(wx, acquired_at=NOW - timedelta(minutes=31)),
                        replace(wx, hours=()), replace(wx, hours=tuple(replace(row, gust_mph=None) for row in wx.hours))):
            self.assertEqual(fc.calculate(req, missing, sky(req))["status"], "unavailable")

    def test_unrounded_gust_breaks_tie_and_earlier_start_is_final_tie(self):
        req = request()
        wx = snapshot(req)
        base = req.availability[0].start
        changed = replace(wx, hours=tuple(replace(row, gust_mph=8.01 if row.start < base + timedelta(hours=2) else 8.001) for row in wx.hours))
        got = fc.rank_candidates(req, changed, sky(req))
        self.assertGreater(got[0].interval.start, base)
        self.assertEqual(fc.rank_candidates(req, wx, sky(req))[0].interval.start, base)

    def test_identical_or_zero_personal_scores_have_no_invented_reason(self):
        req = request()
        exact = req.availability[0].start + timedelta(hours=1)
        data = sky(req, [event(req)], [fc.SharedEvent("major", fc.Interval(exact, exact + timedelta(hours=2)), exact)])
        narrow = replace(req, availability=(fc.Interval(exact, exact + req.duration),))
        got = fc.calculate(narrow, snapshot(req), fc.SkyData(narrow.availability, data.shared, (), {}))
        self.assertIn("about equal weight", got["reason"])

    def test_zero_can_win_by_avoiding_negative_events_without_false_tie_claim(self):
        req = request()
        got = fc.calculate(req, snapshot(req), sky(req, [event(req, minutes=0, contribution=-1, aspect="square")]))
        self.assertEqual(got["recommended"]["personal_contribution"], 0)
        self.assertIn("demanding chart timing", got["reason"])


class WeatherAcquisitionTest(unittest.TestCase):
    def payload(self):
        data = {"time": [int((NOW + timedelta(hours=i)).timestamp()) for i in range(72)]}
        data.update({field: [0 if field in ("weather_code", "precipitation") else 5] * 72 for field in fw.FIELDS})
        return {"hourly": data, "hourly_units": dict(temperature_2m="°F", wind_speed_10m="mp/h", wind_gusts_10m="mp/h", precipitation="mm")}

    def test_one_forecast_call_no_history_bounded_timeout_and_shared_cache(self):
        store = fw.WeatherStore()
        response = mock.Mock()
        response.json.return_value = self.payload()
        req = request()
        with mock.patch.object(fw.requests, "get", return_value=response) as get:
            first = store.get(req)
            second = store.get(replace(req, birth=None))
        self.assertIs(first, second)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args, (fw.URL,))
        self.assertEqual(get.call_args.kwargs["timeout"], (2, 5))
        params = get.call_args.kwargs["params"]
        self.assertNotIn("past_days", params)
        self.assertNotIn("daily", params)
        self.assertNotIn("birth", json.dumps(params))
        self.assertEqual(params["timeformat"], "unixtime")

    def test_cache_keys_use_coordinates_coverage_provider_and_are_bounded(self):
        store = fw.WeatherStore()
        response = mock.Mock()
        response.json.return_value = self.payload()
        req = request()
        with mock.patch.object(fw, "MAX_ENTRIES", 2), mock.patch.object(fw.requests, "get", return_value=response) as get:
            for lat in (38, 39, 40):
                store.get(replace(req, water=replace(req.water, lat=lat)))
            self.assertEqual(get.call_count, 3)
            self.assertEqual(len(store.cache), 2)

    def test_hourly_values_align_with_the_hour_they_are_stamped_on(self):
        store = fw.WeatherStore()
        data = self.payload()
        data["hourly"]["wind_gusts_10m"][:4] = [99, 8, 25, 6]
        data["hourly"]["precipitation"][:4] = [99, .2, 4, 0]
        data["hourly"]["wind_speed_10m"][:4] = [7, 5, 20, 9]
        response = mock.Mock()
        response.json.return_value = data
        with mock.patch.object(fw.requests, "get", return_value=response):
            got = store.get(request())
        # Same index as wind, temperature and weather code: no one-hour shift.
        self.assertEqual([h.gust_mph for h in got.hours[:4]], [99, 8, 25, 6])
        self.assertEqual([h.precipitation_mm for h in got.hours[:4]], [99, .2, 4, 0])
        self.assertEqual([h.start for h in got.hours[:4]],
                         [datetime.fromtimestamp(t, timezone.utc) for t in data["hourly"]["time"][:4]])
        # The ending date's last hour is retained; a shift previously dropped it.
        self.assertEqual(len(got.hours), len(data["hourly"]["time"]))
        self.assertEqual(got.hours[-1].start, datetime.fromtimestamp(data["hourly"]["time"][-1], timezone.utc))

    def test_day_boundary_hour_belongs_to_its_own_date(self):
        # Open-Meteo's daily precipitation_sum equals the sum of hourly values
        # sharing that calendar date; a midnight value shifted into the previous
        # day was the live bug.
        store = fw.WeatherStore()
        data = self.payload()
        times = data["hourly"]["time"]
        midnight = next(i for i, t in enumerate(times)
                        if datetime.fromtimestamp(t, timezone.utc).hour == 0)
        data["hourly"]["precipitation"][midnight - 1] = 0.0
        data["hourly"]["precipitation"][midnight] = 0.4
        response = mock.Mock()
        response.json.return_value = data
        with mock.patch.object(fw.requests, "get", return_value=response):
            got = store.get(request())
        day = datetime.fromtimestamp(times[midnight], timezone.utc).date()
        total = sum(h.precipitation_mm for h in got.hours if h.start.date() == day)
        self.assertAlmostEqual(total, 0.4)
        self.assertAlmostEqual(got.hours[midnight].precipitation_mm, 0.4)
        self.assertAlmostEqual(got.hours[midnight - 1].precipitation_mm, 0.0)

    def test_duplicate_hours_and_provider_failures_are_unavailable(self):
        store = fw.WeatherStore()
        response = mock.Mock()
        data = self.payload()
        data["hourly"]["time"][1] = data["hourly"]["time"][0]
        response.json.return_value = data
        with mock.patch.object(fw.requests, "get", return_value=response):
            self.assertIsNone(store.get(request()))
        with mock.patch.object(fw.requests, "get", side_effect=fw.requests.Timeout()):
            self.assertIsNone(store.get(request()))

    def test_unit_mismatch_does_not_reinterpret_weather_thresholds(self):
        store = fw.WeatherStore()
        data = self.payload()
        data["hourly_units"]["wind_gusts_10m"] = "km/h"
        response = mock.Mock()
        response.json.return_value = data
        with mock.patch.object(fw.requests, "get", return_value=response):
            self.assertIsNone(store.get(request()))


if __name__ == "__main__":
    unittest.main()
