# Module 2: Mobile Application (Frontend — Android)

_Covers: UI tickets (Onboarding, Account, Score Library, Playback, Settings, System States) and Integration tickets._

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
8. On successful completion, automatically routes to Playback for the newly processed score within 2 seconds of receiving the `complete` status.

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

---

### PIYA-211 — Export Audio Modal UI
**User Story:** As a choir member, I want to download selected voice tracks, so that I can rehearse offline without needing the app open.

**Process:**
1. User taps download icon from Playback.
2. System displays Export Audio modal.
3. User selects voice(s)/options, taps Download Selected.

**Acceptance Criteria:**
1. Displays a selectable checklist: Soprano, Alto, Tenor, Bass, All Voices, and a "With Metronome Click" toggle.
2. Selecting "All Voices" automatically selects all four individual checkboxes; deselecting any individual voice automatically deselects "All Voices."
3. Download Selected button disabled until at least one voice option is selected.
4. Tapping Download Selected saves selected file(s) to local device storage, displays success confirmation with saved file name/location.
5. Downloaded files remain accessible and playable without internet connection, per NFR-4.
6. Download failure (e.g., storage full, permission denied) displays a specific error message distinct from a generic failure.

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
1. Score Library calls PIYA-308 on load and on each search-bar keystroke (debounced), rendering loading/empty/error states exactly as defined in PIYA-205.
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

---

### PIYA-217 — Export & Settings Integration
**Trigger:** Internal — build task, Sprint 8 finish (Oct 6–12).
Wires Export Audio (PIYA-211) and Settings (PIYA-212) to their data sources — direct CDN URLs from PIYA-103, and PIYA-305/306/307.

**Acceptance Criteria:**
1. Export downloads selected voice track(s) directly from the `audioTracks` URLs returned by PIYA-103 — no separate export endpoint call needed, consistent with PIYA-103's design.
2. Settings calls PIYA-306 on load to populate account info, and PIYA-305 on logout, clearing the securely stored session token (per PIYA-214) on success.
3. Account deletion (if surfaced in Settings) calls PIYA-307, handles its password-confirmation requirement as a client-side prompt before the request is sent.