# Unreadable voices, client review filter, meter fix, bar-step timing, app prompts: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A score with some unreadable voices still plays and tells the user which voice and page; the app review object carries voice flags only; mid-strip meter changes are applied; the timing file carries bar positions; the app shows the general notice, the voice prompt and a bar-step playback line.

**Architecture:** Pipeline changes (Stage 3/4/5, repo root) are copied into the backend in the same commit set they already live in (the backend imports the repo-root stage modules). The adapter `backend/worker/pipeline.py` reads `report["failed_voices"]` instead of inferring from missing MP3s. The client `review` object is built only in `stage5_synthesis.build_review`; the app reads it through `lib/models/score_result.dart`.

**Tech Stack:** Python 3.12, Flask, psycopg, pytest (`backend/.venv/Scripts/python -m pytest backend/tests -q -W error`; pipeline tests with system `python`), Flutter/Riverpod (`flutter analyze`, `flutter test` from `mobile/piyanota_application/`).

**Spec:** `.superpowers/sdd/2026-11-04-conversion-worker-backend/handoff-latest.md` (CURRENT state, user decisions), `docs/decisions/backend-bar-step-timing.md`, `docs/decisions/app-bar-step-playback-line.md`, `docs/decisions/moonriver-diagnostic-accuracy-2026-11-04.md`, `docs/decisions/moonriver-time-signature-trace-2026-11-04.md`.

## Global Constraints

- Branch `feature/module3-backend`, worktree `D:/PiyaNota/.claude/worktrees/module3-backend`. Never push or merge without asking the user.
- Commit prefix `PIYA-300` (backend, app) or `PIYA-106` (pipeline); commits by pathspec; end with the two attribution lines (Co-Authored-By Claude Sonnet 5.5, Claude-Session). No Claude attribution beyond those.
- CPU only: `CUDA_VISIBLE_DEVICES=-1`. Git Bash, literal paths, no `git -C`.
- Moonriver is dev data: diagnostic only, never reported as accuracy. Hand-authored ground truth is diagnostic only. `piyanota_dataset` photos are TEST-only: no threshold tuning on them.
- The client `review` object carries ONLY voice flags (`voice_unreadable`, voice dropped). Meter, clef/key and tenor-range flags stay internal.
- General notice text, verbatim: "PiyaNota's conversion is not fully accurate yet. Please review the playback against your score before relying on it."
- Voice prompt text, verbatim pattern: "Voice <name> could not be read. Do you want to continue with playback anyway? It is recommended to retake a clearer picture of page <n> of the score to be more sure of the output", with choices continue or retake.
- Meter resolution per bar: explicit token for that bar or header, then previous meter (across system breaks), then bar-total inference (three quarters = 3/4, beat = quarter, flag the guess internally), then 4/4. Three-voice quorum stays before a mid-strip change is applied. `mid_strip_meter_change` stays an internal flag and never sets client `review_needed`.
- Stage 4 `failed_voices` port source: PIYA-108 `ea575f9` (different base; port by hand, do not cherry-pick blindly).
- Bars and events succeed or fail together in the timing file; `build_timing` never raises; the fallback is exactly `{"events": []}`.

## Review Focus

- All four voices empty: job fails with a retake message, no partial score row.
- A voice empty on every page: prompt names the voice and lists all pages, not an empty page list.
- One voice short on one page only (staff-count short): page list names only that page; other voices unaffected, their ticks stay aligned (empty voice padded to same length, no shift).
- Old stored timing rows without bar fields, and `{"events": []}`: nothing crashes, app falls back to per-event highlight or no line.
- Meter: a stray lone digit in 2 of 4 voices (p4 noise case) must not change meter; a 3-voice 3/4 reading must; a piece with no meter change must be byte-identical to before.
- Bar `x` scaled to the served page (a missed `bars` loop in `_scale_to_served_pages` puts the line at ~53 percent of the correct x).

---

### Task 1: Unreadable voices become a partial success

**Files:**
- Modify: `stage4_reconstruction.py` (`reconstruct_satb_with_report`, per-voice steps), `stage5_synthesis.py` (`synthesize_satb` pads empty voices, `build_review`), `backend/worker/pipeline.py:251-279`
- Test: `tests/test_meter_and_muting.py` or a new `tests/test_failed_voices.py`; `backend/tests/test_worker_pipeline.py`

**Interfaces:**
- Consumes: PIYA-108 `ea575f9` (`git show ea575f9 -- stage4_reconstruction.py`) as the reference behaviour.
- Produces: `reconstruct_satb_with_report(events) -> (satb, report)` where `satb[voice] == []` for an empty voice, `report["failed_voices"]: list[str]` (capitalised voice names), a flag `{"kind": "voice_unreadable", "voice": str, "pages": list[int], "review_needed": True}` with `pages` 1-based, listing pages where the voice has no events but another voice does (all pages when the voice is empty everywhere). `ValueError` only when all four are empty. `PipelineResult.failed_voices` (lowercase) now comes from `report["failed_voices"]`; `failed_voice_causes[v] == FAILED_VOICE_CAUSE`.

- [ ] **Step 1: Write failing tests**: `test_one_empty_voice_returns_partial` (3 voices events, Tenor `[]`: `satb["Tenor"] == []`, `report["failed_voices"] == ["Tenor"]`, flag pages equal all pages seen), `test_voice_missing_on_one_page_only_names_that_page`, `test_all_four_empty_raises_value_error`, `test_unreadable_voice_does_not_shift_other_voices_ticks`, adapter test `test_failed_voices_from_report_job_succeeds` (fake stages; `mp3` has 3 voices, `failed_voices == ["tenor"]`, review item code `voice_unreadable` names `tenor` and pages), adapter test `test_all_empty_fails_with_retake_message` (`PipelineError` reason contains "retake").
- [ ] **Step 2: Run them; expect FAIL.** `python -m pytest tests/test_failed_voices.py backend/tests/test_worker_pipeline.py -q`
- [ ] **Step 3: Port by hand** the `ea575f9` empty-voice handling into `stage4_reconstruction.py`; guard each later per-voice step on an empty list; add `pages` to the flag from the input events' `page_index`.
- [ ] **Step 4: `stage5_synthesis.synthesize_satb`** pads an empty voice to the common length (silent MP3, not a missing file) so the app still gets four tracks; `build_review` keeps `voice_unreadable` items (Task 2 filters everything else).
- [ ] **Step 5: Adapter** `run_pipeline`: stop inferring `failed` from missing MP3s; use `report["failed_voices"]`; map the all-empty `ValueError` to `PipelineError("no readable staves, please retake clearer photos of your pages")`. The review object must reach the client with the voice name and pages (existing `completion.py` already stores `failed_voices`; check `routes_scores.py:103` exposes the review items unchanged).
- [ ] **Step 6: Run** tests from step 2 plus the full backend suite; expect PASS.
- [ ] **Step 7: Review** with `choral-conductor` (is padding with silence the right thing for a missing voice?) and `backend-lead` (Module 3 contract). Commit `PIYA-106: port unreadable-voice handling (PIYA-108 ea575f9)` for pipeline files and `PIYA-300: ...` for adapter files.

### Task 2: Client review filter

**Files:**
- Modify: `stage5_synthesis.py:288-336` (`build_review`)
- Test: `tests/test_stage5_review.py` (create if absent) and `backend/tests/test_worker_pipeline.py`

**Interfaces:**
- Consumes: Task 1's `voice_unreadable` flag.
- Produces: `CLIENT_REVIEW_CODES: frozenset[str] = frozenset({"voice_unreadable", "voice_dropped"})` (check the real Stage 4 dropped-voice code name first). `build_review(stage3_events, stage4_flags) -> (review, full_items)`: `review` items and `reasons` contain only `CLIENT_REVIEW_CODES`; `full_items` keeps everything for the job record and logs.

- [ ] **Step 1: Failing tests**: `test_client_review_only_voice_codes` (events carrying `clef_key_unvalidated`, `tenor_range_suspect`, `mid_strip_meter_change` plus a `voice_unreadable` Stage 4 flag: `review["reasons"] == ["voice_unreadable"]`, `reviewNeeded` True), `test_no_voice_flags_means_review_not_needed` (only internal flags: `reviewNeeded` False, `items == []`), `test_full_items_keep_internal_flags`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the filter in `build_review`; update its docstring (why: the user can only act on missing or unreadable voices).
- [ ] **Step 4: Run** tests and the full backend suite; expect PASS. Check `grep -rn "clef_key_unvalidated\|reviewNeeded" backend/ mobile/` for tests asserting the old client contract and update them.
- [ ] **Step 5: Commit** `PIYA-106: client review carries voice flags only`.

### Task 3: Apply mid-strip meter changes

**Files:**
- Modify: `stage3_transcription.py:1738-1745` (R3 branch), `:2854-2900` (`decide_mid_changes`), `stage4_reconstruction.py:336-356` (`_consensus_time_signatures`), plus the matching copies in the repo root used by the backend
- Create: `docs/decisions/piya-106-meter-change-applied.md`, `training/meter_ablation.py` (dev-set ablation, flags off vs on)
- Test: `tests/test_meter_apply.py`

**Interfaces:**
- Produces: `resolve_bar_meter(explicit: str | None, previous: str | None, bar_total_ticks: list[int]) -> tuple[str, str]` returning (meter, source) with source in `{"explicit", "carried", "inferred", "default"}`; `inferred` fires when at least 3 measures or a clear majority share a total (3 quarters maps to 3/4). Constant `APPLY_MID_METER_CHANGE: bool = True` so the ablation can switch it off.

- [ ] **Step 1: Investigate first (no code).** Read the R3 rationale in `stage3_transcription.py` (comments at :1215, :1308, :1738-1745, :2512, :2880) and `git log -S"R3" --oneline -- stage3_transcription.py`. Dispatch `ml-cv-lead` to confirm why changes were reported only ("re-timing on a misread meter would shift bars") and what the apply path risks. Write the finding in the decision doc. Stop and tell the user if the reason makes applying unsafe.
- [ ] **Step 2: Failing tests**: `test_three_voices_agree_3_4_applied` (bars after the change laid out at 3/4, `bar_underfull` flags drop to zero on a synthetic 4/4 then 3/4 piece), `test_two_voices_stray_digit_not_applied` (quorum not met, meter unchanged), `test_explicit_token_beats_inference`, `test_carry_forward_across_system_break`, `test_inferred_three_quarters_is_3_4_flagged_internally`, `test_default_4_4_last_resort`, `test_no_change_piece_unchanged` (output equal with the flag on and off), `test_mid_strip_meter_change_flag_not_client_review` (stays internal).
- [ ] **Step 3: Run; expect FAIL.**
- [ ] **Step 4: Implement** apply-on-quorum in Stage 3, per-bar meter in Stage 4 consensus (a "4/4" reading is real evidence when it follows a change), and `resolve_bar_meter`. Keep `mid_strip_meter_change` as an internal flag.
- [ ] **Step 5: Ablation (dev data only).** Run `training/meter_ablation.py` over the dev set with `APPLY_MID_METER_CHANGE` False then True; report per piece pitch/rhythm change, `bar_underfull` count and total ticks. Also rerun the Moonriver diagnostic (`backend/scripts/moonriver_diag_eval.py`); expected: 3/4 bars read as 3/4, audio length near 58,560 ticks, label as diagnostic.
- [ ] **Step 6: Reviews:** `ml-cv-lead` on ablation design and leakage (no tuning on TEST photos), `choral-conductor` on the 3/4-vs-6/8 rule and carry-forward across systems. Fix findings.
- [ ] **Step 7: Run** full pipeline tests and the backend suite; copy the changed stage files into the backend tree as Task 5 did. Commit `PIYA-106: apply quorum mid-strip meter change`.

### Task 4: Bar-step timing fields in the backend

**Files:**
- Modify: `timing_export.py` (`_build`), `backend/worker/main.py` (`_scale_to_served_pages`), `backend/scripts/smoke_convert.py`
- Test: `backend/tests/test_timing_export.py` (create), `backend/tests/test_worker_main.py`

**Interfaces:**
- Produces: each `bars[]` entry gains `pageIndex: int` (0-based), `systemIndex: int`, `x: float` (1 decimal, page px), `systemTopY: float`, `systemBottomY: float`, `pickup: bool` (true only for bar 0 with `pickup_ticks > 0`). Existing keys and all `events` entries unchanged. `_scale_to_served_pages` scales `x`, `systemTopY`, `systemBottomY` on `events + bars`.

- [ ] **Step 1: Failing tests** exactly as listed in `docs/decisions/backend-bar-step-timing.md` under "Tests" (items 1 to 8: scale test with x 100 to 187.5, top 160 to 240, bottom 240 to 360; new fields and sort order; pickup entry; x semantics; second system; missing last barline; barline count off by two returns exactly `{"events": []}`; compatibility of pre-existing keys).
- [ ] **Step 2: Run; expect FAIL.** `backend/.venv/Scripts/python -m pytest backend/tests/test_timing_export.py backend/tests/test_worker_main.py -q -W error`
- [ ] **Step 3: Implement** in `_build` per the spec: build `out_bars` inside the per-system loop (zip `sys_bars` with `edges`), keep the final sort by `startTick` then `pageIndex`; add the comment on what `x` means for first bars of a system.
- [ ] **Step 4: Implement** the `_scale_to_served_pages` loop over `timing.get("events", []) + timing.get("bars", [])`.
- [ ] **Step 5: Extend** `smoke_convert.py`: every bar has finite `x` inside the served page width; `x` increasing within a (`pageIndex`, `systemIndex`).
- [ ] **Step 6: Run** the focused tests and full suite; then re-run the smoke on Moonriver p01-p04 (dev data, expect 40 bars, plausible x). Update the spec doc's status line. Commit `PIYA-300: bar position fields in the timing file`. Review with `backend-lead` (contract consumed by Module 2).

### Task 5: App changes (frontend-lead)

**Files:**
- Modify: `mobile/piyanota_application/lib/models/score_result.dart` (review items), `lib/models/measure_table.dart` (`BarInfo.tryParse` optional `x`, `pageIndex`, `systemIndex`, `systemTopY`, `systemBottomY`), `lib/models/score_timeline.dart` (`_BarStep`, `kBarStepLine = true`, `positionAt`), `lib/state/playback_providers.dart:604-621` (pass `file.bars`), `lib/screens/playback/playback_screen.dart` and `playback_messages.dart` (notice and prompt), `lib/services/demo/playback_demo.dart` (`barsJson()`)
- Test: `test/playback/score_timeline_test.dart`, `test/playback/playback_screen_test.dart`, a new model test for `BarInfo`

**Interfaces:**
- Consumes: Task 4 bar fields; Task 1/2 review items `{code: "voice_unreadable", voice, pageIndex...}` (item shape from `build_review`; page numbers 1-based in the Task 1 flag, convert in the app copy only).
- Produces: dismissible general notice once per result screen visit; voice prompt with continue or retake page N; `ScoreTimeline.positionAt` returns the bar step with no slide when `kBarStepLine`, using bar `x` when present and the derived downbeat x otherwise.

- [ ] **Step 1: Delegate to `frontend-lead`** with the three spec docs and the verbatim texts from Global Constraints; it writes widget tests first, from the "Tests to add" list in `docs/decisions/app-bar-step-playback-line.md` plus: notice shows once and is dismissible; prompt names voice and page and offers both choices; a result with no review items shows no prompt; old timing rows without bar fields use the per-event path.
- [ ] **Step 2: Run** `flutter analyze` and `flutter test` from `mobile/piyanota_application/`; both clean. Update existing slide tests, do not delete them.
- [ ] **Step 3: Retake action** routes to the existing per-page resubmit flow if present; if PIYA-116 still 404s, ask the user before inventing an endpoint (flag, do not guess).
- [ ] **Step 4: Commit** `PIYA-300: app notice, voice prompt and bar-step playback line`. `frontend-lead` reviews before merge (required by CLAUDE.md).

### Task 6: Final whole-branch review and merge question

- [ ] **Step 1:** Run `scripts/review-package` with this plan path, `git merge-base main HEAD`, and HEAD; point `senior-reviewer` at the ledger deferred minors and parked lines.
- [ ] **Step 2:** One fix dispatch if needed, one scoped re-review.
- [ ] **Step 3:** Run the full backend suite with `-W error`, pipeline tests, and `flutter analyze` plus `flutter test`.
- [ ] **Step 4:** Collect every `Ruling:` line from `progress.md` into the final message and ask the user whether to merge. Do not push or merge.
