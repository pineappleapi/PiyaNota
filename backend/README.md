# PiyaNota backend

Flask API for Module 3. Configuration comes from `PIYA_*` environment variables (see
`backend/.env.example`); the app does not read a `.env` file itself.

## Where things are

| File / folder | Job |
|---|---|
| `app.py` | Flask app factory, JSON error envelope, `/healthz`. |
| `routes_auth.py`, `routes_account.py` | Sign-up, login, password reset, account info and deletion. |
| `routes_jobs.py` | Score upload (`POST /api/jobs`, `/api/jobs/pdf`), job status, cancel. |
| `routes_scores.py`, `routes_media.py`, `routes_piano.py` | Score library and results, signed media download, piano octave setting. |
| `config.py`, `db.py`, `migrate.py`, `migrations/` | Settings from `PIYA_*` variables, the Postgres pool, the SQL migration runner and its `.up.sql`/`.down.sql` files. |
| `security.py`, `access.py`, `throttle.py`, `validation.py` | Password hashing and sessions, per-user record scoping, rate limits, request checks. |
| `envelope.py`, `failure_codes.py`, `logutil.py` | Response format, the stable failure codes the app parses, log helpers that never print user data. |
| `storage.py`, `mailer.py`, `standardize.py`, `midi_combined.py` | Object storage, password-reset mail, upload/PDF page standardizing, the one combined MIDI the app plays. |
| `completion.py`, `background.py` | Marking a job done or failed, background cleanup (deletion queue, expiry). |
| `worker/` | The conversion worker (`python -m backend.worker --loop`): `queue.py` claims jobs, `pipeline.py` calls the Stage 1-5 modules at the repo root, `main.py` publishes the results. |
| `scripts/` | `smoke.py` (API contract check), `smoke_convert.py` (worker end to end on real photos), `jobs_cli.py` (operator CLI), `bench_intake.py` (upload benchmark), `check_secrets.py` (fails if git tracks a secret). |
| `tests/` | One `test_*.py` per area; need Postgres (see Tests). |
| `Dockerfile` | The API image Render builds from `render.yaml`. |

## Setup (Windows)

```
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
```

## Tests

Tests need PostgreSQL at `TEST_DATABASE_URL` (default `postgresql://piya:piya@localhost:55432/piya_test`).
Any Postgres 16 on port 55432 with that user, password and database works (a portable Windows build is fine
when Docker is not available). With Docker:

```
docker run -d --name piya-pg-test -e POSTGRES_USER=piya -e POSTGRES_PASSWORD=piya -e POSTGRES_DB=piya_test -p 55432:5432 postgres:16
```

Run from the repository root:

```
backend/.venv/Scripts/python -m pytest backend/tests -v
```

## Piano settings (PIYA-321)

`GET`/`PUT /api/users/me/piano-settings` (auth required; no `/api/v1` prefix, matching every other route). One saved octave per user (2-6). GET takes an optional `?voice=<VoicePart name>`: tenor/bass default to 3, anything else 4, used only until the first save (`isDefault: true`, `updatedAt: null`). PUT takes `octave` and optional `clientUpdatedAt` (UTC ISO 8601); an older `clientUpdatedAt` keeps the stored value and returns it. A `clientUpdatedAt` up to 5 minutes ahead is stored clamped to server now (`min(clientUpdatedAt, now)`) and the response returns that stored `updatedAt`; more than 5 minutes ahead is 400 `client_updated_at_invalid`. Validation codes (`octave_missing`, `octave_invalid`, `octave_out_of_range`, `client_updated_at_invalid`) are in `message` and `error.code`. Rate limit `PIYA_PIANO_SETTINGS_PER_MINUTE` (default 60, GET and PUT share it). Migration 0010.

## Job list endpoint

`GET /api/jobs` (no trailing slash; `/api/jobs/` is not routed) (auth required) returns `{"data": {"jobs": [...]}}`: the caller's jobs that are still
active, plus any created in the last 7 days (`LIST_WINDOW_DAYS`), newest first, at most 50
(`LIST_MAX_ITEMS`). Each item has the same shape as `GET /api/jobs/<ref>` (including `clientSubmissionId`,
echoed or `null`, and `createdAt`). Jobs whose score is in the deletion recovery window are omitted.
Jobs superseded by a retake are omitted (one row per capture). `replacesJobId` on `POST /api/jobs` accepts any terminal failed job of the caller (any `failureReason`; it is superseded at submit) or a complete job with unreadable voices; queued/running and clean complete jobs get 409 `not_retakeable`. There is no delete-job endpoint: failed jobs have no score row, so superseding covers it. Has its own rate limit
(`PIYA_LIST_READS_PER_MINUTE`, default 30/min), separate from per-job status polling (120/min).

## Cheap result revalidation

`GET /api/scores/<id>/result` takes two optional query params:

- `touch=false` skips the `last_accessed_at` write so a background refresh does not reorder the library.
  Default (absent or any other value) still touches.
- `version=<v>`: the payload always carries `version`, a sha256 prefix over the sorted file keys of every
  file the client downloads (audio, MIDI, combined MIDI, pages, timing) plus the non-file fields the app shows or
  plays from (title, arranger, tempo, review, mutedMeasures, failedVoices, failedVoiceCauses). It changes when
  a file is replaced or one of those fields is edited; it never depends on signed URLs or sizes. If `v` equals the
  current version the reply is `200 {"unchanged": true, "version": "<v>"}` with no signing or storage
  lookups. A different or absent `v` returns the full payload (additive `version` field only).

## Failure codes

`failureReason` on a failed job is a stable code the app parses (`backend/failure_codes.py`, one table); the
worker's raw text is in `failureDetail`. no readable page / unreadable page image -> `preprocessing_error`;
no readable staves / could not read the notation -> `no_staff_detected`; all voices empty ->
`incomplete_voice_sequence`; audio rendering failed / no playable audio -> `synthesis_failed`;
`max_runtime_exceeded` -> `stage_timeout`; `worker_timeout` -> `server_restart`; service misconfigured /
conversion failed -> `internal_error`. Text not in the table is passed through (the app shows it as unknown).

## Cancel by clientSubmissionId (before the 202)

`POST /api/jobs/by-submission/<clientSubmissionId>/cancel` (auth required, no body, UUID in the path).
Idempotent, owner-scoped, rate limited (own bucket, `PIYA_STATUS_READS_PER_MINUTE`).
- `200 {"clientSubmissionId", "jobId", "status"}`. `jobId` is the job when one exists, else `null`.
  `status` is `cancelled`, or the job's terminal status (`complete`/`failed`) when it had already finished (left alone).
- No job yet: a cancelled-intent is stored (migration 0009, pruned after 7 days). A later or in-flight
  `POST /api/jobs` (or `/pdf`) with that id gets `409 submission_cancelled` and creates nothing; the same holds for a
  retry of a job that was cancelled. The race is closed by the per-user submit lock both paths take.
- `400 invalid_client_submission_id` for a non-UUID, `401` unauthenticated, `429 rate_limited`.
Cancelling a retake (by id or by job ref) restores the failed job it replaced to the list and makes it retakeable again.

## Worker hung past the runtime cap

After `PIYA_JOB_MAX_RUNTIME_S` the heartbeat fails the job. If the pipeline has not returned 120 s later
(`HUNG_EXIT_GRACE_S`), the worker exits with code 3 (`os._exit`; a hung thread cannot be killed in-process).
Run the worker under a supervisor that restarts it (Docker `restart: always`, NSSM/Task Scheduler on Windows).
The worker also refuses to start on a schema older than its code (`check_schema`, exit 1).

## Smoke

`python -m backend.scripts.smoke <base_url>` covers the contract incl. cancel-by-submission. Add
`--check-active-cap` (opt-in, test/staging URLs: it queues up to 6 real jobs, then cancels them) to assert the
`429 too_many_active_jobs` cap.

## Job limits

- `PIYA_MAX_ACTIVE_JOBS_PER_USER` (default 2): queued plus running jobs one user may hold. Submit beyond it
  returns `429` `too_many_active_jobs` with `limit` and `Retry-After: 60`. Resubmitting an existing
  `clientSubmissionId` returns the existing job and is not counted.
- `PIYA_JOB_MAX_RUNTIME_S` (default 1800): wall-clock cap per attempt, measured from the worker claim
  (`jobs.started_at`, migration 0008). The worker fails an overrunning job with `failure_reason`
  `max_runtime_exceeded` and queues its page objects for deletion, like a cancel. Deploy the API (which
  migrates at boot) before the worker.
