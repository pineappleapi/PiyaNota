# PIYA-127 - Recapture prompt & page replacement (FR-24)

Ticket ID: **PIYA-127** (raised 2026-09-26; next number after PIYA-126 in `module1-pipeline.md`).
Related: PIYA-116 (Resubmit Failed Page API - already specifies replace-one-page-and-new-jobId; this ticket
adds the pipeline reason codes, the checklist screen and the page-id rules it depends on), PIYA-105 #4/#7,
PIYA-108 #5, PIYA-120, PIYA-207 (Processing Status screen).
Split out of BUG-001, which is signed off. Modules: 1 (reason codes), 3 (API/job state), 2 (app UI).
Bug-tracker entry: BUG-018.

## Problem

`docs/sow.md` FR-24 needs the app to prompt the user to retake a photo the pipeline cannot use.
Today the pipeline does not give the API anything to act on:

- A page with zero staff boxes prints a warning and is silently skipped (`stage2_detection.py`,
  `len(boxes) == 0 -> continue`).
- A staff count not divisible by 4 raises a plain `ValueError` with the reason only in the message text.
- A missing voice raises a plain `ValueError` in Stage 4.
- `docs/tickets/module1-pipeline.md` already specifies `failure_reason = "no_staff_detected"` and
  `"incomplete_voice_sequence"` (with `page_index` / missing voice) but neither exists in code.

## Scope

1. **Structured failures (Module 1).** Replace the bare errors with one exception type carrying
   `reason` (`no_staff_detected`, `unsupported_staff_layout`, `incomplete_voice_sequence`),
   `page_index`, and detail (staff count, missing voice). A zero-box page must raise, not skip.
   Distinct reason codes so they can be triaged separately (PIYA-410).
2. **Job state (Module 3).** Job goes to `failed` (or a `needs_recapture` state - decide with
   backend-lead) with that reason and the page id, so the client can show the prompt.
3. **Recapture screen (Module 2).** Shown when the reason is a recapture reason. Checklist for the user:
   - Hold the phone steady, or fix it in one position.
   - Use good, even lighting; avoid shadows across the page.
   - Shoot at eye level with the page facing the camera, not from above a table with the page lying flat
     at a steep angle.
   - Keep the whole page in view with nothing blocking it (hands, objects, page edges cut off).
4. **Page identity on retake.** A retaken photo replaces the failed page in place:
   - Each uploaded page has a stable page id and a fixed position (`page_index`) in the piece.
   - A retake gets a NEW image id but keeps the replaced page's `page_index`, so the numbering and
     order of the other pages never change.
   - The failed image is marked superseded (kept for triage, excluded from the pipeline).
   - Only the replaced page is re-run through Stages 1-2 and Stage 3; Stage 4 then rebuilds the piece.

## Acceptance criteria (draft - confirm before implementing)

- [ ] Zero-box page, non-multiple-of-4 page and missing voice each surface a structured reason with
      `page_index`; none is silent.
- [ ] The API returns that reason and page id to the client.
- [ ] The recapture screen shows the four checklist items above.
- [ ] After a retake, page order and `page_index` values of all other pages are unchanged and the
      replaced page carries a new image id.
- [ ] The superseded image is not used in the output audio.
- [ ] Test: retake page 2 of a 3-page piece; pages 1 and 3 keep their ids/positions.

## Open questions

- Job state name and whether a partial (some pages good) job stays open while waiting for the retake.
- Whether a voice missing from only one system (currently silent in Stage 4) should also prompt.
- Owner review: backend-lead (API/job state), frontend-lead (screen).
