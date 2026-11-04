# Bar-step playback line (advice, 2026-11-04)

Status: proposal only. No app code was changed. Written for the Flutter app in `mobile/piyanota_application/` and for backend-lead.

## Why

The backend timing file has measured accuracy only at barlines (median 0.54 staff space, p90 0.83). The x of a note inside a bar is unmeasured: `timing_export.py` places it by linear interpolation of its tick between the bar's left and right edge, then blends it 50/50 with the CRNN CTC x when the two agree (`timing_export.py:204-209`). The blue line should therefore jump from barline to barline and not slide between notes.

## Current behaviour

The blue line is called the "band" in code. It is a translucent vertical rectangle over the four staves of one system.

- Data: `TimingEvent` (`lib/models/score_result.dart:323-390`) holds `timestampMs`, `pageIndex`, `x`, `y`, `voice`, `tick`, `bar` (pickup is 0), `systemIndex`, `systemTopY`, `systemBottomY`. `parseTimingEvents` (`score_result.dart:396-406`) sorts events by time. `TimingFile.parse` (`lib/models/measure_table.dart:118-127`) also reads the `bars` list into `BarInfo` (`bar`, `startTick`, `durTicks`, `startMs`, `durMs`, meter, `pickup`). `BarInfo` has no x, page or system.
- Load: `_loadTimeline` (`lib/state/playback_providers.dart:604-621`) fetches `timingMetadataUrl`, builds `ScoreTimeline(onExistingPages(file.events, result.hasPage))` and returns `file.bars` separately. Any fetch or parse error gives `ScoreTimeline.empty` plus a flag that shows a one-time notice.
- Mapping time to position: `ScoreTimeline.positionAt` (`lib/models/score_timeline.dart:162-196`). It groups events into onsets (same `timestampMs` and page, `_Onset`, lines 98-107, x is the mean x of the chord). It binary-searches the last onset at or before the audio position. Then it slides x linearly toward the next onset when that onset is on the same page and system (lines 180-187). That slide is the per-note smooth movement the user wants gone.
- Systems: `_assignSystems` (lines 198-222) uses the explicit `systemIndex`, or derives a line break when x jumps back more than 25 percent of the page width. `_measureSystems` (lines 224-248) takes top and bottom from `systemTopY`/`systemBottomY`, or derives them from note y values.
- Drawing: `_ScorePage` (`lib/screens/playback/playback_screen.dart:1348-1433`). A `ValueListenableBuilder` on `display` (the audio position, a `ValueListenable<Duration>`) calls `timeline.positionAt` on every tick (line 1406) and draws a `Positioned` box with key `playback-band`. Its left is `band.x * scale - bandWidth / 2`, its width is 18 dp scaled to screen width (lines 1006-1007, 1294-1295). It is drawn only on the page whose index equals `band.pageIndex`.
- Scrolling: `_ScoreViewState._follow` (`playback_screen.dart:1234-1268`) runs on every `display` tick. It calls `positionAt`, converts to view coordinates, and if the band is outside the viewport it animates the `InteractiveViewer` matrix (350 ms, `_scrollDuration`, anchor 8 percent from the top or left). Manual pan or pinch sets `_manual` and stops following until play or a seek (`_onUserMove`, `_onJump`, lines 1210-1220). Pages are stacked vertically in one scroll view, so a page break is just a scroll.
- Seek and skip: `skipTargets` (`score_timeline.dart:21-56`) finds bar starts from events for the skip buttons. `_onJump` is triggered by `jumps`. Speed changes go to the engine (`playback_providers.dart:889-896`). The band is driven by the engine position, never a wall clock, so it needs no speed handling in the timeline.
- Related existing code that already derives bar starts: `lib/services/metronome_click.dart:261` (earliest event per bar).

## Proposed behaviour

The line stays put for the whole bar and jumps at the bar's start time to that bar's left barline x.

### Derive client-side (no schema change), with a fallback quality caveat

In `ScoreTimeline`, add a second index, built once in the constructor, with one `_BarStep` per (`bar`, `pageIndex`, `systemIndex`):

- `startMs`: the smallest `timestampMs` among events of that bar.
- `x`: the smallest `x` among events of that bar whose `tick` equals the bar's smallest tick (the downbeat). If events have no `tick`, use the smallest x of the bar.
- `top`/`bottom`: the existing system band from `_systems`.
- `positionAt(position)` then does the same binary search over `_BarStep`s and returns that step with no slide. Keep the old per-note path behind a constant `kBarStepLine = true` so the tests and the demo can cover both, the same pattern as `kSkipBackIncludesPickup` (`score_timeline.dart:9`).

Caveat the client cannot fix: the downbeat note x is not the barline. It is `left` of the bar, or the average of `left` and the CTC x when they agree within the blend limit (`timing_export.py:208-209`). The first bar of a system has no barline at all; its `left` is the median first-note x (`timing_export.py:189-190`). So the client-derived x carries unmeasured CTC error and sits a notehead to the right of the barline. A barline x from the backend (below) removes this. Recommendation: ship the client change with the derived x now, and switch to the backend field when it exists, using it when present and falling back to the derived x when it is absent.

### Edge cases

- Pickup bar (bar 0): treat it like any bar. Its step starts at t = 0. The line shows at the pickup's left (the first note). Do not skip it, because `kSkipBackIncludesPickup` already says a pickup is heard.
- Bar with no events (a bar of rests, if rests are not emitted as events): no step is created, so the line stays on the previous bar for that time. This is acceptable but wrong visually. The backend field `bars[].x` fixes it; the client cannot place such a bar.
- Bars with `bar == null` (Stage 4 could not number them): group by (`pageIndex`, `systemIndex`, `tick` rounded down to the nearest known bar start). If there is no `bars` table either, fall back to the old per-onset behaviour with no slide (still a step, per onset). Do not invent a bar grid.
- System break: bar steps carry their own system, so the line jumps to the new system's first bar at its start time. Remove the "same system" test used for sliding. `_follow` already scrolls when the band leaves the viewport.
- Page break: same as a system break; `_ScorePage` hides the band on other pages. `_follow` scrolls down the stack.
- Last bar: the line stays at the last step after the end, as today.
- Before the first step: wait on the first step, as today.
- Tempo or speed change: nothing to do. `positionAt` takes the engine's position, and the file's times are at the score tempo. Check once on a device that the engine position reported to `display` is in score time at speed != 1 (the existing slider tests suggest it is; I did not trace the engine). If the user changes the base tempo in settings, the file's `timestampMs` are fixed by the tempo the backend rendered; this is unchanged by this proposal.
- Seek: `positionAt` is a pure lookup, so a seek lands on the bar containing the target time. Because the line now jumps, scrubbing shows the line hopping between bars; this is correct. `_onJump` still clears the manual hold.
- Empty timing (`{"events": []}`): `parseTimingEvents` returns an empty list, `ScoreTimeline` is empty, `positionAt` returns null, no band is drawn, and the bar table is empty. Behaviour is unchanged. Note that an empty file currently produces no notice (only a parse or fetch failure does). Consider a quiet note, "Following along is not available for this score", so the user knows why there is no line.
- Chords across voices: bar start `x` uses the minimum across voices, which matches the backend's median-of-voices barline intent (`median_barlines`, `timing_export.py:71`).

### Smoother look (optional, not required)

Because the jump is abrupt, a short fade or a 120 ms slide on the band is possible, but it was not asked for and it would again suggest sub-bar precision. Skip.

## Files to change

1. `lib/models/score_timeline.dart`: add `_BarStep` index; make `positionAt` return the bar step; remove the slide (lines 180-187) in bar-step mode; add `kBarStepLine`.
2. `lib/screens/playback/playback_screen.dart`: no change needed. `_ScorePage` (line 1406) and `_follow` (line 1237) both call `positionAt` and get the new position. Do not add a second code path there.
3. `lib/models/measure_table.dart` and `lib/models/score_result.dart`: only when the backend adds `bars[].x` etc. Add optional `x`, `pageIndex`, `systemIndex`, `systemTopY`, `systemBottomY` to `BarInfo.tryParse` (all optional, invalid values give null), then pass `file.bars` into `ScoreTimeline` in `playback_providers.dart:613`.
4. `lib/services/demo/playback_demo.dart`: add the same bar fields to `barsJson()` if the backend field is adopted, so the demo shows the real behaviour.

## Tests to add

In `test/playback/score_timeline_test.dart`:

- A bar with notes at three onsets: `positionAt` at each onset's time returns the same x (the bar's downbeat x), and at the next bar's `startMs` it jumps.
- Pickup bar 0 then bar 1: first position is the pickup's x; jump at bar 1.
- System break: last bar of system 0 to first bar of system 1 changes `systemIndex` and top/bottom with no intermediate x.
- Page break: `pageIndex` changes.
- Chord across voices in the downbeat: x is the minimum.
- Events with `bar == null`: falls back to per-onset steps, no slide.
- Empty list: `positionAt` returns null.
- Before the first step and after the last step.
- Seek backwards: same result as a fresh lookup (pure function).
- A bar with no events between two bars keeps the previous bar's step.
- Flag off (`kBarStepLine = false`): the old sliding result, so existing tests keep passing. Existing slide tests in that file will need the flag or an update.

In `test/playback/playback_screen_test.dart`: the `playback-band` key's left offset stays constant while the display value moves inside one bar and changes at the bar start.

## Risks

- Downbeat note x is not the barline (see the caveat above). The line will sit about a notehead right of the barline, and the first bar of a system is anchored on a median first-note x. The visible error is usually smaller than the 18 dp-wide band, but it is not the measured 0.54 staff space figure.
- All-rest bars and unnumbered bars (`bar == null`) cannot be placed from events alone.
- Existing tests assert sliding; they must be updated, not silently deleted.
- The jump at a bar start is abrupt at slow speeds (long bars); users may read it as lag. This is the requested trade-off.
- `_follow` runs on every tick and animates a scroll when the band is off screen; a step jump to a new system will trigger one 350 ms animation per jump. That is fine, but check that it does not fight the audio at fast speeds with short bars.
- Unverified: whether the engine's reported position is in score time at speed != 1. Confirm on a device.
- Not run: no `flutter test` or device run was done for this advice.

## Backend fields (precise list)

Needed only to fix the accuracy caveat. The client works without them.

Add to each entry of `bars` in the timing JSON (built in `timing_export.py:217-219`):

- `x` (number, page pixels): left barline x of that bar, the measured barline value, not a note x. For the first bar of a system, the barline if detected, else the existing `left` edge.
- `pageIndex` (int, 0-based, the served page index, same as events).
- `systemIndex` (int, same numbering as events).
- `systemTopY`, `systemBottomY` (numbers): same values as on events, so a bar with no events can still be drawn.

Backend must also:

- Scale the new bar fields in `_scale_to_served_pages` (`backend/worker/main.py:87-105`), which today scales only `events`. Without that, bar x would be in 1600 px detection space and the line would be misplaced on the served 2250x3000-style page.
- Keep `bars` present for `{"events": []}`? No: keep the empty file as is. The app treats a missing `bars` as no table.
- Optionally add `xConfidence` (number) or `xMeasured` (bool) per bar so the app could hide the line for bars whose barline was extrapolated (the final barline is extrapolated by mean bar width when the CRNN drops it, `timing_export.py:113-115`). Not required.
- Add a contract test that `bars[i].x` lies inside the page width and is increasing within a (`pageIndex`, `systemIndex`).

Everything else (bar number, ticks, ms, system box) already exists in events or bars.
