"""Fishwitch — the fishing report apparatus.

Layers:
  geo.py      — geocoding (birth places + bodies of water), timezone lookup
  weather.py  — Open-Meteo forecast fetch + pressure trend + water-temp estimate
  skycalc.py  — Swiss Ephemeris astronomy: rise/set/transits, solunar, planetary hours
  chart.py    — natal charts + live transits + void-of-course + dignities
  tactics.py  — species/lure knowledge base + condition-matched recommendations
  report.py   — the model builder + markdown report generator (import this for a UI)
"""
