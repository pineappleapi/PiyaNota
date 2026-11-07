# Plan: play the score from MIDI on the phone (Session B)

Date: 2026-11-07. Status: plan only, no app code written, nothing committed or merged.
Source: `2026-11-07-phone-test-findings-plan.md` sections 0 and 6, plus two checks below.
Also follows `2026-11-07-handoff.md` "Session B" and "Working method" (cheap models for search/checks, strong model only
for design decisions D1-D6, reviewers only where CLAUDE.md requires them). Branch: `feature/piya106-overnight-cancel-logging-ui`.

## 1. Constraints (from findings plan section 0)

- Playback stays per-voice and mixable. A single premixed track is not the playback path.
- Phone-side rendering is wanted only if it is faster and removes the chopping.
- Offline delete removes local files at once. Nothing is committed or merged without user approval.

## 2. Checks of the two unverified items

### 2.1 Does /result carry midiTracks for new scores? YES (code-verified, live API not checked)

- `backend/routes_scores.py:78-126`: `GET /api/scores/<id>/result` builds `midiTracks` per request from
  `audio_tracks.midi_key`. Shape: `{"soprano": {url, fileId, sizeBytes}, ...}`, lowercase voice keys, or `null`.
- New conversions: `backend/worker/pipeline.py:310-320` reads `<voice>.mid`; `worker/main.py:169-179` uploads it;
  `completion.py:134-135` stores `midi_key`. Stage 5 writes a `.mid` for every voice (`stage5_synthesis.py:112-114`).
- `midiTracks` is `null` for: scores converted before migration `0004_midi_key`; scores where no voice has MIDI.
  It can be partial (failed voices are dropped).
- App: `lib/services/local_results_store.dart:65-92` already downloads `midi_<voice>` files. Missing MIDI does not block
  offline opening (`:175-176`). No MIDI reader exists in `lib/`.
- The handoff and findings plan cite `playback_providers.dart` for "MIDI has no reader yet". The comment actually sits
  in `local_results_store.dart:175`; no `playback_providers.dart:32-33` match was found. Treat that citation as loose.
- Not checked: a live `/result` for a newly processed score; that the production worker runs the new path (the docs say
  the worker needs a restart after the backend change). Task 0 below closes this.

### 2.2 Does Stage 5 know the beat grid and time signature? NO

- Stage 5 writes tempo only: `stage5_synthesis.py:199-201` (`MIDIFile(1, ticks_per_quarternote=480)`, one `addTempo`).
  No time-signature meta event, no click track, no pickup marker. `bpm` is a flat int (default 90), not read from the score.
- `synthesize_satb` and `build_voice_midi` never receive the Stage 4 report, so `pickup_ticks`, per-system
  `time_signature`, bars and `start_tick` (`stage4_reconstruction.py:282-289`) are dropped.
- The data does exist elsewhere: `backend/worker/pipeline.py:328-329` passes `report` and `bpm` to
  `timing_export.py:90-109,213-222`, which builds `bars` (pickup = bar 0, numerator/denominator, mid-piece meter changes,
  startMs/durMs). The app click (`metronome_click.dart:67-86`) is built from those bars.
- Meter caveats from the checks: undetected meter defaults to 4/4 (flagged `METER_NOT_INFERRED` in Stage 4); mid-strip
  meter changes were applied conservatively (`docs/decisions/piya-106-meter-change-applied.md`); the spec for accents,
  pickup and last-bar length is `docs/decisions/meter-click-and-muting-gaps.md` items 8-10, 13.
- Not verified: that `midiutil` exposes `addTimeSignature` in the installed version (public API says yes).

## 3. Design decisions

D1. The click does not come from Stage 5. Stage 5 lacks the data and changing its signature spreads meter logic into a
second place. Build the click from the timing `bars` that already exist and already drive the app click.

D2. Combined file is built in the worker, not in Stage 5. A small function next to `timing_export` takes the four
per-voice note lists plus the `bars` and writes one format-1 `.mid`: tempo + time-signature meta events on a conductor
track, tracks 1-4 = S/A/T/B on channels 0-3, track 5 = click on channel 9 (accent on downbeat per the spec doc). The
four per-voice files stay unchanged (export, compatibility). Pickup bar 0 is written as a shortened first measure so the
click lines up with the notes by tick, not by a free timer.

D3. Contract change: add `midiCombined` (single `{url, fileId, sizeBytes}` or `null`) to `/result`. Additive and nullable,
so old clients and old scores are unaffected. Requires backend-lead review (CLAUDE.md rule) and a migration for a
stored key. Old scores (`midiTracks` null or no combined file): keep the current MP3 path. No backfill in this session.

D4. Rendering path: option 2 from findings plan section 6, only after the spike. Render once per score and tempo in
an isolate with a soundfont synth, mix unmuted voices plus click into one PCM buffer, play one source. Mute and volume
re-mix a short buffer. Reuse the existing Kotlin `Mixer.kt` / `PcmDecoder.kt` only if the spike shows FFI-to-Kotlin
mixing is simpler than mixing in Dart. Option 3 (real-time synthesis) is not designed until option 2 is measured.

D5. Tempo: the combined MIDI carries the base tempo. Speed changes scale the render time base, so voices and click
cannot drift apart. Cache renders per tempo bucket only if the spike shows render time is the bottleneck.

D6. Export stays server-side MP3 for now. Moving export to the phone is a later decision once playback is proven.

## 4. Tasks, in order (ledger line after each; short handoff and /clear after every three)

0. Live check (haiku subagent or user): fetch `/result` for one newly processed score; confirm `midiTracks` has four
   entries and the `.mid` files open. Confirm the worker was restarted. Gate for everything below.
1. Spike A, on the user's phone, 30 minutes: render one voice from a real `.mid` with a small piano `.sf2`. Report render
   time, output size, soundfont size and licence. Stop and re-plan if a full piece renders in over about 5 s or the
   soundfont is too large to ship. This tests the existing per-voice file, so it does not wait on D2/D3.
2. Spike B: hand-build one combined `.mid` (script, from existing timing JSON of one real score). Render it, check
   click vs notes alignment (target within the 30 ms drift goal from `2026-11-05-v2-checks-frontend.md` F8a/F8b), check
   mute by channel, and a tempo change. Includes pickup and one non-4/4 piece.
3. Decide from numbers (user): go / no-go, soundfont choice, whether option 2 is enough.
4. Backend: combined-file builder, `midiCombined` in `/result`, migration, tests (full, partial, old score). Then
   backend-lead review.
5. App: render isolate, cache, one-source player, mixer wiring, fallback to MP3 for old scores. Then frontend-lead review.
6. Phone test pass: chopping gone, click aligned, offline playback, mute/volume, delete removes render cache.
7. senior-reviewer before any merge proposal. Merge only on user approval.

## 5. Risks

- Soundfont size and licence may block shipping; spike A answers this first.
- Render time on low-end phones; mitigated by render-once cache and the 5 s stop rule.
- Wrong or defaulted meter yields a wrong click; same limitation as the current app click, not new.
- Mid-piece meter changes in the combined file depend on Stage 4 per-bar meters being right.
- Migration plus worker restart must be sequenced; MIDI-less old scores must keep working.

## 6. Open questions for the user (ask once)

- OK to treat "no backfill, old scores stay on MP3" as final?
- Soundfont: any licence or size limit (MB) for the app bundle?
- Soundfont choice ties to reverb item E in the findings plan; decide them together.
- Export (MP3 per voice): phone or server? Plan assumes server for now (D6).

## 7. Token rules for execution

One subagent per task with an explicit cheap model for search and checks; strong model only for D-decisions.
Briefs and reports as short files, reports capped near 40 lines. Grep with line ranges, no whole-file dumps.
Run only touched tests. Do not re-read `docs/sow.md`, pipeline code or old ledgers.
