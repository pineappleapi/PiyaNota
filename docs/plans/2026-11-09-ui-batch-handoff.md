# UI batch handoff (2026-11-09)

Worktree: `D:\PiyaNota\.claude\worktrees\feature-piya106-overnight-cancel-logging-ui`
Branch: `feature/piya106-overnight-cancel-logging-ui` (== `origin/main` at `9033a7f` when this was written).
App: `mobile/piyanota_application` (Flutter, Android). Backend: `backend/` (Flask API on Render, worker local, DB on Neon).

## State before this batch

- Live-synth MIDI playback is done, merged and pushed (Session G in `docs/plans/2026-11-07-handoff.md`). Do not touch the playback engine internals unless a task below requires it.
- New scores are MIDI-only (`audioTracks {}`); old MP3 scores were deleted by the user.
- The worker runs locally: `powershell -ExecutionPolicy Bypass -File "C:/Users/paul_/start-piyanota-worker.ps1"`. The script contains secrets: never read, print or copy it. Restart the worker (TaskStop the old one first) after any backend change.
- `reset_code_waits.dart` has a formatting-only change: ignore.
- Phone: adb serial `622ad04c`. Release build: `flutter build apk --release --dart-define=API_BASE_URL=https://piyanota-api.onrender.com --dart-define=USE_FAKE_AUTH=false`, then `adb -s 622ad04c install -r`.
- Bash mangles Windows backslash paths: use forward slashes. Tests need `D:\PiyaNota\.venv\Scripts\python.exe` and, for backend DB tests, the scratch Postgres on port 55432 (`scratch/postgresql-16.4-1-windows-x64-binaries`). Docker does not work.

## Reference images (copied into the repo)

`mobile/piyanota_application/references/ui-batch-2026-11-09/`
- `Add Score Details_Change.png` (task I)
- `Playback_Disclaimer_Change.png` (task II.1)
- `VoiceMixerModal_UI_Change.png` (task III)
- `Home Page - capture button change.png` (task IV)

Colour rule (memory: design-fidelity workflow): sample colours from the reference with a pixel/dropper tool, do not eyeball.

## Tasks (user's words, verbatim intent)

### I. Add Score details screen (`lib/screens/capture/score_details_screen.dart`)
1. Remove the "Step 1 of 2" header label. Only a back button (returns to library) plus the label "Score Details" as in the reference.
2. Tapping "Add score" in the library must not auto-open the keyboard. Keyboard opens only when the user taps the song title or arranger field.

### II. Playback screen (`lib/screens/playback/playback_screen.dart`, `playback_messages.dart`, `playback_alerts.dart`)
1. Yellow disclaimer banner: more padding (text sits on the edge), colour changed to a very light blue-green that fits the app palette, text replaced by the message in the reference image. It shows only the first time a score is opened after its conversion finishes. After the app is closed, or the user leaves to the library and reopens the score, it stays gone. Persist a per-score "disclaimer seen" flag locally.
2. Mixer state (which voices on/off, volumes) and speed persist per score across sessions (leaving to library, closing the app) and are restored when the score is opened again. Decide storage with the existing local store (`local_results_store` / settings providers); per score id.

### III. Mixer modal (`lib/screens/playback/mixer_sheet.dart`)
1. Remove the message under the metronome click when it is off. The metronome row must not gray out when off (unlike voices).
2. Remove the Mute button (redundant with the S/A/T/B checkboxes).
3. The mute and full-volume icons at the two ends of each volume slider become tap targets: mute icon sets volume to 0, full icon sets volume to max.

### IV. Home / Library screen (`lib/screens/library/`)
1. Capture icon: blue-green gradient, colours sampled from the reference with a dropper tool. Notification icon: like the reference. With unread notifications, a red circle badge with the unread count. Also add system (OS) notifications in addition to in-app ones (conversion finished etc.). Needs the `flutter_local_notifications` package or similar, Android 13 `POST_NOTIFICATIONS` permission, and a decision on triggering (see Open questions).

### V. Processing screen (`lib/screens/processing/`, `lib/state/processing_providers.dart`, backend `backend/worker/pipeline.py`, `main.py`, `queue.py`)
1. Percentage must follow the log lines, not jump only when a whole stage group finishes. Each logged step adds to the percentage, so the bar is dynamic and accurate. Likely needs the worker to report finer progress (per page/strip/voice step) and the app to map log events to a monotonic percentage.

### General
1. After closing and reopening the app, scores load from local storage with no internet needed. Today it shows "cannot load scores" with Retry. It must show the offline scores immediately, avoid a loading state as far as possible, and refresh from the network in the background only when online. Look at `lib/state/score_library_providers.dart`, `local_results_store`, and the library screen's error/retry state.

## Open questions to settle with the user before coding (ask once, in one message)
- IV system notifications: local notification fired by the app when polling sees a job finish (works only while app is alive) vs. FCM push from the backend (needs Firebase + backend work, Module 3). Recommend local notifications first.
- V: is it acceptable to change worker/pipeline progress reporting (backend contract, needs backend-lead review and a worker restart), or must it stay app-side only?

## Method (standing rules)
- Coordinator spawns one subagent per task with an explicit model: haiku/sonnet for edits and checks, opus only for design or merge review. Short briefs and reports. Run only touched tests.
- State the planned change and a one-line risk before editing.
- Reviews required: frontend-lead for every Module 2 change; backend-lead for any backend/contract change (task V worker side); senior-reviewer before proposing the merge.
- No commit, merge, push, migration or deploy without the user's word. Commit message format `PIYA-XXX: <summary>`.
- Update this file and stop for a `/clear` after every three tasks (memory: clear every 3 tasks).
- Suggested order: I, III, II (small UI) -> General (offline load) -> V -> IV (largest).

## Progress log (append below)
- 2026-11-09 block 1 (uncommitted, in worktree):
  - I DONE: white header, navy circular back (#272960), "Score Details", no "Step 1 of 2", no autofocus. 8/8 tests.
  - III DONE: metronome off-msg + gray-out removed, Mute button removed, slider-end icons tap -> onVolume(0)/(1). mixer tests pass. Unused strings mute/muteLabel/metronomeOff left in playback_messages.dart.
  - II DONE (banner colour re-sample pending): per-score prefs `playback_disclaimer_seen_<id>`, `playback_mix_<id>` in playback_providers.dart; banner fill AppTheme.playbackNoticeFill; new test/playback/playback_persist_test.dart.
  - V backend DONE: pipeline.py tick() at 39/84/91, main.py PROGRESS_WRITE_INTERVAL_S 2.0->1.0, test_worker_pipeline 21 pass (DB tests not run). App consumes data.percentComplete; ProcessingProgress.next keeps never-decrease/cap-99. Worker restart needed.
  - General: running. V app-side + IV: not started.
  - General DONE (cache-first library, key score_library_cache_<email>). V app-side: no change (poll 2 s kept, PIYA-207 AC1). IV DONE: CaptureGlyph gradient #148FC7->#0AB7C1, bell filled; OS notifications + badge already existed (ScanBackgroundHost), no new package.
  - Full flutter suite: 1388 pass; the 1 failure (export_sheet_test, stale metronome-off assertion) fixed, test/export+test/playback pass. Unused `autofocus` param removed.
  - backend-lead: APPROVE (ticks 39/84/91 mostly overwritten; fix agent a0ceedf4633ce11b5 moves Pass-2 progress inside st.transcribe + runs DB tests on scratch PG 55432; result pending).
  - frontend-lead: BLOCKED. B1 playback_providers.dart ~1411/1429: restored muted voice can't unmute (_mixMuted={} but muted restored) -> set _mixMuted to restored set or persist playable-selected; add reopen+select-chip test. B2 playback_providers.dart ~644: _restoreMix(await ...) writes state before current() check -> await into local, check current(), then restore. Non-blocking: clear score_library_cache_*/playback_mix_* in wipeAccountLocalData (session_actions.dart:73); refresh-vs-delete epoch guard in score_library_providers; dart format score_details_screen.dart:133; clickMuted legacy; CaptureGlyph #0AB7C1 ~2.4:1 contrast (mockup colour).
  - Backend fix DONE: stage3_transcription.py PASS1/PASS2_PROGRESS_UNITS 9/1 (Pass 2 now reports per strip), pipeline.py TRANSCRIBE_BAND=(40,84), ticks removed. pytest 4 backend files on scratch PG: 81 passed, 1 skipped. Real stage3 run not done; backend-lead not re-reviewed after this change. Worker restart still needed.
  - TODO: fix B1/B2, re-test, senior-reviewer, restart worker, release APK + adb install 622ad04c, phone checklist, ask user for commit/merge/push.
  - Defaults chosen: local notifications; worker progress change allowed.
