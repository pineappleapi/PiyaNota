# PIYA-300 amendment — free hosting for evaluation testing

**Status:** Decided 2026-11-01 (user decision, revised the same day). Amends `piya-300-database-hosting.md`.

## Decision

| Concern | Was (2026-09-09) | Now |
|---|---|---|
| Database | PostgreSQL on Neon | **Unchanged.** Neon free Postgres. |
| API hosting | DigitalOcean Droplet | **Render free web service** (Docker), kept awake by an UptimeRobot 5-minute ping. |
| File storage | Droplet disk | **Backblaze B2** free tier, private bucket, signed URLs. |
| Reset-code email | Not decided | **Brevo HTTPS API** (port 443), one verified sender, no domain needed. |
| GPU | RunPod on demand (Vast.ai fallback) | **None.** See GPU below. |
| Conversion worker (later) | On the VPS or rented GPU | **Hugging Face Space**, talking to the API and B2 over HTTPS only. |

## Why

The goal is evaluation testing with choir testers, not a public launch. The new stack costs
$0 and needs no card. The old estimate of about $50-90 in the original decision no longer applies.
Neon stays because it is already free, and the PIYA-311 schema does not change.

## Why not Hugging Face for the API

HF Spaces allow outbound traffic only on ports 80, 443 and 8080 (HF forum, staff statements).
An API on HF could not reach Neon (port 5432) or an SMTP server (port 587). Render has no such
limit. A worker on HF is fine because it only needs HTTPS: it calls the API and B2 over 443.

## Free-tier limits to verify at signup

Limits change. Check each page on the day of signup.

- **Render free web service:** 512 MB RAM, 750 instance-hours/month, sleeps after 15 minutes idle
  and takes about 1 minute to wake. An UptimeRobot ping every 5 minutes keeps it awake, so the
  app's 15 s request timeout is not hit by a cold start. The disk is ephemeral, which is why all
  files (page images, audio, timing, thumbnails) live in B2, never on the service.
- **Backblaze B2:** about 10 GB free. The bucket must be private. Files are served by signed URL
  only (PIYA-308 AC9).
- **Brevo:** 300 mails/day on the free plan. One verified sender address. Sent through the HTTPS API.
- **Neon:** compute auto-suspends and wakes in about 1 s. Check the storage cap and compute hours.
- **UptimeRobot:** free plan allows a 5-minute interval. Confirm.

## PIYA-317 / PIYA-318 impact

- Transport security: Render terminates TLS with auto-renewed certificates and redirects HTTP to
  HTTPS. The app talks HTTPS only.
- At rest: Neon encrypts data at rest. Enable **SSE-B2** on the B2 bucket.
- Secrets live in Render environment variables, never in git.

## PIYA-401 / PIYA-407 impact

- PIYA-401 (provisioning): there is no Droplet to provision. Create the Render service instead.
- PIYA-407 (performance validation): timing is measured where the conversion worker runs, not on
  the API host.

## GPU

No GPU. The conversion worker is skipped for now. Two later options:

1. Run conversion on a Hugging Face Space CPU (slow, acceptable for a few testers).
2. The operator runs Stages 1-5 locally with the operator CLI (plan Task 11) and uploads the
   results to B2 and the database.

Until one is built, jobs are accepted and stored but not converted automatically.

## Action items

- [ ] Create a Render account and a Docker web service for the API.
- [ ] Create an UptimeRobot monitor on the API health URL, 5-minute interval.
- [ ] Create a Neon project (free) and put the connection string in Render environment variables.
- [ ] Create a Backblaze B2 account, a private bucket, enable SSE-B2, and make an application key.
- [ ] Create a Brevo account, verify one sender address, and make an API key.
- [ ] Create a Hugging Face account when the worker is built (not needed yet).
