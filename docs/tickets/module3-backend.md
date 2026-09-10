# Module 3: Backend Services (API & Database)

_Covers: Authentication & Account API tickets, Score & File Management API tickets, Database tickets, Security & Authorization tickets._

## API Tickets — Authentication & Account

### PIYA-300 — Database & Hosting Technology Selection
**Status:** Done — 2026-09-09. Decision recorded in `docs/decisions/piya-300-database-hosting.md`.
**Trigger:** Internal — executed as the Sep 4 action item, before Sprint 8 begins.
Records the decision on database technology (e.g., PostgreSQL/MySQL) and hosting provider, made before schema design (PIYA-311) or provisioning (PIYA-401) can proceed.

**Acceptance Criteria:**
1. A specific database technology and hosting provider are selected and documented, with rationale (cost, thesis-scale suitability, GPU availability if applicable) recorded in the repository.
2. Decision made before PIYA-311 (schema migration) begins, since migration syntax is technology-dependent.
3. Decision explicitly accounts for whether a GPU-enabled instance is realistically available, since this directly affects PIYA-407's performance validation baseline.

---

### PIYA-301 — Sign-Up API
**Method:** POST
Creates a new user account and returns a session token, used by Sign-Up UI (PIYA-203).

**Acceptance Criteria:**
1. Accepts `email`, `password`, `passwordConfirmation`; returns 400 if any field missing.
2. Returns 400 with specific error if password and passwordConfirmation don't match.
3. Returns 400 if password doesn't meet minimum strength policy (min. 8 characters, at least 1 letter and 1 number).
4. Returns 409 with error code `email_already_registered` if email already exists, without revealing other account details.
5. Stores password only as a salted hash (per PIYA-313); plaintext password never persisted or logged.
6. On success, creates user record with default role `choir_member`, issues session token, returns it in same response.
7. Returns 500 with generic error message (no stack trace/internal details) if account creation fails unexpectedly.
8. Endpoint responds within 2 seconds under normal load.

**Response Schema:**
```json
{
  "data": {
    "userId": 214,
    "email": "maria@example.com",
    "role": "choir_member",
    "sessionToken": "sess_a1b2c3d4",
    "expiresAt": "2026-09-11T09:15:00Z"
  },
  "success": true,
  "status": 201,
  "message": "Account created"
}
```

---

### PIYA-302 — Login API
**Method:** POST
Authenticates an existing user and issues a session token, used by Login UI (PIYA-202).

**Acceptance Criteria:**
1. Accepts `email` and `password`; returns 400 if either missing.
2. Uses parameterized queries for credential lookup — no string-concatenated SQL.
3. Returns 401 with generic message ("Incorrect email or password") for both non-existent email and wrong password — never distinguishes which one failed.
4. On success, issues a new session token (per PIYA-314 expiration policy), returns it along with `userId` and `role`.
5. Failed login attempts logged with email (hashed) and timestamp, without logging submitted password in any form.
6. Endpoint responds within 2 seconds under normal load.

**Response Schema:**
```json
{
  "data": {
    "userId": 214,
    "email": "maria@example.com",
    "role": "choir_member",
    "sessionToken": "sess_a1b2c3d4",
    "expiresAt": "2026-09-11T09:15:00Z"
  },
  "success": true,
  "status": 200,
  "message": "Login successful"
}
```

---

### PIYA-303 — Password Reset Request API
**Method:** POST
Initiates a password reset by emailing a reset link/code, used by Password Reset UI (PIYA-204).

**Acceptance Criteria:**
1. Accepts `email`; returns 400 if missing or malformed.
2. Returns the same 200 confirmation message regardless of whether email is registered, to avoid account enumeration.
3. Generates a single-use reset token with defined expiration (e.g., 30 minutes), stores only its hash, not the raw token, in the database.
4. Sends reset link/code via email only when the account exists; no email sent for unregistered addresses.
5. Any previously issued, unused reset token for the same account is invalidated when a new one is requested.
6. Endpoint responds within 3 seconds, matching the UI's stated confirmation-message timing (PIYA-204).

**Response Schema:**
```json
{
  "data": null,
  "success": true,
  "status": 200,
  "message": "If this email is registered, a reset link has been sent"
}
```

---

### PIYA-304 — Password Reset Confirm API
**Method:** POST
Validates a reset token and sets a new password, completing the flow started by PIYA-303.

**Acceptance Criteria:**
1. Accepts `resetToken`, `newPassword`, `newPasswordConfirmation`.
2. Returns 400 if new password fails the same strength policy enforced at Sign-Up (PIYA-301).
3. Returns 410 with error code `reset_token_expired_or_invalid` if token is expired, already used, or unrecognized.
4. On success, hashes and stores new password, invalidates reset token immediately (single use), invalidates all existing session tokens for that account.
5. Returns 200 with success confirmation on completion, matching UI's routing to Login (PIYA-204).

**Response Schema:**
```json
{
  "data": null,
  "success": true,
  "status": 200,
  "message": "Password reset successful"
}
```

---

### PIYA-305 — Logout / Session Invalidation API
**Method:** POST
Invalidates the current session token server-side, used by Settings UI (PIYA-212).

**Acceptance Criteria:**
1. Requires a valid session token; returns 401 if missing or already invalid.
2. Marks provided session token as invalid server-side (not just cleared client-side) within 1 second of request.
3. Any subsequent request using the invalidated token returns 401, confirming the token cannot be reused.
4. Returns 200 on success regardless of whether the token had already expired.

**Response Schema:**
```json
{ "data": null, "success": true, "status": 200, "message": "Logged out" }
```

---

### PIYA-306 — Get Account Info API
**Method:** GET
Returns the authenticated user's account details, used by Settings UI (PIYA-212).

**Acceptance Criteria:**
1. Requires a valid session token; returns 401 if missing, expired, or invalid.
2. Returns only `email`, `role`, `accountCreatedAt` — no password hash or internal fields — per "trimmed API responses" security requirement.
3. Returns data scoped strictly to the token's own account (record-level access control, per PIYA-315).
4. Responds within 500ms under normal load.

**Response Schema:**
```json
{
  "data": {
    "email": "maria@example.com",
    "role": "choir_member",
    "accountCreatedAt": "2026-08-01T10:00:00Z"
  },
  "success": true,
  "status": 200,
  "message": "Account info retrieved"
}
```

---

### PIYA-307 — Delete Account API
**Method:** DELETE
Permanently deletes a user's account and associated data, on user request.

**Acceptance Criteria:**
1. Requires a valid session token; returns 401 if missing or invalid.
2. Requires re-entry of the current password in the request body as a confirmation step; returns 403 if it doesn't match.
3. On success, triggers Account Deletion Data Purge Process (PIYA-319), invalidates all session tokens for the account immediately.
4. Returns 200 only after the account record is marked for deletion; response does not block on full asset purge completing (purge runs asynchronously per PIYA-319).
5. The email associated with a deleted account becomes available for re-registration only after the purge process fully completes.

**Response Schema:**
```json
{
  "data": null,
  "success": true,
  "status": 200,
  "message": "Account deletion initiated"
}
```

## API Tickets — Score & File Management

### PIYA-308 — Get User Score Library API
**Method:** GET
Returns the list of saved scores belonging to the authenticated user, used by Score Library UI (PIYA-205).

**Acceptance Criteria:**
1. Requires a valid session token; returns 401 if missing or invalid.
2. Returns only scores owned by the authenticated `userId` (record-level access control) — no cross-user data returned under any query.
3. Each score entry includes `scoreId`, `title`, `lastAccessedAt`/`lastProcessedAt`, thumbnail URL.
4. Supports an optional search query parameter filtering by title, case-insensitive, partial match.
5. Returns an empty array (not an error) when the user has zero saved scores.
6. Responds within 1 second for libraries up to 200 scores.

**Response Schema:**
```json
{
  "data": {
    "scores": [
      {
        "scoreId": 552,
        "title": "Bayan Ko",
        "lastAccessedAt": "2026-09-03T14:22:00Z",
        "thumbnailUrl": "https://cdn.piyanota.app/thumbs/552.png"
      }
    ]
  },
  "success": true,
  "status": 200,
  "message": "Score library retrieved"
}
```

---

### PIYA-309 — Delete Score API
**Method:** DELETE
Permanently removes a saved score and its associated audio/image assets from a user's library.

**Acceptance Criteria:**
1. Requires a valid session token; returns 401 if missing or invalid.
2. Returns 404 if `scoreId` doesn't exist or doesn't belong to caller's account (indistinguishable response for both cases, to avoid leaking existence of other users' scores).
3. Deletes the database record and queues associated audio files/score images for deletion from storage within 60 seconds.
4. Returns 200 immediately after the database record is removed; score no longer appears in subsequent PIYA-308 calls.
5. Deletion is irreversible and does not require a secondary confirmation at the API layer (confirmation handled client-side).

**Response Schema:**
```json
{ "data": null, "success": true, "status": 200, "message": "Score deleted" }
```

---

### PIYA-310 — PDF Upload & Rasterization API
**Method:** POST
**Context:** This is the upload-handling layer referenced in PIYA-101's context note — it allows PDF input to reach the image-only pipeline entry point.

**Acceptance Criteria:**
1. Accepts a single PDF file; returns 415 if content type is not `application/pdf`.
2. Returns 400 if PDF exceeds 20 pages (per FR-6), before rasterization begins.
3. Returns 422 with error code `corrupt_or_encrypted_pdf` if file cannot be parsed or is password-protected.
4. Rasterizes each page to the same image format/resolution standard used by camera and gallery inputs (per PIYA-320), preserving page order as `page_index`.
5. On successful rasterization, automatically forwards resulting image array to PIYA-101, returns the same `jobId`/`status` response shape as PIYA-101, so the client doesn't need a separate call.
6. Rasterization for a 20-page PDF completes in under 15 seconds on deployed hardware.

**Response Schema:**
```json
{
  "data": {
    "jobId": "job_8842",
    "userId": 214,
    "pageCount": 5,
    "status": "queued",
    "submittedAt": "2026-09-10T09:20:00Z"
  },
  "success": true,
  "status": 202,
  "message": "PDF rasterized and submitted for processing"
}
```

## Database Tickets

### PIYA-311 — Database Schema Design & Initial Migration
**Trigger:** Internal — executed once during Sprint 8 setup, before any endpoint depending on persistence goes live.

**Acceptance Criteria:**
1. Schema includes, at minimum: `users` (id, email [unique], password_hash, role, created_at), `scores` (id, user_id [FK], title, created_at, last_accessed_at), `jobs` (id, user_id [FK], score_id [FK, nullable until complete], status, page_count, created_at), `audio_tracks` (id, score_id [FK], voice, file_url), `timing_metadata` (id, score_id [FK], metadata_url), `password_reset_tokens` (id, user_id [FK], token_hash, expires_at, used_at).
2. Every foreign key relationship enforces referential integrity at the database level (not application-level only).
3. All tables include `created_at`; mutable tables include `updated_at`.
4. Migration scripts are version-numbered and re-runnable idempotently.
5. Schema documented in a single reference file (ERD or equivalent) committed to the repository.
6. Applying the full migration set to a fresh database completes without error, verified before Sprint 8 ends.

---

### PIYA-321 — Score Title Assignment
**Trigger:** Internal — invoked when a job transitions to `complete` (after PIYA-109/PIYA-103), creating the associated scores record. Satisfies FR-3, currently undefined in PIYA-101–103.

**Acceptance Criteria:**
1. On job completion, a `scores` record is created with a non-null `title`, defaulting to the original filename (PDF) or a timestamp-based label (camera/gallery capture), since no dedicated title-input UI is in scope.
2. The generated default title is what Get User Score Library (PIYA-308) returns and what its search parameter filters against.
3. Title generation never blocks or delays the `complete` status response to the client.

---

### PIYA-312 — Migration Script Versioning & Rollback
**Trigger:** Internal — invoked whenever a schema change is needed during Sprints 8–9, and during deployment.

**Acceptance Criteria:**
1. Each migration has a corresponding, tested rollback script.
2. Migrations applied in a fixed, tracked order (e.g., timestamped filenames); applied version recorded in a dedicated migrations-tracking table.
3. Running the migration tool reports which migrations are pending versus already applied.
4. A failed migration does not leave the schema in a partially applied state — either the full migration succeeds or the transaction is rolled back automatically.

## Security & Authorization Tickets (Internal)

### PIYA-313 — Password Hashing Implementation
**Trigger:** Internal — invoked by Sign-Up (PIYA-301) and Password Reset Confirm (PIYA-304) whenever a password is set.

**Acceptance Criteria:**
1. Passwords hashed using a salted, adaptive hashing algorithm (e.g., bcrypt or Argon2) with a per-user unique salt; no custom or reversible encryption for passwords.
2. Work factor/cost parameter is configurable without a code change, allowing it to be increased as hardware improves.
3. Plaintext passwords never written to application logs, error logs, or crash reports at any point in the request lifecycle.
4. Login (PIYA-302) verifies credentials via hash comparison only; stored hash never decrypted or reversed.

---

### PIYA-314 — Session Token Issuance & Expiration Policy
**Trigger:** Internal — invoked on every successful Sign-Up/Login, checked on every authenticated request.

**Acceptance Criteria:**
1. Tokens are cryptographically random, of sufficient length to resist brute-force guessing, unique per issuance.
2. Each token has a defined expiration (e.g., 30 days for mobile sessions); expired tokens rejected with 401 on any subsequent request.
3. Tokens transmitted only over HTTPS (per PIYA-317), never included in URL query strings or logged in plaintext.
4. All active tokens for an account invalidated on password reset (PIYA-304) and account deletion (PIYA-307/PIYA-319).
5. A revoked or expired token returns a consistent 401 response distinguishable from other auth failures only by status code, not by leaking why it was revoked.

---

### PIYA-315 — Record-Level Access Control Middleware
**Trigger:** Internal — invoked on every request to an authenticated endpoint accessing a user-scoped resource.

**Acceptance Criteria:**
1. Every data-access query scoped to a resource (score, job, account) is automatically filtered by the requesting user's `userId`, enforced centrally rather than reimplemented per endpoint.
2. Any attempt to access another user's resource by ID (score, job, account) returns 404, not 403, to avoid confirming resource existence.
3. Middleware coverage is verified with an automated test that attempts cross-user access against every user-scoped endpoint (Modules 1 and 3) and confirms it is denied.
4. New endpoints added after this ticket must route through the same middleware; documented as a required step in the API-ticket template.

---

### PIYA-316 — Role-Based Authorization (Choir Member / Choir Director)
**Trigger:** Internal — evaluated on account creation (PIYA-301) and on any endpoint checking role-specific permissions.

**Acceptance Criteria:**
1. Every account has exactly one role, `choir_member` or `choir_director`, defaulting to `choir_member` at Sign-Up.
2. Role is included in the session token's associated server-side record (not solely client-supplied) so it cannot be spoofed by modifying client requests.
3. No endpoint currently restricts functionality by role (per SOW scope — this ticket only establishes the field and enforcement pattern for future use).
4. An automated test confirms that submitting a role value in a request body without director-level authorization does not change an account's stored role.

---

### PIYA-317 — HTTPS Enforcement
**Trigger:** Internal — verified at server startup and enforced on every incoming request, from Sprint 8 onward, confirmed live during Sprint 9 deployment.

**Acceptance Criteria:**
1. Any plain HTTP request to the deployed server is redirected to HTTPS or rejected — no endpoint reachable over unencrypted HTTP in the deployed environment.
2. A valid TLS certificate is installed and auto-renewal (or a renewal reminder) is configured before Sprint 9's "confirm HTTPS live" deliverable.
3. Session tokens and passwords never accepted over a non-HTTPS connection, verified via a startup check that fails loudly if HTTPS is not properly configured.

---

### PIYA-318 — Data-at-Rest Protection & Secrets Management
**Trigger:** Internal — verified during Sprint 8 finish (data-at-rest policy) and Sprint 9 deployment.

**Acceptance Criteria:**
1. Database credentials, API keys, and any signing secrets stored in environment variables or a secrets manager — never hard-coded in the repository.
2. Repository includes a `.gitignore` (or equivalent) entry preventing secrets files from being committed, verified by a pre-deployment check.
3. Password hashes and reset-token hashes are the only credential-related fields persisted; no recoverable secret stored for either.
4. Storage-layer encryption (disk-level or database-native, depending on hosting provider) enabled for the production database before Sprint 9's deployment deliverable.

---

### PIYA-319 — Account Deletion Data Purge Process
**Trigger:** Internal — invoked immediately after Delete Account (PIYA-307) marks an account for deletion.

**Acceptance Criteria:**
1. Deletes or anonymizes the user record, all associated scores, jobs, audio track files, and score images within 24 hours of the deletion request.
2. Deletion cascades correctly across all foreign-key-linked tables defined in PIYA-311, leaving no orphaned records.
3. Purge process is logged (account ID reference only, not personal data) with a completion timestamp, viewable via the bug/ops tracker for verification.
4. If purge fails partway (e.g., storage deletion error), it retries automatically and does not leave the account in a state where it's neither active nor deleted.

---

### PIYA-320 — Input Standardization (Camera / Gallery / PDF)
**Trigger:** Internal — invoked by PIYA-101 and PIYA-310 immediately before job creation.

**Acceptance Criteria:**
1. All inputs normalized to the same file format (JPEG or PNG, matching PIYA-101's accepted types) and a defined maximum resolution/dimension, regardless of source.
2. Images exceeding defined maximum dimensions are downscaled (preserving aspect ratio) rather than rejected.
3. Standardization runs before `page_index` tagging, so downstream pipeline stages (Module 1) never need to branch logic based on input source.
4. A standardized test set — one sample each from camera capture, gallery selection, PDF rasterization — produces output images with matching format and comparable resolution, verified as part of Sprint 8's integration testing.