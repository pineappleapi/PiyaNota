# Divisi Seconds and Split-Stem Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the divisi arm's two known weak spots (seconds drawn as side-by-side heads; two voices with
different rhythms in one staff) measured, flagged and correctly played, without changing the frozen training data.

**Architecture:** Before the Kaggle launch (Sat 2026-10-17 12:00): pre-register the new measurements in the freeze
doc (amendment A3), add a chord head x-order audit at the corpus gate, and break chordnote metrics down per
interval. After launch, before the version-2 eval: teach Stage 3 to turn `chordnote-<pos>` into simultaneous
events (dots k/h, accidentals per position, ties per member) and teach Stage 4 to flag a bar that is about twice
its length as a suspected split-stem divisi instead of silently repairing it.

**Tech Stack:** Python 3, PyTorch (train_phase2 metrics only), xml.etree (SVG audit), pytest.

**Spec:** `docs/decisions/piya-106-divisi-arm-freeze.md` (frozen; sections 1, 3, 5, 10) plus the 2026-10-15
reviews recorded in A3 (choral-conductor: label order and Stage 3/4 rules; ml-cv-lead: GO, 3 pre-registration
additions, no gate or schedule change).

## Global Constraints

- Training data, interval mix (3rds .35, 6ths .25, 8ves .20, 4ths/5ths .10, 2nds .10) and section 5 gates stay as
  frozen. Seconds are reported, never gated.
- Phase 4 data (`D:/PiyaNota/datasets/phase4_strips/`) is never read while writing or tuning anything here. A3 is
  committed before any Phase 4 look.
- The split-stem flag rule is hand-set now: bar total / bar length in [1.75, 2.25] while the other three voices
  fit that bar. Never tuned on Phase 4 or `piyanota_dataset`.
- Thesis claim scope: "reads same-stem (homorhythmic) divisi". Split stems with the same rhythm were cut
  2026-10-14 (freeze table line 27); two voices with different rhythms were never in scope. Both are flagged, not
  modelled.
- Commit messages `PIYA-106: <summary>` with the session trailer; commit only after user approval.

## Review Focus

1. Unison divisi (model emits `chordnote` at the same position as its `note.*`): must sound as one note, not two
   identical notes. Test in Task 4.
2. Dots after a chord follow chord vocabulary plan 10.4/10.6 (fix C): dots at distinct positions are one dot for
   the whole chord, repeats at one position are a double dot. Test in Task 4.
3. A legitimate 2-bar total caused by a real missing barline in all voices must not be flagged as split-stem
   (the "other voices fit" condition). Test in Task 5.
4. An inline accidental on one chord member must not alter the other members (octave dyad E-flat4 + E5 natural).
   Test in Task 4.
5. A tie on one member of a chord (the other member re-struck) must merge only that member. Test in Task 5.

---

### Task 1: Freeze-doc amendment A3 (pre-registration)

**Files:**
- Modify: `docs/decisions/piya-106-divisi-arm-freeze.md` (append to section 10)

- [ ] **Step 1: Append A3** with these decisions, each one line: claim scope (Global Constraints); seconds kept at
  the frozen mix (candidate-limited, realised .03 on the G1b sample); per-interval rows (2nd, 3rd, 4th/5th, 6th,
  8ve) of chordnote precision/recall with n and Wilson 95% CI, reported on synthetic val, camera-grandstaff
  diagnostic and Phase 4, no gate; `second_as_sequence` count; corpus-gate x-order audit (Task 2), mismatches go
  on the known-lost list, no relabelling; Phase 4 expected outcome per GT kind (same-stem: primary metric;
  split-stem same rhythm: zero-shot, same labels as a chord; two-voice different rhythm: expected failure,
  report member recall, insertions, confident-wrong at 0.90); split-stem flag rule `divisi_rhythm_split_suspected`
  + `review_needed` ([1.75, 2.25], others fit), report its recall on two-voice bars and false-flag rate elsewhere;
  Stage 3 chord rules (Task 4) and the label-order finding (dyads: bottom-to-top equals left-to-right in all stem
  directions; only 3+ head clusters differ). Also correct `docs/decisions/piya-106-chord-vocabulary-plan.md` line
  495 ("reverse of x order"), which the reviews found to be wrong for dyads.
- [ ] **Step 2: Commit** `PIYA-106: freeze amendment A3 (seconds, split-stem pre-registration)` after approval.

### Task 2: Chord head x-order audit (corpus gate)

**Files:**
- Create: `training/phase1/chord_xorder_audit.py`
- Test: `tests/test_chord_xorder_audit.py`

**Interfaces:**
- Produces: `chord_order_mismatches(svg_text: str) -> list[dict[str, object]]` (one dict per chord whose heads,
  sorted bottom to top by y, are not in left-to-right x order; keys `chord_id`, `heads` as `[(x, y), ...]`);
  CLI `python training/phase1/chord_xorder_audit.py --renders <dir> [--out report.json]` printing
  `{"chords": N, "mismatches": M, "by_size": {...}}`.

- [ ] **Step 1: Write failing tests**: a hand-written SVG snippet with one `g.chord` of two `g.note` heads where the
  upper head has the larger x returns `[]`; the same with x swapped returns one mismatch; a 3-head cluster with
  middle head displaced right returns one mismatch. Heads with equal x (stacked 3rds) never count.
- [ ] **Step 2: Run** `D:/PiyaNota/.venv/Scripts/python.exe -m pytest tests/test_chord_xorder_audit.py -v`; expect FAIL.
- [ ] **Step 3: Implement**: notehead = the `use` inside each `g.note` child of `g.chord`; x/y from its `x`/`y`
  attributes (or `transform`, as `svg_check._use_y` does); SVG y grows downward, so bottom to top is y descending.
- [ ] **Step 4: Run tests**; expect PASS. Run the CLI on the G1b sample renders
  (`C:/Users/paul_/.claude/jobs/3ab43d79/tmp/g1b_div/renders`); expect dyad mismatches 0.
- [ ] **Step 5: Commit** after approval.

### Task 3: Per-interval chordnote metrics and `second_as_sequence`

**Files:**
- Modify: `training/phase2/train_phase2.py:347-362` (`chordnote_metrics`)
- Test: `tests/test_chordnote_metrics.py`

**Interfaces:**
- Produces: `chordnote_metrics(pairs)` adds `by_interval: dict[str, dict]` keyed `2nd, 3rd, 4th5th, 6th, 8ve,
  other`, each `{"gt": int, "hit": int, "recall": float | None, "wilson95": [lo, hi] | None}`, and
  `second_as_sequence: int`. Interval = staff steps between the chordnote and the head directly below it
  (1 = 2nd, 2 = 3rd, 3-4 = 4th5th, 5 = 6th, 7 = 8ve, else other). Existing keys unchanged.

- [ ] **Step 1: Write failing tests**: gt `[note.quarter-L2, chordnote-S2]` with pred identical gives
  `by_interval["2nd"] == {"gt": 1, "hit": 1, ...}`; pred `[note.quarter-L2, note.quarter-S2]` gives
  `second_as_sequence == 1` and 2nd recall 0; a 3rd (`L2` + `L3`) lands in `3rd`; Wilson bounds for 8/10 are
  about [0.49, 0.94].
- [ ] **Step 2: Run** `pytest tests/test_chordnote_metrics.py -v`; expect FAIL.
- [ ] **Step 3: Implement** using the existing `lcs_matched_gt`; `second_as_sequence` counts GT positions i where
  `gt[i]` is a 2nd chordnote, i is unmatched, and pred contains a `note.*` at `gt[i]`'s position directly after a
  `note.*` at `gt[i-1]`'s position.
- [ ] **Step 4: Run tests and the head-only smoke** (`--smoke --vocab-ext --head-only --select-last --lr 1e-3
  --divisi-recut-out <fake corpus>`); expect PASS and `by_interval` in `metrics.json`.
- [ ] **Step 5: Commit** after approval (must land before the Kaggle bundle is built).

### Task 4: Stage 3 chordnote parsing (after launch)

**Files:**
- Modify: `stage3_transcription.py` (`infer_pitch` note branch ~1600-1680, dot branch ~1552)
- Test: `tests/test_stage3_chordnote.py`

**Interfaces:**
- Consumes: tokens from `VOCAB_EXT_CHORD_TUPLET`.
- Produces: each `chordnote-<pos>` becomes a `"type": "note"` event with the preceding note's `tick_onset`,
  `duration_ticks`, `voice`, and a shared `chord_id`; `current_tick` advances once per chord. Flags on the
  chord's events: `chord_dots_ambiguous`, `unison_chordnote_dropped`.

- [ ] **Step 1: Write failing tests** (treble, E-flat major): `note.half-L2 chordnote-L3 dot-S2 dot-S3` gives two
  events, pitches 67 and 70, both 1440 ticks, same onset, next event onset +1440; 3 dots on a dyad gives 1 dot
  each (distinct positions S2 S3 + a stray third dot is still one dot, flagged `review_needed`); `accidental.natural-S4 note.quarter-L1 chordnote-S4` gives 63 and 76 (only E5
  natural); `note.quarter-L2 chordnote-L2` gives one event plus `unison_chordnote_dropped`; a later
  `note.quarter-S4` in the same bar keeps the natural (76).
- [ ] **Step 2: Run** `pytest tests/test_stage3_chordnote.py -v`; expect FAIL.
- [ ] **Step 3: Implement** chord vocabulary plan 10.6 Stage 3 exactly (it is the spec; A3 only adds the flag
  names above).
- [ ] **Step 4: Run** the new tests plus `pytest tests/test_stage3_dots.py tests/test_stage3_accidentals.py
  tests/test_stage3_5_regressions.py`; expect all PASS (no-chord output unchanged).
- [ ] **Step 5: choral-conductor review, then commit** after approval.

### Task 5: Stage 4 chord-aware ties and split-stem flag (after launch)

**Files:**
- Modify: `stage4_reconstruction.py` (tie merge; bar overflow repair near `FLAG_RUN_SCALED`, line ~1150)
- Test: `tests/test_stage4_divisi.py`

**Interfaces:**
- Consumes: Task 4 events (`chord_id`).
- Produces: flag constant `FLAG_SPLIT_STEM = "divisi_rhythm_split_suspected"` (carries `review_needed`); bar
  totals count a chord once.

- [ ] **Step 1: Write failing tests**: in 3/4, one voice's bar holds three quarters + a dotted half (6 beats) while
  the other voices hold 3 beats: flag `divisi_rhythm_split_suspected`, no `suspected_tuplet` or
  `bar_overflow_run_scaled` on that bar, notes kept up to the bar length; all four voices at 6 beats: no split
  flag (falls to `suspected_missing_barline` as today); a chord (G4+B-flat4 half) counts 2 beats, not 4; tie on
  the G4 member only into a G4+C5 chord merges G4 and re-strikes C5.
- [ ] **Step 2: Run** `pytest tests/test_stage4_divisi.py -v`; expect FAIL.
- [ ] **Step 3: Implement** the ratio check before the run-scaling repair; ties match by pitch across consecutive
  onsets within a voice.
- [ ] **Step 4: Run** the new tests plus the existing Stage 3-5 tests; expect all PASS.
- [ ] **Step 5: choral-conductor review, senior-reviewer before merge, commit** after approval.
