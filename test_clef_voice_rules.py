"""Standalone checks for the voice-constrained clef decision (clef_voice_rules.resolve_clef).

Run: ``python test_clef_voice_rules.py`` (exit code 1 on any failure). No test framework in this repo.
Probability order is clef_key_core.CLEF_CLASSES: (G, G8vb, F, other).
"""
from __future__ import annotations

import sys
from typing import Callable

from clef_voice_rules import ClefDecision, resolve_clef

THR = 0.3  # the frozen T4 checkpoint's clef_threshold
FAILURES: list[str] = []


def check(name: str, got: object, want: object) -> None:
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def summary(d: ClefDecision) -> tuple[str, str, int, str]:
    return d.clef_class, d.token, d.octave_shift, d.source


def raises(name: str, fn: Callable[[], object]) -> None:
    try:
        fn()
    except ValueError:
        return
    FAILURES.append(f"{name}: expected ValueError")


def main() -> int:
    # Confident, allowed readings pass straight through.
    check("soprano G", summary(resolve_clef("Soprano", [0.97, 0.01, 0.01, 0.01], THR, True)),
          ("G", "clef.G-L2", 0, "classifier"))
    check("bass F", summary(resolve_clef("Bass", [0.01, 0.01, 0.97, 0.01], THR, True)),
          ("F", "clef.F-L4", 0, "classifier"))
    check("tenor G8vb", summary(resolve_clef("Tenor", [0.05, 0.9, 0.04, 0.01], THR, True)),
          ("G8vb", "clef.G-L2", -12, "classifier"))
    check("tenor F", summary(resolve_clef("Tenor", [0.02, 0.02, 0.95, 0.01], THR, True)),
          ("F", "clef.F-L4", 0, "classifier"))
    check("bass G8vb", summary(resolve_clef("Bass", [0.03, 0.9, 0.06, 0.01], THR, True)),
          ("G8vb", "clef.G-L2", -12, "classifier"))
    d = resolve_clef("Soprano", [0.97, 0.01, 0.01, 0.01], THR, True)
    check("clean reading has no flags", d.flags, ())
    check("bass G8vb always reviewed", "review_needed" in resolve_clef("Bass", [0.03, 0.9, 0.06, 0.01],
                                                                        THR, True).flags, True)

    # Low voices pool G and G8vb (same audio), so a Bass read as plain G is not pushed to the F default.
    d = resolve_clef("Bass", [0.9, 0.05, 0.04, 0.01], THR, True)
    check("bass plain G -> G8vb", summary(d), ("G8vb", "clef.G-L2", -12, "classifier"))
    d = resolve_clef("Tenor", [0.2, 0.15, 0.6, 0.05], THR, True)
    check("tenor F beats pooled treble 0.35", d.clef_class, "F")
    d = resolve_clef("Tenor", [0.2, 0.2, 0.1, 0.5], THR, True)
    check("tenor split treble pooled over threshold", (d.clef_class, d.octave_shift, d.source),
          ("G8vb", -12, "classifier_voice_restricted"))

    # Plain treble on a tenor line is sung 8vb (choral convention); an explicit G8vb is not doubled.
    d = resolve_clef("Tenor", [0.9, 0.05, 0.04, 0.01], THR, True)
    check("tenor plain G octave", (d.token, d.octave_shift), ("clef.G-L2", -12))
    check("tenor plain G flag", "plain_treble_on_low_voice_assumed_8vb" in d.flags, True)
    check("tenor plain G not review", "review_needed" in d.flags, False)

    # Confident but disallowed: the best allowed clef wins, flagged (real case: Alto G read as F).
    d = resolve_clef("Alto", [0.35, 0.02, 0.62, 0.01], THR, True)
    check("alto F->G restricted", summary(d), ("G", "clef.G-L2", 0, "classifier_voice_restricted"))
    check("alto restricted flags", d.flags, ("clef_voice_mismatch", "review_needed"))
    check("alto restricted keeps raw top", d.classifier_top, "F")
    d = resolve_clef("Soprano", [0.4, 0.55, 0.04, 0.01], THR, True)
    check("soprano G8vb->G restricted", summary(d), ("G", "clef.G-L2", 0, "classifier_voice_restricted"))
    d = resolve_clef("Tenor", [0.1, 0.35, 0.05, 0.5], THR, True)
    check("tenor other->G8vb", summary(d), ("G8vb", "clef.G-L2", -12, "classifier_voice_restricted"))
    check("tenor other flagged out of scope", "clef_out_of_scope" in d.flags, True)

    # No allowed clef reaches the threshold: the voice default, flagged.
    for voice, want in (("Soprano", ("G", "clef.G-L2", 0)), ("Alto", ("G", "clef.G-L2", 0)),
                        ("Tenor", ("G8vb", "clef.G-L2", -12)), ("Bass", ("F", "clef.F-L4", 0))):
        d = resolve_clef(voice, [0.1, 0.1, 0.1, 0.7], THR, True)
        check(f"{voice} default", (d.clef_class, d.token, d.octave_shift, d.source), (*want, "voice_default"))
        check(f"{voice} default flags", {"clef_unsure", "review_needed"} <= set(d.flags), True)
    # Restriction uses the raw probability, so a weak allowed clef is not promoted by renormalising.
    d = resolve_clef("Alto", [0.25, 0.05, 0.69, 0.01], THR, True)
    check("weak allowed clef -> default", d.source, "voice_default")
    check("threshold is inclusive", resolve_clef("Alto", [0.3, 0.0, 0.7, 0.0], THR, True).source,
          "classifier_voice_restricted")

    # g8vb_reliable=False: G and G8vb pooled, octave from the voice.
    d = resolve_clef("Tenor", [0.2, 0.15, 0.6, 0.05], THR, False)
    check("unreliable tenor F still wins", summary(d), ("F", "clef.F-L4", 0, "classifier"))
    d = resolve_clef("Tenor", [0.2, 0.2, 0.55, 0.05], THR, False)
    check("unreliable tenor treble pooled 0.4 < F 0.55", d.clef_class, "F")
    d = resolve_clef("Tenor", [0.5, 0.1, 0.35, 0.05], THR, False)
    check("unreliable tenor treble", summary(d), ("G8vb", "clef.G-L2", -12, "classifier"))
    check("unreliable octave flag", "octave_from_voice_prior" in d.flags, True)
    d = resolve_clef("Alto", [0.2, 0.75, 0.04, 0.01], THR, False)
    check("unreliable alto G8vb is just treble", summary(d), ("G", "clef.G-L2", 0, "classifier"))
    d = resolve_clef("Bass", [0.2, 0.2, 0.55, 0.05], THR, False)
    check("unreliable bass F", summary(d), ("F", "clef.F-L4", 0, "classifier"))

    # Bad input fails loudly.
    raises("unknown voice", lambda: resolve_clef("Solo", [1.0, 0.0, 0.0, 0.0], THR, True))
    raises("wrong length", lambda: resolve_clef("Alto", [0.5, 0.5, 0.0], THR, True))
    raises("nan", lambda: resolve_clef("Alto", [float("nan"), 0.5, 0.5, 0.0], THR, True))
    raises("not a softmax", lambda: resolve_clef("Alto", [0.9, 0.9, 0.0, 0.0], THR, True))
    raises("threshold out of range", lambda: resolve_clef("Alto", [1.0, 0.0, 0.0, 0.0], 1.5, True))

    for f in FAILURES:
        print("FAIL", f)
    print(f"{'FAILED' if FAILURES else 'OK'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
