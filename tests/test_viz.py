"""Session timeline SVG — well-formed, deterministic, null-safe."""
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import viz


def model():
    t0 = datetime(2026, 5, 1, 17, 0)
    bands = [("golden", 10, 1012), ("sunset/sunrise", 2, 1011),
             ("dusk/dawn", -4, 1010), ("night", -12, 1010)]
    blocks = []
    for i, (light, alt, press) in enumerate(bands):
        s = t0 + timedelta(hours=i)
        blocks.append(dict(start=s, end=s + timedelta(hours=1), light=light, sun_alt=alt,
                           wx=dict(press=press, temp_f=70, wind_mph=6, cloud=20),
                           picks=[({"id": "dropshot", "label": "Drop shot"}, 9.0, ["why"])],
                           solunar=None, events=[]))
    return dict(start=t0, end=t0 + timedelta(hours=4), blocks=blocks, prime=blocks[2],
                sun=dict(sunset=t0 + timedelta(hours=1.5), civil_dusk=t0 + timedelta(hours=2)),
                solunar=[dict(kind="major", label="Moon overhead",
                              peak=t0 + timedelta(hours=2))])


class VizTest(unittest.TestCase):
    def test_svg_is_wellformed(self):
        svg = viz.session_timeline_svg(model())
        ET.fromstring(svg)                       # must parse
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("prime 19:00", svg)
        self.assertIn("sunset", svg)
        self.assertIn("Moon overhead", svg)
        self.assertIn("Drop shot", svg)

    def test_deterministic(self):
        self.assertEqual(viz.session_timeline_svg(model()),
                         viz.session_timeline_svg(model()))

    def test_null_safe(self):
        self.assertEqual(viz.session_timeline_svg({}), "")
        self.assertEqual(viz.session_timeline_svg(dict(start=datetime.now(),
                                                       end=datetime.now(), blocks=[])), "")


if __name__ == "__main__":
    unittest.main()
