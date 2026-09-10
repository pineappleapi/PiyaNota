# PiyaNota — Sprint Plan

_Routing note: full ticket acceptance criteria live in /docs/tickets/module{1-4}-*.md. This file tracks timeline, focus, and sprint-to-ticket mapping only._

## Timeline Overview

| Week | Dates | Sprint | Focus | Deliverable |
|---|---|---|---|---|
| 1 | Feb 3–21 | Sprint 1 | Planning & Requirements | Requirements doc, 10-score corpus, Ch.1–2 drafts |
| 2 | Feb 24–Mar 14 | Sprint 2 | Architecture & Design | Architecture diagram, API endpoints defined |
| 3 | Mar 17–Apr 4 | Sprint 3 | Preprocessing Pipeline | Preprocessed images pass quality inspection |
| 4 | Apr 7–25 | Sprint 4 | Staff Region Detection | mAP50 ≥ 85% on Filipino SATB test set |
| 5 | Apr 28–May 16 | Sprint 5 | Proposal Defense Prep | Ch.1–3 finalized, defense deck ready |
| — | May 18 | **PROPOSAL DEFENSE** | — | — |
| — | May 19–Aug 3 | Hiatus | Project paused | — |
| — | Sep 4 | Action Item | Lock testing dates, DB/hosting decision, bug tracker setup | Confirmed schedule, tech stack, bug tracker |
| 6 | Sep 8–14 | Sprint 6 | Transcription & Pitch Finalization | Transcription model finalized, model loads once at startup, timeout handling in place |
| 7 | Sep 15–21 | Sprint 7 | Audio Synthesis & Mobile UI Kickoff | Working audio synthesis, UI screens begin (incl. Login/Sign-Up) |
| 8 | Sep 22–28 | Sprint 8 | Mobile UI Build-Out | Full UI built (not yet backend-connected) |
| 9 | Sep 29–Oct 5 | Sprint 9 | API & Authentication | Working auth flow + core endpoints, secured against SQLi/cross-user access |
| 10 | Oct 6–12 | Sprint 10 | Integration & Database Finalization | Full end-to-end flow: capture → process → playback working |
| 11 | Oct 13–19 | Sprint 11 | Deployment | System fully built and deployed — **Oct 19 deadline** |
| 12 | Oct 20–25 | Sprint 12 | Dry-Run & Stability Testing | Confidence system holds up for real respondents |
| 13 | Oct 26–30 | Sprint 13 | Live Usability Evaluation | First batch of evaluation data collected |
| 14 | Nov 3–9 | Sprint 14 | Backup Usability Evaluation | Complete evaluation dataset (12+ respondents) |
| 15 | Nov 10–16 | Sprint 15 | Results Analysis | Finalized, defensible evaluation results |
| 16 | Nov 17–21 | Sprint 16 | Final Defense Preparation | Defense-ready materials |
| — | Nov 22–28 | **FINAL DEFENSE** | — | — |

## Sprint Details

### Sprint 1 (Feb 3–21) — Planning & Requirements
- Define FR/NFR
- Identify Filipino SATB score corpus
- Establish evaluation metrics (SER, mAP, SUS)
- Finalize system scope and exclusions
- Write Chapter 1 (Introduction) & Chapter 2 (RRL)
- **QA**: Review requirements doc against SOW; spot-check corpus annotations

### Sprint 2 (Feb 24–Mar 14) — Architecture & Design
- Design two-stage pipeline architecture (YOLOv8 + CRNN-CTC)
- Design Android mobile client and Flask server API
- Define preprocessing pipeline parameters
- Design MIDI synthesis mapping
- **QA**: Architecture walkthrough against FR/NFR checklist

### Sprint 3 (Mar 17–Apr 4) — Preprocessing Pipeline
- Implement grayscale conversion, adaptive thresholding, noise filtering, skew correction (PIYA-104)
- Validate image quality on mobile-captured Filipino choral scores
- **QA**: Visual quality inspection; staff-line legibility check

### Sprint 4 (Apr 7–25) — Staff Region Detection
- Base-train YOLOv8 on DeepScoresV2 (PIYA-105)
- Fine-tune on annotated Filipino SATB score images
- Evaluate mAP50 / mAP50-95 on test set
- **QA**: Evaluate detection accuracy on held-out test set

### Sprint 5 (Apr 28–May 16) — Proposal Defense Prep
- Finish Chapter 3 (Methodology)
- Consolidate Chapters 1–3 into proposal manuscript
- Build proposal defense deck, rehearse
- **QA**: Adviser/panel review, peer slide walkthrough

### Sep 4 Action Item
1. Contact DLSU-D Chorale and Lasallian Chorus to lock Oct 26–30 availability + early-Nov backup date
2. Decide database technology/hosting provider (PIYA-300)
3. Set up bug-tracking method (PIYA-410)

### Sprint 6 (Sep 8–14) — Transcription & Pitch Finalization
- Finalize Symbol Transcription + Pitch Inference refinement (PIYA-106, PIYA-107)
- Model loading optimization (PIYA-110)
- Pipeline failure/timeout handling (PIYA-111)
- Environment/dependency pinning (PIYA-112)
- **QA**: Unit testing on transcription output vs. ground-truth samples

### Sprint 7 (Sep 15–21) — Audio Synthesis & Mobile UI Kickoff
- SATB reconstruction (PIYA-108), MIDI/audio synthesis (PIYA-109)
- Begin mobile UI in parallel: Onboarding, Login/Sign-Up, Library, Capture (PIYA-201–206)
- **QA**: Test each synthesized voice track for correct playback as built

### Sprint 8 (Sep 22–28) — Mobile UI Build-Out
- Mobile UI: Processing, Playback, Voice Mixer, Export (PIYA-207–211)
- Permissions handling, error/offline states (PIYA-213), Settings (PIYA-212)
- **QA**: Manual UI walkthrough per screen against state diagram/use case flows

### Sprint 9 (Sep 29–Oct 5) — API & Authentication
- API endpoints + auth, sign-up/login (PIYA-301, PIYA-302)
- HTTPS setup (PIYA-317), password hashing (PIYA-313), role permissions (PIYA-316)
- Input validation, password reset flow (PIYA-303, PIYA-304)
- Session token security (PIYA-314), parameterized queries, record-level access control (PIYA-315), secrets management (PIYA-318)
- **QA**: Test each endpoint individually as built (auth flow, token issuance, error handling, password reset, access control)

### Sprint 10 (Oct 6–12) — Integration & Database Finalization
- PDF upload + rasterization (PIYA-310)
- Connect mobile app to all endpoints (PIYA-214–217)
- Finalize DB schema (PIYA-311, PIYA-321), migration scripts (PIYA-312)
- Data-at-rest policy (PIYA-318), account deletion policy (PIYA-307, PIYA-319)
- **QA**: Incremental integration testing per feature as connected (PIYA-405) — not saved for the end

### Sprint 11 (Oct 13–19) — Deployment
- Deploy to hosting, GPU instance if feasible (PIYA-401)
- Run DB migrations (PIYA-402), confirm HTTPS live (PIYA-403)
- Backup/data-loss handling + in-progress job recovery on restart (PIYA-113, PIYA-404)
- Device compatibility testing (PIYA-408)
- **QA**: Full system regression test — all input types, all screens, edge cases (PIYA-406)

### Sprint 12 (Oct 20–25) — Dry-Run & Stability Testing
- **No new features** — protected stability week (PIYA-409)
- Simulate concurrent submissions, process real scores back-to-back
- Fix critical bugs, unhappy-path walkthrough
- **QA**: Dry-run testing under simulated conditions, confirming ≤2 min/page holds (PIYA-407)

### Sprint 13 (Oct 26–30) — Live Usability Evaluation
- Live testing/evaluation with choir respondents, primary window (PIYA-411)
- **QA**: Real-user QA — observe crashes, slow responses, confusing flows; collect SER/pitch/SUS data

### Sprint 14 (Nov 3–9) — Backup Usability Evaluation
- Backup respondents/sessions to reach 12+ total, covering trained/untrained groups (PIYA-412)
- **QA**: Same real-user QA observations applied to backup session

### Sprint 15 (Nov 10–16) — Results Analysis
- Compile SER, pitch accuracy, processing time, SUS results against targets (PIYA-413)
- **QA**: Cross-check results against Chapter III thresholds

### Sprint 16 (Nov 17–21) — Final Defense Preparation
- Finalize Chapter IV/V, build slides, rehearse

---

## Sprint Backlog Allocation

| Sprint | Dates | Tickets |
|---|---|---|
| Sprint 1 | Feb 3–21 | (No PIYA tickets — requirements/lit review phase) |
| Sprint 2 | Feb 24–Mar 14 | (No PIYA tickets — architecture/design phase) |
| Sprint 3 | Mar 17–Apr 4 | PIYA-104 |
| Sprint 4 | Apr 7–25 | PIYA-105 |
| Sprint 5 | Apr 28–May 16 | (No PIYA tickets — proposal defense prep) |
| Sep 4 Action Item | Sep 4 | PIYA-300, PIYA-410 |
| Sprint 6 | Sep 8–14 | PIYA-106, PIYA-107, PIYA-110, PIYA-111, PIYA-112, *PIYA-101, *PIYA-102 |
| Sprint 7 | Sep 15–21 | PIYA-108, PIYA-109, PIYA-201, PIYA-202, PIYA-203, PIYA-204, PIYA-205, PIYA-206, *PIYA-103, *PIYA-115, *PIYA-117, *PIYA-118 |
| Sprint 8 | Sep 22–28 | PIYA-207, PIYA-208, PIYA-209, PIYA-210, PIYA-211, PIYA-212, PIYA-213, *PIYA-114, *PIYA-116 |
| Sprint 9 | Sep 29–Oct 5 | PIYA-301, PIYA-302, PIYA-303, PIYA-304, PIYA-313, PIYA-314, PIYA-315, PIYA-316, PIYA-317, *PIYA-305, *PIYA-306, *PIYA-318 (secrets portion) |
| Sprint 10 | Oct 6–12 | PIYA-214, PIYA-215, PIYA-216, PIYA-217, PIYA-310, PIYA-311, PIYA-312, PIYA-321, PIYA-307, PIYA-319, *PIYA-308, *PIYA-309, *PIYA-320, *PIYA-318 (data-at-rest portion), PIYA-405 |
| Sprint 11 | Oct 13–19 | PIYA-401, PIYA-402, PIYA-403, PIYA-113, PIYA-404, PIYA-408, PIYA-406, *PIYA-119 |
| Sprint 12 | Oct 20–25 | PIYA-409, PIYA-407 |
| Sprint 13 | Oct 26–30 | PIYA-411 |
| Sprint 14 | Nov 3–9 | PIYA-412 |
| Sprint 15 | Nov 10–16 | PIYA-413 |
| Sprint 16 | Nov 17–21 | (No PIYA tickets — thesis writing/defense prep) |

_* = ticket introduced mid-list, grouped into the sprint where implementation naturally starts._