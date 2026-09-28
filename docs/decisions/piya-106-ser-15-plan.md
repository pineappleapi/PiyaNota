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
- **E4, speck filter** (whiten ink components ≤ A px at CRNN scale before decoding, A in {0, 2, 4, 6, 9}, plus the
  E1b rule): see results below.

<!-- E4 results are filled in when the run finishes -->

## 5. The plan

The error budget sets the order. Camera must lose about 12 pp, and 16 pp of camera SER is note tokens, most of
them rhythm glyphs and insertions. No rule or decoder removes that. The model has to read notes better on
*our* strips, which means more data, the right layout, and our own cutting. Every step has a go/no-go gate.

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
