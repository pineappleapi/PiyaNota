# Module 1: Recognition Pipeline (Backend — ML/Processing)

_Covers: API tickets (client-facing), pipeline stage tickets (internal), infrastructure/reliability tickets._

## API Tickets (Client-Facing)

### PIYA-101 — Submit Score for Processing API
**Method:** POST
**Context:** Accepts image arrays only, in reading order. PDF pages must already be rasterized by the upload-handling layer (PIYA-310) before reaching this endpoint.

**Acceptance Criteria:**
1. Accepts an ordered array of page images (JPEG/PNG) and creates a new processing job scoped to the authenticated user's account.
2. Returns 400 if the array is empty or exceeds 20 pages.
3. Returns 415 if any submitted file is not JPEG or PNG.
4. Returns a `job_id` and status `"queued"` within 1 second of submission; does not block until processing completes.
5. Each page is tagged internally with its `page_index`, reflecting submission order, preserved through every downstream stage.
6. If the processing queue is at capacity, returns 429 with an estimated wait time instead of silently dropping the request.
7. The submission is logged with `job_id`, `user_id`, `page_count`, and timestamp.

**Response Schema:**
```json
{
  "data": {
    "jobId": "job_8841",
    "userId": 214,
    "pageCount": 3,
    "status": "queued",
    "submittedAt": "2026-09-10T09:15:00Z"
  },
  "success": true,
  "status": 202,
  "message": "Score submitted for processing"
}
```

---

### PIYA-102 — Get Processing Status API
**Method:** GET

**Acceptance Criteria:**
1. Returns current status (`queued` / `preprocessing` / `detecting_staff` / `transcribing` / `reconstructing` / `synthesizing` / `complete` / `failed`) for the given `job_id`, scoped to caller's account.
2. Returns `current_page` and `total_pages` while status is not `complete`/`failed`.
3. Returns `percent_complete` (0–100), calculated from completed stages across all pages.
4. Returns 404 if `job_id` doesn't exist or doesn't belong to caller's account.
5. If status is `failed`, includes `failure_reason` and the specific `page_index` that failed, when applicable.
6. Response time under 500ms regardless of underlying job state.

**Response Schema:**
```json
{
  "data": {
    "jobId": "job_8841",
    "status": "transcribing",
    "currentPage": 2,
    "totalPages": 3,
    "percentComplete": 75,
    "failureReason": null,
    "estimatedRemainingSeconds": 62
  },
  "success": true,
  "status": 200,
  "message": "Processing status retrieved"
}
```

---

### PIYA-103 — Get Processed Score Result API
**Method:** GET

**Acceptance Criteria:**
1. Returns 409 (not 200) if job status is not yet `complete`.
2. Once complete, returns all four SATB audio track URLs (soprano, alto, tenor, bass), preprocessed page image URL(s) for playback overlay, and tick-based timing metadata for the playback indicator.
3. Returns 404 if `job_id` doesn't exist or doesn't belong to caller's account.
4. Every returned audio track URL is independently playable/downloadable without additional auth beyond the session token.
5. Repeated calls return cached results and do not re-trigger pipeline computation.

**Response Schema:**
```json
{
  "data": {
    "jobId": "job_8841",
    "scoreId": 552,
    "audioTracks": {
      "soprano": "https://cdn.piyanota.app/audio/job_8841_soprano.mp3",
      "alto": "https://cdn.piyanota.app/audio/job_8841_alto.mp3",
      "tenor": "https://cdn.piyanota.app/audio/job_8841_tenor.mp3",
      "bass": "https://cdn.piyanota.app/audio/job_8841_bass.mp3"
    },
    "scoreImages": ["https://cdn.piyanota.app/pages/job_8841_p1.png"],
    "timingMetadataUrl": "https://cdn.piyanota.app/timing/job_8841.json"
  },
  "success": true,
  "status": 200,
  "message": "Processed score result retrieved"
}
```

---

### PIYA-114 — Cancel Processing Job API
**Method:** POST
**Trigger:** Client action from PIYA-207 when user taps Cancel Scan.

**Acceptance Criteria:**
1. Requires a valid session token; accepts a `jobId`.
2. Returns 404 if the job doesn't exist or doesn't belong to the caller.
3. If job is `queued`, immediately marks it `cancelled`.
4. If job is actively processing, orchestrator terminates processing gracefully at the next safe checkpoint.
5. Deletes all temp files associated with the cancelled job within 60 seconds.
6. Job cannot transition to `complete` after successful cancellation.
7. Returns 409 if job is already in a terminal state (complete/failed/cancelled).
8. Cancellation events logged with `jobId`, `userId`, timestamp, current stage.

**Response Schema:**
```json
{
  "data": { "jobID": "job_8841", "status": "cancelled" },
  "success": true,
  "status": 200,
  "message": "Processing cancelled"
}
```

---

### PIYA-115 — Estimated Processing Time Tracking
**Trigger:** Internal, invoked whenever PIYA-102 returns job status.

**Acceptance Criteria:**
1. Calculates estimated remaining time from: current stage, completed pages, historical average processing times per stage.
2. Returns estimated time in seconds; updates continuously as processing progresses.
3. Returns `null` when estimation confidence is insufficient.
4. Returns `0` when status is `complete`.
5. Estimation generation adds less than 50ms overhead to PIYA-102.

---

### PIYA-116 — Resubmit Failed Page API
**Method:** POST
**Trigger:** Invoked from PIYA-207 when user selects "Retake Page" after `no_staff_detected` or `preprocessing_error`.

**Acceptance Criteria:**
1. Requires authentication; accepts `jobId`, `pageIndex`, replacement image.
2. Verifies ownership; returns 404 if job doesn't exist.
3. Returns 409 if the job did not fail because of a page-specific error.
4. Replaces only the failed page; preserves all unaffected pages.
5. Creates a new processing job automatically; returns a new `jobId`.
6. Logs original and replacement job relationships.

**Response Schema:**
```json
{
  "data": {
    "originalJobId": "job_8841",
    "replacementJobId": "job_8899",
    "pageIndex": 2,
    "status": "queued"
  },
  "success": true,
  "status": 202,
  "message": "Failed page resubmitted"
}
```

## Pipeline Tickets (Internal Processing Stages)

### PIYA-104 — Image Preprocessing Stage
**Trigger:** Internal — invoked automatically after job dequeue, before Staff Region Detection.

**Acceptance Criteria:**
1. Converts every page to grayscale using the luminosity method (weighted RGB sum).
2. Applies Gaussian blur, background subtraction, adaptive thresholding, producing a binary image per page.
3. Applies Canny edge detection + Hough Line Transform to compute dominant skew angle; rotates page if angle exceeds 2°, otherwise leaves unchanged.
4. Tags output as `(I_corrected, page_index)`, forwards to Staff Region Detection only after all four operations complete successfully.
5. If a page fails preprocessing (corrupted/unreadable), sets job status to `failed` with `failure_reason = "preprocessing_error"` and identifies the `page_index`.
6. Preprocessing for a single page at standard mobile-capture resolution (≤3000×4000px) completes in under 5 seconds on deployed hardware.

---

### PIYA-105 — Staff Region Detection (YOLOv8)
**Trigger:** Internal — invoked after Image Preprocessing completes for a given page.

**Acceptance Criteria:**
1. Detects staff regions as bounding boxes, filters detections below the confidence threshold, applies Non-Maximum Suppression using the defined IoU threshold.
2. Achieves mAP50 ≥ 85% when benchmarked against the hand-annotated Filipino SATB test set.
3. Sorts detected regions top-to-bottom by vertical center within each page, then groups them into sets of four (one SATB system per group).
4. **Staff-count validation (open-score enforcement):** after sorting detected regions, verifies the total detected staff count per page is evenly divisible into groups of 4.
   - If a page's staff count is **not** a multiple of 4 (e.g., 2 staves per system, indicating closed-score format), sets job status to `failed` with `failure_reason = "unsupported_staff_layout"` and the specific `page_index`.
   - Triggers the recapture prompt on the mobile client (FR-24) — same UX path as `no_staff_detected`, but with a **distinct reason code** so it can be logged and triaged separately (per PIYA-410) from a true zero-detection failure.
5. Assigns voice labels within each group by fixed vertical index: 1 = Soprano, 2 = Alto, 3 = Tenor, 4 = Bass.
6. Crops and resizes each detected region to a fixed height of 128 pixels, preserving aspect ratio, before passing to transcription.
7. If zero staff regions are detected on a page, sets job status to `failed` with `failure_reason = "no_staff_detected"` and the specific `page_index`, triggering the recapture prompt (FR-24).
8. Accumulates strips across multiple pages into four continuous per-voice sequences, preserving global reading order via `page_index`.

---

### PIYA-120 — Staff-Count Validation Recovery (Confidence Retry + Failure-Reason Disambiguation)
**Trigger:** Proposed — not yet scheduled into a sprint. Depends on PIYA-105 #4 (already implemented). Recorded here as an explicitly-flagged extension beyond PIYA-105's literal text, not a restatement of it — needs sign-off before implementation, since it changes detection behavior (an extra inference pass) rather than just failure classification.

**Context:** PIYA-105 #4 treats every non-multiple-of-4 staff count as `unsupported_staff_layout`, unconditionally. In practice a low-confidence missed detection on a genuinely valid open-score page (e.g. 15 boxes instead of 16) produces the same unrecoverable failure as a genuine 2-staff closed-score page, denying the user the retake option that would actually fix their case (PIYA-207 #7 withholds retake specifically for `unsupported_staff_layout`). This ticket proposes a bounded recovery attempt plus a more precise failure classification for that gap, without changing PIYA-105 #4's core validation rule.

**Acceptance Criteria:**
1. Before PIYA-105 #4 fails a page for a non-multiple-of-4 staff count, the page is re-run through Staff Region Detection exactly once at a reduced confidence threshold (e.g., `CONF_THRESHOLD − 0.1`), attempting to recover a missed low-confidence staff region.
2. If the retry yields a staff count divisible by 4, the page proceeds normally through the rest of Stage 2 using the retry's detections; the retry event is logged (`job_id`, `page_index`, original count, recovered count) for later threshold tuning.
3. If the retry still does not yield a multiple of 4, the page fails using the retry's detected count, classified as:
   - **Odd count** → new `failure_reason = "ambiguous_staff_count"` — offers the same recapture-this-page UX as `no_staff_detected` (PIYA-207 #7), since an odd count is more consistent with a missed/spurious detection than a genuine 2-per-system layout.
   - **Even, non-multiple-of-4 count** → `failure_reason = "unsupported_staff_layout"` (unchanged from PIYA-105 #4) — no recapture-this-page action offered.
4. The retry adds at most one additional detection pass per *failing* page only — never on pages already passing the modulo-4 check — so it does not measurably affect the ≤2-min/page budget (NFR-1) on the happy path.
5. `ambiguous_staff_count` is logged/triaged via the bug tracker (PIYA-410) as its own category, distinct from both `no_staff_detected` and `unsupported_staff_layout`, so its false-positive/negative rate can be evaluated independently.
6. **Open design risk — validate before relying on this in live testing (Sprint 13/14):** the odd/even parity check is a best-effort heuristic, not a guarantee. A genuinely closed-score page with one staff occluded could register an odd count and be misclassified as recoverable; a genuinely open-score page with two independent misses could register an even count and be misclassified as unsupported. Spot-check heuristic accuracy against a labeled sample of known open- and closed-score images before Sprint 13.

**Note (post real-data testing, see PIYA-121):** manual testing of the retry idea in AC1 against real detection output suggests it may be counterproductive — the spurious/duplicate boxes observed already fall within the normal confidence range of real detections (0.4–0.85), so lowering the threshold further is likely to admit more noise rather than recover missed staves. A gap-based dedup fix looked more promising on one input type (digital screenshots) but did not generalize to camera-captured images — see PIYA-121 for the evidence. AC1–2 should be revisited against that evidence before implementation.

---

### PIYA-121 — Camera-Capture Detection Reliability Gap (Investigation)
**Trigger:** Proposed — not yet scheduled. Raised as a QA finding from manual diagnostic testing of `stage2_detection.py` (with PIYA-105 #4's staff-count validation in place), not derived from a written requirement. Needs a triage/priority decision before scheduling into a sprint. Tracked as `BUG-001` in `docs/bug-tracker.md` (PIYA-410) — this section remains the full evidence trace; keep both in sync if the investigation continues.

**Context:** Testing PIYA-105 #4's staff-count validation against two real input samples surfaced a reliability gap specific to camera-captured images — the SOW's actual primary target input (`docs/sow.md` §1: "mobile-captured... choral sheet music"), as distinct from the digital screenshots that happened to be available for testing in `data/raw/Digital Screenshot`.

**Evidence:**
1. 7 camera-captured pages (`data/raw/Raw`, IMG_1081–1088) and 6 digital-screenshot pages (`data/raw/Digital Screenshot`) were run through Stage 1 → Stage 2 with identical settings (`staff_detector_files/weights/best.pt`, default `CONF_THRESHOLD`, `min_cy_gap=30`).
2. Post-dedup staff-count-divisible-by-4 pass rate: **3/6 on screenshots, 1/7 on camera captures.**
3. Screenshot failures traced to a single, cleanly separated cause: one near-duplicate box per failing page, 60–95px from a real detection, against a consistent real inter-staff spacing of 168–180px. Visually confirmed on one failing page (`IMG_5752 (1).PNG`) that the source image is genuinely valid open-score content — the failure was detector noise, not a real layout issue.
4. Camera failures did not reduce to the same single cause. Manually traced `IMG_1082.JPG` (page 2): after accounting for the one obvious near-duplicate (36.1px gap, just over the current 30px dedup threshold), the resulting count was still not divisible by 4 — indicating additional missed and/or spuriously-extra detections beyond simple duplication. Raw (pre-dedup) detection counts hit the 16-box cap on 6 of 7 camera pages (vs. 8–10 on screenshot pages), with generally lower, more spread-out confidence scores (0.4–0.85 on camera vs. 0.65–0.9 on screenshots).
5. The duplicate-vs-real gap boundary itself differs by input source: roughly 36px vs. 49px+ on camera pages, versus 95px vs. 168px+ on screenshots. No single hardcoded `min_cy_gap` value fits both, and a per-page-adaptive threshold (proposed for PIYA-120) addresses double-counted detections only — it does not address the missed/extra-detection pattern that dominates the camera failures.

**Why this matters:** PIYA-105 #2 requires mAP50 ≥ 85% "when benchmarked against the hand-annotated Filipino SATB test set." This finding does not measure whether that target is currently met — mAP wasn't computed here — but it's a concrete signal that detection reliability on camera-sourced images may be materially worse than on cleaner digital sources, and that gap should be checked directly rather than assumed adequate because Stage 2 behaves reasonably on screenshots.

**Proposed acceptance criteria (pending scope/priority decision):**
1. Re-run or confirm PIYA-105's mAP50 benchmark specifically on the camera-captured subset of the Filipino SATB test set, reported separately from any digital-source subset.
2. If mAP50 on camera-sourced images falls materially short of the 85% target, determine whether the gap is addressable via preprocessing quality (deskew/denoise), confidence-threshold tuning, or requires additional fine-tuning data — rather than defaulting to Stage 2 post-processing fixes to compensate for a detection-quality shortfall.
3. Document the finding (met or not met) and, if not met, the corrective action taken, in a form usable for Chapter III/IV evaluation reporting.

---

### PIYA-106 — Symbol Transcription (CRNN-CTC)
**Trigger:** Internal — invoked after Staff Region Detection produces a valid staff strip.

**Acceptance Criteria:**
1. Achieves Symbol Error Rate (SER) ≤ 15% against ground-truth annotated Filipino SATB test sequences.
2. Applies CTC greedy decoding (remove blanks, merge duplicates) to produce final symbol sequence per strip.
3. Detects vertically aligned noteheads sharing a stem and assigns a shared `chord_group_id`, preserved through decoding.
4. Model trained on Camera-PrIMuS, supplemented with CPMS for photographic distortion, fine-tuned on the Filipino SATB dataset before production use.
5. Each output symbol tagged with staff position and chord grouping for use by Pitch Inference.

**Verification note (2026-09-09):** `stage3_transcription.py` implements PIYA-106 and PIYA-107 as
one combined stage by design (its own header titles it "Music Symbol Transcription and Pitch
Inference"), not two independently-tagged hand-off boundaries — confirmed acceptable by the user.
Concretely: AC3's chord grouping is a tick-onset heuristic inside `infer_pitch()` (notes sharing
the same onset tick), not geometric stem detection — confirmed by the user as the correct reading
of "shared stem" for a CRNN-CTC decoder, which only ever sees a linear token sequence from one
horizontally-scanned strip and structurally cannot detect notehead/stem geometry (that's Stage 2's
domain, not decoding). AC5's staff-position + chord tagging is likewise produced inside
`infer_pitch()`, not by `transcribe_strip()`/CTC decode itself. The code's field name is `chord_id`,
not `chord_group_id` as written here — left as-is per the user; note it's also read by
`stage4_reconstruction.py` (chord counting/reporting), so a future rename must update both files.

**AC1 decision (2026-09-10):** No hand-annotated Filipino SATB test set exists yet to measure the
15% SER target against directly. User decision: accept the Camera-PrIMuS-derived SER comparison
(`compare_omr_baselines.py`) as an interim proxy metric for AC1 while a subset of the Filipino SATB
set is hand-annotated in parallel. AC1 is not considered formally closed on the proxy number alone —
final sign-off still requires re-measuring against the hand-annotated ground truth once available.

**AC4 status (2026-09-10):** Blocked, dropped from active work for now. Fine-tuning on the Filipino
SATB dataset (supplemented with CPMS for photographic distortion) can't proceed until the base
Camera-PrIMuS training run currently in progress finishes — per the user, still training as of this
date. Revisit once that run completes; not pursuing a partial/parallel fine-tune in the meantime.

**AC1 end-to-end cross-reference (2026-09-10):** See PIYA-107's AC1 end-to-end measurement note
below — it runs the real CRNN decode path (not ground-truth tokens) end to end and is the closest
proxy this project has to "does symbol transcription plus pitch inference actually work together,"
which token-level SER alone can't answer.

---

### PIYA-107 — Pitch Inference (Clef-Aware Diatonic Mapping)
**Trigger:** Internal — invoked immediately after Symbol Transcription for each staff strip.

**Acceptance Criteria:**
1. Achieves pitch inference accuracy ≥ 85% against ground-truth pitch labels.
2. Computes MIDI pitch as `M = R_c + Δ(p) + K + A`, where `R_c` = clef reference pitch, `Δ(p)` = position-based offset, `K` = key signature offset, `A` = accidental offset.
3. If clef detection fails/missing, applies fallback by voice: treble for Soprano/Alto, treble-8vb for Tenor, bass for Bass.
4. Defaults key signature to `K = 0` and time signature to 4/4 if either not detected on a staff.
5. Groups chord-tagged noteheads (shared `chord_group_id`) into a single chord event; all others treated as individual note events.
6. Every output pitch event includes pitch, duration, time signature, voice label, page index, position.

**AC5 decision (2026-09-10):** Two ways to satisfy "groups chord-tagged noteheads into a single
chord event" were on the table: (a) merge same-onset noteheads into one multi-pitch event object,
or (b) keep them as N separate note events that share a single `chord_id`. Recommended and adopted:
**(b)**, matching the code's existing implementation — no change needed. Reasoning: every downstream
consumer (`stage4_reconstruction.py`'s slur resolution and tick assignment, `stage5_synthesis.py`'s
MIDI note emission) already operates per-event on single-pitch note dicts; a merged multi-pitch
event would need a new dict shape threaded through both stages for no behavioral gain, since
"simultaneous playback" (PIYA-109 AC5) is already achieved by giving chord members identical
`tick_onset`/`duration_ticks`. `chord_id` is the grouping key a consumer uses if it needs to treat
the notes as one chord. Consistent with the 2026-09-09 precedent recorded above for PIYA-106 AC3/AC5
(chord grouping as a tick-onset heuristic producing tagged individual events, not merged geometry).
Explicitly out of scope per the user: separating intra-voice divisi sections (e.g. Soprano 1 vs. 2)
— PIYA-106/107 operate on the four SATB voice parts only.

**AC1 end-to-end measurement (2026-09-10):** The 98.736% figure logged against BUG-009/BUG-010 fed
ground-truth `.agnostic` tokens straight into `infer_pitch()`, isolating the pitch-mapping math from
CRNN decoding — it answers "is the formula correct," not "how accurate is the pipeline in practice."
Built a second scratch check (`end_to_end_pitch_check.py`, not committed — analysis tooling, same
pattern as the earlier isolated check) that instead runs the real CRNN (`transcribe_strip`) on actual
Camera-PrIMuS images, feeds its *predicted* tokens into `infer_pitch()`, and scores the resulting
MIDI pitches against `.semantic` ground truth via edit-distance alignment (so CRNN note
insertions/deletions score as errors too, not just substitutions on a length-matched subset like the
isolated check did). Same 500-sample/seed-42 draw, 6960 expected notes:
- **Clean images:** 98.118% pitch accuracy (6829 matches / 114 subs / 12 ins / 17 del) — clears AC1's
  85% target with a wide margin, consistent with the isolated-math check.
- **Distorted (synthetic photographic-distortion proxy):** 86.983% pitch accuracy (6054 matches / 655
  subs / 41 ins / 251 del) — still clears AC1's 85% floor, but by under 2 points, not the wide margin
  the clean/isolated numbers implied. The 15 worst-scoring samples were checked against clef tokens
  and don't correlate with the deferred `clef.G-L1` BUG-010 gap — they're genuine CRNN misreads on
  heavy distortion, not a pitch-math bug, so no bug-tracker change from this run.

Practical read: AC1's 85% target is met on both proxy variants as measured today, but the distorted
margin is thin enough that this shouldn't be treated as decisively closed. The next thing that would
actually move this number is real camera photos, not more synthetic distortion — and real photos
route through Stage 2 staff detection first, which is where BUG-001 (PIYA-121, open) currently caps
usable input before this pitch-inference path is even reached.

**Real-screenshot AC1 measurement (2026-09-14) — target missed, root cause isolated:** the 98%/87%
figures above are Camera-PrIMuS-only (clean and synthetically-distorted proxies of the *same*
training-distribution font/rendering). Measuring against real, non-CPM screenshots
(`data/raw/Digital Screenshot/IMG_5750`–`5755`, BUG-011) tells a different story: real-world pitch
accuracy is bounded by clef accuracy at **~4.2%** (2/48 strips), since `infer_pitch()`'s formula
(`M = R_c + Δ(p) + K + A`) is entirely clef-relative — an incorrect `R_c` from a wrong clef shifts
every single pitch in that voice by the same wrong offset, with nothing downstream to catch it. AC3's
fallback-by-voice (treble/treble-8vb/bass) only triggers when clef detection *fails/is missing*, not
when the CRNN confidently emits the wrong clef token, so it does not help here. This is a large,
qualitative miss of AC1's 85% floor, not a marginal one — and it is the dominant reason PiyaNota's
real-world (non-CPM) pitch accuracy is far below target, not a secondary contributor.

Root cause (full diagnostic trail in `docs/bug-tracker.md` BUG-011): eight image-level fix hypotheses
were tested and falsified this session and prior sessions (padding dilution, capture-resolution
ceiling, crop-margin/padding sweep, anisotropic stretch, voice-label bleed, BUG-012 content-
destruction contamination, anti-aliasing/binarization mismatch, stroke-width in both directions —
none moved the number off the 2-4/48 floor). ml-cv-lead reviewed this negative-result set, required
three follow-ups (all now done): a statistical correction to the label-bleed write-up (downgraded to
inconclusive, was previously held to a looser bar than the padding sweep), a per-symbol confidence
check (the 46 misreads are confidently wrong, mean 0.79 softmax confidence, statistically the same as
the 2 correct reads' 0.88 — not a low-confidence/uncertain decode), and a synthetic multi-font glyph
test (a third, unrelated, well-formed font — Segoe UI Symbol — also fails 6/6, generalizing the
domain-gap finding beyond this one screenshot's specific engraving software).

**Decision point for the user:** the image-level/code-only fix space is exhausted. ml-cv-lead's
recommendation is retraining/fine-tuning with multi-font-augmented training data (this ticket's own
PIYA-106 AC4 — ties directly to that AC's fine-tuning-on-Filipino-SATB-data plan, already blocked
pending the base Camera-PrIMuS training run's completion). No further code change on this branch
family is expected to move real-world pitch accuracy materially; the next move requires either (a)
the base training run finishing so AC4's fine-tune can proceed with explicit multi-font sourcing, or
(b) a different user-directed path if that's not the preferred next step.

---

### PIYA-108 — SATB Part Reconstruction
**Trigger:** Internal — invoked after Pitch Inference completes for all strips belonging to a job.

**Acceptance Criteria:**
1. Sorts all strips by `page_index`, then vertical position, to establish global reading order before assembly.
2. Appends each strip's event sequence to its corresponding voice sequence (S/A/T/B) without altering event order.
3. Preserves chord events, clefs, key signatures, time signatures, and barlines unmodified during assembly.
4. Verifies all four voice sequences are non-empty before marking the stage complete.
5. If any voice sequence is empty, sets job status to `failed` with `failure_reason = "incomplete_voice_sequence"`, identifying the missing voice, triggers recapture prompt (FR-24).

---

### PIYA-109 — MIDI-Based Piano Audio Synthesis
**Trigger:** Internal — invoked after SATB Part Reconstruction confirms all four voices are complete.

**Acceptance Criteria:**
1. Encodes each voice as an independent MIDI track at 480 PPQ (pulses per quarter note).
2. Applies default tempo of 90 BPM unless a detected tempo marking overrides it.
3. Encodes dotted notes at 1.5× base duration, double-dotted at 1.75×.
4. Encodes rests by advancing the tick counter without generating note events.
5. Encodes chord notes with identical onset/offset ticks to guarantee simultaneous playback.
6. Outputs exactly four independently playable audio files (S/A/T/B) per job upon successful synthesis.
7. Synthesis for a 3-page score completes in under 30 seconds on deployed hardware, as part of the overall ≤2-min/page budget.

## Infrastructure & Reliability Tickets

### PIYA-110 — Model Loading & Inference Optimization
**Trigger:** Internal — executed once at server startup, before API begins accepting requests.

**Acceptance Criteria:**
1. Both trained model weights loaded into memory exactly once at server startup, confirmed via startup log entry with load duration.
2. No request handler reloads model weights from disk during normal operation.
3. Average end-to-end processing time per page is logged for every completed job and does not exceed 2 minutes under single-job conditions.
4. Server memory footprint after model load is documented and does not exceed deployed instance's available memory.

---

### PIYA-111 — Pipeline Failure & Timeout Handling
**Trigger:** Internal — monitored continuously by the pipeline orchestrator for every active job. Distinct from per-stage validation failures already defined in PIYA-104 through PIYA-108.

**Acceptance Criteria:**
1. Each pipeline stage has a defined maximum execution time (e.g., 90 seconds/stage/page); exceeding it sets job status to `failed` with `failure_reason = "stage_timeout"` and identifies the stage.
2. On any failure (validation or timeout), all partial output (temp files, incomplete audio) is deleted within 60 seconds.
3. A crashed worker process does not leave job status stuck in a non-terminal state longer than the defined stage timeout — a watchdog marks it `failed` if no progress update occurs within that window.
4. All failures logged with `job_id`, failed stage, timestamp for later review via bug tracker.

---

### PIYA-112 — Environment & Dependency Pinning
**Trigger:** Internal — verified during Sprint 9 deployment.

**Acceptance Criteria:**
1. A `requirements.txt` (or equivalent) specifying exact versions of ML framework, CUDA version (if GPU), and all inference dependencies is committed to the repository.
2. Deployed server's installed package versions match the pinned file exactly, verified via automated version check at startup.
3. Any mismatch between pinned and installed versions blocks server startup and logs a clear error identifying the mismatched package.

---

### PIYA-113 — Server Restart Job Recovery
**Trigger:** Internal — executed automatically on server startup, before API begins accepting new requests. Satisfies NFR-9; distinct from PIYA-111's per-stage timeout handling.

**Acceptance Criteria:**
1. On startup, any job left in a non-terminal status from before the restart is identified and marked `failed` with `failure_reason = "server_restart"`.
2. Previously completed, saved scores (and their audio/image assets) are confirmed present and unaffected by the restart — recovery only touches in-flight jobs.
3. Affected user's Processing Status screen (PIYA-207) reflects the failed status on next poll.
4. This recovery check completes before the server's health-check endpoint (used in PIYA-401's smoke test) returns 200.

---

### PIYA-117 — Timing Metadata Generation
**Trigger:** Internal, executed after PIYA-109 (MIDI Audio Synthesis) and before the score is marked complete.

**Acceptance Criteria:**
1. Generates timing metadata for every playback event.
2. Converts MIDI tick values into timestamp values.
3. Preserves page index, voice label, note position, chord position.
4. Stores metadata as JSON; produces exactly one metadata file per completed score.
5. Metadata generation adds less than 5 seconds to total processing time.
6. Output is accessible through PIYA-103.

**Example Record:**
```json
{ "timestampMs": 12500, "pageIndex": 1, "voice": "Soprano", "tick": 960, "eventId": 45 }
```

---

### PIYA-118 — Playback Indicator Coordinate Generation
**Trigger:** Internal, executed immediately after PIYA-117.

**Acceptance Criteria:**
1. Every playable event receives page index, timestamp, x-coordinate, y-coordinate.
2. Coordinates reference the original preprocessed score image returned by PIYA-103.
3. Supports multi-page scores and page transitions during playback.
4. Coordinates remain aligned after image scaling performed by the mobile client.
5. Position accuracy is visually validated against evaluation scores.
6. Generated coordinates are stored within the timing metadata file.

**Example Entry:**
```json
{ "timestampMs": 12500, "pageIndex": 1, "x": 1432, "y": 528 }
```

---

### PIYA-119 — Score-to-Playback Synchronization Validation
**Trigger:** Internal QA task performed before deployment and during regression testing.

**Acceptance Criteria:**
1. Playback indicator remains synchronized to audio within ±250ms.
2. Seeking updates the indicator position within 200ms.
3. Page transitions occur at the correct timestamps.
4. A randomly sampled set of completed scores is validated visually.
5. Any detected synchronization drift is logged through PIYA-410.

---

### PIYA-125 — Fix Border-Blanking Content Destruction (BUG-012, Stage 1)
**Trigger:** Found while investigating BUG-012 (near-blank Bass/system-2 strips on 5/6 real
screenshots), previously mis-attributed to Stage 2 box geometry. Branch:
`fix/bug012-border-blank-overreach`, cut from `5387968`.

**Context:** `stage1_preprocessing.py`'s `_blank_border_if_no_staff()` blanks the page's top/bottom
border bands (`BORDER_TOP_PX`/`BORDER_BOTTOM_PX`) except rows matching a literal long-horizontal-
staffline mask. That mask protects only the staffline pixels themselves, not the musical content
(noteheads, stems, clefs, accidentals, ties, dots) sharing the same band. When a real staff sits
within the border zone — e.g. Bass/system-2 on a tightly-cropped digital screenshot, only 47px from
the page bottom on `IMG_5750` — everything except ~5 bare staffline rows was wiped to white,
producing a near-blank strip downstream. Confirmed via direct pixel comparison of raw source page vs.
Stage 1 output at identical coordinates, and confirmed the YOLO box itself was geometrically normal
(ruling out Stage 2 entirely).

**Acceptance Criteria:**
1. Extract the staff-band-detection logic already used by `blank_lyrics_regions()` into a shared
   helper (`_detect_staff_bands()`), preserving its existing `MIN_RAW_LINE_BANDS`/
   `MIN_MERGED_BAND_HEIGHT` reliability guards unchanged.
2. `_blank_border_if_no_staff()` must not blank any row falling inside a detected staff's full
   content zone (merged band ± margin), not just its literal staffline-mask rows.
3. No change to `blank_lyrics_regions()`'s existing behavior/output on any image where staff
   detection succeeds — verified by re-running it standalone pre/post-refactor on the same input.
4. Verified against all 5 affected screenshots (`IMG_5750`/`5751`/`5752`/`5754`/`5755`): the
   previously near-blank Bass/system-2 (or equivalent edge-adjacent) strip now contains real
   notation — checked both by ink-density ratio (near-zero → ~19-22%) and visual inspection.
5. No external callers of either function outside `stage1_preprocessing.py` (grep-confirmed), so no
   other call site requires updating.
6. senior-reviewer sign-off obtained before this branch is proposed for merge (mandatory per
   CLAUDE.md Agent Usage Rules).

**Status (2026-09-14):** Implemented and self-verified against ACs 1-5. Re-running the full BUG-011
6-screenshot/48-strip clef-consistency check with this fix in place gave 2/48 correct — unchanged
from the pre-fix (contaminated) figure — which confirms this fix does not itself move BUG-011's
clef-misread rate, but does establish a clean, uncontaminated baseline for that separate
investigation.

AC6 complete: senior-reviewer reviewed this branch, verdict "recommend merge with changes," 7
findings. 5 addressed via code edit (named `BORDER_PROTECT_MARGIN_RATIO` constant, extracted shared
`_staff_line_mask()` helper, `logger.warning()` on the previously-silent `_detect_staff_bands() is
None` fallback path, `context`-tagged SKIPPED logging, tightened return typing — see bug-tracker.md
BUG-012 row for the full list). 1 addressed via branch hygiene: unrelated pre-existing
`CLAUDE.md`/`docs/methodology.md` doc-reorg changes moved off this branch onto a separate
`docs/methodology-reorg` branch cut from `main`, so this branch now contains only
`stage1_preprocessing.py`, `docs/bug-tracker.md`, and this ticket file. 1 (CPM SER-baseline non-impact)
upgraded from reasoned to empirically verified: `compare_omr_baselines.py` never imports
`stage1_preprocessing`, so Stage 1 changes cannot affect the CPM 98%+/87% baseline. Re-ran the
48-strip verification against the Finding-fixed code: identical 2/48 result, confirming no
regression from the review-driven refactor. Ready for user merge approval — no code changes remain
outstanding.