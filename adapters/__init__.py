"""Adapters — mesh fishwitch with marine electronics & other programs.

Import paths (boat data -> fishwitch):
  GPX  waypoints/tracks     universal chartplotter export (Garmin/Lowrance/HB)
  SL2  Lowrance sonar logs  depth/GPS/temp stream (EXPERIMENTAL, calibrate)
  SON  Humminbird records   (EXPERIMENTAL, calibrate)
  NMEA 0183 live sentences  serial/TCP/UDP streams (DPT/DBT/MTW/RMC/GGA)
  Signal K                  open marine data server (REST/WebSocket hub)

Export paths (fishwitch -> boat/other programs):
  GPX  prime-window waypoints loadable on any MFD
  ICS  calendar events for feeding windows
  JSON the report model itself (tb/report.py::generate)
  Signal K waypoint/notification PUT

Calibration: SL2/SON binary offsets vary by firmware — feed a sample file to
`Sl2Reader.calibrate(path)`; plausibility guards reject misparsed frames.
"""
from adapters import gpx, nmea, signalk, sl2  # noqa: F401
