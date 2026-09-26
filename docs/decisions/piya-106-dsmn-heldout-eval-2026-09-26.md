# PIYA-106 Step 3/4 - DSMN real-photo evaluation and Stage 3/4/5 review (2026-09-26)

Branch `piya106/groundtruth-eval` (unmerged, unpushed). Raw evidence lives in `data/eval_dsmn/` (gitignored;
this file is the durable record). Evaluation by ml-cv-lead, code review by senior-reviewer.

## Scope and limits (read first)

- Set: 5 "Don't Stop Me Now" (DSMN) phone photos, open-score SATB, 4/4, key of 1 flat. CPU only.
- 24 strips annotated, p3s1 Tenor excluded, **23 scored (264 reference notes)**. Wide confidence intervals.
- Ground truth is **single-annotator (an agent), frozen before any CRNN run**. One of four cross-checked strips
  disagrees with `ground_truth/dont_stop_me_now` (p1s1 Alto bar 2, C4 vs D4). Diagnostic only, not accuracy evidence.
- DSMN was seen during Stage 1/2 mask tuning, so it is **not blind for Stage 1/2**.
- Audio rendering was NOT tested (pydub, fluidsynth, ffmpeg and a soundfont are absent). MIDI structure only.
- Both fine-tuned seeds are reported as a **range**; never average or pick the better one.

## Verdicts

| Question | Verdict |
|---|---|
| Stage 1/2 ready for Stage 3 | READY with caveats: 12 staves/page x5 pages, 60 strips, ~20 s/page; residual curl at p3s2 Alto and p5s2 Soprano |
| Stage 3 | Passed except two defects, both now fixed (below) |
| Stage 4 | Correct on clean input; blind to clef errors |
| Stage 5 | MIDI structure passes (4 voices, equal length); hanging note-on defect now fixed |
| CRNN accuracy | **FAIL** on the SOW thresholds; BUG-011 is not fixed |

## CRNN on 23 DSMN strips (range across seeds)

| Metric | seed 1 | seed 2 | base CRNN |
|---|---|---|---|
| Token SER, corpus [95% CI] | 44.3% [36.1, 55.3] | 47.9% [38.8, 59.3] | 70.9% [60.9, 83.6] |
| Token SER, mean per strip | 52.4% | 57.1% | 81.9% |
| Event SER (full) | 81.8% | 80.6% | 95.1% |
| Pitch accuracy (SOW) [CI] | 11.4% [3.2, 22.9] | 10.6% [1.0, 23.1] | 12.5% [3.8, 22.6] |
| Pitch accuracy (strict) | 8.0% | 9.1% | 7.6% |
| Clef correct | 2/23 | 3/23 | 1/23 |
| Predominant clef output | clef.C-L1 (21/23) | clef.C-L1 | clef.C-L3 (22/23) |
| Pitch with GT clef substituted (diagnostic only) | 87.5% | 86.4% | 72.7% |

- Clef confidence is uninformative (AUROC 0.64; mean 0.71 when wrong vs 0.74 when right).
- Silent-clef signature: a constant semitone offset per strip (Bass +17, Tenor +9) on 11 strips (seed 1) and 10 (seed 2).
- Length bias hyp/ref 1.32; 30% of strips have SER > 0.5.
- The fine-tune helps token SER versus the base model but does not fix the clef, which is the dominant pitch error.

## SOW criteria

| Criterion | Result |
|---|---|
| SER <= 15% | FAIL (44.3-47.9%) |
| Pitch accuracy >= 85% | FAIL (10.6-11.4%) |
| <= 2 min/page | Consistent with PASS (34-36 s/page on CPU, MIDI only) |
| No Camera-PrIMuS regression | PASS with caveat (below) |

Camera-PrIMuS regression (300 samples, seed 42): clean 1.87% for both seeds vs 2.03% base; distorted 4.40% / 4.46%
vs 15.46% base. Overlap between the CPM samples and the fine-tune data is unverified.

## Defects found and fixed (commits `1f237de`, `4021323`)

1. Stage 3: a dot multiplied duration but did not advance the tick cursor, causing overlapping notes.
2. Stage 3: a `slur.end` in the header before the first note was silently dropped.
3. Stage 5: same-pitch overlaps left more note-ons than note-offs (hanging note); now clipped with a warning.

13 regression tests: `tests/test_stage3_5_regressions.py`.

## Senior-reviewer findings still open (rework NOT ready for main)

High:
- Clef misreads stay silent in Stage 4 (same class as BUG-002). Swapping every ground-truth clef leaves flags
  identical (Bass mean pitch 47.9 -> 64.9, no new flag). `tenor_range_suspect` false-positives on correct ground truth.
- `run_full_pipeline` discards the Stage 4 report, so flags never reach the FR-14 error states.

Other:
- Double dots wrong (second dot gives 2.25x, not 1.75x; `int()` truncates); no tests for double dots, chord-tail
  dots or dots after a barline; `dot_pending` is dead code.
- The cross-system tie test does not pin the Stage 3 fix, since Stage 4 never needed the end marker.
- Stage 5 warnings are unstructured; `_render_to_mp3` has `except Exception` that returns a `.mid` as if it were success.
- A voice missing from one system raises nothing and sets no flag (see PIYA-127 open questions).
- Overflow repair can hide a wrong barline read; Stage 4 thresholds are hand-set with no held-out validation.
- Stage 4 flags saturate on CRNN input, so they carry little signal.

## Tie preservation (36 GT ties; measures the CRNN, not the mask)

Predicted `slur.start`: seed 1 16 (11 count-matched), seed 2 17 (13), base 32 (18). New-code recall over
detector-found ties is not sufficient evidence; a paired old-vs-new comparison against independent GT ties is needed.

## Open decisions and follow-ups

- Wire Stage 4 flags plus a clef-unsure signal into `run_full_pipeline` / FR-14 before any merge (recommended).
- Whether a voice missing from one system should raise as an FR-24 recapture (PIYA-127).
- Checkpoint metadata mismatch, unresolved: seed 1 file says epoch 2 / 0.0926 vs the decision doc's epoch 1 / 0.0523;
  seed 2 file says epoch 2 / 0.0562 vs 0.0886. Which is authoritative must be settled before quoting either.
- Second annotator for the DSMN ground truth.
- Fix double dots and the dead code; tighten the tie test.
- The clef needs real-engraving training data (BUG-011 / PIYA-106 AC4); do not treat the seeds as a fix.
- Keep DSMN and Both Sides Now held out from any threshold tuning from here on.
