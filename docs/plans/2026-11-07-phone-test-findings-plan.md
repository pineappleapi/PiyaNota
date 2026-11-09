# Plan: phone-test findings, recommendations and logging (2026-11-07, revised)

Source: the user's real-backend phone test of app 1.2.0 against Render (`main` at `a829724`) with the PC worker,
plus two read-only backend-lead reviews. The second review read `mobile/`; its facts are marked VERIFIED below with
file:line (paths relative to `mobile/piyanota_application`, written `M/`). Status: plan only, nothing implemented.
Failures found here must also be logged in `docs/bug-tracker.md` (phase: dev-sprint).

## 0. Decisions recorded from the user (2026-11-07)

- Playback stays **per-voice and mixable**: the mixer is a product purpose, so a single premixed track is NOT
  acceptable as the playback path. (A premixed file may still be considered for export only.)
- **Phone-side Stage 5 (MIDI to audio on the phone) is wanted**, if it makes the user's experience faster and removes
  the chopping. It is a separate work session; see section 6, which is written to keep token use low.
- **Offline delete removes the local files immediately.**
- "Test 20" is dropped. It was a stray line copied from an old checklist file, not a real test.
- Nothing here is to be committed or merged without the user's explicit approval.

## 1. What passed (no work)

Login ladder (F2), password reset by Brevo email (F3), delete account (F9), progress rises and stays at 99 or below
(F13), 20-score limit and 409 dialog (F15), capture and gallery retake, stacked-page playback, auto-scroll, seek and
+/-5 s, chip and mixer sync, mute, metronome switch, offline playback of an already-opened score, splash, library
icons, settings header and picker, blank offline thumbnails (expected, deferred).

## 2. Findings, ranked

| # | Finding | Severity | Owner | Pre-merge |
|---|---------|----------|-------|-----------|
| A | Cancel: server marks the job cancelled but nothing tells the running worker; it keeps working | High | backend (worker) | Yes |
| B | Offline: library list is never cached; edit and delete need the network; no sync queue | High (UX) | frontend, small backend | Own branch |
| C | Playback chops with 4 voices; click lags at high tempo (5 separate players kept in step by seeks) | High | frontend, then phone-side synth | Diagnose, then section 6 |
| D | Playback page images have lyrics blanked | Medium | pipeline | After review |
| E | Piano has too much trailing reverb; wants a MuseScore-like sound | Medium | pipeline | After review |
| F | Offline copies: cause of "lost on close" not found in the code | Medium | frontend | With B |
| G | Export progress jumps about 30% to 100%; cause not found | Low | frontend, Android | No |
| H | Floating messages should auto-dismiss after 10 s | Low | frontend | Yes (tiny) |
| I | Metronome max tempo to 180 (today 240) | Low | frontend | Yes (tiny) |
| J | Logging: per-action durations | Low risk | backend | Yes |
| K | `.mid` files never used on the phone | Confirmed | frontend | Part of section 6 |

## 3. Item plans

### A. Cancel does not stop the worker

VERIFIED (app): cancel in the app (`M/lib/state/processing_providers.dart:562-583`) calls the cancel API, then
forgets the job (stops polling, removes the local card and bell entry) and refreshes the library. A missing card and
no notification are by design (`M/lib/widgets/scan_toast_host.dart:28-29,120`; scan-cancel snackbar text exists at
`score_library_screen.dart:133`). The app never shows a completed result for a cancelled job.

VERIFIED (backend, reading the code): `cancel_job` (`backend/routes_jobs.py:470`) only runs
`UPDATE jobs SET status='cancelled'`. The server then refuses to deliver a result: `backend/completion.py:79` returns
`None`, `_publish` raises `_Cancelled` (`backend/worker/main.py:194`), the uploads are discarded.

So what you saw is most likely this: the worker kept running (wasted work, and its console still printed the Stage 5
output list), then discarded the result. It did not deliver the file. To confirm, in the worker log find
`job cancelled job_id=…` after the pipeline finished. If instead a result really reached the phone for a cancelled
job, that is a separate and more serious bug and takes priority.

Fix (about 4 lines plus a test):
1. `write_progress` (`backend/worker/main.py:241-243`) raises `_Cancelled` when `queue.set_progress`
   (`backend/worker/queue.py:59`) returns False.
2. `make_progress_writer` (`main.py:42-63`) re-raises `_Cancelled` ahead of its broad `except Exception`.
3. Fix the docstring at `backend/worker/pipeline.py:246` ("must not raise").
4. One test in `backend/tests`.

Acceptance criteria:
- [ ] Cancelling during Stage 1, 2 or 3 makes the worker log `job cancelled job_id=…` within one progress-write
      interval, and the pipeline stops.
- [ ] No audio, MIDI or timing blobs remain for the cancelled job; a `job timing` line still appears.
- [ ] No card and no result reaches the phone (already true; keep it true).
- [ ] Optional UX: a short "Conversion cancelled" snackbar. Ask the user; today there is none by design.

Limits: Stage 2/3 loops may not call `on_progress` often enough, and one long model call cannot be interrupted. A hard
kill needs a subprocess and is out of scope. Risk: the progress writer is on the path of every job; run the full
backend suite before merging.

### B and F. Offline-first

Goal (user): after processing finishes and the files are on the phone, every feature works with no internet, even
after closing and reopening the app while still logged in: playback, export, mixing, delete, edit. Changes made
offline are recorded and sent to the server when the connection returns, then cleared.

VERIFIED, current state:
- Cold start offline: `M/lib/app.dart:163-180` restores the session from local storage only, so the user stays signed
  in. Only a `SessionExpiredException` sends the user to Login (`app.dart:195-203`).
- The library has **no cache**: `ScoreLibraryController.build()` calls the API directly
  (`M/lib/state/score_library_providers.dart:43-45`). Offline this raises `ScoreLibraryNetworkException`
  (`score_library_api.dart:188-196`) and shows "Can't load your scores" (`library_messages.dart:29`). This is the
  cause of the reported message.
- Edit and delete are direct API calls, not optimistic (`score_library_providers.dart:63-93`). The local copy is
  removed only after a successful server delete (`score_library_screen.dart:236-240`). No outbox or queue exists.
- Local files are wiped only on logout, account delete or a different account
  (`M/lib/state/session_actions.dart:56-60,102-104`), never on a network error. So "closing the app loses the offline
  copies" is probably the library failing to list them, not the files being deleted. Verify on the phone: with
  airplane mode on, does the score still exist in the app's results folder? Treat F as solved by caching the list.
- The score list model has `lastActivityAt` only; no `updatedAt` (`M/lib/models/score_summary.dart:72-74`).

Work:
1. **Library cache.** Store the score summaries and local file paths after every successful fetch. Cold start offline
   shows the cache; online refreshes it.
2. **Local-first edit and delete.** Apply the change to local state at once. For delete, remove the local files
   immediately (user decision), and keep only a tombstone record in the queue.
3. **Persistent operation queue.** Each operation (`patch`, `delete`) gets a client op id and timestamp and survives
   restart. A replay step runs on app start and on connectivity change, removing an operation only after success.
4. **Replay rules.** `DELETE` repeated on an already-deleted score returns 404 (backend `routes_scores.py:189`):
   treat 404 as success. `PATCH` (`routes_scores.py:164`) sets absolute values, so it is safe to replay; 404 means
   deleted elsewhere, so drop the operation; 409 `retake_in_progress` (`routes_scores.py:171`) means keep and retry.
   Conflict policy: last write wins by client timestamp. Keep the 7-day soft delete; no restore endpoint.
5. **Backend (optional):** add `updatedAt` to score entries if the client needs it to reconcile after sync.

Acceptance criteria:
- [ ] Airplane mode, force-close, reopen: the library lists every score and each one plays.
- [ ] Offline edit and offline delete both work, survive an app restart, and sync once when internet returns.
- [ ] A delete done offline removes the local files immediately; a failed sync never brings the score back.
- [ ] A second sync sends nothing. Edit-then-remote-delete is dropped without an error dialog.
- [ ] Logout and account delete still wipe all local copies.

This is the largest app change. Own branch, own frontend-lead review, not in the same merge as A, H, I and J.

### C. Playback chopping and click lag

VERIFIED: the app uses `just_audio ^0.10.6` with **one player per voice (4) plus a fifth for the click**, all
separate players (`M/lib/services/playback_engine.dart:154`). One is master; the others are kept in step by a timer
that re-seeks them when they drift more than 25 ms (`playback_engine.dart:177,772`). Mute is volume 0 (`:119-121`).
The click is a pre-rendered WAV (`M/lib/services/metronome_click.dart:389-401`), played as a plain player and
time-stretched with the voices when speed changes (`playback_engine.dart:519-525`).

Reading: five independent decoders corrected by seeks is the most likely cause of both the chopping and the click
lag. Each seek correction can click, and the click transients smear when stretched. This also explains why loudness
(the earlier B10 worry) is probably not the cause. It is not proven. Cheap check before building anything:
1. Play two voices only. 2. Play one voice with the metronome at maximum tempo. 3. Lower all four by 6 dB. If the
chopping stays the same with fewer voices lowered in volume, loudness is ruled out. Record the result.

The user's direction (section 0) is to replace the 5-player mix with phone-side synthesis (section 6), because the
mixer must remain. A premixed track is not an acceptable replacement. Short-term only, if the user wants relief before
section 6 is done: raise `resyncTrigger` or reduce re-seeks. Treat this as a stopgap and ask first.

### D. Lyrics blanked in playback images

`blank_lyrics_regions` runs at `stage1_preprocessing.py:650` on the binary page that feeds detection. The served
`result.pages` likely share that image through `clean_page` (`backend/worker/pipeline.py:273`); UNVERIFIED. Plan:
build the display JPEG from the deskewed grayscale image before blanking; detection keeps the blanked copy. Do not
change the detection input (BUG-016 area). Review by ml-cv-lead; re-run Stage 1 to 3 checks to show detection output
is unchanged.

### E. Piano sound

A Stage 5 parameter; the FluidSynth reverb setting was not found in a quick search. Plan: find where Stage 5
configures FluidSynth, render one short piece with reverb off and low, compare by ear with MuseScore's piano, and test
one or two drier piano `.sf2` candidates if needed. Review by choral-conductor. This also decides the soundfont for
section 6, so decide E before choosing the phone-side soundfont.

### G. Export progress jumps 30% to 100%

The weights are download 0.2, prepare 0.05, render 0.7, save 0.1 (`M/lib/services/export_service.dart:678-740`),
monotonic. Android reports whole-percent steps (`RenderProgress.kt:23-60`; `ExportWorker.kt:196-203` posts via
`main.post` and drops events once finished). No code explains the jump, so UNVERIFIED. Likely render events are
throttled or coalesced until the end. Next step: log progress events on both sides during one export.

### H and I. Tiny frontend items

- H: no explicit snackbar duration exists in `lib/`; Flutter's default is about 4 s (10 s only with an action,
  UNVERIFIED for this Flutter version). Set an explicit 10 s duration through one shared helper or a
  `SnackBarThemeData`, not per call. The scan toast is separate (`lib/screens/scan_status/scan_toast_host.dart`, 4 s); user decided it also becomes 10 s.
  Add a "Conversion cancelled" snackbar on cancel (user decision).
- I: `ScoreDetails.minTempo = 30, maxTempo = 240` (`M/lib/models/score_details.dart:36-37`); `setBpm` clamps to them
  (`playback_providers.dart:891`). Change `maxTempo` to 180 and add a clamp test. Check that a saved tempo above 180
  from older scores clamps cleanly.

### K. `.mid` files

VERIFIED: the app does download the per-voice `.mid` files when `/result` carries `midiTracks`
(`M/lib/services/local_results_store.dart:82-85`), into private storage under
`getApplicationSupportDirectory()/results/<scoreId>/midi_<voice>_<fileId>` (`playback_providers.dart:32-33`;
`local_results_store.dart:108-109`). They are invisible to the user, which matches the test. They are **never used**:
`loadOffline` skips them with "MIDI has no reader yet" (`:175-176`), and nothing else in `lib/` reads MIDI. Whether
`/result` carries `midiTracks` for newly processed scores should be checked once on the live API. Section 6 gives
these files a reader.

## 4. Logging plan (item J)

Done (on `main`, `a829724`):
- API: `req METHOD route status ms in_bytes out_bytes`, using the route template so raw ids, query strings and signed
  media tokens never reach the log. `/healthz` is skipped.
- Worker: `job timing job_id pages total_s stages` after every job, including failed and cancelled ones.

Add (backend, no contract change):
1. `job_id` and `score_id` on the `req` line, from `request.view_args`.
2. An integer `user_id` when the request is authenticated. Never log emails, passwords, tokens, reset codes or
   signed media tokens.
3. Explicit event lines with durations:
   - `auth login ok|fail reason=<code> ms=…` (reason code only, no email)
   - `auth signup ok ms=…`
   - `auth reset requested|verified|confirmed ms=…`
   - `account delete ok ms=… purged_keys=…`
   - `score create job_id=… pages=… in_bytes=… ms=…`
   - `score edit score_id=… ms=…`, `score delete score_id=… ms=…`
   - `job cancel job_id=… ms=…`
4. Worker: log queue wait (created to claimed) and end to end (created to complete) per job.
5. Phone-side durations (upload, download, offline open, export, on-device render) need app timers and a new APK;
   schedule them with the section 6 work.

Tests: extend `backend/tests/test_app_basics.py` to assert the new fields and that no token or email reaches the log.
Use of logs: restart the worker from current `main`, run one full conversion, collect only the lines starting with
`req ` and `job timing `. Data point already in hand: job 12, Stage 1 about 80 s for 4 pages on CPU, Stage 2 about 7 s,
Stage 3 about 0.3 s per strip.

## 5. Order of work

1. A cancel fix (small, tested).
2. J logging additions.
3. H and I (10 s messages, tempo cap 180).
4. C three-minute check, then start section 6.
5. G and the `midiTracks` live check.
6. B and F offline-first, own branch.
7. D and E after pipeline review (E before the soundfont choice in section 6).
8. Section 6 phone-side Stage 5, own session.

Before any merge to `main`: senior-reviewer; backend-lead for Module 3 changes; frontend-lead for Module 2 changes;
ml-cv-lead for D.

## 6. Phone-side Stage 5 (separate session) — token-aware plan

Goal: the phone turns the four per-voice `.mid` files into audio itself, so playback keeps per-voice mixing but runs
from fewer, sample-aligned sources, with no seek-corrected five-player mix. Also lets the server skip MP3 rendering
later (faster processing, smaller downloads).

VERIFIED facts to build on: `.mid` files already download into private storage and are unused; the app has no synth
or soundfont dependency; the click is already rendered to a WAV in an isolate (`metronome_click.dart:399`); the
Android export mixer already exists in Kotlin (`Mixer.kt`, `PcmDecoder.kt`) and could be reused for mixing.

Options, smallest first (all UNVERIFIED as to package names; no synth package is in `pubspec.yaml`):
1. **Render once at open, keep the current engine.** A native/FFI soundfont synth renders each voice's MIDI plus the
   click to WAV in an isolate, cached per score and tempo; `just_audio` plays them. Smallest code change; the
   five-player problem remains, so this fixes sound quality and reverb but maybe not the chopping.
2. **Render once, mix on the phone.** Same render, then mix the voices the user has unmuted into one PCM buffer and
   play one source. Mute and volume changes re-mix a short buffer. Fixes chopping and click lag; the mixer works.
3. **Real-time synthesis** (a soundfont synth feeding an audio stream). Best tempo and mixer response, biggest risk
   and battery cost. Not recommended first.
Recommended: spike option 2. Decision gate: a 30-minute spike that renders one voice from a real `.mid` with a small
piano `.sf2` on the user's phone and reports render time and file size. Stop and re-plan if render time for a
full piece is over about 5 s or the soundfont is too large to ship.

**Idea from the user (2026-11-07): one combined `.mid`.** A Standard MIDI File (format 1) holds many tracks on one clock: tracks 1-4 = S/A/T/B on channels 0-3, track 5 = click on a percussion channel (9) with one note per beat. Mute = skip a channel, volume = channel volume, tempo change = scale the tempo for all tracks at once, so voices and click cannot drift apart. Keep the four per-voice files too (compatibility, export). Needs: Stage 5 writes the extra file (midiutil already supports multiple tracks); backend stores/serves it as a new file kind in `/result` (backend-lead review, contract change); the click track comes from the beat grid and time signature, so check that Stage 5 knows them (UNVERIFIED). Spike should test this file first. It also makes real-time synthesis (option 3) cheaper, since mute and tempo are just channel and clock controls.

Open design questions for that session: bundled soundfont size and licence; whether to cache renders per tempo;
how the click is aligned to MIDI ticks (use the timing data, not a free timer); whether export (MP3 per voice) is
produced on the phone or kept on the server; behaviour for old scores without `midiTracks`.

**Token-use rules for that session** (user request):
- Start from this file and the handoff only; do not re-read `docs/sow.md`, the pipeline code or old ledgers.
- One subagent per task with an explicit model; briefs and reports as short files; read reports, not transcripts.
- Use Grep with line ranges; never dump whole files; cap subagent reports at about 40 lines.
- Do the spike first and decide from numbers; do not design option 3 before option 2 is measured.
- Write a ledger line after each task and a short handoff after every three tasks; run /clear after three tasks and
  never while a subagent is running.
- Do not re-run the full backend suite for frontend-only work; run only the touched tests.
- Ask the user once, up front, for the few decisions listed above instead of one question per step.

## 7. Not verified

- Whether the worker log shows `job cancelled` after the pipeline finishes for the test run.
- Whether `/result` carries `midiTracks` for newly processed scores on the live API.
- Whether `clean_page` shares the blanked image; where the FluidSynth reverb setting lives.
- Why the export bar jumps; the Flutter snackbar default for this version.
- Any synth, soundfont or MIDI package name for Flutter or Android.
- Whether Stage 2 and Stage 3 call `on_progress` often enough for fast cancel.

## 8. Decisions (user, 2026-11-07)

- Cancel gets a bottom snackbar "Conversion cancelled" (not the top scan toast; the scan toast stays silent on cancel).
- Scan toast (`lib/screens/scan_status/scan_toast_host.dart`, top banner) also lasts 10 s, same as snackbars.

### Section 6 defaults (apply unless the user objects)

- Playback keeps per-voice mixing; render on the phone from the `.mid` files; spike option 2 first.
- Click is rendered from the timing data, not a free timer.
- Export (MP3 per voice) stays server-side for now.
- Scores without `midiTracks` (old scores) keep playing from the existing mp3 path; no migration.
- Soundfont: decide after item E (reverb/piano choice); size cap and licence to be checked in the spike. Ask the user only if the best candidate is over about 30 MB.
