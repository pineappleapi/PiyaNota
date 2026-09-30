# PIYA-106 - Plan to reach token SER below 15% (2026-09-29)

**Status:** plan plus Phase 0 implemented on branch `piya106/ser15-header-rule` (not merged). ml-cv-lead review of
this plan is pending. All numbers below are on **eval_prelim, which is dev data**: the user decided on 2026-09-28
that tuning on it is allowed, but no held-out claim can come from it. The thesis SER claim can only come from the
Phase 4 pre-registered held-out set.

**Target, quoted from PIYA-106 AC1:** "Achieves Symbol Error Rate (SER) ≤ 15% against ground-truth annotated
Filipino SATB test sequences." The thesis applies it to camera input. The metric stays as defined (SOW token SER on
agnostic tokens, slurs/ties excluded). Nothing here redefines it.

## 1. Where we are (dev data, both seeds as a range)

The numbers come from the official scorer on the stored Stage 3 replays, with 0 greedy mismatches against the
stored tokens.
- **Camera pool:** Non Nobis, Gaano, Honneur, Handog and Don't Stop Me Now.
- **Digital pool:** Non Nobis and Gaano.

This camera pool is wider than the 2-piece table in `NEXT-SESSION.md`, which is why its baseline is slightly higher.

| Variant | Camera SER | Camera pitch | Digital SER | Digital pitch |
|---|---|---|---|---|
| Baseline (pipeline as merged, `19cd627`) | 34.50-36.24% | 85.23-85.27% | 24.99-25.53% | 89.58-89.98% |
| E1a: drop time signature before first barline, continuation systems | 27.70-30.09% | - | 17.98-19.90% | - |
| E1b: E1a + pre-body fermata + multirest | 25.88-27.60% | ~85.1-85.2% | 15.31-15.60% | 89.68-90.18% |
| E1c prototype: E1b with choral-conductor's quorum conditions | 26.79-28.26% | 85.16% | 16.20-16.44% | 89.78-90.18% |
| **Implemented (E1c + system-wide meter change, see §3)** | **26.83-28.43%** | 85.16% | **16.30-16.54%** | 89.78-90.18% |
| E2: two-seed logit ensemble (one system) | 34.09% | - | 24.40% | - |
| E2 + E1b | 26.02% | 84.84% | 15.11% | - |
| Conservative: drop meter only if equal to running meter | 27.95-31.54% | - | 16.49-17.88% | - |

- **E2 ensembling is not worth its cost:** double inference for about 0.5 pp.
- **The conservative rule fails:** the CRNN invents *different* meters, so it kept 69-116 false "changes".
- **E1c costs about 1 pp against E1b.** That is the price of never deleting a real multirest or a real meter change
  (see §3).
- **Its quorum kept 5-7 meter "changes" per condition. All are false** (the dev GT has none), and all are flagged
  for review.
- **Pitch doesn't move.** Stage 4 already inherited the running meter when a strip has none, so dropping a
  hallucinated meter mostly removes wrong bar lengths.

**What is left to cut:**
- **Camera needs about -12 pp more.**
- **Digital needs about -1.5 pp.**

## 2. Critical diagnosis: what we were missing

We had been treating the gap as "fine-tune the CRNN harder on fonts". Looking at the error from scratch points to
five things. None of them is a font:

1. **The CRNN has never seen a continuation system.**
   - Every Camera-PrIMuS sample is an incipit that opens with clef, key and time signature.
   - Every SATB system after the first has no time signature, but the CRNN writes one anyway, often with a fermata
     or multirest.
   - The dev GT has zero such tokens before the first barline on 207 continuation strips (5,284 GT tokens).
   - This one layout prior was about 8-9 pp of SER. Phase 0 removes it by rule. Phase 1 data removes it at the
     source.
2. **The base model saw 4% of PrIMuS.**
   - It was trained on 3,596 of the ~87k PrIMuS incipits (R1 in
     `piya-106-accuracy-diagnosis-and-reference-comparison.md`).
   - Published end-to-end OMR that reaches low SER trains on the full corpus or on large synthetic sets.
   - A 4% sample is a very plausible cause of weak note/rhythm reading. It is also a cheap lever: the data exists,
     since the Kaggle `umerellous/primus` copy is already referenced in notebook cell 6.
3. **Training strips and inference strips are cut differently.**
   - CPM crops are single-staff incipits with CPM margins.
   - Ours come out of Stage 1/2: masked, dewarped, full-width, a different bracket or left edge, and about 2× longer.
   - BUG-016 names this. It was never fixed at the source, i.e. by training on strips cut by our own Stage 1/2.
4. **Camera-specific rhythm-glyph errors are about 7× the digital ones.** After E1b, measured on raw Levenshtein
   alignment:

   | Error | Camera | Digital |
   |---|---|---|
   | Duration substitutions | 548 (mostly quarter→`beamedRight1`, eighth rest→sixteenth) | 76 |
   | Inserted dots | 241 | 36 |
   | Inserted notes | 514 | 303 |

   - Notes are 16.4 pp of camera SER and 12.1 pp of digital.
   - A side-by-side (`cmp_alto.png`) shows specks and a leftover margin mark on the camera strip.
   - CPM's synthetic distortion doesn't look like our phone photos after Stage 1.
5. **The two approaches already written up were never executed.** Neither was AC4's real-data fine-tune.
   - The 2026-09-26 diagnosis proposed A4 (layout-realistic Verovio synthetic data with replay) and A5 (rendered
     SATB corpus plus print-and-photograph).
   - AC4 requires a fine-tune "on the Filipino SATB dataset before production use".
   - The dev pieces are allowed for tuning, and they are exactly that data. However, only Non Nobis GT is
     user-verified. Gaano, Honneur and Handog GT are agent-made (diagnostic only), and Don't Stop Me Now's GT status
     is not on record. The user must verify GT before a piece is used as training labels.

**Things checked and not blamed:**
- **Scale.** Staff height at the 64 px input is 30.5 px on camera and 31.25 px on digital, against CPM's 34 px.
  Margins are similar.
- **Strip length.** E3 cut strips into CPM-sized chunks and decoded each one. It made SER and pitch worse (§4),
  so the CRNN reads locally.
- **Decoding.** Plain beam search was a NO-GO (see `NEXT-SESSION.md`).

## 3. Phase 0 (done on this branch): header-zone filter in Stage 3

`stage3_transcription.filter_header_hallucinations` runs by default: `transcribe_voice_sequences(...,
header_filter=True)`. It needs all voices of a system at once, so Stage 3 now decodes every strip first and then
runs pitch inference.

It follows the choral-conductor review of 2026-09-29, with the rules scoped as follows:
- **First system of the piece** (first page, system 1): untouched.
- **Time signature:** `digit.*` / `metersign.*` before the first barline is dropped, except multirest digits. It is
  kept only if at least 3 voices of the system carry the same group and it differs from the voice's running meter.
  A kept change is flagged `header_meter_change_kept` / `review_needed`, and the flag reaches the API review
  object through `stage5_synthesis.build_review`. The code is new, so **backend-lead review is needed**.
- **Multirest:** it is dropped together with its digits (its bar count) when fewer than 3 voices of the system have
  one. A real multirest is in every voice at once.
- **Fermata:** dropped only before the first note/rest of the strip.

**System-wide change (choral-conductor follow-up review, 2026-09-29).** When at least 3 voices accept a meter
change:
- every voice's running meter moves to it;
- every strip of the system is flagged, so a voice that misread or missed the change is visible to the reviewer
  and is not flagged one system late;
- a dissenting group is dropped.

**Dev result.** Before this change, the pipeline function matched the E1c prototype on all 656 stored dev strips.
After it, 27 strips differ, and SER is 0.04-0.17 pp higher (table in §1). These are phantom quorum changes where a
voice that already held the meter keeps its restated time signature.

**Tests:** `tests/test_stage3_header_filter.py`.

**Deferred (choral-conductor change 2).** Stage 3 emits a fermata token *before* its note, so a real fermata on a
system's first note is dropped too. No stage plays fermatas yet. Before fermata playback exists, keep a header
fermata when at least 3 voices have one directly followed by a note.

**Limits:**
- The vocabulary has no double-barline token, so "a change after a double barline is real" can't be checked.
- choral-conductor would rather confirm a meter change by structural evidence: bar sums, or a courtesy meter at the
  end of the previous system. Voice agreement alone is a weaker proxy, because the CRNN also agrees with itself on
  phantoms. That is why it is flagged, not trusted.

## 4. Other no-training experiments (dev data, diagnostic)

- **E3, chunked decoding: NO-GO.**
  - Method: cut each strip at its own CRNN barlines into CPM-sized chunks (≤ 560 or ≤ 800 px at height 64), paste
    the strip's header in front of every later chunk, and drop the tokens decoded inside the pasted header.
  - It is worse than full-strip decoding in every cell:

    | Rule | Condition | Full strip | Chunked 800 | Chunked 560 |
    |---|---|---|---|---|
    | E1b | Camera | 25.88-27.60% | 26.77-28.24% | 27.74-29.36% |
    | E1b | Digital | 15.31-15.60% | 15.65-15.85% | 16.49-16.94% |

  - Pitch drops 1-3 pp.
  - Strip length is not a lever: the CRNN reads locally, and chunk seams add errors.
- **E4, speck filter: small gain, not adopted yet.**
  - Method: whiten 8-connected ink components of at most A px at CRNN input scale, then decode greedy, applying
    the E1b rule.

    | A (px) | Camera SER | Digital SER |
    |---|---|---|
    | 0 | 25.88-27.60% | 15.31-15.60% |
    | 2 | 25.42-26.79% | 15.31-15.65% |
    | 4 | 25.32-26.71% | 15.56-15.70% |
    | 6 | 26.19-27.24% | 15.16-15.51% |
    | 9 | 27.78-28.78% | 17.23-17.48% |

  - Pitch is unchanged within ±0.3 pp.
  - Camera gains 0.5-0.9 pp at A = 2-4. Digital is neutral, and A = 9 hurts both, because it erases dots and
    thin glyph parts.
  - The threshold was picked on dev, so the gain is optimistic. Specks explain only a small part of the camera
    dot and rhythm errors. Per ml-cv-lead, the stroke and binarisation ablations come next.
  - A = 3 in Stage 1/2 is a candidate once those ablations are in. Phase 1 augmentation should add specks
    either way.
- **E5, stroke thickness at CRNN input: the largest lever found so far (2026-09-29).**
  - Method: apply one variant to each stored 64 px strip, then greedy decode, E1b, and the official
    `score_strip`. `thinN` = 4x cubic upsample, 3x3 dilate N times (ink is dark, so this thins it by about
    0.25 px per side per iteration at 64 px), INTER_AREA down. The base re-decode matched the stored tokens on
    every strip. ClefKeyNet header info is taken from the stored records, so both arms have the same header
    input.

    | Variant | Camera SER | Camera pitch | Camera rhythm | Digital SER | Digital pitch |
    |---|---|---|---|---|---|
    | base | 25.88-27.60% | 85.1-85.2% | 81.4-82.5% | 15.31-15.60% | 89.7-90.2% |
    | thick1 | 40.91-44.85% | 74.9-75.6% | 58-62% | 16.99-17.38% | 88.8-89.5% |
    | thin1 | 18.45-18.78% | 90.2-90.4% | 91.2% | **14.07-14.72%** | 90.8-91.3% |
    | thin2 | **16.19-17.29%** | **91.6-92.1%** | **92.2-92.6%** | 16.10-16.64% | 91.2-91.6% |
    | thin3 | 21.34-23.51% | 89.7-89.8% | 87.4-88.3% | 21.09-24.40% | 89.6-90.2% |
    | re-binarise at 128 | 43.48-46.40% | 73.2-74.7% | 62-65% | 18.62-20.30% | 86.2-86.9% |
    | blur σ 0.7 | 23.18-24.88% | 86.1-86.3% | 83.2-83.8% | 14.77-14.86% | 90.7-91.7% |

  - thin2 helps every camera piece on both seeds (for example Don't Stop Me Now goes from 23.7-26.5% to
    10.1-11.8%).
  - Per class (camera, thin2 vs base): quarter-note recall goes from 68.5-69.7% to 93.7-95.7%, dotted quarter
    from 57-61% to 85-88%, and note precision from 69-70% to 72-73%.
  - **Direct measurement confirms the cause** (stroke width as a ratio to staff interline, at 64 px input,
    median):

    | Images | Staff line / interline | Stem / interline |
    |---|---|---|
    | CPM clean (training) | 0.127 | 0.127 |
    | CPM distorted (training) | 0.176 | 0.222 |
    | Ours, camera | **0.260** | 0.261 |
    | Ours, digital | **0.219** | 0.215 |
    | Ours, camera thin2 | 0.132 | 0.163 |
    | Ours, digital thin1 | 0.161 | 0.164 |

    Our Stage 1 binary strips are 1.5-2x thicker than anything the model trained on. The SER-best thin level
    (thin2 camera, thin1 digital) is the one that moves them into the CPM range.
  - **Still weak after thin2 (camera):** whole notes (72-77% end-to-end), half-note pitch given recognised
    (87-88%, a hollow notehead's staff position), dotted eighths (82-84% recall). On digital: naturals (35-51%
    recall, base) and half rests (56-67%). Sharp precision is 45-49% (phantom sharps, base).
  - Dev data, and the level was chosen on it, so the gain is optimistic. Scripts and JSON:
    `C:\Users\paul_\.claude\jobs\61611c36\tmp\` (`e5_stroke.py`, `e5b_thin.py`, `perclass.py`,
    `stroke_measure.py`).
- **ml-cv-lead review of E5 (2026-09-29): CONDITIONAL GO.**
  - Inference-time thinning is allowed only as a flagged, manifest-recorded dev/eval option. It is NOT the
    pipeline default and NOT the frozen Phase 4 system.
  - Pick the level from the stroke measurement (target the training median), never from SER. If SER must be
    used, use leave-one-piece-out, with the camera and digital copies of a piece in the same fold.
  - Fix order: (1) the measurement (done, above); (2) calibrate the Stage 1 strip-source binarisation (C, blur,
    block size) to the stroke statistics, which fixes the root cause; (3) add stroke-width erode/dilate
    augmentation in Phase 1/2 anyway; (4) inference thinning only as a stopgap, re-ablated after retraining.
  - Confounds still to report:
    - thin2 against the speck filter alone, with dot insertions and deletions reported separately;
    - body-only SER;
    - results with and without E1b;
    - per-piece paired deltas, not pooled SER.
- **SKIMusic baseline (DLSU thesis, `docs/references/`), read 2026-09-29.**
  - Its "90%" (Tables 3.3/3.4) is pitch accuracy *given the note was already recognised*, on ideal PDFs. The
    abstract's 77.62% is recognition only.
  - The honest end-to-end numbers (Table 3.5, weighted) are about 85.7% ideal and about 62.5% captured.
  - It scores 4 note durations only: no rests, accidentals, keys or clefs, and no penalty for insertions. It
    uses grade 1-2 piano with at most 2 staves, and the user crops the image and picks the staff removal.
  - Its Table 3.3/3.4 counts are copied from the captured Table 3.2 (463/544 = 85%, not the printed 94%).
  - On that same metric we measure digital 85.5-85.6% (base) / 90.2-90.3% (thin2), and camera 74.1-75.0% (base)
    / 89.6-90.4% (thin2). Different pieces, so not head-to-head.
  - What to adopt from it:
    - its binarisation-window lesson (the same failure as E5);
    - rule-based *verification* of CRNN output (beam ink, notehead/stem count, dot position, filled vs hollow
      notehead), in Phase 3;
    - bar-duration grammar;
    - app-side capture guidance and crop confirmation (Module 2).

## 5. The plan

The error budget sets the order. Camera must lose about 12 pp, and 16 pp of camera SER is note tokens, most of
them rhythm glyphs and insertions. No rule or decoder removes that. The model has to read notes better on
*our* strips, which means more data, the right layout, and our own cutting. Every step has a go/no-go gate.

### Phase 0b: strip-source calibration (before Phase 1; added 2026-09-29 after E5)

Per ml-cv-lead's E5 review, these run in order before any rendering. The Phase 1 corpus is cut with Stage 1/2,
so freezing Stage 1/2 before this step would bake the thick strokes into the training data.

1. **Sweep the Stage 1 strip-source binarisation** (`STRIP_SOURCE_THRESHOLD_C`, blur sigma, and block size if
   needed). Select by stroke statistics only. The target, fixed before any decoding, is a median staff-line and
   stem width of 0.15 x interline (the midpoint of the CPM clean and distorted medians) on camera and digital.
   The base setting must reproduce the stored eval_prelim strips byte-identically (parity check).
   **Sweep result (2026-09-29, dev data, stroke stats only, nothing decoded).** The base setting reproduced all
   388 stored strips byte-identically. Values are camera line/stem | digital line/stem; n is the number of
   strips measured (camera | digital).

   | C (sigma 0.4 x scale) | camera | digital | max \|dev\| | n |
   |---|---|---|---|---|
   | 10 (base) | 0.260 / 0.261 | 0.209 / 0.223 | 0.111 | 227 \| 160 |
   | 30 | 0.218 / 0.234 | 0.169 / 0.205 | 0.084 | 219 \| 160 |
   | 40 | 0.202 / 0.217 | 0.155 / 0.184 | 0.067 | 217 \| 160 |
   | 50 | 0.183 / 0.205 | 0.127 / 0.177 | 0.055 | 213 \| 156 |
   | 60 | 0.162 / 0.194 | 0.122 / 0.174 | 0.044 | 209 \| 137 |
   | 70 | 0.153 / 0.181 | 0.110 / 0.168 | 0.040 | 190 \| 130 |

   The values in between (C14-C26) are monotonic, and a blur sigma of 0.2 instead of 0.4 changes nothing.

   **Why strokes are thick.** A native run-length check on 5 pages shows staff lines 4-6 px thick on a staff
   pitch of about 20 px. That rules out a resolution floor. Mean-minus-C thresholding counts the blurred stroke
   edges as ink.

   **No single C fits all four cells.** C is an absolute grey offset, so camera and digital thin at different
   rates. Stems also thin much more slowly than staff lines. At C50, digital lines are already at the CPM-clean
   edge (0.127) while camera stems are still at 0.205.

   **Rule amendment (ml-cv-lead, recorded before any decode of C40-C70).** A strip whose staff lines break
   fails measurement, so at high C the medians come only from surviving, thicker strips. The minimax objective
   stands, with one validity guard added: settings with real digital erosion are excluded. That removes C60
   (digital n 137/160) and C70 (130/160).

   **Lock.** C50 is the provisional lock, with C40 as the fallback, settled by a stroke-only visual audit:
   - (a) 1:1 tiles of the strips that measure at C10 but fail at C50. If most of them show broken or eroded
     staff lines, fall back to C40.
   - (b) About 20 strips chosen by a fixed rule before viewing: the first strips in manifest order whose
     ground truth has augmentation dots, ties, ledger-line notes or half/whole notes. Compare C40 and C50
     side by side. If any dot, tie, ledger line or hollow notehead is broken or missing at C50 but not at C40,
     fall back to C40.

   **Audit outcome (2026-09-30, visual, done before any C40/C50 decode): locked C40.**

   *Failed at C50 (18 strips: 14 camera, 4 digital).*
   - The camera failures are 12 Honneur p2-3 strips, 1 Handog p14 strip and 1 Don't Stop Me Now p3 strip.
   - The digital failures are all Don't Stop Me Now digital. That piece is not in the E5 scoring combos, which
     is why the sweep's digital n was 156, not 160.
   - Most failures are real erosion, not a quirk of the peak finder: staff lines break into dashes, key
     signature flats erode, hollow noteheads open.
   - So rule (a) sends the lock to C40.

   *Feature sample (20 strips, fixed rule, strips already picked skipped).*
   - Good-contrast camera pages and all digital strips are clean at both C40 and C50.
   - On the low-contrast pages, some features are worse at C50 than C40 (e.g. Handog key signature flats).

   *Caveat, which matters more than the C40/C50 choice.*
   - On low-contrast camera pages (Honneur p2-3, Handog p14), C40 already breaks staff lines and opens hollow
     heads, while C10 fuses the lines into over-fat bands.
   - No absolute C is both thin enough and unbroken there. That is direct evidence for a contrast-relative
     threshold or grey input (E7), not a better C.

   *Stage 2 parity.* The page manifests (boxes, strip ids) are identical at C10 and C40 (42/42).

   No later SER result may reopen the choice of C. Any retune after decoding needs leave-one-piece-out.

   **Deviation log.** Audit rule (b) gained "skip strips already picked" after the strip list was printed and
   before any tile was viewed (2026-09-30). It is a de-duplication rule and depends on no pixel content or
   outcome. ml-cv-lead accepted it.

   ~~**Deferred.** A contrast-relative (FWHM-style) threshold is built only if the binary source wins step 5.~~
   Superseded by ml-cv-lead's 2026-09-30 review. The contrast-relative threshold is the only binary candidate
   still standing, so it becomes a step-5 arm in its own right, pre-registered in step 4b below.
2. **Decode the one locked setting** against base and inference thin2/thin1. This is diagnostic only, with the
   E5 confound reporting above.
   - Also decode the lock plus inference thin1, as a diagnostic arm only: a big extra gain means the
     calibration is incomplete.
   - Checks:
     - Stage 2 boxes must be byte-identical to base.
     - Header and ClefKeyNet come from the stored records, and body-only SER is the primary metric.
     - Every strip is decoded, with measured and measurement-failed strips reported separately.
   - Reporting also covers:
     - per-class recall for quarter, dotted, half/whole (hollow) and ledger-line notes and for naturals, plus
       sharp precision;
     - each arm's stroke medians next to its SER.

   **Result (2026-09-30, C40 locked, dev data, diagnostic only; ranges are seed1-seed2).** Base-mismatch was 0,
   no strips were missing, and Stage 2 parity held. Header and ClefKeyNet came from the stored records.

   | camera | SER | body-only SER | pitch | dot ins/del | line / stem |
   |---|---|---|---|---|---|
   | base | 25.9-27.6% | 30.6-32.8% | 85.1-85.2% | 104-137 / 13-16 | 0.260 / 0.261 |
   | inference thin1 | 18.5-18.8% | 23.1-23.7% | 90.2-90.4% | 86-129 / 11-14 | 0.196 / 0.198 |
   | inference thin2 | 16.2-17.3% | 21.2-22.7% | 91.6-92.1% | 71-123 / 15-21 | 0.132 / 0.163 |
   | **C40** | 19.4-20.3% | 24.5-25.6% | 87.9% | 45-67 / 14-15 | 0.202 / 0.216 |
   | C40 + thin1 (diagnostic only) | 17.8-19.2% | 23.0-24.5% | 89.5-90.3% | 58-102 / 12 | 0.147 / 0.162 |

   - **Camera, split by whether the strip survives C40.**
     - On the 11 strips that fail measurement at C40 (Honneur low contrast), C40 scores 70.7-71.0% SER. That is
       worse than base (62.5-65.3%) and far worse than thin2 (30.0-30.9%).
     - On the intact strips, C40 scores 15.8-16.7% against thin2's 15.2-16.3% and thin1's 16.8-17.3%.
     - ~~So the whole C40-vs-thin2 gap is the eroded low-contrast strips.~~ **Biased (ml-cv-lead).** "Fails at
       C40" is caused by C40, so this split favours C40 and the claim is partly circular. It will be re-cut
       by page contrast measured before thresholding (step 4b covariate), with measurability at C10 as a
       second cut.
     - ~~At a similar width, threshold thinning slightly beats morphology (C40 vs thin1).~~ Not resolvable: the
       difference is inside the 1-2 pp seed range.
     - All 11 are Honneur strips, and Honneur is hard at base, so contrast and piece are fully confounded.
       Handog p14 and Don't Stop Me Now camera p3 are the only partial de-confounders.
   - **Camera per piece (SER change vs base).**
     - C40 gains 5-14 pp on Non Nobis, Gaano, Handog and Don't Stop Me Now.
     - On Honneur it loses 3.0-3.8 pp, where thin2 gains 7.6-9.7 pp.
   - **Camera per class, base -> C40 (thin2 in brackets).**
     - quarter 68.5-69.7% -> 86.0-86.4% (93.7-95.7%)
     - dotted quarter 57-61% -> 79% (85-88%)
     - dotted eighth 81-82% -> 73-75%, a loss consistent with eroded dots and flags
     - half/whole 75-77% -> 88% (93-94%)
     - ledger notes 64-66% -> 71-72% (62-69%)
     - naturals 32-50% under every arm, so naturals are not a stroke problem
     - sharp precision 46-49% -> 50-61% (65-73%)
   - **Digital.**
     - C40 is about the same as base: 15.6-15.9% vs 15.3-15.6%.
     - thin1 is still best at 14.1-14.7%.
     - thin2 over-thins, with digital line/interline at 0.103.
     - Digital per-piece changes are within +/-2 pp.
   - ~~**Calibration is incomplete.** C40 + thin1 still gains about 1-1.5 pp on camera.~~ Unconfirmed: the gain
     is at or below seed resolution.
   - Dot insertions fell while dotted-eighth recall also fell. That is the usual precision/recall trade-off of
     erosion, not a pure gain. Future arms report dot insertions per dotted reference token.
   - **Conclusion.** A global absolute C cannot be frozen. It works wherever contrast is adequate and destroys
     low-contrast photos, which is the failure mode real choir photos will hit. The strip source has to adapt
     to local contrast, or be grey (E7).

   **ml-cv-lead review (2026-09-30): step 2 CLOSED, NEGATIVE for an absolute global C.**
   - C40 stays in the record as the answer to "best absolute C". It is not frozen into Stage 1.
   - **Positive finding.** Where contrast is adequate, bringing stroke width at the source down toward about
     0.15-0.20 interline is the lever: C40 on intact strips roughly equals thin2. This justifies building an
     adaptive source.
   - **Next order:** E6 → E7 (grey) → contrast-relative threshold.
     - The threshold is not pulled ahead of E7. It has a free k, and E7 has none.
     - Calibrating k first would give the binary arm a tuning advantage.
   - **Dev-set exhaustion.** eval_prelim has now informed E1b, E4, E5, the thinning arms and C. Its absolute
     SERs are optimistic, and only arm-vs-arm deltas mean anything. Only the fresh held-out photos can say
     whether <15% is met.
   - **Long-term cost.** Every step in Phase 0b is a preprocessing patch toward CPM's stroke statistics. The
     durable fix is Phase 1/2 training data covering low contrast and broken strokes. Prefer the source that
     loses the least information (probably grey, if E7 is competitive).
   - BUG-011's confidently-wrong problem is untouched by any of this.
3. **E6:** push CPM images through our binarisation and confirm that SER degrades (the reverse causal test).
   It is cheap, has no free parameters, and runs in parallel.
   - Use the Stage 1 strip-source binariser at C10 and C40.
   - Use only CPM samples that neither the base nor the fine-tuned models trained on. If none exist, report
     relative deltas only and note that the baseline is inflated.
   - Measure stroke width on the outputs with the same peak finder. This also checks the 0.15 target through
     our pipeline.
   - After Phase 2, E6 at the final strip source becomes a canary.

   **E6 result (2026-09-30, diagnostic).** Setup:
   - 399 canary stems, excluded from fine-tuning. The base model may have seen some of them, so only
     relative deltas count.
   - Stage 1's background, block and blur constants were converted to interline units from 25 cached camera
     pages: background ≈ 11.2, block ≈ 3.9, σ ≈ 0.05 interline.
   - Page geometry steps (perspective, dewarp, border blank, lyric mask) were skipped.
   - Only 189 of 399 distorted images had a measurable interline; the rest use the median ratio.

   | CPM | raw SER | C10 SER | C40 SER | line / stem: raw → C10 → C40 |
   |---|---|---|---|---|
   | clean | 2.59-2.69% | 3.52-3.93% | 2.67-2.73% | 0.128/0.128 → 0.239/0.166 → 0.166/0.166 |
   | distorted | 5.73-5.83% | 22.13-23.76% | 13.66-14.14% | 0.176/0.202 → 0.277/0.250 → 0.222/0.218 |

   - The reverse causal test holds. Our current binariser alone fattens CPM strokes into our camera-strip
     regime (0.26-0.28), and on camera-like CPM it multiplies SER about 4×.
   - C40 recovers only about half of that on distorted CPM (still 2.4× raw). A fixed offset loses information
     that grey keeps.
   - This supports E7 (grey) as the prime candidate. It is not a decision: E7 and 4b still run as registered.
   - Caveat: the distorted interline fallback affects the transform scale for 210 of 399 images.

   **ml-cv-lead's reading (2026-09-30).**
   - "Our binariser degrades camera-like input" holds.
   - "Fixed offset destroys information" is not isolated. Raw CPM is in-distribution by construction, so E6
     cannot separate that from "any binarisation hurts degraded input". Clean C40 roughly equals raw, so the
     damage is specific to degraded input.
   - The background kernel (about 11.2 interlines) is probably taller than a CPM incipit (8-9 interlines), so
     border handling may dominate the normalisation. The operator is not identical to the page case.
   - Width is not the whole story. Distorted C40 lines (0.22) are close to raw (0.18), yet SER is 2.4×, so the
     rest is breakage or speckle.
   - The order is unchanged: E7 then 4b.
   - Optional, no free parameter: 4b's form at a fixed k = 0.5 on the distorted stems. It must not feed the
     choice of k.
   - **Interline-fallback re-cut (post hoc, no new decode): the caveat closes.** Distorted SER, measured
     interline (189) / fallback (210):

     | arm | measured | fallback |
     |---|---|---|
     | raw | 4.8-4.9% | 6.4-6.8% |
     | C10 | 23.8-26.0% | 20.7-21.8% |
     | C40 | 12.8-13.7% | 14.4-14.5% |

     The degradation holds in both subsets.
   - E6's raw CPM widths and E7's ink-mass widths use the same `stroke_stats.measure`. On that like-for-like
     measure, E7 camera strips (0.215/0.226) are still fatter than distorted CPM (0.176/0.202).
4. **E7:** grayscale `strip_gray` input. The re-binarise-at-128 result suggests the model wants grey edges.
   - Measure the grey strips' stroke width (half-max) before decoding.
   - Keep the non-staff-ink mask: masked pixels are set to paper. Otherwise E7 changes two variables at once.
   - The mask creates hard edges inside a soft image. Report SER separately for strips with heavy masked area.

   **E7 fixed rules (recorded 2026-09-30, before any E7 strip was viewed or decoded).**
   - **Source.** The grey page is Stage 1's normalised, blurred, dewarped native gray (the fourth return of
     `_build_strip_source`, at C10), with no contrast stretch.
     - It is set to paper (255) on the border-blank region.
     - It is also set to paper on the C10 non-staff mask, dilated by ⌈2σ⌉ px, where σ is the page's strip-source
       blur, so the erased lyrics' blur halo goes too.
     - Stage 2 runs unchanged, so its boxes must match the C10 manifests.
   - **Stroke measure.**
     - Raw ink-mass `measure()` on the grey strip.
     - Also half-max width: `measure()` after thresholding each strip at (paper + ink)/2, where paper is the
       strip's median and ink its 1st percentile.
   - **Heavy mask.** Report SER by quartile of the per-strip masked fraction; Q4 counts as heavy.
   - **Contrast covariate.** Page contrast is the median over tracked staves of (p90 − p2) of the normalised
     grey in the staff band (centre ± 2 spacings), measured before any threshold.
     - Low-contrast pages are those below 0.75 × the median camera-page contrast. The pages are named when the
       covariate is computed, before decoding.
     - This covariate re-cuts the C40 split (ml-cv-lead) and defines 4b's low-contrast cell.
   - **Decode.** Same path as step 2 (`cal_decode`), one decode, both seeds.

   **E7 pre-decode checks (2026-09-30).**
   - **Stage 2 parity.** The page manifests are identical to C10 (42/42).
   - **E7 stroke widths.** Median line/stem per interline:

     | E7 strips | ink-mass | half-max |
     |---|---|---|
     | camera | 0.215 / 0.226 (n 191) | 0.143 / 0.250 (n 193) |
     | digital | 0.109 / 0.173 (n 103) | 0.125 / 0.125 (n 41) |

     The peak finder often fails on grey strips, so these are rough.
   - **The pre-registered contrast covariate FAILED: it names no page.**
     - The camera median is 202.5 and the cutoff 151.9. The lowest page is Non Nobis p2 at 154.0.
     - Honneur p1-3 are at 202.5-207.5, around the median. Handog p14 is at 178.5; Don't Stop Me Now p3 at 214.5.
     - So, measured as the band p90 − p2 on the background-normalised grey, "low contrast" does not describe
       the pages that break at C40.
     - A likely reason: p2 is set by solid noteheads, while what breaks is thin, faint staff lines and
       strokes. That suggestion is post hoc.
   - **Consequences.**
     - The C40 re-cut and 4b's low-contrast cell are on hold pending ml-cv-lead's choice of a replacement
       covariate. Nothing is redefined silently.
     - The earlier "low-contrast pages" wording in step 1-2 was a visual description; this measure does not
       confirm it.

   **ml-cv-lead ruling (2026-09-30), recorded before any of the following was computed.**
   - **No second covariate.** Any definition registered now would be shaped by already knowing which pages it
     has to name.
   - **"Low contrast" is withdrawn.** Whatever breaks Honneur is not overall page contrast (Honneur sits at
     the camera median). The mechanism is unconfirmed; candidates are faint or thin line print, print weight,
     and illumination residue. Resolution is a weak candidate.
   - **Fragile pages, the gating definition.** "C50-fragile camera pages" = every camera page with at least
     one strip that measured at C10 and failed measurement at C50 in audit (a). That audit was visual,
     stroke-only and done before any decode.
     - The rule gives Honneur p2, Honneur p3, Handog p14 and Don't Stop Me Now camera p3.
     - These pages were chosen by fragility under the same binariser family, so any 4b gain on them is
       in-sample for the choice of k.
   - **C40 re-cut, and every later arm (E7, 4b):**
     - primary: camera strips on the fragile pages vs all other camera strips;
     - secondary: C10-measurable vs C10-unmeasurable;
     - also Honneur vs non-Honneur. Piece and fragility remain confounded; only Handog p14 and Don't Stop Me Now
       p3 partly separate them.
   - **Exploratory panel, descriptive only.** It never defines a cell, selects k or splits a result. Its only
     uses are reading the mechanism and choosing Phase 1 augmentation targets. Per strip, with no cutoff:
     - native interline in px;
     - C10 line/interline;
     - staff-line depth: median over tracked line rows of (local paper grey − minimum grey across the line
       profile);
     - notehead depth: strip p1 depth;
     - line depth / notehead depth;
     - line FWHM in native px.
   - **Reading E7.**
     - Grey stroke widths are descriptive. They are not compared with the binary 0.15 target and are not used
       to explain SER.
     - Half-max is biased low on faint-line strips, because its ink level is the p1 of the noteheads.
     - The digital half-max comes from a survivor subset (41 strips) and is not reported as a cell median.
     - E7 changes two things at once: grey edges and an unstretched dynamic range. If E7 loses, dynamic range
       is an uncontrolled explanation. No stretch is added unless it is registered first.
     - Deltas inside 1-2 pp are unresolved.

   **E7 result (2026-09-30, one decode, dev data, diagnostic only; seed1-seed2).** Base-mismatch 0, no missing
   strips, same header path as step 2.

   | camera | SER | SER without E1b | body-only | pitch | dot ins/del | dotted 8th | sharp precision |
   |---|---|---|---|---|---|---|---|
   | base | 25.9-27.6% | 40.1-41.9% | 30.6-32.8% | 85.1-85.2% | 104-137 / 13-16 | 81-82% | 46-49% |
   | thin2 | 16.2-17.3% | 30.9-32.6% | 21.2-22.7% | 91.6-92.1% | 71-123 / 15-21 | 82-84% | 65-73% |
   | **E7 grey** | **15.8-16.4%** | **24.2-27.1%** | **20.1-21.1%** | 88.0-89.3% | **35-56 / 6-8** | **91.5%** | **79-83%** |
   | E7 + thin1 (diagnostic) | 15.3-16.0% | 25.3-27.2% | 19.9-20.6% | 88.8-90.2% | 34-63 / 8-12 | 88-90% | 78-84% |

   - **Dots and headers.**
     - Dot insertions per dotted reference token fall, and dotted-eighth recall rises, which rules out the
       erosion trade-off seen at C40.
     - E7 depends less on the E1b header rule: the gap between SER with and without E1b is 8-11 pp, against
       14 pp for the binary arms.
   - **Weaknesses.**
     - Pitch is 2.5-3.5 pp below thin2.
     - Naturals are 32-34% (the class is weak in every arm).
     - Ledger notes are 68-71%, the same as thin1 and C40.
   - **Digital.** E7 14.9-15.7% vs base 15.3-15.6% and thin1 14.1-14.7%, within noise.
   - **Pre-registered re-cuts (camera SER):**

     | cut | n | base | thin2 | E7 |
     |---|---|---|---|---|
     | C50-fragile pages | 39 | 30.2-32.3 | 18.3-18.5 | 15.6 |
     | other pages | 188 | 24.8-26.4 | 15.6-17.0 | 15.8-16.7 |
     | Honneur | 28 | 33.1-34.6 | 24.9-25.5 | 18.2-18.7 |
     | non-Honneur | 199 | 24.2-25.9 | 14.0-15.5 | 15.1-16.0 |
     | mask Q1 (least masked) | 57 | 27.2-28.3 | 15.0-15.4 | 11.5-12.1 |
     | mask Q2 | 57 | 26.0-27.2 | 16.4-17.0 | 15.0-16.3 |
     | mask Q3 | 56 | 27.1-30.5 | 18.5-20.1 | 19.2-19.6 |
     | mask Q4 (heavy) | 57 | 23.1-24.5 | 14.6-17.6 | 18.2-18.7 |

     - Only 1 camera strip is unmeasurable at C10, so the secondary cut carries no information.
     - The fragile-page gain is in-sample (see the ruling above).
     - Per piece, E7 beats thin2 on Handog and Honneur and loses on Don't Stop Me Now (12.8-14.3 vs
       10.1-11.8).
   - **Reading.**
     - Where binary thinning breaks (fragile pages, Honneur), grey is robust and is not worse elsewhere.
     - On other pages, E7 and thin2 are tied.
     - E7 degrades steadily with masked fraction, from best of all arms at Q1 to worse than thin2 at Q4. The
       mask's hard paper-fill edges look like E7's main remaining cost, as predicted.
     - Masked fraction may track lyric-heavy pieces, so this is a correlation, not an isolated cause.
     - A softer mask fill is a new variable and would need registering before any run.

   **C40 pre-registered re-cut (per-strip re-decode, 2026-09-30; camera SER, `cal` = C40).**

   | cut | n | thin2 | C40 | C40 + thin1 |
   |---|---|---|---|---|
   | fragile | 39 | 18.3-18.5 | **31.9-32.9** | 28.9-30.5 |
   | other | 188 | 15.6-17.0 | 16.1-17.0 | 14.9-16.2 |
   | Honneur | 28 | 24.9-25.5 | **36.9-37.6** | 36.6-38.3 |
   | non-Honneur | 199 | 14.0-15.5 | 15.2-16.2 | 13.3-14.6 |

   - On the fragile pages, C40 is worse than base (30.2-32.3%), and Honneur carries all of it.
   - On the other pages C40 ties thin2.
   - So the earlier C40 average hid a page-level break. This is consistent with the fragile-page definition, which
     was drawn from these pages and is in-sample. Grey (E7) has no such break (15.6 on fragile pages).

   **ml-cv-lead ruling on E7 (2026-09-30, post-results).**
   - **Step-5 source: grey (E7), chosen by tie-break, not as a measured win.** Dev headline SER is tied.
     - Tie-break, applied in order:
       - (a) destroy no information;
       - (b) no free parameters;
       - (c) match the model's training domain (E6: the CRNN is a grey model).
     - E7 passes all three. thin2 fails (a) and (b): thinning is banned in step 5 and was tuned on dev.
     - The step-5 criterion is the source we train and serve on; today's model's SER is secondary.
     - The dot, sharp-precision and E1b-dependence signals support the choice. They are in-sample.
     - The fragile-page gain is biased toward any non-binary arm, because those pages were selected for failing
       under binary. It is only "consistent with".
     - Record as "grey chosen by tie-break (a)-(c); headline SER tied on dev". Never as "E7 beats thin2".
     - Fresh held-out photos score only the final model on the frozen source. They are never used to re-choose the
       source.
   - **Frozen recipe:** C10-normalised, blurred, dewarped native grey; no contrast stretch; border 255; C10
     non-staff mask dilated by ⌈2σ⌉; mask fill decided by F1 below.
   - **4b: superseded by the tie-break, not run.**
     - A free-k binary arm cannot beat grey by more than dev resolution.
     - Its fragile cell is in-sample.
     - Its own registered failure mode applies.
     - It is revived only if grey is withdrawn by review; the registration then stands as written.
   - **F1, soft mask fill (registered before running; one arm, no sweep).**
     - `m_hard` = E7's dilated mask AND NOT C10 retained ink (staff plus connected ink).
     - `m_soft` = GaussianBlur(float(`m_hard`), σ = the page's strip-source σ), clipped to [0,1], then 0 on
       C10 retained ink.
     - `paper` = the strip's median grey.
     - out = (1 − `m_soft`)·grey + `m_soft`·`paper`. The border stays 255; everything else is as in E7.
     - No inpainting.
     - Checks: Stage 2 parity, one decode with both seeds, the same re-cuts and mask quartiles.
     - **Adopt only if all four hold on both seeds:**
       - Q4 SER at least 2 pp better than E7;
       - Q1 no more than 1 pp worse;
       - overall camera SER no more than 1 pp worse;
       - digital SER no more than 1 pp worse.
       - Otherwise keep the hard fill, and keep it on a tie.
     - Descriptive only, never used to change F1: the fraction of dilated-mask pixels that land on C10
       retained ink per quartile, and the piece make-up of each quartile.
     - Run F1 only if it is cheap; otherwise freeze the hard fill.
     - **F1 result (2026-09-30, one decode, dev data; seed1-seed2).**
       - Checks passed: Stage 2 parity 42/42, the same 388 strips as E7, base-mismatch 0.
       - As implemented, `paper` is applied per strip after Stage 2's resize.

       | camera SER | E7 | F1 | rule |
       |---|---|---|---|
       | mask Q4 | 18.2-18.7 | 16.3-16.6 | ≥ 2 pp better on both seeds: seed1 −1.6, seed2 −2.4, **fail** |
       | mask Q1 | 11.5-12.1 | 11.4-12.0 | pass |
       | overall | 15.8-16.4 | 15.6-15.6 | pass |
       | digital | 14.9-15.7 | 14.9-15.7 | pass |

       - Other results:
         - fragile 14.7-15.4;
         - Honneur 17.8-18.7;
         - pitch 88.7-89.7;
         - dot insertions 36-52.
       - **Decision by the registered rule: F1 is not adopted, and the hard fill is kept.**
       - F1 points the right way on Q4, but seed1 misses the 2 pp threshold. The rule was fixed before the run, so it
         is not re-read after the fact. Hard-fill edges are left for Phase 1 retraining to absorb, as ruled.
       - Descriptive `dil_on_retained_ink` is saved in `f1_strips.json` and not used.
   - **Pitch 3 pp below thin2: does not block the choice. Diagnosis is the first entry of step 6, from existing
     outputs:**
     - aligned-note count per arm, to rule out a denominator effect;
     - pitch errors split into position ±1, position ±2 or more, and alteration-only;
     - sharp and flat recall;
     - pitch by mask quartile.
     - Note (2026-09-30): the decode dumps keep only per-strip error counts, not hypothesis tokens. This needs one
       re-decode of the existing arms that saves hypotheses; it is not a tuning run.
     - It **blocks** if alteration-only errors rise under E7 with no link to mask quartile. That would mean faint
       accidentals are lost in grey, and step 5 goes back to review.
   - **ClefKeyNet stays on the unmasked binary crop, unchanged.**
     - Before the freeze, run the live pipeline on the dev pages with the grey source. Assert that the ClefKeyNet
       crops are byte-identical and its decisions identical. Every E7 decode used stored header records, so the
       live path has not been exercised.
     - Grey ClefKeyNet is a separate retrain plus fresh-validation ticket.
   - **Before step 5 is final:**
     - F1 decided;
     - live ClefKeyNet parity check;
     - pitch breakdown filed;
     - E6 re-run through the frozen grey path (raw CPM vs grey path, clean and distorted) as the canary baseline.
   - **Step-5 augmentation amendment (if grey is frozen).**
     - Retarget the "eroded/fused binariser regime" to grey artefacts:
       - faint lines (line depth / notehead depth);
       - blur;
       - low dynamic range;
       - illumination residue;
       - JPEG;
       - paper texture.
     - These are still applied to the page before Stage 1.
     - The dot/flag survival rule becomes a minimum-contrast rule: keep a dot only if its depth exceeds 3σ of paper
       noise; otherwise drop or relabel the sample.
     - The C10 binary mask still decides erasure (train = serve).
     - The thinning ban and the no-SER-matching rule stand.
   - **Open confounds:**
     - eval_prelim is exhausted, so absolute SERs are optimistic.
     - Piece is confounded with fragility (Honneur).
     - Mask quartiles are confounded with lyric-heavy pieces.
     - E7 changes edges and dynamic range together.
     - BUG-011's confidently-wrong problem is untouched.

   **4b. Contrast-relative threshold (pre-registered 2026-09-30, before any E7 decode; ml-cv-lead).**
   - **Form.** Per pixel, T = paper − k·(paper − ink), with dark if gray < T.
     - paper and ink are the local 90th and 10th grey percentiles in a window about 2 interlines wide,
       centred on the tracked staff band.
     - k = 0.5 is the FWHM definition.
   - **Contrast floor.** Where (paper − ink) is below the floor, fall back to C10, the fat-but-unbroken option.
     - The floor is 3σ of paper grey in blank paper regions. It is never set from SER.
   - **Sweep.** k ∈ {0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65}, blur sigma at base.
   - **Objective.** Minimise the maximum of |median − 0.15| over five cells:
     - camera line, camera stem, digital line, digital stem;
     - a fragile-page camera line cell. This is amended 2026-09-30, after the contrast covariate named no page;
       see the E7 pre-decode ruling.
   - **Fragile-page cell.** The cell value is the median line/interline over all measurable strips on the
     C50-fragile camera pages (Honneur p2-3, Handog p14, Don't Stop Me Now camera p3), not only the strips that
     failed.
     - ~~The low-contrast set, defined by page contrast, including any page below the cutoff.~~ That covariate
       failed and the cutoff no longer exists.
     - Expected failure mode, stated in advance: ink is a local p10, which noteheads pull toward their own
       depth. A staff line shallower than half the notehead depth is then erased at k = 0.5, just as at C40.
     - The contrast floor will not trigger on these pages. What protects them is this cell and its retention
       guard.
   - **Retention guard.** Exclude any k where:
     - measurable strips in camera, digital or the fragile pages fall below C10's count; or
     - the digital count falls below 160.
   - **Tie-break.** If minimax scores are within 0.01, pick the k with the smaller across-page IQR of
     line/interline; after that, the k closest to 0.5.
   - **Audit.** Repeat audit rules (a) and (b), and view all 11 Honneur strips plus the Handog p14 strips at
     the chosen k.
   - **Decode once.** Any retune after decoding needs leave-one-piece-out.
5. **Decide the strip source**, record it, and freeze Stage 1/2 (commit hash) for Phase 1.
6. **Redo the per-class error budget** on the chosen strips before choosing Phase 1/2 oversampling targets.

### Phase 1: data engine (CPU, local; Sep 30 - Oct 5)

1. **Build the music → agnostic converter** (music21/MEI → Camera-PrIMuS agnostic tokens), per staff and per
   system.
   - music21 10.5 parses CPM `.mei` notes, durations and beams, but drops key signatures and multirests. The
     converter must add both.
   - **Gate G1:** at least 99% token agreement with CPM's gold `.agnostic` on all 3,996 local CPM samples.
     Below that, labels are noise and nothing downstream is trusted.
2. **Assemble the corpus:**
   - the music21 corpus: 433 Bach chorales (true SATB), 1,318 Palestrina, 97 Monteverdi;
   - CPM MEI;
   - later, the full PrIMuS MEI.
   - Chorales render directly as 4-staff open score.
   - Chords stay out: a divisi is split or skipped, because the vocabulary has none (chord plan, section 10).
3. **Render with Verovio** in SATB system layout:
   - lyrics under the staves, 4-5 measures per system, and the 5 bundled SMuFL fonts;
   - encoded system breaks, so we know which measures land on which system. Continuation systems then carry
     clef + key and no time signature, like real scores.
4. **Cut the strips with our own Stage 1/2** from the rendered pages, with labels joined by (page, system, voice).
   This fixes the BUG-016 cutting mismatch at the source.
5. **Camera augmentation on the page before Stage 1:**
   - specks, blur, perspective, curl, illumination/shadow, JPEG, paper texture, stroke thickness;
   - parameters matched to our dev camera pages by eye and by speck/stroke statistics, not by SER.
   - **Stroke/contrast (ml-cv-lead, 2026-09-30, after Phase 0b step 2):**
     - Span both failure regimes, from eroded (line about 0.10 interline, dashed lines, open hollow heads) to
       fused (about 0.26+), weighted toward low contrast.
     - Produce them by page-level contrast reduction and uneven illumination before Stage 1, so the real
       binariser makes the real artefacts. Do not apply morphology to strips.
     - Match ranges to measured page-contrast and stroke statistics, which makes Honneur less independent.
       That trade-off is accepted and stated.
     - If a dot or flag is erased while the label still has it, the model learns context dot insertion. So
       enforce a minimum surviving dot/flag area, or drop or relabel the sample.
     - Report dotted-eighth recall and dot insertions per dotted token per arm.
     - Do not use morphological thinning as augmentation: it removes short ledger lines (ledger recall 71-72%
       at C40 vs 62-69% under thin2).
     - Naturals (32-50% in every arm) are not a stroke problem. They go to the step-6 budget, oversampling
       and Phase 3.
   - **Timing.** Do not cut the corpus until Phase 0b step 5 freezes the strip source. Train and serve on
     exactly that source. The G1 converter and Verovio rendering do not depend on it and can start now.
6. **Optional, highest fidelity (A5):** print about 20 rendered pages and photograph them with the user's phone.
   This gives true camera images with exact labels, at a cost of about 1 hour of the user's time.

### Phase 2: retraining (Kaggle GPU; Oct 4 - Oct 12)

**ml-cv-lead reviews the training code before any run** (CLAUDE.md). The DataLoader seeding fix (notebook cell 12,
still open from Step 2) goes in first.

1. **Scale-up run:**
   - Train on the Phase 1 synthetic SATB strips plus about 50% CPM replay (the full PrIMuS if the Kaggle copy loads).
   - Fine-tune from the current base with 2 seeds, reported as a range.
   - Canary: CPM clean/distorted SER, with the existing caps.
   - Model selection on a synthetic-layout validation split, never on dev pieces.
   - **Gate G2:** dev SER (eval_prelim, both conditions) improves by at least 3 pp over E1c, with no canary cap
     breach. If not, stop and diagnose with ml-cv-lead before spending more GPU.
2. **AC4 real-data fine-tune:**
   - Fine-tune on real dev-piece strips with GT (5 pieces, about 330 strips per condition), plus replay.
   - Use leave-one-piece-out cross-validation: each dev piece is scored by a model that never saw it. That stops
     the dev number from being a training-set number.
   - The final model trains on all 5 pieces.
   - **Gate G3:** the leave-one-piece-out SER beats G2's model.

### Phase 3: grammar-aware rescoring (CPU; Oct 10 - Oct 14)

- Oracle headroom: 47% of note/accidental misreads have the GT token in the top 3 with p > 1e-2.
- Rescore the top 3 per CTC segment with:
  - bar-duration consistency against the running meter;
  - the key signature and the accidental grammar (no accidental repeating the key alteration);
  - a small insertion penalty.
- Tune the weights with leave-one-piece-out on dev only.
- **Gate G4:** at least 1 pp dev SER gain in leave-one-piece-out, and pitch not worse.

### Phase 4: frozen, pre-registered held-out evaluation (Oct 14 - Oct 18) - step 4, ON HOLD for the user's questions

- New pieces, never seen, never tuned on, digital and camera. The proposal promises 10 scores.
- Pre-register the metrics, the system version and the analysis, like `data/eval_fresh/PREREG.md`.
- Run once and report both seeds as a range, with 95% CI and note precision.
- **This is the only number that can go in the thesis as the AC1 result.**

**Oct 19:** report whatever Phase 4 gives, honestly. For context, published polyphonic camera OMR is above 39%
error (Martinez-Sevilla 2025).

### Side track (only if Phase 2 misses G2): homr bake-off

Install homr (a TrOMR-style transformer, trained on much larger synthetic data) in a separate venv. Score it on the
same dev strips as an offline comparator. That tells us whether a different model family, not more data for ours,
is the lever.

## 6. Expected outcome (honest)

- **Digital:** 16.3-16.5% after Phase 0, on a 2-piece pool that has been tuned on. It is close on dev, but that
  says little about held-out.
- **Camera:** 26.8-28.4% after Phase 0. Below 15% needs note errors roughly halved.
  - The literature says this is the size of gain that target-layout synthetic data plus camera augmentation
    gives. OLiMPiC's Zeus went from 59.9% to 17.7% SER on scanned input from augmentation alone.
  - Still, no one can promise it for our data. The gates exist to find out early.
- **The held-out number will likely sit above the dev number**, because dev data has been tuned on.

## 6b. ml-cv-lead review (2026-09-29): CONDITIONAL GO for Phase 1

These are required before Phase 1 starts, and are binding on the phases above:

**Measurement**
- **Deletions untested.** Dev GT has no real meter change or multirest, so E1c's false-deletion rate is untested.
  - Phase 1 renders include constructed meter changes and multirests.
  - Phase 4 pre-registers the count of real ones and reports whether each survived.
- **Pools differ.** The camera pool (5 pieces) and the digital pool (2 pieces) aren't comparable. Report per piece.
- **Unverified figures.** The literature numbers come from web-search summaries. Verify them against the papers
  before thesis use.

**Phase 1 data**
- **G1b:** a human spot-check of about 30 rendered SATB strips against their labels. This covers what CPM gold
  can't: continuation headers, tenor treble-8vb, ties and beams across system breaks, and SATB multirests.
- **Label join:** drop any rendered page where Stage 2's staff count differs from the expected count, so
  (page, system, voice) labels can't shift silently.
- **Freeze Stage 1/2** (record the commit) before generating the corpus.
- **Palestrina:** normalise it to treble / treble-8vb / bass clefs, or exclude it. It doesn't train beams or
  eighth-rest shapes.
- **Source and format:** use full PrIMuS as the *source* and the SATB engine as the *format*. Stack 4 incipits
  as a system, force breaks so there are continuation systems, and cut with Stage 1/2. Rendered Bach alone
  (about 7k strips) is too narrow.
- **Replay binarisation:** pass CPM replay through the same binarisation as inference, or report the difference
  as a confound.

**Phase 2 training**
- **Ordering:** run E4 (speck) and no-training stroke/binarisation ablations before rendering, so augmentation
  targets the *post-Stage-1 binarised strip*. The ablations are threshold, erode/dilate, and INTER_AREA vs
  grayscale strips. The camera-only duration and dot errors point to stroke and noise.
- **G2 must be attributable.**
  - Keep one augmentation on/off ablation.
  - Both seeds must pass, with margins set by a piece-level bootstrap.
  - Report with and without E1c, since a new model may stop hallucinating and the filter would then only delete.
- **G3 leave-one-piece-out:**
  - The camera and digital copies of a piece go in the same fold.
  - Fix epochs, LR and replay ratio in advance, or select them inside each fold.
  - Report the Non Nobis fold separately.
  - Check the CPM canary for forgetting.
  - Only user-verified GT counts as labels.

**Phase 3 rescoring**
- Tune the rescoring on each fold model's logits, never on the final model trained on all pieces.
- G4 also requires the CPM canary and the confident-wrong rate not to get worse.

**Phase 4 evaluation**
- **Pre-register:**
  - 10 pieces with human-verified GT;
  - a piece-level bootstrap CI;
  - both seeds as a range;
  - camera and digital reported separately;
  - the confident-wrong rate and calibration (the retraining plan's step 7, which no gate covered before).

## 7. Literature consulted (via web search summaries, 2026-09-29)

| Work | Result or relevance |
|---|---|
| Calvo-Zaragoza & Rizo 2018, PrIMuS / Camera-PrIMuS (ISMIR / Applied Sciences) | ~87k incipits; our training base |
| Ríos-Vila et al., Sheet Music Transformer | 5.3% SER on Camera-GrandStaff, trained on large synthetic data |
| Mayer, Straka, Hajič, Pecina 2024, OLiMPiC / Zeus (ICDAR) | Scanned SER 59.9% without and 17.72% with augmentation |
| Martinez-Sevilla et al. 2025 | Above 39% error on polyphonic camera OMR |
| homr (TrOMR-style) | Candidate comparators and ideas |
| oemer (segmentation-based, scale normalisation by staff unit size) | Candidate comparators and ideas |

**The common thread:** low SER comes from target-layout synthetic data at scale plus realistic augmentation, not
from decoding tricks. That matches our error budget.

## 8. Timing check (PIYA-110 / SOW 2 min/page, measured 2026-09-29, CPU)

**Setup:** Both Sides Now, 7 pages, full pipeline with ClefKeyNet.
- **With ClefKeyNet:** 23.7-37.4 s per page, mean 32.1 s. Stages 1-3 take about 26 s, ClefKeyNet 0.09-0.21 s and
  synthesis about 4.3 s. All 7 pages produced 4 MP3s.
- **Without ClefKeyNet:** about 32.6 s per page.
- The classifier adds no measurable time, and every page is well under the 2-minute limit. The header filter only
  reorders Stage 3 work, so it adds no inference.
