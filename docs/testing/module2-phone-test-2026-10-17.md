# Module 2 phone test — 2026-10-17

Manual acceptance test of the Android app by the user, on a physical phone, using the debug APK built
from `feature/piya218-scan-status` (now merged to main as 83b32b6). The build uses the in-app fake
backend (`FakeAuthApi` and the fake score/job APIs), so no real server was involved.

Checklist used: the published checklist artifact (https://claude.ai/artifact/FZeA6gWnetipfuYmhMvypC),
which quotes each AC from `docs/tickets/module2-mobile.md`.

**Totals: 75 pass, 0 fail, 12 untested.**

## Passed (75)

| Ticket | Passed ACs |
|---|---|
| PIYA-201 Onboarding | 1, 2, 3, 4, 5, 6 (all) |
| PIYA-202 Login | 1, 2, 3, 4, 5, 6, 7 (all) |
| PIYA-203 Sign-Up | 1, 2, 3, 4, 5, 6, 7 |
| PIYA-204 Password Reset | 1, 2, 3, 4, 5 |
| PIYA-205 Score Library | 1, 2, 3, 4, 5, 6, 7, 8 (all) |
| PIYA-206 Capture / Add Score | 1, 2, 3, 4, 5, 6, 7 |
| PIYA-207 Processing | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| PIYA-208 Playback | 2, 3, 4, 5, 6, 7, 8 |
| PIYA-209 Voice Mixer | 1, 2, 3, 4, 6, 7 |
| PIYA-210 Speed | 1, 2, 3, 4, 5 (all) |
| PIYA-218 Scan Status & Bell | 1, 2, 3, 5, 6, 9, 12 |

PIYA-202 AC3 passed on what the phone can show (session survives an app restart). The real Login
API call and token storage against Module 3 still need the real backend.

## Untested (12)

The user reports these could not be tested without a real backend. Their reasons below are the
expected blockers, not test findings. Retest each against the real Module 3 backend.

| AC | Why it is still open |
|---|---|
| PIYA-203 AC8 | Added 2026-10-17 after the checklist run; already built, not yet checked on the phone. |
| PIYA-204 AC6 | Added 2026-10-17 after the checklist run; already built, not yet checked on the phone. |
| PIYA-206 AC8 | The endpoint chosen (PIYA-101 vs PIYA-310) isn't visible with the fake API. Covered by unit tests. |
| PIYA-207 AC11 | Re-photograph offer for an unreadable voice. |
| PIYA-207 AC12 | Whole-score retake (`replacesJobId`). |
| PIYA-208 AC1 | Needs a real preprocessed score image; the fake build shows a bundled sample. |
| PIYA-209 AC5 | All voices unmuted at full volume on first open. |
| PIYA-218 AC4 | Library processing card (long-press cancel, in-place change to a normal card). |
| PIYA-218 AC7 | Push-notification half not built (needs FCM and a server-side sender). |
| PIYA-218 AC8 | Restart persistence: the fake server dies with the app, so "finished while closed" needs a real backend. |
| PIYA-218 AC10 | Paused/resume and the 90 s "Still working" state. |
| PIYA-218 AC11 | `POST_NOTIFICATIONS` request not built (deferred with AC7). |

## Not in this test

PIYA-211 (Export Audio) and PIYA-212 (Settings) are not built yet. Per the user (2026-10-17), version 1
of the app is everything above plus those two tickets.
