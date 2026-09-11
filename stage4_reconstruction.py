"""
PiyaNota - Stage 4: SATB Part Reconstruction
Combines pitch-assigned event sequences from Stage 3 into four continuous
voice sequences in correct reading order, ready for Stage 5 MIDI synthesis.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Expected voices ───────────────────────────────────────────────────────────
VOICES = ["Soprano", "Alto", "Tenor", "Bass"]

# Tick tolerance for the per-measure duration consistency check below.
# 10 ticks (~1/48 of a quarter note at PPQ=480) absorbs int() truncation
# from repeated dotted-note (*1.5) rounding without masking a genuine
# dropped/extra note or rest.
DURATION_MISMATCH_TOLERANCE_TICKS = 10


# ── Main reconstruction function ──────────────────────────────────────────────

def reconstruct_satb(
    voice_events: dict,
) -> dict:
    """
    Combines pitch-assigned event sequences into four complete voice sequences.

    Accepts the direct output of Stage 3 transcribe_voice_sequences():
        {voice: [event_dict, ...]}

    Each event_dict contains:
        type, pitch, duration_ticks, voice, page_index, sys_idx,
        chord_id, symbol, tick_onset, slur

    Returns:
        {voice: [event_dict, ...]} sorted by page_index, then sys_idx, then
        tick_onset, with slur durations resolved and tick_onset renumbered
        to a single globally-monotonic timeline across systems (see
        _assign_global_ticks).

    Raises:
        ValueError if any voice sequence is missing or empty.
    """
    # print(), not logger.info(): no file in this codebase calls
    # logging.basicConfig()/addHandler() (confirmed via the independent
    # /code-review pass on this same branch), so a bare logger.info() call is
    # silently dropped by the default root WARNING level and never reaches the
    # console -- unlike logger.warning() below, which still surfaces via
    # Python's stderr "handler of last resort". This message was always-visible
    # print() output before PIYA-124; keeping it print() preserves that.
    print("\n[Stage 4] Reconstructing SATB part sequences...")

    # ── Validate completeness ─────────────────────────────────────────────
    missing = [v for v in VOICES if v not in voice_events
               or len(voice_events[v]) == 0]
    if missing:
        raise ValueError(
            f"[Stage 4] Missing or empty voice sequence(s): {missing}. "
            f"Check Stage 2/3 outputs or recapture the score."
        )

    reconstructed = {}

    for voice in VOICES:
        events = voice_events[voice]

        # ── Sort by page index, then system, then tick onset ──────────────
        # sys_idx must sort before tick_onset: tick_onset resets to 0 at the
        # start of every Stage 3 infer_pitch() call (once per system's voice
        # strip), so without sys_idx in the key, events from different
        # systems on the same page would interleave here -- corrupting
        # both playback order and _resolve_slurs()'s sequential scan below.
        events = sorted(events, key=lambda e: (e["page_index"], e["sys_idx"], e["tick_onset"]))

        # ── Resolve slur durations ────────────────────────────────────────
        events = _resolve_slurs(events, voice)

        reconstructed[voice] = events

    # ── Renumber tick_onset onto one global timeline ───────────────────────
    # Must run after sorting/slur-resolution (both are per-voice and order-
    # only) and before Stage 5 ever sees this dict -- Stage 5 groups events
    # by raw tick_onset and derives absolute MIDI time directly from it, both
    # of which assume a single monotonic clock rather than one that resets
    # to 0 at every system.
    _assign_global_ticks(reconstructed)

    _check_measure_duration_consistency(reconstructed)
    _check_voice_pitch_range_plausibility(reconstructed)
    _report(reconstructed)
    return reconstructed


# ── Global tick assignment ─────────────────────────────────────────────────────

def _assign_global_ticks(reconstructed: dict) -> None:
    """
    Mutates tick_onset in place so it increases monotonically across the
    whole piece instead of resetting to 0 at the start of every system.

    Root cause this fixes: Stage 3's infer_pitch() runs once per detected
    strip (i.e. once per system), so tick_onset is only ever meaningful
    *within* one system. Stage 5's synthesize_satb() groups events with
    `tick_map[ev["tick_onset"]]` and computes `onset_beats = tick_onset /
    PPQ` straight off that value -- so without this pass, system 2's notes
    land on the same tick range as system 1's and get synthesized as
    simultaneous chords instead of playing after them. This reproduces on
    any piece with more than one system, which is the common case, not an
    edge case.

    The offset added at each (page_index, sys_idx) boundary is the *same
    for all four voices*, derived from the max end-tick (tick_onset +
    duration_ticks) across voices for that system -- not each voice's own
    total. Using a shared clock means a single Stage-3 duration error in
    one voice (already surfaced separately by
    _check_measure_duration_consistency) shifts that one system boundary
    slightly but does not compound into a growing desync between voice
    tracks for the rest of the piece, which a per-voice offset would do.

    Args:
        reconstructed: {voice: [event_dict, ...]}, already sorted; mutated
          in place.
    """
    system_keys = sorted({
        (e["page_index"], e["sys_idx"])
        for events in reconstructed.values()
        for e in events
    })

    system_end_tick: dict = {}
    for events in reconstructed.values():
        per_system_end: dict = {}
        for e in events:
            key = (e["page_index"], e["sys_idx"])
            end = e["tick_onset"] + e["duration_ticks"]
            per_system_end[key] = max(per_system_end.get(key, 0), end)
        for key, end in per_system_end.items():
            system_end_tick[key] = max(system_end_tick.get(key, 0), end)

    offset_for_system: dict = {}
    running_offset = 0
    for key in system_keys:
        offset_for_system[key] = running_offset
        running_offset += system_end_tick.get(key, 0)

    for events in reconstructed.values():
        for e in events:
            key = (e["page_index"], e["sys_idx"])
            e["tick_onset"] += offset_for_system[key]


# ── Slur resolution ───────────────────────────────────────────────────────────

def _resolve_slurs(events: list, voice: str) -> list:
    """
    Resolves slurred note groups into extended durations.

    A slur means one continuous sound across multiple noteheads.
    The first note (slur=start) absorbs the duration of all subsequent
    notes until slur=end. Middle and end notes are silenced (pitch=None,
    duration=0) so Stage 5 skips them without advancing the tick incorrectly.

    Note: tick_onset values are preserved so chord grouping still works.
    """
    i = 0
    while i < len(events):
        ev = events[i]

        if ev.get("slur") == "start" and ev["type"] == "note":
            # Accumulate duration across the slur group
            total_ticks = ev["duration_ticks"]
            j = i + 1

            while j < len(events):
                next_ev = events[j]
                if next_ev["type"] != "note":
                    j += 1
                    continue

                total_ticks += next_ev["duration_ticks"]

                if next_ev.get("slur") == "end":
                    # Extend the start note, silence everything in between
                    events[i]["duration_ticks"] = total_ticks
                    for k in range(i + 1, j + 1):
                        if events[k]["type"] == "note":
                            events[k]["pitch"]          = None
                            events[k]["duration_ticks"] = 0
                            events[k]["slur"]           = "absorbed"
                    break

                j += 1

        i += 1

    # Remove absorbed slur notes (silenced middle/end notes)
    events = [e for e in events if e.get("slur") != "absorbed"]

    return events


# ── Cross-voice duration consistency (diagnostic only) ────────────────────────

def _measure_duration_totals(events: list) -> dict:
    """
    Sums duration_ticks per (page_index, sys_idx, measure_index) for one voice.

    Chord notes share a single tick_onset -- only the first note of a
    chord actually advances the shared clock in Stage 3's infer_pitch()
    (see the `in_chord` handling there), so summing every event's
    duration_ticks directly would double-count stacked chord notes.
    Deduplicating by (page_index, sys_idx, measure_index, tick_onset) first
    avoids that: each unique onset contributes its duration once, taking the
    max across any simultaneous notes at that onset.

    sys_idx (the 1-based system number within the page) is included in the
    key because measure_index and tick_onset both reset to 0 per Stage 3
    infer_pitch() call, and infer_pitch() runs once per detected strip --
    i.e. once per system's voice line, not once per page. Without sys_idx in
    the key, a page with more than one system would alias events from
    unrelated systems that happen to share a measure number.

    Args:
        events: One voice's event list, each carrying measure_index and
          sys_idx (both added to the event dict in
          stage3_transcription.infer_pitch()).

    Returns:
        {(page_index, sys_idx, measure_index): summed_duration_ticks}
    """
    onset_ticks: dict = {}
    for e in events:
        key = (e["page_index"], e.get("sys_idx"), e.get("measure_index"), e["tick_onset"])
        onset_ticks[key] = max(onset_ticks.get(key, 0), e["duration_ticks"])

    totals: dict = {}
    for (page_index, sys_idx, measure_index, _tick_onset), ticks in onset_ticks.items():
        totals_key = (page_index, sys_idx, measure_index)
        totals[totals_key] = totals.get(totals_key, 0) + ticks
    return totals


def _check_measure_duration_consistency(reconstructed: dict) -> None:
    """
    Read-only diagnostic: logs (does not correct) any measure where one
    SATB voice's summed duration diverges from the others by more than
    DURATION_MISMATCH_TOLERANCE_TICKS.

    A genuine per-voice divergence usually means Stage 3 dropped or
    hallucinated a note/rest token for that voice on that strip -- exactly
    the failure mode more common on distorted/camera-captured input (this
    session measured 0.70% SER on clean Camera-PrIMuS images vs 18.76% on
    the same samples' distorted variant). This function never raises and
    never mutates `reconstructed`; it only adds visibility into a class of
    error that would otherwise pass through Stage 4/5 silently, since
    nothing downstream currently cross-checks voices against each other.

    measure_index and tick_onset are both reset to 0 per Stage 3
    infer_pitch() call, and infer_pitch() runs once per detected strip --
    i.e. once per system's voice line, not once per page. sys_idx (the
    1-based system number within the page, threaded from Stage 2 through
    Stage 3's event dict) is included in _measure_duration_totals()'s keys
    for exactly this reason, so that this function's per-measure comparison
    never aliases events from unrelated systems that happen to share a
    measure number -- the same fix also applies to
    transcribe_voice_sequences()'s all_events.sort() (same root cause).

    Args:
        reconstructed: {voice: [event_dict, ...]}, already sorted and
          slur-resolved -- the dict this function's caller is about to
          return from reconstruct_satb().
    """
    per_voice_totals = {voice: _measure_duration_totals(events)
                         for voice, events in reconstructed.items()}

    all_measures = set()
    for totals in per_voice_totals.values():
        all_measures.update(totals.keys())

    mismatches = 0
    for measure_key in sorted(
            all_measures,
            key=lambda k: (k[0],
                            k[1] if k[1] is not None else -1,
                            k[2] if k[2] is not None else -1)):
        voice_ticks = {voice: totals.get(measure_key, 0)
                       for voice, totals in per_voice_totals.items()}
        spread = max(voice_ticks.values()) - min(voice_ticks.values())
        if spread > DURATION_MISMATCH_TOLERANCE_TICKS:
            mismatches += 1
            page_index, sys_idx, measure_index = measure_key
            detail = ", ".join(f"{v}={t}" for v, t in voice_ticks.items())
            logger.warning(
                "duration mismatch strip_id=page%03d_sys%02d measure=%s: %s "
                "(ticks, spread=%d)",
                page_index, sys_idx if sys_idx is not None else -1,
                measure_index, detail, spread,
            )

    if mismatches:
        logger.warning(
            "%d measure(s) with SATB duration mismatch (tolerance=%d ticks) -- "
            "check Stage 3 transcription for dropped/extra tokens on the flagged voice(s).",
            mismatches, DURATION_MISMATCH_TOLERANCE_TICKS,
        )


# ── Per-voice pitch-range plausibility (diagnostic only) ───────────────────────

# Practical choral MIDI pitch bounds per voice -- generous enough to cover
# extended/divisi writing without false-flagging legitimate range; this is a
# plausibility check, not an enforced vocal-range limit. Values are sounding
# pitch: Tenor events are already octave-corrected by Stage 3's
# get_clef_reference()/TENOR_CLEF_REFERENCE before reaching Stage 4, so no
# further adjustment is needed here.
# PIYA-124: confirmed by ml-cv-lead 2026-09-11. Tenor's low bound was raised
# from G2 (43) to A2 (45) -- G2 was ungrounded in real tenor practice (true
# extended floor is A2/Bb2) and, worse, overlapped Bass's range, directly
# undercutting the Tenor/Bass clef-confusion pattern this diagnostic exists
# to catch. All other bounds confirmed as-is (generously wide, not wrong).
VOICE_MIDI_RANGE = {
    "Soprano": (57, 86),   # A3-D6
    "Alto":    (50, 79),   # D3-G5
    "Tenor":   (45, 72),   # A2-C5 (sounding)
    "Bass":    (36, 65),   # C2-F4
}


def _check_voice_pitch_range_plausibility(reconstructed: dict) -> None:
    """
    Read-only diagnostic: logs (does not correct) any note event whose pitch
    falls outside VOICE_MIDI_RANGE[voice].

    A pitch far outside a voice's practical range is typically a symptom of
    Stage 3 resolving the wrong clef (e.g. BUG-011's Bass clef.C-L3 collapse)
    or the wrong octave reference -- either shifts an entire strip's notes
    by several semitones to an octave or more, rather than producing a
    merely-unusual individual pitch, which is what this threshold is sized
    to catch.

    Copies _report()'s `e["type"] == "note" and e["pitch"] is not None`
    guard: rest events carry pitch=None (see stage3_transcription.infer_pitch
    rest handling), and _resolve_slurs() also sets pitch=None on absorbed
    slur middle/end notes before they're filtered out -- both would raise on
    the pitch comparison below without this guard.

    This function never raises and never mutates `reconstructed`, matching
    _check_measure_duration_consistency()'s diagnostic-only contract.

    Args:
        reconstructed: {voice: [event_dict, ...]}, already sorted and
          slur-resolved -- the same dict _check_measure_duration_consistency
          receives.
    """
    for voice, events in reconstructed.items():
        low, high = VOICE_MIDI_RANGE.get(voice, (0, 127))
        for e in events:
            if e["type"] != "note" or e["pitch"] is None:
                continue
            if e["pitch"] < low or e["pitch"] > high:
                page_index = e["page_index"]
                sys_idx    = e.get("sys_idx")
                logger.warning(
                    "pitch range anomaly strip_id=page%03d_sys%02d voice=%s "
                    "symbol=%s pitch=%d outside expected [%d, %d] -- "
                    "possible clef/octave misread (flag only, not corrected)",
                    page_index, sys_idx if sys_idx is not None else -1,
                    voice, e.get("symbol"), e["pitch"], low, high,
                )


# ── Reporting ─────────────────────────────────────────────────────────────────

def _report(reconstructed: dict):
    # print(), not logger.info() -- see the comment in reconstruct_satb() above:
    # this summary was always-visible console output before PIYA-124, and no
    # logging handler is configured anywhere in this codebase to keep it that way.
    print("\n[Stage 4] Reconstructed voice sequences:")
    for voice in VOICES:
        events = reconstructed[voice]
        notes  = sum(1 for e in events if e["type"] == "note" and e["pitch"] is not None)
        rests  = sum(1 for e in events if e["type"] == "rest")
        chords = len(set(e["chord_id"] for e in events
                         if e.get("chord_id") is not None))
        print(f"  {voice}: {len(events)} events "
              f"({notes} notes, {rests} rests, {chords} chord groups)")
    print()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    from stage1_preprocessing import preprocess_batch
    from stage2_detection import detect_staff_regions
    from stage3_transcription import transcribe_voice_sequences

    parser = argparse.ArgumentParser(
        description="PiyaNota Stage 4 — SATB Part Reconstruction")
    parser.add_argument("--input",   default="data/raw")
    parser.add_argument("--prep",    default="data/preprocessed")
    parser.add_argument("--strips",  default="data/strips")
    parser.add_argument("--weights", default="crnn_weights/best.pt")
    parser.add_argument("--yolo",    default="staff_detector_files/weights/best.pt")
    parser.add_argument("--img-height", type=int, default=64)
    args = parser.parse_args()

    pages  = preprocess_batch(args.input, args.prep, save_debug=False)
    voices = detect_staff_regions(pages,
                                  model_weights=args.yolo,
                                  output_dir=args.strips)
    events = transcribe_voice_sequences(voices,
                                        model_weights=args.weights,
                                        img_height=args.img_height)
    satb   = reconstruct_satb(events)

    print("\nStage 4 complete. SATB sequences ready for Stage 5 (MIDI synthesis).")
