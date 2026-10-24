"""Approved window policy: frozen synthetic data, no provider or real profiles."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
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
    return fc.SkyData(req.availability, tuple(shared), tuple(personal), {"fixture": "synthetic-v1"})


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
    def test_same_data_produces_same_ranking_and_text(self):
        req = request()
        data = sky(req, [event(req)])
        self.assertEqual(fc.calculate(req, snapshot(req), data), fc.calculate(req, snapshot(req), data))

    def test_half_open_event_membership_and_conflicts_caps(self):
        req = request()
        base = req.availability[0].start
        intervals = (fc.Interval(base, base + timedelta(hours=2)),
                     fc.Interval(base + timedelta(hours=2), base + timedelta(hours=4)))
        events = [event(req, minutes=120), event(req, minutes=0),
                  event(req, minutes=1, contribution=-1, aspect="square")]
        ranked = fc.rank_candidates(req, snapshot(req), sky(req, events), intervals)
        self.assertEqual([s.personal for s in ranked], [1, 0])
        self.assertEqual(sum(len(s.events) for s in ranked), 3)
        many = [event(req, minutes=i) for i in range(4)]
        self.assertEqual(fc.rank_candidates(req, snapshot(req), sky(req, many), intervals)[0].personal, 2)

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
        self.assertIn("does not distinguish", got["reason"])

    def test_zero_can_win_by_avoiding_negative_events_without_false_tie_claim(self):
        req = request()
        got = fc.calculate(req, snapshot(req), sky(req, [event(req, minutes=0, contribution=-1, aspect="square")]))
        self.assertEqual(got["recommended"]["personal_contribution"], 0)
        self.assertIn("more challenging", got["reason"])


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

    def test_gust_and_rain_use_the_preceding_hour_not_the_following_hour(self):
        store = fw.WeatherStore()
        data = self.payload()
        data["hourly"]["wind_gusts_10m"][:3] = [99, 8, 25]
        data["hourly"]["precipitation"][:3] = [99, .2, 4]
        response = mock.Mock()
        response.json.return_value = data
        with mock.patch.object(fw.requests, "get", return_value=response):
            got = store.get(request())
        self.assertEqual(got.hours[0].gust_mph, 8)
        self.assertEqual(got.hours[0].precipitation_mm, .2)
        self.assertEqual(got.hours[1].gust_mph, 25)
        self.assertEqual(got.hours[1].precipitation_mm, 4)

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
