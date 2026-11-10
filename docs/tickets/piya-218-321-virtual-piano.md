# Virtual Piano Modal — Tickets (PIYA-218, PIYA-321)

### PIYA-218 — Virtual Piano Modal UI

**User Story:** As a choir member, I want to tap an on-screen piano while viewing a score, so that I can find my starting pitch without leaving the playback screen.

**Depends on:** PIYA-321 (Piano Settings API). Sound is produced on-device by the phone's built-in MIDI player, so there is no sound asset or backend sound dependency.

**Design References:** `PIYA212_PianoModal_UI.png` (default), `PIYA212_PianoModal_UI_wheninfobuttonpressed.png` (Notes Chart open), `PIYA212_PianoModal_UI_whitekeypress.png` (white key pressed), `PIYA212_PianoModal_UI_blackkeypress.png` (black key pressed).

> **Note:** the design reference currently shows 6 dots. The available octaves are 2 to 6, so the final design has **5 dots**. Where the references and the acceptance criteria below differ, the acceptance criteria win.

**Process:**
1. User taps the piano entry point on the playback screen; the Piano modal slides up over the score.
2. System opens on the last-used octave (or, the first time, the default for the user's voice) and prepares the device MIDI player.
3. User taps keys to hear notes and uses the chevron buttons to move between octaves. The dots and the Octave label update with each change.
4. Optionally, user taps the info button to open the Notes Chart without leaving the piano.
5. User closes the modal (X or swipe down). The octave is saved locally and synced to the server.

**Acceptance Criteria:**

*Modal layout*
1. The modal shows, top to bottom: drag handle, info button, title "Piano", description "Find your pitch.", close (X) button, chevron row, and keyboard, matching the design references.
2. The chevron row has a left chevron labeled "Lower", a right chevron labeled "Higher", a row of 5 dots, and an "Octave N" pill centered between the chevrons.
3. The modal closes via the X button or by swiping the modal down. Both close paths behave identically.

*Keyboard and labels*
4. The keyboard shows 7 white keys (C D E F G A B) and 5 black keys, laid out like a real piano with no black key between E–F or B–C.
5. White keys display their note name as a label. The C key displays "C" with the current octave number as a superscript (e.g., C⁴).
6. Each black key displays two labels stacked on one key: the flat name on top and the sharp name below (D♭/C♯, E♭/D♯, G♭/F♯, A♭/G♯, B♭/A♯), as in the design.
7. The C label is teal only when Octave 4 (middle C) is showing. In all other octaves it uses the default white-key label color.
8. All labels remain visible at all times, including while a key is pressed. The pressed state must never hide or obscure a label, and label contrast must stay legible in both the pressed and unpressed states.

*Key press behavior and sound (device MIDI player)*
9. Pressing a white key shows the light-teal pressed fill (`PIYA212_PianoModal_UI_whitekeypress.png`). Pressing a black key shows the dark-teal pressed fill (`PIYA212_PianoModal_UI_blackkeypress.png`). The pressed state clears on release or when the touch leaves the key.
10. A key plays its note on touch-down and releases it on touch-up. The visual pressed state and the sound start together.
11. A flat/sharp pair (e.g., D♭ and C♯) shares one key and plays the same pitch.
12. The keyboard supports multi-touch, so several keys can be held and sounded at once.
13. Note pitches use standard MIDI numbering: C4 = MIDI 60, so the C of Octave N = 12 × (N + 1). The 5 octaves cover MIDI 36 (C2) through MIDI 95 (B6).
14. Notes are played by calling the phone's built-in MIDI player/synthesizer (no bundled soundfont, no FluidSynth, no downloaded audio). The instrument is General MIDI program 0 (Acoustic Grand Piano). Touch-down sends note-on at a fixed velocity (default 100, defined as one constant), and touch-up sends note-off. Touch-to-sound latency target is ≤ 100 ms on supported devices.
15. The MIDI player is initialized when the modal opens, so the first key press is not silent or delayed by lazy loading. If the device MIDI player is unavailable or fails, the keys still show their pressed state and the user sees a non-blocking message that sound is unavailable on this device.
16. The keyboard follows the existing audio-session behavior of the playback screen (e.g., silent mode, interruptions, volume).
17. Piano sound makes no network or backend call and works fully offline.

*Octave changer (chevrons, dots, label)*
18. The available octaves are 2, 3, 4, 5, and 6. Tapping the right chevron moves up one octave, and tapping the left chevron moves down one octave.
19. On every octave change, the "Octave N" pill text updates to the new octave number (e.g., "Octave 3"), the key labels update (including the C superscript), and the keyboard slides in the direction of the change.
20. The dots show position: dot 1 = Octave 2, dot 2 = Octave 3, dot 3 = Octave 4, dot 4 = Octave 5, dot 5 = Octave 6. The active dot is highlighted with the blue-green gradient (same gradient as the Octave pill), and inactive dots are light gray. On every change the highlight moves to the new dot, with a short transition.
21. At Octave 2 the left chevron is disabled and grayed out, and at Octave 6 the right chevron is disabled and grayed out. Disabled chevrons ignore taps.
22. Any notes held when the octave changes are released cleanly (note-off sent), with no stuck notes.
23. The dots are an indicator only (non-interactive). The chevrons are the only way to change octave.
24. Chevron tap targets are at least 40×40px.

*Default octave (first open)*
25. When the user has no saved octave, the modal opens on a default based on the voice selected at onboarding or in settings:
    - Tenor or Bass → **Octave 3**
    - Soprano, Alto, Not sure, or Conductor → **Octave 4**
26. The default applies only until an octave has been saved. Once the user has used or closed the modal, the last-used octave always opens, even if the user later changes their voice in settings.
27. If the voice is missing or unrecognized, the default is Octave 4.
28. Closing the modal saves the octave currently shown, even if the user never tapped a chevron, so the first-time default becomes the user's saved octave.

*Notes Chart (info button)*
29. Tapping the info button opens the Notes Chart as a card over the score, above the Piano modal, as in `PIYA212_PianoModal_UI_wheninfobuttonpressed.png`.
30. The Notes Chart shows a title "Notes Chart", an X button, a "Treble Clef" tag with a treble staff labeled C⁴ through G⁵, and a "Bass Clef" tag with a bass staff labeled E² through B³. Only C⁴ is highlighted teal. G⁴ (treble) and F³ (bass) are shown as hollow notes, as designed.
31. The Notes Chart is static content bundled in the app. It makes no backend call, opens instantly, and works offline.
32. Tapping the Notes Chart's X closes only the chart. The Piano modal stays open, and the octave and held state are unchanged.
33. While the Notes Chart is open, the Piano modal stays fully functional: keys play and show pressed states, and the chevrons change octave (dots and label update as usual). Opening the chart does not dim, block, or disable the Piano modal.
34. If the Piano modal is closed by its X or by swiping down while the Notes Chart is open, the Notes Chart closes too, and the user returns to the playback screen. The chart is never left open without the Piano modal.
35. The Notes Chart also closes if the user leaves the score or the app is backgrounded.
36. Tapping the info button while the chart is already open leaves it open (no duplicate chart is created).

*Persistence of octave (local)*
37. The selected octave is saved to local storage every time it changes, together with an `updatedAt` timestamp (ISO 8601, UTC).
38. When the user closes the Piano modal, leaves the score, or closes or force-quits the app, then reopens the Piano modal later, it opens on the last octave used.
39. If a saved value is outside 2 to 6 or corrupted, the client falls back to the voice-based default (AC 25 to 27) without crashing.

*Integration with Piano Settings API (PIYA-321)*
40. On app launch and when the Piano modal opens, the client renders immediately from the local octave (or the voice-based default if none), then calls `GET /api/v1/users/me/piano-settings` in the background. It never waits for the response before showing the keyboard.
41. Reconciliation: if the server `updatedAt` is newer than the local `updatedAt`, the client adopts the server octave and updates local storage. If the local `updatedAt` is newer, the client sends it with `PUT`. If the server returns `updatedAt: null` (`isDefault: true`), the client treats it as "no server value" and pushes the local value only if the user has a saved one. The default is never pushed as a saved value until AC 28 applies.
42. If the server octave arrives while the user is already interacting with the modal, the UI does not jump. The client applies the server value next time the modal opens, unless the user has not changed the octave yet in this session.
43. After each octave change, the client sends `PUT /api/v1/users/me/piano-settings` with `{ "octave": N, "clientUpdatedAt": "<local updatedAt>" }`. Requests are debounced (about 500 ms after the last tap) so rapid chevron taps send one request with the final value.
44. A pending change is also flushed when the modal closes (including the AC 28 save) or the app goes to the background.
45. If the PUT response returns a different octave than the one sent (the server kept a newer value, per PIYA-321 AC 7), the client updates local storage with the response, and applies it on next open.
46. The client sends `Authorization: Bearer <sessionToken>` on every call. On 401, the client follows the app's existing session-expiry flow and keeps the piano usable with local values.
47. Sync failures (offline, timeout, 5xx) never block or visibly interrupt the user. The client keeps the local value, keeps a "pending sync" flag, and retries on next launch, next modal open, or when connectivity returns, with backoff.
48. Responses with `400 octave_invalid` or `octave_out_of_range` indicate a client bug. The client logs them, does not retry, and keeps the local value.

*Accessibility and quality*
49. Every key has an accessibility label that includes note name and octave (e.g., "C sharp or D flat, octave 4"). Chevrons are labeled "Lower octave" and "Higher octave", and the pill announces the current octave.
50. Layout works on small phone widths without the labels clipping or overlapping.

---

### PIYA-321 — Piano Settings API (Octave Persistence)

**Method:** GET / PUT `/api/v1/users/me/piano-settings`
Stores and returns the user's last-used piano octave so it can be restored across sessions and devices. Used by Virtual Piano Modal UI (PIYA-218).

**Acceptance Criteria:**
1. Both methods require a valid session token (`Authorization: Bearer`). Returns 401 if missing, invalid, or expired.
2. GET returns the user's saved settings. If the user has never saved an octave, returns 200 with the voice-based default octave, `updatedAt: null`, and `isDefault: true`:
   - Voice tenor or bass → `octave: 3`
   - Voice soprano, alto, not sure, or conductor → `octave: 4`
   - Voice missing or unrecognized → `octave: 4`
3. PUT accepts `octave` (integer) and optional `clientUpdatedAt` (ISO 8601, UTC). Returns 400 with error code `octave_missing` if `octave` is missing.
4. Returns 400 with error code `octave_invalid` if `octave` is not an integer (e.g., string, decimal, null).
5. Returns 400 with error code `octave_out_of_range` if `octave` is less than 2 or greater than 6.
6. Returns 400 with error code `client_updated_at_invalid` if `clientUpdatedAt` is not a valid ISO 8601 timestamp or is more than 5 minutes in the future.
7. If `clientUpdatedAt` is older than the stored `updatedAt`, the server does not overwrite and returns 200 with the stored (newer) value, so stale offline writes cannot clobber newer data.
8. If `clientUpdatedAt` is newer than or equal to the stored value, the server saves `octave` and sets `updatedAt` to `clientUpdatedAt`. If `clientUpdatedAt` is omitted, the server uses its current time. This keeps client and server timestamps comparable for the reconciliation in PIYA-218 AC 41.
9. The server saves the value against the authenticated user only. A user can never read or modify another user's settings.
10. PUT is idempotent: sending the same value repeatedly returns 200 with no side effects beyond `updatedAt`.
11. The response always returns the value now stored (not just what was sent), so the client can detect when the server kept a newer one. After a successful save, `isDefault` is `false`.
12. Returns 500 with a generic error message (no stack trace/internal details) if the save fails unexpectedly.
13. Endpoint responds within 2 seconds under normal load.
14. The default is computed at read time from the user's current voice and is not stored. Once the user has a saved octave, later voice changes do not alter it. If the user changes voice before ever saving, the default follows the new voice.

**Integration (Frontend: PIYA-218):**
15. Called by the client at: app launch and modal open (GET), 500 ms after the last octave change, on modal close, and on app background (PUT). The server must handle bursts of PUTs from a single user without errors.
16. Error codes (`octave_missing`, `octave_invalid`, `octave_out_of_range`, `client_updated_at_invalid`) are returned in the `message` field exactly as written, because the client maps them to behavior (PIYA-218 AC 48).
17. The response shape is identical for GET and PUT so one client parser handles both.

**Response Schema (GET/PUT):**
```json
{
  "data": {
    "octave": 3,
    "updatedAt": "2026-11-10T09:15:00Z",
    "isDefault": false
  },
  "success": true,
  "status": 200,
  "message": "Piano settings retrieved"
}
```

**GET Response, never saved (tenor user):**
```json
{
  "data": {
    "octave": 3,
    "updatedAt": null,
    "isDefault": true
  },
  "success": true,
  "status": 200,
  "message": "Piano settings retrieved"
}
```

**PUT Request Example:**
```json
{
  "octave": 5,
  "clientUpdatedAt": "2026-11-10T09:14:58Z"
}
```

**Error Response Example (400):**
```json
{
  "data": null,
  "success": false,
  "status": 400,
  "message": "octave_out_of_range"
}
```

---

### End-to-End Integration Flow

| Step | Frontend (PIYA-218) | Backend | Result |
|---|---|---|---|
| 1. First open, no saved octave | Opens on voice default (Octave 3 for tenor/bass, Octave 4 otherwise), prepares device MIDI player, calls GET settings | PIYA-321 GET (`isDefault: true`) | Default shown, keys sound, nothing pushed yet |
| 2. User changes octave | Dots, pill label, and key labels update, local save, debounced PUT | PIYA-321 PUT | Server stores the final octave |
| 3. Close modal, score, or app | Saves shown octave (even if untouched), flushes pending PUT | PIYA-321 PUT | Last octave is saved everywhere, default no longer applies |
| 4. Reopen | Opens on last-used octave | None (local) | Same octave as when closed |
| 5. Reopen offline | Device MIDI player and local octave | None | Fully works offline |
| 6. Back online | Retries pending PUT | PIYA-321 | Local and server values re-synced |
| 7. Second device | Same flow as step 1 | PIYA-321 GET (`isDefault: false`) | Opens on the octave last set on the other device |

**Build order:** PIYA-321 first, then PIYA-218 against the real endpoint. The frontend can be built earlier with a mocked API using the response schemas above. Sound needs no backend work.

**Integration test checklist (for QA / Claude Code):**
1. New tenor or bass user opens the piano: opens on Octave 3. New soprano, alto, not sure, or conductor user: opens on Octave 4.
2. Tap keys in airplane mode: sound plays through the device MIDI player.
3. Tap right chevron from Octave 4: pill reads "Octave 5", the gradient dot moves to dot 4, key labels show 5.
4. At Octave 2 the left chevron is disabled. At Octave 6 the right chevron is disabled.
5. Hold a key and change octave: note is released, no stuck note.
6. Press several keys at once: all sound together.
7. Change octave to 2, force-quit, reopen: opens on Octave 2.
8. Open as a tenor, close without touching chevrons, switch voice to soprano in settings, reopen: still Octave 3.
9. Change octave offline, reconnect: server receives the final value.
10. Set octave 5 on device A, open on device B: B opens on Octave 5.
11. Stale offline write (older `clientUpdatedAt`): server keeps newer value, client adopts it.
12. PUT with octave 1 or 7: server returns `octave_out_of_range`.
13. Device where the MIDI player is unavailable: keys still show pressed state and the "sound unavailable" message appears without blocking.
14. Expired session: piano still works with device sound and local octave.
15. Notes Chart open: keys still play and chevrons still change octave. Closing the piano modal also closes the chart.

---

### Assumptions to Confirm

- **Device MIDI:** sound uses the phone's built-in MIDI player (General MIDI Acoustic Grand Piano). Built-in MIDI support and latency differ between devices and platforms, so test on real target devices (iOS and Android) early. If a device has no usable built-in real-time synth, or latency is above 100 ms, AC 15 shows the "sound unavailable" message. Decide then whether a fallback is needed.
- Piano timbre will vary by device, since each phone's built-in sound bank is different.
- "First time" is treated as the first time the **user** opens the piano modal (not per score). Octave is saved per user, not per score. For per-score memory, the settings API needs a `scoreId`.
- Closing the modal without touching the chevrons still saves the default as the user's octave (AC 28), so a later voice change will not alter it.
- If a user can pick more than one voice, tell me which wins. Currently the backend assumes one voice.
- The design reference shows 6 dots. Update it to 5 before feeding it to Claude Code, or rely on AC 2 and 20.
- Gradient colors for the active dot follow the existing blue-green gradient on the Octave pill.
- The C label is teal only in Octave 4 (AC 7).
- Debounce of about 500 ms is a default; change it if you prefer a different value.
- Design reference filenames still say `PIYA212_...` because those are the actual files.
