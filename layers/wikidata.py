"""Wikidata enrichment — structured lake facts for any named water.

OSM extratags are patchy; Wikidata publishes area (P2046 km²), elevation
(P2044 m), and for many lakes maximum depth — queryable via SPARQL for
free. This closes the morphology gap for market-scale lake coverage.

Used as a fallback: registry > manual > Wikidata > OSM extratags > defaults.
"""
from __future__ import annotations
import requests

UA = {"User-Agent": "fishwitch-mvp/1.0 (fishing report tool)",
      "Accept": "application/sparql-results+json"}
SPARQL = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?item ?itemLabel ?area ?depth ?elev WHERE {{
  ?item rdfs:label "{name}"@en .
  VALUES ?type {{ wd:Q23397 wd:Q131681 wd:Q212729 }} .
  ?item wdt:P31/wdt:P279* ?type .
  OPTIONAL {{ ?item wdt:P2046 ?area }} .
  OPTIONAL {{ ?item wdt:P2044 ?elev }} .
  OPTIONAL {{ ?item wdt:P8562 ?depth }} .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 3
"""


def lookup(name: str) -> dict | None:
    """-> {wikidata_id, area_km2, max_depth_m, elevation_m} or None."""
    label = name.split(",")[0].strip()
    try:
        r = requests.get(SPARQL, params=dict(query=QUERY.format(name=label),
                                             format="json"),
                         headers=UA, timeout=20)
        r.raise_for_status()
        bindings = r.json()["results"]["bindings"]
    except Exception:
        return None
    for b in bindings:
        out = dict(wikidata_id=b["item"]["value"].rsplit("/", 1)[-1])
        if "area" in b:
            out["area_km2"] = float(b["area"]["value"])
        if "depth" in b:
            out["max_depth_m"] = float(b["depth"]["value"])
        if "elev" in b:
            out["elevation_m"] = float(b["elev"]["value"])
        if len(out) > 1:
            return out
    return None
