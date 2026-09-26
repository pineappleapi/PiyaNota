# PIYA-106 - Real-photo CRNN accuracy: root-cause diagnosis and reference-project comparison (2026-09-26)

Status: advisory analysis by ml-cv-lead. Read-only: no repo code was changed, nothing was trained, the GPU was not
used. The only computation was a few CPU image/label statistics (listed under "Measurements made for this note").
Not committed. Branch `piya106/groundtruth-eval`.

## How to read this note

- Every "expected gain" below is a hypothesis. **No gain in this note is measured.**
- The DSMN numbers are a 23-strip, single-annotator diagnostic (CIs roughly +/-10 points). They are quoted as a
  diagnostic, not as accuracy evidence, per CLAUDE.md. The two fine-tuned seeds are always quoted as a range.
- Confidence tags: **CONFIRMED** = directly measured/observed in the repo's own data or code; **PLAUSIBLE** = consistent
  with evidence, not isolated by a controlled test; **GUESS** = reasoned from architecture or the references, no data.
- DSMN, Both Sides Now (BSN) and `piyanota_dataset` are TEST-only. Nothing recommended here tunes on them.

## Headline

1. The clef is the dominant *pitch* error (pitch 10.6-11.4% -> 86-88% with GT clef substituted, seeds as a range),
   but the clef is not the dominant *SER* error. Token SER stays 44.3-47.9% and duration-only event SER is about
   19-22% (both from `data/eval_dsmn/REPORT.md`). Fixing the clef alone might approach the SOW pitch threshold
   (85%); it cannot be expected to approach the SER <= 15% threshold. These are two different problems.
2. The 4-font Verovio fine-tune did not move the clef (2-3/23 correct) while the held-out-font probe
   (`loo_font_ser`, Leland) is 5-9%. Inference: glyph *shape* is no longer the main residual gap; the remaining gap is
   layout/context/capture, or the fine-tune was too weak to move the clef. Under the retraining plan's own Step 4
   go/no-go rule ("if clef does not improve ... stop and re-diagnose"), this is the stop condition. It has not yet
   been acted on.
3. There is a cheap, no-retraining lever for the clef (voice prior for S/A/T/B) that the existing Stage 3 already
   half-implements (`CLEF_FALLBACK`). It trades a silent CRNN error for a silent scope assumption, so it must ship
   with an independent verifier flag, not alone.

---

## 1. Ranked root-cause analysis

Ranking is by my estimate of contribution to the *observed real-photo failure*, weighted by strength of evidence.

### R1. Training-data scale and diversity: ~3.6k monophonic incipits, one layout family (CONFIRMED fact; effect PLAUSIBLE)

- Evidence: the local Camera-PrIMuS copy has **3,996** samples (counted); the notebook's base split is 3,596 train +
  399 canary/val (cells 9 and 12). Median 25 tokens per sample, max 54 (counted). First-clef distribution over all
  3,996: G-L2 62.7%, C-L1 23.7%, **F-L4 6.4% (257)**, C-L3 3.1%, C-L4 2.8%, G-L1 0.9%, C-L2 0.3%, F-L3 0.1% (counted;
  matches the BUG-011 note). There is **no** treble-8vb clef token.
- Consequence: every SATB Bass strip is a ~6% class (about 230 training examples) and every real system is a
  polyphonic-context layout the model never saw. The BUG-011 table shows Bass was never predicted correct across 48
  strips, consistent with (not proof of) a rare-class effect.
- The full PrIMuS is ~87k incipits; `training/piyanota-training-ver-2.ipynb` cell 6 references a second Kaggle copy
  (`umerellous/primus`). Base training on ~4% of it is a choice, not a constraint, and is the cheapest scale lever.
- Not isolated: no experiment varies training-set size.

### R2. Context/layout gap around the strip, not the glyph: left-edge content, spacing, and non-CPM symbols (PLAUSIBLE, untested in a controlled way)

- Evidence for "not just glyph": (a) fine-tune on 3 extra fonts + original, evaluated on a held-out real font in CPM
  layout, gives 5-9% SER (`loo_font_ser` in the decision doc), yet real strips give 44-48% SER and clef stays wrong;
  (b) BUG-011 found the same wrong token (`clef.C-L3`, base; `clef.C-L1`, fine-tuned) regardless of padding 0.5/0.25/
  0.1/0.0 and regardless of thresholding/dilation/erosion, i.e. a fixed attractor rather than a geometry-sensitive
  misread; (c) the clef is the first symbol decoded, i.e. it sits exactly where real strips carry non-CPM content:
  voice-label text, system-start barline/bracket, page margin (BUG-015 says left-edge labels survive masking by
  design). In CPM the clef always appears at a fixed left offset after a clean margin.
- Caveat on (a): `loo_font_ser` evaluates content the model already saw in other fonts (same stems across fonts; see
  cell 12 comments), so it is optimistic for glyph generalization and says nothing about layout. It is also used for
  best-epoch selection, so its best value is optimistically biased (decision doc, 2026-09-23 amendment).
- Caveat on the label-bleed test: BUG-011's label-blanking experiment was underpowered (n=43, Fisher p~0.5,
  downgraded to inconclusive). Absence of evidence, not evidence of absence.
- Other non-CPM content present in real strips and absent from training: phrase slurs (CRNN "has never seen a phrase
  slur" - CLAUDE.md), dynamics, lyric remnants, fermatas as engraved, key-signature layouts on 4 staves, wider note
  spacing (next item).

### R3. Horizontal density and vertical scale mismatch, with almost no scale augmentation (CONFIRMED measurement; contribution PLAUSIBLE, probably secondary)

- Measured (CPU, this note): after resizing to 64 px height, CPM staff-line spacing has median **8.5 px** (5th-95th
  percentile 7.0-10.0, n=191 sampled). Real Stage 2 strips in `data/step3_testset/strips` (n=60) have median
  **7.5 px** (5th-95th percentile 6.0-8.0); Bass strips reach 5.7 px at the 5th percentile. So real glyphs are
  ~12% smaller at the median and up to ~30% smaller in the tail (the adaptive crop growth from BUG-014 is the
  cause: it grows the crop, then the strip is shrunk to 64 px).
- Measured (6 CPM samples vs 6 real strips): CPM strips at 64 px are ~370-680 px wide for ~26 tokens; real strips are
  ~850-1280 px wide for a similar number of symbols. That is roughly 1.5-1.9x more horizontal pixels per symbol.
  This is a rough figure from small samples; recompute it over the full sets before relying on it.
- Training augmentation covers x-stretch of only 0.9-1.1 (anisotropic) and **no isotropic scale jitter** at all
  (`CameraPrIMuSDataset._augment`). BUG-011's CPM+50%-blank-padding test (100% -> ~20-25%) is a scale/spacing
  brittleness signal in disguise (padding shrinks the glyphs by ~2x); it was interpreted as a padding effect but is
  confounded with scale.
- Why only "probably secondary": the median mismatch is small, and BUG-011's padding sweep on real strips showed no
  recovery when glyph scale was varied via the padding parameter. But that sweep was run on a model that was already
  degenerate at the clef, so it is weak evidence either way.
- Link to BUG-016 finding: resolution ceiling was falsified on CPM (40 px vs native: 0/150 discordant). That test
  varied resolution at fixed content, not scale relative to the training scale. Different variable.

### R4. Clef is one token in an end-to-end sequence with no structural prior, and the model is confidently wrong (CONFIRMED mechanism of impact)

- Evidence: clef confidence AUROC 0.64, mean 0.71 wrong vs 0.74 right (DSMN); BUG-011: 0.79 wrong vs 0.88 right on
  n=2 correct. `infer_pitch()` is clef-relative, so one wrong token gives a uniform, silent offset (observed: Bass +17,
  Tenor +9 semitones on 10-11 of 23 strips).
- The CRNN's clef vocabulary has 8 classes (5 of them C-clef variants) while SATB open-score choir music needs 2-3
  (G-L2, treble-8vb which is G-L2 plus voice identity, F-L4). Everything else is dead probability mass that the model
  collapses into (C-L3 base, C-L1 fine-tuned; C-L1 is the second-most-common training clef at 23.7%, which is
  consistent with the fine-tuned seed shifting to it, but not proof).
- The pipeline already knows the voice (Stage 2 assigns S/A/T/B) and already contains a voice-to-clef map
  (`CLEF_FALLBACK`, stage3_transcription.py ~line 653), used only when no clef token is decoded.
- Note: this explains the *impact*, not the *cause* of the misread. It is the best leverage point because it is the
  point where one wrong token becomes total pitch failure.

### R5. Fine-tune too weak/constrained to test the font hypothesis, and the intervention was never evaluated on clef during training (CONFIRMED design facts; conclusion PLAUSIBLE)

- lr=3e-5, best epoch 1-2, early-stopped by patience or canary hard cap (breached at epoch 3 in one 2026-09-23
  run; ~89% of cap in another). About 13k rows per epoch (3 fonts + original, stem-split). The hard cap is a
  brake set by judgment (3.0x baseline), and the decision docs show it actively stopped runs.
- Checkpoint selection used `loo_font_ser`, a metric that does not measure clef accuracy at all. No clef-accuracy or
  real-domain metric was tracked during fine-tuning. Therefore "font re-rendering does not fix the clef" is **not
  established**; only "this small, brake-limited, font-only fine-tune did not" is.
- The 2026-09-23 amendment records seed identity flipping between runs and up to 1.8x variance in best `loo_font_ser`;
  the DSMN eval also notes an unresolved checkpoint metadata mismatch (seed1 file says epoch 2 / 0.0926 vs doc
  epoch 1 / 0.0523; seed2 file 0.0562 vs 0.0886). Which run each "seed" file came from is unclear, so "seed 1 vs
  seed 2" comparisons on DSMN should be treated as "two checkpoints from this family", not as clean seeds.
  **Resolved 2026-09-26:** the files are the 2026-09-23 run (see that amendment); the file metadata is authoritative.

### R6. Tokenization and decoding: engraver-dependent beam tokens, greedy CTC, no grammar, insertion bias (PLAUSIBLE)

- Evidence: predicted/reference length ratio 1.32; 30% of strips SER > 0.5; duration-only event SER 19-22% vs
  pitch-only event SER ~78-80% (the latter dominated by the clef); BUG-011's manual read found hallucinated
  beamed-sixteenth clusters and missing rests.
- The agnostic vocabulary encodes beam grouping (`beamedLeft/Right/Both1-3`) and staff-position as separate token
  variants. Beam grouping is an engraver/style decision, so token SER over-penalizes rhythm differences that do not
  change audio. Event-level scores (pitch, duration) are the fairer measure for the SOW; the SOW's SER definition
  should be checked (see open questions).
- Greedy decoding with no constraints on clef-first, one clef per strip, key signature contiguity, or barline
  structure (Stage 3's state machine runs after decoding and repairs nothing).

### R7. Architecture detail: vertical average pooling before the BiLSTM (GUESS)

- `CRNN.cnn` ends in `AdaptiveAvgPool2d((1, None))` after 4 pooling steps (64 -> 4 rows), so vertical position is
  averaged away and pitch (staff position) has to be inferred from receptive-field context. The CRNN-CTC reference
  instead flattens channels x height into the LSTM input (128 ch x 8 rows = 1024). No experiment here isolates this;
  pitch-with-GT-clef is 86-88%, so position reading is not the bottleneck on DSMN. Low priority.

### R8. Evaluation-side limits that can distort the diagnosis (CONFIRMED)

- n=23 strips, single annotator, one of four cross-checked strips disagrees with `ground_truth/`; DSMN was used for
  Stage 1/2 mask tuning; the 86-88% "GT clef" figure is a diagnostic upper bound, not a pipeline result;
  base model clef 1/23 vs seeds 2-3/23 is within noise for any inference about the fine-tune.
- Bimodality (30% of strips SER > 0.5) suggests some strips fail for reasons unrelated to the model (residual curl,
  lyric/label remnants). A per-strip post-hoc breakdown of the existing DSMN outputs against strip properties (staff
  spacing, label presence, curl flag) is allowed as a diagnostic and would separate "model" from "crop" failures;
  n is too small to support any fitted rule.

### What I checked and would *not* blame

- Augmentation breadth: our `_augment` (brightness/contrast, shadow gradient, rotation, x-stretch, blur, perspective,
  elastic) is **broader** than the CRNN-CTC reference's (rotation +/-3, contrast, erosion, brightness). Gaps in ours
  are isotropic scale, stroke-width jitter (the reference's erosion thickens ink; BUG-011 observed real clefs are
  bolder), and *context* (labels/margins), not the photometric family.
- Anti-aliasing/threshold/stroke-width preprocessing, padding, and label-length: already falsified or inconclusive in
  BUG-011. Aspect-ratio stretch: isotropic by construction (verified in `_crop_and_resize` and `transcribe_strip`).
- Input resolution at 64 px: falsified on CPM (BUG-011).

---

## 2. Side-by-side comparison

Reference facts are from reading the code in `D:\PiyaNota_OMR_References`. Where the reference ships no data or
weights, that is stated; "n/a" means not comparable.

| Aspect | Ours (PiyaNota Stage 3) | oemer | CRNN-CTC reference (PRAIG) |
|---|---|---|---|
| Paradigm | End-to-end CRNN, one strip -> agnostic token sequence | Two U-Net semantic-segmentation nets (staff/symbols; then noteheads, clefs+accidentals, stems/rests) + classical geometry + sklearn SVMs for clef/accidental/rest class | End-to-end CRNN-CTC, one image -> token sequence |
| Input | Strip, height fixed 64 px, width free (~850-1280 px real, ~370-680 CPM) | Whole page, resized to ~3-4.35 Mpx, 256x256 sliding windows; all geometry normalized by staff `unit_size` (scale-invariant) | Height fixed **128** px, width free, batch zero-padded |
| Backbone | Conv + 5 ResNet blocks, 4 pools (H/16), width /4, `AdaptiveAvgPool` over height | U-Net (dilated, multi-grid, layer-norm) | 4 conv (5x5,5x5,3x3,3x3) BN LeakyReLU, H/16, width /2, **flatten C x H** into RNN (1024-d) |
| Sequence model | 2-layer BiLSTM 256, dropout 0.3 | none (no sequence model; rhythm/pitch by rules) | 2-layer BiLSTM 256, dropout 0.5 |
| Targets/vocabulary | Camera-PrIMuS agnostic, ~500-token frequency-sorted vocab incl. 8 clef tokens, beam-grouped note tokens, staff-position suffixes | Pixel classes from DeepScoresV2/CVC-MUSCIMA colour maps (14 channels); clefs collapsed to **G and F only** | Toy vocabulary in the repo example (7 tokens), user-supplied; no real dataset or weights shipped |
| Clef | Decoded as a token inside the sequence; no prior used unless no token decoded | Blob detected by size/coverage heuristic, class by SVM (gclef/fclef); **default by track parity if none found** (`ClefType(track%2+1)`: G/F) | n/a (task-specific) |
| Key signature | Decoded as accidental tokens; Stage 3 state machine interprets | Counts sharp/flat blobs in the leading region across tracks, majority vote across tracks; consistency check | n/a |
| Pitch | Token suffix (staff position) + clef reference in `infer_pitch()` | Notehead position on staff lines counted in `unit_size` steps from a clef-dependent origin | n/a |
| Rhythm | Token (note.quarter, beamedLeft2...) | Rule-based: notehead fill, stem, beam/flag counting, dot scan, per-track alignment | n/a |
| Augmentation | Brightness/contrast, shadow gradient, +/-3 deg rotation, x-stretch 0.9-1.1, blur/motion blur, perspective (4%), elastic, plus a pre-rendered "distorted" CPM variant at p=0.5. **No isotropic scale, no stroke-width jitter** | Random resize, background colour (hue/sat/value), colour jitter, blur, pixel shuffle, JPEG quality, pixelization, perspective on classifier patches | p=0.6 of: rotation +/-3 deg, contrast (0.5-1.6), **erosion** (3-7 px kernel, 1-3 iters), brightness (0.4-1.5) |
| Training data | ~3.6k CPM incipits (+3 Verovio fonts in fine-tune), monophonic, synthetic | DeepScoresV2 + CVC-MUSCIMA (staff-distortion variants); pretrained checkpoints are downloaded separately and are **not** in the reference folder | Example only (1 sample); trained on user data |
| Optimizer/recipe | AdamW 3e-4, cosine 50 ep, bs 16; fine-tune lr 3e-5 with canary brake | Adam-style TF training on random 256-px crops (train.py) | Adam 1e-3, 200 ep max, bs 16, val every 5 epochs, early stopping on val SER, fp16 mixed |
| Decoding | Greedy CTC; frame-mean softmax "confidence" (uninformative, AUROC 0.64) | Argmax segmentation map + rules | Greedy CTC with **optional vocabulary masking** (logits of tokens outside `test_vocab` set to -inf) |
| Dewarp | Classical staff-curve tracker + per-column remap (Stage 1) | Model-based (predicted staff lines -> dewarp map applied to all predicted layers) | none |
| Polyphony | One voice per strip (open-score assumption) | Multi-voice within a staff and multi-track systems | n/a |
| Uncertainty | None usable; confidently wrong | Rule-based; warnings (e.g. inconsistent key counts across tracks) but no calibrated confidence | None |
| Licence/maintenance | n/a | This copy has no LICENSE file and the README says it is unmaintained (upstream is `BreezeWhite/oemer`); licence to be verified by the human, not decided here | MIT (LICENSE present) |

Observations that matter:

- oemer is scale-invariant *by construction* (unit_size everywhere) and never lets a clef be a free-form token: only
  G/F, with a positional default. Our pipeline lacks both properties.
- The CRNN-CTC reference is architecturally close to ours; it is **not** ahead of us on augmentation or data. Its
  useful ideas are: 2x input height, height-flatten before the RNN, ink-thickening augmentation, and decode-time
  vocabulary masking. The reference cannot tell us about accuracy: it ships no real data or weights.
- Neither reference handles tenor treble-8vb or SATB open score; both would have their own domain gap.

---

## 3. Adoptable approaches, ranked

Ranking is expected gain x plausibility / (effort + risk). All gains are hypotheses.
"Held-out" below means data that is not DSMN, BSN or `piyanota_dataset`, is never used for tuning, and is split by
*piece* (not by strip) from any training source.

### A0 (do first, low effort): controlled single-variable ablation harness on synthetic data, CPU only

- What: take the 399 canary stems (never trained on) and generate variants that change ONE thing each: (1) isotropic
  scale 0.6/0.75/0.9/1.1 of staff spacing; (2) x-stretch 1.5/2.0; (3) prepend a left margin with a printed voice
  label ("S.", "Soprano"), then add a system-start barline; (4) add lyrics/dynamics text under the staff; (5) stroke
  thickening/thinning; (6) 5th Verovio font. Report clef accuracy and token SER per variant on the current
  checkpoints (both seeds and base, as a range).
- Where: new eval script under `training/`; reuses `transcribe_strip`. No GPU needed (399 samples x ~6 variants on CPU).
- Why: this is the controlled comparison BUG-011 has lacked. It converts R2/R3 from "plausible" to measured, and tells
  us which augmentation is worth generating before any GPU is spent.
- Leakage: uses canary stems only (not train stems). No real data touched. Caveat: synthetic proxies; a variant that
  breaks the model on CPM does not prove it explains the real failure.

### A1 (very low effort, likely largest pitch effect): voice-prior clef in Stage 3, with a verifier flag

- What: in `process_strip`/`infer_pitch`, do not let the CRNN clef token decide pitch for the standard SATB layout;
  use the voice prior (Soprano/Alto/Tenor -> G-L2 with Tenor octave shift, Bass -> F-L4) which already exists as
  `CLEF_FALLBACK`. Keep the decoded clef only as a *check*: if the decoded clef family differs from the prior, emit a
  `clef_unsure` flag that Stage 4 and `run_full_pipeline` propagate to FR-14 (this also closes a senior-reviewer
  High finding).
- Expected effect (unmeasured for the pipeline): the DSMN "GT clef substituted" diagnostic (86-88% pitch, seeds as a
  range) is the ceiling *if* the DSMN GT clefs equal the voice prior. That equality must be verified, not assumed
  (check `data/eval_dsmn/gt`). Sub-effect on SER: negligible (one token of ~30).
- Validation without test data: unit tests on synthetic strips; a rule chosen a priori needs no tuning. Report DSMN/BSN
  once as diagnostic. Say explicitly that the rule was motivated by DSMN failures (DSMN is therefore not blind to this
  design decision).
- Risk: the failure moves from a silent CRNN error to a silent scope assumption (a score with an Alto C-clef, a Tenor in
  bass clef, swapped voice order, or a Stage 2 voice mis-assignment produces wrong pitch with no flag). Mitigate only
  with A2.
- Long-term cost: **preprocessing/logic patch**, durable against any font, brittle to any non-standard clef.

### A2 (moderate effort): independent clef (and optionally key-signature) classifier used as verifier

- What: a small, separate classifier on the leading region of the strip (or a detector on the Stage 1 page), classes
  {G, F, C-family, other}, trained on crops whose labels are free: (a) DeepScoresV2 clef annotations (real engraved
  pages, several fonts; the dataset is already in the training workflow via `prepare_deepscore.py`); (b) Verovio renders
  of the CPM clefs in 5 fonts with label/margin/brace context; (c) later, the fresh real set. It is oemer's clef
  approach (blob -> classifier) but trained on our data and restricted to our scope.
- Role: produce the `clef_unsure` signal when it disagrees with the voice prior or the CRNN. Two independent-modality
  models disagreeing is a much better uncertainty signal than CTC frame-mean softmax (AUROC 0.64).
- Validation: DS2 val split (not the DS2 test split, which BUG-004 says still has no valid number and is reserved for
  the detector) and font leave-one-out; then ONE evaluation on the fresh real set (plan Step 3) reporting precision and
  recall of the flag against the true clef, separately from any accuracy number.
- Leakage: split DS2 by score/page, not by crop; keep CPM canary stems held out; never fit a threshold on
  DSMN/BSN. Shared failure risk: if both models are trained on the same synthetic fonts, their errors correlate;
  say so when reporting.
- Note: the local `datasets/` folder is not present in this worktree; DS2 path availability needs confirming.

### A3 (low-moderate effort): scale and aspect normalisation in Stage 2 (oemer's `unit_size` idea), plus scale/stroke augmentation

- What (inference side): Stage 1 already tracks staff lines, so staff spacing is known per strip. Choose the crop
  height so that staff spacing after resize equals the CPM median (~8.5 px at 64 px height), instead of a fixed
  crop-to-64 that shrinks glyphs when the adaptive crop grows (BUG-014). Optionally also normalise horizontal
  spacing (see A4 for the training-side alternative).
- What (training side, bundled into A5): isotropic scale jitter (0.7-1.3), x-stretch 0.7-2.0, ink erode/dilate
  jitter (both directions).
- Expected gain: probably small at the median (12% scale gap), larger on tail strips (Bass); could matter more for
  camera photos at different distances. Unmeasured.
- Validation: A0 quantifies how much the current model cares about scale on CPM. Only if A0 shows real sensitivity is
  the Stage 2 change worth doing.
- Long-term cost: **preprocessing patch** (input normalisation toward the training distribution). Principled (oemer
  does the same), but it does not help features the model has never seen.

### A4 (high effort, needs GPU, highest plausible gain): layout-realistic synthetic data, then retrain/fine-tune with replay

- What: extend Step 1's Verovio re-render so each sample also carries, independently switchable: staff/system label
  text (MEI `<label>`/`<labelAbbr>` on `staffDef`, native to Verovio), system-start barline/bracket, wider
  note spacing (Verovio spacing options), lyrics and dynamics, phrase slurs, several staff sizes, 5 fonts, and
  bass/tenor-range transpositions so F-L4 is not 6% of the data. Use the full PrIMuS instead of the 3,996 subset
  (verify availability, cell 6). Add treble-8vb only via voice identity as now (a new vocabulary token would
  invalidate checkpoints).
- Train with replay (original CPM mixed continuously) rather than a tight canary brake; keep the canary as a monitor
  with a pre-set threshold. Track clef accuracy on a held-out *synthetic-with-layout* set during training and select
  checkpoints on it, not on `loo_font_ser`.
- Ablate one factor at a time (font only, +label, +spacing, +scale, +lyrics/dynamics) with the A0 harness so the
  result says which factor mattered. Do not fold multiple changes into one run and attribute the result to one.
- Leakage/masking risk: augmentation can mask the gap without closing it (a model that learns "labels look like this
  renderer's labels"). Mitigations: hold out an entire *renderer* (e.g. MuseScore/LilyPond output) and a fresh real
  set never used for augmentation design; report CPM and layout-synthetic and real as separate numbers, never
  blended; split by piece across fonts.
- Long-term cost: **data fix**, durable against unseen fonts only to the extent the renderer/layout variety spans the
  deployment set; another engraver or a new template can still fail. More expensive to maintain.

### A5 (high effort, highest fidelity): rendered open-score SATB corpus plus print-and-photograph loop

- What: render open-score SATB from public-domain MusicXML (e.g. the music21 Bach chorale corpus, other CC0
  four-part scores) via MuseScore/LilyPond/Verovio in several styles; cut strips with the existing Stage 1/2 pipeline;
  derive per-strip labels from the MusicXML with a small converter to the agnostic token scheme (exact pitch and
  duration; beam-group tokens need a rule or a beam-agnostic vocabulary decision). Print a subset and photograph
  it with the target phone(s): known labels, true camera domain, no annotator.
- Value: the only route to real capture noise with exact ground truth at scale, and it also fixes "one voice per staff"
  polyphonic context. It also removes the single-annotator problem for at least this part of the evaluation.
- Leakage: split by piece; exclude "Don't Stop Me Now", "Both Sides Now" and "Amanamin" outright; keep one renderer
  and one physical print batch untouched as the final held-out set. The label converter is new code that needs its
  own unit tests, otherwise label errors become invisible training noise.
- Cost: converter (largest piece), rendering and print/photo logistics, and a pipeline run per sample.

### A6 (low effort, opportunistic): decode-time constraints

- What: mask the clef logits to the allowed set (G-L2, F-L4 and, only if in scope, the C-clefs) before argmax at
  clef frames; mask tokens outside the scope vocabulary; optionally require exactly one clef as the first token. The
  CRNN-CTC reference does vocabulary masking in `ctc_greedy_decoder`.
- Expected effect on the clef: unknown. The model is confidently wrong; the correct class may have the second-highest
  logit or a very low one. Read the logit margin on the canary+synthetic sets (A0) before deciding it is useful.
- Note: it changes decoding only, so no checkpoint or vocabulary change. It is a *masking* patch (brittle to scope
  changes) and complements A1, not replaces it.

### A7 (moderate effort, uncertain): use oemer, or its ideas, as a comparator and possible fallback

- What: (a) adopt the **ideas** (unit-size normalisation = A3; positional default clef = A1; key from cross-track vote
  = a cross-voice consistency check on key signature/bar count between the four strips of one system, independent of
  the clef); (b) optionally run oemer as a second opinion on the same *strips' source pages* to compare clef family,
  key and bar count per system.
- Methodology if a go/no-go comparison is run: same pages, same GT, same clef taxonomy (G/F only, Tenor as treble),
  same voice mapping (oemer assigns tracks/groups; map by vertical order within a system), per-strip clef and event
  metrics, pre-registered decision rule, a single look at DSMN/BSN (test only), and note that oemer works on whole
  pages while ours works on strips, so the crops are not identical.
- Domain-gap check: trained on DeepScoresV2 (rendered scores, mostly piano/orchestral) and CVC-MUSCIMA (staff-variant
  synthetic); not on camera photos or choral open-score; has its own dewarp; cannot represent C clefs or tenor 8vb. It
  likely has a *different* domain gap, not none. Pretrained weights are not in the reference folder, so no accuracy
  claim is possible from what is here. Licence and inference cost are human decisions.
- Silent-failure check: oemer warns on inconsistent key counts but has no calibrated confidence. A model swap that
  is confidently wrong is the same failure class as BUG-011.
- Not recommended as a wholesale swap on current evidence.

### A8 (only if A0/A4 point to it): architecture changes

- Height 64 -> 96/128 and flatten channels x height before the BiLSTM (the CRNN-CTC reference design). Requires
  training from scratch, so it needs the A4 data first. BUG-011 already falsified resolution as a cause on CPM;
  gain is a guess.

---

## 4. What I would NOT do

- Do not present the DSMN "GT clef substituted" 86-88% as achieved accuracy, and do not tune the clef rule, flag
  thresholds, or Stage 4 priors on DSMN/BSN/`piyanota_dataset`.
- Do not average the two fine-tuned seeds or pick the better one; do not rank seeds (identity flipped across runs, and
  the checkpoint metadata mismatch is unresolved).
- Do not run more LR sweeps or font-only fine-tunes chasing `loo_font_ser`. That metric is content-leaked (same stems
  in other fonts), optimistically biased by best-epoch selection, single-font, and blind to clef.
- Do not add more fonts as the next step before A0 shows the font is still the bottleneck; the current evidence says it
  is not.
- Do not trust or gate on the CTC frame-mean confidence (AUROC 0.64).
- Do not blend CPM, layout-synthetic and real numbers into one aggregate, and do not count the 48 BUG-011 strips as
  clean test data any more (they were used to develop many hypotheses).
- Do not swap models (oemer or a Sheet-Music-Transformer-style model) on n=23 evidence, and do not rewrite the
  vocabulary (removing C-clef tokens) in place: it invalidates every checkpoint. Use decode masking (A6) instead.
- Do not treat A1 as closing BUG-011: it hides the clef failure for standard scores and leaves SER at 44-48%.
- Do not move to hand-labelling real strips (plan Step 5) until A0 and A5's rendered-and-photographed data have been
  tried; a human correcting a model draft anchors to the model's mistakes.

## 5. Open questions for the user

**Answered by the user, 2026-09-26:**

- **Q1, clef scope.** C clefs are out of scope. The only clefs to detect are:

  | Voice | Clefs in scope |
  |---|---|
  | Soprano | treble |
  | Alto | treble |
  | Tenor | treble, treble-8vb or bass |
  | Bass | bass |

  So A1's voice prior fully decides the clef for Soprano, Alto and Bass. It does NOT decide Tenor, which still needs
  a treble-vs-bass (G vs F) decision per strip. That decision is a 2-class problem, suited to A2 or decode-time
  masking (A6) restricted to G/F. Treble vs treble-8vb stays handled by the existing tenor octave reference, since
  the CRNN cannot see the small 8. The C-clef caveat on A1 no longer applies.
- **Q6, SER definition.** The SOW SER is **agnostic-token-level**. So the SER <= 15% criterion is measured on this
  token vocabulary, and a clef fix alone cannot meet it (token SER stays around 44-48% with any clef handling). SER
  needs the non-clef work (A0, A4, A5, A6 decode constraints).

Remaining questions (still open):

1. **Scope of clefs.** Is the deployment strictly modern SATB (G, treble-8vb for tenor, F for bass)? If historic
   editions with C clefs are in scope, A1 (voice prior) is unsafe on those and A2 becomes mandatory.
2. **What produced DSMN, BSN and "Amanamin"** (which engraver/font, printed page photographed vs screenshot)? This
   decides which renderers A4/A5 should include and whether a MuseScore/Leland-like style is representative.
3. **New real data (plan Step 3).** Can you supply a fresh, distinct set, and are you willing to do a print-and-photograph
   round of rendered scores (A5)? Both need your phone and time.
4. **Full PrIMuS/Camera-PrIMuS availability.** Is the ~87k set (Kaggle `umerellous/primus`) attachable, and was the
   base run really limited to the 3,996-sample "Copy"?
5. **Which checkpoint is authoritative** given the epoch/`loo_font_ser` metadata mismatch between the files and the
   decision docs; and can the two files be re-hashed against the DSMN eval's `checkpoint_hashes.txt`?
6. **What is the SOW SER definition?** Agnostic-token SER (engraver-dependent beam tokens) or an event-level measure?
   This determines whether SER <= 15% is reachable at all with this vocabulary.
7. **GPU/compute plan.** The GPU is wedged; is Kaggle quota available for A4/A5, and is a CPU-only path acceptable
   for A0-A3 in the meantime?
8. **Second annotator** for the DSMN GT (still open) - required before any reported number is treated as more than a
   diagnostic.

---

## Measurements made for this note (CPU only, read-only, reproducible)

- Counted `clef.*` first-token frequencies and token-length stats over all `*.agnostic` in `D:\CameraPrIMuS - Copy`
  (3,996 files): see R1.
- Staff-line spacing after resize to 64 px on 191 randomly sampled CPM PNGs (seed 1) vs 60 Stage 2 strips in
  `data/step3_testset/strips`: see R3. The peak-detection heuristic (row ink > 50% of width) is crude; staff-spacing
  numbers are approximate. Strip widths are from 6 samples each and should be recomputed on the full sets.
- No model was loaded, no strip was transcribed, no accuracy was computed.

## Files consulted

- `D:\PiyaNota-training\CLAUDE.md`
- `D:\PiyaNota-training\docs\decisions\piya-106-dsmn-heldout-eval-2026-09-26.md`
- `D:\PiyaNota-training\docs\decisions\piya-106-crnn-font-retraining-plan.md`
- `D:\PiyaNota-training\docs\bug-tracker.md` (BUG-011, BUG-014, BUG-016 entries)
- `D:\PiyaNota-training\data\eval_dsmn\REPORT.md`
- `D:\PiyaNota-training\stage3_transcription.py` (CRNN class, `transcribe_strip`, `CLEF_FALLBACK`)
- `D:\PiyaNota-training\stage2_detection.py` (`_crop_and_resize`, `STRIP_HEIGHT`)
- `D:\PiyaNota-training\training\piyanota-training-ver-2.ipynb` (cells 0-12)
- `D:\PiyaNota_OMR_References\CRNN-CTC\` (`nn/crnn/modules.py`, `nn/crnn/model.py`, `utils/data_preprocessing.py`,
  `utils/encoding_convertions.py`, `train.py`, `README.md`)
- `D:\PiyaNota_OMR_References\oemer\` (`README.md`, `oemer/inference.py`, `oemer/constant.py`,
  `oemer/symbol_extraction.py`, `oemer/build_system.py`, `oemer/train.py`, `oemer/classifier.py`)
