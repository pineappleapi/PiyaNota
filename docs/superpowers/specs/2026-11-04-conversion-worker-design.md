# Conversion worker and shared storage — design

Date: 2026-11-04. Status: draft, awaiting user approval. Branch: `feature/module3-backend`.

## Intent

Today a user can upload score photos and the backend queues a job, but nothing converts the photos into
audio. An operator has to run `backend/scripts/jobs_cli.py` by hand, and media URLs are dead because
storage is in-memory. This design adds the missing piece: a worker that takes a queued job, runs the
PiyaNota pipeline (Stages 1-5), and publishes the four per-voice MP3s so the app can play them.

The app will be evaluated by testers, and the user will not spend money. So everything must run on free
tiers, and testers must be able to convert a score without the user's PC being on.

## Decisions (made by the user, 2026-11-04)

- v1 uses the **monophonic** model: one note at a time per staff. Divisi and chords are out of scope.
- **Primary host: a Hugging Face Space** (Docker, CPU basic, free). **Backup: the user's PC**, running
  the same worker. Both run CPU-only.
- Storage and the Neon database stay on free tiers. No Backblaze B2 or other paid provider.
- The thesis target is **1-2 minutes per page** (NFR-1). Whether "per page" means end-to-end or compute
  only is still open (see Open questions).

## Goals

1. A queued job becomes a playable score with no human step.
2. The same worker code runs on the Space and on the PC, and both can run at once without processing a
   job twice.
3. Finished audio, timing and thumbnails are reachable from the app on phones.
4. A crashed or sleeping worker never leaves a job stuck forever.
5. Every run records its provenance (checkpoint hashes, timings) using the existing `run_manifest.py`.

## Non-goals and anti-goals

- No GPU use. BUG-013 (suspected GPU nondeterminism and driver hang) makes GPU numbers unverified.
- No divisi or chord support, no model retraining, no accuracy work. Real-phone accuracy is unmeasured
  (BUG-011) and this design does not change it.
- No change to the app's API contract. Failure here would be: the app needs edits to see a result.
- No new paid service, and no secrets in the repo or in logs.
- Not a general job-queue framework. One polling loop is enough.

## Architecture

```
phone app -> Render API (Flask) -> Neon Postgres  <-- worker (HF Space, or PC)
                  |                    ^                  |
                  +-- /media/<key> ----+ blobs table -----+
```

### Worker (new)

A polling loop, in a new module `backend/worker.py`, that reuses `jobs_cli` logic instead of
duplicating it:

1. **Claim** one job: `UPDATE jobs SET status='preprocessing' ... WHERE id = (SELECT id FROM jobs WHERE
   status='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING ...`. `SKIP LOCKED` is what
   lets the Space and the PC run at once safely.
2. **Fetch pages** from storage into a temp directory (what `jobs_cli._fetch_pages` does).
3. **Run Stages 1-5** with `stage5_synthesis.run_full_pipeline_with_report`-style call, CPU-only,
   passing a `RunManifest`. Update `jobs.status` and `percent_complete` between stages, using the
   existing status values (`preprocessing`, `detecting_staff`, `transcribing`, `reconstructing`,
   `synthesizing`) so the app's progress screen works unchanged.
4. **Publish**: reuse the `_complete` upload-then-`completion.complete_job` path, which is already
   atomic and handles orphan keys and cancelled jobs.
5. **On exception**: `completion.fail_job` with a short reason; never leave the job in a working status.
6. **Reclaim stale jobs**: a job in a working status whose `updated_at` is older than a timeout
   (my guess: 10 minutes, tunable) goes back to `queued`, with an attempt cap so a poison job fails
   instead of looping. The worker touches `updated_at` on each stage so live jobs are not reclaimed.

Retries need an `attempts` column on `jobs` (new migration `0003`). This is my call; the schema has none.

### Hosting the worker on a Hugging Face Space

- Docker Space, CPU basic. Image holds torch (CPU), ultralytics, fluidsynth, ffmpeg, the soundfont, the
  CRNN checkpoint(s) and `staff_detector_files/weights/best.pt`. The Space needs the model weights at
  build time, so they must come from somewhere the Space can read (open question below).
- Secrets as Space secrets: the Neon connection string and `PIYA_*` settings. Never baked into the image.
- Exposes a tiny `/health` endpoint. A Space sleeps after roughly 48 hours with no incoming traffic, and
  outbound database polling does not count as traffic. An UptimeRobot (or similar free) ping to
  `/health` during test windows keeps it awake. Cold start after sleep is about 1-2 minutes.
- The disk is ephemeral. Nothing durable is stored there; temp files only.

### Hosting the worker on the user's PC (backup)

Same code, started from the repo (`python -m backend.worker`) with CUDA hidden
(`CUDA_VISIBLE_DEVICES=""`) and the same Neon connection string in a local env file. For demo days the
user can stop the Space so only the PC takes jobs.

### Shared storage (new): `DbStorage`

`MemoryStorage` cannot work, because the worker is a separate process and cannot see pages uploaded to
Render. B2 was rejected over paid-tier worry. So:

- A new `DbStorage` implements the existing `Storage` protocol (`put`, `get`, `delete`, `signed_url`)
  and stores bytes in a `blobs(key text primary key, content_type text, data bytea, created_at)` table
  (migration `0003`). It is selected by a new storage setting alongside `memory` and `b2`.
- `signed_url` returns a Render route `/media/<key>?exp=...&sig=...`, checked with HMAC using the
  existing signing secret. A new Flask route streams the blob. This route is the main new API surface and
  needs a security review: signature check, expiry, no key enumeration, correct `Content-Type`, and
  HTTP range support if the audio player needs it (the audio player's range behaviour is unchecked).
- Page blobs (`job_pages`) are deleted after a job completes, to stay inside the Neon free quota
  (about 0.5 GB; backend-lead's estimate is roughly 5 MB per score including pages).
- The existing deletion queue (`background.queue_deletion`, `run_deletions`) works unchanged.

## Constraints

- Render free: 512 MB RAM, cold start about 50 s after idle. It does not run the pipeline.
- Space: 16 GB RAM, 2 vCPU (my assumption for CPU basic). Estimated 0.8-1.5 GB resident.
- Neon free: about 0.5 GB storage. Use the unpooled connection for the worker's `FOR UPDATE SKIP LOCKED`
  claim (the existing deployment already uses the unpooled URL).
- Latency is an estimate from ml-cv-lead (5-25 s per page for YOLO plus CRNN on 2 vCPU) and does
  **not** include Stage 1, Stage 5 (FluidSynth and MP3 for four voices) or the Space cold start.
  Nobody has timed it. A real timing run comes first (see Plan order).

## Risks testers will meet

- Space asleep: first conversion waits 1-2 minutes extra. Mitigate with the keep-alive ping.
- Neon quota full: uploads fail. Mitigate with page-blob deletion and a per-user job cap (existing
  throttles may already cover this; unchecked).
- Wrong audio: real-phone accuracy is unmeasured (BUG-011). The model is confidently wrong, and a wrong
  clef shifts every pitch for that voice. The existing `review` flags and `failed_voices` fields are the
  only signal. Testers should be told. This design adds no accuracy fix.
- Divisi passages are silently lost in v1.

## Plan order (for the plan, not decided here)

1. Time one real page on the PC with `CUDA_VISIBLE_DEVICES=""` through `stage5_synthesis.py`.
2. `DbStorage`, `blobs` migration, `/media` route, with tests.
3. `backend/worker.py` (claim, run, publish, fail, reclaim) with tests using a fake pipeline.
4. Space Dockerfile, `/health`, secrets, keep-alive ping.
5. Live smoke test: upload from the app, watch it convert, play it.

## Action items for the user

- Create a free Hugging Face account (needed before step 4). Unverified: whether Docker Spaces need a card.
  I believe CPU basic does not, but I have not checked.
- Create a free UptimeRobot (or equivalent) monitor once the Space exists.
- Decide how the model weights reach the Space (see Open questions).

## Open questions

1. Model weights: the CRNN checkpoints are about 96 MB each and the YOLO weights 22 MB. Git LFS is used in
   the main repo, but the Space needs its own copy. Options: push them to the Space's own git repo (the
   Space repo supports LFS), or upload them to a private Hugging Face model repo. My lean: the Space's own
   repo. This is the user's call because it puts the checkpoints on a third-party host.
2. Which checkpoint is v1? The notes say "path 4" (monophonic) but name no file. The worker needs one
   path and one SHA-256 in config.
3. Does ClefKeyNet (`clef_key_classifier.pt`, 5.5 MB, only in older worktrees) belong in v1? Not checked.
4. Does "1-2 minutes per page" mean end-to-end from tapping convert, or pipeline compute only?
5. Does the app's audio player need HTTP range requests on the `/media` route?
6. The Space needs the main-repo pipeline modules (`stage1_preprocessing.py` through
   `stage5_synthesis.py`, `run_manifest.py`). The backend worktree may not contain them, so how they get
   into the Space image (copy at build time) is left to the builder.

## Calls made after the builder check (my calls, not the user's)

- **Pipeline entry point:** `jobs_cli.py` mentions `stage5_synthesis.run_full_pipeline_with_report()`, but that
  function does not exist in this branch or in the main checkout (only `run_full_pipeline`, which returns a
  dict). The worker therefore gets a thin adapter that calls `run_full_pipeline` and builds the
  `failed_voices`, `review` and `timing` inputs that `completion.complete_job` expects. The builder must read
  what `run_full_pipeline` actually returns before sizing this adapter.
- **`run_manifest.py`** is not on this branch (it lives on `feature/piya106-run-manifest`, uncommitted). The
  worker records provenance only if that module is merged first; otherwise it logs checkpoint SHA-256 hashes
  and per-stage timings itself. Provenance is a goal, so the plan should resolve this before step 3.
- **Stale-job timeout:** 20 minutes, not 10, with the worker touching `updated_at` at least every 60 seconds
  from a heartbeat thread while a stage runs. A long Stage 3 therefore cannot look dead. Attempts capped at 2.
- **`/media` route:** implement HTTP `Range` support. It is small, and iOS-style or Android media players
  often need it for seeking. No need to check the app first.

## Playback requirements from the user (2026-11-04)

- Visual playback shows the **preprocessed (cleaned) Stage 1 page**, not the original photo. Backend stores
  that image under the page-image key, keeps `job_pages` width/height in sync, and measures timing x/y on the
  same pixels.
- The score view must be **vertically scrollable** (pages stacked, scrolling through the whole score). Not yet
  checked whether `playback_screen.dart` already scrolls vertically across pages; the plan must verify this
  and, if it does not, add it to the app (Module 2, so frontend-lead reviews).
- Mixer (per-voice volume/mute), speed control and a moving highlight must work with the real backend output.
  The moving highlight depends on a timing file (`timestampMs`, `pageIndex`, `x`, `y`) that no code produces
  yet; producing it is the main open piece of work.

## User answers and checkpoint findings (2026-11-04)

- Hard gate? No. Build regardless of the 1-2 min/page timing and report the real measured number.
- The model files may be stored in the Space repo.
- **v1 checkpoints (ml-cv-lead review, unrun):** `music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt`
  (SHA-256 `5c444ad3...eaf93`) and `seed2/phase2_seed2.pt` (`f79892ac...daed4`), about 96 MB each. Ship both and
  report results as a range; nothing on record separates the seeds. Use the base vocab; no extra vocab file.
  Dev-data numbers only (not held-out): camera SER 8.15-8.44%, pitch 95.30-95.62%. Same-stem divisi is a known
  silent loss; confident-wrong output (BUG-011) is unresolved.
- **ClefKeyNet:** `clef_key_classifier.pt` (5.5 MB, SHA-256 `e718d447...e10`) failed its pre-registered real-photo
  gate (clef 95.5% when sure, 4.5% confidently wrong). Use as advisory (`review_needed`) only. It is wired into
  Stage 3 only on branch `piya106/stroke-calibration` (`stage3_clefkey.py`, `infer_pitch_b`); the main checkout
  and this branch do not have it.
- **Pipeline code lives on another branch.** The worker needs `stage1-5`, `stage3_clefkey.py` and
  `run_manifest.py` from `piya106/stroke-calibration` / `feature/piya106-run-manifest`. Which commit the Space
  image pins, and how it is merged with `feature/module3-backend`, must be decided in the plan.

## Data storage plan (proposed, my calls)

| Data | Stored where | Kept how long |
|------|--------------|---------------|
| Camera upload (standardized 3000px JPEG) | `blobs`, referenced by `job_pages` | Deleted when the job completes or fails |
| Preprocessed Stage 1 page (cleaned) | `blobs`, replaces the `job_pages` key and width/height | Kept as long as the score exists; shown in playback |
| 4 per-voice MP3s, timing JSON, thumbnail | `blobs`, referenced by `audio_tracks`, `timing_metadata`, `scores` | Kept until the user deletes the score or account |
| Run manifest (hashes, timings, tokens) | `manifest.json` in `blobs`, or logged by the worker | Kept short-term; useful for the thesis timing report |

Budget guess: about 5 MB per score (4 pages, 4 MP3s). Neon free is about 0.5 GB, so roughly 80 scores. A cap
on stored scores per tester is likely needed. Encode the cleaned page as a grayscale JPEG or PNG; pick whichever
is smaller at readable quality (the builder measures this).

## Frontend connection plan (proposed)

No API-contract change except: (1) return 409 for an unfinished job on `GET /api/scores/{id}/result`; (2)
absolute signed URLs; (3) refresh signed URLs when expired (the app fetches images/timing without auth).
The app already plays four MP3s in sync with mute/solo, speed (`setSpeed`), a highlight driven by the timing
file, and draws any URL in `scoreImages`. Vertical scrolling of stacked pages needs checking in
`playback_screen.dart`. The timing file generator is the missing piece (below).

## Timing file generation (open, highest risk)

The app needs `{timestampMs, pageIndex, x, y}` per note on the cleaned page pixels. The pipeline's events have
`tick_onset` and `page_index` but no pixel x. ml-cv-lead's code reading (nothing run) found:

- **Frame to strip x exists only for visualization.** `_greedy_ctc_decode_with_confidence(spans_out=)` and
  `transcribe_strip(spans_out=)` in `stage3_transcription.py` return the CTC frame span per token. Each frame is
  4 strip pixels (`CNN_WIDTH_STRIDE`). Spans are collected only when `viz_dir` is set and are not stored in events.
- **The page Stage 2 sees is the page to ship.** YOLO runs on `PreprocessedPage.detect` (the cleaned Stage 1 output),
  and no geometry changes after it. Strips are cut from a native-resolution copy (`strip_source`), so
  `page_x = strip_x * (crop_h_src / 64) / kx`. Stage 2 must persist the per-strip adaptive crop `(y1, y2)` and `kx`;
  today its manifest keeps only the YOLO box.
- **Main geometric risk (unchecked):** `strip_source` is rotated with `warpAffine` about its centre; `correct_to_grid`
  rotates the shipped page the same way. Verify the centres agree, and check dewarped pages by eye.

**Algorithm (proposed):**
1. Stage 2 stores per-strip crop box and scale. Stage 3 always collects spans, including barline tokens (they are
   currently dropped; keep them with `measure_index`).
2. Convert span midpoints to page x. Per (page, system), take barline x per bar as the **median across the four
   voices**; discard a voice whose barline count differs from the mode.
3. Place each event inside its bar by tick, interpolating linearly between barlines. Blend with the CTC x only if
   within about one staff space of the interpolation; otherwise use the interpolation. Rests use interpolation
   only; accidentals use their note's x. Tied notes emit one highlight at the first note's x.
4. y: the app needs only `systemTopY`/`systemBottomY` per (page, system): min Soprano y1 and max Bass y2.
5. Time: `timestampMs = tick_onset / PPQ * 60000 / bpm`. The JSON must carry the same bpm used to render the MIDI
   (Stage 5 is constant tempo, default 90).

**Expected accuracy:** per-note CTC x is approximate (about 4-12 strip px, 1-3 frames). Barline-median
interpolation should be better. Target on Tikong_Tiko p01-p04: barlines median under 0.5 staff space, notes about
1 staff space. A missed barline can put a bar in the wrong place, and a wrong transcription (BUG-011) gives wrong
bar counts. Estimated effort 1-2 days. Validate on CPU only (BUG-013) by overlaying the x positions on the Stage 1
image and measuring against hand-marked barlines; four pages of one piece is a sanity check, not a statistic.

**Fallback:** if validation fails, ship with `{"events": []}` (audio, mixer and speed work; no highlight).

## Left to the builder

Module layout inside `backend/`, claim-query details and the stale timeout value, the `attempts` cap,
the Dockerfile contents, and test structure. Follow the existing style: flat modules, type hints,
no new frameworks.
