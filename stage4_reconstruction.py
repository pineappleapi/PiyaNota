"""
PiyaNota - Stage 4: SATB Part Reconstruction
Combines pitch-assigned event sequences from Stage 3 into four continuous
voice sequences on ONE shared global tick timeline, ready for Stage 5 MIDI
synthesis.

Timeline model (why it is bar-anchored, not duration-anchored):
    Stage 3 emits ticks that are local to one strip (one system of one voice),
    accumulated from that voice's own recognised durations. A single misread
    rhythm in one voice therefore shifts everything after it in that voice,
    and (with the old max-end-tick offset) every voice's later systems too.
    Here each system's start tick is derived from *bar count x time signature*
    instead, and each bar's events are placed relative to that bar's start, so
    a rhythm error stays inside the bar it occurred in. Every bar that
    disagrees with the time signature, every voice whose bar count disagrees
    with the other voices, every pickup and every tie that could not be
    resolved is reported in the returned report / logged -- never absorbed.
"""

from collections import Counter, defaultdict
from typing import Any, Optional

Event = dict[str, Any]
Flag = dict[str, Any]

# ── Expected voices ───────────────────────────────────────────────────────────
VOICES = ["Soprano", "Alto", "Tenor", "Bass"]

# Must equal stage5_synthesis.PPQ and the tick scale of stage3_transcription's
# NOTE_DURATION_TICKS (whole = 4 quarters). The Stage 5 half is enforced by the
# import-time RuntimeError in stage5_synthesis.py.
TICKS_PER_QUARTER = 480
WHOLE_NOTE_TICKS = 4 * TICKS_PER_QUARTER

# Mirrors stage3_transcription.DEFAULT_TIME_SIGNATURE (not imported: Stage 3
# pulls in torch). Stage 3 stamps this on any strip with no explicit meter
# token -- i.e. every continuation system -- so it cannot be read as evidence
# of a real 4/4; see _bar_meters().
DEFAULT_TIME_SIGNATURE = "4/4"

# Where a bar's meter came from (PIYA-108 AC7; published as PIYA-117 AC9's
# meterSource). Stage 3 marks each event "detected" or "default"
# (PIYA-107 AC9); "inherited" and "unknown" are Stage 4's. "unknown" is part
# of the contract but never produced here: every bar gets either a vote, an
# inherited meter, or the 4/4 default.
METER_DETECTED = "detected"
METER_INHERITED = "inherited"
METER_DEFAULT = "default"
METER_UNKNOWN = "unknown"

# Tick tolerance for the per-bar duration check below.
# 10 ticks (~1/48 of a quarter note at PPQ=480) absorbs int() truncation
# from repeated dotted-note (*1.5) rounding without masking a genuine
# dropped/extra note or rest.
DURATION_MISMATCH_TOLERANCE_TICKS = 10

SLUR_START = "start"
SLUR_END = "end"

# ── Flag kinds (report["flags"][i]["kind"]) ───────────────────────────────────
FLAG_PICKUP = "pickup_detected"
FLAG_PICKUP_MISMATCH = "pickup_length_mismatch"
FLAG_BAR_COUNT = "bar_count_mismatch"
FLAG_NO_MEASURES = "no_measure_index"
FLAG_BAR_UNDERFULL = "bar_underfull"
FLAG_BAR_OVERFLOW = "bar_overflow_clipped"
FLAG_TIE_UNRESOLVED = "tie_unresolved"
FLAG_PICKUP_SUSPECT = "pickup_suspect"
FLAG_SUSPECTED_TUPLET = "suspected_tuplet"
FLAG_MIDBAR_BREAK = "suspected_midbar_break"
FLAG_RUN_SCALED = "bar_overflow_run_scaled"
FLAG_MISSING_BARLINE = "suspected_missing_barline"
FLAG_VOICE_RUN_SCALING = "voice_run_scaling_frequent"
# Flag "action" values written by _repair_overflow.
ACTION_CLIPPED = "clipped"
ACTION_COMPRESSED = "compressed_into_bar"
ACTION_SCALED_TUPLET = "scaled_tuplet"
ACTION_SCALED_RUN = "scaled_run"
FLAG_TENOR_RANGE = "tenor_range_suspect"
FLAG_BAR_INVARIANT = "bar_length_invariant_failed"
FLAG_LOCAL_OVERRUN = "local_placement_overrun"
FLAG_METER_DISAGREEMENT = "meter_disagreement"
# A meter change backed by too few voices (see MIN_METER_CHANGE_VOTES) is not
# applied: in open-score SATB every staff engraves the meter, so one voice
# reading a change the others do not is far likelier a misread.
FLAG_METER_CHANGE_MINORITY = "meter_change_minority"
# Informational (review_needed=False): a voice's lone whole rest in the opening
# bar was read as its rest through the agreed pickup, not as a full bar 1.
FLAG_WHOLE_REST_PICKUP = "whole_rest_as_pickup"
MIN_METER_CHANGE_VOTES = 2
# Repairs that threw notes away (PIYA-103 AC9 "muted reasons"). Such a flag
# carries muted=True plus start_tick/end_tick (PIYA-108 AC8) only when its
# repair actually dropped or cut notes: a clip that trimmed durations and
# dropped nothing is not muted (resolution 3 of
# docs/decisions/meter-click-and-muting-gaps.md).
ACTION_TRIMMED_PICKUP = "trimmed_head_to_pickup"
MUTED_FLAG_KINDS = frozenset({FLAG_BAR_OVERFLOW, FLAG_MISSING_BARLINE, FLAG_BAR_INVARIANT,
                              FLAG_LOCAL_OVERRUN, FLAG_PICKUP_MISMATCH})
# Flags that also carry review_needed=True ask the user to confirm/fix the
# bar; a flag without the key is informational (treat as review_needed=False).

# Job failure codes (PIYA-108 AC5, PIYA-109 AC9). Callers key on
# ``PipelineFailure.failure_reason``, never on message text.
FAILURE_INCOMPLETE_VOICE_SEQUENCE = "incomplete_voice_sequence"


class PipelineFailure(ValueError):
    """A job-level failure with a machine-readable ``failure_reason``.

    Subclasses ValueError so callers that already catch ValueError for an
    all-empty score keep working.
    """

    def __init__(self, failure_reason: str, message: str) -> None:
        super().__init__(f"{failure_reason}: {message}")
        self.failure_reason = failure_reason
        self.message = message

    def __reduce__(self) -> tuple[type, tuple[str, str]]:
        # BaseException pickles as cls(*self.args), and args holds only the
        # joined string, so without this a job queue / worker process that
        # pickles the exception gets a TypeError instead of the failure.
        return (type(self), (self.failure_reason, self.message))

# -- Calibration status of every threshold below ---------------------------
# ALL thresholds and weights in this module are hand-set priors, NOT fit to
# data, and none has held-out validation: the pickup evidence scores (2.0 floor,
# 0.75 margin, complement/rhythm/standard/excess bonuses, the 0.75 no-pickup
# prior, the constant vote weight), the run-repair scales (2/3, BAR_SCALE_MIN
# 0.75, MIN_SCALED_SLOT_TICKS, RUN_MIN_*), MAX_CONFIDENCE_DROP_TICKS and the
# voice-scaling fractions. They were chosen to make hand-built fixtures behave
# sensibly. Treat them as guesses to be tuned on a real held-out set of
# engraved SATB systems before anyone quotes an accuracy for this stage.

# Pickup validity: whole multiples of a sixteenth (dotted eighth = 3 units is
# legal; an eighth-only grid would wrongly reject it), and at least one unit.
PICKUP_UNIT_TICKS = WHOLE_NOTE_TICKS // 16
# Overflow that is not a whole number of sixteenths looks like a flattened
# tuplet (BUG-015), not a dropped/extra written note.
TUPLET_GRID_TICKS = PICKUP_UNIT_TICKS
# Longest single value the confidence-based overflow repair may remove.
MAX_CONFIDENCE_DROP_TICKS = TICKS_PER_QUARTER
# Run-based overflow repair (see _repair_overflow): a run is >= 3 consecutive
# same-duration onset slots of which >= 2 are notes; a squeezed slot may not
# fall below 60 ticks or the run is not a credible culprit; a whole-bar
# squeeze beyond 25% is not a plausible tuplet.
RUN_MIN_SLOTS = 3
RUN_MIN_NOTE_SLOTS = 2
MIN_SCALED_SLOT_TICKS = 60
BAR_SCALE_MIN = 0.75
# Voice-level warning when more than this fraction of a voice's bars needed
# run scaling, judged only once the voice has MIN_BARS_FOR_VOICE_FLAG bars.
VOICE_RUN_SCALING_FRACTION = 0.25
MIN_BARS_FOR_VOICE_FLAG = 4
# Pickup evidence scoring (see _score_pickup_candidate / _decide_pickups).
# Accept the best candidate only with this much total evidence and this lead
# over the runner-up; below that the pickup is refused and suggested instead.
PICKUP_MIN_SCORE = 2.0
PICKUP_MIN_MARGIN = 0.75
PICKUP_SUGGEST_MIN_SCORE = 1.0
PICKUP_TIE_EPSILON = 0.25
# Per-voice vote weight is CONSTANT: CRNN confidence is uncalibrated (and can
# be confidently wrong, BUG-011), so it must not steer a structural decision.
PICKUP_VOTE_WEIGHT = 0.75
PICKUP_REST_VOTE_FACTOR = 0.5        # rest-only first bar of the right length
PICKUP_SUFFIX_VOTE_FACTOR = 0.5      # shorter bar that is a dropped-note suffix
PICKUP_COMPLEMENT_PER_VOICE = 1.0
PICKUP_COMPLEMENT_CAP = 2.0
PICKUP_RHYTHM_PER_PAIR = 0.5
PICKUP_RHYTHM_CAP = 1.0
PICKUP_STANDARD_BONUS = 0.5
PICKUP_EIGHTH_BONUS = 0.25
PICKUP_NO_PICKUP_PRIOR = 0.75
# Structural pre-check (bar-count excess + tick congruence): a sounding voice
# with exactly one more measure than the full-first-bar reference voices,
# whose extra ticks equal its short first bar, is a pickup the others rest
# through (Stage 3 never emits the empty pickup segment of a rest voice).
PICKUP_EXCESS_BAR_BONUS = 1.0
PICKUP_EXCESS_BAR_CAP = 2.0
PICKUP_EXCESS_MIN_REFERENCE_VOICES = 2
# 'Full final bars' say nothing about a pickup when only the first system is
# available, so with the pre-check firing L=0's complement is capped lower.
PICKUP_EXCESS_ZERO_COMPLEMENT_CAP = 1.0
PICKUP_STANDARD_LENGTHS = {
    "4/4": {240, 480, 720, 960},
    "3/4": {480, 960, 720},
    "6/8": {240, 720},
}
# Tenor sounds an octave below written; written A4 (MIDI 69) -> 57.
TENOR_MAX_SOUNDING_MIDI = 57


# ── Main reconstruction function ──────────────────────────────────────────────

def reconstruct_satb(voice_events: dict) -> dict:
    """
    Combines pitch-assigned event sequences into four complete voice sequences.

    Thin wrapper over reconstruct_satb_with_report() that keeps the original
    return shape ({voice: [event_dict, ...]}) for existing callers. Flags are
    still logged to stdout; use reconstruct_satb_with_report() to get them
    as data.

    Raises:
        ValueError if all four voice sequences are missing or empty.
    """
    satb, _report_data = reconstruct_satb_with_report(voice_events)
    return satb


def reconstruct_satb_with_report(voice_events: dict) -> tuple[dict, dict]:
    """
    Builds the global-timeline SATB sequences plus a machine-readable report.

    Accepts the direct output of Stage 3 transcribe_voice_sequences():
        {voice: [event_dict, ...]}
    Each event needs type, pitch, duration_ticks, page_index, sys_idx,
    tick_onset; measure_index/time_signature/slur/tie_to_next/note_id are
    used when present. Input dicts are copied, never mutated.

    Output events keep every input field (so note_id, written_pitch, ... pass
    through) and gain:
        tick_onset        -- now GLOBAL (was per-strip local; same key so
                             Stage 5 is unchanged)
        local_tick_onset  -- the original per-strip tick
        global_bar        -- 1-based bar number across the piece, 0 for a
                             pickup bar, None if the voice-strip fell back to
                             local-tick placement (see flags)
        tie_to_next       -- True only if this (possibly already merged)
                             note is tied forward but no continuation was
                             found (also reported as a flag)
        tie_span          -- number of written notes merged into this event
                             (1 = not tied)
        tied_note_ids     -- note_ids absorbed into this event, if any

    Returns:
        (satb, report). satb is {voice: [event_dict, ...]} ordered by global
        tick, with [] for a failed voice. report has keys: flags (list of
        dicts, see FLAG_* kinds; a lossy repair's flag carries muted=True and
        its global start_tick/end_tick, PIYA-108 AC8), pickup_ticks,
        total_ticks (nominal end of the last bar), failed_voices (voices that
        were missing or empty, SATB order), systems (per-system layout; each
        has a ``bars`` list with every bar's ticks, time_signature,
        meter_source and actual_ticks, PIYA-108 AC6/AC7).

    Raises:
        PipelineFailure (a ValueError) with failure_reason
        ``incomplete_voice_sequence`` if all four voice sequences are missing
        or empty. One to three empty voices are reported in failed_voices and
        the rest are reconstructed (PIYA-108 AC4/AC5).
    """
    print("\n[Stage 4] Reconstructing SATB part sequences...")

    failed = [v for v in VOICES if not voice_events.get(v)]
    if len(failed) == len(VOICES):
        raise PipelineFailure(
            FAILURE_INCOMPLETE_VOICE_SEQUENCE,
            "[Stage 4] All four voice sequences are missing or empty. "
            "Check Stage 2/3 outputs or recapture the score.")
    if failed:
        print(f"[Stage 4] WARNING: no events for {failed}; continuing with the "
              "other voices (reported as failed voices)")

    flags: list[Flag] = []
    strips = _split_into_strips(voice_events)
    layout, pickup_ticks, voice_pickup = _plan_layout(strips, flags)

    reconstructed: dict = {voice: [] for voice in VOICES}
    for key in sorted(strips):
        for voice in VOICES:
            if voice in strips[key]:
                reconstructed[voice].extend(_place_voice_strip(
                    voice, key, strips[key][voice], layout[key],
                    pickup_ticks, voice_pickup.get(voice, 0), flags))

    for voice in VOICES:
        reconstructed[voice].sort(key=lambda e: e["tick_onset"])
        reconstructed[voice] = _resolve_ties(reconstructed[voice], voice, flags)

    _flag_voice_run_scaling(reconstructed, flags)
    _flag_tenor_range(reconstructed.get("Tenor", []), flags)
    _flag_midbar_breaks(strips, layout, flags)

    total_ticks = pickup_ticks + sum(
        bar["ticks"] for info in layout.values() for bar in info["bars"])
    report_data = {
        "flags": flags,
        "pickup_ticks": pickup_ticks,
        "total_ticks": total_ticks,
        "failed_voices": failed,
        "systems": [{"page_index": k[0], "sys_idx": k[1], **layout[k]}
                    for k in sorted(layout)],
    }
    _report(reconstructed, report_data)
    return reconstructed, report_data


# ── Strip grouping and timing helpers ──────────────────────────────────────────

def _bar_ticks(time_signature: str) -> int:
    """Ticks in one bar of `time_signature` ("3/4" -> 1440, "6/8" -> 1440)."""
    try:
        num_s, den_s = time_signature.split("/")
        num, den = int(num_s), int(den_s)
        if num <= 0 or den <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        print(f"[Stage 4] WARNING: unparseable time signature "
              f"{time_signature!r}; assuming {DEFAULT_TIME_SIGNATURE}")
        return _bar_ticks(DEFAULT_TIME_SIGNATURE)
    return num * WHOLE_NOTE_TICKS // den


def _split_into_strips(voice_events: dict) -> dict:
    """
    {(page_index, sys_idx): {voice: [event copies sorted by local tick]}}.

    sys_idx must be part of the key: tick_onset resets to 0 for every Stage 3
    infer_pitch() call (one per system's voice strip), so events of different
    systems would otherwise interleave.
    """
    strips: dict = defaultdict(dict)
    for voice in VOICES:
        by_strip: dict = defaultdict(list)
        for e in voice_events.get(voice) or []:
            copy = dict(e)
            copy["local_tick_onset"] = copy["tick_onset"]
            by_strip[(copy["page_index"], copy["sys_idx"])].append(copy)
        for key, events in by_strip.items():
            events.sort(key=lambda e: e["local_tick_onset"])  # stable
            strips[key][voice] = events
    return strips


def _measure_ticks(events: list) -> int:
    """
    Summed duration of one measure's events.

    Chord notes share a tick_onset, so each unique onset counts once (the
    longest note at it); otherwise stacked chord notes would be double
    counted.
    """
    per_onset: dict = {}
    for e in events:
        per_onset[e["local_tick_onset"]] = max(
            per_onset.get(e["local_tick_onset"], 0), e["duration_ticks"])
    return sum(per_onset.values())


def _is_multirest(events: list) -> bool:
    return any(str(e.get("symbol", "")).startswith("multirest") for e in events)


def _measures(events: list) -> Optional[dict]:
    """{measure_index: [events]} in measure order, or None if any event lacks
    measure_index (older/foreign Stage 3 output)."""
    if any("measure_index" not in e for e in events):
        return None
    grouped: dict = defaultdict(list)
    for e in events:
        grouped[e["measure_index"]].append(e)
    return dict(sorted(grouped.items()))


def _event_meter(e: Event) -> tuple[str, str]:
    """(time_signature, source) of one event.

    Events from before PIYA-107 AC9 carry no source; for them only a non-4/4
    value is certainly a reading (Stage 3 stamped 4/4 on every strip without a
    meter), so that is the rule they fall back to.
    """
    ts = e.get("time_signature") or DEFAULT_TIME_SIGNATURE
    src = e.get("time_signature_source")
    if src not in (METER_DETECTED, METER_DEFAULT):
        src = METER_DETECTED if ts != DEFAULT_TIME_SIGNATURE else METER_DEFAULT
    return ts, src


def _measure_meter(m_events: list[Event]) -> Optional[str]:
    """The meter Stage 3 read for one measure, or None if it only defaulted.

    Stage 3 stamps each event with its own measure's meter (PIYA-107 AC7), so
    every event of a measure normally agrees; the most common detected value
    wins if a stray one does not.
    """
    detected = [ts for ts, src in map(_event_meter, m_events) if src == METER_DETECTED]
    return Counter(detected).most_common(1)[0][0] if detected else None


def _opening_meter(strips: dict, first_key: tuple) -> Optional[str]:
    """Detected meter of the first measure of the first system, by vote across voices.

    Needed before the layout exists, because the pickup decision measures the
    first bar against it. A pickup is engraved after the header meter, so its
    measure carries bar 1's meter.
    """
    votes: list[str] = []
    for voice in VOICES:
        events = strips[first_key].get(voice)
        if not events:
            continue
        measures = _measures(events)
        first = next(iter(measures.values())) if measures else events
        meter = _measure_meter(first)
        if meter is not None:
            votes.append(meter)
    return Counter(votes).most_common(1)[0][0] if votes else None


def _measure_at(ranked: dict[int, list[Event]], rank: int) -> Optional[list[Event]]:
    """The measure covering bar ``rank`` of a voice-strip (a multirest covers several ranks)."""
    for start, m_events in ranked.items():
        if start <= rank < start + _measure_span(m_events):
            return m_events
    return None


def _plan_layout(strips: dict, flags: list) -> tuple[dict, int, dict]:
    """
    Decides bar structure for the whole piece before any event is moved.

    Returns:
        layout: {(page, sys): {time_signature, bar_ticks (both the system's
                 first bar, kept for older readers), n_bars, voice_bars,
                 voice_base, bars, first_bar, start_tick}} -- n_bars is the
                 cross-voice consensus (most common; ties -> larger). ``bars``
                 has one entry per bar: ticks (nominal, from its own meter),
                 time_signature, meter_source and actual_ticks (equal to ticks
                 except a short final bar, resolution 9).
        pickup_ticks: length of the anacrusis (0 if none) = the length the
                 agreeing voices share (deviant voices do not move it). Bar
                 1's downbeat is at this tick in every voice.
        voice_pickup: {voice: that voice's own pickup length} for voices
                 that have pickup content.

    Meter per bar (PIYA-108 AC6/AC7): the voices whose bar count matches the
    consensus vote with the meter Stage 3 read for the measure covering that
    bar; defaulted readings abstain. With no vote the bar inherits the
    previous bar's meter, so a continuation strip's stamped 4/4 never resets
    the meter while a detected 4/4 is a real change. Detected votes that
    disagree raise meter_disagreement.

    Pickups are decided by _decide_pickups() (gates plus voice consensus,
    pickup_suspect on doubt), from durations and not measure_index numbering: Stage 3 skips a
    barline token that precedes the first note, so the first *full* bar of a
    voice without pickup content is measure_index 0 in real Stage 3 output
    but 1 in hand-authored ground truth. Limit: a first bar that is short
    only because Stage 3 dropped a token can still pass the gates; it is
    reported as FLAG_PICKUP (review_needed unless the final bar completes it)
    so it is visible, not assumed correct.
    """
    first_key = min(strips)
    opening = _opening_meter(strips, first_key) or DEFAULT_TIME_SIGNATURE
    voice_pickup, pickup_ticks, suffix_ok = _decide_pickups(
        strips, {first_key: opening}, first_key, flags)

    layout: dict = {}
    previous: Optional[tuple[str, str]] = None      # (meter, source) of the last bar laid out
    for key in sorted(strips):
        n_by_voice: dict[str, int] = {}
        voice_base: dict[str, int] = {}
        ranked: dict[str, dict[int, list[Event]]] = {}
        for voice, events in strips[key].items():
            measures = _measures(events)
            if measures is None:
                continue
            indices = list(measures)
            base = indices[0]
            if key == first_key and voice in voice_pickup:
                base = indices[1]
            voice_base[voice] = base
            ranked[voice] = {mi - base: measures[mi] for mi in indices if mi >= base}
            n_by_voice[voice] = max(
                (rank + _measure_span(m) for rank, m in ranked[voice].items()), default=0)
        counts = Counter(n_by_voice.values())
        n_bars = max(counts, key=lambda n: (counts[n], n)) if counts else 0
        voters = [v for v in VOICES if n_by_voice.get(v) == n_bars] or [
            v for v in VOICES if v in ranked]

        bars: list[dict[str, Any]] = []
        notes: list[tuple[str, int, dict[str, str], str]] = []   # (kind, rank, votes, meter used)
        for rank in range(n_bars):
            votes: dict[str, str] = {}
            for voice in voters:
                m_events = _measure_at(ranked[voice], rank)
                meter = _measure_meter(m_events) if m_events else None
                if meter is not None:
                    votes[voice] = meter
            if previous is None:
                kept = (DEFAULT_TIME_SIGNATURE, METER_DEFAULT)
            else:
                # Within one system the source carries over (a change earlier in
                # this strip still counts as read here); across a system break a
                # read meter becomes inherited (AC7). A default stays default.
                kept = (previous[0], previous[1] if bars or previous[1] == METER_DEFAULT
                        else METER_INHERITED)
            if votes:
                tally = Counter(votes.values())
                meter, source = tally.most_common(1)[0][0], METER_DETECTED
                if len(tally) > 1:
                    notes.append((FLAG_METER_DISAGREEMENT, rank, votes, meter))
                # Only voices that read a meter at this bar count: a voice that read
                # nothing (or sits in a multirest) is no evidence against a change,
                # and must not let one stray read pass either. A system with a
                # single live voice in total is the one case one read is enough.
                needed = 1 if len(ranked) == 1 else max(
                    MIN_METER_CHANGE_VOTES, len(votes) // 2 + 1)
                if previous is not None and meter != previous[0] and tally[meter] < needed:
                    notes.append((FLAG_METER_CHANGE_MINORITY, rank, votes, kept[0]))
                    meter, source = kept
            else:
                meter, source = kept
            ticks = _bar_ticks(meter)
            bars.append({"ticks": ticks, "time_signature": meter,
                         "meter_source": source, "actual_ticks": ticks})
            previous = (meter, source)

        head = bars[0]["time_signature"] if bars else (
            previous[0] if previous else opening)
        layout[key] = {"time_signature": head, "bar_ticks": _bar_ticks(head),
                       "n_bars": n_bars, "voice_bars": n_by_voice,
                       "voice_base": voice_base, "bars": bars, "_meter_notes": notes}

    # PIYA-117 AC9: the pickup row carries the meter the opening measure was
    # engraved under, which _decide_pickups measured it against.
    layout[first_key]["opening_meter"] = {
        "time_signature": opening,
        "meter_source": METER_DETECTED if _opening_meter(strips, first_key) else METER_DEFAULT}

    # Voices whose shorter pickup is a dropped-leading-note suffix of the agreed
    # one: their length mismatch is informational (a list, so the report stays
    # JSON-serialisable).
    layout[first_key]["pickup_suffix_ok"] = sorted(suffix_ok)

    # Resolution 9: a short final bar (often the complement of the pickup)
    # keeps its actual length. Only bar-anchored voices count, and the longest
    # of them wins, so one voice that dropped a note cannot shorten the bar.
    last_key = max((k for k in layout if layout[k]["bars"]), default=None)
    if last_key is not None and last_key == max(strips):
        info = layout[last_key]
        own = {v: t for v, t in _final_bar_ticks(strips).items()
               if info["voice_bars"].get(v) == info["n_bars"]}
        last = info["bars"][-1]
        if own and 0 < max(own.values()) < last["ticks"]:
            last["actual_ticks"] = max(own.values())

    running = pickup_ticks
    bar_no = 1
    for key in sorted(layout):
        layout[key]["start_tick"] = running
        layout[key]["first_bar"] = bar_no
        running += sum(bar["ticks"] for bar in layout[key]["bars"])
        bar_no += layout[key]["n_bars"]
        _flag_meter_runs(key, layout[key], flags)
    return layout, pickup_ticks, voice_pickup


def _flag_meter_runs(key: tuple, info: dict[str, Any], flags: list) -> None:
    """One review flag per contiguous run of bars with the same meter conflict.

    A misread stamps every later measure of that strip, so one flag per bar
    would bury the review list; ``bar``..``bar_end`` give the run.
    """
    notes = info.pop("_meter_notes")
    run: Optional[list] = None
    runs: list[list] = []
    for kind, rank, votes, meter in notes:
        if run and run[0] == kind and run[2] == votes and run[3] == meter and run[4] == rank - 1:
            run[4] = rank
        else:
            run = [kind, rank, votes, meter, rank]
            runs.append(run)
    for kind, first, votes, meter, last in runs:
        if kind == FLAG_METER_DISAGREEMENT:
            detail, action = f"voices read different meters: {votes}; used {meter}", "majority_meter"
        else:
            detail = (f"meter change read by too few voices: {votes}; kept {meter} "
                      f"(every staff engraves the meter in open score)")
            action = "kept_previous_meter"
        flags.append({
            "kind": kind, "page_index": key[0], "sys_idx": key[1],
            "bar": info["first_bar"] + first, "bar_end": info["first_bar"] + last,
            "voice": None, "expected_ticks": _bar_ticks(meter), "actual_ticks": None,
            "detail": detail, "action": action, "review_needed": True,
            "system_bar_rank": first})


def _bar_starts(info: dict[str, Any]) -> list[int]:
    """Global start tick of every bar of a system, plus the system end as the last item."""
    starts = [info["start_tick"]]
    for bar in info["bars"]:
        starts.append(starts[-1] + bar["ticks"])
    return starts


def _is_valid_pickup_length(ticks: int, bar_ticks: int) -> bool:
    """Whole multiple of a sixteenth, >= one sixteenth, strictly below a bar."""
    if (ticks < PICKUP_UNIT_TICKS
            or ticks >= bar_ticks - DURATION_MISMATCH_TOLERANCE_TICKS):
        return False
    remainder = ticks % PICKUP_UNIT_TICKS
    return (min(remainder, PICKUP_UNIT_TICKS - remainder)
            <= DURATION_MISMATCH_TOLERANCE_TICKS)


def _final_bar_ticks(strips: dict) -> dict:
    """{voice: duration of that voice's last non-multirest measure} in the
    last strip of the piece."""
    result: dict = {}
    for voice, events in strips[max(strips)].items():
        measures = _measures(events)
        if not measures:
            continue
        last = list(measures.values())[-1]
        if not _is_multirest(last):
            result[voice] = _measure_ticks(last)
    return result


def _first_bar_observations(strips: dict, first_key: tuple,
                            bar_ticks: int) -> dict:
    """
    {voice: observation} for the first measure of the first strip.

    kind is "sounding" (has a pitched note), "rest" (short, rests only) or
    "full" (a full bar or a multirest: evidence that the voice has NO
    pickup). Voices with fewer than two measures give no observation. Other
    fields: whole_rest (the bar is a lone whole rest, which is "full" for
    scoring but, once a pickup is accepted, a rest through it), ticks (own
    length), conf (mean note confidence, None unless every
    note has one; informational only), weight (constant), offsets/durs (onset offsets and slot durations
    inside the bar).
    """
    obs: dict = {}
    for voice, events in strips[first_key].items():
        measures = _measures(events)
        if measures is None or len(measures) < 2:
            continue
        first = next(iter(measures.values()))
        own = _measure_ticks(first)
        if own <= 0:
            continue
        first_local = min(e["local_tick_onset"] for e in first)
        slots = _make_slots(first)
        notes = [e for e in first if e["type"] == "note"]
        conf = (sum(e["confidence"] for e in notes) / len(notes)
                if notes and all(_has_confidence(e) for e in notes) else None)
        if _is_multirest(first) or own >= bar_ticks - DURATION_MISMATCH_TOLERANCE_TICKS:
            kind = "full"
        elif any(e["type"] == "note" and e.get("pitch") is not None
                 for e in first):
            kind = "sounding"
        else:
            kind = "rest"
        obs[voice] = {
            "kind": kind, "ticks": own, "conf": conf,
            "whole_rest": _is_lone_whole_rest(first),
            "weight": PICKUP_VOTE_WEIGHT,
            "offsets": tuple(s["start"] - first_local for s in slots),
            "durs": tuple(s["dur"] for s in slots)}
    return obs


def _excess_bar_pickup(strips: dict[tuple, dict[str, list[Event]]],
                       first_key: tuple[int, int], obs: dict[str, dict],
                       bar_ticks: int) -> Optional[dict[str, Any]]:
    """
    Structural pickup evidence that does not depend on raw measure_index.
    Reference voices R are those whose first bar is full (a multirest does
    not count). Needs >= PICKUP_EXCESS_MIN_REFERENCE_VOICES of them, all with
    the same non-empty measure count n_R and summed ticks total_R. A voice is
    pickup-shaped if its first bar is sounding, of valid pickup length L, it
    has n_R + 1 measures, and total - L == total_R (so a split-bar
    hallucination, whose extra bar is NOT congruent, does not qualify).
    All pickup-shaped voices must agree on L; otherwise returns None and the
    plain evidence scoring decides. Returns {length, voices, reference}.
    """
    tol = DURATION_MISMATCH_TOLERANCE_TICKS
    shape: dict = {}
    for voice in obs:
        measures = _measures(strips[first_key][voice])
        if not measures:
            continue
        shape[voice] = (len(measures),
                        sum(_measure_ticks(m) for m in measures.values()))
    ref = [v for v, o in obs.items()
           if o["kind"] == "full" and v in shape
           and not _is_multirest(next(iter(
               _measures(strips[first_key][v]).values())))]
    if len(ref) < PICKUP_EXCESS_MIN_REFERENCE_VOICES:
        return None
    n_ref, total_ref = shape[ref[0]]
    if any(shape[v][0] != n_ref or abs(shape[v][1] - total_ref) > tol
           for v in ref):
        return None
    qualifying: dict = {}
    for voice, o in obs.items():
        if voice not in shape or o["kind"] != "sounding":
            continue
        n_v, total_v = shape[voice]
        if (_is_valid_pickup_length(o["ticks"], bar_ticks)
                and n_v == n_ref + 1
                and abs(total_v - o["ticks"] - total_ref) <= tol):
            qualifying[voice] = o["ticks"]
    if not qualifying:
        return None
    lengths = list(qualifying.values())
    if max(lengths) - min(lengths) > tol:
        return None
    return {"length": max(lengths), "voices": sorted(qualifying),
            "reference": sorted(ref)}


def _score_pickup_candidate(length: int, obs: dict[str, dict],
                            final: dict[str, int], bar_ticks: int, meter: str,
                            excess: Optional[dict[str, Any]] = None
                            ) -> dict[str, Any]:
    """Evidence score for "the pickup is `length` ticks" (0 = no pickup)."""
    tol = DURATION_MISMATCH_TOLERANCE_TICKS
    score, unweighted = 0.0, 0.0
    voters: list = []
    suffix_ok: set = set()
    ref_offsets: set = set()
    for voice, o in obs.items():
        matches = abs(o["ticks"] - length) <= tol
        if o["kind"] == "full":
            if length == 0 and not excess:
                score += o["weight"]
                unweighted += 1
                voters.append(voice)
            elif (excess and length > 0 and voice in excess["reference"]
                  and abs(length - excess["length"]) <= tol):
                # Silent through the pickup: same weight as a sounding vote,
                # and its full-bar vote for 0 is void (fits both hypotheses).
                score += o["weight"]
                unweighted += 1
                voters.append(voice)
        elif length > 0 and o["kind"] == "sounding" and matches:
            score += o["weight"]
            unweighted += 1
            voters.append(voice)
            ref_offsets.update(o["offsets"])
        elif length > 0 and o["kind"] == "rest" and matches:
            score += PICKUP_REST_VOTE_FACTOR * o["weight"]
            unweighted += PICKUP_REST_VOTE_FACTOR
            voters.append(voice)
    if length > 0:
        for voice, o in obs.items():
            if o["kind"] != "sounding" or o["ticks"] >= length - tol:
                continue
            shift = length - o["ticks"]
            if all(any(abs(off + shift - r) <= tol for r in ref_offsets)
                   for off in o["offsets"]):
                suffix_ok.add(voice)
                score += PICKUP_SUFFIX_VOTE_FACTOR * o["weight"]

    if length == 0:
        complement = [v for v, f in final.items()
                      if abs(f - bar_ticks) <= tol]
    else:
        complement = [v for v, f in final.items()
                      if abs(f + length - bar_ticks) <= tol]
    cap = PICKUP_COMPLEMENT_CAP
    if excess and length == 0:
        cap = min(cap, PICKUP_EXCESS_ZERO_COMPLEMENT_CAP)
    score += min(cap, PICKUP_COMPLEMENT_PER_VOICE * len(complement))
    if excess and length > 0 and abs(length - excess["length"]) <= tol:
        score += min(PICKUP_EXCESS_BAR_CAP,
                     PICKUP_EXCESS_BAR_BONUS * len(excess["voices"]))

    standard = False
    if length == 0:
        score += PICKUP_NO_PICKUP_PRIOR
    else:
        groups = Counter(o["durs"] for v, o in obs.items() if v in voters
                         and o["kind"] == "sounding")
        pairs = sum(c * (c - 1) // 2 for c in groups.values())
        score += min(PICKUP_RHYTHM_CAP, PICKUP_RHYTHM_PER_PAIR * pairs)
        standard = length in PICKUP_STANDARD_LENGTHS.get(
            meter, _default_standard_pickups(bar_ticks))
        if standard:
            score += PICKUP_STANDARD_BONUS
        elif length % (TICKS_PER_QUARTER // 2) == 0:
            score += PICKUP_EIGHTH_BONUS
    return {"ticks": length, "score": score, "voters": voters,
            "unweighted": unweighted, "complement_voices": complement,
            "standard": standard, "suffix_ok": suffix_ok}


def _default_standard_pickups(bar_ticks: int) -> set:
    """Standard-length set for a meter not listed in PICKUP_STANDARD_LENGTHS."""
    return {bar_ticks // 2, TICKS_PER_QUARTER, TICKS_PER_QUARTER // 2,
            3 * TICKS_PER_QUARTER // 4, 3 * TICKS_PER_QUARTER // 2}


def _rank_pickup_candidates(cands: list) -> list:
    """Best first: score, then longest. If the top two are within
    PICKUP_TIE_EPSILON the tie-break keys decide their order: more voices with
    a per-voice complement, more unweighted first-bar votes, standard beats
    non-standard, then the LONGER length
    (too short clips a real pickup; too long only adds leading silence). The
    order never changes acceptance -- that needs the raw margin -- it decides
    which candidate is reported/suggested first."""
    ranked = sorted(cands, key=lambda c: (-c["score"], -c["ticks"]))
    if (len(ranked) >= 2 and ranked[0]["score"] - ranked[1]["score"]
            < PICKUP_TIE_EPSILON):
        def key(c: dict) -> tuple:
            return (len(c["complement_voices"]), c["unweighted"],
                    c["standard"], c["ticks"])
        if key(ranked[1]) > key(ranked[0]):
            ranked[0], ranked[1] = ranked[1], ranked[0]
    return ranked


def _candidate_summary(c: dict) -> dict:
    return {"ticks": c["ticks"], "score": round(c["score"], 2),
            "voters": list(c["voters"]),
            "complement_voices": list(c["complement_voices"]),
            "standard": c["standard"]}


def _candidate_text(c: dict) -> str:
    what = "no pickup" if c["ticks"] == 0 else f"pickup {c['ticks']}"
    parts = []
    if c["voters"]:
        parts.append(f"first bars of {','.join(c['voters'])}")
    if c["complement_voices"]:
        parts.append(f"final bars of {','.join(c['complement_voices'])} "
                     "complete it" if c["ticks"] else
                     f"full final bars of {','.join(c['complement_voices'])}")
    return f"{what} ({'; '.join(parts) or 'no evidence'}; score {c['score']:.2f})"


def _decide_pickups(strips: dict, meters: dict, first_key: tuple,
                    flags: list) -> tuple[dict, int, set]:
    """
    Returns ({voice: own pickup ticks}, agreed pickup ticks, {voices whose
    shorter first bar is a dropped-leading-note suffix of the agreed pickup}).
    The dict holds every voice that is right-aligned to the downbeat;
    ({}, 0, set()) means no pickup (nothing right-aligned, no silence
    inserted).

    Gates kept: (1) some voice has a first bar with a sounding note that is
    not a multirest, and it is short; (3) the first measure of the first strip
    of the first page only. Instead of demanding agreement, the pickup length
    is CHOSEN by evidence scoring (see _score_pickup_candidate): candidates
    are "no pickup" (0), every valid sounding first-bar length, and the
    complement of every valid short final bar. Full/multirest first bars are
    votes for 0, so a lone short first bar among full bars is out-voted.
    Accepted only if the best score >= PICKUP_MIN_SCORE and it leads the
    runner-up by >= PICKUP_MIN_MARGIN; otherwise refused (pickup_suspect,
    bar-1 placement) with the ranked candidates and a suggested length in the
    flag so the user can confirm. Voices that disagree with an accepted length
    are still right-aligned to the downbeat on the one shared timeline
    (shorter: leading silence; longer: the last L ticks are kept; full bar:
    not shifted) and flagged pickup_length_mismatch.
    """
    bar_ticks = _bar_ticks(meters[first_key])
    tol = DURATION_MISMATCH_TOLERANCE_TICKS
    obs = _first_bar_observations(strips, first_key, bar_ticks)
    sounding = {v: o["ticks"] for v, o in obs.items()
                if o["kind"] == "sounding" and o["ticks"] < bar_ticks - tol}
    if not sounding:
        return {}, 0, set()

    final = _final_bar_ticks(strips)
    lengths = {0}
    lengths.update(t for t in sounding.values()
                   if _is_valid_pickup_length(t, bar_ticks))
    lengths.update(bar_ticks - f for f in final.values()
                   if _is_valid_pickup_length(f, bar_ticks))
    merged: list = []
    for t in sorted(lengths):
        if merged and t - merged[-1] <= tol:
            merged[-1] = t                  # near-duplicates: keep the longer
        else:
            merged.append(t)
    meter = meters[first_key]
    excess = _excess_bar_pickup(strips, first_key, obs, bar_ticks)
    if excess and not any(abs(t - excess["length"]) <= tol for t in merged):
        merged = sorted(merged + [excess["length"]])
    ranked = _rank_pickup_candidates(
        [_score_pickup_candidate(t, obs, final, bar_ticks, meter, excess)
         for t in merged])
    best = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    top = sorted((c["score"] for c in ranked), reverse=True)
    margin = top[0] - top[1] if len(top) > 1 else top[0]
    summaries = [_candidate_summary(c) for c in ranked[:3]]

    def flag(kind: str, voice: Optional[str], detail: str, action: str,
             review: bool, actual: Optional[int] = None,
             **extra: Any) -> None:
        flags.append({"kind": kind, "page_index": first_key[0],
                      "sys_idx": first_key[1], "bar": 0, "voice": voice,
                      "expected_ticks": None, "actual_ticks": actual,
                      "detail": detail, "action": action,
                      "review_needed": review, **extra})

    short_voices = {v: o["ticks"] for v, o in obs.items()
                    if o["kind"] in ("sounding", "rest")}
    accepted = (best["score"] >= PICKUP_MIN_SCORE
                and margin >= PICKUP_MIN_MARGIN)
    if not accepted or best["ticks"] == 0:
        vs = f" vs {_candidate_text(runner)}" if runner else ""
        if accepted:
            why = f"voted down: {_candidate_text(best)}{vs}"
        elif best["score"] < PICKUP_MIN_SCORE:
            why = (f"best score {best['score']:.2f} < {PICKUP_MIN_SCORE}: "
                   f"{_candidate_text(best)}")
        else:
            why = (f"{_candidate_text(best)}{vs}; margin {margin:.2f} < "
                   f"{PICKUP_MIN_MARGIN}")
        suggested = best["ticks"] if best["score"] >= PICKUP_SUGGEST_MIN_SCORE else None
        for voice, own in short_voices.items():
            flag(FLAG_PICKUP_SUSPECT, voice,
                 f"short first bar ({own} ticks) not accepted as a pickup: "
                 f"{why}. Placed as bar 1 -- confirm.",
                 "placed_as_bar_1", True, best["ticks"],
                 candidates=summaries, suggested_pickup_ticks=suggested)
        return {}, 0, set()

    agreed = best["ticks"]
    voice_pickup: dict = {}
    deviants: list = []
    for voice, o in obs.items():
        if o["kind"] == "full" and excess and voice in excess["reference"]:
            continue        # rests through the pickup; bar 1 starts at the downbeat
        if o["kind"] == "full" and o["whole_rest"]:
            # A voice silent through the anacrusis is often engraved with a
            # whole rest in the pickup bar; it is that voice's pickup, not a
            # full bar 1 (placement normalises the rest to the pickup length).
            voice_pickup[voice] = agreed
            flag(FLAG_WHOLE_REST_PICKUP, voice,
                 f"lone whole rest in the first bar taken as this voice's "
                 f"{agreed}-tick pickup rest", "whole_rest_as_pickup", False,
                 o["ticks"])
            continue
        if o["kind"] == "full":
            deviants.append(voice)
            flag(FLAG_PICKUP_MISMATCH, voice,
                 f"full first bar ({o['ticks']} ticks) while the pickup is "
                 f"{agreed}; not shifted or clipped (likely a wrong barline "
                 "count in this voice) -- confirm.",
                 "not_shifted", True, o["ticks"])
        elif abs(o["ticks"] - agreed) <= tol:
            voice_pickup[voice] = o["ticks"]
        elif o["kind"] == "sounding":
            voice_pickup[voice] = o["ticks"]
            deviants.append(voice)      # mismatch flag is raised at placement
        else:
            deviants.append(voice)
            flag(FLAG_PICKUP_SUSPECT, voice,
                 f"rest-only first bar of {o['ticks']} ticks differs from the "
                 f"pickup ({agreed}); placed as bar 1 -- confirm.",
                 "placed_as_bar_1", True, agreed)
    hard_deviants = [v for v in deviants if v not in best["suffix_ok"]]
    clean = (len(best["complement_voices"]) >= 2 and best["standard"]
             and not hard_deviants)
    flag(FLAG_PICKUP, None,
         f"pickup {agreed} ticks accepted (score {best['score']:.2f}, margin "
         f"{margin:.2f}); voters {best['voters']}, complement voices "
         f"{best['complement_voices']}, standard {best['standard']}, "
         f"deviants {deviants}; candidates {summaries}"
         + (f"; pickup inferred from bar-count excess + tick congruence "
            f"(pickup-shaped voices {excess['voices']} have one more measure "
            f"than reference voices {excess['reference']} and the extra ticks "
            "equal the short first bar)" if excess else ""),
         "downbeat_anchored", not clean, agreed,
         score=round(best["score"], 2), margin=round(margin, 2),
         candidates=summaries, **({"basis": "bar_count_excess"} if excess else {}))
    return voice_pickup, agreed, set(best["suffix_ok"])


def _flag_midbar_breaks(strips: dict, layout: dict, flags: list) -> None:
    """
    Flag-only (v1): a system that ends on a short bar, equal in all four
    voices, whose complement opens the next system is one bar split across a
    system break, not two short bars. Placement is not changed.
    """
    keys = sorted(strips)
    for cur, nxt in zip(keys, keys[1:]):
        # The break splits the system's LAST bar, which may have its own meter.
        bars = layout[cur]["bars"]
        bar_ticks = bars[-1]["ticks"] if bars else layout[cur]["bar_ticks"]
        tails: dict = {}
        heads: dict = {}
        for voice in VOICES:
            if voice not in strips[cur] or voice not in strips[nxt]:
                break
            m_cur = _measures(strips[cur][voice])
            m_nxt = _measures(strips[nxt][voice])
            if not m_cur or not m_nxt:
                break
            tails[voice] = _measure_ticks(list(m_cur.values())[-1])
            heads[voice] = _measure_ticks(next(iter(m_nxt.values())))
        else:
            tail = tails["Soprano"]
            short = (len(set(tails.values())) == 1
                     and 0 < tail < bar_ticks - DURATION_MISMATCH_TOLERANCE_TICKS)
            complements = all(
                abs(tails[v] + heads[v] - bar_ticks)
                <= DURATION_MISMATCH_TOLERANCE_TICKS for v in VOICES)
            if short and complements:
                flags.append({
                    "kind": FLAG_MIDBAR_BREAK, "page_index": nxt[0],
                    "sys_idx": nxt[1], "bar": layout[nxt]["first_bar"],
                    "voice": None, "expected_ticks": bar_ticks,
                    "actual_ticks": tail + heads["Soprano"],
                    "detail": "last bar of the previous system and first bar "
                              "of this one add up to one bar in all voices; "
                              "likely one bar split across the system break. "
                              "Not merged (flag only).",
                    "action": "none", "review_needed": True})


def _flag_tenor_range(events: list, flags: list) -> None:
    """Tenor sounding above written A4 usually means a clef misread
    (BUG-011); pitch inference is clef-relative, so the error is uniform and
    silent."""
    high = [e for e in events if e["type"] == "note"
            and e["pitch"] is not None and e["pitch"] > TENOR_MAX_SOUNDING_MIDI]
    if high:
        flags.append({
            "kind": FLAG_TENOR_RANGE, "page_index": high[0]["page_index"],
            "sys_idx": high[0]["sys_idx"], "bar": high[0].get("global_bar"),
            "voice": "Tenor", "expected_ticks": None, "actual_ticks": None,
            "detail": f"{len(high)} Tenor note(s) sound above MIDI "
                      f"{TENOR_MAX_SOUNDING_MIDI} (written A4); possible clef "
                      "error", "action": "none", "review_needed": True})


def _measure_span(events: list) -> int:
    """Bars a measure occupies: 1, or N for a multirest measure (Stage 3
    bumps measure_index by N-1 after it, so the span is real bars).

    N is the count Stage 3 read (``multirest_bars``), not ticks divided by a
    bar length: dividing a 3/4 multirest's ticks by a whole note was BUG-052.
    Only events without the field fall back to dividing, by the measure's own
    meter.
    """
    if not _is_multirest(events):
        return 1
    counts = [e["multirest_bars"] for e in events
              if isinstance(e.get("multirest_bars"), int) and e["multirest_bars"] > 0]
    if counts:
        return max(counts)
    meter = _measure_meter(events) or DEFAULT_TIME_SIGNATURE
    return max(1, round(_measure_ticks(events) / _bar_ticks(meter)))


# ── Placement onto the global timeline ─────────────────────────────────────────

def _place_voice_strip(
    voice: str,
    key: tuple,
    events: list[Event],
    info: dict[str, Any],
    pickup_ticks: int,
    own_pickup_ticks: int,
    flags: list[Flag],
) -> list[Event]:
    """
    Moves one voice-strip's events onto the global timeline.

    Bar mode (normal): the voice's bar count equals the cross-voice
    consensus, so measure `rank` (measure_index - base) is anchored at the
    start of the system's bar `rank` (bars may differ in length, PIYA-108
    AC6), and each event keeps only its offset inside its own measure.
    Duration errors are contained per bar; bars whose total disagrees with
    their meter are flagged (and overflow is clipped so it cannot collide
    with the next bar).

    Local mode (fallback): the voice's bar count disagrees with consensus (a
    dropped/hallucinated barline or multirest miscount) or it has no
    measure_index. Per-bar ranks cannot be trusted then, but its own running
    ticks still are; events are placed at system_start + local tick and the
    disagreement is flagged.

    A repair that threw notes away marks its flag muted=True with the global
    span Stage 5 silences (PIYA-108 AC8, PIYA-109 AC8).
    """
    page_index, sys_idx = key
    measures = _measures(events)
    start_tick = info["start_tick"]
    starts = _bar_starts(info)
    system_end = starts[-1]

    def flag(kind: str, bar: Optional[int], expected: Optional[int],
             actual: Optional[int], detail: str, action: str,
             review_needed: bool = False,
             span: Optional[tuple[int, int]] = None) -> None:
        entry = {"kind": kind, "page_index": page_index,
                 "sys_idx": sys_idx, "bar": bar, "voice": voice,
                 "expected_ticks": expected, "actual_ticks": actual,
                 "detail": detail, "action": action}
        if review_needed:
            entry["review_needed"] = True
        if span is not None and span[1] > span[0]:
            entry.update(muted=True, start_tick=span[0], end_tick=span[1])
        flags.append(entry)

    if measures is None or info["voice_bars"].get(voice) != info["n_bars"]:
        if measures is None:
            flag(FLAG_NO_MEASURES, None, None, None,
                 "events lack measure_index", "placed_by_local_ticks")
        else:
            flag(FLAG_BAR_COUNT, None, info["n_bars"],
                 info["voice_bars"].get(voice),
                 f"voice has {info['voice_bars'].get(voice)} bar(s), "
                 f"consensus is {info['n_bars']}; bar anchoring not trusted",
                 "placed_by_local_ticks")
        # Never before tick 0, even for a pickup voice longer than the agreed one.
        origin = max(0, start_tick - own_pickup_ticks)
        kept_events: list[Event] = []
        dropped_desc: list[str] = []
        trimmed_onsets: list[int] = []
        for e in events:
            e["tick_onset"] = origin + e["local_tick_onset"]
            e["global_bar"] = None
            if e["tick_onset"] >= system_end:
                if e["type"] == "note":
                    dropped_desc.append(_describe(e))
                continue
            if e["tick_onset"] + e["duration_ticks"] > system_end:
                e["duration_ticks"] = system_end - e["tick_onset"]
                if e["type"] == "note":
                    trimmed_onsets.append(e["tick_onset"])
            kept_events.append(e)
        if dropped_desc or trimmed_onsets:
            # Resolution 2: silence from the earliest cut NOTE to the system
            # end. Notes dropped past the end never sounded, so they need no
            # span, and a shortened rest lost nothing (resolution 3).
            span = (min(trimmed_onsets), system_end) if trimmed_onsets else None
            flag(FLAG_LOCAL_OVERRUN, None, system_end - start_tick, None,
                 f"locally placed voice ran past the system end (tick "
                 f"{system_end}); trimmed {len(trimmed_onsets)} note(s), dropped "
                 f"{len(dropped_desc)} note(s): {dropped_desc}",
                 ACTION_CLIPPED, review_needed=True, span=span)
        return kept_events

    base = info["voice_base"][voice]
    first_bar_ticks = info["bars"][0]["ticks"] if info["bars"] else info["bar_ticks"]
    placed: list = []
    for mi, m_events in measures.items():
        if mi < base:
            # A pickup that is only a whole rest is a rest for the pickup, not a
            # full bar: normalising it to a bar would read as a too-long pickup
            # and trim (mute) it.
            _normalise_whole_rest(m_events, pickup_ticks or first_bar_ticks)
            first_local = min(e["local_tick_onset"] for e in m_events)
            total = _measure_ticks(m_events)
            if abs(total - pickup_ticks) > DURATION_MISMATCH_TOLERANCE_TICKS:
                own_total = total
                review = True
                span: Optional[tuple[int, int]] = None
                if total > pickup_ticks:
                    # Right-aligning a longer bar would sound before tick 0:
                    # keep the LAST pickup_ticks (the notes leading into the
                    # downbeat), trimming from the head.
                    m_events, dropped, head_cut = _keep_last_ticks(
                        m_events, first_local, pickup_ticks)
                    first_local = min(e["local_tick_onset"] for e in m_events)
                    total = _measure_ticks(m_events)
                    action = ACTION_TRIMMED_PICKUP
                    # Mute only when a note was actually lost: trimming away
                    # leading rests loses nothing a singer would hear.
                    if dropped or head_cut:
                        span = (0, pickup_ticks)
                    how = (f"longer than the agreed pickup; kept the last "
                           f"{pickup_ticks} ticks, dropped {len(dropped)} "
                           f"note(s) from the head: {dropped}")
                else:
                    action = "right_aligned"
                    review = voice not in info.get("pickup_suffix_ok", ())
                    how = ("shorter than the agreed pickup; right-aligned "
                           "with leading silence"
                           + (" (looks like a dropped leading note)"
                              if not review else ""))
                flag(FLAG_PICKUP_MISMATCH, 0, pickup_ticks, own_total,
                     f"this voice's first bar is {how}", action,
                     review_needed=review, span=span)
            origin = pickup_ticks - total
            bar_no: Optional[int] = 0
        else:
            rank = mi - base
            span_bars = _measure_span(m_events)
            origin = starts[rank]
            bar_ticks = starts[min(rank + span_bars, len(info["bars"]))] - origin
            bar_no = info["first_bar"] + rank
            if _is_multirest(m_events):
                # The rest lasts exactly the bars it covers, each at its own meter.
                for e in m_events:
                    if str(e.get("symbol", "")).startswith("multirest"):
                        e["duration_ticks"] = bar_ticks
            else:
                _normalise_whole_rest(m_events, bar_ticks)
            first_local = min(e["local_tick_onset"] for e in m_events)
            total = _measure_ticks(m_events)
            if not _is_multirest(m_events):
                if total < bar_ticks - DURATION_MISMATCH_TOLERANCE_TICKS:
                    flag(FLAG_BAR_UNDERFULL, bar_no, bar_ticks, total,
                         "bar shorter than the time signature (dropped "
                         "note/rest?); remainder plays as silence", "none")
                elif total > bar_ticks + DURATION_MISMATCH_TOLERANCE_TICKS:
                    m_events, kind, detail, action, n_dropped = _repair_overflow(
                        m_events, first_local, bar_ticks, total)
                    lossy = kind in MUTED_FLAG_KINDS and n_dropped > 0
                    flag(kind, bar_no, bar_ticks, total, detail, action,
                         review_needed=True,
                         span=(origin, origin + bar_ticks) if lossy else None)
        for e in m_events:
            e["tick_onset"] = origin + (e["local_tick_onset"] - first_local)
            e["global_bar"] = bar_no
            placed.append(e)
    return placed


def _is_lone_whole_rest(m_events: list) -> bool:
    return (len(m_events) == 1 and m_events[0]["type"] == "rest"
            and str(m_events[0].get("symbol", "")).startswith("rest.whole"))


def _normalise_whole_rest(m_events: list, bar_ticks: int) -> None:
    """A measure holding only a whole rest is a full-bar rest whatever the
    meter (a 3/4 bar rest is engraved as a whole rest), but Stage 3 always
    gives rest.whole 1920 ticks. In a pickup bar ``bar_ticks`` is the pickup
    length."""
    if _is_lone_whole_rest(m_events):
        m_events[0]["duration_ticks"] = bar_ticks


def _describe(e: Event) -> str:
    return f"{e.get('note_id') or e.get('symbol')}(midi {e.get('pitch')})"


def _has_confidence(e: Event) -> bool:
    """True if the event carries a usable numeric confidence. A missing key, a
    None from a foreign producer, NaN, or a non-number all count as "no
    signal" rather than raising."""
    c = e.get("confidence")
    return (isinstance(c, (int, float)) and not isinstance(c, bool)
            and c == c)


def _make_slots(m_events: list) -> list:
    """Onset slots of one measure in time order. A chord is ONE slot (its
    notes share an onset); the slot's duration is its longest member, as in
    _measure_ticks()."""
    by_onset: dict = {}
    for e in m_events:
        by_onset.setdefault(e["local_tick_onset"], []).append(e)
    return [{"events": evs, "start": onset,
             "dur": max(e["duration_ticks"] for e in evs),
             "is_note": any(e["type"] == "note" for e in evs)}
            for onset, evs in sorted(by_onset.items())]


def _qualifying_runs(slots: list) -> list:
    """(start_idx, end_idx_exclusive) of every maximal run of consecutive
    slots with the same duration, with >= RUN_MIN_SLOTS slots of which
    >= RUN_MIN_NOTE_SLOTS are notes (rests may join a run).

    The duration class is duration_ticks, not the symbol string: Stage 3 does
    not put dots in `symbol` (a dot is a separate token that rewrites
    duration_ticks), and beamed/unbeamed variants of a value share ticks, so
    ticks are the one field that already separates dotted from undotted."""
    runs, i = [], 0
    while i < len(slots):
        j = i
        while j < len(slots) and slots[j]["dur"] == slots[i]["dur"]:
            j += 1
        if (j - i >= RUN_MIN_SLOTS
                and sum(s["is_note"] for s in slots[i:j]) >= RUN_MIN_NOTE_SLOTS):
            runs.append((i, j))
        i = j
    return runs


def _rescale_slots(slots: list, i0: int, i1: int, target_total: int) -> None:
    """Squeezes slots[i0:i1] into target_total ticks in place. Durations are
    decided first (even split, remainder ticks to the earliest slots) and
    onsets are the cumulative sum of those durations, so onset and duration
    can never round apart. Events after the run shift left by the ticks
    removed; events before it do not move."""
    n = i1 - i0
    shift = sum(s["dur"] for s in slots[i0:i1]) - target_total
    q, r = divmod(target_total, n)
    onset = slots[i0]["start"]
    for k, slot in enumerate(slots[i0:i1]):
        dur = q + 1 if k < r else q
        for e in slot["events"]:
            e["local_tick_onset"] = onset
            e["duration_ticks"] = dur
        onset += dur
    for slot in slots[i1:]:
        for e in slot["events"]:
            e["local_tick_onset"] -= shift


def _repair_by_run(m_events: list[Event], slots: list[dict],
                   runs: list[tuple[int, int]], first_local: int,
                   bar_ticks: int, overshoot: int
                   ) -> Optional[tuple[list[Event], str, str, str, int]]:
    """Steps 1-4 of _repair_overflow. Returns (events, kind, detail, action,
    notes dropped) or None when no run is a plausible culprit (caller goes to
    step 5)."""
    def run_ticks_of(run: tuple) -> int:
        return sum(s["dur"] for s in slots[run[0]:run[1]])

    # 1. Candidate: largest run that can absorb the overshoot by squeezing
    #    it by at most a third (s >= 2/3, in integers).
    fits = [r for r in runs
            if 3 * (run_ticks_of(r) - overshoot) >= 2 * run_ticks_of(r)]
    if not fits:
        return None
    i0, i1 = max(fits, key=run_ticks_of)
    n, d = i1 - i0, slots[i0]["dur"]
    run_ticks = n * d
    ratio = (run_ticks - overshoot) / run_ticks
    facts = (f"run of {n} x {d}-tick slots, {overshoot} ticks over, "
             f"scale {ratio:.2f}")

    def finish(kind: str, detail: str, action: str) -> tuple:
        # Not an assert: it would vanish under python -O and abort otherwise.
        landed = _measure_ticks(m_events)
        if landed == bar_ticks:
            return m_events, kind, detail, action, 0
        kept, dropped = _clip_to_bar(m_events, first_local, bar_ticks)
        return (kept, FLAG_BAR_INVARIANT,
                f"run repair ({kind}) left the bar at {landed} ticks, not "
                f"{bar_ticks}; clipped to the bar end, dropped {len(dropped)} "
                f"note(s): {dropped}. Internal invariant failure: verify",
                ACTION_CLIPPED, len(dropped))

    # 2. Exact tuplet: the whole run is 3-in-the-time-of-2.
    if (n % 3 == 0 and abs(overshoot - run_ticks / 3)
            <= DURATION_MISMATCH_TOLERANCE_TICKS):
        _rescale_slots(slots, i0, i1, run_ticks - overshoot)
        return finish(FLAG_SUSPECTED_TUPLET,
                      f"{facts}; reads as a triplet run, every slot scaled "
                      "to 2/3 of its written value", ACTION_SCALED_TUPLET)

    # 3. Partial triplet: exactly one beat-aligned 3-group could absorb a
    #    one-value overshoot. (Only the single-group case is handled; two or
    #    more groups to compress is ambiguous and goes to step 4.)
    if (abs(overshoot - d) <= DURATION_MISMATCH_TOLERANCE_TICKS
            and n >= 3):
        groups = [g for g in range(i0, i1 - 2)
                  if (slots[g]["start"] - first_local) % TICKS_PER_QUARTER == 0]
        if len(groups) == 1:
            g = groups[0]
            _rescale_slots(slots, g, g + 3, 3 * d - overshoot)
            return finish(FLAG_SUSPECTED_TUPLET,
                          f"{facts}; the one beat-aligned 3-group (slots "
                          f"{g - i0}-{g - i0 + 2} of the run) scaled to 2/3",
                          ACTION_SCALED_TUPLET)

    # 4. Ambiguous: spread the squeeze evenly over the whole run.
    target = run_ticks - overshoot
    if target // n < MIN_SCALED_SLOT_TICKS:
        return None
    _rescale_slots(slots, i0, i1, target)
    return finish(FLAG_RUN_SCALED,
                  f"{facts}: either {overshoot / d:.1f} note(s) of the run "
                  f"were over-counted or part of it is a tuplet at an "
                  f"ambiguous position; all {n} slots scaled evenly, nothing "
                  "dropped", ACTION_SCALED_RUN)


def _keep_last_ticks(m_events: list, first_local: int,
                     keep: int) -> tuple[list, list, bool]:
    """Keeps the final `keep` ticks of a measure. Events wholly before the cut
    are dropped (pitched ones listed), an event straddling it loses its head:
    its onset moves to the cut and its duration shrinks accordingly.

    Returns:
        (kept events, dropped note descriptions, whether a NOTE lost its head).
        The caller mutes the pickup only if a note was dropped or cut, so a
        trim that removed only rests is not reported as lost music.
    """
    cut = _measure_ticks(m_events) - keep
    kept, dropped = [], []
    head_cut = False
    for e in m_events:
        offset = e["local_tick_onset"] - first_local
        end = offset + e["duration_ticks"]
        if end <= cut:
            if e["type"] == "note":
                dropped.append(_describe(e))
            continue
        if offset < cut:
            e["local_tick_onset"] += cut - offset
            e["duration_ticks"] -= cut - offset
            head_cut = head_cut or e["type"] == "note"
        kept.append(e)
    return kept, dropped, head_cut


def _clip_to_bar(m_events: list, first_local: int,
                 bar_ticks: int) -> tuple[list, list]:
    """Drops notes starting at/after the bar end and trims the straddler.
    Rests are never dropped. Returns (kept, dropped descriptions)."""
    dropped, kept = [], []
    for e in m_events:
        offset = e["local_tick_onset"] - first_local
        if e["type"] == "note":
            if offset >= bar_ticks:
                dropped.append(_describe(e))
                continue
            if offset + e["duration_ticks"] > bar_ticks:
                e["duration_ticks"] = bar_ticks - offset
        kept.append(e)
    return kept, dropped


def _repair_overflow(m_events: list, first_local: int, bar_ticks: int,
                     total: int) -> tuple[list, str, str, str, int]:
    """
    Repairs an over-long bar so nothing sounds past the bar end and nothing
    leaks into the next bar. The rest of the voice is never shifted. Returns
    (events, flag_kind, detail, action, notes dropped); the count decides
    whether Stage 5 mutes the bar (PIYA-103 AC9, resolution 3).

    1-4. If the bar holds a run (>=3 consecutive same-duration slots, >=2 of
       them notes) that can absorb the overshoot (squeezing it by <= 1/3),
       the run is rescaled rather than notes dropped: an exact triplet run,
       one beat-aligned partial triplet, or otherwise the whole run evenly
       (flag bar_overflow_run_scaled -- the CRNN most often miscounts
       beamed/repeated values, and a squeezed bar still plays every note).
       Nothing is dropped and no rest is touched.
    5. No usable run:
       - total ~ k*bar (k>=2): a barline was probably missed; clip, flag
         suspected_missing_barline, never scale.
       - overshoot off the sixteenth grid and the bar needs <= 25% squeeze:
         flattened tuplet (BUG-015), whole bar scaled, flag suspected_tuplet.
       - no qualifying run anywhere in the bar, every note has a usable
         confidence and one short value is over: drop the lowest-confidence
         match. (Never fires when a qualifying run exists -- the run is the
         better explanation.)
       - otherwise clip at the bar end, listing dropped notes.
    """
    overshoot = total - bar_ticks
    slots = _make_slots(m_events)
    runs = _qualifying_runs(slots)
    if runs:
        repaired = _repair_by_run(m_events, slots, runs, first_local,
                                  bar_ticks, overshoot)
        if repaired is not None:
            return repaired

    k = round(total / bar_ticks)
    if k >= 2 and abs(total - k * bar_ticks) <= DURATION_MISMATCH_TOLERANCE_TICKS:
        kept, dropped = _clip_to_bar(m_events, first_local, bar_ticks)
        return (kept, FLAG_MISSING_BARLINE,
                f"bar holds {total} ticks = {k} bars' worth; a barline was "
                "probably missed. Clipped to the first bar (not scaled), "
                f"dropped {len(dropped)} note(s): {dropped}",
                ACTION_CLIPPED, len(dropped))

    remainder = overshoot % TUPLET_GRID_TICKS
    if (min(remainder, TUPLET_GRID_TICKS - remainder)
            > DURATION_MISMATCH_TOLERANCE_TICKS
            and bar_ticks / total >= BAR_SCALE_MIN):
        scale = bar_ticks / total
        for e in m_events:
            offset = e["local_tick_onset"] - first_local
            e["local_tick_onset"] = first_local + round(offset * scale)
            e["duration_ticks"] = max(1, round(e["duration_ticks"] * scale))
        return (m_events, FLAG_SUSPECTED_TUPLET,
                f"bar is {overshoot} ticks over, not a multiple of "
                f"{TUPLET_GRID_TICKS}; likely a tuplet read as plain values "
                "(BUG-015). Scaled into the bar, nothing dropped.",
                ACTION_COMPRESSED, 0)

    note_events = [e for e in m_events if e["type"] == "note"]
    if (not runs and note_events
            and all(_has_confidence(e) for e in note_events)
            and overshoot <= MAX_CONFIDENCE_DROP_TICKS):
        onset_counts = Counter(e["local_tick_onset"] for e in m_events)
        candidates = [e for e in note_events
                      if abs(e["duration_ticks"] - overshoot)
                      <= DURATION_MISMATCH_TOLERANCE_TICKS
                      and onset_counts[e["local_tick_onset"]] == 1]
        if candidates:
            victim = min(candidates, key=lambda e: e["confidence"])
            m_events = [e for e in m_events if e is not victim]
            for e in m_events:
                if e["local_tick_onset"] > victim["local_tick_onset"]:
                    e["local_tick_onset"] -= victim["duration_ticks"]
            return (m_events, FLAG_BAR_OVERFLOW,
                    f"bar {overshoot} ticks over; dropped the lowest-"
                    f"confidence matching note {[_describe(victim)]} and "
                    "closed up (tie-broken by uncalibrated CRNN confidence "
                    "-- a guess, verify)", ACTION_CLIPPED, 1)

    kept, dropped = _clip_to_bar(m_events, first_local, bar_ticks)
    return (kept, FLAG_BAR_OVERFLOW,
            f"bar {overshoot} ticks over; durations trimmed to the bar end, "
            f"dropped {len(dropped)} note(s) starting after it: {dropped}",
            ACTION_CLIPPED, len(dropped))


# ── Tie resolution ─────────────────────────────────────────────────────────────

def _onset_groups(events: list) -> list:
    """Events (already ordered by global tick) grouped by identical onset."""
    groups: list = []
    for e in events:
        if groups and groups[-1][0]["tick_onset"] == e["tick_onset"]:
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups


def _infer_ties_from_slurs(groups: list, flags: list, voice: str) -> None:
    """
    Sets tie_to_next on notes whose slur is really a tie.

    Why slurs are treated as ties at all: in Camera-PrIMuS (the CRNN's only
    training data) every slur.start/slur.end pair is a `tie` in the semantic
    encoding (676/676/676 across the corpus, zero real slurs), so a slur token
    from the CRNN can only be a tie or an out-of-distribution guess. Stage 3
    has no tie token, so the tie is inferred: a slur that starts on a note and
    ends on the *immediately following* note (no rest between) of the *same
    pitch*. A slur over different pitches, or over 3+ notes, is a phrase slur
    and must not change audio. Across a system break the start is "dangling"
    (no end in its own strip): it ties to the first note of the next strip if
    the pitch matches; the end marker is not required there because the
    CRNN often drops it.

    Only sets flags on events; merging happens in _resolve_ties().
    """
    for a, group in enumerate(groups):
        for n in group:
            if n["type"] != "note" or n.get("slur") != SLUR_START or n.get("tie_to_next"):
                continue
            nxt = groups[a + 1] if a + 1 < len(groups) else None
            strip = (n["page_index"], n["sys_idx"])
            if nxt is not None and (nxt[0]["page_index"], nxt[0]["sys_idx"]) == strip:
                for m in nxt:
                    if (m["type"] == "note" and m["pitch"] == n["pitch"]
                            and (m.get("slur") == SLUR_END
                                 or m.get("slur_end"))):
                        n["tie_to_next"] = True
                continue
            # Last group of its strip with an open slur: dangling start.
            later_same_strip = any(
                (g[0]["page_index"], g[0]["sys_idx"]) == strip
                for g in groups[a + 1:])
            if later_same_strip:
                continue
            if nxt is not None and any(
                    m["type"] == "note" and m["pitch"] == n["pitch"] for m in nxt):
                n["tie_to_next"] = True
            else:
                flags.append({
                    "kind": FLAG_TIE_UNRESOLVED, "page_index": n["page_index"],
                    "sys_idx": n["sys_idx"], "bar": n.get("global_bar"),
                    "voice": voice, "expected_ticks": None, "actual_ticks": None,
                    "detail": "slur open at the end of the system but the next "
                              "system's first note has a different pitch (or "
                              "there is none); treated as a phrase slur",
                    "action": "none"})


def _resolve_ties(events: list, voice: str, flags: list) -> list:
    """
    Merges tied notes into one sustained note; phrase slurs pass through.

    A tie (explicit tie_to_next, or inferred by _infer_ties_from_slurs) joins
    a note to the SAME-PITCH note in the very next onset group -- also across
    a system/page boundary, since events are on the global timeline -- and
    only there: a rest or a different pitch in between breaks it and the
    break is flagged. Chains (A~A~A) merge into the first note. The absorbed
    events are removed, as before; the survivor records tie_span and
    tied_note_ids.
    """
    groups = _onset_groups(events)
    _infer_ties_from_slurs(groups, flags, voice)

    out: list = []
    open_ties: dict = {}          # pitch -> surviving event awaiting continuation
    for group in groups:
        next_open: dict = {}
        for e in group:
            e.setdefault("tie_to_next", False)
            e.setdefault("tie_span", 1)
            if e["type"] != "note":
                out.append(e)
                continue
            survivor = open_ties.pop(e["pitch"], None)
            if survivor is None:
                out.append(e)
                if e["tie_to_next"]:
                    next_open[e["pitch"]] = e
                continue
            survivor["duration_ticks"] += e["duration_ticks"]
            survivor["tie_span"] += 1
            if _has_confidence(survivor) and _has_confidence(e):
                survivor["confidence"] = min(survivor["confidence"],
                                             e["confidence"])
            elif "confidence" in survivor:
                survivor.pop("confidence")      # mixed: no honest signal
            if e.get("note_id") is not None:
                survivor.setdefault("tied_note_ids", []).append(e["note_id"])
            survivor["tie_to_next"] = bool(e["tie_to_next"])
            if e["tie_to_next"]:
                next_open[e["pitch"]] = survivor
        for pitch, survivor in open_ties.items():
            _flag_unresolved_tie(survivor, voice, flags)
        open_ties = next_open
    for survivor in open_ties.values():
        _flag_unresolved_tie(survivor, voice, flags)
    return out


def _flag_voice_run_scaling(reconstructed: dict, flags: list) -> None:
    """One voice-level warning if run scaling hit >25% of a voice's bars: that
    is the CRNN failing on the voice (or a wrong meter), not a few tuplets."""
    for voice in VOICES:
        bars = {(e["page_index"], e["sys_idx"], e["global_bar"])
                for e in reconstructed.get(voice, [])
                if e.get("global_bar") is not None}
        scaled = sum(1 for f in flags
                     if f["kind"] == FLAG_RUN_SCALED and f["voice"] == voice)
        if (len(bars) >= MIN_BARS_FOR_VOICE_FLAG
                and scaled / len(bars) > VOICE_RUN_SCALING_FRACTION):
            flags.append({
                "kind": FLAG_VOICE_RUN_SCALING, "page_index": None,
                "sys_idx": None, "bar": None, "voice": voice,
                "expected_ticks": None, "actual_ticks": None,
                "detail": f"{scaled} of {len(bars)} bars needed run scaling; "
                          "transcription of this voice is unreliable",
                "action": "none", "review_needed": True})


def _flag_unresolved_tie(note: Event, voice: str, flags: list) -> None:
    flags.append({
        "kind": FLAG_TIE_UNRESOLVED, "page_index": note["page_index"],
        "sys_idx": note["sys_idx"], "bar": note.get("global_bar"),
        "voice": voice, "expected_ticks": None, "actual_ticks": None,
        "detail": f"tie from {note.get('note_id') or note.get('symbol')} "
                  f"(midi {note['pitch']}) has no same-pitch note in the next "
                  "onset group (end of data, a rest, or a different pitch)",
        "action": "left_unmerged"})


# ── Reporting ─────────────────────────────────────────────────────────────────

def _report(reconstructed: dict, report_data: dict) -> None:
    print("\n[Stage 4] Reconstructed voice sequences:")
    for voice in VOICES:
        events = reconstructed[voice]
        notes  = sum(1 for e in events if e["type"] == "note" and e["pitch"] is not None)
        rests  = sum(1 for e in events if e["type"] == "rest")
        tied   = sum(e.get("tie_span", 1) - 1 for e in events)
        chords = len(set(e["chord_id"] for e in events
                         if e.get("chord_id") is not None))
        print(f"  {voice}: {len(events)} events "
              f"({notes} notes, {rests} rests, {chords} chord groups, "
              f"{tied} tie-merged)")
    flags = report_data["flags"]
    print(f"[Stage 4] {len(flags)} flag(s); pickup={report_data['pickup_ticks']} "
          f"ticks, total={report_data['total_ticks']} ticks")
    for f in flags:
        print(f"  [Stage 4] FLAG {f['kind']} p{f['page_index']} s{f['sys_idx']} "
              f"bar={f['bar']} voice={f['voice']}: {f['detail']} "
              f"(expected={f['expected_ticks']}, actual={f['actual_ticks']}, "
              f"action={f['action']})")
    print()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import stage3_clefkey
    from stage3_transcription import run_stages_1_to_3

    parser = argparse.ArgumentParser(
        description="PiyaNota Stage 4 — SATB Part Reconstruction")
    parser.add_argument("--input",   default="data/raw")
    parser.add_argument("--prep",    default="data/preprocessed")
    parser.add_argument("--strips",  default="data/strips")
    parser.add_argument("--weights", default="crnn_weights/best.pt")
    parser.add_argument("--yolo",    default="staff_detector_files/weights/best.pt")
    parser.add_argument("--img-height", type=int, default=64)
    stage3_clefkey.add_clef_key_args(parser)
    args = parser.parse_args()

    events = run_stages_1_to_3(args.input, args.prep, args.strips, args.yolo, args.weights,
                               stage3_clefkey.clef_key_arg(args), img_height=args.img_height)
    satb   = reconstruct_satb(events)

    print("\nStage 4 complete. SATB sequences ready for Stage 5 (MIDI synthesis).")
