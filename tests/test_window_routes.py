"""Minimal web/CLI path: no legacy enrichment, PII caching, or body logging."""
from dataclasses import asdict
from datetime import timedelta
import json
import unittest
from unittest import mock

import webapp
import window_cli
from zoneinfo import ZoneInfo
from tests.test_forecast import BIRTH, NOW, WATERS, request, snapshot


class WindowRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()
        self.rate = mock.patch.object(webapp, "_rate_ok", return_value=True)
        self.rate.start()
        self.addCleanup(self.rate.stop)

    def payload(self):
        return dict(water_id="synthetic", birth=BIRTH, request_id="fixture-1", daylight=False,
                    availability=[dict(start="2026-10-23T08:00", end="2026-10-23T16:00")], duration_minutes=120)

    def test_get_is_only_a_small_form_and_has_no_forecast_or_analytics(self):
        with mock.patch.object(webapp, "gen", side_effect=AssertionError("report")), \
                mock.patch.object(webapp, "_ledger", side_effect=AssertionError("ledger")), \
                mock.patch.object(webapp.window_weather, "get", side_effect=AssertionError("weather")), \
                mock.patch.object(webapp.telemetry, "record") as record:
            response = self.client.get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        record.assert_not_called()
        self.assertIn('id="window-form"', html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("/static/app.js", html)
        self.assertNotIn("leaflet", html)
        self.assertNotIn('id="profile-menu"', html)
        self.assertIn('id="result"', html)

    def test_every_registry_water_has_an_explicit_valid_timezone(self):
        for water in webapp.registry().values():
            self.assertTrue(ZoneInfo(water["tz"]))

    def test_web_cli_and_frozen_core_agree_without_caching_personal_results(self):
        clock = mock.Mock()
        clock.now.return_value = NOW
        with mock.patch.object(webapp, "registry", return_value=WATERS), \
                mock.patch.object(webapp, "datetime", clock), \
                mock.patch.object(webapp.window_weather, "get", return_value=snapshot()), \
                mock.patch.object(webapp, "_cached", side_effect=AssertionError("result cache")), \
                mock.patch.object(webapp, "gen", side_effect=AssertionError("legacy report")), \
                mock.patch.object(webapp, "shared_history", side_effect=AssertionError("history")), \
                mock.patch.object(webapp.telemetry, "record") as record:
            response = self.client.post("/api/window", json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, window_cli.execute(self.payload(), WATERS, NOW, snapshot()))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(BIRTH["date"], response.get_data(as_text=True))
        self.assertEqual(response.json["reading_version"], "horoscope-1")
        self.assertTrue(response.json["recommended"]["reading"]["entries"])
        record.assert_not_called()

    def test_invalid_requests_fail_before_weather(self):
        with mock.patch.object(webapp.window_weather, "get") as get:
            for payload in ([], {}, dict(self.payload(), water_id="missing")):
                response = self.client.post("/api/window", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            get.assert_not_called()

    def test_out_of_range_dates_are_actionable_before_weather_acquisition(self):
        clock = mock.Mock()
        clock.now.return_value = NOW
        payload = dict(self.payload(), availability=[dict(start="2026-10-28T08:00", end="2026-10-28T16:00")])
        with mock.patch.object(webapp, "registry", return_value=WATERS), \
                mock.patch.object(webapp, "datetime", clock), \
                mock.patch.object(webapp.window_weather, "get") as get:
            response = self.client.post("/api/window", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["field"], "availability")
        self.assertIn("2026-10-21 through 2026-10-27", response.json["error"])
        self.assertIn("both dates included", response.json["error"])
        self.assertNotIn(BIRTH["date"], response.get_data(as_text=True))
        get.assert_not_called()

    def test_provider_and_calculation_errors_are_redacted(self):
        clock = mock.Mock()
        clock.now.return_value = NOW
        with mock.patch.object(webapp, "registry", return_value=WATERS), \
                mock.patch.object(webapp, "datetime", clock), \
                mock.patch.object(webapp.window_weather, "get", side_effect=ValueError("synthetic-private-data")):
            response = self.client.post("/api/window", json=self.payload())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("synthetic-private-data", response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_birthplace_provider_receives_no_birth_details_and_no_retry(self):
        from fishwitch import geo
        response = mock.Mock()
        response.json.return_value = {"results":[dict(name="Synthetic", latitude=38, longitude=-122, timezone="America/Los_Angeles")]}
        with mock.patch.object(geo.requests, "get", return_value=response) as get:
            result = self.client.post("/api/window/place", json=dict(query="Synthetic", birth=BIRTH))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["timeout"], (2, 5))
        self.assertNotIn(BIRTH["date"], json.dumps(get.call_args.kwargs))
        self.assertEqual(get.call_args.kwargs["params"]["name"], "Synthetic")

    def test_proxy_rate_buckets_use_one_trusted_loopback_hop(self):
        with mock.patch.object(webapp, "_rate_ok", return_value=True) as rate:
            for client_ip in ("192.0.2.10", "192.0.2.11"):
                self.client.post("/api/window", json={},
                                 environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
                                 headers={"X-Forwarded-For": "198.51.100.99, " + client_ip})
            self.assertEqual([c.args[0] for c in rate.call_args_list],
                             ["window:192.0.2.10", "window:192.0.2.11"])

    def test_untrusted_direct_peer_cannot_spoof_rate_bucket(self):
        with mock.patch.object(webapp, "_rate_ok", return_value=True) as rate:
            self.client.post("/api/window/place", json={},
                             environ_overrides={"REMOTE_ADDR": "192.0.2.20"},
                             headers={"X-Forwarded-For": "198.51.100.99"})
            self.assertEqual(rate.call_args.args[0], "window-place:192.0.2.20")

    def test_proxy_without_forwarded_header_uses_peer(self):
        with mock.patch.object(webapp, "_rate_ok", return_value=True) as rate:
            self.client.post("/api/window", json={},
                             environ_overrides={"REMOTE_ADDR": "::1"})
            self.assertEqual(rate.call_args.args[0], "window:::1")

    def test_cli_snapshot_loader_preserves_utc_and_values(self):
        data = asdict(snapshot())
        data["acquired_at"] = data["acquired_at"].isoformat()
        for row in data["hours"]:
            row["start"] = row["start"].isoformat()
        self.assertEqual(window_cli.load_snapshot(data), snapshot())


if __name__ == "__main__":
    unittest.main()
