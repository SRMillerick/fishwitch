"""Tactics layer — deterministic selection over the cited knowledge base.

NO KNOWLEDGE LIVES IN CODE. Everything about lures/rigs/techniques is read
from kb/<species>.json, where every entry carries provenance (source, url,
confidence, verified_by). This module only:
  - loads the KB
  - matches the angler's arsenal to KB entries (deterministic string rules)
  - scores entries against block conditions (fixed arithmetic)
  - surfaces provenance alongside every recommendation

If the KB lacks an entry, we say so — we never invent one. AI agents query
this KB (`fishwitch kb`); they do not author it at runtime. New entries are
added as reviewed, cited JSON — see kb/README.
"""
from __future__ import annotations
import json
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent / "kb"
_cache: dict[str, dict] = {}


# ── knowledge base access ───────────────────────────────────────────────────
def load_species(species: str) -> dict:
    key = normalize_species(species)
    if key not in _cache:
        p = KB_DIR / f"{key}.json"
        _cache[key] = json.loads(p.read_text()) if p.exists() else dict(label=key, cats=[])
    return _cache[key]


def kb_path(species: str) -> Path:
    return KB_DIR / f"{normalize_species(species)}.json"


def catalog(species: str = "bass") -> list[dict]:
    return load_species(species)["cats"]


def entry(species: str, entry_id: str) -> dict | None:
    for c in catalog(species):
        if c["id"] == entry_id:
            return c
    return None


def find_entry(entry_id: str) -> dict | None:
    """Look up an entry id across every species file (for cross-species tasks)."""
    for sp in ("bass", "trout", "catfish", "panfish"):
        c = entry(sp, entry_id)
        if c:
            return c
    return None


def normalize_species(name: str) -> str:
    n = (name or "").lower()
    if "largemouth" in n or "smallmouth" in n or "bass" in n:
        return "bass"
    if "trout" in n: return "trout"
    if "cat" in n: return "catfish"
    if "bluegill" in n or "crappie" in n or "panfish" in n or "perch" in n:
        return "panfish"
    return "bass"


# ── cross-species knowledge: knots & line (kb/knots.json, kb/line.json) ─────
_KNOTS: dict | None = None
_LINE: dict | None = None


def load_knots() -> dict:
    global _KNOTS
    if _KNOTS is None:
        p = KB_DIR / "knots.json"
        _KNOTS = json.loads(p.read_text()) if p.exists() else {"knots": [], "recommend": {}}
    return _KNOTS


def load_line() -> dict:
    global _LINE
    if _LINE is None:
        p = KB_DIR / "line.json"
        _LINE = json.loads(p.read_text()) if p.exists() else {"types": []}
    return _LINE


_TERMINAL: dict | None = None
_PRINCIPLES: dict | None = None
_SUBSTRATE: dict | None = None


def load_terminal() -> dict:
    global _TERMINAL
    if _TERMINAL is None:
        p = KB_DIR / "terminal.json"
        _TERMINAL = json.loads(p.read_text()) if p.exists() else {"terminal": []}
    return _TERMINAL


def load_principles() -> dict:
    global _PRINCIPLES
    if _PRINCIPLES is None:
        p = KB_DIR / "principles.json"
        _PRINCIPLES = json.loads(p.read_text()) if p.exists() else {"principles": []}
    return _PRINCIPLES


def load_substrate() -> dict:
    """Editorial substrate/presentation table (kb/substrate.json). Facts here
    are T5-labelled until sourced; scoring uses them only when the session
    declares a bottom."""
    global _SUBSTRATE
    if _SUBSTRATE is None:
        p = KB_DIR / "substrate.json"
        _SUBSTRATE = json.loads(p.read_text()) if p.exists() else {"entries": {}}
    return _SUBSTRATE


def substrate_fit(entry_id: str, bottom: str | None) -> tuple[float, str]:
    """(score delta, one-line behavior note) for an entry on a declared bottom."""
    if not bottom:
        return 0.0, ""
    e = (load_substrate().get("entries") or {}).get(entry_id) or {}
    b = e.get(bottom) or {}
    return float(b.get("fit", 0) or 0), (b.get("note") or "")


def color_principle(ctx: dict) -> dict | None:
    """Pick the colour principle that fits the session (editorial selection over
    the cited fish-vision science in kb/principles.json)."""
    ps = {p["id"]: p for p in load_principles().get("principles", [])}
    light = (ctx.get("light") or "")
    cloud = ctx.get("cloud") or 0
    ls = ctx.get("lake_state") or ""
    if light in ("night", "dusk/dawn"):
        pid = "low-light-rods"
    elif "post-turnover" in ls:
        pid = "depth-absorbs-long-wavelengths"
    elif cloud >= 70:
        pid = "contrast-over-color"
    elif light in ("golden", "sunset/sunrise"):
        pid = "true-colors-near-surface"
    else:
        pid = "clear-water-color-vision"
    return ps.get(pid)


def knots_for(entry_id: str, limit: int = 2, known: set | None = None) -> list[dict]:
    """Knots whose CITED use fits this KB entry. If `known` (the knot ids this
    angler actually ties) is given, their knots come first; any others the map
    suggests are kept as "worth learning". The pick→knot map lives in
    kb/knots.json (labelled editorial there); the knot facts are cited quotes."""
    d = load_knots()
    ids = (d.get("recommend", {}).get("by_entry", {}) or {}).get(entry_id, [])
    if known:
        ids = [i for i in ids if i in known] + [i for i in ids if i not in known]
    by_id = {k["id"]: k for k in d.get("knots", [])}
    out = []
    for i in ids:
        if i in by_id:
            out.append(by_id[i])
        if len(out) >= limit:
            break
    return out


def match_knots(items: list[str]) -> list[dict]:
    """Map an angler's free-text knot list to knot entities (exact first,
    then substring — same two-pass rule as match_arsenal)."""
    knots = load_knots().get("knots", [])
    out = []
    for item in items or []:
        s = (item or "").strip().lower()
        if not s:
            continue
        hit = None
        for k in knots:
            names = [k["id"].lower(), k["label"].lower()] + [a.lower() for a in k.get("aliases", [])]
            if s in names:
                hit = k
                break
        if hit is None:
            for k in knots:
                names = [k["id"].lower(), k["label"].lower()] + [a.lower() for a in k.get("aliases", [])]
                for n in names:
                    if n in s or s in n:
                        hit = k
                        break
                if hit:
                    break
        if hit and hit["id"] not in [o["id"] for o in out]:
            out.append(hit)
    return out


def recommend_line(picks: list[dict], known: set | None = None) -> dict | None:
    """Editorial pick→line rule, grounded in the CITED line properties (kb/line.json).
    `picks` are KB entries with id/style. Returns {id, label, why, mine?} or None.
    If `known` (the line-type ids this angler actually spools) is given, the
    result carries `mine`: whether the condition pick is already in their kit —
    the report flags a better fit they don't spool yet, same as knots."""
    d = load_line()
    rec = d.get("recommend", {}) or {}
    by_entry = rec.get("by_entry", {}) or {}
    by_style = rec.get("by_style", {}) or {}
    types = {t["id"]: t for t in d.get("types", [])}
    votes: dict[str, int] = {}
    for c in picks or []:
        lid = by_entry.get(c.get("id")) or by_style.get(c.get("style"))
        if lid:
            votes[lid] = votes.get(lid, 0) + 1
    if not votes:
        return None
    lid = max(votes, key=lambda k: votes[k])
    out = dict(id=lid, label=types.get(lid, {}).get("label", lid),
               why=(rec.get("why", {}) or {}).get(lid, ""))
    if known:
        out["mine"] = lid in known
    return out


# ── knots & line matching (cross-species, deterministic) ───────────────────
def match_line(items: list[str]) -> list[dict]:
    """Map an angler's free-text line list to line-type entities (exact first,
    then substring — same two-pass rule as match_arsenal/match_knots)."""
    types = load_line().get("types", [])
    out = []
    for item in items or []:
        s = (item or "").strip().lower()
        if not s:
            continue
        hit = None
        for t in types:
            names = [t["id"].lower(), t["label"].lower()] + [a.lower() for a in t.get("aliases", [])]
            if s in names:
                hit = t
                break
        if hit is None:
            for t in types:
                names = [t["id"].lower(), t["label"].lower()] + [a.lower() for a in t.get("aliases", [])]
                for n in names:
                    if n in s or s in n:
                        hit = t
                        break
                if hit:
                    break
        if hit and hit["id"] not in [o["id"] for o in out]:
            out.append(hit)
    return out


# ── arsenal matching (deterministic) ────────────────────────────────────────
def match_arsenal(items: list[str], species="bass") -> dict:
    cats = catalog(species)
    matched, unmatched = [], []
    for item in items:
        s = item.strip().lower()
        hit = None
        # pass 1: exact match (id / label / alias == item) — substring matching
        # alone mis-binds short items ('jig' belongs to the jig entry, not to
        # chatterbait's 'bladed jig' alias)
        for c in cats:
            names = [c["label"].lower(), c["id"]] + [a.lower() for a in c["aliases"]]
            if s in names:
                hit = c
                break
        # pass 2: substring fallback ('110 walker' → walker, 'abstract 24' → neko)
        if hit is None:
            for c in cats:
                names = [c["label"].lower(), c["id"]] + [a.lower() for a in c["aliases"]]
                for n in names:
                    if n in s or s in n:
                        hit = c
                        break
                if hit:
                    break
        if hit:
            if hit["id"] not in [m[0]["id"] for m in matched]:
                matched.append((hit, item.strip()))
        else:
            unmatched.append(item.strip())
    return dict(matched=matched, unmatched=unmatched)


# ── condition scoring (fixed arithmetic over KB data) ───────────────────────
def _wind_band(w):
    if w < 3: return "glass"
    if w <= 12: return "chop"
    return "windy"


def score_entry(cat: dict, ctx: dict) -> tuple[float, list[str], str | None]:
    """(score, reasons, rejection) — reads only KB fields."""
    cond = cat["conditions"]
    lo, hi = cond["water_temp_f"]
    t = ctx.get("water_f") or ctx.get("temp_f") or 65
    if ctx["light"] not in cond["light"]:
        if not (ctx.get("cloud", 0) >= 75 and "moderate day" in cond["light"]
                and "golden" in ctx["light"]):
            return 0.0, [], f"out of light band ({ctx['light']})"
    score = 3.0
    why = []
    score += 2.0 if _wind_band(ctx.get("wind_mph", 5)) in cond["wind"] else 0.5
    score += 2.0 if lo <= t <= hi else (1.0 if lo - 8 <= t <= hi + 8 else 0.0)
    ruler = ctx.get("hour_ruler")
    style_hour = {"Mars": "reaction", "Jupiter": "reaction", "Mercury": "finesse",
                  "Venus": "finesse", "Moon": "finesse", "Saturn": "finesse"}.get(ruler)
    if style_hour and cat["style"] == style_hour:
        score += 1.0; why.append(f"{ruler} hour favors {style_hour} work")
    if ctx.get("solunar") == "major" and cat["style"] == "reaction":
        score += 1.0; why.append("solunar major — feed window")
    if ctx.get("solunar") == "minor" and cat["style"] == "reaction":
        score += 0.5; why.append("solunar minor stirring")
    ls = ctx.get("lake_state") or ""
    if "post-turnover" in ls:
        if cat["style"] == "reaction" and cat["depth"] == "shallow":
            score -= 2.0; why.append("post-turnover: shallow reaction compressed")
        if cat["depth"] in ("mid", "deep"):
            score += 1.5; why.append("post-turnover: fish holding deep/suspended")
    sub = ctx.get("bottom")
    if sub:
        fit, note = substrate_fit(cat["id"], sub)
        if fit:
            score += fit
            if note:
                why.append(f"{sub}: {note}")
    if "hot-streak" in ls and ctx["light"] not in ("dusk/dawn", "night"):
        if cat["depth"] == "shallow" and cat["style"] == "reaction":
            score -= 1.0
        if cat["depth"] == "deep":
            score += 0.5
    if ctx["light"] in ("golden", "sunset/sunrise", "dusk/dawn", "night") \
            and cat["id"] in ("walker", "plopper", "buzz", "frog"):
        score += 0.5; why.append("low-light topwater = the big-fish play")
    return score, why, None


def recommend(ctx: dict, matched: list[tuple[dict, str]], top_n=2) -> list[tuple[dict, float, list[str]]]:
    out = []
    for cat, _label in matched:
        score, why, reject = score_entry(cat, ctx)
        if reject:
            continue
        out.append((cat, round(score, 1), why))
    out.sort(key=lambda x: -x[1])
    return out[:top_n]


def zone_hint(cat: dict, light: str) -> str:
    zones = cat.get("zones")
    if not zones:
        return ""
    return zones.get("night", "") if light in ("night", "dusk/dawn") else zones.get("day", "")


def color_hint(cat: dict, ctx: dict) -> str:
    colors = cat.get("colors", {})
    if not colors:
        return ""  # bait/live entries have no color dimension
    if ctx["light"] in ("night",):
        return colors.get("night", "dark silhouette colors")
    if ctx.get("cloud", 0) >= 70:
        return colors.get("overcast", "")
    return colors.get("clear", "")


# ── decision rules (fixed templates over live conditions) ──────────────────
def decision_rules(ctx: dict, picks: list[str]) -> list[str]:
    rules = []
    ls = ctx.get("lake_state") or ""
    if "post-turnover" in ls:
        rules.append("**Post-turnover lake →** the water column just mixed; fish are deep/suspended and the mats & back coves are empty. Work the first break and basin edges.")
        rules.append("**Post-turnover dusk →** compress the shallow experiment to the last 30 minutes of light; earn it deep first.")
    if "hot-streak" in ls:
        rules.append("**Multi-day heat →** deep is home; shallow visits are short commutes at first/last light only.")
    if "Walking topwater (Spook/110)" in picks:
        rules.append("**Swirls/short strikes on topwater →** don't speed up; slow down, longer pauses. Still missing → upsize the profile.")
    if "Drop shot" in picks:
        rules.append("**Drop-shot fish slapping →** re-cast the same fish one size up — change profile, not color.")
    if ctx.get("wind_mph", 0) >= 5 and "Chatterbait (bladed jig)" in picks:
        rules.append("**Wind dies →** skip the wind-lane baits, go straight to the low-light topwater.")
    if ctx.get("cloud", 0) >= 60:
        rules.append("**Overcast holds →** extend the reaction phase; this cloud is a gift.")
    if ctx.get("moon_fruitful") == "barren":
        rules.append("**Slow start ≠ bad session →** barren-sign evenings backload — the payoff window is late.")
    if ctx.get("pressure_word") in ("falling fast",):
        rules.append("**Barometer crashing →** fish will slide deeper sooner; work the first break line, not the back coves.")
    for s in ctx.get("structure_notes", [])[:3]:
        rules.append(f"Lake intel: {s}")
    return rules[:8]
