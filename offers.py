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


def shopping_list(entries: list[dict]) -> list[dict]:
    """Aggregate the component bundles of the recommended rigs into one
    deduped shopping list. Presentation only — never enters ranking. Each row
    names every rig it belongs to; resolved links keep their source rig entry
    so /out/ click counting stays attributed. `entries` = [{"id", "label"}]."""
    d = _load()
    reg = d.get("retailers", {})
    byid = d.get("entries", {})
    rows: dict[str, dict] = {}
    for e in entries or []:
        eid = e.get("id")
        elabel = e.get("label") or eid or ""
        cfg = byid.get(eid, {})
        comps = cfg.get("components", []) if isinstance(cfg, dict) else []
        for c in comps:
            row = rows.setdefault(c["id"], dict(
                id=c["id"], label=c.get("label", c["id"]), note=c.get("note"),
                for_labels=[], offers=[]))
            if elabel and elabel not in row["for_labels"]:
                row["for_labels"].append(elabel)
            for o in c.get("offers", []):
                ro = _resolve(eid, o, reg, comp=c["id"])
                ro["entry"] = eid
                sig = (ro.get("retailer"), ro.get("url"), ro.get("comp"))
                if sig not in {(x.get("retailer"), x.get("url"), x.get("comp"))
                               for x in row["offers"]}:
                    row["offers"].append(ro)
    return list(rows.values())


def build_shopping(rigs: list[dict]) -> list[dict]:
    """Shopping list from the rig `spec` blocks (dialed labels + sizes), merged
    across rigs, with component offers attached where the part's `ref` matches a
    registered component. Rigs without a spec fall back to their component
    bundle. Presentation only — never enters ranking."""
    rows: dict[str, dict] = {}
    import tactics as tx
    for r in rigs or []:
        rid = r.get("id")
        rlabel = r.get("label") or rid or ""
        comps = {c["id"]: c for c in components(rid)}
        spec = r.get("spec")

        def _row(key: str, label: str, note, offers: list[dict], alts: list[dict] | None = None):
            row = rows.setdefault(key, dict(id=key, label=label, note=note,
                                            for_labels=[], offers=[], alternatives=[]))
            if rlabel and rlabel not in row["for_labels"]:
                row["for_labels"].append(rlabel)
            for o in offers:
                sig = (o.get("retailer"), o.get("url"))
                if o.get("url") and sig not in {(x.get("retailer"), x.get("url"))
                                                 for x in row["offers"]}:
                    row["offers"].append(o)
            for a in alts or []:
                if a["id"] not in {x["id"] for x in row["alternatives"]}:
                    row["alternatives"].append(a)
            return row

        if spec:
            for part in ("hook", "weight", "ring", "tool", "bead", "swivel", "bait", "line"):
                p = spec.get(part)
                if not p:
                    continue
                if part == "line":
                    label = " / ".join(str(x) for x in (p.get("main"), p.get("leader")) if x)
                else:
                    label = p.get("ref_label") or p.get("type") or p.get("form") or ""
                sizes = p.get("sizes") or []
                if isinstance(sizes, str):
                    sizes = [sizes]
                if sizes:
                    label = (label + " " + "–".join(str(x) for x in sizes[:2])).strip()
                key = p.get("ref") or f"{rid}:{part}"
                comp = comps.get(p.get("ref"))
                offers = []
                if p.get("ref"):
                    for o in resolve(p["ref"]):
                        ro = dict(o); ro["entry"] = p["ref"]
                        offers.append(ro)
                if comp:
                    for o in comp.get("offers", []):
                        ro = dict(o); ro["entry"] = rid
                        offers.append(ro)
                alts = []
                for a in tx.alternatives(p.get("ref")) if p.get("ref") else []:
                    ao = resolve(a["id"])
                    for o in ao:
                        o["entry"] = a["id"]
                    alts.append(dict(id=a["id"], label=a.get("label", a["id"]),
                                     offers=[o for o in ao if o.get("url")]))
                _row(key, label, p.get("note"), offers, alts)
        else:
            for c in comps.values():
                offers = []
                for o in c.get("offers", []):
                    ro = dict(o); ro["entry"] = rid
                    offers.append(ro)
                _row(c["id"], c.get("label", c["id"]), c.get("note"), offers)
    return list(rows.values())


def categories() -> dict:
    """High-AOV category scaffold in `kb/offers.json` (electronics, kayaks…)."""
    return _load().get("categories", {})


def category_entries(cat_id: str) -> list[dict]:
    cat = categories().get(cat_id) or {}
    return cat.get("entries", [])


def resolve_category(cat_id: str, entry_id: str) -> list[dict]:
    """Resolved offers for one high-AOV category entry (electronics, kayaks…)."""
    reg = _load().get("retailers", {})
    for e in category_entries(cat_id):
        if e.get("id") == entry_id:
            return [_resolve(entry_id, o, reg) for o in e.get("offers", [])]
    return []


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
