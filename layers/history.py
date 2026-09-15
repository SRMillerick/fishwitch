"""Weather history layer — the hindsight the model was missing.

60-75 days of daily hi/lo from Open-Meteo's free archive API, then:
  - heat/cold streaks (real, not 2-day guess)
  - est. surface temp series (7-day mean air − small-lake bias)
  - TURNOVER INFERENCE: a sharp cold anomaly that pulls est. surface below
    the lake's mixing trigger = probable turnover/mixing event, ±a few days.

This would have flagged HVL as post-turnover on Sep 9 using only data that
existed before the trip (cold bout Aug 28–Sep 3, est surface 75→64°F).
"""
from __future__ import annotations
from datetime import datetime, timedelta
import requests

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
UA = {"User-Agent": "fishwitch-mvp/1.0"}


def _c2f(c): return c * 9 / 5 + 32


class History:
    def __init__(self, lat: float, lng: float, end: datetime, days: int = 75):
        # the ERA5 archive lags ~5 days behind — clamp to what exists
        max_end = datetime.utcnow().date() - timedelta(days=5)
        end_d = min(end.date(), max_end)
        start_d = end_d - timedelta(days=days)
        r = requests.get(ARCHIVE, params=dict(
            latitude=lat, longitude=lng,
            start_date=start_d.strftime("%Y-%m-%d"),
            end_date=end_d.strftime("%Y-%m-%d"),
            daily="temperature_2m_max,temperature_2m_min",
            timezone="auto",
        ), headers=UA, timeout=20)
        r.raise_for_status()
        d = r.json()["daily"]
        self.series = [dict(
            date=datetime.fromisoformat(t),
            tmax=_c2f(d["temperature_2m_max"][i]),
            tmin=_c2f(d["temperature_2m_min"][i]),
        ) for i, t in enumerate(d["time"])]

    # ── streaks ───────────────────────────────────────────────────────────
    def heat_streak(self, threshold=90) -> int:
        n = 0
        for day in reversed(self.series):
            if round(day["tmax"]) >= threshold:
                n += 1
            else:
                break
        return n

    # ── surface-temp proxy ────────────────────────────────────────────────
    def est_surface(self, day_i: int, bias_f: float = 4.0, window: int = 7) -> float | None:
        """Small shallow lakes track ~7-day mean air temp, a few degrees under."""
        if day_i < 0:
            return None
        lo = max(0, day_i - window + 1)
        chunk = self.series[lo:day_i + 1]
        if not chunk:
            return None
        return sum((c["tmax"] + c["tmin"]) / 2 for c in chunk) / len(chunk) - bias_f

    def surface_series(self, bias_f=4.0) -> list[tuple[datetime, float | None]]:
        return [(d["date"], self.est_surface(i, bias_f)) for i, d in enumerate(self.series)]

    # ── turnover inference ────────────────────────────────────────────────
    def infer_turnover(self, trigger_f: float = 68.0, anomaly_f: float = 12.0,
                       min_prior_warm_days: int = 14, bias_f: float = 4.0) -> dict | None:
        """First sharp cold anomaly that drags est. surface below `trigger_f`
        after a sustained warm stretch = probable fall mixing. The anomaly
        typically peaks a few days AFTER the surface first drops, so the
        warm-run is counted over the whole prior month, not reset daily."""
        for i in range(len(self.series)):
            s = self.est_surface(i, bias_f)
            recent = [c["tmax"] for c in self.series[max(0, i - 2):i + 1]]
            prior_mean = sum(recent) / len(recent) if recent else None
            trail = [c["tmax"] for c in self.series[max(0, i - 14):i]]
            trail_mean = sum(trail) / len(trail) if trail else None
            if s is None or prior_mean is None or trail_mean is None:
                continue
            if s >= trigger_f:
                continue
            cold_anomaly = (trail_mean - prior_mean) >= anomaly_f
            if not cold_anomaly:
                continue
            warm_days_prior = sum(
                1 for j in range(max(0, i - 30), i)
                if self.est_surface(j, bias_f) is not None and self.est_surface(j, bias_f) > trigger_f + 4
            )
            if warm_days_prior >= min_prior_warm_days:
                return dict(date=self.series[i]["date"],
                            confidence="inferred (±3 days)",
                            evidence=(f"est surface fell to {s:.0f}°F (trigger {trigger_f:.0f}°F) "
                                      f"during a cold anomaly (3-day mean {prior_mean:.0f}°F vs "
                                      f"{trail_mean:.0f}°F trailing norm) after {warm_days_prior} "
                                      f"warm days in the prior month"))
        return None
