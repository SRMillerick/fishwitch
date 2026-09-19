"""Public JSON shape (v1) for baromoon — a curated, stable view over the
deterministic model.

Contract: **anonymous only** (no profile can appear here), additive fields
within v1, datetimes as ISO-8601 local (minutes precision), and every claim
keeps its source. Rankings are the same ones the site serves; monetization
never touches them. Free to use with attribution.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlencode

from tactics import rig_spec, spec_line

SOURCE = "https://baromoon.com"
LICENSE = "free to use with attribution to https://baromoon.com"
DISCLAIMER = ("Conditions are estimates (weather forecast, inferred lake state, "
              "air-temp water estimate unless a gauge is live) — a plan, not a promise.")


def _iso(v):
    if isinstance(v, datetime):
        return v.isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    return v


def envelope(payload: dict) -> dict:
    return {
        "api": "v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": SOURCE,
        "license": LICENSE,
        "disclaimer": DISCLAIMER,
        **payload,
    }


def links(lake_id: str, at: datetime | None = None) -> dict:
    q = {"lake": lake_id}
    out = {
        "lake": f"{SOURCE}/lake/{lake_id}",
        "outlook": f"{SOURCE}/outlook?{urlencode(q)}",
        "calendar": f"{SOURCE}/ledger.ics?{urlencode(q)}",
        "rss": f"{SOURCE}/outlook.rss?{urlencode(q)}",
    }
    if at:
        out["report"] = f"{SOURCE}/report?{urlencode({**q, 'at': f'{at:%Y-%m-%d %H:%M}'})}"
    return out


def _picks(picks) -> list[dict]:
    out = []
    for c, s, why in picks or []:
        out.append({"id": c["id"], "label": c["label"], "score": round(float(s), 1),
                    "why": list(why or [])})
    return out


def _rod(c: dict) -> dict:
    prov = c.get("provenance") or {}
    spec = rig_spec(c["id"])
    return {"id": c["id"], "label": c["label"], "kind": c.get("kind"),
            "kb": f"{SOURCE}/kb/{c['id']}",
            "style": c.get("style"), "depth": c.get("depth"),
            "technique": c.get("technique"), "note": c.get("note"),
            "build": spec_line(spec) if spec else None,
            "source": prov.get("source"),
            "source_url": prov.get("source_url"),
            "confidence": prov.get("confidence")}


def _block(b: dict) -> dict:
    return {"start": _iso(b["start"]), "end": _iso(b["end"]),
            "light": b.get("light"), "solunar": b.get("solunar"),
            "events": list(b.get("events") or []),
            "picks": _picks(b.get("picks"))}


def report(m: dict, lake_id: str, lake: dict, at: datetime, hours: float,
           voice: str, species: str, bottom: str | None) -> dict:
    prime = m.get("prime")
    knots = [{"id": k["id"], "label": k.get("label"),
              "connection": k.get("connection"),
              "confidence": (k.get("provenance") or {}).get("confidence")}
             for k in (m.get("knots") or [])]
    return {
        "lake": {"id": lake_id, "name": lake.get("name"), "region": lake.get("region")},
        "session": {"at": _iso(at), "hours": hours, "voice": voice,
                    "species": species, "bottom": bottom},
        "scores": m.get("scores") or {},
        "prime": ({"start": _iso(prime["start"]), "end": _iso(prime["end"]),
                   "light": prime.get("light"), "solunar": prime.get("solunar"),
                   "events": list(prime.get("events") or []),
                   "picks": _picks(prime.get("picks"))} if prime else None),
        "blocks": [_block(b) for b in (m.get("blocks") or [])],
        "rods": [_rod(c) for c in (m.get("rods") or [])],
        "gap": [{"id": c["id"], "label": c["label"], "score": round(float(s), 1),
                 "kind": c.get("kind", "product"), "why": list(why or [])}
                for c, s, why in (m.get("gap") or [])],
        "knots": knots,
        "line": m.get("line"),
        "color": ({"label": m["color"].get("label"), "rule": m["color"].get("rule")}
                  if m.get("color") else None),
        "sky": {
            "sun": {k: _iso(v) for k, v in (m.get("sun") or {}).items()},
            "moon": {k: _iso(v) for k, v in (m.get("moon") or {}).items()},
            "solunar": [{"kind": e.get("kind"), "label": e.get("label"),
                         "start": _iso(e.get("start")), "end": _iso(e.get("end")),
                         "peak": _iso(e.get("peak"))} for e in (m.get("solunar") or [])],
        },
        "conditions": {
            "water_temp_f": (m.get("weather") or {}).get("water_f"),
            "water_temp_source": "gauge" if m.get("water_temp_source") else "estimate",
            "lake_state": m.get("lake_state") or None,
            "state_basis": m.get("state_basis") or None,
            "stocking": bool(m.get("stocking")),
        },
        "forecast": m.get("forecast"),
        "shoreline": m.get("shoreline"),
        "trends": [{"label": t.get("label"), "score": t.get("score"),
                    "signal": t.get("signal"), "source": t.get("source"),
                    "url": t.get("url"), "observed_at": t.get("observed_at")}
                   for t in (m.get("trends") or [])],
        "links": links(lake_id, at),
    }


def windows(rows: list[dict], moon_rows: list, lake_id: str) -> dict:
    return {
        "lake": {"id": lake_id},
        "windows": [{"day": r.get("day"), "start": _iso(r.get("start")),
                     "end": _iso(r.get("end")), "overall": r.get("overall"),
                     "confidence": r.get("conf"),
                     "prime": _iso(r.get("prime")) if r.get("prime") else None,
                     "picks": list(r.get("picks") or [])} for r in rows],
        "moon": [{"day": d, "phase": ph, "illum": il}
                 for d, ph, il, _svg in (moon_rows or [])],
        "links": {k: v for k, v in links(lake_id).items() if k != "report"},
    }
