# Backend deploy (Render + Neon) — PIYA-401

The API runs as one free Render Docker web service built from `render.yaml` (Blueprint) and
`backend/Dockerfile`. The Docker image was written by inspection and has not been built locally
(no Docker on the dev machine); the first build happens on Render.

## Initial deploy: memory storage + log mailer

No Backblaze B2 or Brevo accounts exist yet, so the Blueprint sets `PIYA_STORAGE_BACKEND=memory`
and `PIYA_MAIL_BACKEND=log`:

- **Password-reset codes appear in the Render logs** (Logs tab of the service), not in an inbox.
- **Memory storage loses uploaded pages, audio and thumbnails on every restart or redeploy**
  (and on free-tier spin-down). The database rows survive in Neon; the files do not.
- B2, Brevo and UptimeRobot are optional later steps (below).

## Production environment

The app runs with `PIYA_ENV=prod` and `PIYA_REQUIRE_HTTPS=true` (startup fails otherwise). Only
`/healthz` is exempt from the HTTPS check; Render's proxy sets `X-Forwarded-Proto`, which
ProxyFix trusts for `PIYA_TRUSTED_PROXY_COUNT` hops. In prod a missing required variable is a
startup error that names it.

| Variable | Where | Notes |
|---|---|---|
| `PIYA_ENV` | render.yaml value | `prod` |
| `PIYA_REQUIRE_HTTPS` | render.yaml value | `true` |
| `PIYA_STORAGE_BACKEND` | render.yaml value | `memory` now; `b2` later |
| `PIYA_MAIL_BACKEND` | render.yaml value | `log` now; `brevo` later |
| `PIYA_MAIL_FROM` | render.yaml value | required in prod; use the verified Brevo sender later |
| `PIYA_TRUSTED_PROXY_COUNT` | render.yaml value | `1` until the header check below |
| `DATABASE_URL` | dashboard (`sync: false`) | Neon **direct (unpooled)** connection string (host without `-pooler`), because migrations run DDL on it at every boot and the backend already uses direct connections. `config.py` reads `PIYA_DATABASE_URL`, falling back to `DATABASE_URL`; `python -m backend.migrate` reads `DATABASE_URL` only, so use that name for both |
| `PIYA_RESET_CODE_HMAC_KEY` | dashboard (`sync: false`) | long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PIYA_LOG_HASH_KEY` | dashboard (`sync: false`) | another long random string |
| `PIYA_B2_ENDPOINT`, `PIYA_B2_BUCKET`, `PIYA_B2_KEY_ID`, `PIYA_B2_APP_KEY` | dashboard | only with `b2` |
| `PIYA_BREVO_API_KEY` | dashboard | only with `brevo` |
| `PIYA_RUN_BACKGROUND` | Dockerfile | `1`; one gunicorn worker means one background loop |
| `PIYA_DEBUG_HEADERS` | dashboard, temporary | `1` only while doing the proxy check below |

Secrets go in the Render dashboard, never in files.

## Steps

1. Neon: create a project, copy the direct (unpooled) connection string (becomes `DATABASE_URL`).
2. Push the branch to GitHub (ask the owner first), then in Render: New > Blueprint > pick the
   repo and branch. Fill the `sync: false` values when prompted.
3. Render builds the image; the container runs `python -m backend.migrate up` and then gunicorn.
   `GET /healthz` must return 200.
4. Run the live contract smoke from any machine:
   `python -m backend.scripts.smoke https://<service>.onrender.com` — all steps must PASS. It
   needs no email (the password change flow is authenticated).
5. Phone check (owner): `flutter build apk --release --dart-define=API_BASE_URL=https://<service>.onrender.com --dart-define=USE_FAKE_AUTH=false`.
   The reset code is read from the Render logs while the log mailer is on.

## Proxy / client IP check (temporary)

Per-IP limits only work if `request.remote_addr` is the tester's real IP.

1. Set `PIYA_DEBUG_HEADERS=1` in the dashboard and redeploy. This enables `GET /api/_debug/headers`
   (404 when off). It is not exempt from the HTTPS check, so call it over https, e.g.
   `curl -H "X-Forwarded-For: 1.2.3.4" https://<service>.onrender.com/api/_debug/headers`.
2. Read `X-Forwarded-For`, `True-Client-IP`, `CF-Connecting-IP` and `remoteAddr` from a phone on
   mobile data and from a laptop. Expect `remoteAddr` to equal the real client IP with
   `PIYA_TRUSTED_PROXY_COUNT=1`. If `X-Forwarded-For` has more hops than that (Render sits behind
   Cloudflare), raise the count so `remoteAddr` is the real client, or switch to a trusted header.
3. Record the result here: `TODO — not measured yet`.
4. **Remove after use:** unset `PIYA_DEBUG_HEADERS`, then delete the `debug_headers` setting
   (`backend/config.py`), the endpoint in `backend/app.py` and its tests in
   `backend/tests/test_app_basics.py`.

## Optional later steps

- **Backblaze B2:** private bucket with SSE-B2, application key limited to that bucket; set
  `PIYA_STORAGE_BACKEND=b2` and the four `PIYA_B2_*` variables.
- **Brevo:** verified sender and API key; set `PIYA_MAIL_BACKEND=brevo`, `PIYA_BREVO_API_KEY`,
  `PIYA_MAIL_FROM`. Then send one real reset email to the owner's inbox.
- **UptimeRobot:** free HTTP monitor on `/healthz` every 5 minutes (keeps the free service awake).

## Verify at signup (free-tier limits change; check the current terms)

- Render free CPU share and spin-down behaviour.
- Neon compute-hour allowance (the background loop runs every 10 min; pool `min_size=0`).
- B2 Class B daily transaction cap (about 2,500/day free). Every presigned GET and audio range
  request counts; set caps and alerts in the B2 console.
- Brevo free-mail sender deliverability.

## Sleeping service

The free service sleeps when idle; the background loop (cleanup, every 10 min) does not run while it sleeps and resumes on the next request. The first request after sleep is slow (cold start).

## Operator duties

- The queue is global (`queue_capacity`, default 50). Until the pipeline runs server-side, an
  operator must complete (`python -m backend.scripts.jobs_cli`) or cancel queued jobs, or new
  submissions get 429 `queue_full`.
- A queued retake of a score blocks edits to that score until it is completed or cancelled.
