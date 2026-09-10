# PIYA-300 — Database & Hosting Technology Selection

**Status:** Decided 2026-09-09 (originally due as the Sep 4 action item; carried into Sprint 6).
**Decides for:** `docs/tickets/module3-backend.md` PIYA-300, PIYA-311 (schema), PIYA-401
(provisioning), PIYA-407 (performance validation baseline).

## Decision

- **Database:** PostgreSQL on **Neon** (not Supabase). Neon's free-tier compute auto-suspends
  after inactivity but wakes automatically on the next query (~1s cold start); Supabase's free
  tier instead *pauses the whole project* after ~7 days idle and requires a manual dashboard
  restore, which is a real risk for this project's uneven activity between now and Oct. Verify
  current published free-tier storage/compute limits at signup — they change over time and
  aren't re-quoted here as fixed numbers.
- **Application hosting:** **DigitalOcean**, Basic Droplet, ~2 vCPU / 4GB RAM (pick the smallest
  tier that comfortably runs Flask + YOLOv8 + CRNN inference + FluidSynth without OOM — verify
  actual RAM headroom against Stage 2/3 memory use before committing to a specific tier size).
  Chosen over Linode/Hetzner for its documentation depth and setup tutorials, which matters for
  solo troubleshooting under deadline pressure.
- **GPU:** no standing GPU instance. GPU compute is rented on-demand from **RunPod** (prebuilt
  PyTorch pod templates, per-second billing, T4-class, ~$0.20–0.40/hr) *only* during the specific
  windows that need GPU-based timing numbers — PIYA-407 (performance validation), PIYA-409
  (dry-run buffer week), PIYA-411 (live usability evaluation) — and torn down immediately after.
  **Contingency:** if RunPod capacity/pricing is unfavorable at the exact time needed, fall back
  to Vast.ai (cheaper, more DIY/bidding-based marketplace). If neither has capacity, the
  CPU-only VPS measurement remains the reported PIYA-407 baseline regardless — GPU numbers are a
  bonus data point, not a requirement the schedule depends on.
- **Estimated total cost:** ~$50–90 across the active hosting window (~Oct 13 provisioning
  through ~Nov 21 defense prep, per `docs/sprint-plan.md`), covering ~6 weeks of VPS uptime plus
  ~30–40 hours of on-demand GPU rental. Treat this as an estimate to re-check once actual
  Droplet-tier and RunPod hourly pricing are confirmed at signup, not a firm quote.

## Action items (not yet done — this is a decision record, not a provisioned environment)

- [ ] Create the Neon project + Postgres instance — target before Sprint 10 (Oct 6–12, database
      finalization), so PIYA-311 migrations have somewhere to run against.
- [ ] Provision the DigitalOcean Droplet — target start of Sprint 11 (Oct 13–19, deployment),
      per PIYA-401.
- [ ] Create and verify a RunPod account (payment method, template access) *ahead of* the first
      window that needs it, rather than during PIYA-407 itself — account/payment verification
      delays are exactly the kind of last-minute friction a solo timeline can't absorb.
- [ ] Confirm Vast.ai as a working fallback account before relying on the contingency above.

## Rationale

### Cost
No budget figures exist anywhere in the SOW or sprint plan, and this is a solo student thesis
with no team/lab budget behind it. The above stack keeps total spend in the $50–90 range for the
whole remaining project by using free-tier managed Postgres, a cheap CPU-only VPS instead of a
continuously-billed GPU box, and renting GPU time only for the handful of days it's actually
needed for measurement — a standing GPU instance would run $150–400/mo alone, which isn't
justifiable against a solo thesis budget for the ~5 weeks it would otherwise sit idle.

### Thesis-scale suitability
The schema (PIYA-311) and record-level access control (PIYA-315) already scope every resource
(`scores`, `jobs`, `audio_tracks`) to a `user_id`, and PIYA-411/412 anticipate a 12+ respondent
pool with modest concurrent load, not production-scale traffic. `audio_tracks`/`timing_metadata`
store URLs to files in object storage, not the binary data itself, so the database only holds
small relational rows (users, scores, jobs, tokens) — well within any current free-tier managed
Postgres storage limit at this scale. A 2–4 vCPU box is enough for a handful of simultaneous
submissions during a group testing session.

### GPU availability
GPU is deliberately *not* assumed to be continuously available — it's rented on-demand only for
the windows where GPU-based timing numbers are actually collected (PIYA-407/409/411). This
directly satisfies PIYA-401 AC2's requirement to document a CPU-only fallback if a GPU-enabled
instance isn't feasible within budget: the CPU-only VPS is the steady-state deployment, and
CPU-only per-page timing is what's validated against the ≤2-min/page target (PIYA-407) as the
primary, always-true baseline. On-demand GPU rentals are used to additionally collect
GPU-accelerated timing numbers during the same windows, but the system's actual production
posture for the rest of the project is CPU-only.

## Implications for dependent tickets

- **PIYA-311 (schema/migration):** unblocked — proceed using PostgreSQL migration syntax
  (this decision satisfies AC2, made before PIYA-311 begins).
- **PIYA-401 (provisioning):** target the CPU-only VPS spec above as the documented fallback
  per PIYA-401 AC2; GPU rental is provisioned separately, on-demand, only when PIYA-407/409/411
  are actively running.
- **PIYA-407 (performance validation):** CPU-only timing on the VPS is the primary measurement
  used against the ≤2-min/page target; GPU-based numbers collected during rental windows are
  reported as a secondary data point, not a substitute baseline.
