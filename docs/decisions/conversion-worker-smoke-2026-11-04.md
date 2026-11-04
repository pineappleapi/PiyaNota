# Conversion worker local smoke, 2026-11-04

## What was run

`backend/scripts/smoke_convert.py` ran the whole worker path once on the four Moonriver photos (p01 to p04). It signs up a user against the local test Postgres (port 55432, database piya_test, never Neon), submits the four pages through the real `POST /api/jobs` endpoint with `DbStorage`, runs `process_one` with the real pipeline, then reads the result endpoint, downloads every MP3 through `/media` with a `Range` request, fetches the timing JSON and checks it against the shape the Flutter `TimingEvent.tryParse` accepts.

The backend venv has no torch and the pipeline venv has no psycopg, so `process_one` runs in the backend venv and its runner starts `run_pipeline` in a child process under the pipeline venv. Stage events stream back over stdout, so the job status moved live. Models were the real ones from the main checkout: CRNN `phase2_seed1.pt`, ClefKeyNet default checkpoint, YOLO `best.pt`, `piano.sf2`. CPU only (`CUDA_VISIBLE_DEVICES=-1`).

Moonriver is dev data. Nothing in this document is an accuracy result. The run proves that the plumbing works end to end; it says nothing about whether the notes, rhythms or highlights are right.

## Result

The job finished with status `complete` and no failed voices.

- Total wall clock for 4 pages: 204.8 s, which is 51.2 s per page. This is a PC CPU number. The thesis target is 1 to 2 minutes per page, so this is inside it on this machine. The Hugging Face Space speed is unmeasured and its CPU is likely slower.
- Per stage, for the whole 4-page job: preprocessing 102.0 s, staff detection 32.1 s, transcription (ClefKeyNet plus CRNN) 32.3 s, reconstruction under 0.1 s, synthesis 27.2 s. Preprocessing is half of the time. The earlier one-page run (Task 3) took about 33 s in total, so one page costs less than the 4-page average of 51 s; the reason was not investigated.
- MP3 sizes: soprano 2,616,885 bytes, alto 2,617,512, tenor 2,619,393, bass 2,622,528. All four were served with a 206 `Range` response for the first 1024 bytes and a full 200 response.
- Cleaned pages: four JPEGs, each 2250 x 3000, between 854 KB and 1.03 MB each, all served as valid JPEGs.
- Blob bytes stored for this score (4 MP3s, timing, thumbnail, 4 cleaned pages): 14,477,929 bytes, about 13.8 MiB. The whole `blobs` table held 20,022,386 bytes right after the run because the four standardized upload pages (about 5.5 MB) wait in the deletion queue until the API's background loop removes them. Against the Neon budget, plan on roughly 14 MB per 4-page score once the queue has drained, of which 10.5 MB is audio.
- Review object: `reviewNeeded` true, reasons `clef_key_unvalidated`, `mid_strip_meter_change`, `tenor_range_suspect`. That is expected: ClefKeyNet is still unvalidated, and Moonriver changes meter.

## Timing

Timing came out non-empty. The real Stage 2 geometry and Stage 3 barline wiring worked for real, not only with fakes: `build_timing` returned 334 events and 40 bars, covering all four voices and all four pages, with no unplaceable entry under the Flutter rules (timestamps, page index, x and y all valid). The fallback to `{"events": []}` was not used.

Barline accuracy comes from the Task 4 spike (`docs/decisions/piya-106-timing-x-mapping.md` in the `piya106-stage4-fixes` worktree): "Barline x error vs reference: median 4.6 px = 0.54 staff space; p90 7.1 px = 0.83 staff space (n = 40)". That was measured on the same Moonriver dev photos, so it is a feasibility number only. Note x was not measured.

### Problem found: timing coordinates are in the wrong pixel space

The timing x and y values are measured on the 1600 px detection page, but the cleaned page the app receives is the native-resolution page (2250 x 3000 here). The largest x in the timing file is 1016 and the largest y is 1438 (system bottom 1456), against pages that are 2250 wide and 3000 tall. The ratio is about 1.875 (3000 / 1600). Task 5 listed this as unchecked. As served today, the playback highlight would land at roughly 53 percent of the correct position on every page. The Flutter model documents x and y as "pixels in the original preprocessed page image", and the smoke only checks that entries are well formed, not that they match `scoreImageSizes`. The fix is to scale x, y, `systemTopY` and `systemBottomY` by cleaned size over detection size per page (or serve the detection-size page). It was not made here because it needs a decision on where to scale and a test.

## Other findings

- EXIF orientation: the first attempt failed with `no readable staves`. The Moonriver JPEGs are 4032 x 3024 with EXIF orientation 6. The server drops EXIF on purpose and the pipeline reads the stored pixels, so the page arrived sideways. The Flutter app bakes the orientation in before upload (`page_image_processor.dart`), so the smoke script now does the same. A client that uploads a raw camera JPEG with an orientation tag will fail conversion. This is by design, but any other client must bake orientation first.
- The sideways attempt printed Stage 1 warnings ("no tracked staves", "no native strip source"); the successful run printed none.
- Process exit prints psycopg pool "couldn't stop thread" hints because the smoke script closes the pool while workers are idle. This is harmless script noise.

## Failures

None in the final run. One failed run (sideways pages, above) was a fixture problem, not a worker bug.
