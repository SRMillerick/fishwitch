"""Reset prerequisites, using synthetic sky motion and birth details only."""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import chart
import report
import webapp
from skycalc import Sky


class AspectGeometryTest(unittest.TestCase):
    def aspects(self, target, direction=1, hours=2, natal_lon=0):
        natal = SimpleNamespace(points={"Venus": natal_lon}, time_known=True)
        # One degree/day; exact event one hour after the start (JD 100).
        def longitude(jd, body):
            return ((natal_lon + target + direction * (jd - 100 - 1 / 24)) % 360,
                    direction)
        with mock.patch.object(chart, "BODIES", ["Moon"]), \
                mock.patch.object(chart, "ANGLES", ["Venus"]), \
                mock.patch.object(chart, "planet_lon", side_effect=longitude):
            return chart.transit_aspects(natal, 100, hours)

    def test_both_orientations_direct_and_retrograde(self):
        for angle in (0, 60, -60, 90, -90, 120, -120, 180):
            for direction in (-1, 1):
                with self.subTest(angle=angle, direction=direction):
                    rows = self.aspects(angle, direction)
                    self.assertEqual(len(rows), 1)
                    self.assertAlmostEqual(rows[0]["perfect_jd"], 100 + 1 / 24)

    def test_conjunction_across_zodiac_wrap(self):
        self.assertAlmostEqual(self.aspects(0, natal_lon=359.99)[0]["perfect_jd"],
                               100 + 1 / 24)

    def test_microseconds_survive_julian_conversion(self):
        sky = Sky(0, 0, 0, 0)
        at = datetime(2026, 1, 1, 9, 30, 0, 500000)
        self.assertLess(abs((sky.loc(sky.jd(at)) - at).total_seconds()), 0.00005)

    def test_no_perfection_after_search_window(self):
        self.assertIsNone(self.aspects(60, hours=0.5)[0]["perfect_jd"])

    def test_session_end_excluded(self):
        self.assertIsNone(self.aspects(60, hours=1)[0]["perfect_jd"])

    def test_unrounded_orb(self):
        self.assertAlmostEqual(self.aspects(60)[0]["orb"], 1 / 24)

    def test_unknown_birth_time_has_no_precise_transits(self):
        natal = SimpleNamespace(time_known=False, points={})
        with mock.patch.object(chart, "planet_lon", side_effect=AssertionError("sky called")):
            self.assertEqual(chart.transit_aspects(natal, 100), [])
            self.assertIsNone(chart.phase_resonance(natal, 100))

    def test_voc_negative_orientation_and_ingress_boundary(self):
        for angle in (-60, -90, -120, 0, 180):
            with self.subTest(angle=angle):
                def longitude(jd, body):
                    return ((angle + (jd - 100 - 1 / 24)) % 360, 1) if body == "Moon" else (0, 0)
                sky = SimpleNamespace(moon_ingress=lambda jd: 100 + 3 / 24,
                                      jd=lambda value: value,
                                      loc=lambda jd: datetime(2026, 1, 1) + timedelta(days=jd - 100))
                with mock.patch.object(chart, "BODIES", ["Moon", "Sun"]), \
                        mock.patch.object(chart, "planet_lon", side_effect=longitude):
                    self.assertFalse(chart.voc_moon(100, sky)["void"])
                    sky.moon_ingress = lambda jd: 100 + 0.5 / 24
                    self.assertTrue(chart.voc_moon(100, sky)["void"])


def birth(**overrides):
    value = dict(date="1990-01-15", time="08:30", time_known=True,
                 lat=38.0, lng=-122.0, tz="America/Los_Angeles", place="Synthetic")
    value.update(overrides)
    return value


class BirthPrecisionTest(unittest.TestCase):
    def validate(self, **overrides):
        return webapp._client_profile({"profile": {"birth": birth(**overrides)}})

    def test_unknown_time_without_noon_placeholder_is_valid(self):
        profile, errors = self.validate(time=None, time_known=False)
        self.assertEqual(errors, [])
        self.assertIsNone(profile["birth"]["time"])

    def test_non_boolean_precision_rejected(self):
        for precision in ("false", "true", 0, 1, []):
            self.assertTrue(self.validate(time_known=precision)[1])

    def test_missing_coordinates_and_timezone_rejected(self):
        for field in ("lat", "lng", "tz"):
            value = birth()
            del value[field]
            self.assertTrue(webapp._client_profile({"profile": {"birth": value}})[1], field)

    def test_invalid_timezone_rejected(self):
        self.assertTrue(self.validate(tz="Not/A_Timezone")[1])

    def test_dst_gap_and_fold_rejected(self):
        for date, time in (("2000-04-02", "02:30"), ("2000-10-29", "01:30")):
            self.assertTrue(self.validate(date=date, time=time)[1])

    def test_historical_offset_used(self):
        local = chart.birth_datetime(birth(date="1945-01-15"))
        self.assertEqual(local.utcoffset(), timedelta(hours=-7))
        local = chart.birth_datetime(birth(date="1990-01-15"))
        self.assertEqual(local.utcoffset(), timedelta(hours=-8))

    def test_unknown_time_never_builds_noon_chart(self):
        with mock.patch.object(chart.AstrologicalSubjectFactory, "from_birth_data") as construct:
            with self.assertRaisesRegex(ValueError, "known birth time"):
                chart.NatalChart(birth(time_known=False))
            construct.assert_not_called()


class ReportTemporalTest(unittest.TestCase):
    def generate(self, event_hours=1, unknown=False, symbol="□"):
        start = datetime(2026, 1, 1, 8)
        sky = mock.MagicMock()
        sky.jd.side_effect = lambda dt: 100 + (dt - start).total_seconds() / 86400
        sky.loc.side_effect = lambda jd: start + timedelta(days=jd - 100)
        sky.sun_events_for_day.return_value = {"sunset": start.replace(hour=18)}
        sky.moon_state.return_value = {}
        sky.moon_rise_set.return_value = (None, None)
        sky.solunar.return_value = []
        sky.phase_quality.return_value = (0, "neutral")
        sky.planetary_hours.return_value = []
        sky.light_level.return_value = ("bright day", 40)
        sky.hour_at.return_value = {"ruler": "Saturn"}
        wx = mock.MagicMock(utc_offset=0)
        wx.at.return_value = dict(temp_f=60, cloud=20, wind_mph=0)
        wx.score.return_value = dict(score=5, trend={"word": "steady"})
        wx.series.return_value = [wx.at.return_value]
        wx.est_water_f.return_value = None
        wx.water_trend_f_per_week.return_value = None
        hist = mock.MagicMock()
        hist.heat_streak.return_value = 0
        hist.infer_turnover.return_value = None
        aspect = dict(transit="Moon", natal="Venus", aspect="square", sym=symbol,
                      perfect_jd=100 + event_hours / 24)
        patches = [
            mock.patch.object(report, "Sky", return_value=sky),
            mock.patch.object(report, "NatalChart"),
            mock.patch.object(report, "transit_aspects", return_value=[aspect]),
            mock.patch.object(report, "phase_resonance", return_value=None),
            mock.patch.object(report, "voc_moon", return_value={"void": False}),
            mock.patch.object(report, "moon_note", return_value=None),
            mock.patch.object(report, "model_agreement", return_value=None),
            mock.patch("layers.watertemp.nearest_water_temp", return_value=None),
            mock.patch("layers.stocking.recent", return_value=None),
            mock.patch.object(report.lb, "summary_for", return_value=None),
            mock.patch.object(report.tx, "catalog", return_value=[]),
            mock.patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
        ]
        from contextlib import ExitStack
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch) for patch in patches]
            model = report.generate({"birth": birth(time_known=not unknown)},
                                    {"name": "Synthetic", "lat": 38, "lng": -122},
                                    start, hours=2, wx=wx, hist=hist)
            if unknown:
                mocks[1].assert_not_called()
                mocks[2].assert_not_called()
            return model

    def test_out_of_session_event_has_no_bonus_or_claim(self):
        m = self.generate(event_hours=3)
        self.assertEqual(m["perfecting"], [])
        self.assertEqual(m["scores"]["astro"], 5)
        self.assertFalse(any(kind == "aspect" for _, _, kind in m["events"]))

    def test_exact_boundary_counted_once_and_preserved(self):
        m = self.generate()
        self.assertEqual(len(m["perfecting"]), 1)
        events = [e for block in m["blocks"] for e in block["event_data"] if e[2] == "aspect"]
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual((events[0][0] - m["start"]).total_seconds(), 3600, places=3)
        self.assertEqual(m["prime"]["start"].hour, 9)

    def test_end_excluded_start_included(self):
        self.assertEqual(self.generate(event_hours=2)["perfecting"], [])
        self.assertEqual(len(self.generate(event_hours=0)["perfecting"]), 1)

    def test_unknown_time_is_shared_only(self):
        m = self.generate(unknown=True)
        self.assertIsNone(m["natal"])
        self.assertIsNone(m["resonance"])
        self.assertEqual(m["perfecting"], [])
        self.assertFalse(m["personalized"])

    def test_nearby_events_keep_their_own_time_and_kind(self):
        m = self.generate(event_hours=0.02)
        events = [e for b in m["blocks"] for e in b["event_data"] if e[2] == "aspect"]
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual((events[0][0] - m["start"]).total_seconds(), 72, places=3)
        self.assertEqual(sum(len(b["aspects"]) for b in m["blocks"]), 1)
        self.assertTrue(all((b["end"] - b["start"]).total_seconds() >= 8 * 60 for b in m["blocks"]))

    def test_scoring_does_not_read_display_labels(self):
        first = self.generate()
        renamed = self.generate(symbol="renamed for display")
        self.assertEqual(first["scores"], renamed["scores"])
        self.assertEqual(first["prime_score"], renamed["prime_score"])
        self.assertEqual(first["prime"]["start"], renamed["prime"]["start"])


class RequestIdentityTest(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()
        self.clear = mock.patch.object(webapp, "_RCACHE", {})
        self.clear.start()
        self.addCleanup(self.clear.stop)
        self.rate = mock.patch.object(webapp, "_rate_ok", return_value=True)
        self.rate.start()
        self.addCleanup(self.rate.stop)

    def test_same_named_pins_do_not_share_outlook_results(self):
        def pin(lat, lng):
            return dict(name="Same water", lat=float(lat), lng=float(lng), tz="Etc/UTC")
        with mock.patch.object(webapp, "_pin_lake", side_effect=pin), \
                mock.patch.object(webapp, "_horizon", return_value=([], [])) as horizon:
            for coords in ((1, 2), (3, 4), (1, 2)):
                self.assertEqual(self.client.get(f"/outlook?lat={coords[0]}&lng={coords[1]}").status_code, 200)
            self.assertEqual(horizon.call_count, 2)

    def test_cache_key_covers_timezone_and_rules(self):
        lake = dict(name="Same water", lat=1, lng=2, tz="Etc/UTC")
        base = webapp._outlook_key(lake, 3, None)
        for changed in (dict(lake, tz="Europe/London"), dict(lake, access={"close": "18:00"})):
            self.assertNotEqual(webapp._outlook_key(changed, 3, None), base)

    def test_personal_ledger_never_enters_shared_result_cache(self):
        with mock.patch.object(webapp, "_ledger", return_value=[]) as ledger:
            for _ in range(2):
                r = self.client.post("/api/outlook", json={"profile": {"birth": birth()}})
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json["personalized"])
                self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertEqual(ledger.call_count, 2)
            self.assertEqual(webapp._RCACHE, {})

    def test_unknown_time_and_equipment_only_are_shared_only(self):
        with mock.patch.object(webapp, "_ledger", return_value=[]):
            for profile in ({"birth": birth(time_known=False)}, {"arsenal": ["dropshot"]}):
                r = self.client.post("/api/outlook", json={"profile": profile})
                self.assertFalse(r.json["personalized"])

    def test_failed_personal_request_is_redacted_and_no_store(self):
        with mock.patch.object(webapp, "_ledger", side_effect=ValueError("synthetic-private-name")):
            r = self.client.post("/api/outlook", json={"profile": {"birth": birth()}})
            self.assertEqual(r.status_code, 503)
            self.assertNotIn("synthetic-private-name", r.get_data(as_text=True))
            self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_linked_trip_populates_form_and_native_get_preserves_it(self):
        with mock.patch.object(webapp, "_report_response", return_value={"error": "fixture"}) as render:
            for query in ("at=2026-11-01T09:45", "date=2026-11-01&time=09:45"):
                html = self.client.get("/report?lake=clear-lake&hours=2&" + query).get_data(as_text=True)
                self.assertIn('name="date" value="2026-11-01"', html)
                self.assertIn('name="time" value="09:45"', html)
                self.assertIn("2026-11-01", render.call_args.args[0]["at"])

    def test_invalid_explicit_selection_never_renders_another_trip(self):
        with mock.patch.object(webapp, "_render_report") as render:
            for update in ({"lake": "unknown-water"}, {"at": "bad-date"},
                           {"at": "2020-01-01 09:00"}, {"hours": "nan"},
                           {"hours": "bad"}, {"hours": 0}, {"hours": 9},
                           {"lat": "bad", "lng": 0, "lake": ""}, {"at": [1]}):
                payload = dict(lake="clear-lake", at="", hours=2)
                payload.update(update)
                self.assertIn("error", webapp._report_response(payload, anonymous=True))
            render.assert_not_called()

    def test_zero_coordinate_is_valid_and_not_a_default_water(self):
        lake = dict(name="Synthetic equator", lat=0, lng=1)
        with mock.patch.object(webapp, "_pin_lake", return_value=lake) as pin, \
                mock.patch.object(webapp, "_render_report", return_value={}) as render:
            webapp._report_response(dict(lat=0, lng=1), anonymous=True)
            pin.assert_called_once_with(0, 1)
            self.assertEqual(render.call_args.args[1], lake)

    def test_report_failures_do_not_echo_private_exception(self):
        with mock.patch.object(webapp, "_render_report", side_effect=ValueError("synthetic-private-name")):
            response = self.client.post("/api/report", json={"profile": {"birth": birth()}})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("synthetic-private-name", response.get_data(as_text=True))
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_malformed_inputs_return_field_error_without_calculating(self):
        with mock.patch.object(webapp, "_render_report") as render, \
                mock.patch.object(webapp, "_ledger") as ledger:
            for route, payload in (("/api/report", [1]), ("/api/outlook", [1]),
                                   ("/api/report", {"at": 42}),
                                   ("/api/outlook", {"days": "bad"})):
                response = self.client.post(route, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)
            render.assert_not_called()
            ledger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
