"""Data layers — acquisition mechanisms that make reports right.

history.py   60-75 day weather history (Open-Meteo Archive) → heat/cold
             streaks, surface-temp proxy, TURNOVER INFERENCE
watertemp.py real water temp from USGS NWIS stations (where they exist)
stocking.py  CDFW planting events (trout stockings = bass forage events)

Priority when sources disagree:
  manual flag (--turnover / registry) > station data > inferred from history
"""
from layers import history, watertemp, stocking  # noqa: F401
