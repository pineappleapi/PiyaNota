# Module 1: Recognition Pipeline (Backend — ML/Processing)

_Covers: API tickets (client-facing), pipeline stage tickets (internal), infrastructure/reliability tickets._

## API Tickets (Client-Facing)

### PIYA-101 — Submit Score for Processing API
**Method:** POST
**Context:** Accepts image arrays only, in reading order. PDF pages must already be rasterized by the upload-handling layer (PIYA-310) before reaching this endpoint. *(Amended 2026-10-08, PIYA-206, backend-lead: the request is `multipart/form-data`. Each page image is one file part named `pages`, sent in reading order; part order is page order. The score metadata fields in AC8 travel as text parts in the same request.)*

**Acceptance Criteria:**
1. Accepts an ordered array of page images (JPEG/PNG) and creates a new processing job scoped to the authenticated user's account.
2. Returns 400 if the array is empty or exceeds 20 pages. *(2026-10-08: error codes `no_pages` and `too_many_pages`, per AC9.)*
3. Returns 415 if any submitted file is not JPEG or PNG. *(2026-10-08: error code `unsupported_file_type`, with the offending `pageIndex`. The type is decided from the file's magic bytes, not from the part's `Content-Type` or filename. HEIC and WebP are rejected; the client re-encodes every page after its edits (AC10), so it sends JPEG or PNG.)*
4. Returns a `job_id` and status `"queued"` within 1 second of submission; does not block until processing completes.
5. Each page is tagged internally with its `page_index`, reflecting submission order, preserved through every downstream stage.
6. If the processing queue is at capacity, returns 429 with an estimated wait time instead of silently dropping the request. *(2026-10-08: error code `queue_full`. The wait is sent both as a `Retry-After` header and as `error.retryAfterSeconds`. A per-user submission limit is a separate 429, `rate_limited`, per AC9.)*
7. The submission is logged with `job_id`, `user_id`, `page_count`, and timestamp.
8. **Score metadata fields** (added 2026-10-08, PIYA-206, user decision; canonical values chosen by backend-lead). Sent as text parts next to the files. *(2026-10-09: `composer` renamed to `arranger`, with error codes `arranger_too_long` / `arranger_invalid` and column `jobs.arranger`, user decision — the field holds the arranger.)*

   | Field | Required | Rule | Stored in `jobs` (PIYA-311) | 400 error code |
   |---|---|---|---|---|
   | `title` | yes | 1–120 characters after trimming | `title` | `title_required` (missing or blank), `title_too_long`, `title_invalid` |
   | `arranger` | no | at most 120 characters after trimming | `arranger`, NULL when absent | `arranger_too_long`, `arranger_invalid` |
   | `tempoBpm` | no | ASCII digits only, integer 30–240; absent means 90 | `tempo_bpm`, always stored (90 when absent) | `invalid_tempo` |
   | `keySignature` | no | one of the 15 values below, exact case | `key_signature`, NULL when absent | `invalid_key_signature` |
   | `timeSignature` | no | one of `4/4`, `3/4`, `2/4`, `6/8`, `2/2` | `time_signature`, NULL when absent | `invalid_time_signature` |

   `keySignature` values (major key named by accidental count; ASCII `#` and lowercase `b`, never `♯`/`♭`):

   | Sharps | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   |---|---|---|---|---|---|---|---|---|
   | value | `C` | `G` | `D` | `A` | `E` | `B` | `F#` | `C#` |

   | Flats | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   |---|---|---|---|---|---|---|---|
   | value | `F` | `Bb` | `Eb` | `Ab` | `Db` | `Gb` | `Cb` |

   - **Absent values.** "Not sure" (key) and "Other" (time signature) are both expressed by omitting the field, and the server stores NULL. Multipart cannot carry `null`; an optional field sent with an empty or whitespace-only value is treated as absent. The literal string `"null"` gets no special handling: it is an invalid enumerated value (400), and as `arranger` it would be stored as text, so the client must omit the field as agreed.
   - **Character counting.** Values are trimmed and NFC-normalized, then counted in Unicode code points (Python `len()`, PostgreSQL `char_length()`). Text containing control characters (Unicode category Cc, including newlines and tabs) is rejected with `title_invalid` / `arranger_invalid`.
   - A field sent more than once returns 400 `duplicate_field`. Unrecognized field names are ignored and not stored, so a newer client still works against an older server.
   - **Meaning.** `keySignature` and `timeSignature` are display labels only. They are never passed to the pipeline; Stages 3–4 use their own clef/key/time-signature detection. `tempoBpm` is the default playback speed, and the four tracks are rendered at it (Stage 5 `bpm`). It counts **quarter notes per minute whatever the time signature** (Stage 5 writes a quarter-note MIDI tempo at 480 PPQ), so `6/8` at dotted-quarter = 60 is `tempoBpm` 90, and `2/2` at half = 60 is `tempoBpm` 120. The submitted (or default) tempo takes precedence over any detected tempo marking. *(added 2026-10-09, user decision: PIYA-109 AC2 now says the same. The tempo stays one quarter-note BPM for the whole piece, whatever the meter or meter changes; the metronome click works out each measure's beat from that BPM, see PIYA-210.)*
9. **Errors** (added 2026-10-08, PIYA-206 / PIYA-215 AC3). Every error uses the standard envelope with an `error` object, so the app can map `error.code` to its own message. `message` is English text for logs, not for display:
   ```json
   { "data": null, "success": false, "status": 400, "message": "Title is required",
     "error": { "code": "title_required", "field": "title" } }
   ```
   `field` is set for field errors, `pageIndex` (numbered as in AC5) for errors about one file, and `retryAfterSeconds` for 429.

   | Status | Codes |
   |---|---|
   | 400 | `no_pages`, `too_many_pages`, `mixed_input_types`, `duplicate_field`, plus the AC8 field codes |
   | 401 | session rule shared by every authenticated endpoint |
   | 413 | `file_too_large` (one image over 10 MB), `request_too_large` (body over 100 MB), `image_pixels_too_large` (a page decodes to more than 50 megapixels) |
   | 415 | `unsupported_file_type` |
   | 422 | `corrupt_image` (passes the magic-byte check but cannot be decoded) |
   | 429 | `rate_limited` (per-user submission limit; starting value 10 per user per rolling hour, set in config), `queue_full` (AC6) |

   - Only one error is returned. If several apply, the first in this order wins: 401, 429 `rate_limited`, 413, 400 field errors, 400 `mixed_input_types` / `no_pages`, 415, 422, 400 `too_many_pages`, 429 `queue_full`.
   - A PDF part sent here together with images returns 400 `mixed_input_types`. A PDF sent alone returns 415; PDFs go to PIYA-310.
   - The reverse proxy may answer an oversized body with its own 413 and no JSON. Its body limit and Flask's `MAX_CONTENT_LENGTH` must both be 100 MB, and the client treats any 413 without a readable `error.code` as `request_too_large`.
10. **EXIF and orientation** (added 2026-10-08, PIYA-206, user decision). The client strips EXIF and applies rotation and crop to the pixels before upload, so the server receives final, already-edited images:
    - The server decodes every page **ignoring** the EXIF Orientation tag and re-encodes it during standardization (PIYA-320) with no metadata (no EXIF, XMP, IPTC or comments). Only the re-encoded image is written to storage; the bytes as uploaded are never persisted. GPS and other EXIF values are never stored or logged.
    - OpenCV's `cv2.imread` / `cv2.imdecode` apply EXIF orientation by default, so decode with `cv2.IMREAD_IGNORE_ORIENTATION` (or use Pillow without `ImageOps.exif_transpose`). Test: a JPEG carrying Orientation = 6 comes out of standardization with its pixels unrotated, in the orientation in which they were submitted.
11. **No partial state** (added 2026-10-08). The job row and its stored page images are committed together. On any error, no job row is left behind, and page images already written for that request are deleted.

**Response Schema:** *(2026-10-08: the response echoes the stored `title` and `tempoBpm`, the latter with the default applied. `arranger`, `keySignature` and `timeSignature` are echoed only when present and omitted otherwise, never `null`.)* *(2026-10-09: renamed from `composer`, user decision — the field holds the arranger.)*
```json
{
  "data": {
    "jobId": "job_8841",
    "userId": 214,
    "pageCount": 3,
    "status": "queued",
    "submittedAt": "2026-09-10T09:15:00Z",
    "title": "Bayan Ko",
    "arranger": "Constancio de Guzman",
    "tempoBpm": 90,
    "keySignature": "Eb",
    "timeSignature": "4/4"
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
2. Once complete, returns all four SATB audio track URLs (soprano, alto, tenor, bass), preprocessed page image URL(s) for playback overlay, and tick-based timing metadata for the playback indicator. *(added 2026-10-09, user decision: "all four" now means every voice not listed in `failedVoices` (AC10). A failed voice has no `audioTracks` key.)*
3. Returns 404 if `job_id` doesn't exist or doesn't belong to caller's account.
4. Every returned audio track URL is independently playable/downloadable without additional auth beyond the session token.
5. Repeated calls return cached results and do not re-trigger pipeline computation.
6. Once complete, the response includes a `review` object. `reviewNeeded` is true whenever any Stage 3 strip flag or Stage 4 reconstruction flag carries `review_needed`, or the clef/key classifier was disabled. `reasons` lists the distinct flag codes. `items` holds at most 200 entries, each with `code`, `voice`, `pageIndex`, `systemIndex`, `bar`, and `truncated` is set when entries were left out. `reviewNeeded: false` means no flag was raised, not that the transcription is verified correct. Model provenance (checkpoint hash, gate status) is never included in the response. *(Added 2026-09-29, backend-lead review. While the clef/key classifier has not passed its real-photo gate (BUG-021), every job carries the reason `clef_key_unvalidated`, so `reviewNeeded` is always true. The pipeline side is `stage5_synthesis.run_full_pipeline_with_report()` / `build_review()`; flag codes stay snake_case, voice is lowercase.)*

7. Once complete, the response includes `title` (always present) and `arranger` (omitted when absent, never `null`), read from the job's `scores` row (PIYA-321), so Playback (PIYA-208) can show its header ("arr. by <arranger>") when opened straight from Processing without a library fetch. *(Added 2026-10-09, user decision — closes the "PIYA-103 result has no title/composer" contract gap reported by frontend-lead; the field is `arranger`, not `composer`.)*
8. Once complete, the response includes `tempoBpm`, the tempo the four tracks were rendered at (the stored `tempo_bpm`, 90 when none was submitted; same quarter-note-per-minute meaning as PIYA-101 AC8). The Speed modal (PIYA-210) shows speed in BPM, so the client plays at rate = chosen BPM ÷ `tempoBpm`, and the metronome click (PIYA-209/210) is generated client-side at the chosen BPM. *(Added 2026-10-09, user decision for PIYA-210.)* *(added 2026-10-09, user decision: `tempoBpm` is one quarter-note BPM for the whole piece. The click is laid out measure by measure from the timing file's `bars` table (PIYA-117 AC9) by the rules in PIYA-210, not as one click per quarter note.)*
9. **Muted measures** *(added 2026-10-09, user decision)*. Once complete, the response includes `mutedMeasures`: the measures of a voice that Stage 5 rendered as silence because Stage 4's repair of that measure threw notes away (PIYA-109 AC8). It is always present and is `[]` when nothing was muted. Each entry:

   | Field | Type | Meaning |
   |---|---|---|
   | `voice` | string | lowercase, as in `audioTracks` |
   | `bar` | int or null | printed measure number (PIYA-117 AC7, pickup = 0); `null` when Stage 4 could not anchor the voice-strip to the bar grid |
   | `pageIndex` | int | 0-based, as in PIYA-117 "Index bases" |
   | `systemIndex` | int | 0-based within its page |
   | `startMs` / `endMs` | int | the silent span at the rendered tempo (`tempoBpm`), on the same clock as the timing file's `timestampMs`; `endMs` is exclusive |
   | `reason` | string | the Stage 4 flag code that caused it, snake_case |

   - Muted reasons (repair was lossy): `bar_overflow_clipped`, `suspected_missing_barline` (clipped), `bar_length_invariant_failed`, `local_placement_overrun` (notes dropped), and `pickup_length_mismatch` only when its action is `trimmed_head_to_pickup`.
   - Never muted (the measure was only scaled or compressed, nothing thrown away): `bar_overflow_run_scaled`, `suspected_tuplet` (compressed). A `pickup_length_mismatch` that was only right-aligned is not muted either.
   - Muting is by tick span, so it works where `bar` is `null`. Only that voice is silent in the span; the other voices and the rest of that voice play.
   - Entries are ordered by `startMs`, then voice (soprano, alto, tenor, bass). The list is not capped.
   - Every muted measure also appears in `review.items` with the same `reason` as its `code`, so `review.reviewNeeded` is true whenever `mutedMeasures` is non-empty.
10. **Failed voices** *(added 2026-10-09, user decision)*. One voice that comes back empty from Stage 4, or whose audio Stage 5 cannot produce, no longer fails the job (PIYA-108 AC4/AC5, PIYA-109 AC9). The job fails only if all four voices fail. The response includes `failedVoices`, a list of lowercase voice names in SATB order (e.g. `["tenor"]`). It is always present and is `[]` when every voice rendered. A voice in `failedVoices` has no `audioTracks` entry and no `mutedMeasures` entries. *(Open: whether a voice that Stage 4 placed but Stage 5 could not render keeps its events in the timing file is not decided yet.)* `review.reasons` includes `voice_failed` whenever `failedVoices` is non-empty, with one `review.items` entry per failed voice: `{"code": "voice_failed", "voice": "tenor", "pageIndex": null, "systemIndex": null, "bar": null}`.

*(2026-10-09: open gap. This endpoint is keyed by `job_id`, but the library opens scores by `scoreId`. See PIYA-308 AC8 in `module3-backend.md`. Playback (PIYA-208) is currently built against a fake keyed by score. `review.items[].pageIndex` / `systemIndex` are also affected by the index-base question under PIYA-117.)*

**Response Schema:**
```json
{
  "data": {
    "jobId": "job_8841",
    "scoreId": 552,
    "title": "Bayan Ko",
    "arranger": "Constancio de Guzman",
    "tempoBpm": 90,
    "audioTracks": {
      "soprano": "https://cdn.piyanota.app/audio/job_8841_soprano.mp3",
      "alto": "https://cdn.piyanota.app/audio/job_8841_alto.mp3",
      "tenor": "https://cdn.piyanota.app/audio/job_8841_tenor.mp3",
      "bass": "https://cdn.piyanota.app/audio/job_8841_bass.mp3"
    },
    "scoreImages": ["https://cdn.piyanota.app/pages/job_8841_p1.png"],
    "timingMetadataUrl": "https://cdn.piyanota.app/timing/job_8841.json",
    "review": {
      "reviewNeeded": true,
      "reasons": ["bar_overflow_clipped", "clef_key_unvalidated", "key_no_majority"],
      "items": [
        {"code": "key_no_majority", "voice": "tenor", "pageIndex": 1, "systemIndex": 2, "bar": null},
        {"code": "bar_overflow_clipped", "voice": "bass", "pageIndex": 0, "systemIndex": 0, "bar": 4}
      ],
      "truncated": false
    },
    "mutedMeasures": [
      {"voice": "bass", "bar": 4, "pageIndex": 0, "systemIndex": 0, "startMs": 8000, "endMs": 10667, "reason": "bar_overflow_clipped"}
    ],
    "failedVoices": []
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

**Fresh-photo eval note (2026-09-28):** `data/eval_fresh/REPORT.md` is the first measurement against a
user-verified Filipino-dataset GT: Non Nobis Domine, 36 strips.
- Token SER is 58.3-58.5% as-is and 50.2-50.8% with the clef/key classifier (fine-tuned seed range). Both are far
  above AC1's 15%, so AC1 is not met.
- The remaining error is note and rhythm reading (the BUG-011 domain gap), not the clef/key header.

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

**Clef/key classifier status (2026-09-27):** this is a flag-only side model for the BUG-011 clef collapse. The plan and decisions are in `docs/decisions/piya-106-clef-keysig-detector-plan.md`.

- Local training code is ready and reviewed: ml-cv-lead gave a conditional GO, and fixes R1-R6 / E1-E4 are applied in `850f880`.
- The CPU-only venv is the reference configuration, because the GPU is unreliable (BUG-019).
- No full training run has started, and no accuracy number exists yet.
- Validation is Dormi Jesu, Livin' on a Prayer and Flashlight, check-only. DSMN and Honneur a Toi stay test-only.
- Stage 3 integration (including the `key_plan` for mid-piece key changes) has not started.

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
7. **Time signature per measure, including mid-strip changes** *(added 2026-10-09, user decision)*. A time signature is read wherever it is engraved in the strip: in the header, or after a barline mid-strip (a mid-line meter change). It applies from that measure on, and each event's `time_signature` is the meter of the measure it sits in, not the strip header's. Today the meter is read only in the header states (`clef` / `keysig` / `fixed_header` in `infer_pitch()`); in `body` a metersign is ignored and every `digit.*` token is taken as a multirest count, so a mid-strip `3/4` is lost (BUG-051).
8. **Meter digits vs multirest counts by staff position** *(added 2026-10-09, user decision)*. In the Camera-PrIMuS vocabulary a time-signature digit sits on the staff (numerator `digit.N-L4`, denominator `digit.N-L2`) and a multirest count sits above it (`digit.N-S5`). Stage 3 tells them apart by that position, not by where the digit falls in the token order: an `S5` digit is never read as a meter, and an `L4` + `L2` pair is never read as a multirest count, in the header or the body. This fixes BUG-035 (a strip-start multirest count read as a meter) and the mid-strip case in BUG-051.
9. **Detected vs defaulted meter** *(added 2026-10-09, user decision)*. Each event also carries `time_signature_source`: `"detected"` when its measure's meter was read in this strip (header or mid-strip, AC7), `"default"` when the strip had no meter at or before that measure and AC4's 4/4 was stamped. Stage 4 uses this to inherit the previous meter instead of reading a defaulted 4/4 as a change (PIYA-108 AC7).

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
4. Verifies all four voice sequences are non-empty before marking the stage complete. *(added 2026-10-09, user decision: an empty voice no longer stops the stage. It is reported as a failed voice (PIYA-103 AC10) and the other voices continue to Stage 5. Today `reconstruct_satb()` raises `ValueError` if any voice is empty; that raise moves to the all-four-empty case.)*
5. If any voice sequence is empty, sets job status to `failed` with `failure_reason = "incomplete_voice_sequence"`, identifying the missing voice, triggers recapture prompt (FR-24). *(added 2026-10-09, user decision: the job fails this way only when **all four** voices are empty or fail in Stage 5 (PIYA-109 AC9). One to three failed voices give a completed job with `failedVoices`.)*
6. **Per-measure meter** *(added 2026-10-09, user decision)*. Stage 4 lays out bars measure by measure, each measure's length taken from its own meter (PIYA-107 AC7), so bar ticks can vary inside one system. A meter change at any barline, mid-system included, takes effect from that measure. The voices' meter for a measure is decided by consensus across voices, as `_consensus_time_signatures()` does per system today. `report["systems"]` gives, per system, `first_bar`, `n_bars`, `start_tick` and the ticks and time signature **of each bar** (a single `bar_ticks` / `time_signature` per system is no longer enough), and `pickup_ticks` stays at the top level. A multirest covers the bar count Stage 3 read for it, each bar at its own meter's length, not its tick total divided by one bar's length (`_measure_span()` today assumes 4/4 whole-note bars).
7. **Inherit, don't reset, on a defaulted meter** *(added 2026-10-09, user decision)*. A measure whose meter is only Stage 3's default (`time_signature_source: "default"`, PIYA-107 AC9) inherits the last detected meter. A detected meter always counts, including a detected 4/4 after another meter. This removes the known limit in `_consensus_time_signatures()` ("a real change back to 4/4 mid-piece is invisible"). Each bar also records how its meter was obtained: `detected` (a meter was read for it in its own system: the strip header, or a change at or before it in that strip), `inherited` (carried over from an earlier system), `default` (no meter detected at or before it anywhere, 4/4 used) or `unknown` (Stage 4 could not establish one); PIYA-117 AC9 publishes this as `meterSource`.
8. **Tick span on lossy repairs** *(added 2026-10-09, user decision)*. Every flag whose repair threw notes away (the muted reasons in PIYA-103 AC9) carries `start_tick` and `end_tick`, the global tick span (end exclusive) of the measure whose content was lost, so Stage 5 can silence it even where `bar` is `null`. For a bar-anchored measure this is that bar's span; for `pickup_length_mismatch` with `trimmed_head_to_pickup` it is the pickup, `[0, pickup_ticks)`. *(Open: the span for `local_placement_overrun` is not decided. That voice-strip has no bar anchoring, so Stage 4 cannot say which measure lost the notes.)*

---

### PIYA-109 — MIDI-Based Piano Audio Synthesis
**Trigger:** Internal — invoked after SATB Part Reconstruction confirms all four voices are complete. *(added 2026-10-09, user decision: invoked when Stage 4 has at least one non-empty voice; see PIYA-108 AC4/AC5.)*

**Acceptance Criteria:**
1. Encodes each voice as an independent MIDI track at 480 PPQ (pulses per quarter note).
2. Renders every track at the job's `tempoBpm` (PIYA-101 AC8; 90 when none was submitted), one quarter-note tempo for the whole piece. A detected tempo marking never overrides it. *(added 2026-10-09, user decision; replaces "Applies default tempo of 90 BPM unless a detected tempo marking overrides it", which contradicted PIYA-101 AC8.)*
3. Encodes dotted notes at 1.5× base duration, double-dotted at 1.75×.
4. Encodes rests by advancing the tick counter without generating note events.
5. Encodes chord notes with identical onset/offset ticks to guarantee simultaneous playback.
6. Outputs exactly four independently playable audio files (S/A/T/B) per job upon successful synthesis. *(added 2026-10-09, user decision: one file per voice that did not fail (AC9); a failed voice has no file.)*
7. Synthesis for a 3-page score completes in under 30 seconds on deployed hardware, as part of the overall ≤2-min/page budget.
8. **Damaged measures play as silence** *(added 2026-10-09, user decision)*. For each Stage 4 flag whose repair was lossy (the muted reasons in PIYA-103 AC9, with the tick span from PIYA-108 AC8), that voice is silent from `start_tick` to `end_tick`: notes starting inside the span are not emitted, and a note that starts earlier and sounds into the span is cut at `start_tick`. Measures that were only scaled or compressed (`bar_overflow_run_scaled`, `suspected_tuplet`) play as repaired. The other voices, and the rest of the muted voice, are unaffected. Each silenced span becomes one `mutedMeasures` entry, with `startMs` / `endMs` converted at `tempoBpm` the same way as the timing file.
9. **One voice failing does not fail the job** *(added 2026-10-09, user decision)*. A voice that is empty after Stage 4, or whose audio cannot be produced, is left out of the output and listed in `failedVoices` (PIYA-103 AC10). The other voices are still rendered and the job completes. The job fails only if all four voices fail.

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
7. Every event carries `bar`, the 1-based measure number taken from Stage 4's `global_bar`. A pickup (anacrusis) measure is `bar: 0`, so the first full measure is always `bar: 1` and the numbers match the printed score. `bar` is `null` for events in a voice-strip that Stage 4 could not anchor to the bar grid (its `placed_by_local_ticks` flag), and the client must accept `null`. Rest events are included, so a measure that starts on a rest still has an event on its downbeat. A note tied across a barline is one event (Stage 4 merges ties) and keeps the bar it starts in. *(Added 2026-10-09, for PIYA-208's ⏮ first-measure / ⏭ last-measure-start buttons. Depends on Stage 4 bar tracking in `stage4_reconstruction.py`; when bars are not anchored, those buttons can only approximate.)*
8. Every event also carries `systemIndex` (Stage 2's `sys_idx`, already on every Stage 3/4 event) and `systemTopY` / `systemBottomY` (the top of the system's first staff and the bottom of its last staff, in the same pixel space as `y`). The Playback band spans the whole system. Without these fields the client has to guess the band's height from the four voices' note `y` values near one timestamp, which shrinks when the voices sit close together and breaks when a voice is resting. Stage 2 already has these staff boxes, so the cost is three integers per event. *(Added 2026-10-09, backend-lead; adopted by the user the same day. The client still falls back to note `y` values when the fields are absent.)*
9. **Measure table** *(added 2026-10-09, user decision)*. The file also holds `bars`, one entry per measure of the whole piece, in order, so the client can lay out the metronome click per measure (PIYA-210). It is built from Stage 4's layout (`report["systems"]`: `first_bar`, `n_bars`, `start_tick`, each bar's ticks and time signature, PIYA-108 AC6; and `pickup_ticks`), not from any voice's events, so a measure where a voice rests, failed or was muted still has its entry.

   | Field | Type | Meaning |
   |---|---|---|
   | `bar` | int | printed measure number as in AC7; `0` = pickup |
   | `startMs` | int | start at the rendered tempo (`tempoBpm`), same clock as `timestampMs` |
   | `durMs` | int | the measure's actual length at the rendered tempo |
   | `startTick` | int | global tick at 480 PPQ |
   | `durTicks` | int | the measure's actual length in ticks (a pickup or a short final bar is shorter than its meter) |
   | `numerator` | int or null | `null` only when `meterSource` is `unknown` |
   | `denominator` | int or null | `null` only when `meterSource` is `unknown` |
   | `meterSource` | string | `detected`, `inherited`, `default` or `unknown` (PIYA-108 AC7) |
   | `pickup` | bool | `true` only for the bar-0 entry |
   | `groups` | null | reserved for beat grouping; always `null` for now and ignored by the client |

   - Entries tile the piece with no gaps: the first starts at tick 0, and each `startTick` is the previous `startTick + durTicks`. A multirest of N bars gives N entries.
   - A pickup entry carries bar 1's meter, so the client can place its clicks as the end of a full bar.
   - With `meterSource: "default"` the meter is the 4/4 Stage 4 assumed, written as `4/4`.
   - `durMs` is the next entry's `startMs` minus this one's (the last one runs to the end of the piece), so rounding never opens a gap.

**Record shape (2026-10-09):** PIYA-117 and PIYA-118 describe the **same file**: one JSON array per score (AC4), each element one event holding both the timing fields above and PIYA-118's `x`/`y` (PIYA-118 AC6). PIYA-118's example below is the subset it adds, not a second record type. `timingMetadataUrl` in PIYA-103 serves this array. *(added 2026-10-09, user decision: the top level is now an object, `{"events": [...], "bars": [...]}`. `events` is the event array described here; `bars` is AC9. The client already accepts both a bare event array and `{"events": [...]}`; a file with no `bars` gets the plain quarter-note click fallback in PIYA-210.)*

**Index bases (0-based API indices decided by the user 2026-10-09; `voice` casing still open):** no ticket fixes whether `pageIndex` counts from 0 or 1. The pipeline counts from 1 (Stage 1 `page_index`, Stage 2 `sys_idx`), and PIYA-103's `review.items` pass those values through unchanged (`stage5_synthesis.build_review()`). The app counts pages from 0 (PIYA-116 retake, PIYA-207 failure page). Decision: in every API response, `pageIndex` counts from 0 and indexes `scoreImages` directly, and `systemIndex` counts from 0 within its page. The serializer converts from the pipeline's 1-based values at that boundary. `bar` stays 1-based because it is a printed measure number, not an index. This applies to PIYA-101/102/103/116 as well, not only this file. `voice` here is `"Soprano"`, while PIYA-103 uses lowercase (`audioTracks` keys and `review.items`). The two should match.

**Example Record:**
```json
{ "timestampMs": 12500, "pageIndex": 0, "voice": "Soprano", "tick": 960, "eventId": 45, "x": 1432, "y": 528, "bar": 3 }
```
With the optional AC8 fields: `"systemIndex": 0, "systemTopY": 410, "systemBottomY": 1190`.

**Example file** *(added 2026-10-09, user decision)*: a one-quarter pickup in 3/4, then a change to 6/8 at bar 3, at `tempoBpm` 90 (one quarter = 480 ticks = 666.67 ms):
```json
{
  "events": [
    { "timestampMs": 0, "pageIndex": 0, "voice": "Soprano", "tick": 0, "eventId": 0, "x": 312, "y": 528, "bar": 0 }
  ],
  "bars": [
    { "bar": 0, "startMs": 0,    "durMs": 667,  "startTick": 0,    "durTicks": 480,  "numerator": 3, "denominator": 4, "meterSource": "detected", "pickup": true,  "groups": null },
    { "bar": 1, "startMs": 667,  "durMs": 2000, "startTick": 480,  "durTicks": 1440, "numerator": 3, "denominator": 4, "meterSource": "detected", "pickup": false, "groups": null },
    { "bar": 2, "startMs": 2667, "durMs": 2000, "startTick": 1920, "durTicks": 1440, "numerator": 3, "denominator": 4, "meterSource": "detected", "pickup": false, "groups": null },
    { "bar": 3, "startMs": 4667, "durMs": 2000, "startTick": 3360, "durTicks": 1440, "numerator": 6, "denominator": 8, "meterSource": "detected", "pickup": false, "groups": null }
  ]
}
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
7. Each event carries the `bar` defined in PIYA-117 AC7 alongside its coordinates (and PIYA-117 AC8's `systemIndex` / `systemTopY` / `systemBottomY`). `x`/`y` are pixels in `scoreImages[pageIndex]` at its served resolution. *(Added 2026-10-09; see PIYA-117 "Record shape" and "Index bases".)*

**Example Entry** (the fields this ticket adds to the PIYA-117 event; the full merged event is shown under PIYA-117):
```json
{ "timestampMs": 12500, "pageIndex": 0, "voice": "Soprano", "tick": 960, "eventId": 45, "x": 1432, "y": 528, "bar": 3 }
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

### PIYA-126 — Chord / Divisi Support in Symbol Transcription (deferred; number provisional)
**Trigger:** Divisi (two notes on one staff at the same time) is common in the target SATB scores, and
both divisi notes must sound in the same voice track. Stage 3 cannot represent simultaneous notes:
Camera-PrIMuS is monophonic with no chord token, and Stage 3's `chord_id` block never fires.
**Sequencing:** Do NOT start until PIYA-106 fine-tuning Steps 2–7 are closed (font fix and chord fix
must not be confounded). Full design and 11-step plan: `docs/decisions/piya-106-chord-vocabulary-plan.md`.

**Interim scope (now):** the pipeline is monophonic-only. It should *detect* likely divisi/chord
strips (e.g. bar overflow that looks like stacked notes, vertically stacked noteheads in the strip)
and flag them `review_needed` rather than silently playing them as sequential notes.

**Acceptance Criteria (draft, to be confirmed with the user):**
1. Data-only CTC frame-budget feasibility audit passes for chords up to the chosen size (per-epoch
   zero-loss counter added).
2. Chord token (`chordnote-*`) added to the end of `VOCAB`; existing indices and the
   `finetuned_font_seed{1,2}.pt` checkpoints unchanged until PIYA-106 closes.
3. `infer_pitch` emits chord members with shared onset/duration and an explicit `chord_id`.
4. Training data built from ds2_dense and camera-grandstaff (label source only, split per staff);
   SynthSalienceChoralSet is not usable for training.
5. `piyanota_dataset` remains test-only; results reported per source, per font, chord vs non-chord.
6. ml-cv-lead review before training code and after any reported number; senior-reviewer before merge.

### PIYA-127 — Recapture Prompt & Page Replacement (FR-24)
**Trigger:** A page cannot be used: zero staves (`no_staff_detected`), staff count not a multiple of 4
(`unsupported_staff_layout`), or a missing voice (`incomplete_voice_sequence`). Split out of BUG-001
(signed off 2026-09-26); tracked as BUG-018. Full spec, checklist and draft acceptance criteria:
`docs/tickets/recapture-prompt-fr24.md`.
**Summary:** Today a zero-box page is silently skipped and the other failures are bare `ValueError`s, so
PIYA-102/116 have no structured reason or `page_index` to act on. Needs (1) one structured failure type with
reason + `page_index`, (2) the recapture checklist on the app (steady phone, good lighting, eye level, nothing
blocking the page), and (3) retake replaces the failed page in place: new image id, same `page_index`, other
pages' order untouched, old image kept as superseded. Overlaps PIYA-116 (job-level resubmit) - reconcile
before implementation. Acceptance criteria are DRAFT until confirmed with the user.

