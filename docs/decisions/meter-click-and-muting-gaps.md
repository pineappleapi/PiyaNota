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
   accented. With no `bars` table, the fallback quarter grid still accents
   bar starts, derived from the events' `bar` numbers. A `pickup` bar with no
   trusted meter uses the first trusted meter after it, or else counts
   quarters back from its end; its first click is never a downbeat.
   `detected` = read in the bar's own strip (a change earlier in the same
   strip still counts), `inherited` = carried from an earlier system,
   `default` = nothing read before it (4/4 assumed), `unknown` = reserved.
   The default groupings (5 = 3+2, 7 = 4+3, 8/8 stressing every other eighth)
   follow MuseScore and can be wrong for a given piece: the real grouping
   comes from beaming, which the pipeline does not read. A "wrong accent in
   7/8" report is a known limitation, not a bug. *(Amended 2026-10-09,
   review round.)*
9. **Short final bar.** `bars[].durTicks` of the last bar uses its actual
   length (`_final_bar_ticks()`), not the nominal one.
10. **Unpaired meter digit** (a lone L4 or L2 digit) changes no meter and is
    not read as a multirest count either. *(Refined 2026-10-09 by ml-cv-lead,
    verified on the Camera-PrIMuS `.agnostic` files and the Phase 1 recut
    strips; replaces "is ignored".)* The full digit rule in Stage 3:
    - A meter is `digit.<num>-L4 digit.<den>-L2` (a multi-digit number is ONE
      token, e.g. `digit.12-L4`; L4 digits are never joined) or
      `metersign.C-L3` / `metersign.C/-L3`, in the header or after a barline.
    - A multirest count is a run of `digit.N-S5` tokens, one per decimal digit
      (`digit.1-S5 digit.6-S5` = 16), ending directly at `multirest-L3`. A
      header meter is often directly before it
      (`digit.2-L4 digit.4-L2 digit.1-S5 digit.6-S5 multirest-L3`).
    - A lone L4 or L2 digit: no meter change, and the strip is flagged for
      review (`meter_digit_unpaired`), not silently dropped.
    - An S5 run not followed by a multirest (a tuplet number, a bar-number
      hallucination, or a multirest the CRNN missed) is neither count nor
      meter, and the strip is flagged (`multirest_count_orphaned`).
    - A courtesy meter at the end of a strip (meter tokens with no note, rest
      or multirest after them) does not change the meter inside that strip;
      it only announces the next system.
    - Stage 4 votes the meter per measure across the voices; voices that read
      different detected meters for the same measure raise a review flag
      (`meter_disagreement`), one per contiguous run of bars, with `bar` to
      `bar_end`.
    - A meter or metersign read mid-measure (notes or rests before it in the
      same measure) is not applied, and the strip is flagged
      (`meter_mid_measure`). *(Added 2026-10-09, review round.)*
    - A vote that would change the meter from the previous bar's is applied
      only if a majority of the voices that have that bar back it, with at
      least 2 (capped at the number of voices present). Otherwise the
      previous meter is kept and a review flag is raised
      (`meter_change_single_voice`): in open-score SATB every staff engraves
      the meter, so one voice reading a change is far likelier a misread.
      *(Added 2026-10-09, review round.)*
    - Meter flags of a strip that produced no events reach `review.items`
      through Stage 3's `strip_flags_out`.
    - Limitation: the CRNN vocabulary has no `digit.5-L4` or `digit.7-L4`, so
      5/4, 7/4, 5/8 and 7/8 cannot be read at all. Such a piece gets whatever
      meter was last read (or the 4/4 default). Not worked around.
    - Scope of the claim: the parser interprets these tokens correctly when
      the CRNN emits them. Whether the CRNN emits mid-strip meters on real
      images is unverified (it saw about 17 mid-strip examples in training;
      needs Phase 2 training).
11. **Multirest bar count** (`_measure_span()` divides by `bar_ticks`, so a 4-bar
    multirest in 3/4 counts as 5) is logged as BUG-052 and fixed with PIYA-108
    AC6.
12. Timing-file `voice` stays capitalised (`"Soprano"`); the client matches
    case-insensitively. `mutedMeasures`/`failedVoices` are lowercase.
