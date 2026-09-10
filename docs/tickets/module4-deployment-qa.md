# Module 4: Deployment & Quality Assurance

_Covers: Deployment tickets and QA/Testing tickets._

## Deployment Tickets

### PIYA-401 — Hosting Provisioning & Server Setup
**Trigger:** Internal — executed at the start of Sprint 9 (Oct 13–19), per sprint table's deployment deliverable.
Provisions the production server environment that will run the Flask backend and ML inference pipeline.

**Acceptance Criteria:**
1. A production hosting instance is provisioned with a documented specification (CPU/RAM, and GPU if secured) matching or exceeding requirements validated during Sprint 5–8 development/testing.
2. If a GPU-enabled instance is not feasible within budget, the CPU-only fallback is explicitly documented, and the ≤2-min/page target (PIYA-407) is validated against that fallback specifically — not assumed from GPU-based dev benchmarks.
3. Environment & Dependency Pinning (PIYA-112) is verified against the provisioned instance before any traffic is routed to it.
4. The provisioned server passes a smoke test (server starts, models load per PIYA-110, health-check endpoint returns 200) before proceeding to database migration (PIYA-402).
5. Provisioning steps documented in a runbook sufficient for a second person to reproduce the setup if the instance needs to be rebuilt.

---

### PIYA-402 — Production Database Migration Execution
**Trigger:** Internal — executed during Sprint 9, immediately after server provisioning (PIYA-401), before HTTPS confirmation (PIYA-403).
Applies the schema defined in PIYA-311/312 to the live production database.

**Acceptance Criteria:**
1. All migrations applied in order to the production database with zero manual/ad-hoc schema edits outside the migration scripts.
2. Migrations-tracking table (per PIYA-312) confirms every migration as applied, with no pending or partially-applied entries.
3. A rollback is executed against a staging copy of the production database as a dry run before applying to production, confirming rollback scripts work as expected.
4. Post-migration, a verification query confirms all tables and foreign key constraints from PIYA-311 exist and match the documented schema exactly.

---

### PIYA-403 — HTTPS Live Confirmation
**Trigger:** Internal — executed during Sprint 9, after server provisioning, as the sprint table's explicit "confirm HTTPS live" deliverable.
Confirms HTTPS enforcement (defined in PIYA-317) is correctly active on the production deployment, not just dev/staging.

**Acceptance Criteria:**
1. An external request to the production domain over plain HTTP is confirmed to redirect to HTTPS or be rejected outright.
2. Production TLS certificate verified as valid (not self-signed/expired) using an external check, expiration date logged with a renewal reminder set.
3. A test login and sign-up request against the production URL are confirmed to only succeed over HTTPS, mirroring PIYA-317's acceptance criteria but validated on the live deployment specifically.

---

### PIYA-404 — Backup & Data-Loss Handling
**Trigger:** Internal — configured during Sprint 9, verified before the Oct 20–25 dry-run buffer week begins.
Establishes automated backups for the production database and file storage, protecting collected evaluation data ahead of live testing.

**Acceptance Criteria:**
1. Automated database backups run on a defined schedule (e.g., daily) with a defined retention period, confirmed via at least one successful automated backup before dry-run week.
2. A backup restoration is tested at least once against a non-production instance, confirming the backup is actually usable (not just created).
3. Audio track and score image files in storage are covered by the hosting provider's redundancy/backup mechanism, or an equivalent explicit backup process if not natively provided.
4. A documented recovery procedure exists for the specific failure scenario of data loss during the Oct 26–30 live testing window, given there is no slack time before defense to re-collect respondent data.

## QA & Testing Tickets

### PIYA-405 — End-to-End Integration Testing
**Trigger:** Internal — performed continuously through Sprint 8 finish (Oct 6–12) as each feature is connected, per sprint table's "incremental, not saved for the end" QA note.
Validates that Modules 1–3 function correctly together across the full capture → process → playback flow.

**Acceptance Criteria:**
1. Each of the three input paths (camera, gallery, PDF) is tested end-to-end at least once: capture/select → submit (PIYA-101/310) → poll status (PIYA-102) → retrieve result (PIYA-103) → playback (PIYA-208).
2. Authentication is tested as part of the flow, not in isolation: a logged-out user cannot reach Capture, Library, or Playback screens.
3. Each UI screen from Module 2 is confirmed to call its corresponding Module 1/3 API correctly, with request/response shapes matching the documented schemas.
4. Integration defects found are logged in the bug tracker (PIYA-410) with the specific screen, endpoint, and reproduction steps — not just a general description.
5. No integration test is deferred past Sprint 8; any deferred item is explicitly flagged as a risk to the Oct 19 deadline.

---

### PIYA-406 — Full System Regression Test
**Trigger:** Internal — performed once the system is deployed to production (after PIYA-401–403), as the final gate before the Oct 19 deadline.
Validates the complete built system — all input types, all screens, edge cases — as the Sprint 9 deliverable confirming readiness for the dry-run buffer week.

**Acceptance Criteria:**
1. All input types (camera, gallery, PDF) and all Module 2 screens are re-tested against the production deployment, not just staging/dev.
2. Edge cases explicitly tested and logged: corrupted/unreadable images, a score with zero detected staff regions (PIYA-105 `no_staff_detected` path), a score with an unsupported 2-staff layout (PIYA-105 `unsupported_staff_layout` path), an incomplete voice sequence (PIYA-108 failure path), a 20-page PDF at the upload limit, and a mid-submission network loss.
3. Each edge case's actual system behavior compared against its documented failure-handling acceptance criteria, and any mismatch logged as a bug.
4. Regression test explicitly confirms the Oct 19 "system fully built and deployed" deliverable is met; any unresolved failing case is flagged before the dry-run buffer week begins, since PIYA-409 protects that week from new-feature work, not from fixing carried-over defects.

---

### PIYA-407 — Performance Validation (≤2 min/page)
**Trigger:** Internal — performed during Sprint 9 regression testing (PIYA-406) and re-confirmed during Oct 20–25 dry-run buffer week.
Confirms the ≤2-min/page processing target holds under real deployed conditions, including concurrent load — the system's primary named risk (server-side processing capacity).

**Acceptance Criteria:**
1. Single-job processing time per page measured on the production instance (not dev/local hardware) across at least 5 distinct scores; average and worst-case times both logged.
2. Concurrent-load testing simulates at least the expected peak respondent load for the Oct 26–30 window (multiple simultaneous submissions), re-measures per-page processing time under that load.
3. If concurrent-load processing time exceeds 2 min/page, this is logged as a specific, named finding tied to the primary project risk — not silently absorbed or hidden from the Chapter IV risk narrative.
4. Results recorded in a form directly usable for the thesis evaluation section (mean, worst-case, concurrent-load processing time in minutes/page).

---

### PIYA-408 — Device Compatibility Testing
**Trigger:** Internal — performed during Sprint 9 (Oct 13–19), per sprint table's device compatibility deliverable.
Confirms the Android client functions correctly across the range of devices respondents are likely to use.

**Acceptance Criteria:**
1. App tested on at least 3 distinct Android OS versions and at least 2 distinct screen sizes/aspect ratios, chosen to reasonably represent the DLSU-D Chorale and Lasallian Chorus respondent pool.
2. Camera capture, gallery selection, and PDF upload (PIYA-206) each confirmed functional on every tested device/OS combination.
3. Layout and playback controls (PIYA-208–211) visually confirmed to render without clipping or overlap on the smallest and largest tested screen sizes.
4. Any device-specific defect logged in the bug tracker (PIYA-410) with the exact device model and OS version, triaged for fix priority before Oct 19 versus acceptable-to-defer to the dry-run week.

---

### PIYA-409 — Dry-Run Buffer Week Protocol
**Trigger:** Internal — executed Oct 20–25, immediately after the Sprint 9 deployment deliverable is met, before live respondent testing begins Oct 26.
Defines the structured activities for the protected stability week, ensuring it functions as real de-risking rather than unstructured slack time.

**Acceptance Criteria:**
1. No new features introduced during this week; any proposed work item is checked against the Module 1–4 ticket set and rejected if it is not a fix to an existing, already-scoped item.
2. At least one full simulated concurrent-submission test is run, using volunteer (non-respondent) users submitting real scores back-to-back, to re-validate PIYA-407 under conditions closer to actual live testing.
3. Every bug found during the week is triaged in the bug tracker (PIYA-410) as either fixed within the week or explicitly accepted as a known limitation before Oct 26 — no bug remains untriaged going into live testing.
4. An explicit go/no-go decision for the Oct 26 live testing window is documented at the end of the week, based on whether the ≤2 min/page target and critical-path flows held under simulated conditions.

---

### PIYA-410 — Bug Tracking System Setup & Triage Process
**Status:** Done — 2026-09-09. Tracker set up at `docs/bug-tracker.md`.
**Trigger:** Internal — set up as the Sep 4 action item, used continuously through Nov 9.
Establishes a centralized method for logging and triaging defects, referenced by nearly every other QA ticket in this module.

**Acceptance Criteria:**
1. Every logged bug captures, at minimum: description, reproduction steps, severity, the specific ticket/module it relates to (e.g., PIYA-105), status (open/in-progress/fixed/deferred/won't-fix).
2. A severity/priority scheme is defined (e.g., blocker/major/minor) and applied consistently, so bugs found during live testing (PIYA-411) can be triaged quickly without inventing criteria mid-session.
3. Tracker is accessible and usable by a single researcher without requiring paid/team-tier tooling, given this is a solo thesis project.
4. Bugs found during dry-run week (PIYA-409) and live testing (PIYA-411/412) explicitly tagged as such, distinct from bugs found during earlier development sprints, to support the thesis's QA narrative and evidence trail.

---

### PIYA-411 — Live Usability Evaluation Session Execution
**Trigger:** Internal — executed Oct 26–30, contingent on a "go" decision from the Dry-Run Buffer Week Protocol (PIYA-409).
Defines how the primary testing window is run with real respondents to collect SER, pitch accuracy, processing time, and SUS data.

**Acceptance Criteria:**
1. Each session collects, per respondent: SUS questionnaire responses, and enough score-processing instances to contribute measurable SER, pitch inference accuracy, and processing-time data points against the Chapter III targets.
2. Respondents drawn from both a trained group (e.g., experienced Chorale members) and an untrained group, since SUS ≥ 70 must hold for both per the success criteria.
3. Any crash, unexpected error, or confusing-flow observation during a live session logged in the bug tracker (PIYA-410) in real time or immediately after the session, not reconstructed from memory later.
4. Minimum respondent count math tracked live against the 12-respondent target; if Oct 26–30 does not reach 12+, this triggers PIYA-412 rather than being treated as sufficient on its own.
5. Raw collected data (SUS scores, SER/pitch/timing measurements) backed up (per PIYA-404) immediately after each session, given there is no slack time before defense to re-collect lost data.

---

### PIYA-412 — Backup Respondent Session (Contingency)
**Trigger:** Internal — conditionally executed only if PIYA-411's respondent-count or trained/untrained-coverage criteria were not met.
Defines the contingency session (Nov 3–9) used only if the Oct 26–30 window did not reach the minimum 12 respondents or did not adequately cover both trained and untrained groups.

**Acceptance Criteria:**
1. This session is explicitly skipped (not run) if PIYA-411 already satisfied the 12-respondent minimum with both trained and untrained groups represented — it is a contingency, not a default second round.
2. If executed, follows the identical data-collection and logging protocol as PIYA-411, so results are directly combinable with the Oct 26–30 dataset.
3. Backup respondents specifically fill whichever gap caused the contingency to trigger, rather than arbitrary additional participants.
4. Completion of this session (or the decision that it wasn't needed) confirmed no later than Nov 9, preserving the Nov 10–16 Results Analysis window.

---

### PIYA-413 — Evaluation Results Compilation & Threshold Cross-Check
**Trigger:** Internal — executed Nov 10–16 (Results Analysis week), after live testing data collection is complete.
Compiles all collected data from PIYA-411/412 into final, defensible results checked against the Chapter III evaluation targets.

**Acceptance Criteria:**
1. Final SER, pitch inference accuracy, processing time, and SUS results each computed as a single defensible figure (e.g., mean with sample size) and explicitly compared against their respective Chapter III thresholds (≤15%, ≥85%, ≤2 min/page, ≥70).
2. SUS results reported separately for trained and untrained groups, not only as a combined figure, since the ≥70 target applies to both.
3. Any target not met is flagged explicitly, with the underlying data retained (not discarded) so it can be honestly discussed in Chapter V rather than omitted.
4. Respondent count confirmed and reported as meeting or falling short of the 12-respondent minimum, with a clear accounting of how many came from the primary (PIYA-411) versus backup (PIYA-412) window.
5. Compiled results in a format directly usable for Chapter IV/V drafting and defense slides (Nov 17–21), avoiding a re-compilation step during defense prep.