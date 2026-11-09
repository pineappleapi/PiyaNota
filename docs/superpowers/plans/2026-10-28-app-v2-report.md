# App V2 — execution report (2026-10-29)

Branch `feature/app-v2`, 56 commits on main 4d417ee. Suite 1190/1190, `flutter analyze` clean. Reviews: frontend-lead Ready, senior-reviewer Ready, backend-lead Ready (B1–B5 agreed, in `docs/tickets/module3-backend.md`).

## Rulings made on the user's behalf (in order, each with its cost if wrong)

- Ruling: T3 splash triggers only on `resumed` after `paused` (not `inactive`) — Android permission dialogs/system sheets usually only cause `inactive`; withoutSplash still wraps pickers/Settings/file chooser — cost if wrong: splash after a permission dialog on some devices.
- Ruling: T3 the in-app camera preview is not "leaving the app"; withoutSplash only wraps calls that open another activity — the plan listed camera loosely — cost if wrong: none observable.
- Ruling: T20 AA contrast — chip label colour picked per fill (white or dark ink) to reach 4.5:1; mixerAlto 9354DF with white may fail — spec AC demands AA — cost if wrong: label colour differs from mockup.
- Ruling: T25 uses ticket AC1's example text verbatim ("e.g." in spec; exact text is the safest reading) — cost if wrong: one string edit.
- Ruling: implementers commit per task on feature/app-v2 (user: "commit to branch") — never merge/push.
- Task 2: Ruling: commit trailer = controller's attribution (Opus 5.5 + Claude-Session from Task 3 on); 6198d1d/61af8e8 lack Claude-Session line — not rewritten, history-only — cost if wrong: two commits missing a trailer
- Task 3: Ruling: SplashGate moved outside MaterialApp to get didPopRoute before Navigator — only way observer order lets gate block back — cost if wrong: future MaterialApp-scoped deps in overlay need explicit providers.
- Task 4: Ruling: successful password reset clears that email's login wait (app throttle + fake) — user proved ownership via emailed code; leaving them blocked up to 15 min is the worst UX moment; server keeps its own B1 limit — cost if wrong: one revert, small.
- Task 4: Ruling: 429 without retryAfterSeconds counts as one failure — fail-safe, user still sees a wait — cost if wrong: may double-count with server.
- Task 5: Ruling: only first library-load 401 routes to Login; later 401s keep existing "Log In" panel — AC2 is about launch, B2 says launch check = PIYA-306 load — cost if wrong: one extra tap for user.
- Task 6: Ruling: unregistered-email message keeps error-banner style — no PIYA-204 mockup exists (checked worktree + main references/); spec silent — cost if wrong: swap to AuthNoticeBanner with spans, small.
- Task 7: Ruling: accept implementer's clear-on-successful-reset of the resend cooldown — without it a second reset for same email within 30 s skips the send and dead-ends on Enter Code — cost if wrong: one extra send after a completed reset.
- Task 8: Ruling: wrong-code count is per normalised email, keep-alive (not persisted); Verify disabled during wait, typing allowed — mirrors Task 4/7 — cost if wrong: small provider change.
- Task 8: Ruling: server 429 always yields a visible announced wait; no seconds → backoffAfter(max(1, failures-3)) ≥30 s — extends Task 4's "429 w/o retryAfter = a failure" ruling to the reset flow where the free attempts would otherwise swallow it — cost if wrong: user waits 30 s unnecessarily after a bare proxy 429.
- Tasks 9+10: Ruling: batched into one implementer (two commits) — both small Library-screen layout tasks off the same reference image, separate files — cost if wrong: one combined review instead of two.
- Task 9: Ruling: reference wins over brief's "bell box right edge = header padding" test; test now asserts glyph rect at width−29 ±2 — user's pixel-fidelity rule + AC4 "far top-right" — cost if wrong: bell moves back 10 dp.
- Task 9: Ruling: Library backdrop logo anchored to header top (incl. status bar), not the safe-area inset — it's a backdrop bleeding under the status bar — cost if wrong: logo ~17 dp off on a 24 dp status bar; phone check.
- Task 9: Ruling: Settings keeps 0.4 logo via its own settingsHeaderLogoOpacity — spec V2.1 covers only Library header — cost if wrong: one constant.
- Task 11: Ruling: NEEDS_CONTEXT (no repro on clean start) not escalated to user — user saw it on a phone carrying earlier-run state; implementer told to reproduce with persisted prefs/session, the Task 5 demo-token shortcut, and the real sign-up route; fake id collision across runs to be fixed if confirmed — cost if wrong: the flash is from another cause and survives to the phone check.
- Task 11: review: spec ✅ in tests, Needs fixes — fix explains stale-owner scan, not the user's demo-library flash (fake keyed by email). Ruling: keep d2b49bb, fix round 1 rewords the report, adds id tests and shortcut comments, then a bounded hunt on onboarding→signUp and Settings logout→signup; unresolved symptom goes to the user as a phone repro question in the final report rather than parking the run — cost if wrong: V2.3 still open on phone.
- Task 11: fix round 1/5 (commit f9ea373; suite 1073) — report reworded, id tests, shortcut comments; demo flash not reproduced. Latent issue found: finishing onboarding with a stored token runs _restoreSession and mounts the Library (demo-token fetch) under the outgoing route. Ruling: fix it in round 2 as the most plausible cause of the phone flash — onboarding must not mount the Library under Sign Up — cost if wrong: one extra small fix; the user's symptom may still lie elsewhere.
- Task 12: implementer DONE_WITH_CONCERNS (commit e78dbd7; suite 1090). Ruling: an empty title disables Save with no message, matching capture — AC3 says "matches the capture details screen" — cost if wrong: one extra message string.
- Task 12: Ruling: a PATCH 400 shows the generic error, because capture's per-code wording says "Tap Edit details", which doesn't fit here — cost if wrong: the user gets a vaguer message on server-side rejection.
- Task 12: re-review Approved. Ruling: the inline error not being announced by TalkBack is graded Important (accessibility), so a tiny fix round 2 adds liveRegion and a debug log — cost if wrong: one extra small commit.
- Task 13: Ruling: "large preview" means the existing full-screen PagePreviewScreen, which a thumbnail tap already opened at 58689e0; no inline preview is added — cost if wrong: new UI later.
- Task 13: Ruling: a reorder keeps the selection; after deleting the selected page, the last page is selected (existing behaviour) — cost if wrong: a small focus tweak.
- Tasks 14+15: batched to one implementer (two commits), BASE 13fe9e4. Ruling: in retake mode, a single Gallery pick is allowed if the picker supports it (AC1 says 'captured or picked'); otherwise Gallery is disabled — cost if wrong: Gallery stays or goes in retake.
- Tasks 14+15: review Approved, both ✅. Ruling: keep the retakeFull guard as a defensive check — the UI gates it, and the guard explains the refusal if that gating regresses — cost if wrong: about 4 dead lines.
- Task 16: Ruling: the PDF control looks dimmed once a PDF is present, but a tap still shows 'Only one PDF can be added per score.' (AC1 asks for both disabled and the message) — cost if wrong: the tap could be made fully inert.
- Task 16: review Needs fixes (1 Important: Semantics enabled:false + onTap — TalkBack may drop the double-tap, so the one-PDF message is never heard). Ruling: semantics stay enabled, the hint carries the reason, the dim is visual only — the AC's "disabled" is met visually; the message reaching TalkBack users outweighs announcing "disabled" — cost if wrong: TalkBack doesn't say "disabled".
- Tasks 17+18: Ruling: batched into one implementer (same seek-bar area, BASE e889f0b) — cost if wrong: a larger review surface.
- Tasks 17+18: Ruling: the Slider keeps its full 48 dp hit box; the times are IgnorePointer text inside the slider's lower area; Mixer/Speed may move a few dp below the mockup — a 48 dp target outweighs a few dp of mockup fidelity — cost if wrong: the action row sits slightly lower than the mockup.
- Tasks 17+18: Ruling: gap and font size come from the real Plus Jakarta Sans metrics (TTF downloaded to job tmp, read with fontTools) plus mockup pixel reads; no estimates — cost if wrong: one more measurement pass.
- Tasks 17+18: Ruling: park item 2 (measured gap + 14 vs 16 sp) as a user phone check — pixel-read track bottom to digit top on a device screenshot with the real font; 9 dp / 14 sp stay provisional, with the doc comment saying "estimate" — the download was denied, so the controller must not route around it; a device screenshot is the truer measurement anyway — cost if wrong: the gap is off by about 1 dp and the text by 2 sp until the phone check.
- Task 19: Ruling: spike via widget-test gestures if no emulator is available; real-touch feel becomes a phone check; band goes inside the transformed child; opus implementer (gesture-arena risk) — cost if wrong: a gesture conflict found only on the phone.
- Task 20: Ruling: one line is guaranteed at text scale 1.0 on 360 dp; wrapping is allowed above that (NFR-10 large text beats the spec's 'always') — fixing failing contrast changes the chip label colour, never the shared mixer colours — cost if wrong: chips wrap at large text sizes. BASE 0637302.
- Task 20: Ruling: I1 — the real font can't be measured (download denied earlier), so the one-line test must pass with ≥12% horizontal slack at scale 1.0 to absorb Jakarta's extra width; shrink gap and label padding further if needed — cost if wrong: chips wrap on the phone (phone check).
- Task 21: BASE d8efec4. Ruling: the metronome row label/icon is fully opaque; while off, only the slider, Mute and Solo are disabled, and any dimming applies to those controls only — TalkBack still announces them as disabled — cost if wrong: the row looks interactive when it isn't.
- Task 21: Ruling: when the click is unavailable (no tempo, or it failed mid-play) the row keeps Opacity 0.38 and the disabled note — the AC covers on/off only, and failed voice rows dim the same way — cost if wrong: one more Opacity removal.
- Task 21: Ruling: the speaker glyphs at the slider ends belong to the slider, so they keep its 0.45 fade while the metronome is off — the AC disables only the slider, Mute and Solo — cost if wrong: move the Opacity onto the Slider alone.
- Task 22: BASE 23e7241. Ruling: turning a voice chip on makes that voice audible, unmuting it if the default mix muted it — a selected-but-silent voice is a trap — cost if wrong: it diverges from the mixer's separate mute state. Ruling: AC6 reset returns to the V2.2 default (only the default voice), unless AC6's wording says otherwise — cost if wrong: reset unmutes all.
- Task 23: BASE 9fed5cd; implementer opus (debugging). Ruling: the default mix never mutes the click row; when preparation must finish first, the click is heard as soon as the plan is ready — cost if wrong: a short delay before the first click.
- Task 23: review Approved, spec ✅, no device-only cause found. Ruling: re-graded reviewer Minor 1 to Important — a null or zero engine.duration at plan time produces an empty click WAV that reaches ready but is silent, which matches the user's 'on but not heard' — fix it now — cost if wrong: one guard plus one test.
- Task 24: BASE d178ece. Ruling: reuse the confirmed AppTheme.gradientStart/End (no re-sampling); the fill runs green (gradientEnd) at the start to blue at the thumb, per the AC's 'green-to-blue' wording; the gradient spans the full track width — cost if wrong: the direction is flipped (one-line swap).
- Task 25: BASE 45a3067. Ruling: use the AC1 'e.g.' text verbatim, with 'one' in bold — the user approved the ticket wording, and inventing different copy would need a second approval — cost if wrong: a one-string edit.
- Task 25: review Needs fixes — Important: the 360 dp tests prove reachable-by-scroll only, not 'not pushed off-screen'. Ruling: measure Download's pre-scroll bottom at 360x640/800 before vs after the note. If it was fully visible before at a size, it must stay visible there (tighten the note's padding or style); if it was already below the fold before, reachable-by-scroll meets AC2 — the AC protects against regression, and a sheet that already scrolled is not a regression — cost if wrong: a padding tweak.
- Final: Ruling: re-grade Minor #2 (the Edit button's TalkBack label has no score title) to Important — a screen-reader user hears the same "Edit score details" on every card and cannot tell which score it edits — cost if wrong: one string.
- Final: Ruling: unmuting a default-muted voice and then hand-muting it leaves its chip on but the voice silent — the Mixer shows Muted, so it still matches what is heard (V2.2 AC2) — cost if wrong: one extra chip tap.
- Final: Ruling: fix C1, I1, I2 and I3 now in one pass, and replace the B1–B5 notes with backend-lead's text — C1 is a security flaw in the contract the app ships against, and I2 is a V2.4 AC2 miss — cost if wrong: one more round on the auth code. The two [Decision needed] items (a 24 h count decay for B1 and B4) stay marked in the doc for the user and are not built.
- Ruling: onboarding Skip now also clears a saved voice — Skip only shows before onboarding completes, so no saved voice can exist then — cost if wrong: one guard.

## Deferred minors

- Task 1: minor (deferred): backoff.dart:29 _maxDoublings=5 silently coupled to _firstWait/_maxWait
- Task 2: minor (deferred): two providers (voice + conductor) — exclusivity enforced only in widget
- Task 2: minor (deferred): "saves null" test weak (null is default); add voice→conductor→Get Started case
- Task 2: minor (deferred): test duplicates _conductorLabel string
- Task 2: minor (deferred): selected conductor button border-only, no radio dot
- Task 3: minor (deferred): splash ends on value 1.0 not `completed` — one frame, user-invisible.
- Task 3: minor (deferred): export_service_test.dart:681 openFolder true starts 3 s real grace timer, no setUp(resetLeavingApp).
- Task 3: minor (deferred): leaving_app.dart:390 "returned true = launch" rule is loose; add explicit launchesActivity param if a bool-returning non-launch call is ever wrapped.
- Task 4: minor (deferred): "You can try again now" announced even when login screen covered by reset screen (gate on ModalRoute.isCurrent).
- Task 4: minor (deferred): wrong-password banner live region + wait announcement may cut each other off on TalkBack — device check.
- Task 5: minor (deferred): on slow network 401 path shows Library briefly before Login — inherent to B2 design.
- Task 6: minor (deferred): unregistered sentence assembled in two places (spans + plain message) — add AuthMessages full string.
- Task 6: minor (deferred): no test for bare-string `error` body shape on 404; stale "If this email is registered…" fixture at http_auth_api_test.dart:156.
- Task 6: minor (deferred): no test that unregistered message clears on email edit.
- Task 7: minor (deferred): `_stopResendCooldown` clears the entry but doesn't cancel the timer (misnamed).
- Task 7: minor (deferred): no tests for clear-on-success re-request, nor A→B→A within 30 s.
- Task 8: minor (deferred): fake keeps one global wrong-code counter, drifts from app's per-email count when switching email.
- Task 8: minor (deferred): error banner live region + "Try again in" announcement fire together on 4th wrong code (same as Task 4's TalkBack item; phone check).
- Task 8: minor (deferred): AC5 test doesn't cover a server wait shorter than an app-started wait.
- Task 8: minor (deferred): repeated bare 429s (no seconds) back off 0:30×4 before doubling — fix: count = max(count, 3)+1 before computing wait.
- Task 10: minor (deferred): 5 dp gap rests on recalled Plus Jakarta Sans metrics — phone check ±1 dp.
- Task 10: minor (deferred): test restates `titleToDetailsGap == 5`; ScanningScoreCard gap untouched (out of scope).
- Task 9: minor (deferred): stale "far top-right" comment above Column (library_header.dart:~118); two test lines >80 cols.
- Task 11: minor (deferred): a launch that showed onboarding skips _takeLaunchJob (practically unreachable); _showedOnboarding is set inside build() with no why-comment.
- Task 12: minor (deferred): not confirmed that the library Dio has the 10 s/15 s timeouts; the PATCH {data: entry} envelope is assumed (confirm with the backend under B5).
- Task 13: minor (deferred): the TalkBack reorder announcement "Page 2 of 3" doesn't name which page (could say "Moved to page…"); a stale test comment at capture_screen_test ~:478; the drag-left/right tests assert order only and have awkward names; no new overflow assert for the 4 dp border.
- Tasks 14+15: minor (deferred): no delete-then-retake test; TalkBack gives no reason for disabled Gallery/PDF in retake; a Camera tap during a stale-generation start is dropped (spinner until the next lifecycle event; pre-existing race now user-reachable; phone check).
- Task 16: minor (deferred): the semantics-tap test passed before the fix (flutter_test performAction ignores the enabled flag), so the TalkBack drop is only covered by the phone check; no isEnabled:true assertion.
- Tasks 17+18: minor (deferred): no 360 dp / 1:23:45 / large-text test; a drag in the few-ms window after the resume play() doesn't pause; a pause tap during the pending post-release seek is lost.
- Tasks 17+18: minor (deferred): the unmount branch of the resume guard has no test; Mixer/Speed sit about 12 dp below the digit tops vs level in the mockup (accepted trade, phone check).
- Task 19: minor (deferred): fling then play can drift the view (self-corrects); horizontal follow while zoomed is busy at 4×; the mouse wheel zooms; there is no single-pointer zoom-in (WCAG 2.5.1, not in the spec).
- Task 19: minor (deferred): semantics actions rebuild per frame while a11y is on; a resize during a follow tween is undone (add _scroll.stop() in _reclamp); semantics handle dispose not in addTearDown; pre-existing tap-on-disabled warning at playback_screen_test:813; the double-tap anchor height is unasserted; TalkBack linear nav over pages 2..n is a phone check.
- Task 20: minor (deferred): with FLUTTER_ROOT unset, the AC1 one-line/slack/48 dp proofs skip together; the chips sit 2 dp apart with 1 dp label padding (visual phone check); slack is measured with Roboto standing in for Plus Jakarta Sans (phone check that the chips fit on one line); contrast margin is thin (4.54–4.59).
- Task 21: minor (deferred): the no-faded-ancestor loop can pass vacuously (add findsNothing); there is no test that the unavailable state keeps 0.38 plus the note; the style is compared to a constant, not to a voice row.
- Task 22: minor (deferred): the mid-play test doesn't assert state.muted == {Tenor}; unchecked whether choosing conductor/"all voices" clears a previously saved default voice (flag for the final review).
- Task 23: minor (deferred): the seek-bar duration fix runs only when tempo is known (no-tempo score with unknown length keeps a 0-length bar); the shortcut comment at playback_engine.dart:361 is inaccurate (the failed master is paused, not disposed — re-read _master on failure); the "known at load" engine test is trivial; the firstWhere subscription lingers after the 30 s timeout. Phone checks: the 5-step metronome checklist, plus whether ExoPlayer reports a late or absent duration for backend MP3s (row shows unavailable).
- Task 24: minor (deferred): the painted shader and RTL flip are not tested (add a paints test); unrelated dart-format hunks in mixer_sheet.dart:~93-96 and mixer_sheet_test.dart:~350; muted-drag is covered only by older tests. Phone check: gradient and dimmed-row contrast.
- Task 25: minor (deferred): the 12sp note is small for the main instruction; headroom at 640 is only 13 px (an Ahem proxy; on a real device the status-bar inset is unmeasured); a scroll-position==0 assert would be tighter; the 1.3 text-scale test does not check position. Phone check: the note fits with no scroll at 360 dp.
- Final: minor (deferred): completeOnboarding(defaultVoice:null) does not remove a saved default voice — unreachable today; fix it before onboarding can be re-run.
- Final: minor (deferred): the login wait is not clamped when the device clock moves backwards (it can show more than 15 min).
- Final: minor (deferred): the login throttle keeps every typed email in SharedPreferences indefinitely (PII on a shared phone); prune expired entries.
- Final: minor (deferred): the editSemantics string-inequality test is redundant; one unguarded debugPrint('Session check failed') is inconsistent with the kDebugMode-wrapped log.
- Final: minor (deferred): soloing a chip-off voice still silences the rest after a failure (the _onFailure check ignores solo) — pre-existing edge case.
- Final: minor (deferred): a 429 without a usable wait counts as a wrong login (login_screen.dart:205); an unknown 400 on reset shows the server message (pre-existing V1); PATCH 400/409/429 show a generic error; the PIYA-218 dependency means editing a failed card works only against the fake.
- Final: minor (deferred): the reset-request 429 banner is static (no live countdown).
- Final: minor (deferred): 10 frontend-lead minors in fe-review-fixes.md.

## Owed phone checks

Tasks 3, 5, 8, 9, 10, 11, 13, 15, 16, 17, 19, 20, 23 (metronome click heard; ExoPlayer late/absent duration), 24 (gradient, dimmed contrast), 25 (export note fits at 360 dp); Mixer Unmute fix; Edit TalkBack label; splash around Gmail/camera; Settings All voices.

## Blocked

Task 17 seek-bar gap and time font size are estimates: the Plus Jakarta Sans download was denied. Needs the font file or a phone screenshot.
