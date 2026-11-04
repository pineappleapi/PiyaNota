# Frontend plan — V2 check findings (2026-11-05)

App: `mobile/piyanota_application` (Flutter, Android). Source: the user's "VERSION 2 Frontend CHECKS" and "BACKEND TESTING" notes of 2026-11-05. Ledger: `.superpowers/sdd/2026-11-05-v2-checks/ledger.md`. Joint contract (shapes, ladders, error codes): `.superpowers/sdd/2026-11-05-v2-checks/joint-contract.md`. Backend plan: `docs/superpowers/plans/2026-11-05-v2-checks-backend.md`.

## Rules (from CLAUDE.md and the user)
- Module 2 changes need a `frontend-lead` review before merge. State the planned change and a one-line risk before editing. No commit or push without the user's approval; never push or merge without asking.
- Use a worktree separate from the backend one (suggested branch `feature/module2-v3-checks`, branched from `feature/module3-backend` HEAD 5ff8d17 because the app already depends on its result contract). Ask the user before creating it.
- Verify with `flutter analyze` (clean) and `flutter test` (baseline: 1215 pass). Design work follows the dropper-sampled color rule (memory: design-fidelity-workflow); references live in `mobile/piyanota_application/references/`.
- Skipped on purpose: the TalkBack lines in the checklist (user: "No need").
- Clear the session after every 3 completed tasks (see "Session protocol").

## Token-saving method
- Controller stays thin and hands files, not pasted text, to subagents. One subagent per task with an explicit `model:` on every Agent call. Task-scoped reviews; one broad `frontend-lead` review at the end.
- Model per task weight: haiku for string, layout-constant and ledger edits and tiny re-reviews; sonnet for most implementation and reviews; opus for F8 (audio engine) design and for any fix loop that reaches round 4. UI tasks that only touch one screen use sonnet with the screen's test file only (run focused tests per task, the full suite once at the end of each batch).
- Fix rounds 1-3 resume the implementer (SendMessage); rounds 4-5 fresh implementer on a stronger model. Minor findings go to the ledger.

## Tasks

### F1 — Splash only on a cold start (202-V2.2 change) — haiku/sonnet
Change: the splash must play when the app process starts, not when it returns from the background (Home, app switch, Gmail). Remove the resume-triggered splash; keep it for a cold start. Picker returns (camera, gallery, PDF) must not show it either. Keep "logged-in cold start opens the Library, offline opens the offline Library".
Acceptance: cold start plays the splash once; background and resume shows no splash and keeps typed text, scroll and open sheets; airplane-mode cold start opens the Library. Widget test with lifecycle events `paused` then `resumed`.
Risk: the lifecycle observer also guards session restore; do not remove the session check.

### F2 — Login wait after 5 wrong passwords (202 change, JOINT J2) — sonnet
Change: no wait for wrong passwords 1-4; the wait starts at the 5th (ladder from the joint contract, set by B2: default 0:30, 1:00 and so on). Fake backend and real backend client use the same rule; the persisted wait survives app restarts as today. Airplane-mode failures never count. Show remaining attempts only if the user asks (not planned).
Acceptance: 4 failures show "Incorrect email or password" with Log In enabled; the 5th disables Log In with the live countdown; a success resets; a different email is independent; tests.

### F3 — Reset code stays on the Enter Code step (204 bug, JOINT J1) — sonnet
Finding (both fake and real backend): a wrong code still advances to New Password.
Change: on Submit of the code, call the new verify endpoint (B1). Only a 200 advances. A 400 shows "Verification code is wrong. Try again." and stays; typed passwords stay. After the 3rd wrong code Submit is disabled with a live 0:30 countdown; after the 4th the wait is 1:00 (keep the existing ladder unless B1 changes it; read it from the joint contract). Fix the fake backend to verify the code too, so the bug cannot hide there again.
Acceptance: the two unticked lines of the checklist pass against both fake and real backend; unit test for wrong, wrong, wrong, then wait; resend clears the count.
Depends on B1 for the real-backend check (build against the contract first).

### F4 — Library card icons (205 change) — haiku
Change: bring the pencil and trash icons closer together as a pair, make both slightly larger, but keep the touch targets separate enough that the wrong one is not pressed by accident (48 dp minimum targets, a visible gap between the two targets). Decide the exact numbers by looking at the screenshot, not by eye alone.
Acceptance: golden or widget test of the card at 320 dp and 2.0x text, no overflow; both targets at least 48 dp and not overlapping.

### F5 — Export screen matches the Home design (211) — sonnet
Change: same header treatment as the Score Library: logo on the left at 10% and large, bell at the far top-right. Reuse the Library header widget instead of copying it.
Acceptance: same header widget used; layout tests at 320 and 412 dp; compare with `references/PIYA205_HomePage_Version2.png`.

### F6 — Settings: default voice picker and save behavior (212) — sonnet
Changes: (a) the Default voice picker lists voices vertically (All voices, Soprano, Alto, Tenor, Bass, one per line) so selecting one does not move the others; (b) add a Save changes button at the bottom, and when there are unsaved changes and the user leaves the screen, prompt to save or discard; (c) the "Download Audio button" line of the checklist is not a decided feature: do NOT build it, and ask the user what they meant.
Acceptance: no overflow at 320 dp and 2.0x text; leaving with unsaved changes shows the prompt; a saved default applies when a score opens.
Question for the user before F6 closes: what is the "Download Audio" button the checklist mentions?

### F7 — Voices and mixer share one state; metronome row (209 and 208 changes) — sonnet
Changes: (1) the playback chips and the mixer checkmarks are the same state: choosing only Soprano in playback unchecks the others in the mixer, and checking or unchecking a voice in the mixer updates the chips. (2) Muting is not deselecting: a muted voice keeps its chip selected and only its volume is silent. (3) In the mixer, remove the on/off switch of the Metronome row; keep only the checkbox, styled like the voice rows. Chips: make them wider (more elongated) while still fitting on one line at 320 dp (208).
Acceptance: widget tests for each direction of sync, for mute-keeps-selection, and for the metronome row having no Switch; overflow tests at 320 dp, 2.0x text.
Risk: touches the playback state shared with F8; run F7 before F8 or give both to one implementer.

### F8 — Playback audio engine: sync, lag, volume (208/209 notes) — opus design, sonnet implement
Findings: (1) many replays, seek drags or tempo changes leave the voices misaligned; (2) the metronome tick does not land on the beat and lags; (3) pressing replay or back 5 s during playback with all voices and the metronome on does not stop the old audio, so layers overlap and playback lags; (4) metronome maximum volume is too loud; (5) maximum volume of the voice levels is too quiet; (6) general slowness.
Method: use the `superpowers:systematic-debugging` skill first; reproduce on a release or profile build on the phone and write down the measured drift in ms (do not guess). Likely causes to test, in order: each control action starting new players before the old ones are stopped (stale commands, no single playback-session token); voices started one after another instead of from one shared start; speed changes applied per player at different moments; the metronome scheduled by a separate timer instead of the same clock as the voices; main-thread work (timeline or auto-scroll rebuilds) during playback.
Change direction: one controller owns all players; every transport action (play, pause, seek, replay, back 5 s, speed) takes a monotonically increasing token, stops all players first, then starts them together after they have all seeked; stale completions are ignored; the metronome ticks are derived from the playback position and tempo (the timing JSON gives beats), not from a free-running timer. Volume: lower the metronome maximum; raise the voice maximum (the user wants louder: propose a gain curve, check for clipping with four voices, ask the user for the target if the gain exceeds what four summed voices allow).
Acceptance: 50 rapid replay/seek/speed actions leave all four voices within a measured tolerance (propose 30 ms, record the real number); back 5 s while playing leaves exactly one audio set playing; metronome ticks within a measured tolerance of the beat; volume changes confirmed on the phone by the user. Add a tolerance test using fake players with a virtual clock.
Risk: the largest change in the plan; keep the public controller API so screens do not change.

### F9 — Delete account UI (JOINT J3) — sonnet
Change: Settings gets "Delete account". A confirmation dialog states what deleting means in plain words (all converted scores, audio and pages are lost; this cannot be undone), asks for the password, and calls `DELETE /account`. On success clear local data (session, cached scores and files) and go to Login. Wrong password and network errors show an error and keep the account.
Acceptance: widget tests for cancel, wrong password, network failure, success; checklist tests 21 and 22 pass against the real backend after B3.

### F10 — Local copy of converted results (JOINT J4) — sonnet design/implement, `frontend-lead` review
Change: when a score is completed and opened (or on completion), download the 4 MP3s, cleaned pages, timing JSON and thumbnail into app storage, keyed by score id and the hashes from the result payload; play from the local files; offline playback works without a network; refresh signed URLs by calling `/result` again; delete the files when the score is deleted or the account is deleted; show a storage line only if cheap. Do not block opening a score on the download: stream the first time if needed, then use the local copy next time.
Acceptance: airplane-mode playback of a downloaded score; hash mismatch redownloads; deletion cleans files; widget and unit tests with a fake downloader. Depends on B6 for hashes; build against the contract.
Question for the user: should MIDI files be saved too ("midi and audio" in the notes)? The current result payload has no MIDI.

### F11 — Upload failure leaves no card; faster page thumbnails (JOINT J6) — sonnet
Changes: (a) if the upload fails or is cancelled, remove the local Library card and show a retry message (the server side is B4); (b) gallery pick takes more than 10 s to show page boxes: measure first; likely causes are decoding full-size photos on the UI thread and writing full copies. Decode thumbnails with a bounded size (cacheWidth/resize in an isolate), show placeholders at once, and bake EXIF orientation at upload time only.
Acceptance: measured time for 4 gallery photos before and after, recorded in the ledger; failed upload leaves no card; tests.

### F12 — Capture: PDF page preview, retake from gallery (206) — sonnet
Changes: (a) when a PDF is added, tapping or opening it shows a preview of its pages; (b) the user wrote "allow maybe gallery select?" for the single-photo retake: allow choosing the single replacement photo from the gallery as well as the camera, still exactly one photo. Ask the user to confirm (b) before building it.
Acceptance: PDF preview renders every page lazily; retake keeps the one-photo rule; tests.

### F13 — Processing progress display (JOINT J5) — haiku/sonnet
Change: show the server `progress` field when present (smooth the bar between polls, never move backwards), with the stage label; fall back to the old stage-based percent when the field is absent.
Acceptance: unit test for monotonic display; widget test for fallback. Depends on B5 for the real check.

### F14 — Real-backend multi-page verification (no code expected) — user plus haiku checklist
After the backend result is served by the real worker, run the checklist lines the user marked "to be checked with real score": stacked pages, band moves to the next page, auto-scroll and manual-scroll pause, seek, previous, next and plus/minus 5 s scroll; plus the whole backend test list items 20 and 21-22. Failures become tickets in `docs/bug-tracker.md`.

## Order and parallelism
- Parallel batch A (disjoint files; each in its own subagent): F1, F4, F5, F6.
- Batch B: F7, then F8 (shared playback state; sequential). F8 starts with the measurement spike.
- Batch C (need the joint contract; can start before the backend lands, using the fake backend): F2, F3, F9, F11, F13.
- Batch D: F10, F12, then F14 after B1-B6.
- Backend runs in its own worktree at the same time: B9 contract first, then B1, B3, B7 in parallel with batch A; B2, B4, B5 in parallel with batch B; B6, B8 with batch C. Integration points: F3 with B1, F2 with B2, F9 with B3, F11 with B4, F13 with B5, F10 with B6.
- Final: one `frontend-lead` review of the whole branch, one fix dispatch, then ask the user about merge.

## Session protocol (clear every 3 tasks)
- After each task: one ledger line (id, commit, analyze and test result, review verdict, deferred minors, rulings, measured numbers).
- After every 3 completed tasks: rewrite `.superpowers/sdd/2026-11-05-v2-checks/handoff-frontend.md` (CURRENT state only), then tell the user to /clear and paste the frontend resume prompt from `resume-prompts.md`.
- State lives in files, never only in the conversation.
