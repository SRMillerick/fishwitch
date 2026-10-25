"""Personal horoscope: whole-session geometry, authored copy, no ranking.

horoscope-1 follows the existing planet/aspect vocabulary across a session,
selecting its two closest approaches within 2 degrees. Recurrence means the
same contact occurs in at least two displayed sessions. Timeline proximity is
geometry, not measured mood intensity. Snapshot helpers remain available for
the earlier prototype's geometry checks; production uses session_readings.
"""
from dataclasses import dataclass
from fishwitch import session_timeline

TRANSITS = ("Moon", "Mercury", "Venus", "Sun", "Mars", "Jupiter", "Saturn")
TARGETS = ("Moon", "Mercury", "Mars")
ASPECTS = (("sextile", 60, True), ("square", 90, False), ("trine", 120, True),
           ("opposition", 180, False))
ORB = 2.0
MAX_ENTRIES = 2
VERSION = "horoscope-1"

# Transit -> natal target. "easy" copy covers sextile and trine, "hard" covers
# square and opposition. Every phrase is authored interpretation, not a
# measurement; grouping the aspects this way is itself an editorial choice.
COPY = {
    ("Sun", "Moon"): {
        "easy": ("You may feel at home on the water, happy to enjoy the trip in your own way.",
                 "Choose what you want from the outing before measuring it against anyone else's."),
        "hard": ("You may feel you ought to be enjoying yourself more than you are.",
                 "Give yourself time to settle in without forcing a good mood.")},
    ("Sun", "Mercury"): {
        "easy": ("You may have a clear idea of what you want to try when you get to the water.",
                 "Keep that idea simple enough to give it your full attention."),
        "hard": ("You could become more attached to proving your plan right than seeing how it's working.",
                 "Look for something that might change your mind.")},
    ("Sun", "Mars"): {
        "easy": ("You may feel ready to take the lead and make a start.",
                 "Pick your first move and give it a fair chance."),
        "hard": ("You may be putting pressure on yourself to have a great trip.",
                 "Let the outing be worthwhile without needing a fish to prove it.")},
    ("Moon", "Moon"): {
        "easy": ("You may find it easy to settle into the rhythm of fishing, even when the bites are slow.",
                 "Give yourself time to enjoy being out there."),
        "hard": ("Your enthusiasm may come and go, especially if the fishing is quiet.",
                 "Give a passing mood time to settle before deciding how the trip is going.")},
    ("Moon", "Mercury"): {
        "easy": ("You may find it easier to put your finger on what's giving you a good feeling about a spot.",
                 "Take a closer look at whatever caught your interest."),
        "hard": ("A slow spell could leave you doubting a plan you felt good about a few casts ago.",
                 "Ask what's changed on the water before changing your mind.")},
    ("Moon", "Mars"): {
        "easy": ("When something catches your interest, you may feel ready to give it a go.",
                 "Choose something you're curious to try and get started."),
        "hard": ("Little setbacks may get a quick reaction from you during this session.",
                 "Take a breath before letting a snag or missed bite set the mood.")},
    ("Mercury", "Moon"): {
        "easy": ("You may have a clearer sense of what you want from this trip—a little excitement, some company, or a bit of peace.",
                 "Make room for the part of fishing you came out to enjoy."),
        "hard": ("You could spend more time wondering why you're not enjoying yourself than noticing what's around you.",
                 "Bring your attention back to the water for a few casts.")},
    ("Mercury", "Mercury"): {
        "easy": ("The small details on the water may hold your interest more than usual.",
                 "Follow one thing you're curious about and see what you notice."),
        "hard": ("Your mind may jump from one fishing idea to the next before you've given any of them a chance.",
                 "Settle on one idea to try first.")},
    ("Mercury", "Mars"): {
        "easy": ("You may find it easier to stop weighing your options and get on with fishing.",
                 "Put one of your ideas into practice and see how it goes."),
        "hard": ("You may already be planning your next move while you're still trying the last one.",
                 "Finish what you're doing before deciding what comes next.")},
    ("Venus", "Moon"): {
        "easy": ("The pleasure of being out by the water may come easily, with or without a bite.",
                 "Make room to enjoy the scenery and company as well as the fishing."),
        "hard": ("You may be so keen to keep the trip pleasant that you brush off something that's bothering you.",
                 "Give yourself a moment to admit what would make the outing more enjoyable.")},
    ("Venus", "Mercury"): {
        "easy": ("You may enjoy taking your time and noticing the little things around you.",
                 "Take a good look around before deciding what to do next."),
        "hard": ("The scenery or a good conversation could carry your attention away from the fishing.",
                 "When you're ready to focus again, give the next few casts your full attention.")},
    ("Venus", "Mars"): {
        "easy": ("Fishing may feel less like an effort and more like something you can ease into.",
                 "Settle into a pace you enjoy."),
        "hard": ("Part of you may want to put in the effort, while another part would rather sit back and relax.",
                 "Decide what kind of outing you want and let yourself enjoy that choice.")},
    ("Mars", "Moon"): {
        "easy": ("You may feel eager to get out there and throw yourself into the fishing.",
                 "Put that enthusiasm into the part of the trip you're most looking forward to."),
        "hard": ("Small frustrations could feel bigger than they deserve, especially when you're waiting for a bite.",
                 "Take a short breather when you notice yourself getting wound up.")},
    ("Mars", "Mercury"): {
        "easy": ("You may feel sharp and ready to make decisions as things change around you.",
                 "Give yourself a moment to look, then make your choice."),
        "hard": ("You may be quick to decide a spot or an idea isn't worth your time.",
                 "Check whether you've seen enough to make that call.")},
    ("Mars", "Mars"): {
        "easy": ("You may arrive with plenty of drive and a real appetite for fishing.",
                 "Pick something you want to work on and put that energy into it."),
        "hard": ("A quiet spell could have you itching to change everything at once.",
                 "Pick one change and give it a chance before making another.")},
    ("Jupiter", "Moon"): {
        "easy": ("You may head out with a hopeful mood and plenty to look forward to.",
                 "Enjoy the anticipation and leave room for the trip to surprise you."),
        "hard": ("Your hopes for the trip may grow until an ordinary outing feels like a letdown.",
                 "Make room to appreciate the smaller pleasures along the way.")},
    ("Jupiter", "Mercury"): {
        "easy": ("A new fishing idea may spark your curiosity and make you keen to learn.",
                 "Choose one thing you'd like to understand better while you're out."),
        "hard": ("One bite—or one quiet spell—could have you convinced you've figured the whole place out.",
                 "Look for the pattern to repeat before relying on it.")},
    ("Jupiter", "Mars"): {
        "easy": ("You may feel confident enough to try something you've been putting off.",
                 "Choose one manageable challenge for the outing."),
        "hard": ("You may want to fit more into this trip than you have time or energy for.",
                 "Pick the part you're most excited about and leave the rest for another outing.")},
    ("Saturn", "Moon"): {
        "easy": ("You may find it easier to stay patient when the water is quiet.",
                 "Let yourself enjoy an unhurried stretch of fishing."),
        "hard": ("You may feel quieter than usual, with less enthusiasm to spare.",
                 "Keep the outing simple and give yourself permission to take a break.")},
    ("Saturn", "Mercury"): {
        "easy": ("You may have the patience to watch closely and stick with a question.",
                 "Spend some time on a detail you'd normally hurry past."),
        "hard": ("You could get stuck second-guessing a choice or replaying a missed chance.",
                 "Take one useful lesson from it, then turn your attention to the next cast.")},
    ("Saturn", "Mars"): {
        "easy": ("You may be in the mood to keep at it, without needing something to happen every few minutes.",
                 "Give one part of your fishing some steady practice."),
        "hard": ("Fishing could start to feel like hard work, with little to show for the effort.",
                 "Take a break before deciding whether to keep going or call it a day.")},
}


@dataclass(frozen=True)
class Contact:
    transit: str
    natal: str
    aspect: str
    orb: float
    supportive: bool

    @property
    def key(self):
        return (self.transit, self.natal, self.aspect)

    def order(self):
        return (round(abs(self.orb), 9), TRANSITS.index(self.transit),
                TARGETS.index(self.natal), [a[0] for a in ASPECTS].index(self.aspect))


def angular_error(lon: float, target: float) -> float:
    """Signed shortest angular distance in (-180, 180]; same convention as the engine."""
    return (lon - target + 180) % 360 - 180


def contacts_at(transits: dict, natal_targets: dict, orb: float = ORB) -> list:
    found = []
    for transit in TRANSITS:
        lon = transits[transit]
        for target in TARGETS:
            separation = abs(angular_error(lon, natal_targets[target]))
            for aspect, angle, supportive in ASPECTS:
                for orientation in ({angle, -angle} if angle != 180 else {angle}):
                    error = ((separation - orientation + 180) % 360) - 180
                    # Compare the unrounded angular distance to the threshold.
                    if abs(error) <= orb:
                        found.append(Contact(transit, target, aspect, abs(error), supportive))
    return sorted(found, key=lambda c: c.order())


def select(sessions: list, natal_targets: dict, orb: float = ORB) -> list:
    """sessions: one dict of transit longitudes per displayed session midpoint."""
    per_session = [contacts_at(transits, natal_targets, orb) for transits in sessions]
    seen = {}
    for contacts in per_session:
        for contact in {c.key for c in contacts}:
            seen[contact] = seen.get(contact, 0) + 1
    readings = []
    for contacts in per_session:
        recurring = {c.key for c in contacts if seen[c.key] >= 2}
        # Two tightest contacts, whatever their recurrence: picking a looser
        # non-recurring contact first paired near-duplicate facets and read worse.
        chosen = contacts[:MAX_ENTRIES]
        entries = []
        for contact in chosen:
            mindset, approach = COPY[(contact.transit, contact.natal)][
                "easy" if contact.supportive else "hard"]
            entries.append(dict(transit=contact.transit, natal=contact.natal,
                                aspect=contact.aspect, orb=round(abs(contact.orb), 3),
                                supportive=contact.supportive,
                                scope="recurring" if contact.key in recurring else "midpoint",
                                mindset=mindset, approach=approach))
        readings.append(dict(
            entries=entries,
            contacts=[dict(transit=c.transit, natal=c.natal, aspect=c.aspect,
                           orb=round(abs(c.orb), 3),
                           used=c in chosen,
                           scope="recurring" if c.key in recurring else "midpoint")
                      for c in contacts],
            empty=not contacts))
    return readings


def session_readings(sessions, natal_targets, position, zone):
    """Read whole sessions, selecting the two closest approaches in each.

    Existing authored interpretations remain unchanged. Proximity varies along
    the timeline; it never changes the wording into a stronger mental claim.
    """
    paths = [session_timeline.contacts(s.start, s.end, natal_targets, TRANSITS, TARGETS,
                                      ASPECTS, position) for s in sessions]
    key = lambda c: (c['transit'], c['natal'], c['aspect'])
    counts = {}
    for contacts in paths:
        for identity in {key(c) for c in contacts}:
            counts[identity] = counts.get(identity, 0) + 1
    readings = []
    for session, contacts in zip(sessions, paths):
        public = []
        for index, contact in enumerate(contacts):
            entry = session_timeline.serialize(contact, session.start, zone)
            entry.update(used=index < MAX_ENTRIES, supportive=bool(contact['contribution']),
                         scope='recurring' if counts[key(contact)] >= 2 else 'session')
            public.append(entry)
        entries = []
        for contact in public[:MAX_ENTRIES]:
            mindset, approach = COPY[(contact['transit'], contact['natal'])][
                'easy' if contact['supportive'] else 'hard']
            entries.append(dict(contact, mindset=mindset, approach=approach))
        readings.append(dict(entries=entries, contacts=public, empty=not public,
                             start=session.start.astimezone(zone).isoformat(),
                             end=session.end.astimezone(zone).isoformat()))
    return readings
