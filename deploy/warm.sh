#!/bin/sh
# Keep the baromoon in-memory caches warm so the first real visitor gets an
# instant page. Six separate connections round-robin across gunicorn's two
# workers (new connection per curl), and ?warm=1 keeps these synthetic hits
# out of the aggregate page telemetry.
set -u
BASE="${BAROMOON_WARM_BASE:-http://127.0.0.1:7700}"
HIT="$BASE/?warm=1"
OUT="$BASE/outlook?lake=hidden-valley-lake-ca&days=10&warm=1"
REP="$BASE/report?lake=hidden-valley-lake-ca&warm=1"
for u in "$HIT" "$HIT" "$OUT" "$OUT" "$REP" "$REP"; do
  curl -sS --max-time 90 -o /dev/null "$u" || true
done
