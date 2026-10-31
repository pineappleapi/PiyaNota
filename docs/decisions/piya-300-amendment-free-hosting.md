# PIYA-300 amendment — free hosting for evaluation testing

**Status:** Decided 2026-11-01 (user decision). Amends `piya-300-database-hosting.md`.

## Decision

| Concern | Was (2026-09-09) | Now |
|---|---|---|
| Database | PostgreSQL on Neon | **Unchanged.** Neon free Postgres. |
| API hosting | DigitalOcean Droplet | **Hugging Face Docker Space** (Flask API). |
| File storage | Droplet disk | **Backblaze B2** free tier, private bucket, signed URLs. |
| Reset-code email | Not decided | **Gmail SMTP** with an app password. |
| GPU | RunPod on demand (Vast.ai fallback) | **None.** See GPU below. |

## Why

The goal is evaluation testing with choir testers, not a public launch. Total cost must be $0.
The Droplet and RunPod plan (about $50-90) is not needed at this scale. Neon stays because it is
already free, and its schema work (PIYA-311) does not change.

## Free-tier limits to verify at signup

Limits change. Check each page on the day of signup.

- **Hugging Face Space:** about 2 vCPU / 16 GB RAM. It sleeps after about 48 h idle and wakes on
  the next request. The Space must be public on the free tier, so the uploaded `backend/` source
  is public. Keep secrets in Space secrets, never in the repo.
- **Backblaze B2:** about 10 GB free. The bucket must be private. Files are served by signed URL
  only (PIYA-308 AC9).
- **Gmail SMTP:** about 500 mails/day. Needs 2-step verification and an app password.
- **Neon:** compute auto-suspends and wakes in about 1 s. Check the storage cap.

## PIYA-317 / PIYA-318 impact

- Transport security: HF terminates TLS and renews certificates automatically. The app talks
  HTTPS to the Space only.
- At rest: Neon encrypts data at rest. Enable **SSE-B2** on the B2 bucket.
- Public source: the API code is visible. Nothing secret may live in it.

## GPU

No GPU. The conversion worker is skipped for now. Two later options:

1. Run conversion on the HF CPU (slow, acceptable for a few testers).
2. The operator runs Stages 1-5 locally with the operator CLI (plan Task 11) and uploads the
   results to B2 and the database.

Until one is built, jobs are accepted and stored but not converted automatically.

## Action items

- [ ] Create a Hugging Face account and a Docker Space.
- [ ] Create a Neon project (free) and copy the connection string into Space secrets.
- [ ] Create a Backblaze B2 account, a private bucket, enable SSE-B2, and make an application key.
- [ ] Enable 2-step verification on the sending Gmail account and create an app password.
- [ ] Record all secrets in Space secrets. None go in git.
