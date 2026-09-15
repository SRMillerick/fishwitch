"""NMEA 0183 — live boat data (depth, water temp, position, speed).

Any NMEA gateway (Yacht Devices, Actisense, Digital Yacht, or the MFD's own
TCP feed) streams these sentences. fishwitch uses them live on the water:
  GGA/RMC -> position + fix time     DPT/DBT -> real depth (no estimating!)
  MTW     -> real water temperature  VHW     -> speed through water
"""
from __future__ import annotations


def _valid(sentence: str) -> bool:
    if "*" not in sentence:
        return False
    body, ck = sentence.rsplit("*", 1)
    x = 0
    for c in body[1:]:
        x ^= ord(c)
    return f"{x:02X}" == ck.strip().upper()[:2]


def _coord(v: str, hemi: str) -> float | None:
    if not v:
        return None
    deg = float(v[:v.index(".") - 2])
    minutes = float(v[v.index(".") - 2:])
    val = deg + minutes / 60
    return -val if hemi in ("S", "W") else val


def parse(sentence: str) -> dict | None:
    """'$SDDBT,17.1,f,5.2,m,*..' -> {'type':'depth_m','value':5.2}"""
    s = sentence.strip()
    if not _valid(s):
        return None
    body = s.split("*")[0]
    parts = body.split(",")
    talker_type = parts[0][3:]  # strip $GP/$SD etc
    try:
        if talker_type == "DBT":
            return dict(type="depth_m", value=float(parts[3]))  # meters field
        if talker_type == "DPT":
            return dict(type="depth_m", value=float(parts[1]))
        if talker_type == "MTW":
            return dict(type="water_temp_c", value=float(parts[1]))
        if talker_type == "VHW":
            return dict(type="speed_kn", value=float(parts[5] or 0))
        if talker_type == "GGA":
            return dict(type="fix", lat=_coord(parts[2], parts[3]),
                        lng=_coord(parts[4], parts[5]), sats=int(parts[7] or 0))
        if talker_type == "RMC":
            return dict(type="fix", lat=_coord(parts[3], parts[4]),
                        lng=_coord(parts[5], parts[6]),
                        speed_kn=float(parts[7] or 0),
                        time=f"{parts[9]}T{parts[1][:6]}Z" if len(parts) > 9 else None)
    except (ValueError, IndexError):
        return None
    return None


class Stream:
    """feed() NMEA lines as they arrive; keeps latest state."""

    def __init__(self):
        self.state = dict(depth_m=None, water_temp_c=None, lat=None, lng=None,
                          speed_kn=None, updates=0)

    def feed(self, line: str) -> dict | None:
        m = parse(line)
        if not m:
            return None
        t = m.pop("type")
        if t == "depth_m":
            self.state["depth_m"] = m["value"]
        elif t == "water_temp_c":
            self.state["water_temp_c"] = m["value"]
        elif t == "speed_kn":
            self.state["speed_kn"] = m["value"]
        elif t == "fix":
            self.state.update({k: v for k, v in m.items() if v is not None})
        self.state["updates"] += 1
        return dict(type=t, **m)

    @property
    def water_temp_f(self):
        return self.state["water_temp_c"] * 9 / 5 + 32 if self.state["water_temp_c"] else None


def tail_tcp(host: str, port: int, stream: Stream, on_event=None):
    """Blocking tail of a TCP NMEA feed (typical gateway output)."""
    import socket
    with socket.create_connection((host, port), timeout=10) as s:
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                ev = stream.feed(line.decode(errors="ignore"))
                if ev and on_event:
                    on_event(ev)
