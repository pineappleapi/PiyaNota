# Module 3 Backend (API + DB, no conversion worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployed, free-hosted Flask API that the existing Flutter app (`mobile/piyanota_application`) can run against with `USE_FAKE_AUTH=false`: accounts, password reset by emailed code, score library, score edit/delete, score upload intake (photos + PDF), job status/cancel and score results — everything except the image-to-audio conversion worker.

**Architecture:** Flat Python package `backend/` (one module per concern, matching the repo's flat stage-script style), raw parameterized SQL via psycopg 3 (no ORM), versioned SQL migrations with a tiny in-house runner. Private files live in an S3-compatible bucket and are handed to the app only as signed, expiring URLs. Background work (storage deletions, account purge) is a durable Postgres queue drained by one in-process thread. Jobs are created `queued` and stay there; `complete_job()` (PIYA-321) is real code, driven today by an operator CLI and later by the pipeline worker.

**Tech Stack:** Python 3.12, Flask 3, gunicorn, psycopg 3 + psycopg_pool, argon2-cffi, boto3 (S3 API for Backblaze B2), Pillow, pypdfium2, pytest. Hosting: Render free web service, Docker (API), Neon free Postgres (DB), Backblaze B2 free (files), Brevo transactional email HTTPS API (email). The future conversion worker runs separately (e.g. a Hugging Face Space) and talks to the API and B2 over HTTPS only.

**Spec:**
- `docs/tickets/module3-backend.md` (PIYA-300…323 plus "V2 notes" B1–B5 and the background-polling note) — the source of truth for every AC quoted by ID below.
- `docs/tickets/module1-pipeline.md` PIYA-101 (AC1–AC12), PIYA-102 (AC1–AC9), PIYA-103 (AC1–AC10), PIYA-114 — only their API surface; no pipeline stage work.
- App contract: `mobile/piyanota_application/lib/config/api_config.dart` and `lib/services/*_api.dart` (summarized in Global Constraints; the app is not modified by this plan).

**User decisions (2026-11-01):** skip the conversion worker but build the intake layer; free hosting = HF Spaces + Neon + B2; reset email = Gmail SMTP app password; **revised 2026-11-01 after review found HF Spaces block outbound 5432/587: API on Render free (kept awake by an UptimeRobot 5-min ping), email via Brevo HTTPS API, conversion worker later on an HF Space over HTTPS;** ERD before any code; execute subagent-driven with cheaper models where possible.

## Global Constraints

- All routes under `/api` (module3 header). Paths are the app's, verbatim: `POST /api/auth/login`, `POST /api/auth/signup`, `POST /api/auth/password-reset/request`, `POST /api/auth/password-reset/confirm`, `POST /api/auth/change-password`, `GET /api/scores[?search=]`, `PATCH|DELETE /api/scores/{scoreId:int}`, `GET /api/scores/{scoreId:int}/result`, `POST /api/jobs` (multipart, repeated file part `pages`), `POST /api/jobs/pdf` (multipart, one file part `file`), `GET /api/jobs/{jobId}`, `POST /api/jobs/{jobId}/cancel`. New (app not wired yet, PIYA-217): `POST /api/auth/logout`, `GET /api/account`, `DELETE /api/account`.
- Success envelope: `{"data": <obj|null>, "success": true, "status": <int>, "message": <str>}`. Error envelope (PIYA-101 AC9): `{"data": null, "success": false, "status": <int>, "message": <str>, "error": {"code": <str>, "field"?: <str>, "pageIndex"?: <int>, "retryAfterSeconds"?: <int>}}`. Every 429 also sets a `Retry-After` header (integer seconds). No HTML error pages ever (404/405/413/500 included).
- ID types: `userId` int, `scoreId` positive int, `jobId` string `"job_<int>"`. Timestamps ISO-8601 UTC with `Z` (`2026-09-03T14:22:00Z`). Optional fields are **omitted**, never `null`, except where a ticket schema shows `null` (PIYA-102 `failureReason`/`failedVoices`/`failedVoiceCauses`).
- Auth: `Authorization: Bearer <token>`; any missing/expired/revoked/malformed token → 401 `unauthorized`, same body for every cause (PIYA-314 AC5).
- Email normalized = trimmed + lowercased (V2 B1.1). Password policy = ≥8 chars, ≥1 ASCII letter, ≥1 digit (PIYA-301 AC3), one shared validator.
- Media URLs (audio, page images, thumbnail, timing) are signed, expire after `SIGNED_URL_TTL_SECONDS` = 3600, object keys are random UUIDs (PIYA-308 AC9). The app fetches them with no auth header.
- Every value from config lives in `backend/config.py` `Settings`, read from env; no secret in the repo (PIYA-318 AC1). Named constants, type hints, Google docstrings, no bare `except:` (CLAUDE.md).
- Commit messages `PIYA-XXX: <summary>`, ending with the session's Co-Authored-By/Claude-Session lines. Commit freely on `feature/module3-backend`; never merge or push to `main`.
- Tests run against a real Postgres 16 (`docker run` in Task 2); storage and mail use in-memory fakes in tests.

## Review Focus

1. Email typed with spaces/capitals at sign-up (`" Maria@Example.COM "`) then logged in lowercase → same account, one row (Task 5 test `test_email_normalized_across_signup_and_login`).
2. Body that is not a JSON object (`[]`, `null`, `"x"`, broken JSON, wrong content-type) on any JSON endpoint → 400 `invalid_json`, never 500 (Task 2 test `test_json_body_rejects_non_object`, reused by Tasks 6–8, 13).
3. Two sign-ups for the same email at the same moment → exactly one 201 and one 409 `email_already_registered`, never 500 (Task 5 test `test_concurrent_signup_one_wins`).
4. Neon suspends idle compute and drops connections → the next request after a dropped connection succeeds (Task 2 test `test_pool_recovers_after_backend_terminated`).
5. A 200-character or emoji password at sign-up/login → works (argon2, no bcrypt 72-byte limit) (Task 4 test `test_hash_long_unicode_password`).

---

### Task 1: ERD + free-hosting decision (docs only, USER CHECKPOINT)

**Implementer model:** sonnet. **Tickets:** PIYA-311 AC5, PIYA-300 (amendment).

**Files:**
- Create: `docs/backend/erd.md`
- Create: `docs/decisions/piya-300-amendment-free-hosting.md`
- Modify: `docs/decisions/piya-300-database-hosting.md` (top: one-line "Superseded in part by …amendment-free-hosting.md (2026-11-01)")

**Interfaces:**
- Produces: the schema every later task implements. Task 3's migration must match this file column-for-column.

- [ ] **Step 1: Write `docs/backend/erd.md`** — a Mermaid `erDiagram` plus one table per entity (column, type, null, default, constraint, ticket reference). Entities and columns (exact):
  - `users`: id bigserial PK; email text NOT NULL UNIQUE (stored normalized); password_hash text NOT NULL; role text NOT NULL DEFAULT 'choir_member' CHECK in ('choir_member','choir_director'); deleted_at timestamptz NULL; created_at, updated_at timestamptz NOT NULL DEFAULT now().
  - `sessions`: id bigserial PK; user_id FK users ON DELETE CASCADE; token_hash bytea NOT NULL UNIQUE (SHA-256 of token); expires_at; revoked_at NULL; created_at.
  - `password_reset_tokens`: id; user_id FK CASCADE; token_hash bytea (HMAC-SHA256 of the 6-digit code, V2 B4.1); expires_at; used_at NULL; created_at.
  - `jobs`: id bigserial PK; user_id FK CASCADE; score_id FK scores ON DELETE SET NULL, NULL until complete; status text CHECK in ('queued','preprocessing','detecting_staff','transcribing','reconstructing','synthesizing','complete','failed','cancelled'); source text CHECK in ('images','pdf'); page_count smallint CHECK 1–20; title text NOT NULL CHECK char_length 1–120; arranger text NULL CHECK 1–120; tempo_bpm smallint NOT NULL DEFAULT 90 CHECK 30–240; tempo_source text NOT NULL CHECK in ('user','fallback','default'); key_signature text NULL CHECK in the 15 PIYA-101 AC8 values; time_signature text NULL CHECK in ('4/4','3/4','2/4','6/8','2/2'); current_page smallint NULL; percent_complete smallint NOT NULL DEFAULT 0 CHECK 0–100; failure_reason text NULL; failure_page_index smallint NULL; failed_voices jsonb NOT NULL DEFAULT '[]'; failed_voice_causes jsonb NOT NULL DEFAULT '{}'; replaces_job_id / superseded_by_job_id FK jobs ON DELETE SET NULL; completed_at NULL; created_at; updated_at. Partial unique index `jobs (replaces_job_id) WHERE status NOT IN ('complete','failed','cancelled')` (PIYA-311 AC8). Index `jobs (user_id, status)`.
  - `job_pages`: id; job_id FK jobs CASCADE; page_index smallint ≥0; object_key text NOT NULL; width, height int > 0; created_at; UNIQUE (job_id, page_index).
  - `scores`: id bigserial PK; user_id FK CASCADE; title (same CHECK as jobs); arranger; page_count smallint NOT NULL CHECK 1–20; tempo_bpm; tempo_source; key_signature; time_signature (same CHECKs); thumbnail_key text NULL; review jsonb NOT NULL; muted_measures jsonb NOT NULL DEFAULT '[]'; failed_voices jsonb NOT NULL DEFAULT '[]'; failed_voice_causes jsonb NOT NULL DEFAULT '{}'; last_accessed_at NULL; created_at; updated_at. Index `scores (user_id)`.
  - `audio_tracks`: id; score_id FK CASCADE; voice text CHECK in ('soprano','alto','tenor','bass'); file_key text; created_at; UNIQUE (score_id, voice).
  - `timing_metadata`: id; score_id FK CASCADE UNIQUE; metadata_key text; created_at.
  - `throttle_hits`: id; bucket text; key text (HMAC of email/IP/user id, never raw); created_at; index (bucket, key, created_at).
  - `throttle_backoff`: (scope, key) PK; failures int; last_failure_at; wait_until NULL; created_at; updated_at.
  - `storage_deletions`: id; object_key text; attempts int DEFAULT 0; next_attempt_at DEFAULT now(); last_error text NULL; created_at; updated_at.
  - `purge_log`: id; user_ref bigint (former users.id, no FK, no PII); completed_at; created_at.
  - `schema_migrations`: version text PK; applied_at.
  Record these deviations from PIYA-311 AC1 with reasons: `audio_tracks.file_url`→`file_key` and `timing_metadata.metadata_url`→`metadata_key` (URLs are signed per request, PIYA-308 AC9); added `sessions`, `job_pages`, throttle, deletion-queue and purge tables; `password_reset_tokens.token_hash` is an HMAC (V2 B4.1); score delete removes that score's jobs too (their page images are the "score images" PIYA-309 must delete).

- [ ] **Step 2: Write the amendment** `docs/decisions/piya-300-amendment-free-hosting.md`: decision (Neon kept; DigitalOcean + RunPod replaced by Render free web service (Docker) for the API, Backblaze B2 for files, Brevo HTTPS API for email; future conversion worker on a Hugging Face Space that uses only HTTPS), why (evaluation testing only, not a public launch; $0, no card), why not HF for the API (HF Spaces allow outbound only on 80/443/8080, so Postgres 5432 and SMTP 587 are blocked), free-tier limits to verify at signup (Render: 512 MB RAM, 750 instance-hours/month, sleeps after 15 min idle with ~1 min wake, so an UptimeRobot 5-min ping keeps it awake for the app's 15 s timeout; ephemeral disk, which is why files live in B2; B2: 10 GB, private bucket; Brevo: 300 mails/day, one verified sender), PIYA-317/318 impact (Render terminates TLS with auto-renewed certs and redirects HTTP; Neon encrypts at rest; enable B2 SSE-B2), GPU (none; conversion later on HF CPU or run by the operator locally via the Task 11 CLI), PIYA-401/407 impact (no Droplet; PIYA-407 timing is measured where the worker runs), action items (accounts to create).

- [ ] **Step 3: Commit**
```bash
git add docs/backend/erd.md docs/decisions/piya-300-amendment-free-hosting.md docs/decisions/piya-300-database-hosting.md
git commit -m "PIYA-311: ERD and free-hosting amendment to PIYA-300"
```

- [ ] **Step 4: STOP — user reviews the ERD and the hosting amendment.** Do not start Task 2 until the user approves. Apply requested changes, recommit.

---

### Task 2: Backend scaffold — config, DB pool, envelope, app factory, test harness

**Implementer model:** haiku. **Tickets:** PIYA-318 AC1/AC2, PIYA-101 AC9 envelope.

**Files:**
- Create: `backend/__init__.py`, `backend/config.py`, `backend/db.py`, `backend/envelope.py`, `backend/validation.py` (only `json_body`, `require_str` here), `backend/app.py`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/.env.example`, `backend/README.md`
- Create: `backend/tests/conftest.py`, `backend/tests/test_app_basics.py`
- Modify: `.gitignore` (add `backend/.env`, `.env`)

**Interfaces:**
- Produces:
  - `Settings` frozen dataclass + `load_settings(env: Mapping[str, str] = os.environ) -> Settings`. Fields and defaults: `env: Literal["dev","test","prod"]`; `database_url: str`; `require_https: bool` (default False; True required when env=prod); `argon2_time_cost: int = 3`; `argon2_memory_kib: int = 65536`; `session_ttl_days: int = 30`; `reset_code_ttl_minutes: int = 30`; `reset_code_hmac_key: bytes`; `log_hash_key: bytes`; `storage_backend: Literal["b2","memory"]`; `b2_endpoint`, `b2_bucket`, `b2_key_id`, `b2_app_key: str`; `signed_url_ttl_seconds: int = 3600`; `mail_backend: Literal["brevo","memory","log"]`; `brevo_api_key: str`; `mail_from: str` (the Brevo-verified sender); `mail_from_name: str = "PiyaNota"`; `trusted_proxy_count: int = 1`; `max_content_length: int = 100 * 1024 * 1024`; `max_image_bytes = 10 MB`; `max_pdf_bytes = 50 MB`; `max_image_pixels = 50_000_000`; `standard_max_side_px: int = 3000`; `pdf_render_dpi: int = 200`; `submit_limit_per_hour = 10`; `status_reads_per_minute = 120`; `login_ip_limit = 30` per `login_ip_window_s = 900`; `reset_request_email_per_hour = 5`; `reset_request_ip_per_hour = 20`; `reset_code_ip_per_hour = 30`; `change_password_limit = 5` per 900 s; `queue_capacity: int = 50`; `run_background: bool = False`; `background_interval_s: int = 15`. Missing required secret in env=prod → `RuntimeError` naming the variable.
  - `db.init_pool(url: str) -> None`; `db.transaction() -> ContextManager[psycopg.Connection]` (dict_row, commits on exit, rolls back on exception). Pool: `psycopg_pool.ConnectionPool(..., check=ConnectionPool.check_connection)`.
  - `envelope.ok(data: object, status: int, message: str) -> tuple[Response, int]`; `class ApiError(Exception)` with `__init__(self, status: int, code: str, message: str, *, field: str | None = None, page_index: int | None = None, retry_after: int | None = None)`.
  - `validation.json_body() -> dict[str, object]` (400 `invalid_json` unless the body parses to a JSON object); `validation.require_str(body: Mapping[str, object], field: str) -> str` (400 `missing_field` with `field` when absent, non-string or blank).
  - `app.create_app(settings: Settings | None = None) -> Flask`: registers JSON handlers for `ApiError`, 404 (`not_found`), 405 (`method_not_allowed`), 413 (`request_too_large`), 500 (`internal_error`, generic message, logged with traceback server-side only); `GET /healthz` → 200 `{"data": {"ok": true}, ...}`; `MAX_CONTENT_LENGTH` from settings; `werkzeug.middleware.proxy_fix.ProxyFix(x_for=trusted_proxy_count, x_proto=trusted_proxy_count)`. Blueprints from later tasks are registered here.
  - Test fixtures in `conftest.py`: `settings` (env=test, memory storage, memory mail, `argon2_time_cost=1`, `argon2_memory_kib=8`), `app`, `client`, `db_clean` (truncates all tables between tests), reading `TEST_DATABASE_URL` (default `postgresql://piya:piya@localhost:55432/piya_test`).

- [ ] **Step 1: Start test Postgres**
Run: `docker run -d --name piya-pg-test -e POSTGRES_USER=piya -e POSTGRES_PASSWORD=piya -e POSTGRES_DB=piya_test -p 55432:5432 postgres:16`
Expected: container id printed; `docker exec piya-pg-test pg_isready` → "accepting connections".

- [ ] **Step 2: Write failing tests** in `backend/tests/test_app_basics.py`:
  - `test_healthz_ok`: GET `/healthz` → 200, `body["success"] is True`.
  - `test_unknown_route_json_404`: GET `/api/nope` → 404, `body["error"]["code"] == "not_found"`, content-type JSON.
  - `test_json_body_rejects_non_object`: a test-only route using `json_body()` returns 400 `invalid_json` for bodies `[]`, `null`, `"x"`, `{bad`, and for a non-JSON content-type.
  - `test_internal_error_is_generic`: a route raising `RuntimeError("secret detail")` → 500, `"secret detail" not in response.text`.
  - `test_prod_settings_require_secrets`: `load_settings({"PIYA_ENV": "prod"})` raises `RuntimeError`.
  - `test_pool_recovers_after_backend_terminated`: open `db.transaction()`, run `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()` from a second connection, then a new `db.transaction()` runs `SELECT 1` successfully.

- [ ] **Step 3: Run** `pytest backend/tests/test_app_basics.py -v` → FAIL (import errors).
- [ ] **Step 4: Implement** the files above. `backend/requirements.txt` pins exact versions (PIYA-112 style): Flask, gunicorn, psycopg[binary], psycopg-pool, argon2-cffi, boto3, Pillow, pypdfium2. `requirements-dev.txt`: `-r requirements.txt`, pytest. `.env.example` lists every env var with placeholder values.
- [ ] **Step 5: Run** `pytest backend/tests -v` → all PASS.
- [ ] **Step 6: Commit** `PIYA-318: backend scaffold, config, JSON error envelope, test harness`.

---

### Task 3: Migrations runner + initial schema

**Implementer model:** sonnet. **Tickets:** PIYA-311 AC1–AC7/AC8, PIYA-312 AC1–AC4.

**Files:**
- Create: `backend/migrate.py`, `backend/migrations/0001_initial.up.sql`, `backend/migrations/0001_initial.down.sql`, `backend/tests/test_migrations.py`
- Modify: `backend/tests/conftest.py` (session fixture applies migrations once)

**Interfaces:**
- Consumes: `docs/backend/erd.md` (Task 1) — exact columns/constraints.
- Produces: `migrate.status(conn) -> list[tuple[str, bool]]` (version, applied); `migrate.up(conn, to: str | None = None) -> list[str]` (applied versions); `migrate.down(conn, to: str) -> list[str]`; CLI `python -m backend.migrate {status|up|down} [--to VERSION]` using `DATABASE_URL`. Each migration file runs inside one transaction together with its `schema_migrations` insert/delete.

- [ ] **Step 1: Write failing tests:**
  - `test_up_fresh_db_creates_all_tables`: on an empty schema, `up()` returns `["0001"]`; every table in the ERD exists.
  - `test_up_is_idempotent`: second `up()` returns `[]`, no error.
  - `test_status_reports_pending_and_applied`: before → `[("0001", False)]`; after → `[("0001", True)]`.
  - `test_down_then_up_roundtrip`: `down(to="0000")` drops every ERD table and the row; `up()` recreates.
  - `test_failed_migration_rolls_back`: a temp migrations dir with `0002_bad.up.sql` = `CREATE TABLE t_ok(id int); SELECT 1/0;` → `up()` raises; `t_ok` does not exist; `0002` not in `schema_migrations`.
  - `test_fk_cascade_user_delete`: insert user + score + job + job_page + audio_track + session; `DELETE FROM users` → all child tables empty.
  - `test_check_constraints`: inserting `jobs.tempo_bpm = 29`, `key_signature = 'H'`, `title = ''`, `page_count = 21` each raises `psycopg.errors.CheckViolation`.
  - `test_one_unfinished_retake_per_job`: two `queued` jobs with the same `replaces_job_id` → `UniqueViolation`; second allowed once the first is `failed`.
- [ ] **Step 2: Run** `pytest backend/tests/test_migrations.py -v` → FAIL.
- [ ] **Step 3: Implement** `migrate.py` (sorted `NNNN_*.up.sql` files, `migrations_dir` parameter for the test) and the SQL (`CREATE TABLE IF NOT EXISTS`, CHECK constraints not ENUMs per PIYA-311 AC7; `updated_at` maintained by one `set_updated_at()` trigger function on mutable tables).
- [ ] **Step 4: Run** → PASS. Also `python -m backend.migrate status` against `TEST_DATABASE_URL` prints both columns.
- [ ] **Step 5: Commit** `PIYA-311: initial schema migration and PIYA-312 migration runner`.

---

### Task 4: Security core — hashing, sessions, auth decorator, validators, throttle

**Implementer model:** sonnet. **Tickets:** PIYA-313, PIYA-314, PIYA-316 AC2, V2 B1/B4 counters (primitives only).

**Files:**
- Create: `backend/security.py`, `backend/throttle.py`, `backend/tests/test_security.py`, `backend/tests/test_throttle.py`
- Modify: `backend/validation.py`

**Interfaces:**
- Produces:
  - `security.hash_password(password: str) -> str`; `security.verify_password(password: str, stored: str) -> bool` (argon2id, params from settings; `VerifyMismatchError` → False).
  - `security.issue_session(conn, user_id: int) -> tuple[str, datetime]` (token `"sess_" + secrets.token_urlsafe(32)`, row stores SHA-256 only, expiry `now + session_ttl_days`).
  - `security.revoke_user_sessions(conn, user_id: int, *, keep_token_hash: bytes | None = None) -> None`.
  - `security.token_hash(token: str) -> bytes`; `security.keyed_hash(value: str) -> str` (HMAC-SHA256 hex with `log_hash_key`; used for log lines and throttle keys).
  - `@security.require_auth` decorator: resolves Bearer token to a non-revoked, non-expired session of a user with `deleted_at IS NULL`, sets `g.user = AuthUser(id: int, email: str, role: str)` (role read from DB, PIYA-316 AC2) and `g.token_hash: bytes`; else `ApiError(401, "unauthorized", "Unauthorized")`. Never reads the token from the query string.
  - `security.client_ip() -> str` (`request.remote_addr` after ProxyFix).
  - `validation.normalize_email(raw: object, field: str = "email") -> str` (400 `missing_field` if absent/blank, 400 `invalid_email` unless it matches `^[^@\s]+@[^@\s]+\.[^@\s]+$` after trim+lower); `validation.check_password_policy(password: str, field: str) -> None` (400 `weak_password` with `field`).
  - `throttle.window_retry_after(conn, bucket: str, key: str, limit: int, window_s: int) -> int | None` (seconds until the oldest counted hit leaves the window when count ≥ limit, else None); `throttle.record_hit(conn, bucket: str, key: str) -> None`.
  - `throttle.backoff_wait(conn, scope: str, key: str) -> int | None` (remaining seconds of an active wait); `throttle.record_failure(conn, scope: str, key: str, *, free_failures: int) -> int` (returns N; wait = `min(900, 30 * 2 ** (N - 1 - free_failures))` when N > free_failures; failures reset to 0 first if `last_failure_at` is older than 24 h); `throttle.clear_failures(conn, scope: str, key: str) -> None`.
  - `throttle.too_many(retry_after: int) -> ApiError` → 429 `rate_limited` with `retry_after` set (Retry-After header + `error.retryAfterSeconds`).

- [ ] **Step 1: Write failing tests:**
  - `test_hash_is_salted_and_verifies`: two hashes of the same password differ; both verify; wrong password → False; hash starts with `$argon2id$`.
  - `test_hash_long_unicode_password`: `"pä55wörd🎵" * 20` hashes and verifies.
  - `test_cost_params_from_settings`: hash encodes `t=` / `m=` from settings.
  - `test_session_token_shape_and_storage`: token starts `sess_`, len ≥ 40; DB row has no plaintext token (`token_hash = sha256(token)`).
  - `test_require_auth_rejects_all_bad_tokens_identically`: missing header, `Bearer junk`, expired, revoked, deleted-user tokens → identical status 401 and identical JSON body.
  - `test_require_auth_role_from_db`: session for a director user → `g.user.role == "choir_director"`.
  - `test_revoke_keeps_calling_token`: 3 sessions; revoke with `keep_token_hash` of one → only that one still authenticates.
  - `test_normalize_email`: `" Maria@Example.COM "` → `"maria@example.com"`; `"no-at"` → 400 `invalid_email`.
  - `test_password_policy`: `"abcdefgh"`, `"12345678"`, `"abc1"` → 400 `weak_password`; `"abcdefg1"` passes.
  - `test_window_limit` (throttle): limit 2/60 s: two hits → None, third check → int in (0, 60].
  - `test_backoff_sequence_login`: free=0 → after failures 1,2,3 waits ≈30, 60, 120; after 10 failures wait == 900.
  - `test_backoff_sequence_reset_code`: free=2 → failures 1,2 no wait; 3 → 30; 4 → 60.
  - `test_backoff_resets_after_24h_idle`: set `last_failure_at = now() - 25h` with failures=5 → next `record_failure` returns 1.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `PIYA-313: argon2 hashing, PIYA-314 sessions, auth decorator and durable throttles`.

---

### Task 5: Sign-up and login (PIYA-301, PIYA-302, V2 B1)

**Implementer model:** sonnet. **Files:** Create `backend/routes_auth.py` (blueprint `auth_bp`, prefix `/api/auth`), `backend/tests/test_auth_signup_login.py`; Modify `backend/app.py` (register).

**Interfaces:**
- Consumes: Task 4 (`normalize_email`, `check_password_policy`, `hash_password`, `verify_password`, `issue_session`, `throttle.*`, `keyed_hash`, `client_ip`), Task 2 (`json_body`, `require_str`, `ok`, `ApiError`).
- Produces: `auth_bp` (later tasks add routes to it); `session_payload(user_row: Mapping, token: str, expires_at: datetime) -> dict` → `{"userId": int, "email": str, "role": str, "sessionToken": str, "expiresAt": "…Z"}`; `iso_z(dt: datetime) -> str` in `backend/envelope.py`.

Behaviour (codes the app depends on): signup 201 "Account created"; 400 `missing_field`/`invalid_email`/`password_mismatch` (field `passwordConfirmation`)/`weak_password` (field `password`); 409 `email_already_registered` (also when the unique index fires under a race). Login 200 "Login successful"; 400 `missing_field`; 401 `invalid_credentials` message "Incorrect email or password" for unknown email and wrong password alike; 429 per V2 B1 (check per-email backoff, scope `login_email`, key `keyed_hash(email)`, and per-IP window `login_ip`, **before** the password check); success clears the email backoff; wrong password → `record_failure(free_failures=0)` + `record_hit("login_ip", …)` + log line with `keyed_hash(email)` and timestamp, never the password. Role in the request body is ignored.

- [ ] **Step 1: Write failing tests:**
  - `test_signup_success_shape`: 201; `data` keys exactly `{userId, email, role, sessionToken, expiresAt}`; `isinstance(userId, int)`; `role == "choir_member"`; `expiresAt` ends with `Z`; the token authenticates `GET /healthz`-free auth probe (use `require_auth` test route).
  - `test_signup_validation_codes`: each of missing email/password/passwordConfirmation, mismatch, weak, malformed email → expected code and field.
  - `test_signup_duplicate_409`.
  - `test_signup_ignores_role_field` (PIYA-316 AC4): body with `"role": "choir_director"` → stored role `choir_member`.
  - `test_concurrent_signup_one_wins`: two threads sign up the same email → statuses sorted == [201, 409].
  - `test_email_normalized_across_signup_and_login`.
  - `test_login_success_shape` and `test_login_generic_401` (unknown email and wrong password give byte-identical bodies).
  - `test_login_backoff_429`: wrong password once → 401; immediately again with the **right** password → 429 `rate_limited`, `Retry-After` header ≈ 30, `error.retryAfterSeconds` int.
  - `test_login_success_clears_backoff` (expire the wait by updating `wait_until` in DB, log in correctly, next wrong attempt waits 30 again).
  - `test_login_ip_limit`: 30 wrong logins across 30 different emails from one IP → 31st returns 429.
  - `test_password_never_logged`: with `caplog`, run signup + failed login using password `"Secret123zz"`; `"Secret123zz" not in caplog.text`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `PIYA-301: sign-up and PIYA-302 login with V2 login wait`.

---

### Task 6: Password reset by emailed code (PIYA-303, PIYA-304, V2 B3/B4)

**Implementer model:** sonnet. **Files:** Create `backend/mailer.py`, `backend/tests/test_password_reset.py`; Modify `backend/routes_auth.py`, `backend/app.py`.

**Interfaces:**
- Produces: `mailer.Mailer` Protocol `send_reset_code(to: str, code: str) -> None`; `BrevoMailer` (stdlib `urllib.request` POST to `https://api.brevo.com/v3/smtp/email`, header `api-key`, JSON `{"sender": {"email", "name"}, "to": [{"email"}], "subject": "Your PiyaNota reset code", "textContent"}`, 10 s timeout; non-2xx raises `MailError`), `MemoryMailer` (`sent: list[tuple[str, str]]`), `LogMailer` (dev only: logs the code); `get_mailer() -> Mailer` from `app.extensions["mailer"]`.

Behaviour: **request** — 400 `missing_field`/`invalid_email`; then throttle (windows `reset_req_email` 5/h keyed by email hash and `reset_req_ip` 20/h) checked **before** lookup, and every request is recorded; unregistered → 404 `email_not_registered`, no mail (V2 B3); registered → mark previous unused codes used, store `hmac(reset_code_hmac_key, code)` with 30-min expiry, send `f"{secrets.randbelow(10**6):06d}"`, 200 "If this email is registered, a reset link has been sent". A send failure → 500 `internal_error` and the new code row rolled back. **confirm** — body `email`, `resetToken`, `newPassword`, `newPasswordConfirmation`; 400 `missing_field`; per-email backoff (scope `reset_code`) and per-IP window (`reset_code_ip` 30/h) → 429 without checking the code; no live code for that email → 410 `reset_token_expired_or_invalid`; weak/mismatch password → 400 `weak_password`/`password_mismatch`, code not consumed, not counted; wrong code (`hmac.compare_digest`) → `record_failure(free_failures=2)` + 400 `reset_code_invalid`; success (one transaction): new hash, code `used_at`, revoke all sessions, clear `reset_code` and `login_email` backoffs → 200 "Password reset successful".

- [ ] **Step 1: Write failing tests:**
  - `test_reset_request_registered_sends_code`: 200; `MemoryMailer.sent == [(email, code)]`, code matches `^\d{6}$`; DB stores no plaintext code.
  - `test_reset_request_unregistered_404_no_mail`.
  - `test_reset_request_rate_limited_before_lookup`: 5 requests for an unregistered email → 404 ×5, 6th → 429 (not 404).
  - `test_new_code_invalidates_old`: request twice; confirming with the first code → 400 `reset_code_invalid` (a live reset exists, the code is wrong); confirming with the second code → 200.
  - `test_confirm_success_revokes_sessions`: existing session token → 401 after reset; login with new password works.
  - `test_confirm_expired_410` (set `expires_at` in the past) and `test_confirm_used_410`.
  - `test_wrong_code_backoff`: wrong ×2 → 400 `reset_code_invalid` both; 3rd wrong → 400 and then the next request (even correct code) → 429 ≈30 s.
  - `test_weak_password_does_not_consume_code`: weak → 400 `weak_password`; then correct code + good password → 200.
  - `test_mail_failure_rolls_back`: a mailer that raises → 500; no live code row.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `PIYA-303: reset code request and PIYA-304 confirm with V2 limits`.

---

### Task 7: Logout, account info, change password, delete account (PIYA-305/306/307/322)

**Implementer model:** sonnet. **Files:** Create `backend/routes_account.py` (blueprint, routes `GET/DELETE /api/account`), `backend/tests/test_account.py`; Modify `backend/routes_auth.py` (logout, change-password), `backend/app.py`.

Behaviour: **logout** `POST /api/auth/logout` — `require_auth`; set `revoked_at` on the calling session → 200 "Logged out"; reuse → 401. (PIYA-305 AC4 "200 even if already expired" conflicts with AC1 "401 if already invalid"; implement AC1, since an expired token never passes `require_auth` — record this in the ticket notes in Task 14.) **account** `GET /api/account` → 200 `{"email", "role", "accountCreatedAt"}` exactly, message "Account info retrieved". **change-password** per PIYA-322 AC1–AC7: 400 `missing_field`; 429 window `change_pw` (5 wrong per user per 900 s, checked first, key `keyed_hash(str(user_id))`); 403 `invalid_current_password`; 400 `weak_password` field `newPassword`; success transaction: new hash + revoke other sessions (keep calling token) → 200 "Password changed". **delete account** `DELETE /api/account` body `{"password": str}`: 400 `missing_field`; 403 `invalid_current_password`; success (one transaction): `users.deleted_at = now()`, revoke all sessions → 200 "Account deletion initiated". Purge happens in Task 8.

- [ ] **Step 1: Write failing tests:**
  - `test_logout_revokes`: 200, then same token on `GET /api/account` → 401; second logout → 401.
  - `test_account_info_trimmed`: `set(data) == {"email", "role", "accountCreatedAt"}`.
  - `test_change_password_flow`: wrong current → 403 `invalid_current_password`; weak → 400 field `newPassword`; success → 200; calling token still works; another session of the same user → 401; login with new password works.
  - `test_change_password_rate_limit`: 5 wrong → 403 ×5; 6th → 429 with `Retry-After`.
  - `test_change_password_ignores_role`: body `"role": "choir_director"` → role unchanged.
  - `test_delete_account_requires_password`: wrong → 403; missing → 400.
  - `test_delete_account_marks_and_revokes`: 200; `deleted_at` set; token → 401; login → 401 `invalid_credentials`; sign-up with the same email → 409 (purge not yet run, PIYA-307 AC5).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `PIYA-305: logout, PIYA-306 account info, PIYA-322 change password, PIYA-307 delete account`.

---

### Task 8: Storage, deletion queue, account purge (PIYA-309 AC3, PIYA-319)

**Implementer model:** sonnet. **Files:** Create `backend/storage.py`, `backend/background.py`, `backend/tests/test_storage_background.py`; Modify `backend/app.py` (create storage + mailer extensions; start loop when `run_background`).

**Interfaces:**
- Produces:
  - `storage.Storage` Protocol: `put(key: str, data: bytes, content_type: str) -> None`; `get(key: str) -> bytes`; `delete(key: str) -> None` (missing key is not an error); `signed_url(key: str) -> str`.
  - `B2Storage(settings)` (boto3 `s3` client, `endpoint_url=b2_endpoint`, `signature_version="s3v4"`, `generate_presigned_url("get_object", ExpiresIn=signed_url_ttl_seconds)`); `MemoryStorage()` (dict; `signed_url` returns `f"https://storage.test/{key}?sig=fake"`); `storage.new_key(prefix: Literal["pages","thumbs","audio","timing"], ext: str) -> str` → `f"{prefix}/{uuid4()}.{ext}"`; `get_storage() -> Storage`.
  - `background.queue_deletion(conn, keys: Iterable[str]) -> None`; `background.run_deletions(storage: Storage, limit: int = 100) -> int` (deletes due rows; on error `attempts += 1`, `next_attempt_at = now() + min(3600, 30 * 2**attempts)` s, `last_error` set); `background.run_purges(storage: Storage) -> int` (per user with `deleted_at` set, in one transaction: collect every page/thumbnail/audio/timing key, `queue_deletion`, `DELETE FROM users WHERE id = …` (FK cascade), insert `purge_log(user_ref, completed_at)`, log `"account purge complete user_ref=<id>"`); `background.start_loop(app: Flask) -> threading.Thread` (daemon; every `background_interval_s` runs both; exceptions logged, loop continues).

- [ ] **Step 1: Write failing tests:**
  - `test_memory_storage_roundtrip`, `test_new_key_is_random_uuid` (two keys differ, match `^pages/[0-9a-f-]{36}\.jpg$`).
  - `test_b2_signed_url_has_expiry` (moto not used: construct `B2Storage` with fake creds and assert the presigned URL contains `X-Amz-Expires=3600` — presigning is offline).
  - `test_deletion_queue_deletes_and_retries`: queue 2 keys; storage whose `delete` fails once for key A → after first run: B gone, A row attempts=1 with future `next_attempt_at`; force due; second run removes A.
  - `test_purge_cascades_and_logs`: user with score, job, pages, audio, timing, session, reset token marked deleted → `run_purges` returns 1; no rows left in any user-linked table; all keys queued; `purge_log` has `user_ref`; sign-up with that email now → 201.
  - `test_purge_failure_leaves_account_marked`: make the purge transaction fail (monkeypatch `queue_deletion` to raise) → user row still present with `deleted_at` set; next run succeeds.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `PIYA-319: storage layer, durable deletion queue and account purge`.

---

### Task 9: Upload intake — standardization, PDF rasterization, job creation (PIYA-101, 310, 320, 323)

**Implementer model:** sonnet. **Files:** Create `backend/standardize.py`, `backend/routes_jobs.py` (blueprint, `POST /api/jobs`, `POST /api/jobs/pdf`), `backend/tests/test_standardize.py`, `backend/tests/test_jobs_submit.py`, `backend/tests/fixtures/` (generated in conftest, not committed binaries: tiny JPEG with EXIF Orientation=6, PNG, 2-page PDF, encrypted PDF, 21-page PDF — build PDFs with pypdfium2 or Pillow `save(..., "PDF")`); Modify `backend/validation.py`, `backend/app.py`.

**Interfaces:**
- Produces:
  - `standardize.sniff(data: bytes) -> Literal["jpeg","png","pdf"] | None` (magic bytes only).
  - `standardize.standardize_image(data: bytes, page_index: int) -> StandardPage` where `StandardPage = NamedTuple(jpeg: bytes, width: int, height: int)`: Pillow decode **without** `exif_transpose`; >`max_image_pixels` → 413 `image_pixels_too_large` (`page_index` set); undecodable → 422 `corrupt_image`; convert to RGB; downscale so the long side ≤ `standard_max_side_px` (LANCZOS, aspect kept); re-encode JPEG quality 90 with no EXIF/ICC/comments.
  - Memory (Render free = 512 MB): decode, standardize and store one page at a time; never hold all decoded pages at once. PDF pages are rendered one at a time too.
  - `standardize.rasterize_pdf(data: bytes) -> list[bytes]` (PNG per page at `pdf_render_dpi`): encrypted or unparsable → 422 `corrupt_or_encrypted_pdf`; > 20 pages → 400 `too_many_pages` before rendering.
  - `validation.parse_score_metadata(form: MultiDict[str, str]) -> ScoreMetadata` (dataclass: `title: str`, `arranger: str | None`, `tempo_bpm: int`, `tempo_source: Literal["user","fallback","default"]`, `key_signature: str | None`, `time_signature: str | None`, `replaces_job_id: int | None`) implementing PIYA-101 AC8 + PIYA-323 exactly: trim + NFC, code-point length, Cc characters → `_invalid`, empty optional = absent, duplicate field → `duplicate_field`, `tempoBpm` and `fallbackTempoBpm` together → `duplicate_field`, ASCII-digit 30–240 else `invalid_tempo` (field named), enumerations exact-case.
  - `routes_jobs.job_ref(job_id: int) -> str` → `"job_<id>"`; `routes_jobs.parse_job_ref(ref: str) -> int | None`.
  - `routes_jobs.create_job(conn, user_id: int, meta: ScoreMetadata, pages: list[StandardPage], source: Literal["images","pdf"]) -> dict` — writes pages to storage first, then inserts `jobs` + `job_pages` in one transaction; on any failure deletes the keys already written (PIYA-101 AC11).
  - `submitted_payload(job_row: Mapping) -> dict` → `{"jobId": str, "userId": int, "pageCount": int, "status": "queued", "submittedAt": "…Z", "title": str, "tempoBpm": int}` plus `arranger`/`keySignature`/`timeSignature`/`replacesJobId` only when present.

Error precedence (PIYA-101 AC9, implement in this order): 401 → 429 `rate_limited` (window `submit` 10/user/h, shared by both endpoints, recorded on success) → 413 (`file_too_large` one image > 10 MB / PDF > 50 MB; `request_too_large` from Flask) → 400 metadata field errors → 400 `mixed_input_types` (PDF in `pages` or both `pages` and `file`) / `multiple_pdfs` / `no_pages` → 415 `unsupported_file_type` (with `pageIndex`) → 422 → 400 `too_many_pages` → retake checks (404 `job_not_found`, 409 `retake_in_progress`, 409 `not_retakeable`, PIYA-101 AC12 order) → 429 `queue_full` (count of the caller-agnostic `queued` jobs ≥ `queue_capacity`, `retry_after = 600`). Success 202, messages "Score submitted for processing" / "PDF rasterized and submitted for processing". Log `job_id`, `user_id`, `page_count`, timestamp (AC7). Retake of a failed job sets the old job's `superseded_by_job_id` in the creating transaction (AC12).

- [ ] **Step 1: Write failing tests** (`test_standardize.py`):
  - `test_exif_orientation_ignored`: JPEG 40×20 with Orientation=6 → output 40×20, no EXIF in output (`Image.open(...).getexif()` empty).
  - `test_downscale_keeps_aspect`: 6000×3000 PNG → 3000×1500 JPEG.
  - `test_sniff_rejects_heic_webp` (WebP bytes → None).
  - `test_pdf_rasterize_page_count_and_errors`: 2-page PDF → 2 PNGs; encrypted → 422 `corrupt_or_encrypted_pdf`; 21 pages → 400 `too_many_pages`; random bytes with `%PDF-` header → 422.
- [ ] **Step 2: Write failing tests** (`test_jobs_submit.py`):
  - `test_submit_images_202_shape`: 2 JPEG pages + `title=Bayan Ko` → 202; `data.jobId` matches `^job_\d+$` and is a `str`; `pageCount == 2`; `tempoBpm == 90`; keys `arranger`/`keySignature`/`timeSignature` absent; 2 `job_pages` rows with page_index 0,1 in submission order; storage holds 2 JPEG objects.
  - `test_submit_echoes_optional_metadata` (arranger, `tempoBpm=120`, `keySignature=Eb`, `timeSignature=6/8`).
  - `test_metadata_errors` (parametrized): missing title → `title_required`; 121 chars → `title_too_long`; `"a\nb"` → `title_invalid`; `tempoBpm=29` / `"٩٠"` → `invalid_tempo`; `keySignature=eb` → `invalid_key_signature`; `timeSignature=5/4`; `tempoBpm`+`fallbackTempoBpm` → `duplicate_field`; title sent twice → `duplicate_field`.
  - `test_fallback_tempo_settled`: `fallbackTempoBpm=100` → `tempoBpm == 100`, `jobs.tempo_source == "fallback"`; none → 90 / `default`.
  - `test_file_errors`: zero pages → `no_pages`; 21 pages → `too_many_pages`; a GIF page at index 1 → 415 with `pageIndex == 1`; truncated JPEG → 422 `corrupt_image`; PDF mixed into `pages` → 400 `mixed_input_types`.
  - `test_precedence_field_error_beats_415`: missing title + GIF → `title_required`.
  - `test_oversize_body_json_413`: settings `max_content_length = 1 MB`, 2 MB body → 413 JSON `request_too_large`.
  - `test_submit_pdf_202`: 2-page PDF + title → 202, `pageCount == 2`, pages stored as JPEG; non-PDF in `file` → 415; two `file` parts → `multiple_pdfs`.
  - `test_submit_rate_limit`: 10 successes then 11th → 429 `rate_limited`, counter shared across `/api/jobs` and `/api/jobs/pdf`.
  - `test_queue_full`: `queue_capacity = 1`, one queued job exists → 429 `queue_full` with `Retry-After`.
  - `test_no_partial_state`: storage `put` raising on page 2 → 500; no `jobs` rows; page 1 key deleted.
  - `test_retake_rules`: other user's job → 404 `job_not_found`; queued job → 409 `not_retakeable`; failed `incomplete_voice_sequence` job → 202 and old job superseded; second retake while first unfinished → 409 `retake_in_progress`.
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `PIYA-101: upload intake with PIYA-320 standardization, PIYA-310 PDF and PIYA-323 tempo`.

---

### Task 10: Job status and cancel (PIYA-102, PIYA-114)

**Implementer model:** haiku. **Files:** Modify `backend/routes_jobs.py`; Create `backend/access.py`, `backend/tests/test_jobs_status.py`.

**Interfaces:**
- Produces (PIYA-315 central scoping — every later route must use these): `access.owned_job(conn, job_id: int, *, for_update: bool = False) -> dict` (raises 404 `job_not_found`); `access.owned_score(conn, score_id: int, *, for_update: bool = False) -> dict` (raises 404 `score_not_found`). Both filter by `g.user.id` in the `WHERE` clause.

Behaviour: `GET /api/jobs/<ref>` — malformed ref → 404 `job_not_found`; read limit window `status_read` 120/user/min → 429 `rate_limited` (separate bucket from `submit`); 200 "Processing status retrieved" with `jobId`, `status`, `totalPages` (= page_count) and `currentPage` (omitted when NULL) while not terminal, `percentComplete`, `failureReason` (`null` unless failed) and `pageIndex` (failed only), `failedVoices`/`failedVoiceCauses` (`null` unless complete), `scoreId` (complete only — the app needs it), `title`, `tempoBpm`, and `arranger`/`keySignature`/`timeSignature` when present; `estimatedRemainingSeconds` omitted (no worker). Superseded job → still 200 here (410 applies to results only). `POST /api/jobs/<ref>/cancel` — body ignored (path is authoritative); terminal → 409 `job_terminal`; else status `cancelled`, page keys queued for deletion, log `jobId`/`userId`/timestamp/stage → 200 `{"jobId": ref, "status": "cancelled"}` "Processing cancelled".

- [ ] **Step 1: Write failing tests:** `test_status_queued_shape` (exact keys; `failureReason is None`; no `scoreId`), `test_status_complete_includes_score_and_voices` (job completed via direct SQL fixture), `test_status_other_user_404`, `test_status_bad_ref_404`, `test_status_read_limit_separate_from_submit` (121st read → 429 while submit still allowed), `test_cancel_queued`, `test_cancel_terminal_409`, `test_cancel_other_user_404`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `PIYA-102: job status and PIYA-114 cancel with central record scoping`.

---

### Task 11: Job completion (PIYA-321) + operator CLI

**Implementer model:** sonnet. **Files:** Create `backend/completion.py`, `backend/scripts/__init__.py`, `backend/scripts/jobs_cli.py`, `backend/tests/test_completion.py`.

**Interfaces:**
- Produces:
  - `completion.complete_job(conn, job_id: int, *, audio_keys: Mapping[str, str], timing_key: str, failed_voices: Sequence[str], failed_voice_causes: Mapping[str, str], review: Mapping[str, object], muted_measures: Sequence[Mapping[str, object]], thumbnail_key: str | None) -> int | None` — one transaction (PIYA-321 AC4): lock job `FOR UPDATE`; status `cancelled` → return None (caller deletes its uploaded keys); retake path per AC5 (lock old score `FOR UPDATE`; gone → job `cancelled`, return None; else update score fields, replace `audio_tracks`/`timing_metadata`, queue old keys + old job page keys for deletion, set old job `superseded_by_job_id`, old job `score_id = NULL`); normal path inserts `scores` copying `title, arranger, page_count, tempo_bpm, tempo_source, key_signature, time_signature`; sets job `complete`, `score_id`, `completed_at`, `failed_voices`, `failed_voice_causes`, `percent_complete = 100`. Returns score id.
  - `completion.fail_job(conn, job_id: int, reason: str, page_index: int | None) -> None`.
  - `completion.make_thumbnail(page_jpeg: bytes) -> bytes` (long side 400 px JPEG).
  - CLI `python -m backend.scripts.jobs_cli list-queued`; `fetch-pages <jobId> <out_dir>` (writes `page_000.jpg`…); `complete <jobId> --audio-dir DIR [--timing FILE] [--review FILE] [--failed tenor:unreadable ...]` (expects `soprano.mp3` etc.; uploads with `new_key`; thumbnail from page 0; calls `complete_job`); `fail <jobId> <reason> [--page N]`. Uses `DATABASE_URL` + storage settings from env. This is how an operator turns an uploaded score into audio today (run Stage 1–5 locally on fetched pages, then `complete`).

- [ ] **Step 1: Write failing tests:** `test_complete_creates_score_copying_metadata`; `test_complete_is_atomic` (force failure inserting `audio_tracks` → job still `queued`, no score); `test_complete_cancelled_job_returns_none`; `test_retake_completion_updates_same_score` (same `scoreId`, `last_accessed_at` kept, old audio keys queued, old job superseded); `test_retake_of_deleted_score_cancels`; `test_cli_complete_end_to_end` (MemoryStorage via env, tmp audio dir with 4 tiny files → score row + 4 tracks + thumbnail key).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `PIYA-321: atomic job completion and operator jobs CLI`.

---

### Task 12: Score endpoints — library, result, edit, delete (PIYA-308, 103-by-score, B5, 309)

**Implementer model:** sonnet. **Files:** Create `backend/routes_scores.py`, `backend/tests/test_scores.py`; Modify `backend/app.py`.

**Interfaces:**
- Consumes: `access.owned_score`, `storage.get_storage().signed_url`, `background.queue_deletion`, `validation` text cleaning from Task 9 (reuse the same title/arranger rules and codes).
- Produces: `score_entry(row: Mapping) -> dict` → `{"scoreId": int, "title": str}` + `lastAccessedAt`, `lastProcessedAt` (= `created_at`), `arranger`, `pageCount`, `thumbnailUrl` (signed) only when present.

Behaviour: **GET /api/scores** — `search` optional: blank = none, > 100 chars → 400 `search_too_long`, `ILIKE` on title and arranger with `%`/`_`/`\` escaped and bound; order `COALESCE(last_accessed_at, created_at) DESC`; `{"scores": [...]}`, message "Score library retrieved". **GET /api/scores/<int:id>/result** — 404 `score_not_found`; superseded handling not needed (score-keyed); 200 "Processed score result retrieved" with `jobId` (the completing job's ref), `scoreId`, `title`, `arranger?`, `tempoBpm`, `audioTracks` (lowercase voice → signed URL, failed voices absent), `scoreImages` (signed page URLs, page order), `scoreImageSizes` (`[{"width", "height"}]`, from `job_pages`), `timingMetadataUrl`, `review`, `mutedMeasures`, `failedVoices`, `failedVoiceCauses`; then `UPDATE scores SET last_accessed_at = now() WHERE id = %s AND user_id = %s` — failure logged, response still 200 (PIYA-308 AC8). **PATCH** per V2 B5 1–4 (`score_not_found`, `retake_in_progress`, title/arranger codes; `FOR UPDATE`; updates score and its job rows; response one `score_entry`, "Score updated"; does not touch `last_accessed_at`). **DELETE** per PIYA-309 AC1–AC6: `FOR UPDATE`; cancel unfinished retakes of its jobs; collect thumbnail/audio/timing/page keys → `queue_deletion`; delete the score's jobs and the score; 200 "Score deleted".

- [ ] **Step 1: Write failing tests:** `test_library_empty_list`; `test_library_entry_omits_absent_fields` (never-opened score has no `lastAccessedAt` key, has `lastProcessedAt`); `test_library_order_and_search` (search `"bay"` matches title "Bayan Ko" and arranger; `"%"` matches nothing literal-less; 101 chars → 400); `test_library_thumbnail_signed`; `test_result_shape_and_touch` (keys present, `audioTracks` lowercase, `last_accessed_at` set after call); `test_result_failed_voice_has_no_track`; `test_patch_title_and_clear_arranger`; `test_patch_errors` (`title_required`, `arranger_too_long`, other user → 404 `score_not_found`, unfinished retake → 409 `retake_in_progress`); `test_delete_removes_and_queues` (gone from library; all keys in `storage_deletions`; `run_deletions` empties storage); `test_delete_cancels_running_retake`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `PIYA-308: score library, results by score, V2 edit and PIYA-309 delete`.

---

### Task 13: Hardening — cross-user test, HTTPS enforcement, secrets check (PIYA-315 AC3/AC4, 317, 318)

**Implementer model:** haiku. **Files:** Create `backend/tests/test_cross_user.py`, `backend/tests/test_https_secrets.py`, `backend/scripts/check_secrets.py`; Modify `backend/app.py`, `docs/tickets/module3-backend.md` (PIYA-315 AC4: add "New endpoints must use `access.owned_*` and be added to `backend/tests/test_cross_user.py`" to the template note at the top).

Behaviour: when `require_https`, every request except `/healthz` whose scheme (after ProxyFix) is not `https` → 400 `https_required`, before auth; `create_app` with env=prod and `require_https=False` → `RuntimeError`. `check_secrets.py` exits 1 if `git ls-files` lists any `.env` file or a tracked file matches the patterns `AKIA`, `-----BEGIN`, `PIYA_RESET_CODE_HMAC_KEY=` with a value.

- [ ] **Step 1: Write failing tests:**
  - `test_every_scoped_endpoint_denies_other_user` — parametrized over a list of `(method, path_template, body)` covering `GET /api/jobs/{job}`, `POST /api/jobs/{job}/cancel`, retake via `POST /api/jobs` with `replacesJobId`, `GET /api/scores/{score}/result`, `PATCH /api/scores/{score}`, `DELETE /api/scores/{score}`; user B's token on user A's ids → 404 every time, A's resources unchanged. Plus `test_route_inventory_complete`: every rule in `app.url_map` with a `<` parameter appears in that list (fails when someone adds an unscoped route).
  - `test_http_rejected_when_https_required` (`X-Forwarded-Proto: http` → 400 `https_required`; `https` → passes), `test_prod_requires_https_flag`, `test_check_secrets_clean_repo` (runs the script → exit 0).
- [ ] **Step 2–4:** FAIL → implement → PASS. Run the whole suite: `pytest backend/tests -v` → all PASS.
- [ ] **Step 5: Commit** `PIYA-315: cross-user denial test, PIYA-317 HTTPS check, PIYA-318 secrets check`.

---

### Task 14: Deploy to Render + live contract smoke (NEEDS USER for accounts)

**Implementer model:** sonnet. **Files:** Create `backend/Dockerfile`, `render.yaml` (repo root, Render Blueprint: one free Docker web service, `dockerfilePath: backend/Dockerfile`, `healthCheckPath: /healthz`, every secret as `sync: false`), `backend/scripts/smoke.py`, `docs/backend/deploy.md`; Modify `docs/tickets/module3-backend.md` (an "Implemented contract (2026-11)" section: final paths incl. logout/account, `/api/scores/{id}/result` closing the PIYA-308 AC8 gap, `scoreId` on PIYA-102 complete, `invalid_current_password` on delete-account 403, PIYA-305 AC1/AC4 resolution, cancel response key `jobId`), `CLAUDE.md` (one short "Backend" pointer to `backend/README.md` and `docs/backend/deploy.md`).

**Interfaces:**
- Dockerfile (build context = repo root, copies only `backend/`; add a root `.dockerignore` excluding everything else): `python:3.12-slim`, non-root user, `pip install -r backend/requirements.txt`, `CMD python -m backend.migrate up && gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT:-10000} --timeout 120 "backend.app:create_app()"`; env `PIYA_RUN_BACKGROUND=1` (one worker ⇒ one background loop). 512 MB RAM: one gunicorn worker only.
- `smoke.py <base_url>`: runs signup → account → login → submit 1 generated JPEG → status → cancel → library → change password → logout (401 after) → delete account against a live URL, asserting the app's parse rules (types of `userId`/`jobId`/`scoreId`, `Z` timestamps, envelope keys). Prints PASS/FAIL per step; exit code 1 on any failure. Uses only stdlib `urllib` + `json`.

- [ ] **Step 1:** `docker build -f backend/Dockerfile -t piyanota-api .` then `docker run --rm -p 10000:10000 --env-file backend/.env piyanota-api` against the local test Postgres with `PIYA_STORAGE_BACKEND=memory`, `PIYA_MAIL_BACKEND=log`; `python -m backend.scripts.smoke http://localhost:10000` → all PASS.
- [ ] **Step 2: needs input — user creates accounts** (steps in `docs/backend/deploy.md`): Neon project (copy pooled `DATABASE_URL`), Backblaze B2 private bucket with SSE-B2 + application key limited to that bucket, Brevo account with a verified sender + API key, Render account connected to the GitHub repo (Blueprint from `render.yaml`), UptimeRobot free monitor pinging `/healthz` every 5 min. Secrets go into Render's environment settings, never into files. Pushing the branch to GitHub is needed for Render to build it — ask the user before pushing.
- [ ] **Step 3:** Render builds from the pushed branch; `python -m backend.scripts.smoke https://<service>.onrender.com` → all PASS. Then one real password-reset email to the user's inbox.
- [ ] **Step 4: Phone check with the real app** (user): `flutter build apk --release --dart-define=API_BASE_URL=https://<service>.onrender.com --dart-define=USE_FAKE_AUTH=false`; verify sign-up, login, reset code email, change password, capture upload (job shows "queued"), library after `jobs_cli complete` of that job, playback, edit, delete. Record results in the commit message / execution report.
- [ ] **Step 5: Commit** `PIYA-401: Render deploy, live contract smoke, implemented-contract notes`.

---

### Task 15: Whole-branch review

**Model:** opus (senior-reviewer + backend-lead agents, per CLAUDE.md "MUST BE USED before merge").

- [ ] **Step 1:** Dispatch `backend-lead` on the full diff `main..feature/module3-backend` (API contract vs app, security, schema).
- [ ] **Step 2:** Dispatch `senior-reviewer` on the same diff.
- [ ] **Step 3:** Fix findings (each fix → test → commit), log anything deferred in `docs/bug-tracker.md` (phase `dev-sprint`).
- [ ] **Step 4:** Report to the user; merge only on the user's explicit approval (memory: worktree-merge gating).

---

## Out of scope (named, not built)

- The conversion worker (Stages 1–5 on the server), `percentComplete`/`estimatedRemainingSeconds` progress, PIYA-111 failure/timeout handling, PIYA-115 estimates.
- PIYA-116 per-page resubmit (`POST /api/jobs/{jobId}/resubmit`) — only reachable after a page-specific pipeline failure, which cannot happen without the worker.
- Listing failed scans in PIYA-308 (PIYA-218 dependency), FCM push.
- App changes: wiring logout / account info / delete account (PIYA-217) is Module 2 work for frontend-lead; the endpoints exist after Task 7.
