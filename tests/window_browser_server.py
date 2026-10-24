"""Local browser fixture server. Never used by the production launcher.

Only synthetic birthplaces and generated hourly weather; no outbound requests.
"""
from datetime import timedelta
import logging
import time
from unittest import mock

from flask import jsonify, request
import webapp
from fishwitch.forecast import WeatherHour, WeatherSnapshot

fixture = {"mode": "normal", "delay": False, "legacy_sw": False}


# Reproduce the deployed v3 worker's caching behavior on this disposable origin.
# No production endpoint or runtime configuration exposes this fixture switch.
_original_service_worker = webapp.service_worker


def fixture_service_worker():
    response = _original_service_worker()
    if fixture["legacy_sw"]:
        response.set_data(response.get_data(as_text=True).replace('"baromoon-v4"', '"baromoon-v3"').replace(
            '  if (url.pathname === "/" || url.pathname.startsWith("/api/")) return;\n', ''))
    return response


webapp.app.view_functions["service_worker"] = fixture_service_worker


def places(query, **kwargs):
    if query == "Slow City":
        time.sleep(.8)
    if query == "No Match":
        return []
    return [dict(name=query, region="Fixture", country="Test", lat=38, lng=-122, tz="America/Los_Angeles"),
            dict(name=query, region="Other Fixture", country="Test", lat=40, lng=-74, tz="America/New_York")]


def weather(req):
    if fixture["delay"]:
        delay = float(fixture["delay"])
        fixture["delay"] = False
        time.sleep(.8 if delay == 1 else delay)
    if fixture["mode"] == "offline":
        return None
    start = req.evaluated_at.replace(hour=0, minute=0, second=0, microsecond=0)
    return WeatherSnapshot(req.water.lat, req.water.lng, req.evaluated_at,
                           tuple(WeatherHour(start + timedelta(hours=i), 5,
                                             25 if fixture["mode"] == "storm" else 8,
                                             0, 0, 60) for i in range(216)), "synthetic-browser-fixture")


@webapp.app.route("/__fixture", methods=["POST"])
def fixture_control():
    data = request.get_json()
    fixture.update(mode=data.get("mode", "normal"), delay=data.get("delay", False),
                   legacy_sw=data.get("legacy_sw", fixture["legacy_sw"]))
    return jsonify(ok=True)


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with mock.patch.object(webapp.window_weather, "get", side_effect=weather), \
            mock.patch("fishwitch.geo.geocode_city", side_effect=places), \
            mock.patch.object(webapp, "_rate_ok", return_value=True), \
            mock.patch("requests.sessions.Session.request", side_effect=AssertionError("Browser fixture forbids external HTTP")):
        webapp.app.run(host="127.0.0.1", port=7781, threaded=True, use_reloader=False)
