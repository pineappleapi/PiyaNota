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

   **False dots and pitch: ml-cv-lead review, requested by the user (2026-09-30). Pre-registered before any
   analysis of the saved-hypothesis decode `hyp_decode.json`.**

   *Assessment:*
   - **Stage-3 pitch metric: probably not a material risk.**
     - `score_strip` aligns on (kind, pitch). A false dot can only cost pitch by displacing or replacing a
       pitch-bearing token.
     - The metric is recall-only, so from now on **note precision** (matched hypothesis notes / hypothesis notes)
       is reported next to it.
   - **End-to-end audio: a real risk.** A dot token lengthens `events[-1]` whatever its position suffix and
     whatever tokens come between (`stage3_transcription.py` ~L1426-1450). Ranked:
     1. **Stage 4 overflow repair.** Every false dot on a note or rest overfills its bar. Run-scaling, clipping or
        confidence drops can then move or remove real notes.
     2. **Confidence coupling.** A dot's confidence folds into its host note's `confidence` (min). A low-confidence
        false dot can make its own host the note that a confidence drop deletes.
     3. **Orphan dots.** After a barline, accidental or clef, a dot lengthens the previous bar's last note.
     4. **Substitution.** A dot replaces a note or accidental.
     5. **CTC split duplicate.** A dot between two identical notes prevents the CTC collapse, giving a phantom note.
     6. **Dot-S/L anchoring.** No effect.

   *2a. Scope and alignment:*
   - Primary: E7 camera, each seed reported separately. Secondary: base, thin2, digital. Nothing is pooled.
   - Cells with fewer than 10 events are reported as counts only.
   - Alignment is identical to `score_strip`. S categories are upper bounds, because a dot next to a deletion
     aligns as one S.

   *2b. Definitions:*
   - **False dot** = I with hyp `dot`, or S with hyp `dot` against a non-dot reference token.
   - Each false dot gets one context class, checked in order:
     - **C3p:** S replacing a `note.*` or `accidental.*`.
     - **C3o:** other S.
     - **C4 (split duplicate):** hyp[j−1] == hyp[j+1], both `note.*`, and at most one of the two aligned M.
     - **C2 (orphan):** the preceding non-dot hyp token is not a note or rest. Subtyped by that token: barline,
       accidental, clef/key/meter, strip start.
     - **C1u / C1d (valid host):** the host's GT event is undotted / already dotted. The host's next token is also
       recorded.
   - C4 is also counted on `raw`.

   *2c. Co-location with pitch errors (k = 2 tokens, fixed; k = 0 also reported):*
   - A pitch error is a GT note that is D or S in the pitch-key event alignment.
   - The n-th note event maps to the n-th `note.*` token. Strips where the counts differ are excluded, and the
     excluded count is reported.
   - Null: each strip's false dots placed uniformly over ref positions, 1000 permutations, RNG seed 0.
   - Enrichment E = observed pairs / mean under the null.
   - U = GT pitch errors co-located with a C3p or C4 dot, divided by all GT notes.

   *2d. Also report:* false dots per dotted reference token and per 100 GT notes; host-note mean confidence for
   false vs true dots; C2 counts by subtype.

   *2e. Image audit:*
   - All seed-1 E7 camera false dots, plus new seed-2 locations. Crops ±1 interline, randomised order, arm hidden.
   - Classes:
     - I1: other ink (speck, mask residue, lyric punctuation, articulation);
     - I2: a real dot, so the GT is wrong;
     - I3: no ink (hallucination).
   - Needs the per-token CTC frame index.

   *Decision rules (fixed now):*
   - **R0:** I2 ≥ 5 → fix the GT and rescore first.
   - **R1:** U < 1 pp on both seeds and C3p + C4 < 20% → false dots are not a Stage-3 pitch risk. Treat them as a
     rhythm/audio problem (section 3) and do no pitch-motivated dot work.
   - **R2:** U ≥ 1 pp on either seed, or E ≥ 2 with C3p ≥ 20% → record "dots co-locate with pitch errors"
     (co-occurrence, not cause). Act only through Phase 1 augmentation, never through inference dot suppression.
   - **R3:**
     - I3 ≥ 50%, or C1u-then-eighth is the majority of C1 → Phase 1 rhythm diversity becomes a must.
     - I1 dominant → Phase 1 negative speck, residue and punctuation items become a must.
   - **R4:** C2 ≥ 10% of false dots → register the G1 orphan-dot guard for post-Phase-1 evaluation.

   *3. Stage 4 counterfactual (run now; no Stage 4 change until after Phase 1):*
   - E7, both seeds, camera, only systems where all 4 voice strips were detected.
   - Arms:
     - A: decoded;
     - B: A with the 2b false dots removed, re-run through `infer_pitch` with the same header decisions and
       `next_system_key`;
     - G: GT events.
   - Each arm goes through `reconstruct_satb_with_report()`. Report A − B:
     - overflow, clip, tuplet, missing-barline, drop and `review_needed` flag counts;
     - notes lost in Stage 4;
     - notes whose duration or onset was repaired;
     - post-Stage-4 pitch recall and precision against G;
     - onset agreement with G.

   *4. Fixes, registered:*
   - **Phase 1 training:**
     - the dot-survival label rule (already registered);
     - negative grey specks outside the augmentation-dot zone (0.3-1.5 notehead widths right of a head, on a space),
       with statistics taken from pages outside eval_prelim and piyanota_dataset;
     - lyric punctuation and mask residue, label unchanged;
     - meter-valid rhythm diversity (quarter-eighth vs dotted-quarter-eighth balanced).
   - **Loss:** no dot class weighting or focal loss.
   - **Held-out reporting per arm:** false dots per dotted token; dotted-eighth and dotted-quarter recall; note
     precision; section 3 A − B.
   - **Inference guards.** Pre-registered, flagged, and judged only on held-out data after Phase 1:
     - **G1:** a dot is valid only right after a note, rest or dot; otherwise drop it and flag
       `orphan_dot_dropped`.
     - **G2:** before run-scaling, clipping or drops, remove a dot and flag `dot_removed_overflow` /
       `review_needed`, but only when the bar overflows by exactly that one dot's value and removing it fills the
       bar exactly. If more than one dot qualifies, remove none.
   - **Not legitimate:** a dot-confidence threshold, or any rule chosen because it lowers dev SER.

   **Results (2026-09-30; dev data, diagnostic only; each seed reported, nothing pooled).**

   *Pitch breakdown (step 6, first entry).* It comes from a re-decode that saves hypotheses
   (`hyp_decode.json`: arms base / thin2 / E7, camera 227 + digital 100 strips per arm and seed). That is one
   decode of existing arms, not a tuning run.
   - Camera pitch recall, E7 / thin2 / base: 88.0-89.3 / 91.6-92.1 / 85.1-85.2. Note precision:
     70.7-72.1 / 72.2-73.0 / 68.9-70.0.
   - Digital pitch recall: 90.7-91.0 / 91.2-91.6 / 89.7-90.2.
   - E7's alteration-only misses rose (86-92 vs thin2 65-82), mostly GT-sharp notes (25-26 vs 15-18), all in
     mask quartile Q1. They trace to one system: Honneur camera p3 s1, where ClefKeyNet's stored key is 0 on both
     seeds but GT is 3#.
     - Logged as **BUG-037** (a ClefKeyNet key error, BUG-021 class). It is shared by all arms.
     - base/thin2 hid it with phantom inline sharps that happened to land on those notes; E7 emits fewer phantoms.
   - Excluding that system:
     - recall E7 89.7-90.9 / thin2 93.3-93.9 / base 86.8-87.0;
     - alteration-only misses E7 42-48 / thin2 43-53 / base 48-65.
     - **Alteration-only errors do not rise under E7, so the blocking rule does not fire.**
   - The remaining E7-vs-thin2 gap (~3 pp) comes from:
     - position ±2 or more: 121 / 85 vs 57 / 48, seed-dependent;
     - no hyp note: 37 vs 16-22;
     - position ±1: 54-55 vs 38-40.
   - The gap sits in mask quartile Q4, the most-masked strips: E7 83.6-86.8 vs thin2 92.5-93.2. In Q1 the arms
     are equal. Q4 is confounded with lyric-heavy pieces. This goes to ml-cv-lead: E7 wins SER but thin2 wins
     pitch on heavily masked strips.

   *Live ClefKeyNet / grey-source parity (before the freeze).* Worktree Stage 1 against HEAD, on all 42 dev
   cache pages:
   - Detection page, unmasked page, tracked staves, grey and binary are all equal, and every `strip_source` is
     grey.
   - Live Stage 2 strips match the E7 sweep strips on 388 of 388, byte-identical after PNG round trip.
   - ClefKeyNet crops and probabilities are identical on 388 of 388, and decisions are identical on 388 of 388.
   - **PASS: the grey strip source does not touch ClefKeyNet.**

   *False-dot review.*
   - **Counts (2a/2b, 2d), camera.** False dots are counted per arm and seed, excluding dots inside a GT `<OOV>`
     wildcard (unscorable: E7 68 / 77).

     | Arm | False dots (seed1 / seed2) | Per dotted ref token | Per 100 GT notes |
     |---|---|---|---|
     | E7 | 34 / 53 | 0.11 / 0.17 | 1.34 / 2.09 |
     | thin2 | 66 / 103 | | |
     | base | 98 / 123 | | |

     - **E7 has the fewest false dots of the three arms**, so the grey source removed false dots rather than
       adding them.
     - E7 classes, seed1 / seed2:
       - C3p 5 / 5, C3o 6 / 7, C4 0 / 0;
       - C2 8 / 13 (23.5 / 24.5%; mostly after an accidental);
       - C1u 7 / 13, C1d 3 / 2, C1x 5 / 13.
     - Raw C4: 0 / 2.
   - **Co-location (2c).** U = 0.08 / 0.08 pp.
     - k=2: 2 / 2 observed vs a null mean of 1.61 / 1.14, so E = 1.24 / 1.75.
     - k=0: 0 observed.
     - No strips excluded; 37-38 misses unlocatable.
     - The null permutes over hyp token slots, not ref positions as registered. Misses are located in hyp slots,
       so this is the consistent space; noted as a deviation.
   - **Confidence (2d).** False dots: mean 0.44 / 0.45. True dots: 0.91 / 0.92. False-dot hosts: 0.58 / 0.60 vs
     0.81 / 0.83 for true-dot hosts.
     - This is descriptive only; a dot-confidence threshold stays not legitimate.
     - For 11 / 16 false dots no preceding note or rest exists; they sit in the header zone.
   - **Image audit (2e).** 65 crops: all 34 seed-1 false dots plus 31 new seed-2 locations. Order was randomised
     and the class hidden. Frame-to-x localisation is approximate (±~10 px).
     - I1 other ink: 32 (49%).
       - Voice-label text and periods at the strip's left edge ("T.", "S.", "Soprano"): 18.
       - In-band lyric residue, including "don't" apostrophes, and dynamics/text: 8.
       - Specks: 3.
       - Repeat-sign and fermata dots: 3.
     - Real dot ink that is not a GT error: 11 (17%).
       - Second dot of a divisi chord: 7. There is no chord vocabulary, so this is a known gap.
       - Real dot emitted twice: 2.
       - Real dot aligned against a barline next to a GT `<OOV>`: 2.
     - **I2 (GT wrong): 0.** The 4 candidates were unblinded against the alignment; none is a missing GT dot.
     - I3 (no dark ink): 22 (34%). Many I3 crops show only bright erasure specks: dilated erased ink set to 255 on
       grey paper.
     - Header zone (x < 220 px): 27 of 65.

   *Rulings (rules fixed in advance):*
   - **R0 does not fire** (I2 = 0).
   - **R1 fires on both seeds** (U 0.08 pp < 1 pp; C3p + C4 = 14.7% / 9.4% < 20%). False dots are **not a
     Stage-3 pitch risk**: no pitch-motivated dot work, no inference dot suppression.
   - **R2 does not fire** (E ≥ 2 on neither seed).
   - **R3:** I3 is 34% (< 50%), and C1u-then-eighth is not the majority of C1 (5 of 15, 6 of 28).
     - I1 is the largest class, so **Phase 1 negative items for label punctuation, lyric apostrophes, specks and
       mask residue become a must**.
     - The strip-start voice label is the single biggest source (18 of 65). This is the known Stage 2
       "left-edge label text" residual.
   - **R4 fires** (C2 ≥ 10%). The G1 orphan-dot guard is registered for post-Phase-1 held-out evaluation (already
     in section 4); nothing changes now.

   *Stage 4 counterfactual (section 3).* E7 camera, complete 4-voice systems; 2,497 GT notes per seed.
   - A reproduces the stored decode on every strip (0 mismatches, 0 unmapped dots).
   - Removing every false dot (B) changes, A − B, seed1 / seed2:
     - bar-overflow clips +4 / +10;
     - notes lost in Stage 4 +5 / +6;
     - notes with changed duration +4 / +16;
     - post-Stage-4 pitch recall −0.20 / −0.16 pp; precision −0.05 / +0.02 pp;
     - onset agreement −0.10 / −0.58 pp.
   - The end-to-end cost is real but small. It is dwarfed by Stage 4's baseline repair load: in A, 100 / 121
     clipped bars and 200 / 230 notes lost, mostly from other rhythm misreads. No Stage 4 change until after
     Phase 1, as registered.

   *ml-cv-lead review of these results (2026-09-30).* The rulings above were applied correctly. Caveat: dots
   inside `<OOV>` spans (68 / 77) outnumber the scored ones, so their pitch impact is unmeasured. The exclusion
   was like-for-like (thin2 70 / 86, base 59 / 70). ml-cv-lead then requested a Q4 check (`q4_check.py`,
   diagnostic, BUG-037 system excluded):
   - **(a) Q4 pitch recall per piece, E7 vs thin2 on the same strips.** E7 is lower in all 5 pieces on both
     seeds.
     - dont_stop_me_now: 90.0 vs 99.4 / 92.8 vs 97.8;
     - gaano: 77.2 vs 89.0 / 81.7 vs 89.5;
     - handog: 86.4 vs 93.2 / 88.3 vs 91.3;
     - honneur: 84.1 vs 88.6 / 81.8 vs 86.4;
     - non_nobis: 82.1 vs 92.3 / 89.7 vs 94.9.
     - That is 5 of 5 pieces (one-sided sign-test p = 0.03, post hoc).
   - **(b) Do E7's misses sit on the 255 fill?** The measure is the share of pixels == 255 within ±8 columns of
     each note.
     - In Q4 the paired per-strip difference (misses minus correct notes) is −0.0013 / +0.0001.
     - Misses are whiter in 17 / 15 strips; correct notes are whiter in 23 / 16.
     - **No co-location with the fill.** No mechanism for the gap is known.
   - **Final call: CONDITIONAL. E7 is not frozen as the only strip source.**
     - Carry E7 and thin2 through the held-out evaluation.
     - Pre-register camera pitch recall and note precision as primary, SER as secondary, each seed separately,
       Q4 broken out.
     - If Phase 1 can afford only one training source, train on E7 as registered, but decode the held-out set
       with both arms.
     - Switching to thin2 on this dev result would be metric shopping.
   - **Fill (applied 2026-09-30, user OK).**
     - The erasure (dilated by ceil(2σ)) and the page border are filled with `stage1_preprocessing.paper_fill()`, not
       255. It is a normalised Gaussian convolution of the paper pixels (outside dilated ink and the border) at
       detection size, σ = 12 px at 1600 px, with the page median paper where no paper is nearby. The choice was
       made on train = serve grounds alone.
     - Phase 1 must import `paper_fill()` (train = serve).
     - Parity against E7 at 2ea869b (42 dev pages, 388 strips, `fill_parity.py`):
       - detection page, unmasked page, staves, grey page and binary source are identical;
       - no pixel changed outside E7's 255 region;
       - ClefKeyNet crops and probabilities are identical (it reads the binary unmasked page);
       - on the 25 camera pages no fill pixel is left at 255, and the fill median is within 2 grey levels of the
         paper median;
       - on the 17 digital pages the paper itself is 255 (87% of pixels), so the fill stays 255, which is correct;
       - Stage 1 time rises by about 10% (1094 s vs 989 s over 42 pages, CPU).
     - The current E7 dev numbers are stale. The dev set is not re-decoded to re-justify E7.
   - **Held-out decision (user, 2026-09-30).**
     - Both arms (E7 with the paper fill, and thin2) go through the held-out evaluation.
     - Camera pitch recall and note precision are primary; token SER is secondary.
     - Each seed is reported separately, with Q4 (most-masked quartile) broken out.

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

   **E6 canary baseline through the grey path (2026-09-30, the last step-5 prerequisite; diagnostic).**
   - Same 399 canary stems, interline estimate and Stage 1 constants as E6. The grey arm is `_build_strip_source`
     without the threshold: background divide, blur, no contrast stretch. CPM has no lyrics or border, so the mask
     and `paper_fill()` leave it unchanged and are skipped, as E6's binary arms skipped the mask. The E6 caveat on the
     background kernel being taller than an incipit still applies.
   - Raw reproduces E6 exactly, so the setup matches.

   | CPM SER, seed1 / seed2 | raw | grey | C10 binary (E6) |
   |---|---|---|---|
   | clean | 2.59 / 2.69% | 2.68 / 2.62% | 3.52-3.93% |
   | distorted | 5.73 / 5.83% | 5.84 / 5.68% | 22.13-23.76% |

   - Grey stroke line/stem per interline: clean 0.128/0.141, distorted 0.176/0.235 (raw 0.128/0.128,
     0.176/0.202). Grey keeps CPM's line width; C10 fattened it to 0.24-0.28.
   - The grey path costs the current model at most about 0.1 pp on CPM, against 4× under C10. **These are the
     canary baselines for Phase 2**: rerun the same script on each retrained checkpoint.
   - Script: job tmp `e6_grey.py` (reuses `e6_cpm.py`); to be moved into `training/` with the Phase 2 canary.

   **Step 5 decision (2026-09-30).** All four prerequisites are met: F1 decided (hard fill, then `paper_fill()`),
   live ClefKeyNet parity passed, pitch breakdown filed, E6 grey baseline above.
   - **Training source: grey (E7 recipe with `paper_fill()`), chosen by tie-break (a)-(c); headline SER tied on
     dev.** Never "E7 beats thin2".
   - **thin2 stays a second arm, used at decode time only**, through the held-out evaluation, as ml-cv-lead's
     CONDITIONAL call and the user's held-out decision require. It is not a training source.
   - **Frozen: Stage 1/2 at commit 9b9e12f** (`stage1_preprocessing.py` and `stage2_detection.py` are unchanged
     after it; branch head e3fdf2d). Phase 1 cutting and every Phase 2 input use exactly this code. Any change to
     either file un-freezes step 5 and needs re-review.
   - **Stage 1 un-frozen for BUG-039 by user decision on 2026-09-30, to be re-frozen at the fix commit. Phase 1
     cutting waits for that.** The fix (uncommitted) keeps each staff's end, plus 2 spacings, out of the right
     border blank. Digital strips are byte-identical; 72 camera strips change (dev decode in BUG-039).
6. **Redo the per-class error budget** on the chosen strips before choosing Phase 1/2 oversampling targets.

   **Step 6 result (2026-09-30, dev data, diagnostic only).**
   - **Purpose.** This decode only chooses oversampling targets. It is never used to re-choose the strip source,
     which step 5 froze.
   - **Setup.**
     - Stage 1/2 at 9b9e12f were re-run on the 42 eval_prelim cache pages. All 388 strips are byte-identical to
       the `paper_fill()` parity strips.
     - One decode per seed on the same GT strips as `hyp_decode` (camera 227, digital 100), along the same path:
       greedy, then the E1b header rule, then version_b with the stored ClefKeyNet records, then `score_strip`.
     - Camera and digital are never pooled; seeds are given as a-b ranges.
     - Errors are charged to classes on `score_strip`'s own alignment, asserted to sum to tok_err:
       - substitutions and deletions go to the GT class; insertions go to the hyp class;
       - beamed notes are grouped by duration.
     - Ties are scored in a second alignment that keeps slurs. They sit outside SER.
     - Cross-check: the same script run on `hyp_decode`'s E7 hard-fill arm reproduces the stored E7 pitch numbers.
   - **Headline.**
     - Camera: SER 15.6-16.2%, pitch recall 88.7-89.8%, note precision 70.3-71.9%.
     - Digital: SER 14.9-15.7%, pitch recall 90.7-91.0%, note precision 69.0-69.4%.
     - No strips were missed.
   - **Pitch misses** (s1/s2):
     - Camera:
       - alteration-only 88/90 (GT natural 56/61, GT sharp 26/26); 52/54 of these are in mask Q1, mostly the Honneur p3 key from BUG-037;
       - position ±1 63/62; ±2 or more 101/80; no hyp 34/26.
     - Digital: alteration-only 35/38 (GT natural 32/35), ±1 19/15, ±2 or more 36/31, no hyp 4/7.
   - **Camera pitch recall by mask quartile:** Q1 89.6/89.6, Q2 90.7/90.1, Q3 87.4/90.6, Q4 86.8/89.1.
     - Hard-fill Q4 was 83.6/86.8.
     - Q4 misses: ±2 or more 32/23, ±1 18/20.

   | Group (ranked by camera share) | cam share % | dig share % | GT n cam/dig | cam recall % | cam mix P/C/D/I (s1+s2) | pieces (cam) | flag |
   |---|---|---|---|---|---|---|---|
   | note.eighth (flag+beamed) | 17.7-20.2 | 14.5-15.3 | 1050/299 | 88.1-90.4 | 89/122/15/64 | spread (DSMN 63-80) | DATA: positions; 50 of C are beam-form swaps (no pitch/rhythm cost) |
   | note.quarter | 15.3-17.3 | 18.9-20.9 | 634/355 | 83.4-87.1 | 32/139/16/63 | Gaano 60-73 | camera: 85 are quarter→half (filled head read hollow), an augmentation fix; digital: 29 are quarter→eighth |
   | barline | 9.9-10.2 | 2.0-2.2 | 882/460 | 91.8-92.4 | 0/33/106/15 | Honneur 29-32, Gaano 17-20 | NON-DATA: 38-40/seed erased by Stage 1 (BUG-039); 5-6/seed CRNN misses |
   | note.sixteenth | 9.0-9.4 | 1.6-1.7 | 213/8 | 68.5-69.0 | 4/124/5/8 | **Honneur 57-58** | DATA: 109 are →eighth; fractional-beam gap survives at 64 px but only barely |
   | note.half | 7.6-8.5 | 10.4-11.6 | 257/182 | 82.9-85.2 | 57/14/11/41 | Gaano 34-36 | DATA: positions |
   | dotted notes | 5.0-6.0 | 5.7-6.6 | 293/117 | 85.7-89.4 | 35/31/7/12 | spread | DATA |
   | dot | 4.5-5.8 | 5.3-10.7 | 310/117 | 96.1-97.7 | 0/4/15/60 | spread | negatives: false dots come from label/lyric residue |
   | note.whole | 3.6-6.2 | 1.9-2.0 | 86/47 | 72.1-74.4 | 17/21/8/29 | spread | DATA (11 read as fermata, 8 as half) |
   | inline.natural | 3.3-3.9 | 7.3-7.9 | 42/39 | 31.0-38.1 | 1/40/14/0 | **Gaano 25-27** | DATA for glyph misreads (→sharp 8-14); key-state is BUG-037 |
   | fermata (ins. only) | 3.3 | 3.7-4.7 | 0/0 | - | I 51 | DSMN, Non Nobis | NON-DATA (GT convention); the whole→fermata part is a model error |
   | meter | 2.7-2.8 | 3.3-3.5 | 24/12 | 25.0-33.3 | 0/26/8/8 | spread | partly DATA (digits); E1b/R3 |
   | key signature | 2.5 | 1.3-1.6 | 460/193 | 95.7-95.9 | 1/8/30/0 | Honneur 11-12 | NON-DATA (ClefKeyNet, BUG-037) |
   | inline sharp / flat | 1.3-1.7 / 1.3-1.4 | 0.3 / 3.5-3.7 | 25/15, 26/22 | 88-92 / 73-89 | mostly I | - | negatives (precision 25-49%) |
   | dotted rests | 1.3-1.6 | 0.0 | 16/0 | 37.5-43.8 | 0/18/1/3 | - | DATA (read as dotted notes; small n) |
   | rest.eighth | 1.2-1.5 | 6.6-9.6 | 153/2 | 97.4-98.0 | 0/7/0/13 | digital: Gaano 47/50 | negative: voice label/bracket read in the header; GT is right |
   | clef | 0.1 | 0.0 | 227/100 | 99.6 | 0/2/0/0 | - | NON-DATA (ClefKeyNet) |

   - **Ties** (camera; outside SER):
     - slur.start recall 25-30% (42-50/167), precision 55-56%;
     - slur.end recall 35-38%, precision 79-82%.
     - Ties are a DATA target.
   - **OOV blind spot.**
     - GT `<OOV>` spans (chords, divisi, triplets) absorb 777-787 camera and 309-310 digital hyp tokens. That is
       about equal to all counted errors, and none of those tokens are scored.
     - This ranking covers only the non-OOV regions.
     - These tokens explain most of the roughly 70% note precision. It is a vocabulary problem, not a data one.
   - **Caveats.**
     - Five camera pieces: the unit of evidence is the piece, not the token. Sixteenths (Honneur), inline naturals
       (Gaano) and quarter→half (mostly Gaano) are each carried by one piece. Per-piece table: job tmp
       `step6/perpiece.log`.
     - `beam_check` imports stage3 from the accidental-logic-fixes worktree, as `hyp_decode` did.
     - The ClefKeyNet records are stored ones and predate R1-R4.
     - `score_eval.tok_class` uses `rsplit('-', 1)`, which leaves `-S`/`-L` on negative positions, so
       `per_token_class` splits classes and counts position errors as class confusions. SER is unaffected. The
       budget uses its own regex. Filed as BUG-038.
   - **Follow-up checks for ml-cv-lead items 2, 4 and 6 (2026-09-30, dev strips only, diagnostic).** Crops are in
     job tmp `step6/imgcheck/`. The old `imgcheck/barline/` folder is stale (first detector); use `final_barline/`.
     - **2a. Honneur sixteenth→eighth.** The lost "second beam" is the short fractional stub on dotted-eighth +
       sixteenth pairs. At 64 px the stub is about 3-4 px tall. The gap to the primary beam is 1 px, grey ~150-180
       against paper ~220, and at some columns it partly closes (~100-120). The same figure is read correctly in
       other Honneur strips (for example p1 sys02 Tenor/Bass).
       - Verdict: the gap survives, but only just. This is a rare pattern at marginal resolution, in one piece.
       - DATA: fractional-beam dotted rhythms rendered at the same scale. Held-out recall may stay capped by resolution.
     - **2b. Strip-final barlines.** There are 43-46 deletions per seed over 49 unique camera strips. **None is
       cropped by the Stage 2 box**: the staff ends 61+ px inside the strip.
       - Checked visually (the automatic detector false-fires on stems and rests): 41 strips (38-40 deletions per
         seed) have no barline in the pixels. 8 strips (5-6 per seed) have it present, and the CRNN misses it.
       - Absent by piece (s1/s2): Honneur 19/21, Gaano 13/13, Handog 4/4, DSMN 1/0, Non Nobis 1/2.
       - On Honneur p1 and Gaano p2 the barline is in the photo and in `strip_gray`, but gone in `strip_unmasked`,
         `strip_binary` and `strip_source`, along with the last few px of staff line. So Stage 1 erases it before
         the non-staff mask. The exact step is not isolated.
       - Filed as BUG-039. Non-data. It is frozen with Stage 1/2 at 9b9e12f; any fix un-freezes step 5.
     - **2c. Gaano digital phantom rest.eighth** (47 in seed1). Most of them (Bass: 14 of 22 strips) come out in
       the header zone.
       - Cause: the raw CRNN reads the "B." voice label, the bracket, the bass clef and the flats as `clef.C-L1`,
         `metersign.C` and then runs of `rest.eighth`. Header substitution replaces only the clef and keysig
         tokens, so the rests survive after the substituted key.
       - Token before each phantom: keysig 21, rest 14, note 6, dot 4, inline 2.
       - The GT is right: camera and digital agree, with 2 eighth rests. The camera copy has the same label and no
         phantoms.
       - Verdict: not a GT defect. The fix is negatives (voice labels and brackets) plus a header-zone rule.
     - **4. Natural split.** Each alteration-only pitch miss (s1/s2) is split by cause: own-glyph / phantom own
       accidental / key state / carry.
       - GT natural, camera: 13/17, 1/1, 25/25, 17/18.
       - GT natural, digital: 15/18, 1/2, 5/5, 11/10.
       - So true glyph misreads are camera 14-18 and digital 16-20.
       - Camera key-state misses are mostly the Honneur p3 key (BUG-037). GT-sharp misses (camera 26) are key
         state 24 and carry 2. Nothing was unmapped.
       - Inline natural tokens: camera n 42, substitutions 17/23 (→sharp 8/14, →flat 5/4), deletions 8/6. Digital
         n 39, substitutions 20/23 (→sharp 11/14), deletions 2/2.
       - Wilson 95% intervals on camera exact recall (s1 / s2):
         - inline natural: 38.1 [25.0-53.2] / 31.0 [19.1-46.0]
         - whole: 72.1 [61.8-80.5] / 74.4 [64.3-82.5]
         - dotted rests: 37.5 [18.5-61.4] / 43.8 [23.1-66.8]
         - meter: 25.0 [12.0-44.9] / 33.3 [18.0-53.3]
         - inline sharp: 92.0 [75.0-97.8] / 88.0 [70.0-95.8]
         - inline flat: 73.1 [53.9-86.3] / 88.5 [71.0-96.0]
       - Wilson 95% intervals, digital:
         - natural: 43.6 [29.3-59.0] / 35.9 [22.7-51.6]
         - whole: 93.6 [82.8-97.8]
         - meter: 41.7 [19.3-68.0] / 33.3 [13.8-60.9]
         - sharp: 100 [79.6-100]
         - flat: 81.8 [61.5-92.7]
       - Script and output: `natsplit.py` and `natsplit.json`.
     - **6. Earlier rulings that used `per_token_class`:**
       - E5 sharp precision and natural recall (`perclass.py`);
       - step 2 C40 sharp precision (`cal_decode.py`);
       - the E7 result-table sharp precision and the ml-cv-lead E7 ruling that cites it.
       - No sharp or flat token has a negative position, so sharp precision is exactly unaffected. Natural recall
         left out 4 of 42-44 naturals per condition. The quarter, dotted, half and whole recalls came from
         `per_symbol`, which is unaffected.
       - **No ruling changes.** Negative-position notes: camera 112 of 2533 (4.4%), digital 12 of 1008.
       - Other decision docs mention step 6 but not `per_token_class`.
   - **Re-ranked targets: PROPOSED, PENDING USER FREEZE (item 5).** Ranked by camera error share after the checks.
     Flags: DATA = oversample or render; augmentation; negative = add negative examples; non-data = not a data fix.
     1. note.eighth positions (17.7-20.2%): DATA. The 50 beam-form swaps cost nothing.
     2. note.quarter (15.3-17.3%): augmentation (contrast/stroke) for camera quarter→half hollow heads (85). DATA for
        digital quarter→eighth (29).
     3. note.sixteenth (9.0-9.4%): DATA, fractional-beam dotted rhythms. One piece; resolution-marginal.
     4. note.half (7.6-8.5%): DATA (positions).
     5. dotted notes (5.0-6.0%): DATA.
     6. note.whole (3.6-6.2%): DATA, including whole→fermata.
     7. inline natural (3.3-3.9%): DATA for the glyph misreads (mostly natural→sharp). Key-state misses are non-data
        (BUG-037); carry misses follow from them. Gaano-heavy; wide CI.
     8. ties (outside SER): DATA.
     9. meter (2.7-2.8%): partly DATA (digits), plus E1b/R3.
     10. dotted rests (1.3-1.6%): DATA. n = 16, so the CI is wide.
     11. dot (4.5-5.8%): negative (label/lyric residue).
     12. inline sharp/flat phantoms (1.3-1.7% / 1.3-1.4%): negative.
     13. Gaano digital rest.eighth (digital 6.6-9.6%): negative (voice labels/brackets) plus header rule.
     14. barline (9.9-10.2%): non-data. 38-40 per seed are BUG-039 (Stage 1, frozen); only 5-6 per seed are CRNN
         misses (DATA, minor).
     15. fermata insertions: non-data (GT convention). The whole→fermata part is under item 6.
     16. key signature, clef: non-data (ClefKeyNet, BUG-037).
   - **ml-cv-lead review: CONDITIONAL GO.** The method is sound: alignment parity, per-class sums asserted, E7
     reproduced, both seeds from one decode, no held-out data. The data vs non-data split is not settled yet.
     Required before the target list is used:
     1. A per-piece table for the top groups. Done: the `perpiece.log` job output above. It confirms the
        single-piece concentrations.
     2. Done (see follow-up checks above). Check at 1:1 on the frozen strips:
        - that the gap between sixteenth beams survives at 64 px;
        - whether the strip-final barlines are cropped off or present but missed;
        - whether the Gaano digital phantom rests are residue or a GT defect.
     3. Treat quarter→half hollow-head errors and false dots as augmentation or negative items, not
        oversampling. Only held-out camera recall shows whether they are closed.
     4. Done (above). Separate inline-natural misreads from carry/key-state misses. Give Wilson intervals for small-n classes.
     5. Open, user decision. Freeze the target list and weights in this plan before the Phase 1 cut. A later dev gain on these
        targets is not evidence, and the held-out report must cover every class.
     6. Done (BUG-038; above). File the `tok_class` negative-position bug, and check whether any earlier ruling used `per_token_class`.
   - Scripts and JSON (job tmp `step6/`): `decode.py`, `hyp_live.json`, `strip_parity.json`, `budget.py`,
     `budget_live.json`, `budget_e7hard.json`, `rank.py`/`rank.json`, `perpiece.py`/`perpiece.json`.

   **Step 6 target freeze (2026-09-30, user decision).** Closes ml-cv-lead item 5. The user chose the targets
   "based on observation" and allowed adding classes backed by the step 6 test.
   - **User targets:**
     - with dev evidence (step 6, camera): eighth notes (17.7-20.2% share), sixteenth notes (9.0-9.4%; one piece,
       Honneur), ties (slur.start recall 25-30%, outside SER), inline naturals (3.3-3.9%; glyph misreads only,
       key-state misses are BUG-037), inline sharps/flats (1.3-1.7% / 1.3-1.4%, mostly phantom insertions, so
       they are also negatives below);
     - user priors, no dev evidence: 32nd notes (no dev error measured), and **tuplets** (no dev GT at all:
       they sit inside GT `<OOV>` spans). **Tuplets are BLOCKED ON DESIGN** (see below).
   - **Added from step 6 DATA flags:** note.half (7.6-8.5%), dotted notes (5.0-6.0%), note.whole (3.6-6.2%,
     including whole→fermata), meter (2.7-2.8%, partial: digits only; the rest is E1b/R3), dotted rests
     (1.3-1.6%, n = 16).
   - **Negatives** (add negative examples; not weighted): false dots (label/lyric residue), phantom inline
     sharps/flats, and the header-label rests (voice labels and brackets read as `rest.eighth`).
   - **Augmentation** (not weighted): hollow-head quarter→half (contrast/stroke, Phase 1 step 5).
   - **Non-data, excluded:** barline (BUG-039, Stage 1), fermata insertions (GT convention), key signature and
     clef (ClefKeyNet, BUG-037).
   - **Weights (proposed; share of the *targeted* selection budget, not of the whole corpus).** Evidence-backed
     classes are proportional to their mean camera error count over the two seeds (share × total errors; ties
     from the tie alignment: missed + inserted slur.start/end). User-prior classes get a fixed floor.
     - Floors: 32nd 5%, tuplets 5% (reserved; if tuplets are still blocked at Phase 2 start, the 5% goes back
       pro rata to the rest).
     - Ties: raw proportional value would be ~35% (279 errors vs 438 for all SER classes combined). Proposed cap
       **15%**, because tie tokens are outside SER, ties are plentiful in any corpus, and the verovio-dialect
       tie path is untested until G1b.
     - Remaining 75% by error count (mean errors in brackets): eighth 24.8 (145), sixteenth 12.1 (70.5),
       half 10.5 (61.5), dotted notes 7.2 (42), whole 6.4 (37.5), natural 4.7 (27.5), meter 3.6 (21),
       sharp 2.0 (11.5), dotted rests 1.9 (11), flat 1.8 (10.5).
   - **Amendment 1 (2026-10-01, user): rests are a target class.** The step 6 table showed only `rest.eighth`
     and dotted rests, because the other rest classes are each under 1.3% share. Summed over every rest class
     (camera, from `budget_live.json`), rests are 41 (seed 1) / 42 (seed 2) errors, a 5.3-5.6% share, about the
     same as dotted notes. Most of that is *false* rests, not missed ones:
     - common rests are read well: rest.quarter recall 94.7-95.7% (n = 94), rest.eighth 97.4-98.0% (n = 153),
       rest.whole 91.7-100% (n = 12);
     - phantom rests: rest.half precision 45-50% (6-7 insertions, n = 11), rest.sixteenth precision 29-39%,
       multirest 4-5 insertions with none in GT, rest.eighth 6-7 insertions, rest.eighth.dotted 0-3;
     - dotted rests are misses (already a target): rest.quarter.dotted recall 33-40%, read as dotted notes;
     - digital: rest.eighth 21-29 and rest.quarter 7-11 insertions (the header-label negative above).
     **Coverage gap in the choral corpus** (usable strips after the vocabulary guard, 2026-10-01):
     - Bach (29,715 strips, 5,170 with a rest): quarter 3,665, multirest 2,300, eighth 90, half 40, whole 35;
     - Palestrina (11,803 strips, 6,886 with a rest): half 6,345, whole 3,822, multirest 303, quarter 9;
     - **neither has any dotted rest or sixteenth rest**, and eighth rests are almost absent.
     PrIMuS supplies them (dotted rests in 1,654 held-out samples, see Part B). So the rest target is filled from
     PrIMuS/CPM replay, not from the choral renders.
     Proposed handling, pending the user's ruling on the weights:
     - **DATA:** "rests" as one class at its error count (~30.5 mean errors excluding the dotted rests already
       counted, so about 5% of the 75% pool). Within it, sample so every rest duration (whole to 32nd, plain and
       dotted) appears, rather than in proportion to the corpus.
     - **Negatives:** extend the header-label negative to phantom rests in general (staff-free residue,
       lyric/label crops in which no rest is drawn).
     - **Regression metric:** rest precision per class on the held-out set, since the main failure is
       insertion.
     Rests are in the CRNN vocabulary already, so this needs no head change.
   - **Amendment 2 (2026-10-01, user): drop out-of-vocabulary data, no vocabulary expansion.**
     - PrIMuS samples with any gold token outside `stage3_transcription.VOCAB` are dropped, including the longa
       samples: 3,065 of all 87,678 PrIMuS samples (3.5%; denominator checked in `primus_g1/survey/vocab.json`).
     - Palestrina strips quarantined for the breve rest (`oov:rest.double_whole-L3`) are dropped (11,803 of
       18,504 strips stay usable). No re-barring of 4/2 pieces.
   - **Amendment 3 (2026-10-01, user approved ml-cv-lead's recommendations; weights now FROZEN).**
     - Corpus mix: 45% PrIMuS/CPM replay (natural distribution, vocabulary-filtered), 30% Bach + Palestrina
       renders (natural distribution, 5 fonts, camera augmentation), 20% targeted selection (at most about 3
       repeats per strip per epoch, fresh augmentation on each draw), 5% negatives (false dots, phantom
       sharps/flats, header-label and lyric crops, crops with no rest drawn).
     - Targeted budget: ties 15% (G1b passed), position/ledger 15% (own class, chosen by note position;
       position errors are taken out of the duration classes), quarter 5% (digital quarter→eighth only), rests
       5% (every duration, plain and dotted, at a minimum count; dotted and sixteenth rests from PrIMuS),
       32nd 2% (track 32nd insertions). The remaining 58% is split by error count with position errors
       removed: sixteenth capped at 12%, half at a 2% floor, cap slack returned pro rata. The tuplet 5% is
       folded pro rata into the error-count classes only. Exact shares are recomputed from `budget_live.json`
       when the sampler is built.
     - Tie targets come from choral renders, not PrIMuS gold (some PrIMuS "ties" are slurs across different
       pitches).
     - Tuplets: `tuplet.3` (optionally `tuplet.2`), position-free, emitted only where the number is drawn;
       Stage 3 scales durations. Built in a later vocabulary-expansion arm together with chords (2 seeds), NOT in
       Phase 2. Source: script-injected triplets in choral MEI. Minimum work now: converter support behind an
       off flag (samples with a drawn tuplet are still refused); tuplets labelled explicitly in the Phase 4 GT
       with no tuplet support pre-registered; `tuplet` added to the SVG check. Meanwhile Stage 4
       `suspected_tuplet` stays a `review_needed` fallback; 6/8 duplets (underfull bar) are a known gap.
     - Blocking before training:
       - every one of the 3,996 CPM IDs is excluded from PrIMuS replay (canary leakage);
       - the synthetic validation split is by piece/melody, not by strip;
       - the Palestrina G1b page is checked before any Palestrina strip is used;
       - CPM replay relabels are hand-checked on a random 30;
       - the DataLoader seeding fix is applied;
       - ml-cv-lead reviews the training code.
     - Not addressed by this retrain: confident-wrong output (BUG-011). The held-out report includes
       confident-wrong rates.
   - **Amendment rule.** The list and weights may change before Phase 2 training starts, only with a written
     reason in this block. After that, no dev-driven changes: new targets come only from a new, separately
     registered dev round. A later dev gain on these targets is not evidence; the held-out report covers every
     class.
   - **Tuplets: blocked on design, nothing implemented.** Stage 3's vocabulary has no tuplet token and the
     converter refuses `<tuplet>` (ConversionError, sample skipped). A decision is needed on: a tuplet-number
     token at its drawn position; bracket handling; output-head expansion; Stage 3 duration scaling; and how
     it interacts with Stage 4's `suspected_tuplet` overflow heuristic.
   - **ml-cv-lead review (2026-09-30): CONDITIONAL GO.** The weights above stay PROPOSED until the user rules on
     these items:
     1. Tie cap: justified, but because the 279 counts slur.start and slur.end separately (each tie error
        about twice), not because ties are plentiful. Make the 15% conditional on the verovio tie path passing
        G1b; if it fails, the tie weight is 0.
     2. note.quarter (#2 class) has no weight. "Augmentation" covers only the 85 quarter→half errors; its 32
        position errors, 63 insertions and 29 digital quarter→eighth are DATA. Weight it or write down why not.
     3. Position errors (eighth P89, half P57) are charged to duration classes that oversampling won't fix.
        Move them to a position/ledger budget.
     4. Cut the 32nd floor to 2-3%: zero dev evidence, and oversampling risks sixteenth→32nd confusion on the
        beam-count axis that already fails. Track 32nd insertions as a regression metric.
     5. Note next to sixteenth's 12.1% that it is one piece and resolution-capped.
     6. State what fraction of the corpus the targeted budget is.
     7. Amendment rule: pre-Phase-2 amendments only for feasibility (G1b failure, render failure, tuplets
        unblocked), never reweighting from a new dev decode. Define now where the tuplet 5% goes (including
        whether ties take a share). G2 and G3 scores on targeted classes are optimistic (targets chosen on
        those pieces). The held-out report includes untargeted classes (quarter, barline) as regression checks.
     - **Head expansion: defer out of the Phase 2 scale-up.** A vocabulary change in the same run confounds G2's
       attribution to data. Batch all vocabulary changes (chords/`<OOV>` matter more than tuplets) into one
       later expansion arm with 2 seeds. New rows start small with bias at the log-prior; the CPM canary is
       scored on the full new vocabulary with new-token emissions counted as insertions (keeps it comparable
       with 0.0562-0.0926). Watch "3" vs meter digits.
     - **Tuplet representation:** a position-free `tuplet.<n>` token in drawn x-order, only when the number is
       drawn. No bracket start/end pair (beamed tuplets usually have none). Group extent from the beam group or
       the next n equal-duration notes; an explicit token applies unflagged, `suspected_tuplet` stays the flagged
       fallback. Add `tuplet` to the automatic SVG check. Check CPM/PrIMuS for drawn tuplets whose gold has no
       tuplet token: replaying them teaches the model to ignore the "3", so exclude or relabel them.
   - **choral-conductor view (2026-09-30):** Stage 4's overflow heuristic is acceptable as a flagged fallback
     but cannot be the tuplet mechanism.
     - Practice: eighth triplets within a beat are by far the most common; quarter triplets over a half-bar
       are common in Filipino and pop arrangements; duplets in 6/8 occur; 5/6-tuplets and nesting are rare.
       Beamed groups usually show the number only; flagged or rest groups get a bracket; publishers drop the
       "3" after the first few groups ("sim."). Tuplets often contain rests or start tied, and often sit in one
       voice only, so the other voices are a cross-check.
     - Stage 3 should scale durations (normal/actual: 2/3 triplet, 3/2 6/8 duplet). An omitted "3" is
       inferred by bar arithmetic when a same-shape group overfills by exactly 1/3 after an explicit tuplet
       earlier in the passage, flagged `tuplet_inferred`. Irregular/nested ratios: flag, don't guess.
     - Stage 4 dangers: 6/8 duplets make an *underfull* bar that the overflow repair never sees; the beat
       alignment check uses a quarter, wrong for 6/8; a hallucinated extra eighth gets "repaired" into fake
       triplets; whole-bar scaling is off-grid. A Stage 4 tuplet scaling no other voice supports should carry
       `review_needed`.
     - Minimum representation: one `tuplet.3` token before the group (optionally `tuplet.2`), extent from the
       beam or from the values summing to one beat/half-bar; no bracket tokens, no nested ratios in v1. Every
       bar summing to the meter in every voice is the validator.
   - **Tuplet recommendation (both reviewers agree):** position-free `tuplet.<n>` (3, optionally 2), emitted only
     where the number is drawn, extent from beam/equal values, Stage 3 scales durations, Stage 4 heuristic kept
     only as a flagged fallback. Not in the Phase 2 scale-up; part of one later vocabulary-expansion arm.
     Still blocked on the user's design decision.

### Phase 1: data engine (CPU, local; Sep 30 - Oct 5)

1. **Build the music → agnostic converter** (music21/MEI → Camera-PrIMuS agnostic tokens), per staff and per
   system.
   - music21 10.5 parses CPM `.mei` notes, durations and beams, but drops key signatures and multirests. The
     converter must add both.
   - **Gate G1:** at least 99% token agreement with CPM's gold `.agnostic` on all 3,996 local CPM samples.
     Below that, labels are noise and nothing downstream is trusted.
   - **Result (2026-09-30): G1 PASS, 99.557%** (`training/music_to_agnostic.py`, gate
     `training/g1_converter_gate.py`, rule tests `tests/test_music_to_agnostic.py`; uncommitted pending review).
     - Method: agreement = 1 - (sum of token edit distances) / (sum of gold tokens), over all 3,995 CPM samples
       that have an `.mei` (one of the 3,996 has none). A refused sample would count its full length as errors.
     - 454 errors over 102,585 gold tokens; 3,639 of 3,995 samples match exactly; 0 refused.
     - Every residual pattern was checked against the CPM image, and each is a gold defect, not a converter
       error. They still count against G1:
       - final barline in gold present or absent regardless of the image: about 297 tokens (226 + 71 samples);
       - grace-note order rotated in gold (e.g. 000100017-17_1_1): about 60;
       - mid-piece `metersign.C` / `C/` drawn but missing from gold: 11;
       - trailing grace notes after the barline, and one scrambled gold (000100648-1_1_1): the rest.
       - Without the barline defects agreement would be about 99.85%.
     - **Limit:** CPM was both the development set and the gate, so the rules (accidental re-engraving, ties
       only between same-pitch notes, fermata at S6 before `slur.end`, key-signature placement per clef) were
       read off the same gold. G1 shows the converter reproduces CPM's engraver; it does not show SATB labels
       are right. That is G1b's job (human check of about 30 rendered SATB strips, 6b).
     - **Verovio dialect** (`dialect="verovio"`, for Phase 1 renders): only `@accid` is drawn (not
       `@accid.ges`); `<tie>`/`<fermata>` control events; `<sb>` splits systems. A continuation system gets
       clef + key and no meter unless the meter changes at the break. Smoke test: 31/31 four-part music21 Bach
       chorales convert on all four staves with the same system count per staff; bwv10.7 labels checked by eye
       against the rendered page. Courtesy glyphs at a system end are not validated (left to G1b). Chords,
       tuplets and tremolos raise `ConversionError`, so the sample is skipped rather than mislabelled.
     - Chorale tenors come in bass or treble clef as the source has them. Treble-8vb for tenor is a rendering
       choice for step 3.
     - Residual attribution was checked per pattern on example samples against their images, not on every
       affected sample.
   - **ml-cv-lead review (2026-09-30): G1 PASS for the `primus` dialect only. GO on steps 2-3 (corpus, Verovio
     rendering); NO-GO on cutting and training until the conditions below are met.**
     - The 99.557% says nothing about the `verovio` dialect's accidental and tie tokens. That path skips the
       re-engraving logic and reads `<tie>` events, so those are untested by G1.
     - A post-hoc split of local CPM means nothing (every sample shaped the rules). The held-out check is the
       full PrIMuS minus the local 3,996 IDs: freeze the converter (commit hash), then run G1 once on a
       pre-registered random ~5k sample before PrIMuS becomes a source. A drop there means the rules fit the local set.
     - **Conditions:**
       - (a) freeze the converter and write its commit hash into the render metadata;
       - (b) run the held-out PrIMuS G1 before PrIMuS is used as a source;
       - (c) no render counts as training data until it passes an automatic SVG check and G1b.
     - **Automatic SVG check, run on every render:** compare Verovio's SVG glyph-class counts (`accid`,
       `keySig`, `meterSig`, `barLine`, `clef`, `tie`, `dots`, `rest`, `mRest`/`multiRest`) with the label token
       counts per (page, system, staff).
     - **G1b (human, 30 strips):** stratified across all 5 fonts, and covering each of these:
       - a key change and a meter change at a system break, with any end-of-system courtesy signature;
       - a tie across a break (`slur.start` at the end of system N, `slur.end` after the clef and key of N+1);
       - an accidental on a tied note continued after the break;
       - accidentals carried within a bar, cancelling naturals, cautionary accidentals;
       - multirests and constructed meter changes;
       - beams across a break;
       - a treble-8vb tenor, labelled from the *drawn* clef with the token Stage 3's tenor rule expects;
       - first-system label text, drawn but not labelled.

       Pass rule: 0 systematic errors. Any fix means a fresh sample of 30.
       Known gaps (user decision 2026-09-30): repeats are stripped from the renders (BUG-040) and beams across a
       break cannot be built (BUG-041), so G1b does not test either.
     - **G1b result (2026-10-01, user hand-check; PASS, 0 systematic errors).** Bach page, seed 2, 30 strips,
       5 fonts, 13 cases, converter sha256 `bdf1531f...` (labels unchanged by the mRest fix). Results are in
       `D:/PiyaNota-training/data/phase1_renders/g1b/g1b_results_user.json`. 26 strips were marked correct. The
       other 4 were flagged for one pattern only: a dot after a line note is labelled one step up
       (`note.half-L3 dot-S3`), where the user expected `dot-L3`. That is the Camera-PrIMuS convention (the dot
       is drawn in the space above), not a converter error. The first 3,000 PrIMuS samples label all 1,988 dots
       after line notes `S`, and all 1,882 dots after space notes at the note's own position. So no fix was made
       and no fresh sample is needed. The Palestrina page (`g1b_palestrina/`, 10 strips, 0 OOV) is still
       unchecked.
     - **CPM replay labels (Phase 2):** replace the final-barline and grace-order gold defects (about 7% of
       samples have the barline defect) with converter output, after checking a random 30 of them against their
       images. This way replay and synthetic strips agree on end-of-strip barlines. Keep the CPM canary scored on
       the original gold, so it stays comparable with the 0.0562-0.0926 range; report the cleaned number only
       as a second figure. Leave the metersign, trailing-grace and scrambled cases (about 20 tokens) alone.
   - **Held-out G1 pre-registration (2026-10-01, written before the run; condition (b)).**
     - PrIMuS (`datasets/primus_dataset`, package_aa 43,594 + package_ab 44,084 = 87,678 samples, each with
       `.agnostic .mei .mid .pae .png .semantic`). All 3,996 local CPM IDs are in PrIMuS. The CRNN trained only
       on the local CPM corpus (90/10 positional split, no persisted ID list), so held-out = PrIMuS minus CPM
       = 83,682 IDs, all with `.mei` and `.agnostic`.
     - Sample: `sorted(random.Random(20261001).sample(sorted(eligible), 5000))`; IDs in
       `D:/PiyaNota-training/data/primus_g1/sample_ids.txt`, full record in `preregistration.json` there.
     - Converter `training/music_to_agnostic.py` sha256 `f96bc2f8...beb098` (uncommitted working-tree file on
       HEAD c77ce7b; condition (a)'s commit hash must be taken when it is committed, and must match this sha).
       Gate script unchanged, sha256 `a6698282...3647e9`, run once with `--corpus` on a copy of the 5,000
       samples' `.mei` + `.agnostic`.
     - Threshold: G1's own, "at least 99% token agreement" (agreement = 1 - edit distance / gold tokens;
       refusals count in full). Below 0.99: stop, PrIMuS is not a source. Residuals are diagnosed, not fixed.
     - Amendment 1 (before any sample was scored): attempt 1 crashed on sample 1 because the copy step also
       copied macOS `._<id>.mei` AppleDouble stubs (in every PrIMuS sample dir) and the gate's `*.mei` glob took
       the stub. No figure was produced. The 5,000 stubs were deleted; IDs, converter, gate and threshold are
       unchanged.
     - Post-run note: the scored run used converter sha256 `f96bc2f8...beb098` (checked immediately before it).
       Afterwards the render agent changed `music_to_agnostic.py` (bar-length tracking; a verovio-dialect mRest
       in a bar of 2+ whole notes becomes `rest.double_whole-L3`), now sha256 `bdf1531f...1da60e`. The change is
       claimed verovio-dialect only; the render agent is rerunning CPM G1 to confirm. The held-out result is
       kept as it stands and not rerun on this sample; condition (a)'s committed hash must be checked against
       whichever version is frozen.
   - **Held-out G1 result (2026-10-01, single scored run): PASS, 99.114%** against the pre-registered 0.99.
     1,223 errors over 137,972 gold tokens; 4,711/5,000 samples exact; 45 refused. Report and log:
     `D:/PiyaNota-training/data/primus_g1/g1_heldout_report.json`, `g1_heldout_run.log`.
     - It sits 0.44 pp below the CPM 99.557%, and the drop is almost all refusals, a rule-coverage gap that CPM
       never exercised (0 refused there): 45 samples with longa durations (`rest dur 'long'` 39, `note dur
       'long'` 6), 851 tokens, 70% of all errors. Without them agreement would be about 99.73%.
     - Other residuals (tokens / samples, diagnosed on examples, not fixed): final barline present/absent in
       gold, the CPM defect family, 181/179; grace-note order, 150/49; gold ties across *different* pitches
       (e.g. 100016949: MEI `tie="i/m/t"` over B-A-B, which the converter's same-pitch rule drops), 34/11;
       `metersign` in MEI but missing from gold, 7/6; other 16/3 (one clef-change placement, one beam form,
       grace accidentals).
     - Implication for sourcing: longa samples are skipped (as refused); PrIMuS gold tie tokens are not purely
       ties, so the converter's labels, not PrIMuS gold, are the label source for any PrIMuS render.
   - **PrIMuS target availability (2026-10-01, all 87,678 gold `.agnostic`; held-out 83,682 in brackets).**
     Samples containing each frozen target: eighth 72,261 (68,941); sixteenth 44,568 (42,543); 32nd 8,202
     (7,763); ties 8,762 (8,274); inline sharp 15,125 (14,338), flat 5,967 (5,606), natural 11,062 (10,517);
     half 34,814 (33,063); dotted notes 49,415 (47,008); whole 9,170 (8,746); meter every sample; dotted rests
     1,725 (1,654). Inline vs key-signature accidentals is split by a heuristic (header run after a clef).
     - **Tuplets: none.** No tuplet glyph type exists in PrIMuS gold (token kinds: clef, accidental, digit,
       note, gracenote, rest, multirest, dot, metersign, fermata, barline, slur), and no `<tuplet>` element
       is in the 5,000-sample held-out MEIs (the 113 `num="3"` hits are multirest counts). PrIMuS cannot source
       tuplets.
     - **Outside the CRNN vocabulary** (`stage3_transcription.VOCAB`, 513 entries): 5,412 gold tokens in 3,065
       samples, 247 distinct. Largest: `rest.quadruple_whole` 1,163, `note.double_whole` 1,015,
       `note.quadruple_whole` 164, grace-note shapes (quarter, half, beamed 1-3, 32nd) about 1,100, and
       out-of-range positions (L8/S8, S-1 and below, S7) for ordinary notes, accidentals and slurs; meter
       digits `digit.1/8/24/5/11/7-L4`, `digit.3/12/6/48-L2` 45. No `rest.double_whole` occurs in PrIMuS gold.
       Samples with any OOV token need dropping or a vocabulary decision. Full list: job tmp
       `primus/vocab.json`.
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

#### Key / time-signature continuity R1-R4 (implemented 2026-09-30; choral-conductor and ml-cv-lead reviewed the rules)

**Rules** (`stage3_clefkey.apply_key_continuity`, `stage3_transcription.decide_mid_changes`; all thresholds pinned
before any held-out decode: quorum = `HEADER_QUORUM` = 3, ClefKeyNet threshold unchanged):
- **R1, system key.** A ClefKeyNet system vote that differs from the carried key is accepted only with a sign:
  the adjacent next system votes the same, the adjacent previous system votes the same, a courtesy signature in
  ≥3 voices of the system before, cancelling naturals in ≥3 voices, or a kept header meter change. A change to
  C with neither naturals nor courtesy needs two signs. Otherwise the old key is held and every strip is flagged
  `key_change_unconfirmed` + `review_needed`, with `key_candidates` [held, vote]. A change on the last system
  (no next system) with no sign is accepted and flagged `key_change_unverifiable`.
- **R2, mid-strip key glyphs.** After a barline, a key-ordered burst (or naturals) directly followed by a time
  signature counts with one glyph; a full cancel may be followed by a restated key.
- **R3, mid-strip meter.** Reported (`mid_strip_meter_change` at quorum, else `mid_strip_meter_unconfirmed`), never
  applied; the meter digits are no longer read as a multirest count.
- **R4, mid-strip key change.** Applied only when ≥3 voices read the same key at the same bar index, then in every
  voice (a voice with no glyphs follows the gate). Below quorum: not applied, `mid_strip_key_change_rejected`.
  `key_change_contradicted` marks a gated change that the next system's key does not confirm.

**Known limits.** R4 needs the same bar index in 3 voices, so a missed barline turns a real change into a flagged
rejection. Courtesy signatures are found only after a barline. `key_candidates` are on events and Stage 3 info
but not yet in the client review item (API contract change, needs backend-lead).

**Validation 1 (synthetic).** 28 token tests in `tests/test_stage3_key_continuity.py` (R1-R4 plus negatives:
multirest count, lone tuplet-like digit, one glyph before a multirest, out-of-order burst, partial cancel).
They test the logic only, not recognition.

**Validation 2 (dev replay, diagnostic only).** E7 greedy tokens, 654 strips / 164 systems (82 per seed), live
header filter, both seeds:
- R4: 0 key candidates, 0 meter candidates, 0 gate firings, 0 strip flags per seed (target 0: met).
- R1: accepted Gaano p6s1 3♭→1♭ (the one real change; sign `next_system`) in both conditions and seeds; held
  Honneur p3s1 at 3♯ (the BUG-037 misread 0) and flagged it, both seeds. No other system changed.
- 5-6 systems per seed have a kept header meter change; none coincides with a key vote change.
- This is dev data with 1 real change and 1 misread: it shows no false firing, not recall.

**Validation 3 (pre-registered here, before any held-out decode).** On the Phase 4 held-out set, each seed
separately, both strip-source arms, R1-R4 on vs off (off = `apply_key_continuity` and the gate skipped):
- Per-system key accuracy against GT.
- 2×2 table: R1 accepted / held changes vs GT change real / not real; the same for R4 gate vs GT mid-strip changes.
- End-to-end pitch accuracy delta (on minus off) and the count of each new flag.
- **Pass rule:** R1-R4 stay on only if the number of *unflagged* wrong-key systems does not increase in either
  seed. A held real change counts as a wrong-key system only if unflagged (it is always flagged by construction).
- Recall on real changes is measured on a separate synthetic-positive set (Phase 1 renders with key and meter
  changes, both at system breaks and mid-strip), never on the held-out photos.
- No threshold or evidence rule changes after the held-out decode; a change after that needs a new held-out set.

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
