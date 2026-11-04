# Stage 4 Tie and Bar-Repair Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower event SER of the v1 pipeline by fixing the two Stage 4 failures that ml-cv-lead's 2026-11-04 diagnosis traced most errors to: tied notes that are never merged, and bar-sum repair that spreads one misread beam token across a whole run.

**Architecture:** Both fixes are code-only changes in `stage4_reconstruction.py`, each behind a module-level flag so v1 can ship with them off. Stage 3 output is cached once per dev piece, so Stage 4 iterations take seconds and are deterministic on CPU. Every rule is fixed on dev data and only then run, once, on Tikong_Tiko as a regression check.

**Tech Stack:** Python, pytest, `D:/PiyaNota/.venv/Scripts/python.exe` (torch 2.3.0+cu121, CPU only: set `CUDA_VISIBLE_DEVICES=-1`, an empty value crashes ultralytics).

**Spec:** No separate design doc. The basis is the diagnosis below. Target branch: new branch `piya106/stage4-tie-bar-repair` created from `piya106/stroke-calibration` (worktree `D:/PiyaNota/.claude/worktrees/piya106-stage4-fixes`). This plan file lives in the `module3-backend` worktree and is copied to that branch at execution.

## Diagnosis (ml-cv-lead, 2026-11-04, Tikong_Tiko p01-p04, seed1/seed2 ranges)

- Event SER 20.3-21.6% (83-88 edits / 408 GT events). Pitch accuracy 97.3%, rests nearly perfect.
- **Missed ties ~30% of edits (~6.7 SER points).** The CRNN emits only `slur.end` between same-pitch notes. `_infer_ties_from_slurs` (`stage4_reconstruction.py:1309`) requires `slur.start` on the first note, so 15 / 14 adjacent same-pitch pairs stayed split. Merging same-pitch runs gives SER 14.9% / 14.6%.
- **Bar-sum scaling ~25-30%.** `_repair_by_run` (`:1103`) scales a whole same-duration run evenly. One over-counted slot becomes three substitutions. A beam-level misread (`beamedRight1` for `beamedRight2`, token confidence 0.28) also produces false `suspected_tuplet` bars (about 25 events with durations 80/90/100/111/112/180/200).
- CRNN pitch and extra or missing notes ~25%. Scorer artifact ~0.
- Event confidence: AUROC 0.70-0.75. Two thirds of wrong events are above 0.9. Use it to choose a repair, never to drop tokens.

## Global Constraints

- Do not tune any rule or threshold on Tikong_Tiko p01-p04: they are dev-contaminated after the diagnosis. A Tikong score after a fix is a regression check only.
- Report seed1 and seed2 as ranges; report strict SER and tie-agnostic SER together; never blend datasets.
- Run on CPU only (BUG-013): `CUDA_VISIBLE_DEVICES=-1`.
- Run pytest as `D:/PiyaNota/.venv/Scripts/python.exe -m pytest <path> -v` from the worktree root. In Bash use literal paths, no shell variables.
- PEP 8, type hints, named constants, Google docstrings explaining why, no silent `except` (CLAUDE.md). Commit messages `PIYA-106: <summary>`; the user approves commits.
- Event shape (existing): `type`, `pitch`, `duration_ticks`, `tick_onset`, `local_tick_onset`, `page_index`, `sys_idx`, `global_bar`, `slur` (`SLUR_START`/`SLUR_END`), `slur_end`, `confidence`, `symbol`, `note_id`, `tie_to_next`.

## Review Focus

- Two legitimately repeated same-pitch notes where the CRNN emits a stray `slur.end`: must not merge when a rest or barline-gap separates them; measure the false-merge rate on dev GT.
- A tie across a system or page break: must still merge exactly as today.
- Same pitch inside a chord or divisi onset group: a tie must not pair a note with a different voice's note.
- Two repair candidates with near-equal confidence: must not guess; fall back to the existing repair and flag.
- Underfull bars where the best candidate is a rest: must not stretch a rest silently.

---

### Task 0: Branch, dev set, Stage 3 cache and baseline

**Files:**
- Create: `tools/stage4_eval.py` (promoted from `C:/Users/paul_/.claude/jobs/f4582ada/tmp/scratch/score.py`), `tests/test_stage4_eval.py`
- Create outside repo: `C:/Users/paul_/.claude/jobs/f4582ada/tmp/s4dev/<piece>/stage3_all.json` (cache)

**Interfaces:**
- Produces: `score_events(pred: dict[str, list[dict]], gt_mxl: Path, usable_measures: set[int]) -> dict` returning per-voice and total `strict_ser`, `tie_agnostic_ser`, `pitch_acc`, scored bar by bar on `usable_measures` via Stage 4's `global_bar` (a page whose predicted bar count differs from the GT is reported as `unaligned` and excluded, with the count shown); `run_stage4_from_cache(cache: Path) -> tuple[dict, dict]` wrapping `reconstruct_satb_with_report`.

- [ ] **Step 1:** In a new worktree `D:/PiyaNota/.claude/worktrees/piya106-stage4-fixes` create branch `piya106/stage4-tie-bar-repair` from `piya106/stroke-calibration`.
- [ ] **Step 2:** Build the dev set from `D:/PiyaNota/data/chords_dataset/` (user, 2026-11-04): 11 pieces, each with a `.mscz` and `camera/` photos (Dont_Stop_Me_Now has `ground_truth/` and no `camera/`: skip it unless photos exist; Moonriver has a nested folder). Do not use `10piece_test_set` pieces. Many measures there contain chords or divisi, which v1 cannot represent, so filter:
  1. Export each `.mscz` to `.mxl` with `C:/PROGRA~1/MUSESC~1/bin/MuseScore4.exe -o <out>.mxl <in>.mscz` (the shell refuses the spaced path), into the scratch dir, not the data folder.
  2. Map each part to Soprano/Alto/Tenor/Bass (some pieces, e.g. Handog SSAATBBB, have more parts; keep only pieces with a clean open-score SATB mapping and say which were skipped and why).
  3. Mark a (voice, measure) as **usable** only if the part has at most one sounding note at any moment in that measure: no `<chord/>` elements and no second voice layer holding notes. Mark a measure usable for scoring only if all four voices are usable in it, so the Stage 4 bar sums stay comparable.
  4. Derive each camera page's measure range (compare photo to PDF; record in `dev_manifest.json` beside the cache: piece, page file, first and last measure, usable-measure list). Do not include pages with zero usable measures.
  5. Report how many usable measures and notes the filter keeps per piece. If fewer than about 3 pieces and 300 usable notes remain, stop and ask the user.
- [ ] **Step 3:** Write the failing test `test_score_events_merges_ties_for_tie_agnostic`: two C4 eighths vs one C4 quarter in GT gives `strict_ser > 0` and `tie_agnostic_ser == 0`. Run it, see it fail.
- [ ] **Step 4:** Implement `score_events` in `tools/stage4_eval.py`: event = (pitch or rest, duration ticks at 480/quarter), Levenshtein per page summed per voice, pitch accuracy on notes only. Test passes.
- [ ] **Step 5:** Run Stages 1-3 once per dev piece with both seeds (`phase2_seed1.pt`, `phase2_seed2.pt`, ClefKeyNet on), CPU, caching `stage3_all.json` outside the repo. Implement `run_stage4_from_cache`.
- [ ] **Step 6:** Record the baseline strict and tie-agnostic SER per dev piece and seed in `docs/decisions/piya-106-stage4-tie-bar-repair.md` (new file) with the seed range.

### Task 1: Ties from `slur.end` alone

**Files:**
- Modify: `stage4_reconstruction.py:1309` (`_infer_ties_from_slurs`), add constant `TIE_FROM_SLUR_END_ENABLED: bool = True`
- Test: `tests/test_stage4_ties.py`

**Interfaces:**
- Consumes: `_onset_groups`, `SLUR_END`, `SLUR_START`.
- Produces: events in `groups` with `tie_to_next=True` when the next onset group, in the same `(page_index, sys_idx)`, holds a note of the same pitch carrying `slur == SLUR_END` or `slur_end`, even if the first note has no `slur.start`.

- [ ] **Step 1:** Write failing tests in `tests/test_stage4_ties.py`: (a) `test_slur_end_only_merges_same_pitch_neighbours` (two C4 eighths, second has `slur=SLUR_END`, result one C4 quarter via `_resolve_ties`); (b) `test_rest_between_blocks_tie`; (c) `test_different_pitch_not_tied`; (d) `test_cross_system_tie_unchanged`; (e) `test_chord_group_ties_only_matching_pitch`; (f) `test_flag_off_keeps_old_behaviour` using monkeypatch of `TIE_FROM_SLUR_END_ENABLED=False`. Run, see failures.
- [ ] **Step 2:** Implement the rule in `_infer_ties_from_slurs` guarded by the flag, only for the immediately following onset group in the same strip; keep the existing `slur.start` path untouched.
- [ ] **Step 3:** Run `tests/test_stage4_ties.py` and the existing `tests/test_stage4_divisi.py`; all pass.
- [ ] **Step 4:** On the cached dev set, report SER before and after per piece and seed, plus the false-merge count (merged pairs with no tie in the GT MXL). Record in the decision doc. Accept only if strict SER does not rise on any dev piece.
- [ ] **Step 5:** Commit after user approval.

### Task 2: Single-token bar repair before run scaling

**Files:**
- Modify: `stage4_reconstruction.py:1210` (`_repair_overflow`) and the underfull handling called from `_place_voice_strip` (`:836`; read it first to find where `FLAG_BAR_UNDERFULL` is raised), add `BAR_SINGLE_TOKEN_REPAIR_ENABLED: bool = True`, `FLAG_BAR_SINGLE_TOKEN_REPAIRED = "bar_single_token_repaired"`, `SINGLE_TOKEN_CONFIDENCE_MARGIN: float` (named constant; value chosen on dev data, not Tikong)
- Test: `tests/test_stage4_bar_repair.py`

**Interfaces:**
- Produces: `_single_token_fix(m_events: list, first_local: int, bar_ticks: int) -> Optional[tuple[Event, int]]` returning the event to change and its new `duration_ticks`, or `None`. Candidates are note events whose `symbol` contains `beamed` whose duration halved or doubled makes the bar sum equal `bar_ticks`; pick the lowest `confidence`; return `None` if no candidate, if the two lowest confidences differ by less than `SINGLE_TOKEN_CONFIDENCE_MARGIN`, or if any note lacks a usable confidence (`_has_confidence`).

- [ ] **Step 1:** Write failing tests: (a) `test_overflow_fixed_by_halving_lowest_confidence_beamed_note` (a 2/4 bar of ticks 240+240+240+240 where one beamed 240 should be 120... assert only that note changes and the bar sums to 960); (b) `test_tied_confidence_falls_back_to_run_scaling` (equal confidences keep the old `bar_overflow_run_scaled` result); (c) `test_underfull_bar_fixed_by_doubling`; (d) `test_rest_never_stretched`; (e) `test_no_false_tuplet_when_single_fix_exists` (previously `suspected_tuplet`, now `bar_single_token_repaired`); (f) `test_flag_off_keeps_old_behaviour`. Run, see failures.
- [ ] **Step 2:** Implement `_single_token_fix`; call it first in `_repair_overflow` and in the underfull path when the flag is on. On success apply the new duration, shift later onsets in the bar, append a flag with `review_needed: True`, `action` recording the change, and return before `_repair_by_run`.
- [ ] **Step 3:** Run `tests/test_stage4_bar_repair.py` and `tests/test_stage4_divisi.py`; all pass.
- [ ] **Step 4:** On the cached dev set report SER before and after, the count of `bar_single_token_repaired` flags, and how many of them were correct against GT. Choose `SINGLE_TOKEN_CONFIDENCE_MARGIN` here. Record in the decision doc. Accept only if strict SER does not rise on any dev piece.
- [ ] **Step 5:** Commit after user approval.

### Task 3: Surface new flags to the review output

**Files:**
- Modify: `stage4_reconstruction.py` (`_report`, `reconstruct_satb_with_report` flag aggregation), `stage5_synthesis.py` if the `review` payload is built there
- Test: `tests/test_review_api.py`

**Interfaces:**
- Consumes: the flag dicts from Task 2 (`kind`, `voice`, `bar`, `page_index`, `review_needed`).
- Produces: `bar_single_token_repaired` and tie merges inferred from `slur.end` appear in the `review` items with `reasons` including their `kind`, so the app's review list shows them.

- [ ] **Step 1:** Add a failing test in `tests/test_review_api.py` asserting a `bar_single_token_repaired` flag yields a review item with that reason.
- [ ] **Step 2:** Implement the mapping next to the existing flag handling; test passes along with the rest of `tests/test_review_api.py`.
- [ ] **Step 3:** Commit after user approval.

### Task 4: Mid-system key change (investigation only)

**Files:**
- Create: `docs/decisions/piya-106-key-change-investigation.md`

- [ ] **Step 1:** On the cached dev set, count bars where the GT key changes mid-system and Stage 3 misses it, and the number of pitch errors that causes. Record the numbers. Only if it explains more than a few percent of dev pitch errors, write a separate plan; otherwise close it as low priority (ml-cv-lead: small pitch gain). Bug IDs BUG-027 and BUG-029 stay open.

### Task 5: Validation, regression check and hand-off to the backend branch

**Files:**
- Modify: `docs/decisions/piya-106-stage4-tie-bar-repair.md`

- [ ] **Step 1:** Run the full dev set, both seeds, flags on vs off; record strict and tie-agnostic SER ranges per piece.
- [ ] **Step 2:** Run the existing Stage 4 tests plus a no-regression run on Camera-PrIMuS samples and on pieces with legitimately repeated same-pitch notes; record the false-merge count.
- [ ] **Step 3:** Run Tikong_Tiko p01-p04 once as a regression check only, label it dev-contaminated, and record seed1/seed2.
- [ ] **Step 4:** Ask the user for one fresh piece (never used in any run) for a single blind pass; run it once and report it as the only held-out number.
- [ ] **Step 5:** Ask ml-cv-lead to review the decision doc before any merge, then senior-reviewer before merge proposal (CLAUDE.md). After approval, copy `stage4_reconstruction.py` (and `stage5_synthesis.py` if changed) into the `module3-backend` worktree with `git checkout piya106/stage4-tie-bar-repair -- <files>`.

---

## Self-review

- Spec coverage: ties (Task 1), bar repair and tuplet suppression (Task 2), review flags (Task 3), key change (Task 4), validation without leakage (Tasks 0 and 5). Beam search, TTA, BUG-016 preprocessing and retraining are deliberately out of scope for v1 (ml-cv-lead ranked them 6-8).
- The underfull call site in `_place_voice_strip` and `SINGLE_TOKEN_CONFIDENCE_MARGIN` are not pinned here because they need reading and dev data respectively; both are called out in Task 2.
- Not checked: whether enough dev pieces have ground truth (Task 0 step 2 is the gate).
