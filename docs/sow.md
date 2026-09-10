# PiyaNota — Scope of Work

_Last updated: 2026-09-09 — see Section 3 (open-score assumption)_

## 1. Project Overview
PiyaNota is a mobile Optical Music Recognition (OMR) system that converts
mobile-captured Filipino SATB choral sheet music into playable piano audio
per voice part, supporting independent rehearsal and music literacy for
Filipino choir members.

## 2. Modules & Features

### Module 1: Recognition Pipeline (Backend — ML/Processing)
- **Image Preprocessing**: grayscale, Gaussian blur, background subtraction,
  adaptive thresholding, skew correction, page indexing
- **Staff Region Detection**: YOLOv8 detects/crops staff regions per page
- **Symbol Transcription**: CRNN-CTC transcribes noteheads, rests, clefs
- **Pitch Inference**: rule-based clef-aware diatonic mapping → MIDI pitch
  using staff position, key signature, accidentals
- **SATB Part Reconstruction**: combines events into 4 ordered voice sequences
- **MIDI-Based Audio Synthesis**: 1 playable piano audio track per SATB voice
- **Model Infrastructure**: model loading strategy, versioning, dependency
  pinning, failure/timeout handling, recovery after unplanned server restart

### Module 2: Mobile Application (Frontend — Android)
- Sign Up/Login (gates access to Score Library)
- Onboarding (first-launch guide)
- Score Library (list, search, load, delete saved scores)
- Capture/Add Score (camera, gallery, PDF upload)
- Processing View (real-time progress + failure/error states)
- Playback & Rehearsal (synced indicator, voice selection, play/pause/seek)
- Voice Mixer (per-voice volume, mute/solo, metronome click)
- Playback Speed Control (tempo independent of pitch)
- Export (download voice tracks — individual/combined/all)
- Settings (account info, app version, logout)
- Permissions & Offline Handling
- Frontend-Backend Integration (wiring screens to Module 1/3 APIs — distinct
  from integration *testing*, which is Module 4)

### Module 3: Backend Services (API & Database)
- REST API: score upload, processing status, audio retrieval, account mgmt
- Authentication: sign-up, login, session tokens, password reset
- Authorization: Choir Member / Choir Director roles
- Database: users, saved scores, audio refs, playback timing metadata,
  default score-title assignment on job completion
- File Handling: PDF-to-image rasterization; standardizes camera/gallery/PDF
  into a common page-image format
- Data Security: password hashing, HTTPS, data-at-rest policy, account
  deletion process
- Technology Selection: DB tech + hosting provider decided before schema
  design/provisioning

### Module 4: Deployment & Quality Assurance
- Hosting Setup: server provisioning (GPU if feasible), DB migrations, HTTPS
- Integration Testing: end-to-end across all input types/screens
- Performance Validation: confirm ≤2 min/page under deployed conditions
- Device Compatibility Testing: multiple Android versions/screen sizes
- Usability Evaluation: SUS testing w/ real choirs (DLSU-D Chorale, Lasallian
  Chorus)
- Bug Tracking: centralized log across dry-run and live testing phases

## 3. Key Technical Assumption
Input scores must be in **open-score SATB format** — four separate staves
per system (Soprano, Alto, Tenor, Bass), sorted top-to-bottom in that fixed
order and detected/grouped as such by Staff Region Detection (PIYA-105).
**Closed-score format** (2 staves per system — soprano+alto sharing the
treble staff, tenor+bass sharing the bass staff, voices distinguished by
stem direction/polyphony within a single staff) is **not supported**.
Separating voices sharing a single staff is a substantially different
recognition problem and is explicitly out of scope. This is enforced at
detection time — see PIYA-105's staff-count validation criterion.

"Filipino" in this project refers to the **corpus and evaluation population**
(scores sourced from/used by Filipino choirs; respondents drawn from DLSU-D
Chorale and Lasallian Chorus) — not a notation-specific technical requirement.
No Filipino-language-specific OCR, lyric parsing, or engraving-convention
handling is implemented; the system treats all input as standard Western
choral notation regardless of language.

## 4. Out of Scope
- Closed-score SATB format (see Section 3)
- Handwritten sheet music recognition
- Non-SATB choral formats or instrumental scores beyond piano rendering
- Expressive playback elements (dynamics, articulation, ornamentation)
- Real-time/live audio recognition (capture-then-process only)
- Multi-language UI beyond lyric/chord display in the captured image
- Commercial-scale / multi-tenant deployment

## 5. Success Criteria
| Metric | Target |
|---|---|
| Symbol Error Rate (SER) | ≤ 15% |
| Pitch Inference Accuracy | ≥ 85% |
| Processing Time | ≤ 2 min/page |
| System Usability Scale (SUS) | ≥ 70 (trained + untrained) |
| Min. Evaluation Sample | 12 respondents (DLSU-D Chorale + Lasallian Chorus) |

## 6. Functional Requirements (condensed — full detail in tickets)
- **Core**: FR-1 SATB photo→audio conversion · FR-8 image+overlay playback
  only, no chord/lyric interpretation · FR-10 models load once at startup
- **Account/Security**: FR-2 signup/login · FR-16 settings screen ·
  FR-17 HTTPS everywhere · FR-18 hashed passwords · FR-19 email/password
  validation · FR-20 password reset · FR-21 secure token storage on-device ·
  FR-22 role permissions · FR-23 account/data deletion · FR-25 dedicated
  Login/Sign-Up screens
- **Score Mgmt**: FR-3 save/retrieve/search/delete scores · FR-12 audio
  lifecycle tied to score deletion
- **Input Handling**: FR-6 camera/gallery/PDF → standardized page-images ·
  FR-13 permission requests w/ denial handling
- **Playback/Audio**: FR-4 per-voice play/pause/isolate · FR-5 mix/mute/solo
  · FR-7 export (individual/combined/all) · FR-9 speed w/o pitch change
- **Reliability**: FR-11 defined error + cleanup on timeout/crash · FR-14
  distinct Processing error state · FR-15 offline detection/state · FR-24
  recapture prompt if no staff detected (includes wrong staff-count case,
  see Section 3)
- **Data Security**: FR-26 parameterized queries · FR-27 record-level access
  control · FR-28 secrets never hardcoded · FR-29 sensitive fields excluded
  from API responses

## 7. Non-Functional Requirements (condensed)
- **Performance**: ≤2 min/page (NFR-1)
- **Accuracy**: SER ≤15% (NFR-2)
- **Usability**: SUS ≥70, trained + untrained (NFR-3)
- **Availability**: clear offline notification (NFR-4)
- **Security**: protect credentials/files (NFR-5) · TLS in transit (NFR-7) ·
  no plaintext passwords ever (NFR-8)
- **Reliability**: clear error + recapture on failed staff detection (NFR-6)
  · graceful recovery from server restart, no data loss (NFR-9)
- **Compatibility**: 2–3 distinct Android versions/screen sizes (NFR-10)
- **Maintainability**: pinned dependency versions (framework, CUDA) in a
  documented requirements file (NFR-11)

## 8. Reference
Full FR/NFR list, sprint plan, and per-ticket acceptance criteria live in
`/docs/sprint-plan.md` and `/docs/tickets/module{1-4}-*.md`. This file is a
routing summary — do not duplicate ticket-level detail here.