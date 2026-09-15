"""Review — every logged trip, graded against what the model would have said.

Replays the deterministic pipe for each logbook entry AS OF that moment:
  weather     fetched with enough past_days to cover the entry (92-day API cap),
              so replays use real observed/analysis weather, not today's forecast
  logbook     presented point-in-time — only entries strictly BEFORE the session,
              so the model can't peek at the outcome it is being graded on
              (same blind discipline as the 2026-09-09 HVL validation)
  lake state  re-inferred from weather history by generate() itself

Grades the three things the model actually claims:
  presentation  the lure that caught the fish vs the model's prime picks
                (exact = same category · style = same finesse/reaction family ·
                 benched = lure not in the angler's arsenal · miss = other)
  timing        the catch stamp vs the model's prime moment (±30 / ±60 min)
  zone          depth words in the notes vs the top pick's depth — graded only
                when the notes name exactly one of deep/shallow (deterministic,
                no negation guessing; "shallow bite dead, went deep" → n/a)

And the headline: do window scores SEPARATE catches from skunks?

Read-only. Never writes the logbook, KB, or registry.

    fishwitch review
    fishwitch review --angler Jack --since 2026-09-01
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import logbook as lb
from tactics import match_arsenal, normalize_species
from weather import Weather
from report import generate

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
PROFILES = CONFIG / "profiles"

PAST_DAYS_CAP = 92      # Open-Meteo forecast-endpoint past_days limit
SNAP_SLACK_MIN = 90     # tolerated drift for the nearest-hour weather lookup
GOOD_WINDOW = 5.5       # overall score at/above which a skunk is a calibration miss


# ── small helpers ───────────────────────────────────────────────────────────
def _ts(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry.get("ts") or "")
    except ValueError:
        return None


def _profile_for(angler: str | None) -> dict:
    default = json.loads((PROFILES / "default.json").read_text())
    if not angler:
        return default
    for p in sorted(PROFILES.glob("*.json")):
        if p.name == "example.json":
            continue
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if (d.get("name") or "").lower() == angler.lower():
            return d
    return default


def _lake_for(entry: dict, profile: dict) -> dict | None:
    reg = json.loads((CONFIG / "lakes.json").read_text())
    name = (entry.get("lake") or "").strip().lower()
    if name:
        for k, v in reg.items():
            vname = (v.get("name") or "").lower()
            if k == name or vname == name or vname in name or name in vname:
                return v
    return reg.get(profile.get("home_lake"))


def _dedupe(picks: list[tuple]) -> list[tuple]:
    best: dict[str, tuple] = {}
    for c, s, w in picks:
        if c["id"] not in best or s > best[c["id"]][1]:
            best[c["id"]] = (c, s, w)
    return sorted(best.values(), key=lambda p: -p[1])


# ── the three grades ───────────────────────────────────────────────────────
def _grade_presentation(lure: str | None, species: str, profile: dict,
                        picks: list[tuple]) -> tuple[str | None, str]:
    """Compare the logged lure to the model's picks. None = not gradeable."""
    if not lure or not picks:
        return None, ""
    m = match_arsenal([lure], species)
    if not m["matched"]:
        return "n/a", f"‘{lure}’ not in the {species} catalog"
    cat = m["matched"][0][0]
    labels = " + ".join(c["label"] for c, _, _ in picks[:2])
    if cat["id"] in {c["id"] for c, _, _ in picks}:
        return "exact", f"model picked {labels}"
    arsenal_ids = {c["id"] for c, _ in
                   match_arsenal(profile.get("arsenal") or [], species)["matched"]}
    if cat["id"] not in arsenal_ids:
        return "benched", f"not in angler’s arsenal — model picked {labels}"
    if picks[0][0].get("style") == cat.get("style"):
        return "style", f"right {cat.get('style')} family — model picked {labels}"
    return "miss", f"model picked {labels}"


def _grade_timing(ts: datetime, prime: dict | None) -> tuple[str | None, int]:
    """Catch stamp vs the model's prime moment."""
    if not prime:
        return None, 0
    d = int(abs((ts - prime["start"]).total_seconds()) // 60)
    if d <= 30:
        return "exact", d
    if d <= 60:
        return "close", d
    return "miss", d


def _grade_zone(notes: str, picks: list[tuple]) -> tuple[str | None, str]:
    """Depth words in notes vs top pick's depth. Both words present → n/a."""
    n = (notes or "").lower()
    words = [w for w in ("deep", "shallow") if w in n]
    if len(words) != 1 or not picks:
        return None, ""
    d = picks[0][0].get("depth") or "?"
    hit = words[0] in d
    return ("exact" if hit else "miss"), f"notes: {words[0]} · top pick depth: {d}"


def _lb(length: str | None) -> float | None:
    """Parse a length field to pounds. '4lb'→4 · '<1lb'→0.5 (half the ceiling) ·
    anything else → None (unmeasured fish count but add no weight)."""
    import re as _re
    s = (length or "").strip().lower()
    m = _re.match(r"<\s*([0-9.]+)\s*lb?$", s)
    if m:
        return round(float(m.group(1)) / 2, 2)
    m = _re.match(r"([0-9.]+)\s*lb$", s)
    if m:
        return float(m.group(1))
    return None


def _sessions(rows: list[dict]) -> list[dict]:
    """Group catch entries into sessions: same angler + same calendar day = one
    session (the logbook is per-catch; the replay grades per-session)."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        t = _ts(r)
        key = ((r.get("angler") or "").lower(), t.date())
        by.setdefault(key, []).append(r)
    out = []
    for (angler, day), entries in sorted(by.items()):
        entries.sort(key=_ts)
        catches = [e for e in entries if e.get("result") != "skunk"]
        skunk = not catches
        # primary lure = most-logged, ties broken by first occurrence
        counts: dict[str, int] = {}
        for e in catches:
            if e.get("lure"):
                counts.setdefault(e["lure"], 0)
                counts[e["lure"]] += 1
        primary = max(counts.items(), key=lambda kv: (kv[1], -list(counts).index(kv[0])))[0] \
            if counts else None
        others = [l for l in counts if l != primary]
        lbs = [_lb(e.get("length")) for e in catches]
        lbs = [x for x in lbs if x is not None]
        out.append(dict(
            angler=entries[0].get("angler"), ts=_ts(entries[0]),
            lake=entries[0].get("lake"), entries=entries, skunk=skunk,
            n_fish=len(catches), primary_lure=primary, other_lures=others,
            species=catches[0].get("species") if catches else None,
            notes="; ".join(dict.fromkeys(
                (e.get("notes") or "").strip() for e in entries if e.get("notes"))),
            best_lb=max(lbs) if lbs else None,
            total_lb=round(sum(lbs), 1) if lbs else None,
        ))
    return out


# ── the replay ─────────────────────────────────────────────────────────────
def collect(angler: str | None = None, since: datetime | None = None,
            lake: str | None = None, hours: float = 2.0,
            species: str | None = None) -> tuple[list[dict], list[str]]:
    """Run the blind replays; returns (graded session rows, skip messages).
    Prints nothing — presentation is run()'s / the web panel's job."""
    rows = lb.load()
    if angler:
        rows = [r for r in rows if (r.get("angler") or "").lower() == angler.lower()]
    if since:
        rows = [r for r in rows if _ts(r) and _ts(r) >= since]
    if lake:
        rows = [r for r in rows if lake.lower() in (r.get("lake") or "").lower()]
    rows = sorted((r for r in rows if _ts(r)), key=_ts)
    if not rows:
        return [], []
    sessions = _sessions(rows)
    if not sessions:
        return [], []

    today = datetime.now()
    graded: list[dict] = []
    skipped_msgs: list[str] = []
    skipped = 0
    wx_cache: dict[tuple, Weather] = {}
    hist_cache: dict[tuple, object] = {}
    # point-in-time logbook: generate() must see only what existed before the
    # session it is being graded on. Patched for the replay, restored after.
    cutoff: list[datetime | None] = [None]
    orig_load = lb.load

    def _pit_load():
        return [r for r in orig_load() if (t := _ts(r)) is None or t < cutoff[0]]

    lb.load = _pit_load
    try:
        for sess in sessions:
            e, ts = sess, sess["ts"]
            prof = _profile_for(e.get("angler"))
            lk = _lake_for(e, prof)
            if lk is None:
                skipped += 1
                skipped_msgs.append(f"{e.get('ts')} · {e.get('angler')}: lake not resolvable")
                continue
            sp = normalize_species(e.get("species") or species or prof.get("species", "bass"))
            is_skunk = e["skunk"]

            key = (lk["lat"], lk["lng"])
            if key not in wx_cache:
                need = (today.date() - ts.date()).days + 1
                if need > PAST_DAYS_CAP:
                    skipped += 1
                    skipped_msgs.append(f"{ts:%Y-%m-%d} · {e.get('angler')}: "
                                        f"beyond the {PAST_DAYS_CAP}-day weather replay horizon")
                    continue
                wx_cache[key] = Weather(lk["lat"], lk["lng"], past_days=min(need + 1, PAST_DAYS_CAP))
            wx = wx_cache[key]
            if abs((wx.at(ts)["dt"] - ts).total_seconds()) > SNAP_SLACK_MIN * 60:
                skipped += 1
                skipped_msgs.append(f"{ts:%Y-%m-%d %H:%M} · {e.get('angler')}: no weather coverage")
                continue
            if key not in hist_cache:
                try:
                    from layers.history import History
                    hist_cache[key] = History(lk["lat"], lk["lng"], ts)
                except Exception:
                    hist_cache[key] = None
            hist = hist_cache[key]

            start = ts - timedelta(hours=hours / 2)   # window centered on the stamp:
            cutoff[0] = ts                             # the session actually fished
            try:
                m = generate(prof, lk, start, hours=hours, species=sp, wx=wx, hist=hist)
            except Exception as ex:
                skipped += 1
                skipped_msgs.append(f"{ts:%Y-%m-%d %H:%M} · {e.get('angler')}: replay failed ({ex})")
                continue
            finally:
                cutoff[0] = None

            prime = m.get("prime")
            picks = _dedupe([(c, s, w) for blk in m["blocks"] for c, s, w in blk["picks"]])
            if prime and prime.get("picks"):
                picks = prime["picks"]
            pres, pres_why = (None, "") if is_skunk else \
                _grade_presentation(e.get("primary_lure"), sp, prof, picks)
            tim, tim_d = (None, 0) if is_skunk else _grade_timing(ts, prime)
            zon, zon_why = _grade_zone(e.get("notes", ""), picks)  # skunks too: wrong-water skunks
            overall = m["scores"]["overall"]
            graded.append(dict(entry=e, ts=ts, skunk=is_skunk, overall=overall,
                               prime=prime, picks=picks, pres=pres, pres_why=pres_why,
                               tim=tim, tim_d=tim_d, zon=zon, zon_why=zon_why,
                               state=m.get("lake_state") or "",
                               basis=m.get("state_basis") or ""))
    finally:
        lb.load = orig_load

    return graded, skipped_msgs


def run(angler: str | None = None, since: datetime | None = None,
        lake: str | None = None, hours: float = 2.0,
        species: str | None = None) -> None:
    graded, skipped_msgs = collect(angler=angler, since=since, lake=lake,
                                   hours=hours, species=species)
    if not graded and not skipped_msgs:
        print("  logbook empty for that filter — log trips with `fishwitch log`")
        return
    for s in skipped_msgs:
        print(f"  ⊘ {s}")
    _print_rows(graded)
    _print_summary(graded, len(skipped_msgs))


def _print_rows(graded: list[dict]) -> None:
    for g in graded:
        e, ts = g["entry"], g["ts"]
        if g["skunk"]:
            head = f"🦨 {ts:%a %b %-d · %-I:%M %p} — {e.get('angler')} · SKUNK"
            if e.get("notes"):
                head += f" (‘{e['notes']}’)"
        else:
            bag = f"{e['n_fish']} fish"
            if e.get("best_lb") is not None:
                bag += f", best {e['best_lb']:g} lb"
            if e.get("total_lb") is not None:
                bag += f", known weight {e['total_lb']:g} lb"
            head = (f"🎣 {ts:%a %b %-d · %-I:%M %p} — {e.get('angler')} · {bag} "
                    f"on ‘{e.get('primary_lure') or '?'}’")
            if e.get("other_lures"):
                head += f" (+ {', '.join(e['other_lures'])})"
        print(f"\n  {head}")
        state = f" · {g['state']} ({g['basis']})" if g["state"] else ""
        print(f"     replay overall {g['overall']}/10{state}")
        if g["prime"]:
            p = g["prime"]
            print(f"     prime {p['start']:%-I:%M %p} ({p['light']}) · "
                  + (" + ".join(c["label"] for c, _, _ in g["picks"][:2]) or "no picks"))
        marks = {"exact": "✅", "close": "〰", "style": "〰", "miss": "✗",
                 "benched": "⚪", "n/a": "·"}
        parts = []
        if g["pres"]:
            parts.append(f"presentation {marks.get(g['pres'], '·')} {g['pres']}")
        if g["tim"]:
            parts.append(f"timing {marks.get(g['tim'], '·')} ({g['tim_d']:+d} min vs prime)"
                         .replace("(+", "(").replace("(-", "(−"))
        if g["zon"]:
            parts.append(f"zone {marks.get(g['zon'], '·')} {g['zon']}")
        if parts:
            print("     " + " · ".join(parts))
        if g["pres"] in ("benched", "n/a") and g["pres_why"]:
            print(f"       ⤷ {g['pres_why']}")
        if g["zon"] and g["zon_why"]:
            print(f"       ⤷ {g['zon_why']}")
        if g["skunk"]:
            if g["zon"] == "miss":
                print("     model said: wrong-water skunk — the window wasn’t the problem")
            elif g["overall"] >= GOOD_WINDOW:
                print("     model said: window scored well — calibration miss")
            else:
                print("     model said: low-value window — model agreed")


def _print_summary(graded: list[dict], skipped: int) -> None:
    catches = [g for g in graded if not g["skunk"]]
    skunks = [g for g in graded if g["skunk"]]
    print("\n" + "─" * 56)
    print(f"  CALIBRATION — {len(graded)} session{'s' if len(graded) != 1 else ''} replayed"
          + (f" ({skipped} skipped)" if skipped else ""))

    tally: dict[str, int] = {}
    for g in catches:
        for k in ("pres", "tim", "zon"):
            if g[k]:
                tally[f"{k}:{g[k]}"] = tally.get(f"{k}:{g[k]}", 0) + 1
    pres_bits = [f"{v} {k.split(':')[1]}" for k, v in sorted(tally.items())
                 if k.startswith("pres:")]
    if pres_bits:
        print(f"  PRESENTATION  {' · '.join(pres_bits)}")
    tim_bits = [f"{v} {k.split(':')[1]}" for k, v in sorted(tally.items())
                if k.startswith("tim:")]
    if tim_bits:
        print(f"  TIMING        {' · '.join(tim_bits)}")
    zon_bits = [f"{v} {k.split(':')[1]}" for k, v in sorted(tally.items())
                if k.startswith("zon:")]
    if zon_bits:
        print(f"  ZONE          {' · '.join(zon_bits)}")

    if catches and skunks:
        cm = sum(g["overall"] for g in catches) / len(catches)
        sm = sum(g["overall"] for g in skunks) / len(skunks)
        sep = cm - sm
        verdict = ("separates ✅" if sep >= 1.0 else
                   "weak separation" if sep >= 0 else "inverted ✗")
        print(f"  SEPARATION    catches avg {cm:.1f} · skunks avg {sm:.1f} "
              f"→ {sep:+.1f} ({verdict})")
    elif catches:
        cm = sum(g["overall"] for g in catches) / len(catches)
        print(f"  SEPARATION    catches avg {cm:.1f} · no skunks logged yet — "
              "log the bad days too, they calibrate")
    print("  (blind: logbook shown to the model as of each session; "
          "weather = archived observations)")
