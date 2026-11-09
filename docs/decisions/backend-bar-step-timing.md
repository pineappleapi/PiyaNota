# Backend timing for a bar-step playback line

Date: 2026-11-04. Status: implemented 2026-11-04 (PIYA-300, Task 4); real Moonriver smoke rerun still pending. Author: backend review.

## Question

The app's blue vertical playback line should move once per measure, jumping to the bar's left edge at the bar's start tick, instead of moving per note. Only barline x was measured (median error 0.54 staff space, p90 0.83, n = 40, on the Moonriver dev photos, see `docs/decisions/conversion-worker-smoke-2026-11-04.md`). Note-level x was never measured. Should the backend change nothing, or emit explicit per-bar entries?

## What exists today

`timing_export.build_timing` already returns `{"events": [...], "bars": [...]}`. Each `bars` entry has `bar`, `startTick`, `durTicks`, `startMs`, `durMs`, `numerator` and `denominator`. The pickup is bar 0, and it exists only at the start of the first system. The app already parses this list in `mobile/piyanota_application/lib/models/measure_table.dart` (`BarInfo.tryParse`). It ignores keys it does not know, and it also reads an optional `pickup` boolean.

The bar entries carry no position. `build_timing` does compute the position internally: `_bar_edges` returns a (left, right) page x for every bar of every system, and `_build` also has the system top and bottom y. Those values are used to interpolate note x and are then thrown away.

## Decision: option (b), additive

The backend should add position fields to the existing `bars` entries. It should not add a second array and it should not remove or change any `events` field.

Reasons:

1. The app cannot derive bar x. It would have to rebuild `_bar_edges`, which needs the median barline, the missing-last-barline extrapolation and the strip geometry. Only the backend has that data. Deriving "bar starts" from `events` would give the x of the first note in a bar, which is exactly the unmeasured quantity the user wants to avoid.
2. Option (a) also fails at the pickup and at bars that begin with a rest, because there is no event at the bar's start tick for a voice or for any voice.
3. The cost is small. The values already exist in `_build`, and the app is already tolerant of extra keys, so the shipped app keeps working unchanged.

## Exact fields

Keep every existing bar field as is. Add these to each `bars` entry:

- `pageIndex` (int, 0-based, same numbering as events). This is `out_page` in `_build`.
- `systemIndex` (int, the Stage 2 `sys_idx`, same value events carry).
- `x` (float, rounded to 1 decimal). The left edge of the bar, in page pixels. This is `edges[idx][0]`. It is scaled to the served page like event x.
- `systemTopY` and `systemBottomY` (float). The same values events carry. Scaled by the height ratio.
- `pickup` (bool, true only for bar 0 when `pickup_ticks > 0`). The app already reads this key.

Do not add `startSeconds`. `startMs` already exists as an int and the app uses it. A second time unit would invite drift between the two.

What `x` means must be written in the code comment: for bar `j > 0` in a system, `x` is the median barline of the previous bar, which is the measured quantity. For the first bar of a system (and for the pickup in system 0), `x` is the median first-note x, because the header width is not known. That value is not a barline and has not been measured. The doc for the app should say the line at the start of each system may sit slightly right of the barline, by roughly the gap between the clef or key header and the first note.

## Where in the code

1. `timing_export.py`, `_build`. Build the `out_bars` list inside the per-system loop, where `edges`, `top`, `bottom` and `out_page` are in scope, instead of after the loop from the flat `bars` list. Emit one entry per element of `sys_bars`, zipped with `edges`. Keep the final sort by `startTick`, then `pageIndex`. `by_system` is built from `bars`, so every bar of every system is covered with no bar skipped.
2. `_bar_layout` needs no change. It already knows page and system for each bar. The pickup is only added when `i == 0`.
3. `backend/worker/main.py`, `_scale_to_served_pages`. It loops over `timing["events"]` only. Change the loop to cover `timing.get("events", []) + timing.get("bars", [])`. Both lists use `pageIndex`, and the same `SCALED_KEYS` apply (`x`, `systemTopY`, `systemBottomY`; `y` is simply absent on bars and the existing `isinstance` check skips it). Without this change the bar line would sit at about 53 percent of the correct x, which is the defect already found in the smoke run. This is the most likely thing to be forgotten.
4. `_timing_bytes` needs no change. It already writes whatever `build_timing` returns.

## Page and system breaks, pickup

- A bar belongs to exactly one system and one page, so a break needs no special case. When the bar index crosses to a bar with a different `systemIndex` or `pageIndex`, the app jumps the line to that bar's `x` and system band. The backend sends the bars already ordered by `startTick`, so the app can walk the list.
- The pickup (bar 0) starts at tick 0 and has its own entry with `pickup: true`. Bar 1 starts at `pickup_ticks`. Both are in system 0, page 0.
- The Stage 4 known gap, mid-bar system breaks, is unchanged. If a bar straddles a break, the existing geometry checks already raise and the whole file falls back.
- Per-measure meter changes are already carried by `numerator` and `denominator` per entry.

## Failure fallback

No change to the contract. `build_timing` still never raises. Any inconsistency (barline count that cannot be reconciled, no first-note anchor, non-increasing barlines, missing geometry) returns `{"events": []}`, with no `bars` key. `_timing_bytes` still returns `{"events": []}` when timing is disabled, has no inputs, or any exception escapes. `TimingFile.parse` in the app already treats a missing or non-list `bars` as no table, and an empty `events` as no highlight, so audio still plays. Bars and events succeed or fail together. Do not emit bars when events are empty, and do not emit events without bars if bar geometry fails, because the app would then have two different highlight behaviours depending on the song.

An old row in storage keeps its old timing file without the new fields. The app must treat a missing `x` on a bar as "fall back to the existing per-event highlight", so it needs to handle both shapes. This is app-side work.

## Tests

In `backend/tests/test_worker_main.py` (next to `test_timing_scaled_to_served_page_and_missing_size_is_safe`):

1. Extend the scale test: a `bars` entry on page 0 with `x` 100, `systemTopY` 160 and `systemBottomY` 240 scales to 187.5, 240 and 360 with the same sizes. A bar on a page with a zero detection width stays unscaled. A timing dict with no `bars` key does not crash.

There is no unit test of `build_timing` in the repo today (the only caller test fakes it). Add `backend/tests/test_timing_export.py` with a small hand-built input (two systems on one page, a pickup, three voices):

2. Every bar has the new fields, `pageIndex` is 0-based, and the list is sorted by `startTick`.
3. The pickup entry has `bar` 0, `pickup` true and `startTick` 0. Bar 1 starts at `pickup_ticks`.
4. `x` of bar `j > 0` equals the median previous barline in page pixels. `x` of the first bar equals the median first-note x.
5. The second system's first bar has the second `systemIndex` and a different `systemTopY`.
6. A missing last barline (n_bars minus 1 barlines) still gives a full `bars` list.
7. An inconsistent input (barline count off by two) returns exactly `{"events": []}`.
8. Compatibility: every pre-existing key is still present with an unchanged value, and event entries are byte-for-byte what they were.

Extend `backend/scripts/smoke_convert.py`, which already counts bars, to check that every bar has finite `x` inside the served page width. Rerun it on the Moonriver photos: expect 40 bars, as before.

## Honest limits

- The 0.54 staff-space number was measured on dev photos and is a feasibility number only, not accuracy evidence.
- First-bar x of each system is a first-note estimate, not a barline. If the user wants the line to hit the true barline there, that needs a header-width measurement that does not exist yet.
- The backend treats the rendered tempo as constant (`bpm`), so `startMs` is exact for the audio the pipeline renders, and the line will follow the audio, not the written score tempo.
