"""Weather layer — Open-Meteo forecast, pressure trend, water-temp estimate.

All datetimes in the hourly/daily series are NAIVE LOCAL time for the lake's tz
(Open-Meteo returns them that way when timezone=auto). utc_offset_seconds is
kept so the sky math can convert to UT.
"""
from __future__ import annotations
import math
from datetime import datetime, timedelta
import requests

FORECAST = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m", "apparent_temperature", "relative_humidity_2m",
          "precipitation_probability", "precipitation", "weather_code", "cloud_cover",
          "visibility", "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m",
          "pressure_msl", "uv_index"]
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"]

KPH_PER_MPH = 1.609344


def _c2f(c): return c * 9 / 5 + 32


class Weather:
    def __init__(self, lat: float, lng: float, forecast_days: int = 3,
                 past_days: int = 2):
        r = requests.get(FORECAST, params=dict(
            latitude=lat, longitude=lng, timezone="auto",
            past_days=past_days, forecast_days=forecast_days,
            hourly=",".join(HOURLY), daily=",".join(DAILY),
        ), headers={"User-Agent": "fishwitch-mvp/1.0"}, timeout=15)
        r.raise_for_status()
        j = r.json()
        self.tz = j["timezone"]
        self.utc_offset = int(j["utc_offset_seconds"])
        h = j["hourly"]
        self.hourly = [dict(
            dt=datetime.fromisoformat(h["time"][i]),
            temp_f=_c2f(h["temperature_2m"][i]),
            feels_f=_c2f(h["apparent_temperature"][i]),
            rh=h["relative_humidity_2m"][i],
            pop=h["precipitation_probability"][i] or 0,
            precip=h["precipitation"][i] or 0,
            code=h["weather_code"][i],
            cloud=h["cloud_cover"][i] or 0,
            wind_mph=(h["wind_speed_10m"][i] or 0) / KPH_PER_MPH,
            gust_mph=(h["wind_gusts_10m"][i] or 0) / KPH_PER_MPH,
            dir=h["wind_direction_10m"][i] or 0,
            press=h["pressure_msl"][i],
        ) for i in range(len(h["time"]))]
        d = j["daily"]
        self.daily = [dict(
            dt=datetime.fromisoformat(d["time"][i]),
            tmax_f=_c2f(d["temperature_2m_max"][i]),
            tmin_f=_c2f(d["temperature_2m_min"][i]),
            pop=d["precipitation_probability_max"][i] or 0,
        ) for i in range(len(d["time"]))]

    # ── lookups ────────────────────────────────────────────────────────────
    def at(self, dt: datetime) -> dict:
        """Snapshot at nearest hour to naive-local dt."""
        best = min(self.hourly, key=lambda x: abs((x["dt"] - dt).total_seconds()))
        return best

    def series(self, start: datetime, end: datetime) -> list[dict]:
        return [x for x in self.hourly if start <= x["dt"] <= end]

    def pressure_trend(self, dt: datetime) -> dict:
        """Pressure now vs 6h and 24h ago -> hPa delta + word."""
        now = self.at(dt)["press"] or 1013.0
        d6 = self.at(dt - timedelta(hours=6))["press"] or now
        d24 = self.at(dt - timedelta(hours=24))["press"] or now
        delta = now - d6
        delta24 = now - d24
        if delta24 < -4 or delta < -3:
            word = "falling fast"
        elif delta < -0.8:
            word = "slowly falling"
        elif delta > 3:
            word = "rising fast"
        elif delta > 0.8:
            word = "slowly rising"
        else:
            word = "steady"
        return dict(now=now, delta6=round(delta, 1), delta24=round(delta24, 1), word=word)

    def est_water_f(self, dt: datetime) -> float | None:
        """Rough surface-water estimate from trailing 3-day air means (+2F lag
        bias for small shallow lakes). Clearly an estimate — no buoy data."""
        prior = [d for d in self.daily if d["dt"] < dt.replace(hour=0, minute=0)]
        prior = prior[-3:]
        if len(prior) < 3:
            return None
        mean_air = sum((d["tmax_f"] + d["tmin_f"]) / 2 for d in prior) / 3
        return round(mean_air + 2, 0)

    def heat_streak(self, dt: datetime) -> int:
        """Consecutive days with tmax >= 90F ending at dt."""
        days = [d for d in self.daily if d["dt"] <= dt.replace(hour=23, minute=59)]
        n = 0
        for d in reversed(days):
            if d["tmax_f"] >= 90:
                n += 1
            else:
                break
        return n

    # ── scores used by the report ─────────────────────────────────────────
    def score(self, start: datetime, end: datetime) -> dict:
        win = self.series(start, end)
        if not win:
            win = [self.at(start)]
        cloud = sum(w["cloud"] for w in win) / len(win)
        wind = sum(w["wind_mph"] for w in win) / len(win)
        pop = max(w["pop"] for w in win)
        trend = self.pressure_trend(start)
        pts, notes = 0, []
        if cloud >= 80:
            pts += 3; notes.append("overcast = fish roam shallow & chase (big plus)")
        elif cloud >= 40:
            pts += 2; notes.append("broken cloud softens the light (good)")
        else:
            pts += 1; notes.append("clear sky — fish tight to shade/structure")
        if 3 <= wind <= 12:
            pts += 2; notes.append(f"{wind:.0f} mph chop breaks up overhead predators (plus)")
        elif wind < 3:
            pts += 1; notes.append("glassy — quiet presentations only")
        elif wind <= 18:
            pts += 1; notes.append("windy — fish the protected wind-lane edges")
        else:
            pts += 0; notes.append("hard wind — safety first, fish lee shore")
        pts += {("slowly falling"): 2, ("steady"): 1, ("slowly rising"): 2,
                ("rising fast"): 1, ("falling fast"): 0}[trend["word"]]
        notes.append(f"barometer {trend['word']} ({trend['delta6']:+.1f} hPa/6h)")
        if pop >= 40:
            pts -= 2; notes.append(f"{pop}% rain chance — bring the shells")
        return dict(score=min(10, max(0, pts + 2)), cloud=cloud, wind=wind,
                    pop=pop, trend=trend, notes=notes)
