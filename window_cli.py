"""The window CLI uses the same operation as POST /api/window.

Request JSON travels through stdin or an explicitly chosen file, never birth
flags or URLs. Optional weather/evaluation fixtures reproduce exact web results.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from fishwitch import forecast as engine
from fishwitch.forecast_weather import weather_store


def load_snapshot(data):
    return engine.WeatherSnapshot(float(data["lat"]), float(data["lng"]),
                                  engine.aware(datetime.fromisoformat(data["acquired_at"])),
                                  tuple(engine.WeatherHour(engine.aware(datetime.fromisoformat(row["start"])),
                                                          row.get("wind_mph"), row.get("gust_mph"),
                                                          row.get("precipitation_mm"), row.get("code"),
                                                          row.get("temperature_f"))
                                        for row in data["hours"]), data.get("provider", "fixture"))


def execute(payload, waters, evaluated_at, snapshot=None):
    req = engine.normalize_request(payload, waters, evaluated_at)
    return engine.calculate(req, snapshot if snapshot is not None else weather_store.get(req))


def main(argv=None):
    parser = argparse.ArgumentParser(description="One personal fishing window; canonical window-1 rules.")
    parser.add_argument("--request", default="-", help="request JSON file, or - for stdin")
    parser.add_argument("--weather", help="frozen UTC weather snapshot JSON; omitting it fetches current weather")
    parser.add_argument("--evaluated-at", help="explicit ISO timestamp with UTC offset for reproducibility")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin) if args.request == "-" else json.loads(Path(args.request).read_text())
        waters = json.loads((Path(__file__).resolve().parent / "config" / "lakes.json").read_text())
        at = datetime.fromisoformat(args.evaluated_at) if args.evaluated_at else datetime.now(timezone.utc)
        snapshot = load_snapshot(json.loads(Path(args.weather).read_text())) if args.weather else None
        result = execute(payload, waters, at, snapshot)
    except engine.InputError as exc:
        print(json.dumps(dict(error=exc.message, field=exc.field)))
        return 2
    except Exception:
        print(json.dumps(dict(error="Calculation unavailable. Check the request and weather inputs.", field="request")))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
