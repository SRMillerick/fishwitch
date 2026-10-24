"""Offline checks for the disposition prototype: geometry, selection, copy."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from fishwitch import forecast as fc
import reading

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 0, tzinfo=UTC)
WATERS = {"synthetic": dict(name="Synthetic", lat=38, lng=-122, tz="America/Los_Angeles")}
BIRTH = dict(date="1990-01-15", time="08:30", time_known=True, place="Synthetic",
             lat=38, lng=-122, tz="America/Los_Angeles")
NATAL = {"Moon": 10.0, "Mercury": 100.0, "Mars": 200.0}


def transits(moon=45.0, sun=45.0, mercury=45.0, venus=45.0, mars=45.0, jupiter=45.0, saturn=45.0):
    return dict(Moon=moon, Sun=sun, Mercury=mercury, Venus=venus, Mars=mars,
                Jupiter=jupiter, Saturn=saturn)


def request(**changes):
    payload = dict(water_id="synthetic", birth=BIRTH, request_id="reading-fixture",
                   availability=[dict(start="2026-10-23T08:00", end="2026-10-23T16:00")],
                   duration_minutes=120, daylight=False)
    payload.update(changes)
    return fc.normalize_request(payload, WATERS, NOW)


def snapshot(req):
    return fc.WeatherSnapshot(req.water.lat, req.water.lng, NOW,
                              tuple(fc.WeatherHour(NOW + timedelta(hours=i), 5, 8, 0, 0, 60)
                                    for i in range(192)))


class ContactGeometryTest(unittest.TestCase):
    def test_orb_cutoff_is_inclusive_and_unrounded(self):
        inside = reading.contacts_at(transits(sun=72.0), NATAL)
        self.assertEqual([(c.transit, c.aspect, c.natal) for c in inside], [("Sun", "sextile", "Moon")])
        self.assertEqual(inside[0].orb, 2.0)
        self.assertEqual(reading.contacts_at(transits(sun=72.001), NATAL), [])

    def test_both_orientations_squares_oppositions_and_wrap(self):
        cases = {("Sun", 100.0): ("Sun", "square", "Moon"),      # +90
                 ("Sun", 280.0): ("Sun", "square", "Moon"),      # -90 through wrap
                 ("Sun", 190.0): ("Sun", "opposition", "Moon")}
        for (_, longitude), expected in cases.items():
            found = reading.contacts_at(transits(sun=longitude), NATAL)
            self.assertIn(expected, [(c.transit, c.aspect, c.natal) for c in found])
        # Angles outside the vocabulary are geometry only, never contacts.
        self.assertEqual(reading.contacts_at(transits(sun=55.0), NATAL), [])

    def test_only_the_declared_transits_and_natal_targets_are_used(self):
        # 200 (natal Mars) trine a transit placed at 320 is in vocabulary;
        # a Jupiter-Saturn style pair outside the table is not.
        found = reading.contacts_at(transits(venus=320.0), NATAL)
        self.assertEqual([(c.transit, c.natal) for c in found], [("Venus", "Mars")])
        outside = reading.contacts_at(transits(sun=5.0, venus=5.0, jupiter=5.0, saturn=5.0), NATAL)
        self.assertTrue(all(c.transit in reading.TRANSITS and c.natal in reading.TARGETS
                            for c in outside))

    def test_copy_covers_every_pair_and_both_aspect_groups(self):
        self.assertEqual(len(reading.COPY), len(reading.TRANSITS) * len(reading.TARGETS))
        for transit in reading.TRANSITS:
            for target in reading.TARGETS:
                for kind in ("easy", "hard"):
                    mindset, approach = reading.COPY[(transit, target)][kind]
                    self.assertTrue(mindset and approach)


class SelectionTest(unittest.TestCase):
    def test_midpoint_cue_leads_then_recurring_contact(self):
        sessions = [transits(moon=160.0, sun=70.0),
                    transits(moon=46.0, sun=70.5),
                    transits(moon=47.0, sun=71.0)]
        readings = reading.select(sessions, NATAL)
        first = readings[0]
        self.assertEqual([(e["transit"], e["natal"], e["scope"]) for e in first["entries"]],
                         [("Moon", "Mercury", "midpoint"), ("Sun", "Moon", "recurring")])
        self.assertEqual(first["entries"][0]["orb"], 0.0)
        self.assertEqual(len(readings[1]["entries"]), 1)
        self.assertEqual(readings[1]["entries"][0]["scope"], "recurring")
        self.assertEqual(readings[1]["entries"][0]["orb"], 0.5)

    def test_single_displayed_session_cannot_claim_recurrence(self):
        readings = reading.select([transits(moon=160.0, sun=70.0)], NATAL)
        self.assertEqual(len(readings), 1)
        self.assertTrue(all(e["scope"] == "midpoint" for e in readings[0]["entries"]))

    def test_at_most_two_entries_and_empty_state(self):
        crowded = transits(moon=160.0, sun=70.0, mercury=160.0, venus=70.0, mars=0.0,
                           jupiter=45.0, saturn=45.0)
        readings = reading.select([crowded], NATAL)
        self.assertEqual(len(readings[0]["entries"]), reading.MAX_ENTRIES)
        self.assertGreater(len(readings[0]["contacts"]), len(readings[0]["entries"]))
        used = [c for c in readings[0]["contacts"] if c["used"]]
        self.assertEqual(len(used), reading.MAX_ENTRIES)
        empty = reading.select([transits()], NATAL)
        self.assertTrue(empty[0]["empty"])
        self.assertEqual(empty[0]["entries"], [])
        self.assertEqual(empty[0]["contacts"], [])

    def test_selection_is_deterministic_and_orb_ordered(self):
        sessions = [transits(moon=160.6, sun=70.4), transits(moon=160.1, sun=70.4)]
        readings = reading.select(sessions, NATAL)
        self.assertEqual([e["orb"] for e in readings[0]["entries"]], [0.4, 0.6])
        self.assertEqual(readings, reading.select(list(sessions), NATAL))


class IntegrationTest(unittest.TestCase):
    def test_known_birth_adds_a_reading_without_changing_the_ranking(self):
        req = request()
        data = fc.compute_sky(req)
        self.assertIn("Moon", data.points or {})
        wx = snapshot(req)
        result = fc.calculate(req, wx, data)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reading_version"], reading.VERSION)
        rows = [result["recommended"], *result["alternatives"]]
        for row in rows:
            self.assertIn("reading", row)
            self.assertIn("mindset", row["reading"]["entries"][0] if row["reading"]["entries"] else "mindset")
        without = fc.calculate(req, wx, replace(data, points=None))
        self.assertNotIn("reading_version", without)
        self.assertIsNone(without["recommended"]["reading"])
        self.assertEqual([r["start"] for r in rows], [r["start"] for r in [without["recommended"], *without["alternatives"]]])

    def test_shared_only_requests_get_no_reading(self):
        for birth in (None, dict(time_known=False)):
            req = request(birth=birth)
            result = fc.calculate(req, snapshot(req), fc.compute_sky(req))
            self.assertNotIn("reading_version", result)
            self.assertIsNone(result["recommended"]["reading"])

    def test_reading_does_not_leak_personal_details(self):
        import json
        req = request()
        data = fc.compute_sky(req)
        result = json.dumps(fc.calculate(req, snapshot(req), data))
        for secret in ("1990-01-15", "08:30"):
            self.assertNotIn(secret, result)
        # Natal longitudes stay server-side; only contacts and orbs are returned.
        for value in data.points.values():
            self.assertNotIn(f"{value:.6f}", result)


if __name__ == "__main__":
    unittest.main()
