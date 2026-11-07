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

## 4b. Added after review (2026-11-07)

### Backend-lead answers (read-only review)

- Old scores stay on MP3, no backfill. The server keeps no Stage 4 events or report per score, so Stage 5 cannot be re-run
  from stored data; a backfill is a full GPU re-run per score (26-51 s per page) and could change notes the user trusts.
  The user can retake a score to get MIDI. The app must always fall back to MP3 when `midiCombined`/`midiTracks` is null;
  keep that branch tested permanently.
- Keep server MP3 rendering for new scores until the MIDI path has shipped and passed phone testing. `audio_tracks.file_key`
  is NOT NULL and the worker treats a missing MP3 as a failed voice (`worker/pipeline.py` ~310-318). MP3 render is about
  16 s of a 104 s four-page job, CPU only. Dropping it later is one contract change: nullable `file_key`, nullable
  `audioFiles`/`audioTracks`, a midi-only worker mode, a new failed-voice rule.
- Add the `midiCombined` key to the old-key cleanup (`completion.py` ~103-108) and new keys (~134), and check the delete path
  in `routes_scores.py`, or retakes and deletes orphan the blob (FR-12). Delete path not yet verified.

### Soundfont facts

- The current `soundfont/piano.sf2` (32 MB) is GeneralUser GS 2.0.3 BETA by S. Christian Collins. Its licence allows use for
  music creation; in-app redistribution is not clearly granted and some sample origins are uncertain. Ask the author in
  writing before shipping it in the app.
- Candidates (licences unverified from files): FreePats piano (CC-BY 3.0), Salamander Lite repack (21 MB, CC-BY, repack
  provenance unknown), a trimmed copy of GeneralUser GS (Polyphone). TimGM6mb is GPL, avoid. SFZ pianos need an SFZ player
  (sfizz), not FluidSynth, and are very large; not for shipping.
- Audition MP3s: `scratch/sf-audition` (not committed).

### Item D (added to this session): playback images should keep lyrics

Finding from a read-only trace (cheap agent, partly UNCERTAIN):
- The served page JPEG is the native-resolution gray strip source (`worker/pipeline.py:149-155,276`; source built at
  `stage1_preprocessing.py:668-669,751-753`), not the 1600 px detection binary. `blank_lyrics_regions` (`stage1:650`)
  runs only on the detection binary, so it is NOT what removes lyrics from the served image.
- Lyrics are likely removed by `non_staff_ink_mask` (`stage1:386-433,741`), which erases ink not connected to a staff,
  and the gray source is filled with paper colour where it erased. So the findings-plan fix ("build the JPEG before
  blanking") would not change anything; the lyrics must be kept in a different image.
- Geometry risk: timing x and bar positions are in detection-page pixels (`timing_export.py:31-63,200-213`), while the
  served JPEG has native dimensions; the app scales by the decoded image width (`playback_screen.dart:1185-1213`). The
  phone test showed highlights working, so either something rescales or the mismatch is hidden; UNVERIFIED. Any new
  display image must keep the same dimensions and deskew as the current one.

Plan:
- D1. Verify with one real job: compare page JPEG size with timing `pageW`; confirm what the highlight maps against.
- D2. Prototype: a display-only gray image built from the same deskewed/dewarped source with the staff-ink erase
  skipped (lyrics kept, same size and rotation), saved only for `result.pages`. Detection and strips keep today's
  inputs, so Stage 2-3 output must be byte-identical; show this with a test on one fixture.
- D3. Check that lyrics-kept pages do not look worse (stray marks, bleed-through) on 3-4 real pages. User signs off.
- D4. Review: ml-cv-lead for the Stage 1 change, backend-lead for the page JPEG and storage size (bigger JPEGs, 20-score
  limit), frontend-lead only if app scaling changes.
- Open question for the user: should lyric text be kept as printed, or also should the page remain clean of marginal noise?

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
