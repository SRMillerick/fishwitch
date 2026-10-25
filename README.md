# baromoon · fishwitch

A personal fishing almanac: birth details + one water + confirmed availability
produce one window, one personal reason, and a short conditions sentence.
The local replacement is implemented; no release or deployment is implied.

## Current application

Run `./webapp` and open `http://127.0.0.1:7700/`. Birth details, water, availability,
and results share one page. The first visit computes nothing until submission.
Defaults are next three days, daylight, and two-hour sessions, visibly editable
before submission. Seven days is the maximum. All trip times use the selected
water's IANA timezone, including DST changes. Unknown birth time or no birth data
uses the shared almanac, without a placeholder natal chart.

`forecast.py` is the canonical, network-free calculation. `forecast_weather.py`
acquires one current hourly forecast, with bounded timeouts and a bounded public
weather cache. The new path never calls `report.generate()`, archives, gauges,
stocking, shoreline analysis, model agreement, catch calibration, or commerce.
The new page has one small JS/CSS pair and no third-party font, UI, map, or
analytics requests. Existing deployment machinery and dependencies are retained.

**Approved rules (`window-2`):** Moon sextile/trine natal Moon, Venus, or Jupiter
contributes positively; square/opposition contributes negatively. Each weight
fades linearly from 1 at exact to 0 at 2° away, equally before and after exact.
Average each signed weight across the complete elapsed session, sum, then cap
at ±2. A peak outside the trip can still contribute. Exact-event timestamps are
metadata, not scoring gates. Five-minute positions and refined crossings provide
the integration samples; overlapping candidates share only request-local work.
No houses, angles, returns, lunar-phase resonance, sign lore, or planetary-hour
bonuses participate. Weather bands precede personal timing, shared solunar-major
overlap, minor overlap, lower gusts, lower precipitation, and earlier absolute
start. Missing/stale weather is explicit; weather screening is no safety guarantee.
Interpretation is not established catch probability. Identical personal scores
use shared conditions; zero may also win by avoiding negative alignments.

The `horoscope-1` reading follows the whole session and shows its two closest
approaches within 2°, using the existing authored mindset/action wording. Its
slider shows alignment closeness, not mood intensity. A separate timeline under
Why shows the lunar contacts used for timing. Horoscope interpretations do not
participate in ranking. These versions are implemented locally; production
release status is recorded separately.

The existing installed ephemeris backend is **Moshier through Swiss Ephemeris**.
It is now explicit and checked, with binary/package/timezone fingerprints in
the result. Standard Swiss planetary/lunar files are not bundled here; the code
does not silently switch backend. Kerykeion remains pinned and supplies one
natal chart per request, using an exact historically resolved UTC birth instant.
Restart and revalidate workers after dependency or timezone-data changes.

**Privacy:** optional local device persistence; otherwise settings last for the
tab. Birth details are sent to the server in transient POST bodies, never URLs.
The application does not intentionally retain personal requests or results;
responses use `no-store`, and errors redact computation exceptions. Saved results
are never written to browser storage. Earlier profiles can be explicitly imported;
forgetting clears this page and the active earlier profile, preserving other profiles.

## Canonical API and CLI

`POST /api/window` takes JSON with an existing `water_id`, `availability` intervals
(`start`/`end`, ISO local times), `duration_minutes`, `daylight`, optional `birth`,
and a non-personal `request_id`. Known birth requires date, clock time, resolved
place/coordinates/timezone, and `time_known: true`. Unknown time can be sent as
`{"time_known": false}`. DST gaps/folds require correction or a confirmed explicit
offset. Birthplace lookup is `POST /api/window/place` with just a `query`; the
provider receives no birth date/time.

`./fishwitch window --request request.json` (or stdin with `--request -`) uses
the same operation and ordering. `--weather snapshot.json --evaluated-at ISO`
replays frozen UTC weather and an explicit evaluation time. Request JSON and
frozen snapshots must remain private when they contain personal data; do not
commit real profiles or calculated personal results.

## Validation and release boundaries

```sh
~/.astro-venv/bin/python tests/run_offline.py
node tests/window_state.test.cjs
node tests/report_state.test.cjs
node tests/browser_window.cjs  # installed Chromium + synthetic local fixture server
```

The offline runner blocks HTTP/TCP and supplies legacy retailer test configuration.
The real-browser harness checks returning/expired trips, races, privacy, forgotten
details, keyboard focus, phone widths, and the request deadline. It does not fetch
real weather or use real profiles. No new test/runtime dependencies are required.

Public release still requires a viable weather-service/commercial-use basis and
Swiss Ephemeris/Kerykeion/pyswisseph license review. No license purchase or hosting
change is authorized by this implementation. Existing scheduled warmers, static
snapshots, legacy routes/APIs/feeds, and saved data need an explicit cutover plan;
none were deleted or deployed. Rollback is the prior source revision and retained
legacy routes; do not push private repository history to the public mirror.

## Retained legacy reference

Everything below describes the parked layered-report application. Its `/legacy`,
`/report`, `/outlook`, public API v1, feeds, maps, interviews, and existing CLI
commands remain available for compatibility and use their historical ranking.
They are not dependencies of the new page or the canonical `window` operation.
Do not build new product features on this path. Retirement is a release decision.

## Layers
1. **Weather** — Open-Meteo: temps, wind, cloud, precipitation, barometer
   trend, water-temp estimate.
2. **Astronomy** — Swiss Ephemeris: sunrise/sunset, civil dusk, moonrise/set,
   moon phase, solunar majors (moon overhead/underfoot) & minors (rise/set).
3. **Astrology** — your natal chart (kerykeion/Swiss Ephemeris): transits
   vs. your chart with aspect perfection times, void-of-course moon, planetary
   days & hours, moon sign lore, lunar-phase resonance with your birth moon.
   **The translation layer** (below) controls how this is presented.
4. **Tactics** — a lure/rig/bait knowledge base per species plus cited
   cross-species line/knot tables. Every cited entry is scored for the conditions
   (light, wind, water temp, hour, solunar, lake state) and the **best rigs rank
   first for everyone**; the angler's baseline (arsenal, baits, line, knots) is a
   lens that tags what's already in the box vs a gap. Decision rules also add a
   **wind-exposure** read from the lake's cached shoreline (which bank the wind is
   stacking), fetched once by `adapters/shorelines.py`.

## The translation layer (voices)
The same sky math always runs. `--voice` (or `astro_display` in the profile)
chooses the vocabulary:

| voice | presentation |
|---|---|
| `fisher` | zero astrology — events surface as neutral "activity windows" (peak-feed / aggressive-feed / quiet-feed); verified leak-free |
| `almanac` | old-timers' almanac framing — moon phase & sign as lore, planetary hours by name (almanacs publish them), no natal chart |
| `astro` | full disclosure — natal chart, transits, houses, dignities |

Default: new profiles via interview default to `almanac`; `--voice` always wins.

## Marine electronics meshing (`adapters/`)
Get boat data **in**:
- **GPX** — waypoints/tracks from any Garmin/Lowrance/Humminbird export
  (universal interchange). `gpx.lake_intel_from_waypoints()` turns named
  spots into registry structure notes.
- **NMEA 0183** — live streams (serial/TCP/UDP from any NMEA gateway):
  DPT/DBT depth, MTW real water temp, RMC/GGA position. `nmea.Stream`.
- **Signal K** — open marine server (pairs with OpenCPN etc.): REST client
  `signalk.SignalK` — pull live water temp, push waypoints.
- **Lowrance SL2/SL3 sonar logs** — `sl2.Sl2Reader` (EXPERIMENTAL: community
  reverse-engineered format; calibrate against a known-good log before
  trusting depth/temp output). Humminbird .SON + Garmin Quickdraw follow the
  same pattern (detect → calibrate → parse → bathymetry/temp history).

Push fishwitch **out**:
- `report --gpx out.gpx` — prime-window waypoints loadable on any MFD
- the report model is a plain JSON-able dict — serialize for any UI/service
- Signal K waypoint PUT (chartplotter-visible spots)

## Usage
```bash
fishwitch interview                     # answer the questions → save a profile
fishwitch report                        # tonight 6 PM, default profile + home lake
fishwitch report --at "2026-09-10 18:00" --hours 3
fishwitch report --bottom grass --clarity stained   # declared cover + water clarity
fishwitch report --voice fisher         # astrology fully translated away
fishwitch report --gpx prime.gpx        # waypoints for the chartplotter
fishwitch log --lure "110 walker"       # log a catch → empirical reports
fishwitch review                        # grade the logbook vs blind model replays
fishwitch review --angler Jack --since 2026-09-01
fishwitch kb | kb-ingest | kb-review | kb-promote --by you   # cite → review → promote / reject / retire
fishwitch clicks [--remote]             # aggregate outbound clicks (no PII; --remote = production)
fishwitch stats [--remote]              # aggregate page views (no PII; --remote = production)
./webapp                                 # web front door → http://127.0.0.1:7700
FISHWITCH_LOCAL=1 ./webapp               # + /review, /stats, and ledger-writing /log (self-host)
# public /log is field mode: entries queue in the browser and export as JSON for import
~/.astro-venv/bin/python -m unittest discover -s tests -t .   # 138 tests, no network
FISHWITCH_WEB_HOST=0.0.0.0 ./webapp     # public deploy (gunicorn+nginx in front)
fishwitch report --profile config/profiles/sean.json --lake hidden-valley-lake-ca
fishwitch report --birth "1988-01-18 17:35" --place "Santa Rosa, CA, US" \
    --lake "Clear Lake, CA" --species bass \
    --arsenal "drop shot, wacky senko, chatterbait, squarebill, whopper plopper" \
    --baits "nightcrawlers, live shiners" --line "fluorocarbon, braid" --bottom grass
fishwitch lakes                         # registry of known water bodies
fishwitch arsenal --species bass        # lure categories it understands
```

## Legacy layered-report data flow
```python
from fishwitch.report import generate, to_markdown
profile = {...birth: {date, time, time_known, place, lat, lng, tz},
           arsenal: [...], baits: [...], line: [...], knots: [...],
           setups: {dropshot: {hook: "Owner Mosquito Circle 1/0", bait: "6in Deception worm"}},
           species: "largemouth bass", astro_display: "almanac"}
lake     = {...name, region, lat, lng, alt_m, structure: [...], lore: [...]}
model = generate(profile, lake, at_local=datetime(...), hours=2.5, voice="fisher")
md = to_markdown(model)   # model is a plain dict — serialize for the UI
```
(the repo root is the `fishwitch` package — add its parent to PYTHONPATH)

## Monetization (offers)

Tackle links resolve at the very end of the pipe (`offers.py`) and never
influence ranking. Every offer carries a disclosure, and only promoted, cited
KB entries get links. The rig picks carry a per-rig "build it" bundle and a
consolidated shopping list (hook, weight, plastic, line) — each part routes
through `/out/` with its own disclosure and click count. Affiliate tags live in
the environment (`FISHWITCH_AMZ_TAG`), never in code. Manufacturer pages carry
no commission; affiliate links (Amazon among them) are always labeled. See the
site's `/disclosure` and `/privacy` pages.

## Public JSON API (v1) & embed

Anonymous, read-only, deterministic — the same rankings the site serves, free
to use with attribution. No profile data can appear in a response; responses
carry `Cache-Control` and open CORS for GET.

```bash
curl 'https://baromoon.com/api/v1/report?lake=hidden-valley-lake-ca&bottom=grass'
curl 'https://baromoon.com/api/v1/windows?lake=hidden-valley-lake-ca&days=7'
```

`/api/v1/report` returns the scores, prime window, every block's picks with the
engine's own reasons, the top rigs with their cited builds, the gap lane, knots,
line, color, sky times, conditions, **model-agreement confidence**, and links.
`/api/v1/windows` returns the horizon scan. Embed the ledger anywhere:

```html
<iframe src="https://baromoon.com/embed/ledger?lake=hidden-valley-lake-ca&days=7"
        style="width:100%;max-width:430px;height:250px;border:1px solid #37402c;border-radius:6px"
        title="baromoon — best fishing windows"></iframe>
```

## Notes & limits
- **Shoreline wind model:** lake outlines come from OpenStreetMap (Overpass API),
  simplified and cached in `config/shorelines.json` — data © OpenStreetMap
  contributors (ODbL). The report credits it wherever the wind-bank advice appears.
- **Forecast confidence:** the report shows how much GFS, ECMWF and ICON disagree
  for the window (a free Open-Meteo multi-model call). Wide disagreement on cloud is
  called out because cloud drives the light scoring. It is disclosed, never scored —
  uncertainty changes the ranking only if the calibration ledger earns it.
- Forecast range ~3 days out (Open-Meteo free tier). Further = sky/astro only.
- Water temp is a first-order air-temp-lag estimate (tau ~4 days, 30-day
  spin-up) unless a gauge is live; the report shows the estimate and its 7-day
  warming/cooling trend.
- Solunar majors/minors follow the classic overhead/underfoot model.
- Planetary hours use the unbroken Chaldean sequence from the sunrise ruler.
- Birth time unknown → noon stand-in; Asc/house-dependent lines are hidden.
- Add water bodies to `config/lakes.json` (structure notes + lore get woven
  into decision rules).

Runs on `~/.astro-venv` (shared with ~/astro — swisseph, kerykeion, requests).
