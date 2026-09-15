"""Offers layer — SKU resolution & monetization at the END of the honest pipe.

Rules (enforced by design, see kb/README.md):
  1. Ranking NEVER sees offers. The tactics engine scores conditions only.
  2. Every offer carries an explicit disclosure field.
  3. Affiliate tags live in env/config (FISHWITCH_AMZ_TAG etc.), never code.
  4. Links are product-canonical URLs; an /out/ redirect can wrap them later
     for rotation + measurement without angler PII.

Data: kb/offers.json maps KB entry ids -> retailer URLs.
  { "chatterbait": [
      {"retailer": "zman", "kind": "manufacturer",
       "url": "https://...canonical product page..."},
      {"retailer": "amazon", "kind": "affiliate", "asin": null,
       "note": "add ASIN via PA-API lookup once Associates account qualifies"}]}
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OFFERS = ROOT / "kb" / "offers.json"

DISCLOSURE = {
    "manufacturer": "manufacturer product page (no commission)",
    "affiliate": "affiliate link — fishwitch may earn a commission",
}


def _load() -> dict:
    return json.loads(OFFERS.read_text()) if OFFERS.exists() else {}


def resolve(entry_id: str) -> list[dict]:
    """Attach final URLs + disclosures to an entry's offers."""
    out = []
    for o in _load().get(entry_id, []):
        o = dict(o)
        kind = o.get("kind", "manufacturer")
        if kind == "affiliate" and o.get("retailer") == "amazon":
            tag = os.environ.get("FISHWITCH_AMZ_TAG", "")
            if o.get("asin"):
                o["url"] = f"https://www.amazon.com/dp/{o['asin']}/"
                if tag:
                    o["url"] += f"?tag={tag}"
            else:
                o["url"] = None
                o["note"] = (o.get("note") or "") + " — ASIN pending PA-API access"
        o["disclosure"] = DISCLOSURE.get(kind, "")
        out.append(o)
    return out


def add(entry_id: str, retailer: str, url: str, kind: str = "manufacturer", asin: str | None = None):
    data = _load()
    data.setdefault(entry_id, []).append(
        dict(retailer=retailer, url=url, kind=kind, **({"asin": asin} if asin else {})))
    OFFERS.write_text(json.dumps(data, indent=2))
    return data
