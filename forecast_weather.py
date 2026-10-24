"""One bounded current-weather acquisition; shared weather only, never births.

UTC hourly timestamps avoid duplicated/missing local hours at DST boundaries.
This module never requests archives, gauges, models, daily history, or enrichment.
"""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import math
from threading import Lock

import requests

from fishwitch.forecast import ForecastRequest, WeatherHour, WeatherSnapshot

URL = "https://api.open-meteo.com/v1/forecast"
PROVIDER = "open-meteo-forecast-v1"
FIELDS = ("temperature_2m", "wind_speed_10m", "wind_gusts_10m", "precipitation", "weather_code")
TIMEOUT = (2, 5)
MAX_ENTRIES = 128
TTL = timedelta(minutes=15)
UTC = timezone.utc


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


class WeatherStore:
    def __init__(self):
        self.cache = OrderedDict()
        self.lock = Lock()

    def get(self, req: ForecastRequest) -> WeatherSnapshot | None:
        start = req.availability[0].start.date().isoformat()
        # Gust maxima and precipitation sums are stamped at the *end* of their
        # preceding hour (https://open-meteo.com/en/docs). Include the ending
        # boundary, including midnight, so the final session hour has coverage.
        end = req.availability[-1].end.date().isoformat()
        params = dict(latitude=req.water.lat, longitude=req.water.lng,
                      start_date=start, end_date=end, timezone="UTC", timeformat="unixtime",
                      hourly=",".join(FIELDS), wind_speed_unit="mph", temperature_unit="fahrenheit")
        key = (URL, PROVIDER, tuple(sorted(params.items())))
        with self.lock:
            hit = self.cache.get(key)
            if hit and timedelta(0) <= req.evaluated_at - hit.acquired_at < TTL:
                self.cache.move_to_end(key)
                return hit
        try:
            response = requests.get(URL, params=params, timeout=TIMEOUT,
                                    headers={"User-Agent": "baromoon-window/1"})
            response.raise_for_status()
            payload = response.json()
            units = payload["hourly_units"]
            if (units.get("wind_speed_10m") not in ("mp/h", "mph")
                    or units.get("wind_gusts_10m") not in ("mp/h", "mph")
                    or units.get("precipitation") != "mm" or units.get("temperature_2m") != "°F"):
                return None
            data = payload["hourly"]
            times = data["time"]
            if not isinstance(times, list) or not 1 <= len(times) <= 216:
                return None
            if any(not isinstance(data.get(field), list) or len(data[field]) != len(times) for field in FIELDS):
                return None
            stamps = []
            for stamp in times:
                if number(stamp) is None:
                    return None
                at = datetime.fromtimestamp(stamp, UTC)
                if at.minute or at.second or at.microsecond:
                    return None
                stamps.append(at)
            if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
                return None
            rows = []
            for i, at in enumerate(stamps[:-1]):
                contiguous = stamps[i + 1] - at == timedelta(hours=1)
                rows.append(WeatherHour(at, number(data["wind_speed_10m"][i]),
                                        number(data["wind_gusts_10m"][i + 1]) if contiguous else None,
                                        number(data["precipitation"][i + 1]) if contiguous else None,
                                        number(data["weather_code"][i]),
                                        number(data["temperature_2m"][i])))
            snapshot = WeatherSnapshot(req.water.lat, req.water.lng, req.evaluated_at,
                                       tuple(sorted(rows, key=lambda row: row.start)), PROVIDER)
        except (requests.RequestException, KeyError, ValueError, TypeError, OverflowError):
            return None
        with self.lock:
            while len(self.cache) >= MAX_ENTRIES:
                self.cache.popitem(last=False)
            self.cache[key] = snapshot
        return snapshot


weather_store = WeatherStore()
