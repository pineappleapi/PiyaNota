# Stage 3 note/accidental/dot/tie pairing for divisi chords — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `infer_pitch` pairs every accidental and dot with the notehead it was drawn for, including the members of
a same-stem divisi chord (`note.* chordnote-*`), and leaves monophonic output byte-identical.

**Architecture:** One new "onset" notion in `infer_pitch`: a `note.*` token plus the `chordnote-*` tokens right after
it. Accidentals since the previous onset are held by staff position and consumed by the member at that position;
when the onset closes, leftovers are flagged, validators run and the chord confidence is set. Dots on a chord count
per position. The decoder picks its token table from the model's output width, so a divisi checkpoint can be run.
Stage 4/5 are out of this plan (Stage 4 is Task 5 of `2026-10-15-divisi-seconds-splitstem.md`; Stage 5 needs no
change, chord plan 10.6).

**Tech Stack:** Python 3.12, pytest (scratch install, see Global Constraints), verovio 6.3.0 (oracle only).

**Spec:** `docs/decisions/piya-106-chord-vocabulary-plan.md` sections 10.4 and 10.6;
`docs/decisions/piya-106-divisi-arm-freeze.md` sections 1, 2, 6 and 10 (A3); converter token order in
`training/music_to_agnostic.py` `Converter.chord()` (~344-381). Supersedes Task 4 of
`docs/superpowers/plans/2026-10-15-divisi-seconds-splitstem.md`. Reviewed by senior-reviewer 2026-10-16 (GO with
changes, all applied).

## Global Constraints

- Monophonic input (no `chordnote-*` token) gives byte-identical `infer_pitch` events, stdout and
  `mid_changes_out` to the baseline (freeze section 6: "Phase 2's events stay byte-identical (Amendment 8.4)").
  Task 1's golden diff is the proof, not the unit tests.
- Chord token order is the converter's: `slur.end-<p>` per tied-in member, accidentals bottom to top,
  `note.<dur>-<base>`, `chordnote-<p>` bottom to top, `dot-<p>` one per head per dot, `slur.start-<p>` per member.
- Scope (freeze section 1, user 2026-10-14): "Stage 3 fix C (one dot per head) | IN", "Stage 3
  accidental-by-position matching, orphan drop | IN", "Stage 3 fixes A (ties), B (tie-carried accidentals) |
  DEFERRED | Reported as known-lost, with a count of tied chord members". A3 lists per-member ties under 10.6;
  section 1 is the user's explicit ruling, so ties are Task 6, run **only if the user confirms**; otherwise only the
  count is reported.
- "Stage 3 code may land after Sunday, but it must be sha-frozen before the look." Record the final
  `stage3_transcription.py` sha256 in the freeze doc before any Phase 4 scoring.
- Validators (freeze section 6, verbatim): "V1: member interval over 12 semitones, in any voice." "V2: 3 or more
  members." "V4 voice range (sounding MIDI ...): S 58-86, A 51-79, T 46-71, B 38-66." "All three apply **only to
  events with a `chord_id`**". Flag only; notes still play.
- Confidence (10.6): "each member's is the min of its own note and accidental tokens. The chord's is the min over
  its members. Still not a trust signal (BUG-011)."
- Data firewall: no `piyanota_dataset` photos, nothing under `D:/PiyaNota/datasets/phase4_strips/`. Golden and
  oracle inputs are CPM, the Phase 2 manifest and the G1b divisi build (synthetic/dev); their numbers are
  invariance/diagnostic checks, never accuracy evidence.
- Test header: every `infer_pitch` test starts with an explicit header. `C = ["clef.G-L2", "metersign.C-L3"]`;
  `EB = ["clef.G-L2", "accidental.flat-L3", "accidental.flat-S4", "accidental.flat-S2", "metersign.C-L3"]`. A
  token under test that must be read in the body follows a first note (`"note.quarter-L2"`), so no header stage
  swallows it. Every Step 2 must show each new test FAILING at the pre-change code; a test that passes there is
  rewritten, not kept.
- Treble positions: L-1 A3, S-1 B3, L0 C4, L1 E4, L2 G4, L3 B4, S3 C5, S4 E5. quarter 480 ticks, half 960.
- Test runs: `PYTHONPATH=C:/Users/paul_/.claude/jobs/3ab43d79/tmp/pytest_lib D:/PiyaNota/.venv/Scripts/python.exe -m pytest tests/test_stage3_*.py tests/test_chordnote_metrics.py tests/test_chord_xorder_audit.py -q -p no:cacheprovider`
  (all Stage 3 test files, including `test_stage3_header_filter.py` and `test_stage3_key_continuity.py`). Never
  `pip install` into the shared venv (PIYA-112).
- CLAUDE.md: plan-first, risk line, no commit without the user's approval (`PIYA-106: <summary>` + trailer).

## Review Focus

1. **Accidental before a chord whose base is elsewhere** (`accidental.sharp-L1 note.beamedLeft2-S-1 chordnote-L1`,
   a real G1b label): the sharp must reach the chordnote; today `_accidental_is_anchored` drops it as a BUG-033
   phantom. Tasks 2, 3a.
2. **Production header path**: under `header_override` (the `stage3_clefkey.infer_pitch_b` path),
   `_header_accidental_is_inline` decides the first onset's accidentals and stops at the first non-slur/fermata
   token, so a chord's first accidental is dropped. Task 2.
3. **Dotted chord** `dot-S1 dot-S2` must be one dot; `dot-S1 dot-S1 dot-S2 dot-S2` a double dot. Mono, including
   the misplaced `note.half-L2 dot-S2 dot-S3` (1680 today), unchanged. Task 4.
4. **CRNN junk shapes**: chordnote at strip start, after a rest, barline or in a header stage, on the base position,
   below the base, accidental for no member. Drop/flag, never crash. Task 3b.
5. **Silent `<unk>`**: a decode table that does not match the model must raise, not map chordnotes to `<unk>`
   (BUG-002 class). Task 5.

---

### Task 1: Baselines (golden harness and G1b pitch replay), before any edit

**Files:**
- Create: `training/phase2/stage3_golden.py`, `training/phase1/g1b_pitch_replay.py`
- Output: `C:/Users/paul_/.claude/jobs/3ab43d79/tmp/stage3_golden/`

**Interfaces:**
- Produces: `stage3_golden.py dump --out <json>` / `diff <a> <b>` (exit 1, print the first 20 differing keys);
  `g1b_pitch_replay.py --build <g1b dir> --out <json>` → `{strips, chord_strips, match, chord_match, mismatches}`.

- [ ] **Step 1: golden inputs.** (a) all 3996 CPM `.agnostic` files under
  `D:/PiyaNota/datasets/CameraPriMus/CameraPrIMuS - Copy` (voice "Soprano"); (b) the first 3000 Phase 2 manifest
  rows sorted by `path` (voice = the `_<Voice>.png` suffix of `path`); (c) noisy: Phase 2 seed-1
  (`D:/PiyaNota/music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt`) greedy decodes with
  confidences of 1000 distorted CPM images (first 1000 sorted), via `transcribe_strip(..., return_confidence=True)`.
  Decodes are computed once and cached to the output dir, so later dumps reuse the same tokens.
- [ ] **Step 2: golden variants per input.** (i) plain; (ii) with confidences (real ones for (c), 0.9 per token
  for (a)/(b)); (iii) with a `HeaderOverride` from the ground-truth header (first clef token; key = signed count of
  the accidentals before the first metersign/note; `octave_shift` 0), once with `next_system_key=None` and once
  with `next_system_key = key + 1` if within ±7. Store per key: events (`json.dumps(sort_keys=True)`), captured
  stdout (`contextlib.redirect_stdout`) and `mid_changes_out`.
- [ ] **Step 3: G1b replay.** For each Leipzig strip in `C:/Users/paul_/.claude/jobs/3ab43d79/tmp/g1b_div`
  (`renders/Leipzig/<piece>/labels.json` rows: `voice`, `staff_n`, `measures`, `tokens`): expected = sorted
  sounding MIDI of the MEI notes in `staff_n` within `measures`, via verovio (`loadData`, then `renderToMIDI()`,
  then `getMIDIValuesForElement(id)["pitch"]`); got = sorted pitches of `infer_pitch(tokens, voice)` notes.
- [ ] **Step 4:** Run both at the pre-change code (HEAD `0ebc532` plus only these two new files):
  `golden_base.json` and `g1b_base.json`. Record key counts, sha256 and the replay totals in the task report.
- [ ] **Step 5:** Report; commit with Task 2 after user approval.

### Task 2: Onset positions for anchoring

**Files:**
- Modify: `stage3_transcription.py` `_next_note_position` (~896), `_accidental_is_anchored` (~909),
  `_header_accidental_is_inline` (~924), `_is_mid_key_change` (~963), the glyph check at ~1075
- Test: `tests/test_stage3_chord_pairing.py` (new)

**Interfaces:**
- Produces: `_next_onset_positions(symbols: list[str], idx: int) -> set[str]` — position of the next `note.*`
  after `idx` plus every `chordnote-*` directly after it (stop at the first other token); empty if a barline comes
  first. Mono: `{_next_note_position(...)}` or empty.

- [ ] **Step 1: Failing tests:**
  - `test_accidental_on_chordnote_position_is_anchored`: `C + ["note.quarter-L2", "accidental.sharp-L1",
    "note.quarter-S-1", "chordnote-L1"]` → no event has `unanchored_accidental_dropped`.
  - `test_accidental_off_every_member_still_dropped`: `C + ["note.quarter-L2", "accidental.sharp-L3",
    "note.quarter-L1", "chordnote-S3"]` → the L1 event carries `unanchored_accidental_dropped ==
    "accidental.sharp-L3"`.
  - `test_override_chord_accidentals_inline`: `HeaderOverride("clef.G-L2", 0, 0)`, tokens `["clef.G-L2",
    "accidental.sharp-L1", "accidental.flat-S3", "note.quarter-L1", "chordnote-S3"]` → pitches 65, 71 (after Task
    3a; in Task 2 assert only that no accidental is dropped).
  - `test_post_bar_accidental_on_chordnote_not_key_change`: `C + ["note.quarter-L2", "barline-L1",
    "accidental.sharp-S3", "note.quarter-L1", "chordnote-S3"]` → no key change in `mid_changes_out`, no drop.
- [ ] **Step 2:** Run; each must FAIL (Global Constraints rule).
- [ ] **Step 3:** Add `_next_onset_positions`; replace each next-note equality test with set membership.
  `_header_accidental_is_inline` may skip further accidental tokens only when the onset it reaches has a
  `chordnote-*` (mono keeps today's stop-at-first-token rule).
- [ ] **Step 4:** All tests PASS; golden `dump` → `golden_t2.json`, `diff golden_base.json golden_t2.json`
  identical.
- [ ] **Step 5:** Report; commit after user approval (Task 1 scripts + Task 2).

### Task 3a: Position-keyed pending accidentals and one pitch helper

**Files:**
- Modify: `stage3_transcription.py` `infer_pitch` state (~1211-1231), inline accidental branches (~1356, ~1393,
  ~1542), note branch (~1603-1698), barline (~1700)
- Test: `tests/test_stage3_chord_pairing.py`

**Interfaces:**
- Produces: state `pending_accs: dict[str, tuple[int, float, str]]` (position → alteration, confidence, token)
  replacing `pending_acc`/`pending_acc_conf`; a local helper inside `infer_pitch`
  `_member_pitch(pos_str: str, tok_conf: float) -> tuple[int, int, float]` (midi, step, member confidence) that
  consumes `pending_accs[pos_str]`, writes `measure_alterations` and applies the existing precedence (pending →
  tie carry → measure → key). The note branch calls it; Task 3b's chordnote branch calls it too.

- [ ] **Step 1: Failing tests:**
  - `test_accidental_paired_by_position`: `EB + ["accidental.natural-S4", "note.quarter-L1", "chordnote-S4",
    "note.quarter-S4", "barline-L1", "note.quarter-S4"]` → pitches 63, 76, 76, 75.
  - `test_two_accidentals_two_members`: `C + ["note.quarter-L2", "accidental.sharp-L1", "accidental.flat-S3",
    "note.quarter-L1", "chordnote-S3"]` → last two pitches 65, 71.
  - `test_real_g1b_label_sharp_on_upper_member`: `C + ["note.quarter-L2", "accidental.sharp-L1",
    "note.beamedLeft2-S-1", "chordnote-L1"]` → last two pitches 59, 65 (S-1 B3; L1 E4 sharpened to E#4 = 65).
- [ ] **Step 2:** FAIL (chordnote not parsed yet: these fail until 3b; 3a's own check is Step 4's golden).
- [ ] **Step 3:** Implement the state and helper; a later accidental on the same position replaces the earlier one;
  barline clears `pending_accs`.
- [ ] **Step 4:** Existing tests PASS; golden diff identical.
- [ ] **Step 5:** Report (no commit; commit with 3b).

### Task 3b: Chordnote events, onset close, orphans and confidence

**Files:**
- Modify: `stage3_transcription.py` `infer_pitch` (new `chordnote-` branch next to the note branch; header stages'
  token switch at ~1356-1471; delete the dead same-onset heuristic ~1655-1666)
- Test: `tests/test_stage3_chord_pairing.py`

**Interfaces:**
- Consumes: `_member_pitch` (3a), `_next_onset_positions` (2).
- Produces: base and members are `"type": "note"` events with the base's `tick_onset`, `duration_ticks`,
  `measure_index`, `time_signature` and one shared `chord_id` (int, counter per `infer_pitch` call from 1;
  Stage 4 must not treat it as global); `current_tick` advances once. Mono notes keep `chord_id: None`. A local
  `_close_onset()` runs before handling the next token that is not `chordnote-*`, at a barline, on a header→body
  transition and after the loop. On a chord it: puts the first leftover `pending_accs` token on the base as
  `unanchored_accidental_dropped` (existing log count kept); with confidences, sets `chord_confidence` (min over
  members) on every member. On a mono onset it does exactly what today's code does. Dots and `slur.start` after a
  closed onset still apply to it (Task 4); `slur.start` after a rest or a single note keeps today's `events[-1]`
  behaviour. New keys, each with `review_needed: True`: `unison_chordnote_dropped: str` (on the base),
  `orphan_chordnote_dropped: str` (held like `dropped_acc` and put on the next emitted event),
  `chordnote_below_base: str` (on that member, pitch kept).

- [ ] **Step 1: Failing tests:**
  - `test_dyad_shares_onset_and_advances_once`: `C + ["note.half-L2", "chordnote-L3", "note.quarter-L2"]` → 67, 71,
    67; first two onset 0 and the same `chord_id`, third onset 960, `chord_id None`. Also `EB + [...]` → 67, 70, 67.
  - the three Task 3a tests now PASS.
  - `test_unison_chordnote_dropped`: `C + ["note.quarter-L2", "chordnote-L2"]` → one event,
    `unison_chordnote_dropped == "chordnote-L2"`, `review_needed`.
  - `test_orphan_chordnote_after_rest_barline_header`: `C + ["rest.quarter-L3", "chordnote-L2",
    "note.quarter-L2"]`, `C + ["note.quarter-L2", "barline-L1", "chordnote-L2", "note.quarter-L2"]` and
    `["clef.G-L2", "chordnote-L2", "metersign.C-L3", "note.quarter-L2"]` → no event for the chordnote; the next
    emitted event carries `orphan_chordnote_dropped == "chordnote-L2"` and `review_needed`.
  - `test_chordnote_below_base_kept_and_flagged`: `C + ["note.quarter-L3", "chordnote-L1"]` → pitches 71, 64,
    same `chord_id`, member flagged `chordnote_below_base`.
  - `test_member_and_chord_confidence`: `C` tokens with 0.99 each, then `("note.quarter-L2", 0.99),
    ("accidental.sharp-S3", 0.6), ("note.quarter-L1", 0.9), ("chordnote-S3", 0.95)` → base confidence 0.9, member
    0.6, both `chord_confidence` 0.6.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** All tests PASS; golden diff identical; G1b replay (`g1b_t3.json`): list every chord-strip
  mismatch with its tokens; any caused by pairing is fixed before reporting.
- [ ] **Step 5:** choral-conductor check of the Step 1 expectations (pitches and flags). Report; commit 3a+3b
  after user approval.

### Task 4: Dots on chords (fix C)

**Files:**
- Modify: `stage3_transcription.py` dot branch (~1552)
- Test: `tests/test_stage3_chord_pairing.py`

**Interfaces:**
- Produces: only when the dotted onset has a `chord_id`: every member's duration = `_dotted_ticks(base, n)` with
  `n` = the highest count of `dot-<p>` tokens at any one position since the onset; the cursor moves once by the
  difference. Dot confidence is not folded into chord members (10.6: note + accidental only). Mono dots are
  untouched (each dot token adds one dot, confidence folded, as today).

- [ ] **Step 1: Failing tests:** `test_dotted_dyad_one_dot`: `C + ["note.half-L2", "chordnote-L3", "dot-S2",
  "dot-S3", "note.quarter-L2"]` → both members 1440, next onset 1440. `test_double_dotted_dyad`: `dot-S2 dot-S2
  dot-S3 dot-S3` → 1680 both, next onset 1680. `test_mono_misplaced_double_dot_unchanged`: `C + ["note.half-L2",
  "dot-S2", "dot-S3", "note.quarter-L2"]` → 1680, next onset 1680 (passes before and after; it is the guard).
- [ ] **Step 2:** first two FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** All tests PASS; golden diff identical.
- [ ] **Step 5:** Report; commit after user approval.

### Task 5: Decode with the model's own vocabulary

**Files:**
- Modify: `stage3_transcription.py` CRNN construction in both loaders (~2757, ~2916) and `transcribe_strip`
  (~1940-2014)
- Test: `tests/test_stage3_chord_pairing.py`

**Interfaces:**
- Produces: `_vocab_for_checkpoint(ckpt: dict) -> list[str]`: `ckpt["vocab"]` must equal `VOCAB` or
  `VOCAB_EXT_CHORD_TUPLET` exactly (inference needs a full table, so this is stricter than `train_phase2.py`
  `load_model`'s prefix rule); absent → `VOCAB`; else `ValueError`; and `len(vocab)` must equal the checkpoint's
  `fc.weight` rows, else `ValueError`. Loaders build `CRNN(len(vocab))`. `transcribe_strip` derives its table from
  `model.fc.out_features` (== `len(VOCAB)` → `VOCAB`, == `len(VOCAB_EXT_CHORD_TUPLET)` → the extension, otherwise
  `ValueError`); no `idx_to_sym` default parameter, so no caller can forget it. Call sites to check still work:
  `stage3_transcription.py` ~2659 and ~2774, `training/phase2/eval_dev.py:93`, `compare_omr_baselines.py:186`.

- [ ] **Step 1: Failing tests:** ext vocab → that list; no `vocab` key → `VOCAB`; shuffled vocab → `ValueError`;
  vocab length ≠ fc rows → `ValueError`; a `CRNN(len(VOCAB_EXT_CHORD_TUPLET))` with random weights decodes through
  `transcribe_strip` without `<unk>` for any index.
- [ ] **Step 2–4:** FAIL, implement, PASS. Smoke: load the Phase 2 seed-1 checkpoint and one checkpoint from
  `C:/Users/paul_/.claude/jobs/3ab43d79/tmp/smoke_head_a3/`; both decode one CPM strip. Golden diff identical.
- [ ] **Step 5:** Report; commit after user approval.

### Task 6 (only if the user confirms): ties per member (fixes A, B)

Default (no confirmation): skip, and Task 7 reports the count of tied chord members on the G1b replay as known-lost.

**Interfaces:**
- Produces: `pending_tie_ends: set[str]` replaces the boolean `slur_end_pending`; each `slur.end-<p>` /
  `slur.start-<p>` attaches to the member nearest `p` by staff step (ties toward the lower member);
  `prev_onset_alters: dict[int, tuple[int, float]]` replaces `last_note_step`/`last_note_alteration`/
  `last_note_alt_conf`. Mono reduces to today's rule.

- [ ] **Step 1: Failing tests:** `C + ["accidental.sharp-L2", "note.half-L2", "slur.start-L2", "barline-L1",
  "slur.end-L2", "note.half-L2", "chordnote-S3"]` → second-bar G member 68 with `slur == "end"` and `slur_end`, the
  S3 member 72 without; `C + ["note.half-L2", "chordnote-S3", "slur.start-S3"]` → only the S3 member has
  `slur == "start"`.
- [ ] **Step 2–5:** FAIL, implement, PASS + golden identical, report, commit after approval.

### Task 7: Final checks

- [ ] **Step 1:** Full test run (Global Constraints command): PASS. Golden diff vs `golden_base.json`: identical.
- [ ] **Step 2:** G1b replay → `g1b_final.json`. Report base vs final totals, every remaining chord-strip mismatch,
  and (if Task 6 skipped) the count of tied chord members. Diagnostic only.
- [ ] **Step 3:** Note for the Stage 4 plan: `chord_id` restarts per strip, so Stage 4's chord counting
  (`stage4_reconstruction.py` ~1384) must key on (page, system, chord_id).
- [ ] **Step 4:** choral-conductor review of the whole diff, then senior-reviewer before any merge. Record the
  `stage3_transcription.py` sha256 in the freeze doc after the user approves the commit.
