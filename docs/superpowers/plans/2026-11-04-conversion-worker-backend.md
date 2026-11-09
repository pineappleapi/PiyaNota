# Conversion Worker Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A queued upload becomes a playable score with no human step: a polling worker (Hugging Face Space primary, user's PC backup) runs the v1 pipeline on CPU, stores the cleaned pages, four per-voice MP3s, a timing file and a thumbnail in Neon-backed storage, and the existing result endpoint serves them to the app.

**Architecture:** One worker package polls Neon (`FOR UPDATE SKIP LOCKED`), heartbeats, runs Stages 1-5 through an adapter, and publishes through the existing atomic `completion.complete_job`. A new `DbStorage` (Neon `bytea`) plus a signed `/media/<key>` route replaces the memory backend so the Render API and the worker, being separate processes, share files. The timing file (note highlight) is built on the pipeline side from CTC spans and barline medians, with an empty-events fallback.

**Tech Stack:** Flask + psycopg3 (existing `backend/`), pytest, PostgreSQL 16 on port 55432 for tests, the v1 pipeline copied into the repo root (stages 1-5, `stage3_clefkey.py`, `run_manifest.py`), torch CPU, ultralytics, FluidSynth + ffmpeg.

**Spec:** `docs/superpowers/specs/2026-11-04-conversion-worker-design.md` (decisions, constraints, risks). Where this plan and the spec disagree, the spec wins; record a ruling.

## Global Constraints

- CPU only: set `CUDA_VISIBLE_DEVICES=-1` (an empty value crashes ultralytics). BUG-013 makes local GPU results unverified.
- v1 checkpoints: `D:/PiyaNota/music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt` and `seed2/phase2_seed2.pt` (report both; seed1 is the worker default, seed2 is selectable), YOLO `D:/PiyaNota/staff_detector_files/weights/best.pt`, ClefKeyNet `D:/PiyaNota/.claude/worktrees/piya106-accidental-logic-fixes/training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt` (advisory only), soundfont `D:/PiyaNota/soundfont/piano.sf2`. Passed by environment variables `PIYA_CRNN_WEIGHTS`, `PIYA_YOLO_WEIGHTS`, `PIYA_CLEFKEY_WEIGHTS`, `PIYA_SOUNDFONT`, never hard-coded.
- Pipeline defaults: `TIE_FROM_SLUR_END_ENABLED=True`, `BAR_SINGLE_TOKEN_REPAIR_ENABLED=False` (Stage 4 branch `piya106/stage4-tie-bar-repair`, d66da30). The pipeline source of truth stays on the `piya106/*` branches; the backend repo gets copies via `git checkout <branch> -- <files>`, never edits.
- Moonriver is dev data used for tuning, NOT a blind piece. It is the backend smoke-test fixture only. No accuracy number from it is a result; no SER from this work is published until a truly unseen piece is run (still pending).
- Neon free is about 0.5 GB: delete the uploaded (standardized) page blob once the cleaned page replaces it.
- Backend tests: `backend/.venv/Scripts/python -m pytest backend/tests -q -W error` with the local Postgres on port 55432 (`pg_isready -p 55432` first; start command in memory note `module3-backend-status`). Tests that need torch/weights are marked `slow` and run with `D:/PiyaNota/.venv/Scripts/python`.
- PEP 8, type hints, Google docstrings explaining why, named constants, no silent `except`, no secrets in the repo or logs. Commit messages `PIYA-300: <summary>` (backend) or `PIYA-106: <summary>` (pipeline), ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UJSitkgXi5DTneLgDJkbH9`. Commit locally; never push or merge.
- Shell: Git Bash; literal paths and no shell variables or command substitution in commands that run python or git; no `git -C`; use targeted `git commit -- <paths>`.

## Review Focus

- Two workers claiming at once: a job must never be processed twice.
- A worker that dies or sleeps mid-job: the job must come back, with an attempt cap, and a live job must never be reclaimed.
- `/media` edge cases: expired link, tampered signature, `Range` forms (`bytes=0-99`, `bytes=100-`, `bytes=-50`, invalid or out-of-range gives 416), unknown key, `HEAD`.
- A job cancelled while the worker runs: uploads discarded, no score created.
- Neon quota: no orphaned blobs after complete, fail or cancel.

---

### Task 0: Record decisions and Moonriver's status in the Stage 4 decision doc

**Files:** Modify `docs/decisions/piya-106-stage4-tie-bar-repair.md` in worktree `D:/PiyaNota/.claude/worktrees/piya106-stage4-fixes` (branch `piya106/stage4-tie-bar-repair`).

- [ ] **Step 1:** Add a short dated section: Moonriver (already a dev piece used for tuning) is the backend smoke-test fixture, explicitly NOT a blind piece; the error-reduction evidence stays the dev-set ablation (chords_dataset full and cropped groups, flags off vs on); the blind-piece pass remains pending. Targeted edit, commit on that branch (`PIYA-106: ...`).

### Task 1: DbStorage, blobs migration and signed /media route

**Files:**
- Create: `backend/migrations/0003_worker_and_blobs.up.sql`, `.down.sql`; `backend/routes_media.py`; `backend/tests/test_db_storage.py`; `backend/tests/test_media_route.py`
- Modify: `backend/config.py` (storage backend choice `"db"`, `public_base_url`, `media_hmac_key`), `backend/storage.py` (`DbStorage`, `build_storage`), `backend/app.py` (register blueprint)

**Interfaces:**
- Produces: `class DbStorage` implementing `Storage` (`put`, `get`, `delete`, `signed_url`); `signed_url` returns an absolute `f"{settings.public_base_url}/media/{key}?exp=<unix>&sig=<hex>"` where `sig = HMAC-SHA256(media_hmac_key, f"{key}\n{exp}")`. Migration 0003 creates `blobs(key text primary key, content_type text not null, data bytea not null, created_at timestamptz not null default now())`, `jobs.attempts smallint not null default 0`, `jobs.heartbeat_at timestamptz`.
- Consumes: `db.transaction()`, `Settings`.

- [ ] **Step 1: Write failing tests.** `test_db_storage.py`: `test_put_get_roundtrip_and_content_type`, `test_delete_missing_key_is_not_an_error`, `test_put_overwrites`. `test_media_route.py`: `test_valid_link_returns_bytes_and_content_type`, `test_expired_link_403`, `test_tampered_signature_403`, `test_range_0_99_returns_206_with_content_range`, `test_open_ended_and_suffix_ranges`, `test_unsatisfiable_range_416`, `test_unknown_key_404`, `test_head_returns_length_without_body`, `test_signature_compare_is_constant_time` (assert `hmac.compare_digest` is used by patching it). Run them; they must fail.
- [ ] **Step 2:** Implement migration 0003 (with a working down), settings fields (prod requires `media_hmac_key` and `public_base_url` when `storage_backend == "db"`; dev defaults like the existing reset-code key), `DbStorage`, and `routes_media.py` (`GET`/`HEAD /media/<path:key>`, no auth, signature is the capability; `Cache-Control: private, max-age=0`; `Accept-Ranges: bytes`).
- [ ] **Step 3:** Run `backend/tests/test_db_storage.py backend/tests/test_media_route.py backend/tests/test_migrations.py` then the whole backend suite; all pass, no warnings.
- [ ] **Step 4:** Commit.

### Task 2: Job queue core (claim, heartbeat, reclaim)

**Files:** Create `backend/worker/__init__.py`, `backend/worker/queue.py`, `backend/tests/test_worker_queue.py`.

**Interfaces:**
- Produces (all take an open `conn` inside the caller's transaction):
  `claim_next_job(conn) -> dict | None` (oldest `queued` job, `FOR UPDATE SKIP LOCKED`; sets `status='preprocessing'`, `attempts = attempts + 1`, `heartbeat_at = now()`; returns the job row);
  `touch(conn, job_id: int) -> None` (updates `heartbeat_at` and `updated_at`);
  `set_stage(conn, job_id: int, status: str, percent: int, current_page: int | None) -> bool` (False when the job is no longer in a working status, i.e. cancelled);
  `reclaim_stale(conn, *, timeout_s: int, max_attempts: int) -> tuple[int, int]` (working-status jobs whose `heartbeat_at` is older than `timeout_s` go back to `queued`, or to `failed` with reason `worker_timeout` when `attempts >= max_attempts`; returns `(requeued, failed)`).
  Constants: `STALE_TIMEOUT_S = 1200`, `MAX_ATTEMPTS = 2`, `HEARTBEAT_INTERVAL_S = 60`.

- [ ] **Step 1: Failing tests** (real Postgres): `test_two_concurrent_claims_never_return_the_same_job` (two threads/connections, one queued job, exactly one wins), `test_claim_skips_cancelled_and_finished`, `test_claim_orders_oldest_first`, `test_set_stage_returns_false_when_cancelled`, `test_reclaim_requeues_stale_job`, `test_reclaim_fails_at_attempt_cap_with_reason`, `test_touch_prevents_reclaim`.
- [ ] **Step 2:** Implement; run the tests then the whole backend suite.
- [ ] **Step 3:** Commit.

### Task 3: Pipeline adapter

**Files:** Create `backend/worker/pipeline.py`, `backend/tests/test_worker_pipeline.py`.

**Interfaces:**
- Consumes: the copied stage modules (`stage1_preprocessing`, `stage2_detection`, `stage3_transcription`, `stage3_clefkey`, `stage4_reconstruction`, `stage5_synthesis`); model on the scratch driver `C:/Users/paul_/.claude/jobs/f4582ada/tmp/scratch/drive.py` and `tools/run_stage123_cache.py` in the Stage 4 worktree for the exact call signatures.
- Produces:
  `@dataclass class PipelineResult: mp3: dict[str, bytes]` (keys `soprano`/`alto`/`tenor`/`bass` lowercase), `failed_voices: list[str]`, `failed_voice_causes: dict[str, str]`, `review: dict`, `muted_measures: list[dict]`, `pages: list[CleanPage]` (`CleanPage(jpeg: bytes, width: int, height: int)`, the Stage 1 cleaned page), `events: dict`, `stage_seconds: dict[str, float]`;
  `run_pipeline(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, config: PipelineConfig, on_stage: Callable[[str, int], None]) -> PipelineResult`; `PipelineConfig.from_env(env) -> PipelineConfig` reading the `PIYA_*` paths.
  `on_stage(status, percent)` is called with the existing job statuses in order: `preprocessing`, `detecting_staff`, `transcribing`, `reconstructing`, `synthesizing`.
  Failure to read an input or a missing weights file raises `PipelineError(reason: str, page_index: int | None)`; a voice that comes back empty is reported in `failed_voices` with cause `unreadable`, not raised.

- [ ] **Step 1: Failing tests** with an injectable `stages` object holding fake stage callables: `test_stage_callbacks_fire_in_order`, `test_result_maps_voices_and_lowercases_keys`, `test_empty_voice_becomes_failed_voice_unreadable`, `test_missing_weights_raises_pipeline_error`. One `slow` test `test_moonriver_page1_end_to_end` (skips when weights are absent) that runs real stages on `D:/PiyaNota/data/chords_dataset/Moonriver/camera/p01.jpg` and asserts four non-empty MP3s and one cleaned page with positive size; run with the pipeline venv.
- [ ] **Step 2:** Implement (CPU forced with `CUDA_VISIBLE_DEVICES=-1`; temporary files only under `work_dir`); run the fast tests, then the slow test once and record the wall-clock per stage.
- [ ] **Step 3:** Commit.

### Task 4: Timing export (pipeline side; spike first)

**Files (worktree `D:/PiyaNota/.claude/worktrees/piya106-stage4-fixes`, new branch `piya106/timing-x-mapping` from `piya106/stage4-tie-bar-repair`):** Create `timing_export.py`, `tests/test_timing_export.py`, `docs/decisions/piya-106-timing-x-mapping.md`; Modify `stage2_detection.py` and `stage3_transcription.py` minimally to persist what the mapping needs.

**Interfaces:**
- Produces: `build_timing(events: dict, strips: list[StripGeometry], spans: dict, page_sizes: list[tuple[int, int]], bpm: int, ppq: int = 480) -> dict` returning the app schema: `{"events": [{"timestampMs", "pageIndex", "x", "y", "voice", "tick", "bar", "systemIndex", "systemTopY", "systemBottomY"}], "bars": [{"bar", "startTick", "durTicks", "startMs", "durMs", "numerator", "denominator"}]}`; `StripGeometry(page_index, sys_idx, voice, crop_x1, crop_y1, crop_x2, crop_y2, kx, ky)` persisted by Stage 2; `spans[(page, sys, voice)] = list[Span(token, first_frame, last_frame, measure_index)]` persisted by Stage 3 (barline tokens included). Algorithm per `docs/superpowers/specs/2026-11-04-conversion-worker-design.md` "Timing file generation": span midpoint to page x with `page_x = strip_x * (crop_h_src / 64) / kx` (4 strip pixels per CTC frame); barline x per bar as the median across voices (drop a voice whose barline count differs from the mode); notes placed by tick between barlines, blended with the CTC x only within about one staff space; y from `systemTopY`/`systemBottomY`; `timestampMs = tick / ppq * 60000 / bpm`.
- Failure contract: any internal inconsistency returns `{"events": []}` and a reason string logged by the caller, never an exception into the worker.

- [ ] **Step 1: Spike first (no production code).** In `docs/decisions/piya-106-timing-x-mapping.md` record, from reading the code: where spans exist today, what Stage 2 must persist, and the rotation-centre check between `strip_source` and the cleaned page. Confirm feasibility or stop and rule.
- [ ] **Step 2: Failing tests:** `test_page_x_formula_matches_hand_computed_example`, `test_barline_median_drops_voice_with_different_count`, `test_events_interpolate_between_barlines_by_tick`, `test_timestamp_ms_uses_bpm_and_ppq`, `test_inconsistent_input_returns_empty_events`, `test_output_matches_app_schema_keys` (keys and types per the app model in `mobile/piyanota_application/lib/models/score_result.dart`, read on `git show main:...`).
- [ ] **Step 3:** Implement the persistence changes behind an off-by-default argument (existing outputs unchanged when unused) and `build_timing`; run the new tests plus `tests/test_stage4_*`, `tests/test_review_api.py` and `ground_truth/` (one known pre-existing failure, `test_missing_barline_is_clipped_not_scaled`).
- [ ] **Step 4: Validate on real pages:** run Stages 1-3 on Moonriver p01-p04 (CPU), build the timing, overlay bar and note x on the cleaned pages (save PNGs outside the repo and read them), and compare barline x with an independent reference: vertical barline detection on the cleaned image (Hough or projection profile). Report median and p90 pixel error and the staff-space size. Moonriver is dev data; this is a feasibility check, not an accuracy claim.
- [ ] **Step 5:** Commit on `piya106/timing-x-mapping`. If the median barline error exceeds one staff space, set `TIMING_ENABLED` default to False in the adapter and record it; the fallback ships.

### Task 5: Worker loop, publish and health endpoint

**Files:** Create `backend/worker/main.py`, `backend/worker/health.py`, `backend/tests/test_worker_main.py`; copy the Task 4 module into the repo root via `git checkout piya106/timing-x-mapping -- timing_export.py stage2_detection.py stage3_transcription.py` (record the commit in the message).

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `process_one(*, storage: Storage, runner: Callable[..., PipelineResult], settings: Settings) -> bool` (False when no job was queued); `python -m backend.worker --once | --loop [--health-port N]`; `health.serve(port: int) -> threading.Thread` answering `GET /health` with `ok`.
- Behaviour of `process_one`, in one transaction per step: `reclaim_stale`; `claim_next_job`; fetch the job's pages from storage; start a heartbeat thread (`HEARTBEAT_INTERVAL_S`) that calls `touch`; run the pipeline with `on_stage` calling `set_stage` (stop and discard when it returns False); build timing and thumbnail; `background.reserve_keys` then `storage.put` for four MP3s, timing JSON, thumbnail, and the cleaned pages; replace the job's `job_pages` rows (`object_key`, `width`, `height`) with the cleaned pages and `queue_deletion` for the old keys; call `completion.complete_job`; if it returns None delete the uploads; on `PipelineError` or any other exception call `completion.fail_job(conn, job_id, reason, page_index)` with a short non-leaking reason (full traceback to the log only) and discard uploads.

- [ ] **Step 1: Failing tests** (fake runner, `MemoryStorage`, real Postgres): `test_happy_path_completes_job_and_replaces_pages_with_cleaned_ones`, `test_old_page_blobs_are_queued_for_deletion`, `test_pipeline_error_fails_job_with_reason_and_page_index`, `test_unexpected_exception_fails_job_without_leaking_traceback`, `test_job_cancelled_mid_run_discards_uploads_and_creates_no_score`, `test_heartbeat_updates_while_runner_blocks` (runner sleeps past two intervals with a short test interval), `test_no_queued_job_returns_false`, `test_failed_voice_is_omitted_from_audio_tracks`.
- [ ] **Step 2:** Implement; run the new tests and the whole backend suite.
- [ ] **Step 3:** Commit.

### Task 6: Result path and app-contract check

**Files:** Modify `backend/tests/test_scores.py` or create `backend/tests/test_result_after_worker.py`.

- [ ] **Step 1: Failing test** `test_result_serves_cleaned_pages_sizes_and_absolute_media_urls`: run `process_one` with a fake runner using `DbStorage`, then `GET /api/scores/{id}/result`; assert absolute `https` signed URLs, `scoreImageSizes` equal the cleaned page sizes, `audioTracks` has only non-failed voices, `timingMetadataUrl` fetches JSON through `/media` with a `Range` header. (The 409-for-unfinished mismatch frontend-lead raised does not apply: a score exists only once complete and the app polls job status first; record that in the ledger.)
- [ ] **Step 2:** Fix whatever the test exposes; run the whole backend suite; commit.

### Task 7: Space packaging

**Files:** Create `deploy/space/Dockerfile`, `deploy/space/README.md` (Hugging Face front matter: `sdk: docker`, `app_port: 7860`), `deploy/space/entrypoint.sh`, `deploy/space/requirements-worker.txt` (pinned), `deploy/space/.dockerignore`, `docs/deploy-hf-space.md`.

- [ ] **Step 1:** Dockerfile on a slim Python base: CPU torch wheels, ultralytics, midiutil, pydub, `fluidsynth`, `ffmpeg`, the pipeline stage files and `backend/` package, weights expected under `/app/models/` (committed to the Space repo with Git LFS: `.gitattributes` for `*.pt` and `*.sf2`), `ENV CUDA_VISIBLE_DEVICES=-1`, entrypoint `python -m backend.worker --loop --health-port 7860`.
- [ ] **Step 2:** `docs/deploy-hf-space.md` for the user, exact steps: create the Space (Docker, CPU basic, check no card is asked), add Space secrets `PIYA_DATABASE_URL` (Neon unpooled), `PIYA_STORAGE_BACKEND=db`, `PIYA_MEDIA_HMAC_KEY`, `PIYA_PUBLIC_BASE_URL` (the Render URL), `PIYA_ENV=prod`; copy the weights and soundfont into the Space repo; set the same `PIYA_STORAGE_BACKEND=db`, `PIYA_MEDIA_HMAC_KEY`, `PIYA_PUBLIC_BASE_URL` on the Render service; run migration 0003 against Neon; add an UptimeRobot monitor on `/health`; PC backup command. Docker cannot be built here (virtualization off), so verification is: `python -m backend.worker --once` against the local Postgres in the pipeline venv, and a read-through of the Dockerfile by the reviewer.
- [ ] **Step 3:** Commit.

### Task 8: Local end-to-end smoke on Moonriver

**Files:** Create `backend/scripts/smoke_convert.py`, `docs/decisions/conversion-worker-smoke-2026-11-04.md`.

- [ ] **Step 1:** Script: against the local test Postgres and `DbStorage`, create a user, upload Moonriver `p01`-`p04` through the real API client, run `process_one` with the real pipeline (CPU, seed1), then call the result endpoint, download each MP3 through `/media` with a `Range` request, validate the timing JSON against the app schema, and print wall-clock total and per-page, per-stage seconds.
- [ ] **Step 2:** Run it once; record in the smoke doc: total and per-page seconds (thesis target 1-2 min/page; PC CPU number only, the Space is unmeasured), MP3 sizes, blob bytes stored per score (Neon budget), timing barline error from Task 4, and any failure. State plainly that Moonriver is dev data and nothing here is an accuracy result.
- [ ] **Step 3:** Commit.

---

## Self-review

- Spec coverage: storage (Task 1), claim/heartbeat/reclaim (2), pipeline adapter (3), timing file and cleaned-page highlight (4, 5), worker publish and health (5), result path and Range (1, 6), Space packaging and HF secrets (7), real-run timing (8), Moonriver status (0). Not built here, needs the user: creating the HF Space and secrets, running migration 0003 on Neon, Render env vars, the UptimeRobot monitor, the blind piece.
- Types: `PipelineResult`, `CleanPage`, `PipelineError`, `process_one`, queue function names are used identically in Tasks 2, 3, 5, 6, 8.
- Known risks left to the executors: the stage call signatures in Task 3 (read from `drive.py`), the rotation-centre check in Task 4, `bytea` streaming size for large MP3s in Task 1.
