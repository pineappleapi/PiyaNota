# Module 2: Mobile Application — Version 2 Change Tickets

_Created 2026-10-28 from the user's V2 change list. Version 1 = everything merged to `main` at 4d417ee (PIYA-201–212, 218). Each V2 ticket below is a change to a V1 ticket in `module2-mobile.md`. When a V2 ticket is built, its ACs are folded into the parent ticket there as "(V2, 2026-10-28)" amendments._

_Ticket IDs: `PIYA-2xx-V2.n` = change n to parent ticket PIYA-2xx. "Fake" means the built-in fake backend used in debug builds (`USE_FAKE_AUTH`, on by default). Backend changes these tickets need are listed in `module3-backend.md` → "V2 notes (2026-10-28)"._

_Marking: **[Call]** = a default chosen while writing this doc, not yet confirmed by the user; the user may override. "User-approved 2026-10-28" = a default the user confirmed._

---

## User decisions (2026-10-28)

Q1–Q6 were answered by the user on 2026-10-28. The answers are folded into the tickets below.

1. **[Q1] Multi-page Playback:** all pages stacked in one vertical scroll, page 1 then page 2 below it, joined page to page.
2. **[Q2] Default mix:** when a default voice is set, only that voice plays.
3. **[Q3] Unregistered email message:** accepted, including the trade-off that anyone can check whether an email has an account.
4. **[Q4] Wait schedule:** approved. Login waits start at the 1st wrong attempt. Reset-code waits start after the 3rd wrong code. Each wait doubles from 30 s up to a 15 min cap: 30 s, 1 min, 2 min, 4 min, 8 min, 15 min, then 15 min for every later wrong attempt.
5. **[Q5] "Page 2 of 4":** the label must be dynamic. It must update when photos are reordered, and when a thumbnail is tapped to select it.
6. **[Q6] Metronome:** switching it on makes the click heard straight away, but not when its Mixer row is muted or at 0.

---

## PIYA-201 — Onboarding

### PIYA-201-V2.1 — "I'm a Conductor / I'm not sure yet" is a selectable option
**Now:** the button on step 3 acts immediately (`onConductorTap`, `voice_selection_step.dart`).
**Acceptance Criteria:**
1. On step 3, "I'm a Conductor / I'm not sure yet" is a selectable option that looks and behaves like the Soprano, Alto, Tenor and Bass buttons: same selected/unselected styling, single choice across all five.
2. Selecting it does not leave the step. The user continues with Get Started, the same as after picking a voice.
3. When it is selected, the saved preference is "all voices" (the current conductor behaviour), so Playback opens with all four voices on (PIYA-208 AC3).
4. Selecting a voice after it, or the other way round, deselects the previous choice.

### PIYA-201-V2.2 — Splash screen on every app open
**Now:** the logo intro plays only inside first-launch onboarding (`onboarding_flow_screen.dart`).
**Acceptance Criteria:**
1. Every cold start shows the PiyaNota splash (the same logo intro animation as onboarding) before the first screen: Onboarding on first launch, Login/Sign-Up when signed out, or Score Library when a session is restored (PIYA-202-V2.2).
2. The splash also shows when the user comes back to the app from the background (warm resume). *(User decision 2026-10-28.)* It plays over the screen the user left. When it ends, that screen is shown exactly as it was: typed text, scroll position, open sheets and running exports/scans are all kept.
3. The splash does not show when the app comes back from a screen the app itself opened, such as the camera, the gallery or PDF picker, the folder picker, a permission dialog or Android settings opened from the app. **[Call: otherwise a splash would play after every photo pick.]**
4. The splash lasts no longer than the onboarding intro animation does today and cannot be skipped. **[Call]**
5. On first launch the splash plays once, then onboarding starts, without the intro playing twice.

---

## PIYA-202 — Login

### PIYA-202-V2.1 — Wait time after wrong email/password, growing with each wrong try
**Acceptance Criteria:**
1. After a wrong email/password, the Log In button is disabled for a wait time and shows a live countdown, e.g. "Try again in 0:30". The "Incorrect email or password" error (AC2) still shows.
2. Each further wrong attempt makes the next wait longer, following the [Q4] schedule.
3. The count resets after a successful login.
4. Closing and reopening the app does not reset the wait. The remaining wait and the count are saved on the device, per email. **[Call]**
5. The server enforces the limit as well (backend V2 note B1). When the server answers 429 with `retryAfterSeconds`, the app shows that wait instead of its own count.
6. A network failure (AC7) does not count as a wrong attempt.
7. Fake: the fake backend applies the same schedule, so it can be tested with `demo@piyanota.app` and a wrong password.

### PIYA-202-V2.2 — Stay signed in (auto-login)
**Now:** every launch goes through Login (`app.dart:126` note).
**Acceptance Criteria:**
1. When the user is signed in and closes the app, reopening it goes from the splash (PIYA-201-V2.2) straight to the Score Library, with no Login/Sign-Up screen.
2. Uses the session token already stored in secure storage (PIYA-214 AC2). If the token has expired (`expiresAt` passed) or the server answers 401, the app opens Login instead.
3. When there is no connection at launch and a token is stored and not expired, the app opens the Score Library in its offline/error state rather than Login. *(User-approved 2026-10-28.)*
4. Logout (PIYA-212 AC3) still clears the token, so the next launch opens Login.
5. A tap on a result notification on a cold start opens Playback for that score, not Login (replaces the PIYA-218 AC7 interim note).

---

## PIYA-203 — Sign-Up

### PIYA-203-V2.0 — (V1) "Already have an account? Log In" link
**Status:** already in the ticket as PIYA-203 AC8 (added 2026-10-17) and already built. Nothing to do except confirm on the phone.

---

## PIYA-204 — Password Reset

### PIYA-204-V2.1 — Separate messages for registered and unregistered emails
Per **[Q3]** (accepted).
**Acceptance Criteria:**
1. Registered email: the screen shows "A reset code has been sent to this email. Please check your inbox." and moves to Enter Code, as now.
2. Unregistered email: the screen shows "Email has not yet been registered. Create a new account?", where "Create a new account" is underlined and opens Sign-Up with the email pre-filled. **[Call: pre-filled]** No code is sent.
3. Replaces PIYA-204 AC2/AC3 (same message for both). Needs backend V2 note B3.

### PIYA-204-V2.2 — Resend countdown keeps running for the same email
**Now:** going back from Enter Code to Enter Email and submitting the same email restarts the 30 s countdown.
**Acceptance Criteria:**
1. The resend countdown belongs to the email address, not to the screen. Going back to Enter Email and submitting the same email shows Enter Code with the countdown still at its remaining time, and does not send a new code. **[Call: no new code]**
2. Submitting a different email starts that email's own countdown.
3. The countdown is kept while the app is open. It does not need to survive closing the app. **[Call]**

### PIYA-204-V2.0 — (V1) Resend only after 30 s
**Status:** already in the ticket as PIYA-204 AC6 (added 2026-10-17) and already built (`_resendCooldownSeconds = 30`). V2.2 above changes only how the countdown is kept.

### PIYA-204-V2.3 — Real code by email
**Acceptance Criteria:**
1. The code the user types is the 6-digit code from the reset email (backend V2 note B4). The app never shows the code itself.
2. Fake: the fake backend keeps its stand-in inbox (`demoInboxCodeFor`) for testing. Debug builds only.

### PIYA-204-V2.4 — Wrong code message and wait after 3 wrong codes
**Acceptance Criteria:**
1. A wrong code shows "Verification code is wrong. Try again." and keeps the typed passwords.
2. After 3 wrong codes, the Submit button is disabled with a live countdown. Each further wrong code makes the wait longer, following the [Q4] schedule.
3. An expired code keeps its own message (code expired, request a new one), separate from "wrong".
4. A successful reset, or a new code being sent, resets the wrong-code count. **[Call]**
5. The server enforces the limit (backend V2 note B4); a 429 `retryAfterSeconds` overrides the app's own count.

---

## PIYA-205 — Score Library

Reference: `mobile/piyanota_application/references/PIYA205_HomePage_Version2.png`.

### PIYA-205-V2.1 — Header layout: logo left, bell far right
**Now:** logo top-right at 0.4 opacity, bell just left of it (`library_header.dart`, `AppTheme.libraryHeaderLogoOpacity`).
**Acceptance Criteria:**
1. The PiyaNota logo sits on the left of the header, touching the left screen edge, behind "My Scores", the subtitle and the search bar, as in the reference image.
2. It is larger than now, about the header's full height as in the reference. Exact size is dropper/pixel-matched to the reference (design-fidelity workflow).
3. It is shown at 10% opacity. **[Call: the note says "10% transparent", but the reference shows a faint mark, so this reads it as 10% visible.]**
4. The notification bell is in the far top-right corner of the header.
5. Title, subtitle, search bar and bell stay fully readable and tappable over the logo.

### PIYA-205-V2.2 — Space between card title and details
**Acceptance Criteria:**
1. Each score card has a small visible gap between the title and the details line ("arranger • N pages"), as in the reference.
2. A title that wraps to 2 or 3 lines never overlaps or touches the details line; the gap stays the same and the card grows.

### PIYA-205-V2.3 — No demo scores flash on a new account
**Now:** after signing up, the demo scores show for a moment, then the empty state replaces them.
**Acceptance Criteria:**
1. After sign-up or login, the library shows its loading state until the new account's list has loaded. Scores from a previous account, or demo data, are never shown, even briefly.
2. A new account goes from loading straight to the empty state ("No Scores • Tap Capture Button").
3. Same for switching accounts: log out of `demo@piyanota.app`, sign in as a new account, and no demo score appears.

### PIYA-205-V2.4 — Edit score details (title and arranger)
**Acceptance Criteria:**
1. Each completed or failed score card has an Edit action. A pencil icon next to the trash icon *(user-approved 2026-10-28)*. Processing cards have no Edit.
2. Edit opens a form with only Title (required) and Arranger (optional), pre-filled. Key, tempo and time signature are not editable.
3. Validation matches the capture details screen (PIYA-206 / PIYA-101 AC8 rules and messages).
4. Save calls the update-score API (backend V2 note B5). On success, the card shows the new values without reloading the whole list. On failure, the old values stay and an error is shown.
5. Cancel discards changes.
6. Playback's header (title, "arr. by") shows the edited values next time it opens.
7. Fake: the fake library stores the edit for the session; `@flaky.test` accounts fail it every other time, like delete.

---

## PIYA-206 — Capture / Add Score

### PIYA-206-V2.1 — "Page X of N" label is always correct
Per **[Q5]**.
**Acceptance Criteria:**
1. The "Page X of N" label always shows the position of the selected photo in the current order.
2. Tapping a thumbnail selects that photo. The large preview shows it, and the label updates to its position straight away.
3. After a thumbnail is dragged to a new position, the label updates to the selected photo's new position. The selected photo stays selected.
4. Deleting, adding or undoing a page also updates X and N.

### PIYA-206-V2.2 — Reordering works with 2 pages
**Acceptance Criteria:**
1. With 2 pages, dragging one thumbnail onto the other swaps them. Reordering works for any count of 2 or more.
2. With 1 page there is nothing to reorder, and no error is shown.

### PIYA-206-V2.3 — Camera does not take a photo by itself
**Now:** choosing Camera from + takes a photo straight away.
**Acceptance Criteria:**
1. Choosing Camera from the + menu opens the live viewfinder. No photo is taken until the user taps the shutter.

### PIYA-206-V2.4 — Retake mode replaces one page only
**Acceptance Criteria:**
1. When Capture opens to retake one page (from a PIYA-207 error), only that page can be captured or picked. Add page, Gallery multi-select and PDF are hidden or disabled.
2. After one photo is taken and confirmed, it replaces that page and the user goes on to submit.

### PIYA-206-V2.5 — One PDF per score
**Acceptance Criteria:**
1. A score can contain at most one PDF file. After a PDF is added, the PDF option is disabled. Picking a second PDF shows "Only one PDF can be added per score."
2. A score is either one PDF or a set of photos, never both. **[Call: matches PIYA-206 AC8's single endpoint per submit.]**
3. Removing the PDF enables the PDF option again.

---

## PIYA-208 — Score Playback

### PIYA-208-V2.1 — Time labels at the ends of the seek bar
**Acceptance Criteria:**
1. The elapsed time sits directly under the left end of the seek bar, and the total time directly under the right end.
2. The gap between bar and labels is small, as in the playback mockup.

### PIYA-208-V2.2 — Audio pauses while dragging the seek bar
**Acceptance Criteria:**
1. While the user drags the seek bar, audio is silent and the indicator follows the thumb (AC7, within 200 ms).
2. On release, playback continues from the new position if it was playing before the drag, and stays paused if it was paused. *(User-approved 2026-10-28.)*
3. All four voices and the click stay in sync after release.

### PIYA-208-V2.3 — Zoomable score
**Acceptance Criteria:**
1. The score image can be pinch-zoomed (1× to 4×, user-approved 2026-10-28) and panned while zoomed.
2. The playback indicator band stays on the right place at any zoom.
3. Double-tap returns to 1×. *(User-approved 2026-10-28.)*
4. Zoom resets when the score is reopened.

### PIYA-208-V2.4 — Multi-page layout: one vertical scroll
Per **[Q1]**.
**Acceptance Criteria:**
1. All pages of the score are stacked top to bottom in one vertical scroll, in page order, with page 2 joined directly below page 1, and so on.
2. The playback indicator band moves onto the next page when the audio reaches it.
3. While playing, the view scrolls by itself to keep the indicator band on screen. If the user scrolls by hand, auto-scroll pauses until they tap play again or seek. **[Call]**
4. Seeking (seek bar, ⏮, ⏭, ±5 s) scrolls to the page and system that hold the new position.
5. Zoom (V2.3) applies to the whole stack, and scrolling still works while zoomed.
6. A one-page score looks the same as now.

### PIYA-208-V2.5 — Voice chips on one line, in voice colours
**Acceptance Criteria:**
1. Soprano, Alto, Tenor and Bass chips always fit on one line, with all four selected, on a 360 dp-wide screen. Chip text and padding are made smaller as needed.
2. A selected chip is filled with its voice colour, the same as the Voice Mixer: Soprano pink, Alto purple, Tenor green, Bass blue (`AppTheme.mixerSoprano/Alto/Tenor/Bass`).
3. Selected chip text keeps WCAG AA contrast against its fill.
4. Unselected and disabled chips keep their current look.

---

## PIYA-209 — Voice Mixer

### PIYA-209-V2.1 — Metronome row looks the same as voice rows
**Acceptance Criteria:**
1. The Metronome Click row's icon and text are fully opaque, in the same style as the Soprano/Alto/Tenor/Bass rows, whether the metronome is on or off. Only its slider/Mute/Solo are disabled while it is off.

### PIYA-209-V2.2 — Default mix follows the user's voice
Per **[Q2]**.
**Acceptance Criteria:**
1. With no default voice set (or "all voices" from PIYA-201-V2.1), all four voices start unmuted at 100% (current PIYA-209 AC5).
2. With a default voice set (onboarding or Settings), opening a score plays only that voice. Its Playback chip is the only one on (PIYA-208 AC3). In the Mixer, its row is unmuted at 100%, and the other three rows start muted with their sliders at 100%, so the Mixer shows what is actually heard. **[Call: shown as Mute, not as sliders at 0.]**
3. If the default voice failed for this score, the PIYA-208 failed-voice rule applies: all remaining voices are turned on and unmuted.
4. Replaces PIYA-209 AC5. The reset rules of AC6 are unchanged.

### PIYA-209-V2.3 — Turning the metronome on makes it heard
Per **[Q6]**.
**Acceptance Criteria:**
1. Turning the metronome on (Mixer switch or Speed checkbox) while audio is playing makes the click heard from the next click, without pausing or restarting playback.
2. The click is not heard if its Mixer row is muted, is soloed out, or is at 0. Turning the metronome on does not change its Mute or level.
3. Turning it off silences the click straight away.

### PIYA-209-V2.4 — Brand-gradient volume sliders
**Acceptance Criteria:**
1. The filled part of every Mixer volume slider uses the brand green-to-blue gradient instead of white, so the level is easy to read.
2. A muted row's slider is clearly dimmed, so muted and unmuted rows look different.

---

## PIYA-211 — Export Audio

### PIYA-211-V2.1 — Explain how voice selection works
**Acceptance Criteria:**
1. The top of the Export sheet shows a short explanation, e.g.: "Pick the voices you want to hear. They are mixed into **one** audio file. For example, ticking Soprano and Alto gives one file with both voices singing together, not two separate files."
2. The text is readable by screen readers and does not push the Download Audio button off-screen on a 360 dp-wide phone.
3. No change to export behaviour (PIYA-211 AC13 already exports one mixed file).

---

## Not in this doc

The presentation items (Chapter 4, manuscript formatting, prototype demo, results, ethics forms) are not app changes and have no tickets here.
