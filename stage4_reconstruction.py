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
# of a real 4/4; see _consensus_time_signatures().
DEFAULT_TIME_SIGNATURE = "4/4"

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
# Flags that also carry review_needed=True ask the user to confirm/fix the
# bar; a flag without the key is informational (treat as review_needed=False).

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
        ValueError if any voice sequence is missing or empty.
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
        tick. report has keys: flags (list of dicts, see FLAG_* kinds),
        pickup_ticks, total_ticks (end of the last bar), systems (per-system
        layout).

    Raises:
        ValueError if any voice sequence is missing or empty.
    """
    print("\n[Stage 4] Reconstructing SATB part sequences...")

    missing = [v for v in VOICES if v not in voice_events
               or len(voice_events[v]) == 0]
    if missing:
        raise ValueError(
            f"[Stage 4] Missing or empty voice sequence(s): {missing}. "
            f"Check Stage 2/3 outputs or recapture the score."
        )

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
        info["n_bars"] * info["bar_ticks"] for info in layout.values())
    report_data = {
        "flags": flags,
        "pickup_ticks": pickup_ticks,
        "total_ticks": total_ticks,
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
        for e in voice_events[voice]:
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


def _consensus_time_signatures(strips: dict) -> dict:
    """
    One time signature per strip key.

    Stage 3 defaults to 4/4 whenever a strip carries no meter token, which is
    every continuation system, so a "4/4" reading is not evidence. Rule: the
    first system's most common value wins; a later system only *changes* the
    meter if its consensus differs from DEFAULT_TIME_SIGNATURE, otherwise it
    inherits. Known limit: a real change back to 4/4 mid-piece is invisible.
    """
    result: dict = {}
    previous: Optional[str] = None
    for key in sorted(strips):
        counts = Counter(e.get("time_signature", DEFAULT_TIME_SIGNATURE)
                         for events in strips[key].values() for e in events)
        top = counts.most_common()
        best = max(top, key=lambda kv: (kv[1], kv[0] != DEFAULT_TIME_SIGNATURE))[0]
        if previous is None or best != DEFAULT_TIME_SIGNATURE:
            previous = best
        result[key] = previous
    return result


def _plan_layout(strips: dict, flags: list) -> tuple[dict, int, dict]:
    """
    Decides bar structure for the whole piece before any event is moved.

    Returns:
        layout: {(page, sys): {time_signature, bar_ticks, n_bars,
                 first_bar, start_tick}} -- n_bars is the cross-voice
                 consensus (most common; ties -> larger).
        pickup_ticks: length of the anacrusis (0 if none) = the length the
                 agreeing voices share (deviant voices do not move it). Bar
                 1's downbeat is at this tick in every voice.
        voice_pickup: {voice: that voice's own pickup length} for voices
                 that have pickup content.

    Pickups are decided by _decide_pickups() (gates plus voice consensus,
    pickup_suspect on doubt), from durations and not measure_index numbering: Stage 3 skips a
    barline token that precedes the first note, so the first *full* bar of a
    voice without pickup content is measure_index 0 in real Stage 3 output
    but 1 in hand-authored ground truth. Limit: a first bar that is short
    only because Stage 3 dropped a token can still pass the gates; it is
    reported as FLAG_PICKUP (review_needed unless the final bar completes it)
    so it is visible, not assumed correct.
    """
    meters = _consensus_time_signatures(strips)
    first_key = min(strips)
    voice_pickup, pickup_ticks, suffix_ok = _decide_pickups(
        strips, meters, first_key, flags)
    voice_base: dict = {}

    layout: dict = {}
    for key in sorted(strips):
        bar_ticks = _bar_ticks(meters[key])
        n_by_voice: dict = {}
        for voice, events in strips[key].items():
            measures = _measures(events)
            if measures is None:
                continue
            indices = list(measures)
            base = indices[0]
            if key == first_key and voice in voice_pickup:
                base = indices[1]
            voice_base[(key, voice)] = base
            n_by_voice[voice] = max(
                (mi - base) + _measure_span(measures[mi], bar_ticks)
                for mi in indices if mi >= base)
        counts = Counter(n_by_voice.values())
        n_bars = max(counts, key=lambda n: (counts[n], n)) if counts else 0
        layout[key] = {"time_signature": meters[key], "bar_ticks": bar_ticks,
                       "n_bars": n_bars, "voice_bars": n_by_voice,
                       "voice_base": {v: voice_base[(key, v)] for v in n_by_voice}}

    # Voices whose shorter pickup is a dropped-leading-note suffix of the agreed
    # one: their length mismatch is informational (a list, so the report stays
    # JSON-serialisable).
    layout[first_key]["pickup_suffix_ok"] = sorted(suffix_ok)

    running = pickup_ticks
    bar_no = 1
    for key in sorted(layout):
        layout[key]["start_tick"] = running
        layout[key]["first_bar"] = bar_no
        running += layout[key]["n_bars"] * layout[key]["bar_ticks"]
        bar_no += layout[key]["n_bars"]
    return layout, pickup_ticks, voice_pickup


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
    fields: ticks (own length), conf (mean note confidence, None unless every
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
        bar_ticks = layout[cur]["bar_ticks"]
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


def _measure_span(events: list, bar_ticks: int) -> int:
    """Bars a measure occupies: 1, or N for a multirest measure (Stage 3
    bumps measure_index by N-1 after it, so the span is real bars)."""
    if _is_multirest(events):
        return max(1, round(_measure_ticks(events) / bar_ticks))
    return 1


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
    consensus, so measure `rank` (measure_index - base) is anchored at
    system_start + rank * bar_ticks, and each event keeps only its offset
    inside its own measure. Duration errors are contained per bar; bars whose
    total disagrees with the time signature are flagged (and overflow is
    clipped so it cannot collide with the next bar).

    Local mode (fallback): the voice's bar count disagrees with consensus (a
    dropped/hallucinated barline or multirest miscount) or it has no
    measure_index. Per-bar ranks cannot be trusted then, but its own running
    ticks still are; events are placed at system_start + local tick and the
    disagreement is flagged.
    """
    page_index, sys_idx = key
    measures = _measures(events)
    start_tick = info["start_tick"]
    bar_ticks = info["bar_ticks"]

    def flag(kind: str, bar: Optional[int], expected: Optional[int],
             actual: Optional[int], detail: str, action: str,
             review_needed: bool = False) -> None:
        entry = {"kind": kind, "page_index": page_index,
                 "sys_idx": sys_idx, "bar": bar, "voice": voice,
                 "expected_ticks": expected, "actual_ticks": actual,
                 "detail": detail, "action": action}
        if review_needed:
            entry["review_needed"] = True
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
        system_end = start_tick + info["n_bars"] * bar_ticks
        kept_events: list[Event] = []
        dropped_desc: list[str] = []
        trimmed = 0
        for e in events:
            e["tick_onset"] = origin + e["local_tick_onset"]
            e["global_bar"] = None
            if e["tick_onset"] >= system_end:
                if e["type"] == "note":
                    dropped_desc.append(_describe(e))
                continue
            if e["tick_onset"] + e["duration_ticks"] > system_end:
                e["duration_ticks"] = system_end - e["tick_onset"]
                trimmed += 1
            kept_events.append(e)
        if dropped_desc or trimmed:
            flag(FLAG_LOCAL_OVERRUN, None, info["n_bars"] * bar_ticks, None,
                 f"locally placed voice ran past the system end (tick "
                 f"{system_end}); trimmed {trimmed} event(s), dropped "
                 f"{len(dropped_desc)} note(s): {dropped_desc}",
                 ACTION_CLIPPED, review_needed=True)
        return kept_events

    base = info["voice_base"][voice]
    placed: list = []
    for mi, m_events in measures.items():
        _normalise_whole_rest(m_events, bar_ticks)
        first_local = min(e["local_tick_onset"] for e in m_events)
        total = _measure_ticks(m_events)
        if mi < base:
            if abs(total - pickup_ticks) > DURATION_MISMATCH_TOLERANCE_TICKS:
                own_total = total
                review = True
                if total > pickup_ticks:
                    # Right-aligning a longer bar would sound before tick 0:
                    # keep the LAST pickup_ticks (the notes leading into the
                    # downbeat), trimming from the head.
                    m_events, dropped = _keep_last_ticks(
                        m_events, first_local, pickup_ticks)
                    first_local = min(e["local_tick_onset"] for e in m_events)
                    total = _measure_ticks(m_events)
                    action = "trimmed_head_to_pickup"
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
                     review_needed=review)
            origin = pickup_ticks - total
            bar_no: Optional[int] = 0
            bar_end: Optional[int] = None
        else:
            rank = mi - base
            origin = start_tick + rank * bar_ticks
            bar_no = info["first_bar"] + rank
            bar_end = origin + bar_ticks
            if not _is_multirest(m_events):
                if total < bar_ticks - DURATION_MISMATCH_TOLERANCE_TICKS:
                    flag(FLAG_BAR_UNDERFULL, bar_no, bar_ticks, total,
                         "bar shorter than the time signature (dropped "
                         "note/rest?); remainder plays as silence", "none")
                elif total > bar_ticks + DURATION_MISMATCH_TOLERANCE_TICKS:
                    m_events, kind, detail, action = _repair_overflow(
                        m_events, first_local, bar_ticks, total)
                    flag(kind, bar_no, bar_ticks, total, detail, action,
                         review_needed=True)
        for e in m_events:
            e["tick_onset"] = origin + (e["local_tick_onset"] - first_local)
            e["global_bar"] = bar_no
            placed.append(e)
    return placed


def _normalise_whole_rest(m_events: list, bar_ticks: int) -> None:
    """A measure holding only a whole rest is a full-bar rest whatever the
    meter (a 3/4 bar rest is engraved as a whole rest), but Stage 3 always
    gives rest.whole 1920 ticks."""
    if (len(m_events) == 1 and m_events[0]["type"] == "rest"
            and str(m_events[0].get("symbol", "")).startswith("rest.whole")):
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
                   ) -> Optional[tuple[list[Event], str, str, str]]:
    """Steps 1-4 of _repair_overflow. Returns (events, kind, detail, action)
    or None when no run is a plausible culprit (caller goes to step 5)."""
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
            return m_events, kind, detail, action
        kept, dropped = _clip_to_bar(m_events, first_local, bar_ticks)
        return (kept, FLAG_BAR_INVARIANT,
                f"run repair ({kind}) left the bar at {landed} ticks, not "
                f"{bar_ticks}; clipped to the bar end, dropped {len(dropped)} "
                f"note(s): {dropped}. Internal invariant failure: verify",
                ACTION_CLIPPED)

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
                     keep: int) -> tuple[list, list]:
    """Keeps the final `keep` ticks of a measure. Events wholly before the cut
    are dropped (pitched ones listed), an event straddling it loses its head:
    its onset moves to the cut and its duration shrinks accordingly."""
    cut = _measure_ticks(m_events) - keep
    kept, dropped = [], []
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
        kept.append(e)
    return kept, dropped


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
                     total: int) -> tuple[list, str, str, str]:
    """
    Repairs an over-long bar so nothing sounds past the bar end and nothing
    leaks into the next bar. The rest of the voice is never shifted. Returns
    (events, flag_kind, detail, action).

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
                ACTION_CLIPPED)

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
                ACTION_COMPRESSED)

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
                    "-- a guess, verify)", ACTION_CLIPPED)

    kept, dropped = _clip_to_bar(m_events, first_local, bar_ticks)
    return (kept, FLAG_BAR_OVERFLOW,
            f"bar {overshoot} ticks over; durations trimmed to the bar end, "
            f"dropped {len(dropped)} note(s) starting after it: {dropped}",
            ACTION_CLIPPED)


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
