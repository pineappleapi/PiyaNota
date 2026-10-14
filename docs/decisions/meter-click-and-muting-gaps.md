# Meter click, muted measures, failed voices: contract gap resolutions

2026-10-09. Defaults chosen by Claude to unblock the build after backend-lead's
contract pass (commit 98ab5aa). Each one is easy to change; the user is asked
to confirm the ones marked **(product)**. Tickets: PIYA-103 AC9/AC10, PIYA-107
AC7-AC9, PIYA-108 AC4-AC8, PIYA-109 AC8/AC9, PIYA-117 AC9, PIYA-207 AC10,
PIYA-208-210 design decisions.

1. **(product) Recapture for a failed voice.** *(Superseded 2026-10-14 by user decisions 2026-10-14 (3-6). The 2026-10-09 default was: no FR-24 recapture prompt for a failed voice, and `incomplete_voice_sequence` only when all four fail.)* A job with one to three failed voices still completes. Each failed voice has a cause (PIYA-103 AC10 `failedVoiceCauses`): `unreadable` (Stage 4 placed nothing for it) or `render_failed` (read, but Stage 5 could not render it). Only `unreadable` is the photos' fault, so only it offers a retake, as soon as processing is done and before Playback opens (PIYA-102 AC7, PIYA-207 AC11). The retake is of the whole score: back to Capture with pages cleared and details kept, as a new job that keeps the score's `scoreId` (PIYA-101 AC12, PIYA-207 AC12). `render_failed` keeps the Playback failed-voice alert with "try again later". When all four fail, the reason is `incomplete_voice_sequence` (whole-score retake) if at least one was `unreadable`, and `synthesis_failed` only when all four were read and none rendered (PIYA-109 AC9). *(Added 2026-10-14, user decision 2026-10-14.)* A later retake is also offered from Playback: tapping an `unreadable` voice's disabled chip or Mixer row explains "<Voice> couldn't be read from the photos" and offers Re-photograph, the same whole-score flow (PIYA-208, PIYA-209). The once-per-job offer after processing is unchanged. During a retake the library card shows processing and the old version cannot be opened (confirmed, user decision 2026-10-14).
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
   *(Confirmed 2026-10-14, user decision 2026-10-14: "Muted-measure alert shows on first Playback open per score, not on Processing". PIYA-207 AC10 now defers to Playback, and Processing never shows it. It shows on every Playback open until "Don't show again for this score" is ticked, the PIYA-208 rule, also user decision 2026-10-14.)*
6. **Alert order.** The failed-voice alert comes first, then the muted-measures
   alert. "Don't show again" is on the muted-measures alert only.
   *(Amended 2026-10-14.)* Full order: the retake offer for `unreadable` voices, before Playback (PIYA-207 AC11); then, on Playback, the failed-voice alert for `render_failed` voices and voices that fail on the device; then the muted-measures alert. The retake offer has no "Don't show again"; it is offered once per completed job.
7. **Mid-playback dropout.** A voice that fails while playing shows the same
   failed-voice alert when it happens; the other voices keep playing. A failed
   voice's Mixer row is disabled (no Solo, no slider), so the "Turn <Voice> on"
   alert never applies to it.
   *(2026-10-14: unaffected by the cause split. A mid-playback dropout is a device-side failure and shows the failed-voice alert. The disabled Mixer row applies to both `unreadable` and `render_failed` voices. For an `unreadable` voice, tapping the disabled chip or row gives the retake explanation from resolution 1, so the "Turn <Voice> on" alert still never applies.)*
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
      only if a majority of the voices that READ a meter at that bar back it,
      with at least 2. A voice that read nothing there (or sits in a
      multirest) is no vote either way. Only a system with a single live
      voice in total accepts a one-voice change. Otherwise the previous
      meter is kept and a review flag is raised (`meter_change_minority`):
      in open-score SATB every staff engraves the meter, so one voice
      reading a change is far likelier a misread. *(Added 2026-10-09, review
      round; threshold amended 2026-10-14, review round 3.)*
      *(Confirmed as is, user decision 2026-10-14: at least 2 of the voices that actually read a time signature.)*
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
    case-insensitively. `mutedMeasures`/`failedVoices` are lowercase. `failedVoiceCauses` keys are lowercase too.
13. **No count-in** *(user decision 2026-10-14)*. The metronome plays no count-in bar. The first click sounds with the music at t=0, on the pickup or on bar 1 (PIYA-210).
