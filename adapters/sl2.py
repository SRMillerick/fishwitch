"""Lowrance .sl2/.sl3 sonar-log reader — EXPERIMENTAL.

The SL2 frame layout is community-reverse-engineered (header size 144 for SL2,
124 for SLG); offsets can shift between units/firmware. Strategy: parse with
the documented layout, then validate plausibility (coords on Earth, depth
0–250 m, monotonic-ish time). Bad frames -> skipped; a file whose frames
mostly fail is reported as needs-calibration, never silently wrong data.

Fields this unlocks: exact GPS trail with depth + water temp per ping
-> bathymetry contours, real structure map for lakes.json, real water-temp
history for the weather layer. Calibrate once per unit with a known-good log:
    Sl2Reader(path).summary()
"""
from __future__ import annotations
from pathlib import Path

HEADER_SIZE = {b"SL2": 144, b"SL3": 124, b"SLG": 124}


def detect(path: str | Path) -> str | None:
    with open(path, "rb") as f:
        magic = f.read(2)
    return magic.decode(errors="ignore") if magic in (b"SL", b"sl") and \
        Path(path).suffix.lower().lstrip(".") in ("sl2", "sl3", "slg") else None


class Sl2Reader:
    EXPERIMENTAL = True

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def summary(self) -> dict:
        kind = detect(self.path)
        if not kind:
            return dict(format="unknown", note="not a Lowrance sonar log")
        return dict(format=kind, frames="not yet parsed",
                    note="EXPERIMENTAL reader — feed a known-good sample log "
                         "to calibrate offsets before trusting output",
                    header_size=HEADER_SIZE.get(kind.encode(), None))

    # Future: iter_pings() -> {ts, lat, lng, depth_m, temp_c} with plausibility
    # guards, bathymetry() -> contour polygons, temp_history() -> daily means.
