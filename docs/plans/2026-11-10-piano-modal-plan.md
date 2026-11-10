# Plan: Virtual Piano Modal (PIYA-218) + Piano Settings API (PIYA-321)

For a NEW session. Run with `superpowers:subagent-driven-development`. One implementer per task, then one reviewer per task.
Do not commit, push or merge without user approval (CLAUDE.md). Work in a worktree.

## Inputs
- Ticket: `C:\Users\paul_\Downloads\PIYA-218_321_Virtual_Piano_Tickets (1).md`. Copy it to `docs/tickets/` first, so later agents do not need Downloads.
- Mockups, copy to `docs/design/piano/`:
  - `PIYA212_PianoModal_UI.png` (default)
  - `..._wheninfobuttonpressed.png` (Notes Chart open)
  - `..._whitekeypress.png`
  - `..._blackkeypress.png`
- Notes Chart content image: `D:\PiyaNota\mobile\piyanota_application\lib\assets\PIYA218_Notes Chart.png`.
  - Rename it to `assets/piano/notes_chart.png`; the space in the filename breaks pubspec and tooling.
  - Declare it in `pubspec.yaml`.
  - It is static, so no network (AC 31).
- Design tokens: `.claude/agents/frontend-piyanota.md`. No inline colours or sizes. All copy goes in a `piano_messages.dart`.
- Existing code to reuse:
  - `lib/screens/playback/playback_screen.dart` (entry point, audio-session behaviour for AC 16)
  - `lib/services/live_synth.dart` and `live_synth_engine.dart` (FluidSynth FFI, native `piya_live`)
  - `lib/services/onboarding_prefs_service.dart` (`getDefaultVoicePart()`)
  - the existing session and 401 flow, `HttpScoreResultApi` and the fake-API pattern (`fake_*_api.dart`)
  - backend: `routes_*.py`, `migrations/` (next number is 0010), rate-limit buckets in `config.py`

## Findings that change the ticket (verified in code)
1. **AC 14 conflicts with the app.**
   - Android has no public real-time built-in GM synth. `android.media.midi` only talks to external devices, and `MediaPlayer` plays whole files.
   - The app already ships FluidSynth plus a 32 MB soundfont (`piya_live`), but the ticket says "no bundled soundfont, no FluidSynth".
   - The ticket's own Assumptions section says to decide this early on a real device.
2. **No user voice on the backend.**
   - Voice lives only in the app's onboarding prefs. PIYA-321 AC 2 and 14 want the server to compute the default from the user's voice.
3. The ticket's `/api/v1/users/me/...` prefix may not match the existing routes (they use `/api/...`). Check `backend/app.py`. If it does not match, follow the existing prefix and ledger the ruling.

## Decisions: RESOLVED by user 2026-11-10 — D1 = (a) reuse `piya_live`; D2 = (a) client sends `?voice=` hint. No questions remain; start at Task 0.

## Decision options (for the record)
- **D1, sound source.**
  - (a, recommended) Reuse `piya_live`. Add a small native `noteOn/noteOff` FFI on the existing synth. It works on every device, there is no new asset, and latency is under our control. Cost: the ticket text "no FluidSynth" is wrong for this app.
  - (b) Native `android.media.midi` against a built-in synth. Not viable on stock Android.
  - (c) Pre-rendered sample per key. Needs a new asset and contradicts the ticket.
- **D2, default voice.**
  - (a, recommended) The client sends `?voice=<VoicePart>` on GET and on first PUT. The server computes the default from that hint. No schema change for voice.
  - (b) Add `users.voice` plus a settings endpoint (more scope).
  - (c) The client computes the default and the server returns `octave: 4` only.

## Model and token plan (cheapest model that works)
| Task | Work | Model | Why |
|---|---|---|---|
| 0 | Copy assets, rename, pubspec, ledger, scan table | controller (you), no subagent | Mechanical |
| 1 | Backend PIYA-321: migration 0010 `piano_settings`, GET/PUT, rate-limit bucket, tests, README/smoke | **sonnet**, `backend-lead` agent | Spec is complete, one module |
| 2 | Piano core: pure Dart `piano_octave.dart` (MIDI math, default-by-voice, range clamp), `piano_settings_store` (local, `updatedAt` ISO UTC, corrupt-value fallback) and the unit tests | **haiku** or sonnet | Pure logic, all rules in AC 13, 25-28, 37, 39 |
| 3 | Sync service: reconcile (AC 41-48), 500 ms debounce, flush on close/background, pending flag and backoff, fake API, tests with fake clock | **sonnet** | Subtle, so use a mid-tier floor |
| 4 | Native `noteOn/noteOff` on `piya_live` (C/Kotlin FFI) plus a Dart `PianoSound` wrapper, init on open, "sound unavailable" path, multi-touch, release on octave change and close | **opus**, `frontend-lead` agent | Native, latency and audio-focus risk, the hardest task |
| 5 | Modal UI: bottom sheet, handle, chevrons, 5 dots, pill, keyboard (Listener/multi-touch), labels (AC 5-8), pressed fills, slide animation, a11y labels, small-width layout | **sonnet** | Large, but clear spec and mockups |
| 6 | Notes Chart card, info button rules (AC 29-36), close-with-modal, and lifecycle close | **haiku** or sonnet | Small, one image |
| 7 | Wire the entry point on the playback screen, providers, 401 handling | **sonnet** | Integration |
| 8 | Reviews | per-task reviewer **sonnet**; final whole-branch review **opus** (`senior-reviewer` agent) | Per the skill: cost scales with the risk |

Token-saving rules:
- Hand every subagent file paths (ticket section and mockups), never pasted text. Each task gets a brief of only its AC numbers, written to `.superpowers/sdd/`.
- Batch Tasks 2 and 6 into one dispatch if they are small.
- The implementer returns status only; the full report goes in a file.
- Run only targeted tests while iterating. Run one full `flutter analyze`, `flutter test`, `flutter build apk --debug` and the backend pytest at the end.
- The backend test DB is the portable Postgres. Start it per `docs/plans/2026-11-07-handoff.md` (port 55432). Stop it at the end.

## Order
D1/D2 answers, then Task 0, 1, 2, 3 (these four are independent of the sound source), 4, 5, 6, 7, then the final review. Task 1 can run in parallel with Task 2 only if they touch disjoint files (backend vs `mobile/`).

## Acceptance
- Task by task against the ticket's AC numbers.
- Final: the ticket's 15-item integration checklist. Items 2, 5, 6 and 13 need a real Android device, so write `device-test-checklist.md` for the user.
- `flutter analyze` is clean (the known `live_synth_engine.dart:35` info is allowed). All tests pass.
- Deploy order: backend first (migration 0010), then the app.

## Known risks
- Latency of 100 ms or less is unproven until a device test.
- Held notes must be released on octave change, modal close and app background (AC 22).
- The design mockup shows 6 dots. Build 5 (AC 2 and 20).
- The Notes Chart image is raster. Check that its margins sit inside the card with padding from the card edges (the user asked for space), and render it with `BoxFit.contain` inside padded content.
