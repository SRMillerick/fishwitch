"""Bounded planetary paths, with exact/cutoff crossings and reversals refined.

Positions are supplied by the caller; nothing is cached beyond a request. Five
minute samples bracket motion, speeds bracket stations, and bisection refines
crossings to a millisecond in elapsed time (not an ephemeris accuracy claim).
All elapsed times are UTC seconds. The linear
weight describes proximity, not a measured psychological effect.
"""
from datetime import timedelta
from functools import lru_cache
import math

STEP = 300
ORB = 2.0


def angular_error(longitude, target):
    return (longitude - target + 180) % 360 - 180


def root(fn, left, right):
    before = fn(left)
    if before == 0:
        return left
    if fn(right) == 0:
        return right
    while right - left > 0.001:
        middle = (left + right) / 2
        value = fn(middle)
        if before * value <= 0:
            right = middle
        else:
            left, before = middle, value
    return (left + right) / 2


def proximity(orb):
    return max(0.0, 1.0 - abs(orb) / ORB)


def contacts(start, end, natal, transits, targets, aspects, position):
    """Return every contact within 2 degrees anywhere in the bounded session.

    position(body, aware_datetime) returns longitude and longitude speed/day.
    Include endpoints for drawing; don't imply the session edges are contact
    beginnings/endings. A station splits a path before checking crossings, so
    a reversal or a tangent touch is retained even without an endpoint sign flip.
    """
    duration = (end - start).total_seconds()
    if duration <= 0:
        raise ValueError("A timeline needs a positive elapsed duration")
    grid = [float(t) for t in range(0, math.ceil(duration), STEP)] + [duration]
    found = []
    for transit in transits:
        @lru_cache(maxsize=None)
        def at(seconds):
            values = position(transit, start + timedelta(seconds=seconds))
            if not all(math.isfinite(v) for v in values):
                raise ValueError("Non-finite planetary position")
            return values

        knots = set(grid)
        for left, right in zip(grid, grid[1:]):
            if at(left)[1] * at(right)[1] < 0:
                knots.add(root(lambda t: at(t)[1], left, right))
        motion = sorted(knots)
        for target in targets:
            for aspect, angle, contribution in aspects:
                # The two orientations cannot both fall within this small orb.
                for orientation in ((angle,) if angle == 180 else (angle, -angle)):
                    longitude = (natal[target] + orientation) % 360
                    error = lambda t: angular_error(at(t)[0], longitude)
                    samples = set(motion)
                    exact = []
                    for left, right in zip(motion, motion[1:]):
                        a, b = error(left), error(right)
                        if abs(a - b) > 180:
                            continue  # Opposite-side wrap, not a contact.
                        for boundary in (-ORB, 0.0, ORB):
                            if (a - boundary) * (b - boundary) < 0:
                                crossing = root(lambda t: error(t) - boundary, left, right)
                                samples.add(crossing)
                                if boundary == 0:
                                    exact.append(crossing)
                    # Station tangencies and exact grid/endpoints need no sign flip.
                    exact.extend(t for t in motion if abs(error(t)) < 1e-8)
                    best = min(samples, key=lambda t: (abs(error(t)), t))
                    minimum = abs(error(best))
                    # Allow only floating-point/root-resolution noise at a
                    # tangent boundary, not a rounded display-based cutoff.
                    if minimum > ORB + 1e-9:
                        continue
                    ordered = sorted(samples)
                    curve = [dict(seconds=t, orb=abs(error(t)), weight=proximity(error(t))) for t in ordered]
                    area = sum((b['seconds'] - a['seconds']) * (a['weight'] + b['weight']) / 2
                               for a, b in zip(curve, curve[1:]))
                    found.append(dict(transit=transit, natal=target, aspect=aspect,
                                      contribution=contribution, orb=minimum,
                                      closest_seconds=best, exact_seconds=sorted(set(exact)),
                                      mean_weight=area / duration, samples=curve))
    return sorted(found, key=lambda c: (round(c['orb'], 9), transits.index(c['transit']),
                                       targets.index(c['natal']),
                                       [a[0] for a in aspects].index(c['aspect'])))


def serialize(contact, start, zone):
    """Public geometry only: no natal longitudes or birth inputs."""
    stamp = lambda seconds: (start + timedelta(seconds=seconds)).astimezone(zone).isoformat()
    return dict(transit=contact['transit'], natal=contact['natal'], aspect=contact['aspect'],
                orb=round(contact['orb'], 4), closest_at=stamp(contact['closest_seconds']),
                exact_times=[stamp(t) for t in contact['exact_seconds']],
                mean_weight=contact['mean_weight'],
                samples=[dict(at=stamp(p['seconds']), orb=round(p['orb'], 4),
                              weight=round(p['weight'], 6)) for p in contact['samples']])
