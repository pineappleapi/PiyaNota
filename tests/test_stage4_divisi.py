"""Stage 4 divisi handling: split-stem flag (freeze A3), chords as one slot, per-member ties."""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stage4_reconstruction as s4  # noqa: E402

Q = s4.TICKS_PER_QUARTER
BAR_34 = 3 * Q
VOICES = ("Soprano", "Alto", "Tenor", "Bass")
PITCH = {"Soprano": 72, "Alto": 67, "Tenor": 55, "Bass": 48}


def _bars(voice: str, bars: list, sys_idx: int = 0) -> list:
    """bars = [[(dur, pitch_or_list), ...], ...]; a list of pitches is one chord."""
    out, tick, chord_id = [], 0, 0
    for mi, bar in enumerate(bars):
        for dur, pitch in bar:
            pitches = pitch if isinstance(pitch, list) else [pitch]
            cid = None
            if len(pitches) > 1:
                chord_id += 1
                cid = chord_id
            for p in pitches:
                out.append({"type": "note" if p is not None else "rest", "pitch": p,
                            "duration_ticks": dur, "voice": voice, "page_index": 0,
                            "sys_idx": sys_idx, "tick_onset": tick, "measure_index": mi,
                            "time_signature": "3/4", "chord_id": cid, "slur": None})
            tick += dur
    return out


def _plain(voice: str, n_bars: int = 2) -> list:
    return [[(Q, PITCH[voice])] * 3 for _ in range(n_bars)]


def _run(feed: dict) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sat, report = s4.reconstruct_satb_with_report(feed)
    return sat, report, out.getvalue()


def _kinds(report: dict, voice: str, bar: int) -> set:
    return {f["kind"] for f in report["flags"] if f["voice"] == voice and f["bar"] == bar}


def test_split_stem_bar_flagged_not_scaled() -> None:
    """Alto bar 1 holds 6 beats (two rhythms read in sequence) while S/T/B hold 3."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 64), (3 * Q, 60)], [(Q, 67)] * 3])
    sat, report, _ = _run(feed)
    kinds = _kinds(report, "Alto", 1)
    assert s4.FLAG_SPLIT_STEM in kinds
    assert not kinds & {s4.FLAG_SUSPECTED_TUPLET, s4.FLAG_RUN_SCALED, s4.FLAG_MISSING_BARLINE}
    flag = [f for f in report["flags"] if f["kind"] == s4.FLAG_SPLIT_STEM][0]
    assert flag["review_needed"] is True
    bar1 = [e for e in sat["Alto"] if e["global_bar"] == 1]
    assert [e["pitch"] for e in bar1] == [67, 65, 64]
    assert max(e["tick_onset"] + e["duration_ticks"] for e in bar1) <= BAR_34
    assert [e["tick_onset"] for e in sat["Alto"] if e["global_bar"] == 2] == [BAR_34, BAR_34 + Q, BAR_34 + 2 * Q]


def test_all_voices_double_bar_is_missing_barline_not_split() -> None:
    feed = {v: _bars(v, [[(Q, PITCH[v])] * 6]) for v in VOICES}
    _, report, _ = _run(feed)
    for v in VOICES:
        kinds = _kinds(report, v, 1)
        assert s4.FLAG_SPLIT_STEM not in kinds
        assert s4.FLAG_MISSING_BARLINE in kinds


def test_split_stem_needs_other_voices_to_fit() -> None:
    """Soprano also overflows (by one beat): the Alto bar is not flagged split-stem."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Soprano"] = _bars("Soprano", [[(Q, 72)] * 4, [(Q, 72)] * 3])
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 64), (3 * Q, 60)], [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    assert s4.FLAG_SPLIT_STEM not in _kinds(report, "Alto", 1)


def test_ratio_outside_bounds_not_split() -> None:
    """1.5 bar lengths is below 1.75: ordinary overflow repair, no split flag."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 64), (Q, 62), (Q // 2, 60), (Q // 2, 60)],
                                  [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    assert s4.FLAG_SPLIT_STEM not in _kinds(report, "Alto", 1)


def test_whole_rest_voice_counts_as_fitting() -> None:
    """A 3/4 full-bar rest is engraved as a whole rest (1920 ticks); it still fits."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Bass"] = _bars("Bass", [[(4 * Q, None)], [(Q, 48)] * 3])
    feed["Bass"][0]["symbol"] = "rest.whole"
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 64), (3 * Q, 60)], [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    assert s4.FLAG_SPLIT_STEM in _kinds(report, "Alto", 1)


def test_chord_counts_once_in_bar() -> None:
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(2 * Q, [67, 70]), (Q, 67)], [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    assert not _kinds(report, "Alto", 1)


def test_chord_members_stay_together_through_run_scaling() -> None:
    """4 quarter slots in 3/4 (one a chord) are run-scaled; both members keep one onset and duration."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, [64, 67]), (Q, 65), (Q, 64)], [(Q, 67)] * 3])
    sat, report, _ = _run(feed)
    assert s4.FLAG_RUN_SCALED in _kinds(report, "Alto", 1)
    chord = [e for e in sat["Alto"] if e.get("chord_id") is not None]
    assert len(chord) == 2
    assert chord[0]["tick_onset"] == chord[1]["tick_onset"]
    assert chord[0]["duration_ticks"] == chord[1]["duration_ticks"]


def test_tie_on_one_chord_member_merges_only_that_member() -> None:
    """G4 tied into a G4+C5 chord: G4 sustains, C5 is struck fresh."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 67)], [(Q, [67, 72]), (Q, 65), (Q, 64)]])
    feed["Alto"][2]["tie_to_next"] = True
    sat, _, _ = _run(feed)
    g4 = [e for e in sat["Alto"] if e["pitch"] == 67]
    assert [e["tie_span"] for e in g4] == [1, 2]
    assert g4[1]["duration_ticks"] == 2 * Q
    c5 = [e for e in sat["Alto"] if e["pitch"] == 72]
    assert len(c5) == 1 and c5[0]["tick_onset"] == BAR_34


def test_chord_groups_counted_per_strip() -> None:
    """chord_id restarts at 1 in every strip, so the report keys chords by strip."""
    feed = {v: _bars(v, _plain(v)) + _bars(v, _plain(v), sys_idx=1) for v in VOICES}
    feed["Alto"] = (_bars("Alto", [[(2 * Q, [67, 70]), (Q, 67)], [(Q, 67)] * 3])
                    + _bars("Alto", [[(2 * Q, [67, 70]), (Q, 67)], [(Q, 67)] * 3], sys_idx=1))
    _, _, printed = _run(feed)
    assert "Alto: 12 events (12 notes, 0 rests, 2 chord groups" in printed


SPLIT_ALTO = [(Q, 67), (Q, 65), (Q, 64), (3 * Q, 60)]


def test_split_stem_drops_rests_of_the_second_rhythm() -> None:
    """A rest past the bar end must not leak into the next bar's time."""
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67), (Q, 65), (Q, 64), (2 * Q, None), (Q, 60)], [(Q, 67)] * 3])
    sat, report, _ = _run(feed)
    assert s4.FLAG_SPLIT_STEM in _kinds(report, "Alto", 1)
    bar1 = [e for e in sat["Alto"] if e["global_bar"] == 1]
    assert all(e["type"] == "note" for e in bar1)
    assert max(e["tick_onset"] + e["duration_ticks"] for e in bar1) <= BAR_34


def test_split_stem_rank_with_pickup() -> None:
    """All voices open with a one-beat pickup; the split bar is bar 1, after it."""
    feed = {v: _bars(v, [[(Q, PITCH[v])]] + _plain(v)) for v in VOICES}
    feed["Alto"] = _bars("Alto", [[(Q, 67)], SPLIT_ALTO, [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    assert report["pickup_ticks"] == Q
    assert s4.FLAG_SPLIT_STEM in _kinds(report, "Alto", 1)
    assert s4.FLAG_SPLIT_STEM not in _kinds(report, "Alto", 2)


def test_split_stem_rank_after_multirest_in_other_voice() -> None:
    """Bass rests two bars (multirest); the Alto split in bar 3 is still matched to bar 3."""
    feed = {v: _bars(v, _plain(v, 3)) for v in VOICES}
    feed["Bass"] = _bars("Bass", [[(2 * BAR_34, None)], [(Q, 48)] * 3])
    feed["Bass"][0]["symbol"] = "multirest-2"
    for e in feed["Bass"][1:]:
        e["measure_index"] = 2
    feed["Alto"] = _bars("Alto", [[(Q, 67)] * 3, [(Q, 67)] * 3, SPLIT_ALTO])
    _, report, _ = _run(feed)
    assert s4.FLAG_SPLIT_STEM in _kinds(report, "Alto", 3)
    assert not any(f["kind"] == s4.FLAG_SPLIT_STEM and f["bar"] != 3 for f in report["flags"])


def test_no_split_when_another_voice_is_locally_placed() -> None:
    feed = {v: _bars(v, _plain(v)) for v in VOICES}
    feed["Bass"] = _bars("Bass", _plain("Bass", 3))
    feed["Alto"] = _bars("Alto", [SPLIT_ALTO, [(Q, 67)] * 3])
    _, report, _ = _run(feed)
    local = {f["voice"] for f in report["flags"] if f["kind"] == s4.FLAG_BAR_COUNT}
    assert local == {"Bass"}
    assert not any(f["kind"] == s4.FLAG_SPLIT_STEM for f in report["flags"])


def test_split_bounds_inclusive() -> None:
    for first_bar, flagged in (([(Q, 67)] * 5 + [(Q // 4, 65)], True),             # 1.75
                               ([(Q, 67)] * 6 + [(3 * Q // 4, 65)], True),         # 2.25
                               ([(Q, 67)] * 7, False)):                            # 2.33
        feed = {v: _bars(v, _plain(v)) for v in VOICES}
        feed["Alto"] = _bars("Alto", [first_bar, [(Q, 67)] * 3])
        _, report, _ = _run(feed)
        assert (s4.FLAG_SPLIT_STEM in _kinds(report, "Alto", 1)) is flagged, first_bar
