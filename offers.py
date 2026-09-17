"""Offers layer — SKU resolution & monetization at the END of the honest pipe.

Schema v2 (`kb/offers.json`):
  retailers: registry — `label`, `kind` (manufacturer|affiliate), and URL
             construction (`dp_template` + `tag_env` for Amazon-style links).
  entries:   entry_id -> {kind: product|rig,
                          offers:     [ {retailer, url|asin, note} ],
                          components: [ {id, label, note, offers:[...]} ] }

Rules (enforced by design, see kb/README):
  1. Ranking NEVER sees offers. The tactics engine scores conditions only.
  2. Every offer carries an explicit disclosure.
  3. Affiliate tags/IDs live in env/config (`FISHWITCH_AMZ_TAG` …), never code.
  4. Every outbound link routes via `/out/<entry>/<retailer>` so clicks are
     counted in aggregate and destinations cannot be user-supplied.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OFFERS = ROOT / "kb" / "offers.json"

DISCLOSURE = {
    "manufacturer": "manufacturer product page (no commission)",
    "affiliate": "affiliate link — baromoon may earn a commission",
}


def _load() -> dict:
    if not OFFERS.exists():
        return {"retailers": {}, "entries": {}}
    d = json.loads(OFFERS.read_text())
    if "entries" not in d:          # v1 fallback: whole file is entry_id -> [offers]
        d = {"retailers": {}, "entries": {k: {"offers": v} for k, v in d.items()}}
    return d


def retailers() -> dict:
    return _load().get("retailers", {})


def _offer_url(entry_id: str, o: dict, reg: dict) -> str | None:
    """Build the final URL: dp_template + env tag for catalog retailers, else the
    stored URL (network tracked links, manufacturer pages)."""
    r = reg.get(o.get("retailer"), {})
    tmpl = r.get("dp_template")
    if tmpl:
        if not o.get("asin"):
            return None
        url = tmpl.format(asin=o["asin"])
        tag = os.environ.get(r.get("tag_env") or "", "")
        if tag:
            url += ("&" if "?" in url else "?") + f"tag={tag}"
            if r.get("subtag"):
                url += f"&ascsubtag={entry_id}"
        return url
    return o.get("url") or None


def _resolve(entry_id: str, o: dict, reg: dict, comp: str | None = None) -> dict:
    r = reg.get(o.get("retailer"), {})
    kind = r.get("kind", o.get("kind", "manufacturer"))
    out = dict(o)
    out["retailer_label"] = r.get("label", o.get("retailer", "retailer"))
    out["kind"] = kind
    out["url"] = _offer_url(entry_id, o, reg)
    out["disclosure"] = DISCLOSURE.get(kind, "")
    if comp:
        out["comp"] = comp
    return out


def resolve(entry_id: str) -> list[dict]:
    """Resolved product offers for an entry (the tackle-block / gap-lane rows)."""
    d = _load()
    reg = d.get("retailers", {})
    e = d.get("entries", {}).get(entry_id, {})
    offers = e.get("offers", []) if isinstance(e, dict) else (e or [])
    return [_resolve(entry_id, o, reg) for o in offers]


def components(entry_id: str) -> list[dict]:
    """Resolved component bundles for a rig entry — what it takes to build it."""
    d = _load()
    reg = d.get("retailers", {})
    e = d.get("entries", {}).get(entry_id, {})
    comps = e.get("components", []) if isinstance(e, dict) else []
    out = []
    for c in comps:
        cc = dict(c)
        cc["offers"] = [_resolve(entry_id, o, reg, comp=c["id"]) for o in c.get("offers", [])]
        out.append(cc)
    return out


def add(entry_id: str, retailer: str, url: str | None = None,
        kind: str | None = None, asin: str | None = None):
    """Register/update a product offer. Data-only — no code change to go live."""
    d = _load()
    e = d.setdefault("entries", {}).setdefault(entry_id, {"offers": []})
    e.setdefault("offers", [])
    slot = dict(retailer=retailer)
    if asin:
        slot["asin"] = asin
    if url:
        slot["url"] = url
    for i, o in enumerate(e["offers"]):
        if o.get("retailer") == retailer:
            e["offers"][i] = {**o, **slot}
            break
    else:
        e["offers"].append(slot)
    OFFERS.write_text(json.dumps(d, indent=2) + "\n")
    return d


def add_component_offer(entry_id: str, comp_id: str, retailer: str,
                        url: str | None = None, asin: str | None = None):
    """Register/update an offer on a rig component."""
    d = _load()
    e = d.setdefault("entries", {}).setdefault(entry_id, {"kind": "rig", "components": []})
    comps = e.setdefault("components", [])
    comp = next((c for c in comps if c.get("id") == comp_id), None)
    if comp is None:
        comp = dict(id=comp_id, label=comp_id, offers=[])
        comps.append(comp)
    slot = dict(retailer=retailer)
    if asin:
        slot["asin"] = asin
    if url:
        slot["url"] = url
    for i, o in enumerate(comp["offers"]):
        if o.get("retailer") == retailer:
            comp["offers"][i] = {**o, **slot}
            break
    else:
        comp["offers"].append(slot)
    OFFERS.write_text(json.dumps(d, indent=2) + "\n")
    return d
