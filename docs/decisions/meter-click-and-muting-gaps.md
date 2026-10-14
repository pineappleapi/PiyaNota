# Meter click, muted measures, failed voices: contract gap resolutions

2026-10-09. Defaults chosen by Claude to unblock the build after backend-lead's
contract pass (commit 98ab5aa). Each one is easy to change; the user is asked
to confirm the ones marked **(product)**. Tickets: PIYA-103 AC9/AC10, PIYA-107
AC7-AC9, PIYA-108 AC4-AC8, PIYA-109 AC8/AC9, PIYA-117 AC9, PIYA-207 AC10,
PIYA-208-210 design decisions.

1. **(product) Recapture for a failed voice.** A job with one to three failed
   voices completes; the failed-voice alert names the voice. No FR-24
   recapture prompt is offered for it yet. `incomplete_voice_sequence` stays
   the reason only when all four fail.
2. **`local_placement_overrun` span.** Mute that voice from the earliest
   trimmed onset to the end of the system. Notes dropped past the system end
   never sounded, so they need no span.
3. **`bar_overflow_clipped` that drops no notes** (durations trimmed only) is
   NOT muted: the user's rule is "the repair threw notes away". It stays a
   review item. The same holds for `suspected_missing_barline` with nothing
   dropped.
4. **Timing events.** A failed voice has no events in the timing file. Events
   inside a muted span stay, so the playback indicator keeps moving.
5. **PIYA-207 alert.** PIYA-207 routes to Playback on completion, so the
   muted-measures alert is shown by Playback (once). A background completion
   shows it when Playback is next opened. PIYA-102 gains no muted count.
6. **Alert order.** The failed-voice alert comes first, then the muted-measures
   alert. "Don't show again" is on the muted-measures alert only.
7. **Mid-playback dropout.** A voice that fails while playing shows the same
   failed-voice alert when it happens; the other voices keep playing. A failed
   voice's Mixer row is disabled (no Solo, no slider), so the "Turn <Voice> on"
   alert never applies to it.
8. **Click accents for other meters.** Secondary stresses follow MuseScore's
   rule on beats per bar: every 3rd beat if divisible by 3, else every 2nd if
   divisible by 2, else at beat (n+1)/2 + 1 (5 → 3+2, 7 → 4+3, compound 15/8 →
   3+2 beats). So 8/8 and 10/8 stress every other eighth. "None known" means a
   quarter grid from each barline with only the first click of the bar
   accented; with no bars at all, the old unaccented grid. `detected` = read
   in the bar's own strip, `inherited` = carried from an earlier bar, `default`
   = nothing read before it (4/4 assumed), `unknown` = reserved.
9. **Short final bar.** `bars[].durTicks` of the last bar uses its actual
   length (`_final_bar_ticks()`), not the nominal one.
10. **Unpaired meter digit** (a lone L4 or L2 digit) is ignored: no meter change,
    and it is not read as a multirest count either.
11. **Multirest bar count** (`_measure_span()` divides by `bar_ticks`, so a 4-bar
    multirest in 3/4 counts as 5) is logged as BUG-052 and fixed with PIYA-108
    AC6.
12. Timing-file `voice` stays capitalised (`"Soprano"`); the client matches
    case-insensitively. `mutedMeasures`/`failedVoices` are lowercase.
