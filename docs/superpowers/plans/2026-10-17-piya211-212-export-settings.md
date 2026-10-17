# PIYA-211 Export Audio + PIYA-212 Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1 Export Audio modal (one mixed MP3 of the ticked voices, optional bar-aligned click) and the Settings screen (email, change password, default voice, default tempo, version, log out).

**Architecture:** Flutter UI and logic stay in Dart (Riverpod, existing sheet parts). Audio work runs natively on Android behind one new method channel `piyanota/export`. Decode uses MediaExtractor + MediaCodec, mixing is native, time-stretch uses vendored Sonic (Apache-2.0), and MP3 encoding uses vendored LAME 3.100 built as a shared `.so` through CMake (LGPL: dynamic linking, licence text shipped). The folder is picked with SAF `ACTION_OPEN_DOCUMENT_TREE`. Settings preferences sit next to the onboarding prefs in shared_preferences. Password change goes through a new `AuthApi.changePassword`, faked until Module 3 builds the endpoint.

**Tech Stack:** Flutter 3 / Dart ^3.13, flutter_riverpod 3, shared_preferences, dio, Kotlin, Android NDK + CMake, LAME 3.100, Sonic (waywardgeek/sonic `Sonic.java`), package_info_plus (new).

**Spec:** `docs/tickets/module2-mobile.md` PIYA-211 / PIYA-212, plus the user decisions below (2026-10-17). Design refs: `mobile/piyanota_application/references/PIYA211_ExportAudioModal_UI_1.png` (modal), `PIYA211_ExportAudioModal_UI_2.png` (success dialog).

## User decisions (2026-10-17), to be written into the ticket in Task 1

- Export is **one file**: only the ticked voices, mixed. "All Voices" ticks S/A/T/B. Not one file per voice.
- "With Metronome Click" mixes the click into that one file, lined up with the bars (MuseScore-style per-bar meter click, the existing `ClickPlan`). The click is present only when the box is ticked.
- Format: **MP3**.
- The export **copies the current Playback settings**: chosen speed (pitch kept) and Voice Mixer levels/mute/solo, including the click level.
- Change password: an in-app form (current, new, confirm) plus a new API, faked for now.
- Default tempo: applies **at capture submit** only, when Speed is "Not sure". Scores already scanned are unchanged.

## Global Constraints

- Branch `feature/piya211-212-export-settings`, worktree `D:/PiyaNota/.claude/worktrees/piya211-212`, from main a22ecf2. Never merge into main without the user's OK.
- Commit messages: `PIYA-211: …` / `PIYA-212: …`, ending with the Co-Authored-By line.
- Colours are dropper-sampled from the reference PNGs, never eyeballed. Any AA adjustment is documented in `app_theme.dart` the same way as the existing tokens.
- Font: Plus Jakarta Sans (theme). Reuse `SheetFrame`, `SheetCheckbox`, `showPlaybackSheet`, `mixerSoprano/Alto/Tenor/Bass`, `PrimaryPillButton` and the library header/nav gradients. Do not fork them.
- Touch targets ≥ 48 dp. Every control gets a Semantics label, and checked/toggled state is announced.
- No `catch (_) {}` without a log line. Strict types, no `dynamic` leaks. Named constants.
- Tempo range 30–240 BPM, default 90 (`ScoreDetails.defaultTempo`).
- `flutter analyze` is clean and the `flutter test` count is ≥ the current main count plus the new tests.

## Review Focus

1. **A ticked voice muted, or soloed out, in the Voice Mixer.** The file would be silent for that voice. Show the note "Muted in Voice Mixer" under that row and still allow the export. Test it in Task 4.
2. **Export at speed ≠ 1.0.** Voices and click stay in sync, and pitch is unchanged. Device check in Task 3. Unit-test that the requested speed is `chosenBpm / tempoBpm` in Task 4.
3. **Score title with `/ : * ? " < > |` or an empty title.** The file name is sanitised; an empty title falls back to "Score". Test in Task 2.
4. **The voice is unavailable (failed/unreadable).** Its checkbox is disabled, and "All Voices" means all *available* voices. Test in Task 2/4.
5. **Score with `tempoKnown == false`.** The click checkbox is disabled with the same note the Speed sheet uses (`clickNeedsTempo`). Test in Task 4.

---

### Task 1: Ticket + contract docs

**Files:** Modify `docs/tickets/module2-mobile.md` (PIYA-211, PIYA-212, PIYA-217), `docs/tickets/module3-backend.md` (new change-password API stub, capture `fallbackTempoBpm`).

- [ ] Rewrite PIYA-211 AC7, AC13, AC14, AC15 and AC19 per the decisions. Remove the `[confirm]` tags. Name: `[ScoreName]_[Voices][_Click].mp3`, where Voices is `AllVoices` or the ticked names joined by `-` in SATB order (e.g. `ClairDeLune_Soprano-Alto_Click.mp3`). A name clash gets a ` (1)`, ` (2)`… suffix. AC19 becomes: "On failure the modal keeps the selections and offers Retry." Add AC23: "The export uses the current Playback speed (pitch kept) and Voice Mixer levels."
- [ ] Add PIYA-212 ACs, each tagged *(Added 2026-10-17 for v1, user request)*. AC6: change password (current/new/confirm, Sign-Up strength rules, the 401 → wrong current password message). AC7: default voice S/A/T/B, the same pref onboarding writes. AC8: default tempo 30–240 BPM, used only at capture submit when Speed is "Not sure". AC9: a ⓘ/? help button on default voice and default tempo opens an explanation.
- [ ] Add a backend stub for `POST /auth/change-password` `{currentPassword, newPassword}` → 200 / 401 wrong current / 400 weak. Add the optional capture field `fallbackTempoBpm`: used only if the pipeline detects no tempo, unlike `tempoBpm`, which overrides detection. Flag both for backend-lead.
- [ ] Commit `PIYA-211: v1 export/settings ticket decisions`.

### Task 2: Export selection model + file naming (pure Dart)

**Files:** Create `lib/models/export_selection.dart`, `test/export/export_selection_test.dart`.

**Interfaces — Produces:**
- `class ExportSelection` (immutable): `ExportSelection.empty(Set<VoicePart> available)`, `Set<VoicePart> voices`, `bool withClick`, `bool get allVoices`, `bool get canDownload`, `ExportSelection toggleVoice(VoicePart v)`, `ExportSelection toggleAll()`, `ExportSelection toggleClick()`.
- `String exportFileName({required String title, required ExportSelection selection})` → base name without suffix, ending `.mp3`.
- `String uniqueFileName(String name, Set<String> existing)` → `name` or `stem (n).mp3`.

- [ ] Write the tests first. Empty by default (AC2). All ticks every available voice (AC3); untick All clears (AC4); untick one voice clears All (AC5); ticking all four sets All (AC6). `canDownload` is false with no voice (AC8). An unavailable voice can't be toggled, and All = all available. Name cases: `ClairDeLune_Soprano-Alto_Click.mp3`, `X_AllVoices.mp3`, sanitised `A_B_Soprano.mp3` from `"A/B"`, empty → `Score_Bass.mp3`. Unique name: `X.mp3` with `{X.mp3, X (1).mp3}` → `X (2).mp3`.
- [ ] Run `flutter test test/export/export_selection_test.dart`. It must FAIL.
- [ ] Implement. Run again: PASS. Commit.

### Task 3: Native export channel (Android)

**Files:** Create `android/app/src/main/kotlin/.../export/{ExportChannel.kt, PcmDecoder.kt, Mixer.kt, Mp3Encoder.kt}`, `android/app/src/main/java/org/vinuxproject/sonic/Sonic.java` (vendored, licence header kept), `android/app/src/main/cpp/{CMakeLists.txt, lame_jni.c}` + `android/app/src/main/cpp/lame/` (LAME 3.100 `libmp3lame` + `include`), `THIRD_PARTY_NOTICES.md`. Modify `MainActivity.kt` (register the channel), `android/app/build.gradle(.kts)` (externalNativeBuild, ndk abiFilters `arm64-v8a`, `armeabi-v7a`, `x86_64`).

**Interfaces — Produces (channel `piyanota/export`):**
- `pickFolder() → String?` tree URI; null = cancelled (AC11). The permission is persisted with `takePersistableUriPermission`.
- `listNames({treeUri}) → List<String>`.
- `render({inputs: [{path: String, gain: double}], speed: double, outPath: String}) → null`. Inputs are decoded to 44.1 kHz stereo 16-bit (linear resample when needed), summed × gain, then peak-limited so the result never clips: scale by `1/max(1, peak)`. Then Sonic `setSpeed(speed)` with pitch 1.0, then LAME at 192 kbps CBR.
- `save({treeUri, fileName, srcPath}) → String` final display path.
- `openFolder({treeUri}) → bool`: `ACTION_VIEW` on the tree's document URI; false when no app can handle it.
- Errors are `PlatformException` codes, exactly: `storage_full` (ENOSPC / IOException "No space"), `permission_denied` (SecurityException), `generation_failed` (decode/encode failure), `interrupted` (cancelled or IO broken mid-write). A partial file is deleted on any failure.

- [ ] Build check: `flutter build apk --debug` succeeds and `libmp3lame.so` is in the APK (`unzip -l … | grep mp3lame`).
- [ ] Device check with a debug-only button, or Task 4's modal once it is wired. Demo score: Soprano+Alto at 1.0x and at 0.75x with the click. Expected: plays in the phone's Files app offline, the click lands on the bars, and the pitch is the same at 0.75x.
- [ ] Commit `PIYA-211: native mix/encode/save export channel`.

### Task 4: Export service + modal UI + Playback wiring

**Files:** Create `lib/services/export_service.dart` (`abstract interface class ExportService` + `MethodChannelExportService`), `lib/state/export_providers.dart`, `lib/screens/playback/export_sheet.dart`, `lib/screens/playback/export_messages.dart`, `test/export/export_sheet_test.dart`, `test/export/export_service_test.dart`, `test/export/export_fakes.dart`. Modify `lib/screens/playback/playback_screen.dart` (`onDownload` opens `ExportAudioSheet` instead of `_openPlaceholder`; delete `_ComingSoonSheet` if now unused), `lib/theme/app_theme.dart` (sampled tokens), `lib/screens/playback/playback_messages.dart` (drop `exportSheetTitle` if moved).

**Interfaces:**
- Consumes: `ExportSelection`, `exportFileName`, `uniqueFileName` (Task 2); channel methods (Task 3); `playbackControllerProvider(scoreId)` state (`chosenBpm`, `tempoBpm`, mixer levels/mute/solo, click level, `result.audioTracks`, `clickNeedsTempo`) and the existing ClickPlan WAV render in `lib/services/metronome_click.dart`.
- Produces: `ExportService { Future<String?> pickFolder(); Future<ExportResult> export(ExportJob job, String treeUri); Future<bool> openFolder(String treeUri); }`. `ExportJob {List<(Uri track, double gain)> inputs, double speed, String fileName}`. `ExportResult {String fileName, String location}`. `sealed class ExportFailure implements Exception` with `StorageFull`, `PermissionDenied`, `GenerationFailed`, `Interrupted`. `ExportJob buildExportJob(PlaybackState s, ExportSelection sel, String title)`.

**Behaviour:**
- `buildExportJob` uses each ticked voice's *effective* gain, computed the same way the controller sets engine volume (find and reuse that function, don't re-derive). With the click ticked, it adds the click WAV, rendered in track time, at its effective click gain. `speed = chosenBpm / tempoBpm`.
- `export()` downloads remote `https` track URIs to the cache with dio (local `file:` URIs are used as they are). Then render → `listNames` → `uniqueFileName` → save. Temp files are deleted in `finally`.
- Sheet layout follows UI_1: `SheetFrame` title "Export Audio" (no subtitle line, or an empty one if `SheetFrame` requires it; add an optional subtitle param rather than forking). Rows: voice pill (mixer colours) + `SheetCheckbox`; an "All Voices" pill in `playbackNavy`; a "With Metronome Click" plain-text row; dividers `sheetDivider`; full-width gradient "Download Audio" pill (sample its gradient from UI_1). Disabled until `canDownload` (AC8).
- While working (AC12): the button shows a spinner + "Preparing audio…" and is disabled. The sheet can't be dismissed while busy (`PopScope canPop: false`).
- Folder cancel → back to the sheet with selections kept (AC11).
- Success (AC16): close the sheet, then show a dialog styled per UI_2: "Download Successful!", file name and location as body text, actions "Open folder" (hidden if `openFolder` returns false) + "OK". The OK pill colour is sampled.
- Failure (AC18/20): an inline error banner in the sheet (reuse `AuthErrorBanner` styling or the `errorBannerFill` tokens) with the specific message + Retry, selections kept. Copy (in `export_messages.dart`):
  - storage full: "Not enough space on this phone. Free up some space and try again."
  - permission: "PiyaNota can't save to that folder. Choose another folder, or allow access in Settings > Apps > PiyaNota > Permissions."
  - generation: "The audio file couldn't be made. Try again."
  - interrupted: "The download stopped before it finished. Try again."
- Review Focus 1 and 5 notes as above.

- [ ] Write widget tests with `FakeExportService` + the existing `playback_fakes.dart`: opens from the download icon; default empty; AC3–6 via taps; Download disabled at none; folder cancel keeps ticks; busy disables + spinner; success dialog shows the name; each of the 4 failures shows its message + Retry; muted-voice note; click disabled when `clickNeedsTempo`; the semantics `checked` flag on rows; dismiss with X / barrier / back creates no export call (AC9).
- [ ] Unit test `buildExportJob`: speed `0.75` from chosen 60 / tempo 80; gains from mixer state (muted → 0, solo excludes others); the click input is present only when ticked.
- [ ] Unit test `MethodChannelExportService` error-code mapping with `TestDefaultBinaryMessengerBinding` mock handlers.
- [ ] Run `flutter test test/export` → FAIL, implement, → PASS. Run full `flutter analyze` + `flutter test`.
- [ ] Sample the modal colours from UI_1/UI_2 with PIL and put the values in `app_theme.dart` with comments.
- [ ] Device test on the user's phone (debug APK): the AC checklist for 211.
- [ ] Commit `PIYA-211: export audio modal`. Dispatch senior-reviewer; fix; re-review until MERGE-READY. Stop for the user's phone test + merge OK.

### Task 5: Settings prefs + change-password API

**Files:** Create `lib/services/settings_prefs_service.dart`, `lib/state/settings_providers.dart`, `test/settings/settings_prefs_test.dart`, `test/auth/change_password_api_test.dart`. Modify `lib/services/auth_api.dart`, `lib/services/fake_auth_api.dart`, `lib/services/onboarding_prefs_service.dart` (add `setDefaultVoicePart`), `lib/services/score_upload_api.dart` + its submit call site (send `fallbackTempoBpm` when `details.tempoBpm == null`), `lib/config/api_config.dart` (path).

**Interfaces — Produces:**
- `OnboardingPrefsService.setDefaultVoicePart(VoicePart v) → Future<void>` (same key, so Playback AC3 picks it up unchanged).
- `SettingsPrefsService { Future<int> getDefaultTempo(); Future<void> setDefaultTempo(int bpm); }` key `settings_default_tempo`, clamped 30–240, default 90.
- `AuthApi.changePassword({required String token, required String currentPassword, required String newPassword}) → Future<void>`. Throws `InvalidCredentialsException` (401 wrong current), `AuthValidationException` (400 weak), `AuthNetworkException`, `AuthServerException`. The fake accepts the demo account's current password and enforces Sign-Up's rules (reuse `auth_validators.dart`).
- `accountEmailProvider`: the logged-in email from the stored `AuthSession` (or the fake PIYA-306), plus `appVersionProvider` via package_info_plus.

- [ ] Tests first: tempo default 90, clamp at 29→30 and 241→240, persistence; the voice setter round-trips through `getDefaultVoicePart`; fake changePassword success / wrong current / weak; the HTTP client maps 200/400/401/network; the upload body has `fallbackTempoBpm=<pref>` only when tempo is "Not sure", and never alongside `tempoBpm`.
- [ ] FAIL → implement → PASS. Commit `PIYA-212: settings prefs, change-password API, fallback tempo`.

### Task 6: Settings screen

**Files:** Create `lib/screens/settings/settings_screen.dart`, `settings_messages.dart`, `widgets/{settings_section.dart, voice_picker.dart, tempo_stepper.dart, help_button.dart, change_password_sheet.dart, log_out_dialog.dart}`, `test/settings/settings_screen_test.dart`. Modify `lib/app.dart` (route → `SettingsScreen`, with the session gate in AC5), `lib/theme/app_theme.dart` (derived tokens, commented "derived, not sampled").

**Design direction (frontend-design pass, no mockup, so derived from brand):**
- The header reuses `libraryHeaderGradient` with the faded logo top-right at `libraryHeaderLogoOpacity`, and "Settings" white 34 sp bold left-aligned, the same as the Library title. The bottom nav is `LibraryBottomNav` with Settings selected, so the two tabs feel like one app.
- The body is on `libraryBackground`. Three left-aligned groups on white surfaces with one 16 radius each: **Account**, **Playback**, **About**. Group names are sentence case, 14 sp `playbackSubtle`, not all-caps.
- The memorable element is the default-voice picker: the four voice pills in their mixer colours (`mixerSoprano` …) as a single-select row. The chosen pill is filled with a white ✓; the others are an outline in the voice colour. It echoes Playback's chips and the onboarding badges.
- Default tempo is a stepper: `−` [`♩ = 90`] `+`, with 48 dp round buttons in `playbackNavy`, long-press repeat, and a 30–240 clamp. The label uses the same "♩ = N" format as the Speed sheet.
- A help button (`Icons.help_outline_rounded`, 48 dp target, `sheetClose`-grey icon) sits beside "Default voice" and "Default tempo". It opens a `showPlaybackSheet` + `SheetFrame` explanation:
  - voice: "This is the voice that plays when you open a score for the first time. You can still turn other voices on or off on the Playback screen. You first picked it during setup."
  - tempo: "When you scan a score and choose \"Not sure\" for its speed, PiyaNota makes the audio at this tempo, unless it can read a tempo from the page. Scores you already scanned keep their tempo. You can still change the speed on the Playback screen."
- Account rows: Email (read-only, AC1, no chevron, selectable text). "Change password" row → `change_password_sheet` (current/new/confirm using `AuthTextField`, the Sign-Up validators, a loading state, and AC6 errors; on success the sheet closes and a SnackBar says "Password changed").
- About: "App version 1.0.0 (1)" (AC2).
- Log out: a full-width text button in `processingCancel` red at the bottom, then a confirm dialog "Log out of PiyaNota?" with Cancel / Log out (AC4). On confirm, call `endLocalSession` and `pushNamedAndRemoveUntil(AppRoutes.login)` (AC3).
- AC5: the route builder reads the stored token. If it is missing or expired, it routes to Login instead.

- [ ] Widget tests: shows the email; shows the version; the voice pick persists and reads back; tempo +/− and clamps persist; each help button opens its text; the change-password happy path + wrong current + mismatch + weak; Log out → Cancel stays; Log out → confirm clears the session and lands on Login; no session → Login; semantics labels on the pills (selected state) and the stepper value.
- [ ] FAIL → implement → PASS, then full analyze + test.
- [ ] Device check at 320 dp width and at 2.0 text scale (no overflow).
- [ ] Commit `PIYA-212: settings screen`. Dispatch senior-reviewer → MERGE-READY. Stop for the user's phone test + merge OK.

## Verification (end to end)

1. `flutter analyze` is clean, and `flutter test` all passes (count reported).
2. `flutter build apk --debug`, then install on the user's phone.
3. 211: on the demo score, export S+A with the click at 0.75x into Download. The file `…_Soprano-Alto_Click.mp3` plays offline in Files, the click lands on the bars, and the pitch is unchanged. Exporting again gives ` (1)`. Cancel the picker and the selections are kept.
4. 212: change the default voice → open a new score → that voice is selected. Set the tempo to 70 → scan with "Not sure" → the request carries `fallbackTempoBpm=70` (fake API log). Change password with the demo account. Log out → Login.
