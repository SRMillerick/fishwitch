"""Analytic paths test crossing, continuity, reversal and whole-session reading."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import unittest

from fishwitch import session_timeline as tl, reading, forecast as fc

START = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)


def paths(function, hours=2, target=10, angle=60):
    def position(body, at):
        return function((at - START).total_seconds() / 3600)
    return tl.contacts(START, START + timedelta(hours=hours), {'Moon': target},
                       ('Sun',), ('Moon',), (('sextile', angle, 1),), position)


class TimelineTest(unittest.TestCase):
    def test_exact_peak_and_triangular_area(self):
        contact, = paths(lambda h: (68 + 2 * h, 48))
        self.assertAlmostEqual(contact['mean_weight'], .5, places=5)
        self.assertAlmostEqual(contact['exact_seconds'][0], 3600, delta=.25)
        self.assertEqual(contact['samples'][0]['weight'], 0)
        self.assertEqual(contact['samples'][-1]['weight'], 0)

    def test_near_miss_outside_session_still_has_gradual_proximity(self):
        inside, = paths(lambda h: (68.99 + h, 24), hours=1)
        outside, = paths(lambda h: (69.01 + h, 24), hours=1)
        self.assertEqual(inside['exact_seconds'], [])
        self.assertEqual(len(outside['exact_seconds']), 1)
        self.assertLess(abs(inside['mean_weight'] - outside['mean_weight']), .011)

    def test_station_touches_exact_without_sign_change(self):
        # Station deliberately lies between regular samples.
        contact, = paths(lambda h: (70 + (h - .713)**2, 48 * (h - .713)))
        self.assertAlmostEqual(contact['closest_seconds'], .713 * 3600, delta=.25)
        self.assertLess(contact['orb'], 1e-8)
        self.assertEqual(len(contact['exact_seconds']), 1)

    def test_station_reenters_orb_between_samples(self):
        # Narrow synthetic visit: both regular grid edges are outside the orb.
        contact, = paths(lambda h: (71.999 + 100 * (h - .713)**2, 4800 * (h - .713)))
        self.assertLess(contact['orb'], 2)
        self.assertGreater(contact['mean_weight'], 0)
        self.assertTrue(any(p['weight'] == 0 for p in contact['samples']))

    def test_tangent_cutoff_and_just_outside_are_distinct(self):
        contact, = paths(lambda h: (72 + (h - .713)**2, 48 * (h - .713)))
        self.assertAlmostEqual(contact['orb'], 2, places=8)
        self.assertLess(contact['mean_weight'], 1e-9)
        self.assertEqual(paths(lambda h: (72.000001 + (h - .713)**2, 48 * (h - .713))), [])

    def test_reversal_preserves_two_peaks_and_gap(self):
        contact, = paths(lambda h: (70 + 4 * (h - 1)**2 - 3, 192 * (h - 1)))
        self.assertEqual(len(contact['exact_seconds']), 2)
        middle = next(p for p in contact['samples'] if p['seconds'] == 3600)
        self.assertEqual(middle['weight'], 0)

    def test_wrap_and_negative_orientation(self):
        contact, = paths(lambda h: ((359 + h) % 360, 24), target=60)
        self.assertAlmostEqual(contact['exact_seconds'][0], 3600, delta=.25)
        # Crossing 180 degrees from the target isn't a zero crossing.
        self.assertEqual(paths(lambda h: ((249 + h) % 360, 24)), [])

    def test_endpoint_is_not_reported_as_start_of_influence(self):
        contact, = paths(lambda h: (70.5, 0))
        public = tl.serialize(contact, START, ZoneInfo('America/Los_Angeles'))
        self.assertEqual(public['exact_times'], [])
        self.assertEqual(public['samples'][0]['weight'], .75)
        self.assertEqual(public['samples'][-1]['weight'], .75)
        self.assertNotIn('influence_start', public)

    def test_invalid_positions_fail_instead_of_claiming_empty_reading(self):
        with self.assertRaises(ValueError):
            paths(lambda h: (float('nan'), 0))

    def test_whole_session_finds_contact_missing_at_midpoint(self):
        session = fc.Interval(START, START + timedelta(hours=4))
        def position(body, at):
            hours = (at - START).total_seconds() / 3600
            return (71.9 + hours, 24) if body == 'Sun' else (45, 0)
        natal = {'Moon': 10, 'Mercury': 100, 'Mars': 200}
        result, = reading.session_readings([session], natal, position, timezone.utc)
        self.assertFalse(result['empty'])
        entry = result['entries'][0]
        self.assertEqual((entry['transit'], entry['natal']), ('Sun', 'Moon'))
        self.assertGreater(entry['samples'][0]['weight'], 0)
        self.assertEqual(entry['samples'][-1]['weight'], 0)
        self.assertEqual(entry['mindset'], reading.COPY[('Sun', 'Moon')]['easy'][0])

    def test_dst_fall_back_retains_elapsed_time_and_offsets(self):
        start = datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)
        contact, = tl.contacts(start, start + timedelta(hours=2), {'Moon': 10},
                              ('Sun',), ('Moon',), (('sextile', 60, 1),), lambda body, at: (70.5, 0))
        public = tl.serialize(contact, start, ZoneInfo('America/Los_Angeles'))
        first, last = public['samples'][0]['at'], public['samples'][-1]['at']
        self.assertTrue(first.endswith('-07:00'))
        self.assertTrue(last.endswith('-08:00'))
        self.assertEqual((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds(), 7200)
