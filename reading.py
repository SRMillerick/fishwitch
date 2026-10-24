"""Deterministic personal-disposition prototype: geometry only, no scoring.

Rules (PRODUCT_RESET.md §19, still under review):
  - transits Sun/Moon/Mercury/Venus/Mars/Jupiter/Saturn against natal Moon,
    Mercury and Mars, four aspects, absolute orb <= 2 degrees at a session
    midpoint;
  - a contact is "recurring" only when the same transit-target-aspect is present
    at two or more displayed midpoints; everything else is a midpoint cue;
  - at most two paired entries, simply the two tightest contacts at the
    midpoint; recurrence is reported in the details, not used to pick them.

This module is pure: callers supply already-computed longitudes. It never ranks
sessions, and nothing here is a claim about measured mental states.
"""
from dataclasses import dataclass

TRANSITS = ("Moon", "Mercury", "Venus", "Sun", "Mars", "Jupiter", "Saturn")
TARGETS = ("Moon", "Mercury", "Mars")
ASPECTS = (("sextile", 60, True), ("square", 90, False), ("trine", 120, True),
           ("opposition", 180, False))
ORB = 2.0
MAX_ENTRIES = 2
VERSION = "mindset-0"

# Transit -> natal target. "easy" copy covers sextile and trine, "hard" covers
# square and opposition. Every phrase is authored interpretation, not a
# measurement; grouping the aspects this way is itself an editorial choice.
COPY = {
    ("Sun", "Moon"): {
        "easy": ("You may feel more comfortable with your feelings.",
                 "Acknowledge them while noticing your surroundings."),
        "hard": ("You may feel pressured to feel a certain way.",
                 "Allow the feeling without making it a test.")},
    ("Sun", "Mercury"): {
        "easy": ("You may feel clear about your intention.",
                 "Give attention to one question."),
        "hard": ("You may feel invested in being right.",
                 "Separate what you expect from what you observe.")},
    ("Sun", "Mars"): {
        "easy": ("You may feel ready to take initiative.",
                 "Choose one action and give it time."),
        "hard": ("You may feel driven to prove yourself.",
                 "Pause before effort becomes forcing.")},
    ("Moon", "Moon"): {
        "easy": ("You may feel receptive to your own rhythm.",
                 "Notice when your attention changes."),
        "hard": ("Your mood may shift more than usual.",
                 "Let a passing feeling settle before deciding.")},
    ("Moon", "Mercury"): {
        "easy": ("You may find it easier to connect feelings and observations.",
                 "Name each without confusing them."),
        "hard": ("Your thoughts may follow your changing mood.",
                 "Check the observation before changing the plan.")},
    ("Moon", "Mars"): {
        "easy": ("You may feel ready to act on what you notice.",
                 "Use the energy without rushing."),
        "hard": ("You may be quick to react.",
                 "Pause between the impulse and the action.")},
    ("Mercury", "Moon"): {
        "easy": ("You may find it easier to notice and name feelings.",
                 "Use that awareness without overanalyzing."),
        "hard": ("You may get caught in thought about your feelings.",
                 "Distinguish the feeling from the story about it.")},
    ("Mercury", "Mercury"): {
        "easy": ("You may feel curious and mentally engaged.",
                 "Explore one question at a time."),
        "hard": ("You may feel mentally busy or scattered.",
                 "Reduce the number of things demanding attention.")},
    ("Mercury", "Mars"): {
        "easy": ("You may find it easier to turn thought into action.",
                 "Decide deliberately, then observe the result."),
        "hard": ("You may plan faster than you can attend.",
                 "Finish one decision before starting another.")},
    ("Venus", "Moon"): {
        "easy": ("You may feel comfortable and receptive.",
                 "Enjoy the ease while staying present."),
        "hard": ("You may be inclined to avoid discomfort.",
                 "Notice what you are dismissing to preserve the mood.")},
    ("Venus", "Mercury"): {
        "easy": ("You may feel unhurried and open to impressions.",
                 "Let observations register before judging."),
        "hard": ("You may be easily diverted by pleasant impressions.",
                 "Deliberately return to the question at hand.")},
    ("Venus", "Mars"): {
        "easy": ("You may feel willing to act without strain.",
                 "Use a pace you can sustain attentively."),
        "hard": ("You may feel torn between comfort and effort.",
                 "Choose deliberately rather than drifting between them.")},
    ("Mars", "Moon"): {
        "easy": ("You may feel emotionally engaged and energized.",
                 "Give that energy a deliberate outlet."),
        "hard": ("You may feel irritable or emotionally quick.",
                 "Let the first reaction pass before responding.")},
    ("Mars", "Mercury"): {
        "easy": ("You may feel decisive and alert.",
                 "Check what you noticed before acting."),
        "hard": ("You may feel impatient in your judgments.",
                 "Pause before treating the first conclusion as settled.")},
    ("Mars", "Mars"): {
        "easy": ("You may feel motivated and ready to act.",
                 "Direct effort toward one intention."),
        "hard": ("You may feel pushed to make progress.",
                 "Notice the urge to force an outcome, then reassess.")},
    ("Jupiter", "Moon"): {
        "easy": ("You may feel hopeful and emotionally open.",
                 "Enjoy the possibility without requiring a result."),
        "hard": ("Your expectations may grow with your mood.",
                 "Keep hopes separate from observations.")},
    ("Jupiter", "Mercury"): {
        "easy": ("You may feel open-minded and curious.",
                 "Explore one idea before broadening the plan."),
        "hard": ("You may jump to a broad conclusion.",
                 "Ask which observation actually supports it.")},
    ("Jupiter", "Mars"): {
        "easy": ("You may feel confident about taking initiative.",
                 "Choose a manageable commitment."),
        "hard": ("You may take on more than you can attend to.",
                 "Narrow the effort and reassess.")},
    ("Saturn", "Moon"): {
        "easy": ("You may feel emotionally steady and patient.",
                 "Allow a quiet session to unfold."),
        "hard": ("You may feel reserved or weighed down.",
                 "Acknowledge low energy without demanding enthusiasm.")},
    ("Saturn", "Mercury"): {
        "easy": ("You may feel deliberate and able to sustain attention.",
                 "Give one observation time."),
        "hard": ("You may feel cautious or stuck on a conclusion.",
                 "Test it without turning attention into self-criticism.")},
    ("Saturn", "Mars"): {
        "easy": ("You may feel persistent and measured.",
                 "Sustain effort while noticing fatigue."),
        "hard": ("You may feel blocked or rigid about effort.",
                 "Allow a pause and reconsider the demand.")},
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
