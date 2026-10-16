# Module 2: Mobile Application (Frontend — Android)

_Covers: UI tickets (Onboarding, Account, Score Library, Playback, Settings, System States) and Integration tickets._

_Phone test results (2026-10-17, fake backend): 75 pass, 0 fail, 12 untested. Per-AC detail in `docs/testing/module2-phone-test-2026-10-17.md`._

## UI Tickets

### PIYA-201 — Onboarding Guide UI
**User Story:** As a first-time user, I want to see a brief guide explaining what PiyaNota does, so that I understand how to use the app before I start.

**Process:**
1. User opens the app for the first time (no existing session or prior launch flag).
2. System displays the Onboarding Guide as a swipeable, multi-step sequence.
3. User swipes/taps Next through each step.
4. User taps Get Started or Skip to proceed to Login/Sign-Up.

**Acceptance Criteria:**
1. Displays exactly on first app launch only; does not reappear on subsequent launches once completed/skipped.
2. Consists of 3 steps: app purpose, the 3-step workflow (Capture/Wait/Listen), voice part selection.
3. Each step displays a progress indicator (dots) showing position out of 3.
4. A Skip option is visible/functional on every step, immediately routing to Login/Sign-Up.
5. The voice part selected on the final step is saved and used as the default isolated voice on first score playback.
6. Tapping Get Started on the final step routes to Sign-Up (not Login), since this is a first-time user flow.

---

### PIYA-202 — Login UI
**User Story:** As a returning user, I want to log in with my email and password, so that I can access my saved scores.

**Process:**
1. User opens the app with no active session.
2. System displays Login screen.
3. User enters email and password, taps Log In.
4. On success, routes to Score Library.

**Acceptance Criteria:**
1. Email/password fields required; Log In button disabled until both non-empty.
2. Invalid credentials display inline error ("Incorrect email or password") without clearing entered email.
3. Successful login calls Login API (Module 3) and stores returned session token securely on-device.
4. "Forgot Password?" link visible, routes to Password Reset.
5. "Don't have an account? Sign Up" link visible, routes to Sign-Up.
6. Displays loading state during request; disables repeated submission during that time.
7. Network failure displays a distinct error ("Can't connect — check your internet connection") separate from invalid-credentials error.

---

### PIYA-203 — Sign-Up UI
**User Story:** As a new user, I want to create an account with my email and password, so that I can save and access my scores across sessions.

**Process:**
1. User taps Sign Up from Onboarding or Login.
2. System displays Sign-Up screen.
3. User enters email, password, password confirmation.
4. User taps Create Account; on success, routes to Score Library.

**Acceptance Criteria:**
1. Email, password, confirm-password required; Create Account disabled until all three filled.
2. Displays validation error if email format invalid, before submission.
3. Displays validation error if password and confirm-password don't match.
4. Displays validation error if password doesn't meet minimum strength (defined by Sign-Up API, Module 3).
5. Displays specific error if email already registered ("An account with this email already exists"), with a link to Login.
6. Successful account creation automatically logs the user in and stores session token, no separate login step.
7. Displays loading state during request; disables repeated submission during that time.
8. *(Added 2026-10-17 for version 1, user request.)* An "Already have an account? Log In" link is visible and routes to Login.

---

### PIYA-204 — Password Reset UI
**User Story:** As a user who forgot my password, I want to reset it via my email, so that I can regain access to my account.

**Process:**
1. User taps "Forgot Password?" on Login.
2. System displays Password Reset request screen.
3. User enters registered email and submits.
4. User receives reset link/code via email and completes reset.

**Acceptance Criteria:**
1. Email field required; Submit disabled until non-empty and well-formatted.
2. Valid, registered email displays confirmation message ("If this email is registered, a reset link has been sent") within 3 seconds.
3. Unregistered email displays the **same** confirmation message, to avoid revealing which emails are registered.
4. Reset flow allows setting a new password meeting same strength requirements as Sign-Up.
5. Upon successful reset, user is routed to Login with success confirmation displayed.
6. *(Added 2026-10-17 for version 1, user request.)* A "Resend code" action becomes available 30 seconds after a code is sent, with a visible countdown until then. After the countdown ends, the user can resend the code, which restarts the 30-second countdown.

---

### PIYA-205 — Score Library UI
**User Story:** As a choir member, I want to view all my previously processed scores, so that I can quickly access and rehearse with them.

**Process:**
1. User logs in or opens app with active session.
2. System displays Score Library as home screen.
3. User searches/scrolls through saved scores.
4. User taps a score to open Playback, or taps Add Score to capture a new one.

**Acceptance Criteria:**
1. Displays only scores belonging to the authenticated user's account.
2. Each entry displays at minimum title and date last processed/accessed.
3. Search bar filters by score title, updating as user types (case-insensitive, partial match).
4. Displays empty state ("No Scores • Tap Capture Button") when zero saved scores.
5. Displays appropriate loading state while list is fetched.
6. Displays appropriate error state, with retry option, if list fails to load.
7. Tapping a score entry routes directly to Playback for that score, without re-processing.
8. Add Score entry point routes to Capture flow.

---

### PIYA-206 — Capture / Add Score UI
**User Story:** As a choir member, I want to capture or upload photos of my sheet music, so that PiyaNota can generate an audio guide from it.

**Process:**
1. User taps Add Score or Capture tab.
2. System presents options: take a photo, choose from gallery, or upload a PDF.
3. User captures/selects pages in sequence.
4. User confirms page set and submits for processing.

**Acceptance Criteria:**
1. Offers three distinct input methods: live camera capture, photo library selection, PDF upload, each clearly labeled.
2. Camera capture requests device camera permission at first use; if denied, displays a message explaining camera is required, links to device settings.
3. Photo library selection requests storage/media permission at first use, same denial-handling behavior.
4. Users can capture/select multiple pages in sequence before submission; each page appears in a reviewable, reorderable thumbnail strip.
5. Users can remove an individual page from the set before submitting, without restarting the entire capture process.
6. PDF upload accepts files up to 20 pages (FR-6); files exceeding this are rejected with a clear error before upload begins.
7. Non-PDF, non-image file types rejected immediately at selection time with a clear error message.
8. Tapping Submit/Confirm calls PIYA-101 (camera/gallery input) or PIYA-310 (PDF input), routing to Processing in either case — client selects correct endpoint based on input method, not a single hardcoded call.

*(2026-10-09, user decision: the optional name field on the score-details screen (the PIYA-101 AC8 metadata sent at submit) holds the **arranger**, not the composer. It is sent as `arranger` (renamed from `composer`, with error codes `arranger_too_long` / `arranger_invalid`) and labelled as the arranger in the UI.)*

---

### PIYA-207 — Processing Status UI
**User Story:** As a choir member, I want to see the progress of my score being processed, so that I know how long to wait and whether it succeeded.

**Process:**
1. User is routed here immediately after submitting a score for processing.
2. System polls processing status and displays real-time progress.
3. On completion, routes to Playback; on failure, displays error with next steps.

**Acceptance Criteria:**
1. Polls PIYA-102 at a fixed interval (e.g., every 2 seconds), updates displayed percentage accordingly.
2. Displays current page and total page count (e.g., "page 2/3") while processing is in progress.
3. Displays estimated time remaining, updated as processing progresses.
4. A Cancel Scan option is available/functional at any point before completion.
5. Displays a distinct error state — separate from the normal progress view — if status returns `failed`, showing the specific failure reason (e.g., "No staff lines detected on page 2 — please retake this page").
6. **When `failure_reason` is `"unsupported_staff_layout"` (PIYA-105):**
   - Displays a message distinct from the `no_staff_detected` case — e.g., *"This page appears to use a 2-staff SATB layout, which isn't supported. PiyaNota requires each voice part (Soprano, Alto, Tenor, Bass) on its own staff line."*
   - Does **not** use the generic "please retake this page" wording, since retaking the same score in the same format will not resolve this failure.
7. **Recapture action branching by failure type:**
   - On `no_staff_detected` → offers a direct action to recapture only the affected page, rather than requiring the user to restart the entire submission.
   - On `unsupported_staff_layout` → **no recapture-this-page action is offered**, since recapturing won't change the underlying score's layout. The user is instead directed back to the Score Library with the error message displayed.
   - On `incomplete_voice_sequence` *(added 2026-10-14, user decision 2026-10-14)* → offers "Re-photograph" for the **whole** score (AC12), not a single page, since a failed voice has no single bad page (`pageIndex` is `null`). On `synthesis_failed` the retry-later copy stays and no retake is offered.
8. On successful completion, automatically routes to Playback for the newly processed score within 2 seconds of receiving the `complete` status. *(Amended 2026-10-14: when the `complete` status has an `unreadable` voice, the AC11 offer comes first, and routing waits for the user's choice.)*
9. **Run in the background** *(added 2026-10-08, user decision)*:
   - A "Convert in Background" button sits below Cancel Scan. A back arrow in the top-left corner and the Android system back do the same thing: return to the Score Library without cancelling the scan.
   - The scan keeps running and its status keeps being polled after the user leaves this screen. Polling belongs to one app-level progress source, not to this screen's lifecycle. Polling stops when the job reaches a terminal state (`complete`/`failed`/`cancelled`), when the job is gone (404) or the session has expired (401), or when it pauses after 30 s of continuous poll failures. Resuming a paused background job without opening Processing is PIYA-218 AC10.
   - Reopening Processing for a job that is still running shows its current progress immediately, without restarting from 0%. Reopening it for a job that has already completed routes straight to Playback.
   - The library card and notification bell that show this background progress are specified in PIYA-218 and read the same progress source, so the three never disagree.
10. **Muted-measures alert on completion** *(added 2026-10-09, user decision)*. When processing first completes and the PIYA-103 result has a non-empty `mutedMeasures`, the app shows a system alert (`AlertDialog`) saying those measures were too damaged to play and will be silent, and listing them: voice and measure ("Bass: m. 4"), or page and system when `bar` is `null` ("Bass: page 1, system 2", counting from 1 for display). The dialog has a "Don't show again for this score" option, saved on the device per `scoreId`, which also stops the Playback alert (PIYA-208). When completion routes straight into Playback (AC8), the alert is shown once, not again when Playback opens. The review banner (PIYA-208) is unaffected. *(Amended 2026-10-14, user decision 2026-10-14: "Muted-measure alert shows on first Playback open per score, not on Processing".)* Processing never shows this alert. Playback (PIYA-208) shows it the first time it opens for the score, whether from Processing or from the library, bell or notification, with the same content and the same "Don't show again for this score" option. The sentence above about showing it once on completion and not again on Playback no longer applies.
11. **Re-photograph offer for an unreadable voice** *(added 2026-10-14, user decision 2026-10-14: "When a voice fails completely, the app offers re-photograph AS SOON AS PROCESSING IS DONE, before Playback opens (for background scans: when the user taps the finished score in library/notification). Dialog: names the voice(s), buttons "Re-photograph" and "Continue with N voices"." Also user decision 2026-10-14: "Offer re-photograph ONLY when photos are the cause")*. When a job reaches `complete` and PIYA-102 `failedVoiceCauses` (PIYA-102 AC7) has at least one `"unreadable"` value, the app shows a system alert (`AlertDialog`) before Playback opens.
    - It names the unreadable voice(s), e.g. "The Tenor part couldn't be read from these photos", and says that re-photographing the whole score may fix it.
    - Buttons: "Re-photograph" (AC12) and "Continue with N voices". N is 4 minus the length of `failedVoices`, i.e. the voices that will actually play, so a `render_failed` voice is not counted. "Continue" opens Playback.
    - Foreground: shown on Processing in place of AC8's automatic route. Background scan: shown when the user taps the finished score's library card, bell row or push notification (PIYA-218 AC3, AC6, AC7), before Playback.
    - Later retakes are offered from Playback (PIYA-208, PIYA-209). The post-processing offer itself stays once per job: after either button it is not shown again for that `jobId` (saved on the device). System back dismisses it to the Score Library without opening Playback, and it is offered again on the next tap.
    - A result whose failed voices are all `render_failed` never shows it. It goes straight to Playback, where the PIYA-208 failed-voice alert covers it.
12. **Whole-score retake** *(added 2026-10-14, user decision 2026-10-14: "Re-photograph retakes the WHOLE score: back to Capture with pages cleared, title/details kept (a failed voice has no single bad page)")*. "Re-photograph" (from AC11, or the AC7 `incomplete_voice_sequence` failure view) opens Capture (PIYA-206) with no pages. The score-details screen is pre-filled, and editable, with the title, arranger, tempo, key and time signature submitted for that job. Submitting calls PIYA-101 with `replacesJobId` set to the old job (PIYA-101 AC12) and routes to Processing as usual. Leaving Capture without submitting changes nothing.
    - A completed score keeps its `scoreId` and its library card. While the retake runs, the card shows as processing (PIYA-218 AC4) and the old version cannot be opened (confirmed, user decision 2026-10-14). If the retake fails or is cancelled, the card goes back to the old result, and the failure is reported through the bell and toast as a failed scan. *(Implementation note 2026-10-14: the card's "processing" visual, the bell and the toast are deferred to PIYA-218 AC4/AC5/AC7. Until then a tap on the card while its retake runs opens Processing, and a failed or cancelled retake is reported with a library snack bar.)*
    - A failed job's card is replaced by the new scan's card.
    - Device-side flags for a result (the AC10 / PIYA-208 "Don't show again" and the AC11 offer) are keyed by `jobId`, so the retake's result shows its own alerts. This replaces "saved on the device per `scoreId`" in AC10.
    - Details source: PIYA-102 returns the job's submitted details on every status (PIYA-102 AC8), for failed and completed jobs alike, so the app pre-fills from one PIYA-102 call on the old `jobId`, including after a reinstall.

---

### PIYA-208 — Score Playback UI
**User Story:** As a choir member, I want to view my processed score with synced audio playback, so that I can follow along while listening to my part.

**Process:**
1. User opens a processed score from Score Library or completes processing.
2. System displays score image with playback controls.
3. User selects a voice part, plays the audio, follows the synced indicator.

**Acceptance Criteria:**
1. Displays the original preprocessed captured score image (not a re-engraved rendering), per FR-8.
2. Displays voice selection chips for S/A/T/B, allowing single or multiple selection.
3. On first open, default selected voice matches user's onboarding voice preference (PIYA-201), if set.
4. Play/pause, skip-back, skip-forward controls present and functional.
5. Seek bar reflects current playback position and total duration, allows jumping to any point.
6. A vertical playback indicator overlays the score image, updates horizontal position in sync with audio timestamp, using timing metadata from PIYA-103.
7. Tapping/dragging the seek bar updates the playback indicator's position within 200ms.
8. Voice Mixer and Speed controls accessible from this screen without navigating away.

**Design decisions (2026-10-09, user):** these refine the ACs above without replacing them.
- Transport: ±5 s buttons (Netflix-style), plus ⏮, which jumps to the start of the first measure (m.1), and ⏭, which jumps to the **start** of the last measure (e.g. m.15 of 15). This needs `bar` on every timing event (PIYA-117 AC7). When the piece opens with a pickup (`bar: 0`), ⏮ goes to the very start (t=0) so the pickup is heard. When no event has a `bar`, ⏮ goes to t=0 and ⏭ to the last event.
- The playback indicator band spans the whole system (all four staves), not a single staff (see PIYA-117 AC8).
- Grey text and chip text are darkened just enough to meet WCAG AA contrast.
- A dismissible "automatic transcription — some notes may be wrong" banner appears when PIYA-103 `review.reviewNeeded` is true (see PIYA-216 AC4).
- Mixer, Speed and Download open placeholder sheets until PIYA-209, PIYA-210 and PIYA-211 land.
- The header shows the title and, when present, "arr. by <arranger>" (matches the mockup). The value is the score's `arranger` field (PIYA-101 AC8 / PIYA-103 AC7 / PIYA-308 AC3); with no arranger the line is left out. *(2026-10-09: the field was renamed from `composer`, user decision — it holds the arranger.)*
- Audio plays only while the Playback screen is open. Leaving the screen or sending the app to the background pauses/stops playback. Offline or background listening is what Export (PIYA-211) downloads are for.
- If one voice's track fails to load or drops out, the other voices keep playing; that voice's chip is disabled with a short notice. The score fails as a whole only if no track can play.
- Bundled demo data (the fake API) exists in debug/fake builds only, never in release builds.
- **Whole-voice failure alert** *(added 2026-10-09, user decision)*. On opening Playback, if any voice failed as a whole, either listed in PIYA-103 `failedVoices` or because its audio fails to load or play on the device, the app shows a system alert (`AlertDialog`) at the start. It names the voice as wholly corrupted and says the other voices will play. If that voice was the user's selected voice, all the remaining voices are turned on and play. The failed voice's chip is disabled. This alert replaces the "short notice" above for a voice that fails when Playback opens. *(Amended 2026-10-14, user decision 2026-10-14: "A voice that was read but Stage 5 couldn't render (`render_failed`) keeps the existing failed-voice alert + "try again later", no re-photograph".)* The alert names only the voices whose PIYA-103 `failedVoiceCauses` value is `"render_failed"`, with "try again later" copy, plus voices that fail on the device. `unreadable` voices were already reported by the PIYA-207 AC11 offer and are not repeated here. Their chips are still disabled, and they still count as failed for the selected-voice rule above. *(Added 2026-10-14, user decision 2026-10-14.)* Tapping an `unreadable` voice's disabled chip shows a system alert: "<Voice> couldn't be read from the photos", with "Re-photograph" (the PIYA-207 AC12 whole-score retake) and "Cancel". It can be used any number of times. A `render_failed` voice's disabled chip does not offer it.
- **Muted-measures alert** *(added 2026-10-09, user decision)*. If PIYA-103 `mutedMeasures` is non-empty, the same alert as PIYA-207 AC10 (listing voice + measure, or page/system when `bar` is `null`) is shown each time Playback opens, unless "Don't show again for this score" was ticked for this `scoreId`. When Playback is opened straight from Processing, it is not shown a second time. The review banner is shown as before, independently of this alert. *(Amended 2026-10-14, user decision 2026-10-14: shown on the first Playback open per score, not on Processing (PIYA-207 AC10). "When Playback is opened straight from Processing, it is not shown a second time" no longer applies, since Processing never shows it. Later opens follow the rule above.)* Stated explicitly (user decision 2026-10-14): the alert shows on every Playback open of the score until "Don't show again for this score" is ticked. *(2026-10-14, per PIYA-207 AC12: "Don't show again" is stored per `jobId`, not per `scoreId`, so a whole-score retake (a new job) resets it and the retake's result shows its own alert.)*
- **Metronome click** *(added 2026-10-09, user decision)*: laid out per measure from the timing file's `bars` table (PIYA-117 AC9) by the rules in PIYA-210.

---

### PIYA-209 — Voice Mixer Modal UI
**User Story:** As a choir member, I want to adjust the volume of each voice part individually, so that I can focus on my part while still hearing context from others.

**Process:**
1. User taps Voice Mixer from Playback.
2. System displays modal with per-voice volume controls.
3. User adjusts sliders or mutes specific voices; changes apply immediately.

**Acceptance Criteria:**
1. Displays individual volume slider for each of the four SATB voices, plus Metronome Click.
2. Displays a Mute toggle per voice/metronome, independent of slider position.
3. Adjusting a slider updates that voice's playback volume in real time, audible within 100ms.
4. Muting a voice sets audible volume to zero without resetting slider position, so unmuting restores prior volume level.
5. All voices default to unmuted at full volume the first time a score is opened.
6. Mixer settings persist for the duration of the playback session but reset to default when reopened later, unless otherwise specified.
7. Modal dismissible via close (X) button, returns to Playback without interrupting active playback.

**Design decisions (2026-10-09, user):**
- Each row has a Solo checkbox. When any row is soloed, only soloed rows are heard; Mute still wins over Solo.
- The Metronome Click row sets the click's volume and Mute only. Whether the click plays at all is the Speed modal's toggle (PIYA-210 AC3). The click is heard only when that toggle is on and the row is not muted.
- Mixer volumes stack with the Playback voice chips (PIYA-208): an unselected chip is silent whatever its slider says.
- **Soloing a voice whose chip is off** *(added 2026-10-09, user decision)*. Ticking Solo on a voice whose chip is off on the Playback screen shows a system alert (`AlertDialog`) explaining that nothing will be heard from that voice while its chip is off, with a "Turn <Voice> on" action that turns the chip on.
- **Unreadable voice row** *(added 2026-10-14, user decision 2026-10-14)*. A failed voice's row is disabled (no Solo, no slider; gap-doc resolution 7). Tapping the disabled row of an `unreadable` voice (PIYA-103 `failedVoiceCauses`) shows the same alert as the PIYA-208 chip: "<Voice> couldn't be read from the photos", with "Re-photograph" (PIYA-207 AC12 whole-score retake) and "Cancel". Choosing Re-photograph closes the Mixer and leaves Playback for Capture. A `render_failed` row shows no retake.

---

### PIYA-210 — Playback Speed Modal UI
**User Story:** As a choir member, I want to slow down playback speed, so that I can practice difficult sections at my own pace.

**Process:**
1. User taps Speed from Playback.
2. System displays modal with speed slider and metronome toggle.
3. User adjusts speed; changes apply to active and subsequent playback.

**Acceptance Criteria:**
1. Displays speed slider with default value of 90 (matching system's default tempo per FR-9/NFR).
2. Adjusting slider changes playback speed without altering pitch.
3. Displays a Metronome Click toggle, independent of the Voice Mixer's metronome control, adding an audible click track synced to current tempo.
4. Speed changes apply immediately if audio is currently playing, without requiring restart.
5. Modal dismissible via close (X) button, returns to Playback without interrupting playback.

**Design decisions (2026-10-09, user):**
- The slider is in BPM, range 30–240 (same as the tempo field at capture, PIYA-101 AC8). It opens at the score's `tempoBpm` (PIYA-103 AC8), which is 90 unless another tempo was entered. Playback rate = chosen BPM ÷ `tempoBpm`, with pitch kept. *(added 2026-10-09, user decision: the value is quarter-note BPM whatever the meter and is labelled that way, e.g. "♩ = 90". 30–240 is a hard cap; the user confirmed 240 is high enough.)*
- The Metronome Click checkbox turns the click on or off (off by default). Its volume and Mute live in the Voice Mixer (PIYA-209). The click is generated in the app at the chosen BPM, one click per quarter note, and stays aligned to the start of bar 1. *(added 2026-10-09, user decision: "one click per quarter note" is replaced by the per-measure layout below. It remains only as the fallback for a timing file with no `bars`.)*
- **Metronome click layout** *(added 2026-10-09, user decision; matches MuseScore's metronome, rules from choral-conductor research)*. Clicks are laid out measure by measure from the timing file's `bars` table (PIYA-117 AC9). Each measure uses its own meter and its clicks restart at its barline (`startTick`), so consecutive measures may change meter. A click at tick `t` sounds at `t × 60000 ÷ (480 × chosen BPM)` ms.
  - **Unit:** one 1/`denominator` note (`1920 ÷ denominator` ticks).
  - **Compound meter:** `numerator > 3` and `numerator % 3 == 0` (6/8, 9/8, 12/8, 6/4…). Its beat is 3 units. The beat tempo at the current playback speed is chosen BPM × `denominator` ÷ 12 beats per minute (6/8 at ♩ = 90 is 60). If the beat tempo is 60 per minute or more, click each beat; below 60, click every unit.
  - **Simple meter** (every other meter): click every unit, so 2/2 clicks half notes and 3/8 clicks eighths.
  - **Odd non-compound numerator of 5 or more** (5, 7…): units grouped `ceil(n/2) + floor(n/2)`, i.e. 5 = 3+2 and 7 = 4+3.
  - **Accent levels**, loudest first: downbeat (offset 0 of the measure), secondary (the first click of each later group: beat 3 of 4/4 and of 12/8, following MuseScore's `stressEvery` rule, and the start of the second group in 5 and 7), beat (every other beat click), subdivision (a unit click that is not on a beat, which only happens in a slow compound meter).
  - **Pickup** (`pickup: true`): its clicks are placed as the **end** of a full bar of its meter and take the accent of that full-bar position. A pickup click is never a downbeat.
  - **Short final bar:** clicks from its barline and stops at its end (`durTicks`).
  - **Unknown meter:** a measure whose `meterSource` is `unknown` or `default` uses the last measure with a `detected` or `inherited` meter. If there is none, it gets a plain quarter-note grid from its barline with only the first click accented (downbeat), and no secondary accents.
  - **Speed changes:** when a speed change makes a compound measure's beat tempo cross 60 per minute (either way), the clicks not yet played are re-planned. Other speed changes only rescale the click times.
- **No count-in** *(user decision 2026-10-14: "No count-in bar for the metronome.")*. The first click sounds at t=0 with the music, on the pickup's first click or bar 1's downbeat. No clicks are added before it.
- Speed and metronome settings last while the Playback screen is open and reset when the score is reopened, like the mixer (PIYA-209 AC6).

---

### PIYA-211 — Export Audio Modal UI

**User Story:** As a choir member, I want to download selected voice tracks, so that I can rehearse offline without needing the app open.

**Process:**
1. User taps the download icon from Playback.
2. System displays the Export Audio modal.
3. User selects voice(s)/options and taps **Download Audio**.
4. User selects a download location and taps confirm.
5. System saves the file(s) and displays a success confirmation.

**Preconditions:**
- The download icon is available only for scores with status `completed` from processing stage.

**Acceptance Criteria:**

*Modal and selection*
1. The Export Audio modal displays a selectable checklist: Soprano, Alto, Tenor, Bass, All Voices, and a "With Metronome Click" toggle.
2. All checkboxes and the metronome toggle are unselected by default each time the modal opens.
3. Selecting "All Voices" automatically selects all four individual voices.
4. Deselecting "All Voices" deselects all four individual voices.
5. Deselecting any individual voice automatically deselects "All Voices."
6. Manually selecting all four individual voices automatically selects "All Voices."
7. When "With Metronome Click" is ticked, the metronome click is mixed into the exported file, lined up with the bars (the same per-measure click Playback uses, PIYA-210 "Metronome click layout"). When it is not ticked, the file has no click. The checkbox is disabled, with the Speed modal's note, when the score has no known tempo (`tempoKnown == false`). *(Decided 2026-10-17, user decision: click mixed in, not a separate file.)*
8. The **Download Audio** button is disabled until at least one voice option is selected.
9. The user can dismiss the modal (close button, tap outside, or back gesture) without downloading. No files are created and the selections are discarded.

*Download flow*
10. Tapping **Download Audio** prompts the user to choose a download location and confirm.
11. Cancelling the location prompt returns the user to the modal with selections intact.
12. While files are being prepared and saved, a progress indicator is shown and **Download Audio** is disabled to prevent duplicate downloads.
13. The export is **one file**: the ticked voices mixed together. "All Voices" ticks every available voice, so it gives one file of the full choir. A voice that can't play (failed or unreadable) can't be ticked. *(Decided 2026-10-17, user decision: one mixed file, not one file per voice.)*
14. The file is saved as MP3 and named `[ScoreName]_[Voices][_Click].mp3`. Voices is `AllVoices` when every voice is ticked, else the ticked voice names joined by `-` in SATB order. `_Click` is added when the click is included. Example: `ClairDeLune_Soprano-Alto_Click.mp3`. Characters not allowed in file names (`/ \ : * ? " < > |`) become `_`, and an empty title becomes `Score`. *(Decided 2026-10-17, user decision.)*
15. If a file with the same name already exists in the chosen location, the new file gets a number suffix, ` (1)`, ` (2)` and so on (`X (1).mp3`), and nothing is overwritten. *(Decided 2026-10-17, user decision.)*

*Success*
16. On success, the system displays a confirmation with the saved file name(s) and location, and an option to open the location.
17. Downloaded files remain accessible and playable without an internet connection, per NFR-4.

*Errors*
18. Download failure displays a specific error message distinct from a generic failure. At minimum:
    - Storage full
    - Permission denied
    - File generation failed
    - Download interrupted (e.g., connection lost or app closed)
19. On failure the modal keeps the selections and offers **Retry**. *(Decided 2026-10-17: with one file there is no partial success to report.)*
20. If storage permission is denied, the error message explains how to enable it.

*Non-functional*
21. Checkbox and toggle labels are readable by screen readers, and the toggle's on/off state is announced.
22. All tappable elements meet the minimum touch target size for the platform.

*Playback settings*

23. The export uses the current Playback speed (the Speed modal's BPM, as rate = chosen BPM ÷ `tempoBpm`, pitch kept per FR-9) and the Voice Mixer levels, Mute and Solo, including the Metronome Click row's level. A ticked voice that the Mixer mutes, or leaves out with a Solo, is noted under its row ("Muted in Voice Mixer"); the export is still allowed. *(Added 2026-10-17, user decision.)*

---

### PIYA-212 — Settings UI
**User Story:** As a user, I want to view my account details and manage app-level options, so that I can manage my session and app info in one place.

**Process:**
1. User taps Settings tab from bottom navigation.
2. System displays account info and app options.
3. User can log out from this screen.

**Acceptance Criteria:**
1. Displays logged-in user's email address (read-only).
2. Displays current app version number.
3. A Log Out action is present; tapping clears local session token and routes to Login.
4. Log Out requires a confirmation step (e.g., "Are you sure you want to log out?") before executing.
5. Settings screen only reachable with a valid session; if session expired, tapping Settings routes to Login instead.
6. **Change password.** An in-app form with current password, new password and confirm new password. The new password follows the Sign-Up strength rules (PIYA-203). A 401 from the API shows "Your current password is incorrect." next to the current-password field. Calls the change-password API (PIYA-322 stub in `module3-backend.md`), faked until Module 3 builds it. *(Added 2026-10-17 for v1, user request.)*
7. **Default voice.** Soprano, Alto, Tenor or Bass. It is the same preference onboarding writes (PIYA-201), so Playback (PIYA-208 AC3) picks it up when a score is opened. *(Added 2026-10-17 for v1, user request.)*
8. **Default tempo.** 30–240 BPM, default 90. Used only when a score is submitted with Speed set to "Not sure" (sent as `fallbackTempoBpm`, see `module3-backend.md`). Scores already scanned keep their tempo. *(Added 2026-10-17 for v1, user request.)*
9. **Help.** A help (ⓘ/?) button next to Default voice and Default tempo opens a short explanation of what each setting does. *(Added 2026-10-17 for v1, user request.)*

---

### PIYA-213 — Offline State UI
**User Story:** As a user, I want to be clearly notified when I have no internet connection, so that I understand why the app isn't working rather than assuming it's broken.

**Process:**
1. Device loses internet connectivity while using the app.
2. System detects the lost connection.
3. System displays a dedicated offline notice, distinct from other error states.

**Acceptance Criteria:**
1. Connectivity loss detected within 5 seconds of the connection dropping.
2. Displays a persistent, non-dismissible banner or full-screen state (contextual to where user is) indicating no internet connection, satisfying NFR-4.
3. Actions requiring connectivity (Capture submission, Login, Sign-Up) are disabled while offline, with offline notice shown instead of allowing a failed submission attempt.
4. Previously downloaded audio tracks (via Export) remain playable while offline.
5. Offline state automatically clears and normal functionality resumes within 5 seconds of connectivity restoration, without requiring an app restart.

---

### PIYA-218 — Scan Status in Library & Notification Bell UI
*(Added 2026-10-08, user request. Full design spec: `mobile/piyanota_application/references/scan-status-and-notifications-spec.md`. Depends on PIYA-207 AC9.)*

**User Story:** As a choir member who sent a scan to convert in the background, I want to see its progress from the Score Library and be told when it's ready or has failed, so that I can keep using the app instead of waiting on the Processing screen.

**Process:**
1. User submits a score, then taps Convert in Background (or Back) on Processing (PIYA-207).
2. The Score Library shows the score as a processing card with live progress, and the header's notification bell shows that a scan is active.
3. When the scan finishes, the card and the bell update in place, and the user is notified (an in-app toast, or a push notification if the app is in the background).
4. User taps the card, the bell row, or the notification and lands on Processing, Playback, or the failure view, depending on status.

**Acceptance Criteria:**
1. **One source of truth:** the library card, the bell panel and the Processing screen all read the same app-level progress source as PIYA-207 AC9. Percent, page and stage are identical in all three at any moment. UI updates are throttled to at most once every 1–2 seconds.
2. **Score states:** every score has exactly one status: `processing`, `completed`, `failed` or `cancelled`. A score shows in the library as `processing` from the moment its scan is submitted. A `cancelled` score is removed from the library.
3. **Navigation rule (every tap handler):** `processing` opens Processing (PIYA-207); `completed` opens Playback (PIYA-208); `failed` opens the PIYA-207 failure view. PIYA-207 offers Retake page (where its AC7 allows it) and Back to library; this ticket adds a Delete action to that view, which calls PIYA-309 and confirms first. A score that completed while the user was elsewhere routes to Playback, never to a stale Processing screen. *(Amended 2026-10-14, user decision 2026-10-14: a `completed` score whose result has an `unreadable` voice shows the PIYA-207 AC11 offer before Playback until it has been answered for that `jobId`. A `failed` score with `incomplete_voice_sequence` offers the whole-score "Re-photograph" (PIYA-207 AC12) in the failure view.)*
4. **Library processing card:** shows the title, a small progress bar or ring, and the label "Converting… N%", with a dimmed thumbnail or the scanned page. Tap follows AC3. Long-press offers "Cancel scan", using the same confirm dialog and PIYA-114 call as PIYA-207 AC4. On completion the card turns into a normal score card in place, without reloading the whole list.
5. **Bell states (library header):**
   - Idle: a plain bell.
   - Any scan active: a subtle animated ring or spinner on the bell.
   - Unread items: a red dot or count badge, for completed and failed items only. In-progress scans never add to the badge.
6. **Bell panel:** tapping the bell opens a panel or modal listing recent items newest first, with the following rows:
   - **Processing:** "[Score] is still being converted. Hang on tight!" plus a live progress bar. Tap opens Processing. Not dismissible while active.
   - **Completed:** "[Score] is ready to play" plus a relative time ("Just now"). Unread rows have a dot or bold title. Tap opens Playback and marks the row read.
   - **Failed:** "[Score] couldn't be converted" / "Tap to see what happened". Tap opens the failure view (AC3).
   - A processing row turns into its completed or failed row **in place**. A score never has two rows.
   - "Mark all as read". Swipe to dismiss completed and failed rows. Keep the latest 20 items or 7 days, whichever is fewer. Empty state: "No notifications yet."
7. **Completion feedback:** when a scan completes or fails while the app is in the foreground (and the user isn't on that scan's Processing screen), show an in-app banner or toast: "[Score] is ready. [Open]" (or its failure equivalent). When the app is in the background or closed, send a system push notification, "Your piano guide for [Score] is ready.", and tapping it opens Playback for that score directly.
8. **Survives app restarts:** job status and notification items persist on the device. On reopen the app restores processing cards and bell rows, re-polls PIYA-102 for every job that isn't terminal, and reflects anything that finished while the app was closed. The scan itself keeps running server-side regardless of the app. *(Note 2026-10-14, PIYA-207 AC12: the persisted job must include which score a whole-score retake replaces (`retakeOfScoreId`), so after a restart the old card still can't be opened while its retake runs. Today the tracker is in memory only, so that block is lost on restart until this AC is built.)*
9. **Multiple scans:** several scans can run at once, each with its own card and its own bell row. The bell's active ring shows while any scan is running.
10. **No endless progress:**
    - With no connection, or after repeated failed polls, cards and rows show a "Paused" state with Retry instead of a frozen bar. Paused background jobs resume polling by themselves when connectivity returns (`connectivity_plus`), without the user opening Processing.
    - A scan whose percent hasn't changed for 90 s shows "Still working, this one's a long piece."
11. **Notification permission:** Android 13+ `POST_NOTIFICATIONS` is requested once, in context: the first time a scan is sent to the background, with a one-line reason. If it is denied, the bell and in-app banners still work and the app doesn't ask again on every scan.
12. **Copy:** user-facing text says "scan" and "piano guide", matching the spec's §9 copy table. It doesn't mix in "process"/"convert" except in the spec's own row and card labels.

**Backend dependencies (to confirm with backend-lead before build):**
- PIYA-308 must return in-progress scans (status, percent, jobId) alongside completed ones. Alternatively the client merges its locally tracked jobs, but then a reinstalled app loses them.
- `docs/tickets/module3-backend.md` currently inserts the `scores` row only when the job completes (PIYA-321 AC4), which conflicts with AC2.
- PIYA-101/310's submit response needs `scoreId` too, so a processing card can be linked to its job before completion. The client tracker stores `jobId`, the title, and `scoreId` once known.
- Interim gap until this ticket lands: after "Convert in Background", tapping that score in the library opens Playback for an unfinished score.
- PIYA-102 needs `scoreId` in the `complete` payload to open Playback (also an open gap for PIYA-207 AC8).
- Push notifications when the app is closed need a server-side push sender (e.g. FCM) and device-token registration. Neither is in Module 3's tickets yet. Until they exist, AC7's background half can only be met while the OS keeps the app's background poll alive.

## Integration Tickets

### PIYA-214 — Auth Flow Integration
**Trigger:** Internal — build task, Sprint 8 finish (Oct 6–12), following PIYA-301–304 completion.
Wires Login (PIYA-202), Sign-Up (PIYA-203), and Password Reset (PIYA-204) screens to their corresponding APIs (PIYA-301–304).

**Acceptance Criteria:**
1. Each screen constructs requests matching PIYA-301–304's exact field names, handles every documented response code (200/201/400/401/409/410) with the specific UI state defined in PIYA-202–204.
2. On successful login/sign-up, returned session token is stored using Android's secure storage mechanism (Keystore-backed secure storage via flutter_secure_storage, not plain SharedPreferences), satisfying FR-21.
3. Every subsequent authenticated request automatically attaches the stored token; a 401 response anywhere in the app triggers automatic routing to Login.

---

### PIYA-215 — Score Library & Capture Integration
**Trigger:** Internal — build task, Sprint 8 finish (Oct 6–12).
Wires Score Library (PIYA-205) and Capture/Add Score (PIYA-206) to PIYA-101, PIYA-308, PIYA-309, PIYA-310.

**Acceptance Criteria:**
1. Score Library calls PIYA-308 on load, rendering loading/empty/error states exactly as defined in PIYA-205. The search bar filters the already-fetched list on the phone (title, arranger, displayed last-opened date and "New Score (n)" label) and does not call PIYA-308 per keystroke. PIYA-308's server-side `search` matches title and arranger only (PIYA-308 AC4). *(Amended 2026-10-08, backend-lead; replaces "calls PIYA-308 on load and on each search-bar keystroke (debounced)".)* *(2026-10-09: renamed from `composer`, user decision — the field holds the arranger.)*
2. Score deletion calls PIYA-309 and removes the entry from the displayed list only after a 200 response, not optimistically before confirmation.
3. Capture/Add Score routes to PIYA-101 or PIYA-310 per PIYA-206's logic, surfaces PIYA-101/310's 400/415/429 responses as the specific UI errors PIYA-206 defines.

---

### PIYA-216 — Processing & Playback Integration
**Trigger:** Internal — build task, Sprint 8 finish (Oct 6–12).
Wires Processing Status (PIYA-207) and Score Playback (PIYA-208) to PIYA-102 and PIYA-103.

**Acceptance Criteria:**
1. Processing Status polls PIYA-102 at the fixed interval defined in PIYA-207, maps status/percentComplete/failureReason directly to the UI states already specified there.
2. On `status: complete`, Playback calls PIYA-103 and binds `audioTracks`, `scoreImages`, `timingMetadataUrl` to the player, seek bar, and playback-indicator overlay as defined in PIYA-208.
3. A 409 response from PIYA-103 (job not yet complete) is handled defensively even though the UI shouldn't normally trigger it before `complete` status.
4. Playback shows its dismissible review banner (PIYA-208 design decisions) exactly when PIYA-103 returns `review.reviewNeeded: true`. While BUG-021 is open, that is every score. *(Added 2026-10-09.)*
5. Playback binds PIYA-103 `failedVoices` and `mutedMeasures` to the alerts in PIYA-208 (and PIYA-207 AC10), and reads the timing file's `bars` table (PIYA-117 AC9) for the metronome click (PIYA-210). A voice missing from `audioTracks` is treated as failed, not as an error for the whole score. *(added 2026-10-09, user decision)* *(2026-10-14: Processing and the PIYA-218 tap handlers also bind PIYA-102 `failedVoices` / `failedVoiceCauses` on `complete` to the PIYA-207 AC11 offer, and Playback's failed-voice alert reads `failedVoiceCauses` per PIYA-208.)*

*(2026-10-09: opening a saved score from the library is blocked on the open gap that PIYA-103 is keyed by `job_id`, while the library has only `scoreId`. See PIYA-308 AC8 in `module3-backend.md`. Until that is resolved, Playback runs against a fake keyed by score.)*

---

### PIYA-217 — Export & Settings Integration
**Trigger:** Internal — build task, Sprint 8 finish (Oct 6–12).
Wires Export Audio (PIYA-211) and Settings (PIYA-212) to their data sources — direct CDN URLs from PIYA-103, and PIYA-305/306/307.

**Acceptance Criteria:**
1. Export downloads selected voice track(s) directly from the `audioTracks` URLs returned by PIYA-103 — no separate export endpoint call needed, consistent with PIYA-103's design. *(2026-10-17: the app then mixes the ticked tracks, plus the click when ticked, on the device at the Playback speed and encodes one MP3, PIYA-211 AC13/AC23.)*
2. Settings calls PIYA-306 on load to populate account info, and PIYA-305 on logout, clearing the securely stored session token (per PIYA-214) on success.
3. Account deletion (if surfaced in Settings) calls PIYA-307, handles its password-confirmation requirement as a client-side prompt before the request is sent.