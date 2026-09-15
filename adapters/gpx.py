"""GPX — the universal waypoint/track interchange for chartplotters.

Import: pull waypoints (spots) & tracks (where you fished) off any MFD export.
Export: write prime-window waypoints any Garmin/Lowrance/Humminbird can load.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"g": "http://www.topografix.com/GPX/1/1"}


def import_gpx(path: str | Path) -> dict:
    """-> {waypoints: [{name, lat, lng, desc}], tracks: [[{lat, lng, t}...]]}"""
    root = ET.parse(path).getroot()
    wpts = [dict(name=(w.findtext("g:name", default=f"wpt{i}", namespaces=NS) or "").strip(),
                 lat=float(w.get("lat")), lng=float(w.get("lon")),
                 desc=(w.findtext("g:desc", namespaces=NS) or "").strip())
            for i, w in enumerate(root.findall("g:wpt", NS))]
    tracks = []
    for tr in root.findall("g:trk", NS):
        pts = [dict(lat=float(p.get("lat")), lng=float(p.get("lon")),
                    t=(p.findtext("g:time", namespaces=NS) or ""))
               for p in tr.findall(".//g:trkpt", NS)]
        if pts:
            tracks.append(dict(name=(tr.findtext("g:name", default="track", namespaces=NS) or ""),
                               points=pts))
    return dict(waypoints=wpts, tracks=tracks)


def export_gpx(path: str | Path, waypoints: list[dict]):
    """waypoints = [{name, lat, lng, desc}] -> GPX 1.1 file."""
    ET.register_namespace("", NS["g"])
    gpx = ET.Element(f"{{{NS['g']}}}gpx", version="1.1", creator="fishwitch")
    gpx.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    meta = ET.SubElement(gpx, f"{{{NS['g']}}}name")
    meta.text = "fishwitch prime windows"
    for w in waypoints:
        e = ET.SubElement(gpx, f"{{{NS['g']}}}wpt", lat=f"{w['lat']:.6f}", lon=f"{w['lng']:.6f}")
        n = ET.SubElement(e, f"{{{NS['g']}}}name"); n.text = w.get("name", "spot")[:64]
        d = ET.SubElement(e, f"{{{NS['g']}}}desc"); d.text = w.get("desc", "")[:255]
        s = ET.SubElement(e, f"{{{NS['g']}}}sym"); s.text = w.get("sym", "Fish")
    ET.indent(gpx, space="  ")
    Path(path).write_text(ET.tostring(gpx, encoding="unicode"))


def lake_intel_from_waypoints(waypoints: list[dict]) -> list[str]:
    """Turn imported named spots into lake-registry structure notes."""
    notes = []
    for w in waypoints:
        n = w["name"].lower()
        if any(k in n for k in ("grass", "weed", "hydrilla", "pad")):
            notes.append(f"imported spot '{w['name']}' — vegetation edge ({w['lat']:.4f},{w['lng']:.4f})")
        elif any(k in n for k in ("point", "hump", "bar")):
            notes.append(f"imported spot '{w['name']}' — main-lake structure ({w['lat']:.4f},{w['lng']:.4f})")
        elif any(k in n for k in ("dock", "light")):
            notes.append(f"imported spot '{w['name']}' — dock/light target ({w['lat']:.4f},{w['lng']:.4f})")
    return notes
