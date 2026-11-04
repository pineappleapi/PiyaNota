# Backend plan — V2 check and test findings (2026-11-05)

Branch: feature/module3-backend (HEAD 5ff8d17 pushed). Source of findings: the user's "VERSION 2 Frontend CHECKS" and "BACKEND TESTING" notes of 2026-11-05. Ledger: `.superpowers/sdd/2026-11-05-v2-checks/ledger.md`. Joint contract: `.superpowers/sdd/2026-11-05-v2-checks/joint-contract.md`.

## Rules (from CLAUDE.md and the user)
- State the planned change and a one-line risk before editing. Do not commit or push without the user's approval; never push or merge without asking. Module 3 changes need a `backend-lead` review before merge. Final merge proposal needs `senior-reviewer`.
- Tests: start local Postgres 55432 (check with pg_isready), then `CUDA_VISIBLE_DEVICES=-1 backend/.venv/Scripts/python -m pytest backend/tests -q -W error`.
- Never read or print `C:/Users/paul_/start-piyanota-worker.ps1`.
- Clear the session after every 3 completed tasks (see "Session protocol").

## Token-saving method
- Controller stays thin: it hands work to subagents as files (task brief, report path, diff package), never pastes reports.
- One subagent per task, with an explicit `model:` on every Agent call. Reviews are task-scoped, and one broad review runs at the end.
- Model per task weight: haiku for doc, wording and ledger edits and for scoped re-reviews of tiny diffs; sonnet for implementation and routine review; opus only for security-sensitive design (B1, B2) or when a fix loop reaches round 4. `backend-lead` (sonnet) reviews B1, B2, B3, B5. `ml-cv-lead` reviews B8 only.
- Fix rounds 1-3 resume the implementer with SendMessage; rounds 4-5 use a fresh implementer on a stronger model. Minor findings go to the ledger as deferred, not into the loop.

## Tasks

### B1 — Password-reset code verification step (JOINT J1) — opus design, sonnet implement
Finding: a wrong code still reaches the New Password screen and fails only at confirm. Cause: the API has only `/password-reset/request` and `/password-reset/confirm` (`backend/routes_auth.py:180`, `:246`), so the code is checked only when the new password is sent.
Change: add `POST /api/auth/password-reset/verify` taking `{email, code}`. It checks the code without consuming it, returns 200 on a match and the standard 400 `invalid_code` on a mismatch, and counts the failure against the same per-email attempt budget as `/confirm`. After the budget is spent it returns 429 with a Retry-After matching the app's wait ladder (see B2). `/confirm` keeps requiring the code, so verify cannot be skipped. Uniform responses for unknown emails (no account enumeration beyond what `/request` already allows; the app already shows "Email has not yet been registered", so keep that behavior unchanged).
Acceptance: wrong code returns 400 and does not advance; right code returns 200 and a following `/confirm` with the same code still succeeds; verify attempts and confirm attempts share one counter; tests for each.
Risk: the shared counter could lock out a valid user who mistypes; the test must cover the reset after a good code.

### B2 — Login lockout: 5 wrong passwords before a wait (JOINT J2) — opus design, sonnet implement
Finding: the user wants 5 wrong attempts before the wait starts (the app currently starts a 30 s wait after the first wrong password, then 1:00).
Change: confirm where the wait lives (`backend/throttle.py` for the server, client-side for the fake backend). Server: count consecutive failures per email; no wait for failures 1-4; from failure 5 return 429 with Retry-After 30 s, then 60 s, then keep doubling to a documented cap. A success resets the count. Wrong password in airplane mode never counts (client concern). Write the exact ladder into the joint contract so the app and the server agree.
Open question for the user (ask before implementing): after the 5th failure, is the ladder 0:30, 1:00, 2:00 ..., and does the 5-attempt allowance refill after a wait or only after a success?
Acceptance: 4 failures give 401 with no Retry-After; the 5th gives 429; success resets; a different email is independent; tests including time travel through the clock fake.

### B3 — Delete account end-to-end (JOINT J3) — sonnet
Finding: tests 21 and 22 failed only because the app has no UI. `DELETE /account` exists (`backend/routes_account.py:75`).
Change: verify against the real database that deletion removes the user, scores, jobs, job pages, media blobs and sessions, and that a later login returns the same error as an unknown account. Add the missing test if absent. Report whether stored blobs are removed (storage space matters: about 14.5 MB per score).
Acceptance: after DELETE, login fails, `/scores` returns 401 with the old token, no orphan rows or blobs remain.

### B4 — No score left behind after a failed upload (JOINT J6) — sonnet
Finding: creating a score and then failing the image upload leaves an empty score in the library.
Change: check whether the score row is created before the upload completes. Server side: create the score and its job in one transaction only after all pages are accepted, or mark scores with no pages as `draft` and exclude them from the library list; add a janitor that deletes drafts older than a documented age. Tell the frontend which behavior was chosen through the joint contract (the app also removes its own local card on failure, F-task).
Acceptance: an upload that fails halfway leaves no visible score and no orphan job row; test with a simulated failure.

### B5 — Finer progress (JOINT J5) — sonnet
Finding: the processing percentage should be more dynamic and accurate, for example advancing when a strip finishes.
Change: today the worker sets a stage (`set_stage`). Add a `progress` value (0-100 integer, monotonic) updated on the heartbeat path: a weighted stage table (preprocess, detect, transcribe per strip, reconstruct, synth per voice) and a within-stage fraction (page i of n, strip j of m). Expose it on the existing job status response as `progress` (additive field). Weights come from the measured smoke timing (Moonriver 104 s total: preprocessing is over half of Stage 1-2 time), so state the weights in a constant with a comment.
Acceptance: progress never decreases, reaches 100 only on completion, field is additive (old app ignores it), tests with a fake pipeline reporting callbacks.
Risk: touching `worker/pipeline.py` callbacks; keep the callback optional.

### B6 — Result payload for local saving (JOINT J4) — sonnet
Finding: converted audio and pages should be saved on the phone for offline use and faster playback.
Change: no new endpoint expected. Confirm `GET /api/scores/{id}/result` returns stable content identifiers: add `etag`/`sha256` and byte size per file (additive), make `/media` honor `If-None-Match` and long cache headers, and keep signed URLs refreshable (the app must be able to re-request `/result` for fresh URLs without re-converting). Document the file list: 4 MP3s, cleaned pages, timing JSON, thumbnail. Also decide whether to offer the MIDI per voice (the user wrote "midi and audio"): ask the user.
Acceptance: result lists size and hash for every file; conditional GET returns 304; tests.

### B7 — Deferred backend items from the merge review — sonnet, run in parallel with B1-B6 when files do not overlap
From the ledger and `review-final.md`: (a) `review-t1-2-4` deferred minors 1-7; (b) blob cap or retention policy (about 14.5 MB per score, Neon free tier holds about 30); (c) old stored review rows unfiltered on read; (d) the `review-final.md` Minor list; (e) Moonriver smoke rerun, expect 40 bars (needs a quiet CPU); (f) unseeded `finetune_train_loader` is out of scope here.
Acceptance: each item either fixed with a test or recorded in the ledger as deferred with a reason.

### B8 — Camera-PrIMuS regression for Stage 3/4 changes — sonnet runs, `ml-cv-lead` reviews
Merge precondition from the handoff (open item 2). Run the existing evaluation on CPU only, compare to the recorded baseline (clean 98.118% pitch accuracy, distorted 86.983%). Report numbers and whether they match. Do not treat any number from the dev GPU as verified (BUG-013).
Acceptance: numbers recorded in `docs/decisions/` with the command used; no drop beyond the agreed tolerance (ask the user for a tolerance if none is on record).

### B9 — Backend-side items to hand to the frontend plan — haiku (documentation only)
Write the joint contract file (J1-J6 request and response shapes, ladders, error codes) before B1 starts so the frontend can work in parallel. Update it as tasks finish.

## Order and parallelism
1. B9 first (contract; cheap, unblocks the frontend).
2. Batch 1 (parallel, disjoint files): B1 (routes_auth), B3 (routes_account, tests), B7 (misc).
3. Batch 2: B2 (throttle; touches routes_auth, so after B1), B4 (routes_scores/routes_jobs), B5 (worker).
4. Batch 3: B6, B8.
5. Final: backend-lead review of the whole set, one fix dispatch, then `senior-reviewer`, then ask the user about push and merge.
The frontend plan runs at the same time in its own worktree against the joint contract and the fake backend; integration tests against the real backend happen after B1, B2, B4, B5, B6 land.

## Session protocol (clear every 3 tasks)
- After each task: append one line to the ledger (task id, commit, tests, review verdict, deferred minors, rulings).
- After every 3 completed tasks: rewrite `.superpowers/sdd/2026-11-05-v2-checks/handoff-backend.md` (CURRENT state only), then tell the user to run /clear and paste the backend resume prompt from `resume-prompts.md`.
- Never keep state only in the conversation.
