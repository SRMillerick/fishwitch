#!/usr/bin/env python3
"""Confidence calibration replay — READ-ONLY.

The live report shows a GFS/ECMWF/ICON agreement label; `weather.model_agreement()`
returns None for past windows, so the logbook replay has never carried the
confidence the angler actually saw. Open-Meteo's **Single Runs API** archives
the exact model runs (`&run=YYYY-MM-DDTHH:MM`), so for each graded session we
can fetch the newest run of each model that was *published* before the replay
window opened and rebuild the same spread/label.

This tool changes nothing. It joins those historical labels to `review.collect()`
grades so a human can judge whether model disagreement should soften scores.

    python tools/calibration_confidence.py [--hours 2.0] [--json] [--refresh]

Reads `config/logbook.jsonl` (PII, never leaves the box). Network: Single Runs
API, cached under `.cache/agreement/`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

import review  # noqa: E402
from weather import AGREE_MODELS, KPH_PER_MPH, _agree_label, _c2f  # noqa: E402

ENDPOINT = "https://single-runs-api.open-meteo.com/v1/forecast"
# The archive resolves `gfs_seamless` through a different member when POP is in
# the variable list (precipitation_probability → ncep_gefs05, which has no run
# history for these dates). The label only needs temp/wind/cloud; POP is
# display-only in the live function.
RUN_VARS = ("temperature_2m", "wind_speed_10m", "cloud_cover")
CACHE = ROOT / ".cache" / "agreement"
# typical publication lag after initialization, hours — conservative so we
# never use a run the planner could not have downloaded yet
RUN_LAG_H = {"gfs_seamless": 4, "ecmwf_ifs025": 7, "icon_seamless": 4}


def _candidate_runs(when_utc: datetime, model: str) -> list[datetime]:
    """Run initializations (UTC) newest-first that could be published by `when`."""
    t = when_utc - timedelta(hours=RUN_LAG_H.get(model, 4))
    t = t.replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=(t.hour // 6) * 6)   # snap to the 00/06/12/18 run cadence
    return [t - timedelta(hours=6 * i) for i in range(9)]


def _fetch_run(lat: float, lng: float, model: str, run: datetime) -> list[dict] | None:
    """One model run's hourly rows (local naive times, same as the live call)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / f"{model}_{run:%Y%m%dT%H%M}.json"
    if key.exists() and time.time() - key.stat().st_mtime < 86400:
        data = json.loads(key.read_text())
    else:
        data = {}
        for attempt in range(4):
            try:
                r = requests.get(ENDPOINT, params=dict(
                    latitude=lat, longitude=lng, timezone="auto",
                    hourly=",".join(RUN_VARS), models=model,
                    run=run.strftime("%Y-%m-%dT%H:%M")), timeout=30)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 400:
                break            # run does not exist (e.g. ECMWF 06/18 UTC) — no retry
            if r.ok:
                data = r.json()
                break
            time.sleep(2 * (attempt + 1))
        if data.get("hourly"):
            key.write_text(json.dumps(data))
        time.sleep(0.25)         # the archive storage is rate-friendly, not fast
    h = data.get("hourly") or {}
    times = [datetime.fromisoformat(t) for t in h.get("time", [])]
    if not times:
        return None
    return [dict(_t=times[i],
                 **{v: (h.get(v) or [None] * len(times))[i] for v in RUN_VARS})
            for i in range(len(times))]


def _series_for(lat: float, lng: float, model: str, when_utc: datetime,
                start: datetime, end: datetime):
    """First publishable run that covers [start, end] → ({time: row}, run)."""
    for run in _candidate_runs(when_utc, model):
        rows = _fetch_run(lat, lng, model, run)
        if not rows:
            continue
        window = [r for r in rows if start <= r["_t"] <= end]
        if window:
            return {r["_t"]: r for r in window}, run
    return None, None


def agreement_for(lat: float, lng: float, tz_name: str | None,
                  start: datetime, end: datetime) -> dict | None:
    """Reconstructed model agreement for a window — mirrors weather.model_agreement()."""
    tz = ZoneInfo(tz_name) if tz_name else None
    when_utc = (start.replace(tzinfo=tz) if tz else start).astimezone(timezone.utc)
    models = {}
    runs = {}
    for m in AGREE_MODELS:
        rows, run = _series_for(lat, lng, m, when_utc, start, end)
        if not rows:
            return None
        models[m] = rows
        runs[m] = run
    stamps = sorted(models[AGREE_MODELS[0]])

    def spread(var, convert=lambda v: v):
        vals = []
        for s in stamps:
            row = []
            for m in AGREE_MODELS:
                r = models[m].get(s)
                v = r.get(var) if r else None
                if v is not None:
                    row.append(convert(v))
            if len(row) >= 2:
                vals.append(max(row) - min(row))
        return round(sum(vals) / len(vals), 1) if vals else None

    temp = spread("temperature_2m", _c2f)
    wind = spread("wind_speed_10m", lambda v: v / KPH_PER_MPH)
    cloud = spread("cloud_cover")
    pop = None   # not archived for the seamless model id; display-only anyway
    label = _agree_label(temp, wind)
    if not label:
        return None
    return dict(label=label, models=len(AGREE_MODELS),
                temp_spread_f=temp, wind_spread_mph=wind,
                cloud_spread_pct=cloud, pop_spread_pct=pop,
                runs={m: runs[m].strftime("%m-%dT%H:%M") for m in runs})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=2.0,
                    help="replay window length, same convention as review (default 2.0)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    graded, skipped = review.collect(hours=args.hours)
    rows = []
    for g in graded:
        lk = review._lake_for(g["entry"], review._profile_for(g["entry"].get("angler")))
        if lk is None:
            continue
        ag = agreement_for(lk["lat"], lk["lng"], lk.get("tz"),
                           g["start"], g["end"])
        e = g["entry"]
        rows.append(dict(
            ts=g["ts"].isoformat(), lake=lk.get("name"), angler=e.get("angler"),
            label=(ag or {}).get("label"), temp=(ag or {}).get("temp_spread_f"),
            wind=(ag or {}).get("wind_spread_mph"), cloud=(ag or {}).get("cloud_spread_pct"),
            overall=g["overall"], pres=g["pres"] or ("skunk" if g["skunk"] else "?"),
            skunk=g["skunk"], catch_n=e.get("n_fish"), best=e.get("best_lb"),
            weight=e.get("total_lb"), lure=e.get("primary_lure"),
            bank=e.get("bank") or "",
            stacked=(g.get("shoreline") or {}).get("stacked"),
            lee=(g.get("shoreline") or {}).get("lee"),
            runs=(ag or {}).get("runs")))

    if args.json:
        print(json.dumps(dict(rows=rows, skipped=skipped), indent=1))
        return 0

    print(f"  confidence replay — {len(rows)} graded sessions "
          f"({len(skipped)} skipped) · historical Single Runs API")
    print(f"  {'session':16} {'angler':7} {'agr':6} {'temp':>5} {'wind':>5} "
          f"{'cloud':>5} {'over':>5}  grade   catch")
    for r in rows:
        catch = ("skunk" if r["skunk"] else
                 f"{r['catch_n'] or '?'} fish"
                 + (f" · {r['best']:g} lb" if r["best"] is not None else "")
                 + (f" ({r['lure']})" if r["lure"] else ""))
        print(f"  {r['ts'][:16]:16} {(r['angler'] or '?'):7} {(r['label'] or '?'):6} "
              f"{r['temp'] if r['temp'] is not None else '?':>5} "
              f"{r['wind'] if r['wind'] is not None else '?':>5} "
              f"{r['cloud'] if r['cloud'] is not None else '?':>5} "
              f"{r['overall']:>5}  {r['pres']:7} {catch}")

    labels = [r for r in rows if r["label"]]
    print("\n  by agreement label:")
    for lab in ("high", "medium", "low"):
        sub = [r for r in labels if r["label"] == lab]
        if not sub:
            continue
        grades = {k: sum(1 for r in sub if r["pres"] == k)
                  for k in ("exact", "style", "miss", "benched", "n/a", "skunk")}
        grades = {k: v for k, v in grades.items() if v}
        catches = [r for r in sub if not r["skunk"]]
        skunks = [r for r in sub if r["skunk"]]
        sep = (sum(r["overall"] for r in catches) / len(catches)
               - (sum(r["overall"] for r in skunks) / len(skunks))) if catches and skunks else None
        print(f"    {lab:6} n={len(sub):2}  "
              + " · ".join(f"{k} {v}" for k, v in grades.items())
              + (f"  | separation {sep:+.2f}" if sep is not None else ""))

    # ── wind-bank calibration: the bank the angler logged vs the replay's advice
    banked = [r for r in rows if r.get("bank") and r.get("stacked")]
    print("\n  wind-bank calibration (logged bank vs replay advice):")
    if not banked:
        print("    no bank annotations yet — record with `fishwitch log --bank N`"
              " or the /log form (the report's log link carries the advice)")
    else:
        groups: dict[str, list] = {"followed (stacked)": [], "lee": [], "other": []}
        for r in banked:
            key = ("followed (stacked)" if r["bank"] == r["stacked"]
                   else "lee" if r["bank"] == r["lee"] else "other")
            groups[key].append(r)
        for key, sub in groups.items():
            if not sub:
                continue
            catches = [r for r in sub if not r["skunk"]]
            skunks = [r for r in sub if r["skunk"]]
            avg = sum(r["overall"] for r in catches) / len(catches) if catches else None
            print(f"    {key:18} n={len(sub):2}  catches {len(catches)} · skunks {len(skunks)}"
                  + (f"  | avg window {avg:.1f}" if avg is not None else ""))
    print("\n  read-only: no scoring changed. n is small — treat as a first read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
