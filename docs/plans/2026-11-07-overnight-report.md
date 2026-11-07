# Overnight report, 2026-11-07

Branch: `feature/piya106-overnight-cancel-logging-ui` (from local main fe45105). Not merged, not touching main.

## Done per item
- **A, worker cancel fix** (8205ffb): `write_progress` raises `_Cancelled` when `set_progress` reports the job left the working statuses; `make_progress_writer` re-raises it. Test: `test_cancel_noticed_at_progress_write_stops_pipeline_and_logs`.
- **J, logging** (659960a): `log_event` helper (adds `ms=`); `req` line gains `user_id`/`score_id`/`job_id`; events for signup, login ok/fail (reason code), reset requested/verified/confirmed, account delete (`purged_keys`), score create (`pages`, `in_bytes`), job cancel, score edit/delete; worker `queue_wait_s` and `end_to_end_s`. No emails, passwords, tokens or codes logged (test asserts it). `purge_user` now returns the key count.
- **H/I, mobile** (4523577 + format commit): `AppTheme.snackBarDuration` = 10 s on all 8 SnackBar sites; scan toast 10 s; "Conversion cancelled." text; `maxTempo` 180 and new `maxRenderedTempo` 240 (equals backend `MAX_TEMPO_BPM`) for server-reported tempo; slider and picker clamp. New `test/snack_bar_duration_test.dart` (includes source scan guard).

## Tests
- Worker tests 22 pass; `test_app_basics` 32 pass; full backend suite 421 passed, 2 skipped (local Postgres only).
- Flutter: `flutter analyze` on lib/screens, lib/theme, lib/models and the new test: no issues. `flutter test` on snack_bar_duration, playback, settings: 447 passed. Full Flutter suite not run.
- Not run: device check.

## Open reviewer findings (backend-lead, frontend-lead, senior-reviewer: all say merge, no blockers)
- MEDIUM: score rendered at 181-240 BPM: slider thumb shows 180, label/`chosenBpm` real tempo (BUG-055). Retake seeded above 180 saves 180.
- MEDIUM: non-floating snackbars now stay 10 s over bottom controls, no close action. Check on phone.
- LOW: cancel during `detecting_staff` noticed late (BUG-054); transient DB error on a progress write swallows the cancel until next write.
- LOW: `queue_wait_s` on a requeued attempt includes the earlier run; worker/DB clock skew.
- LOW: `log_event` needs a request context; runs after commit.
- LOW: no test for a single cancel snackbar; "Conversion cancelled" vs "Cancel scan" wording; source-scan test brittle on parens in strings.
- Nit: `import logging` placement in routes_account.py; stub in test_account_delete.py typed `-> None`.

## Assumptions
- Tempo cap 180 applies to the UI only; server still accepts 240.
- Cancel snackbar text reused from `scanCancelled`; scan toast stays silent on cancel.
- Bugs added: BUG-053 (fixed), BUG-054, BUG-055.

## Ledger (decisions this session)
1. Cancel detection lives in the progress write, not a new poll.
2. Logs carry integer ids only, via `request.view_args`.
3. `SnackBarThemeData` has no duration, so duration is per SnackBar, guarded by a scan test.
4. Two tempo constants: UI cap vs rendered range.
5. Postgres 16 portable at `C:/Users/paul_/.claude/jobs/d91e6d9e/tmp/pgdl`, port 55432; backend venv at `C:/Users/paul_/.claude/jobs/23b15561/tmp/bev`.

## Merge
```
git checkout main
git merge --no-ff feature/piya106-overnight-cancel-logging-ui
```
(Review first; you decide.)

## You must do
1. Restart the PC worker from this branch.
2. Cancel a job mid-run; check the worker log for `job cancelled`.
3. Phone-check snackbar placement and the speed sheet at a 181-240 BPM score.
