"""Voice-constrained clef decision for the clef/key classifier (PIYA-106, plan section 3.3 as amended 2026-09-28).

The classifier is confidently wrong on about 4.5% of real-photo staves (BUG-021), and its 4-class output
(G, G8vb, F, other) includes clefs a given SATB voice never uses. In open-score SATB the voice (from the
staff's position, Stage 2) already limits the clef, so this module lets the classifier choose only
among the clefs that voice can have, and falls back to the voice's usual clef when even the best allowed
clef is below the checkpoint's threshold.

Not wired into Stage 3 yet: Stage 3 still reads its clef from the CRNN. This is the decision rule only.
No threshold here is fitted: ``clef_threshold`` and ``g8vb_reliable`` come from the frozen checkpoint.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from clef_key_core import CLEF_CLASSES

VOICES: tuple[str, ...] = ("Soprano", "Alto", "Tenor", "Bass")

# User decision 2026-09-28. Tenor may be written in treble, treble-8vb or bass clef; Bass in bass or
# treble-8vb. "other" (C clefs and the like) is allowed for no voice: C clefs are out of scope.
ALLOWED_CLEFS: Mapping[str, frozenset[str]] = {
    "Soprano": frozenset({"G"}),
    "Alto": frozenset({"G"}),
    "Tenor": frozenset({"G", "G8vb", "F"}),
    "Bass": frozenset({"F", "G8vb"}),
}

# Used when no allowed clef reaches the threshold (clef unreadable).
DEFAULT_CLEF: Mapping[str, str] = {"Soprano": "G", "Alto": "G", "Tenor": "G8vb", "Bass": "F"}

TREBLE_TOKEN = "clef.G-L2"
BASS_TOKEN = "clef.F-L4"
OCTAVE_DOWN = -12
# Choral convention (choral-conductor brief, user-confirmed 2026-09-28): a plain treble clef on a tenor
# line is still sung an octave lower. Voices listed here read any treble-family clef 8vb.
TREBLE_8VB_VOICES: frozenset[str] = frozenset({"Tenor", "Bass"})

_PROB_SUM_TOLERANCE = 1e-3


@dataclass(frozen=True)
class ClefDecision:
    """Resolved clef for one staff.

    Attributes:
        clef_class: One of ``CLEF_CLASSES`` except "other".
        token: Camera-PrIMuS clef token Stage 3 understands (``clef.G-L2`` or ``clef.F-L4``).
        octave_shift: Semitones to add to the written pitch (0 or -12). Callers must not add Stage 3's
            own Tenor octave rule on top of this, or a tenor line drops two octaves.
        source: "classifier", "classifier_voice_restricted" or "voice_default".
        classifier_top: The classifier's unrestricted top class, kept for review and logging.
        flags: Machine-readable reasons; "review_needed" is present whenever a human should look.
    """

    clef_class: str
    token: str
    octave_shift: int
    source: str
    classifier_top: str
    flags: tuple[str, ...] = field(default_factory=tuple)


def _validate(voice: str, clef_probs: Sequence[float], clef_threshold: float) -> None:
    if voice not in ALLOWED_CLEFS:
        raise ValueError(f"unknown voice {voice!r}; expected one of {VOICES}")
    if len(clef_probs) != len(CLEF_CLASSES):
        raise ValueError(f"expected {len(CLEF_CLASSES)} clef probabilities {CLEF_CLASSES}, got {len(clef_probs)}")
    if any(not math.isfinite(p) or p < 0.0 for p in clef_probs):
        raise ValueError(f"clef probabilities must be finite and non-negative, got {list(clef_probs)}")
    if abs(sum(clef_probs) - 1.0) > _PROB_SUM_TOLERANCE:
        raise ValueError(f"clef probabilities must sum to 1 (softmax output), got sum {sum(clef_probs):.6f}")
    if not 0.0 <= clef_threshold <= 1.0:
        raise ValueError(f"clef_threshold must be in [0, 1], got {clef_threshold}")


def _to_output(clef_class: str, voice: str) -> tuple[str, int, tuple[str, ...]]:
    """Maps a resolved class to (token, octave_shift, informational flags)."""
    if clef_class == "F":
        return BASS_TOKEN, 0, ()
    if clef_class == "G8vb":
        return TREBLE_TOKEN, OCTAVE_DOWN, ()
    if voice in TREBLE_8VB_VOICES:  # plain G on a low voice; only Tenor can reach here (Bass disallows G)
        return TREBLE_TOKEN, OCTAVE_DOWN, ("plain_treble_on_low_voice_assumed_8vb",)
    return TREBLE_TOKEN, 0, ()


def resolve_clef(voice: str, clef_probs: Sequence[float], clef_threshold: float,
                 g8vb_reliable: bool) -> ClefDecision:
    """Chooses a clef for one staff from the classifier's probabilities and the staff's voice.

    Only the voice's allowed clefs compete; the raw probability (not renormalised) of the best allowed
    clef must reach ``clef_threshold``, so restricting the choice never makes a weak reading look sure.

    With ``g8vb_reliable=False`` the checkpoint cannot tell G from G8vb, so the two are pooled as one
    treble family and the octave comes from the voice (plan 3.3 rule 3).

    Args:
        voice: Voice from the staff's position ("Soprano", "Alto", "Tenor" or "Bass").
        clef_probs: Calibrated softmax over ``CLEF_CLASSES``.
        clef_threshold: The checkpoint's ``clef_threshold``.
        g8vb_reliable: The checkpoint's ``g8vb_reliable``.

    Returns:
        The decision, with "review_needed" in ``flags`` whenever the classifier was overruled or unsure.

    Raises:
        ValueError: On an unknown voice, a malformed probability vector or an out-of-range threshold.
    """
    _validate(voice, clef_probs, clef_threshold)
    probs = dict(zip(CLEF_CLASSES, (float(p) for p in clef_probs)))
    classifier_top = max(CLEF_CLASSES, key=lambda c: probs[c])
    allowed = ALLOWED_CLEFS[voice]

    # On a low voice G and G8vb sound the same (both read 8vb), so their probabilities are pooled even when
    # the checkpoint can tell them apart; otherwise a Bass read as plain G would fall to the F default.
    # Pooling is also forced when g8vb_reliable is False (plan 3.3 rule 3). Caveat: the threshold was
    # calibrated on single-class maxima, so a pooled two-class sum passes it slightly more easily.
    if g8vb_reliable and voice not in TREBLE_8VB_VOICES:
        scores = {c: probs[c] for c in allowed}
        top_family = classifier_top
    else:
        treble = probs["G"] + probs["G8vb"]
        if voice in TREBLE_8VB_VOICES:
            # Tenor keeps the class the model preferred (logging only; the audio is the same). Bass
            # disallows plain G, so its treble family is always G8vb.
            prefer_plain = g8vb_reliable and "G" in allowed and probs["G"] > probs["G8vb"]
            family_class = "G" if prefer_plain else "G8vb"
        else:
            family_class = "G"
        scores = {("F" if c == "F" else family_class): (probs["F"] if c == "F" else treble) for c in allowed}
        top_family = {"G": family_class, "G8vb": family_class}.get(classifier_top, classifier_top)

    best = max(sorted(scores), key=lambda c: scores[c])  # sorted: deterministic tie-break
    flags: list[str] = []
    if scores[best] >= clef_threshold:
        chosen = best
        if best == top_family:
            source = "classifier"
        else:
            source = "classifier_voice_restricted"
            flags += ["clef_voice_mismatch", "review_needed"]
    else:
        chosen = DEFAULT_CLEF[voice]
        source = "voice_default"
        flags += ["clef_unsure", "clef_below_threshold", "review_needed"]
    if classifier_top == "other":
        flags.append("clef_out_of_scope")
    # Treble-8vb on a Bass line is rare in SATB and usually means the layout shifted (a Tenor in the Bass
    # position), and a real F-clef Bass misread as G8vb lands a sixth high, inside a plausible range, so
    # no range check would catch it (choral-conductor review 2026-09-28).
    if voice == "Bass" and chosen == "G8vb" and "review_needed" not in flags:
        flags += ["bass_treble_8vb", "review_needed"]
    if not g8vb_reliable and chosen in ("G", "G8vb"):
        flags.append("octave_from_voice_prior")

    token, octave, info = _to_output(chosen, voice)
    return ClefDecision(clef_class=chosen, token=token, octave_shift=octave, source=source,
                        classifier_top=classifier_top, flags=tuple(flags) + info)
