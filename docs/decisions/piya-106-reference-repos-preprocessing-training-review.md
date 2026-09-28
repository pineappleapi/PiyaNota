# PIYA-106 - Reference OMR repos: preprocessing and training review, and what to integrate into our CRNN-CTC (2026-09-26)

Status: advisory analysis. Read-only on all code (ours and the three references). Nothing was trained, run on the
GPU or run on any test photo. Not committed. Branch `piya106/groundtruth-eval`.

Companion to `docs/decisions/piya-106-accuracy-diagnosis-and-reference-comparison.md` (the "prior doc"). That doc
already covers root causes R1-R8 and plan items A0-A8 at the level of "what oemer / CRNN-CTC do". This note goes one
level down into the actual preprocessing and training code, adds Polyphonic-TrOMR (not covered before), and corrects
two statements in the prior doc (section 6).

## How to read this note

- **Every expected gain in this note is an estimate. None is measured.** Where I give a band (low / medium / high),
  it is a judgement from the code and the literature, not a number from an experiment.
- DSMN, Both Sides Now, Flashlight and everything in `piyanota_dataset` are TEST-only. Nothing proposed here trains,
  tunes, selects a checkpoint or chooses a threshold on them. Each plan item gives a validation route that uses only
  Camera-PrIMuS (CPM), the Verovio font renders, or synthetic data.
- The DSMN numbers quoted below (token SER 44.3-47.9%, pitch 10.6-11.4%, clef 2-3/23, seeds as a range) are a
  23-strip diagnostic, not accuracy evidence (CLAUDE.md policy).
- Scope reminders used throughout: open score only; C clefs out of scope; Soprano/Alto = treble, Tenor = treble,
  treble-8vb or bass, Bass = bass; test photos are MuseScore scores printed and photographed on a phone.
- Code references are `file:line` for `.py` files and "cell N" for `training/piyanota-training-ver-2.ipynb`
  (cell numbering from a `nbformat` dump, 0-based).

## Headline

1. **We train on one kind of image and infer on another.** Training images are anti-aliased grayscale Verovio renders
   or textured `_distorted.jpg` camera simulations (cell 7). At inference, Stage 1 hands Stage 2 a *binarised* strip
   source (`stage1_preprocessing.py` `_build_strip_source`, line 636, adaptive threshold via `_binarize`, line 1309),
   which Stage 2 then shrinks to 64 px with INTER_AREA (`stage2_detection.py:520-561`). No training sample ever looks
   like "adaptive-threshold output, area-shrunk". None of the three references binarise the recogniser's input:
   CRNN-CTC feeds raw grayscale/255, TrOMR feeds grayscale normalised by dataset statistics, and oemer only
   binarises the *segmentation output*, not the network input. This is the cheapest new lever in this note and can be
   measured on CPM without any test photo (plan item P1).
2. **Our validation SER, and therefore every checkpoint we have selected, is measured under a condition Stage 3 never
   runs in.** `ctc_collate` (cell 8) pads each batch with 0.0, which after `(x-0.5)/0.5` normalisation is mid-grey,
   not white (+1.0). `_evaluate_ser` (cell 9) and `_per_sample_ser` (cell 11) then greedy-decode `log_probs[:, b, :]`
   over **all** frames, including the padded tail, and never use `in_lens`. The BiLSTM's backward pass also reads the
   padding before the real frames. Stage 3 transcribes one unpadded strip at a time. So `loo_font_ser`, canary SER and
   base "best distorted SER" all include padding artefacts whose size depends on batch composition. Size of the effect:
   unmeasured; it is cheap to measure (plan item P2). This does not explain the real-photo collapse, but it means our
   model-selection numbers are noisier and possibly biased relative to deployment.
3. **Augmentation is applied after the resize to 64 px and has no scale or stroke-width jitter.** (cell 7,
   `__getitem__` resizes, then `_augment`.) Blur, rotation and elastic distortion at 64 px act on ~8.5 px staff spaces,
   so a 7-px blur kernel is close to a full staff space. oemer jitters scale 0.2-1.2x (`oemer/train.py:170,288`) and
   CRNN-CTC jitters stroke width by erosion (`utils/data_preprocessing.py:53-58`); we do neither.
4. **Polyphonic-TrOMR is the only reference trained on printed-and-photographed scores** (its CMSD-P set, README), and
   its weights are present locally (86 MB, 21.5M parameters) under Apache-2.0. But its training code is not released
   (README line 5), its decoder samples stochastically, it outputs absolute pitch (bypassing our clef-aware
   `infer_pitch()`), its vocabulary has no tie/slur tokens and no octave clef, and it pins 2022 dependencies. It is
   useful as a *comparator*, not as a drop-in (plan item P8, section 4).
5. **Neither reference that reads clefs can tell treble from treble-8vb.** oemer classifies only `gclef`/`fclef`
   (`oemer/classifier.py:259`); TrOMR's rhythm vocabulary has `clef-G1`, `clef-G2`, `clef-F3/F4/F5` and C clefs, no
   octave variants. Our Tenor rule stays a voice-level decision, as the prior doc's A1 proposes. Notably, oemer's own
   fallback when a staff has no detected clef is a *layout prior*, not a model output: `ClefType(track % 2 + 1)`
   (`oemer/build_system.py:239-242`). That is the same idea as our `CLEF_FALLBACK` voice prior, used by a working
   system.

---

## 1. Per-repo review

### 1.0 Ours (baseline for comparison)

**Inference preprocessing (Stages 1-3).**

| Step | Where | Parameters |
|---|---|---|
| Downscale for detection, keep native copy | `stage1_preprocessing.py` `preprocess_score_page` (431-633) | `DETECT_MAX_DIM` 1600; native capped at 4032 |
| Perspective quad correction | same | page quad |
| Illumination normalisation | same | dilate 91-px ellipse, divide, blur 3 |
| Denoise | same | `fastNlMeansDenoising` h=7 |
| Binarise | `_binarize` (1309) | adaptive Gaussian, block 31, C 10 |
| Staff tracking, conditional dewarp | `track_staff_curves`, `staff_grid_map` | dewarp only if drift >= 5 px |
| Border and lyric blanking, staff-row restore | same | top 30 / bottom 100 / left 20 / right 80 px |
| Non-staff-ink mask | `non_staff_ink_mask` (360) | gap bridge 0.2 staff spacing |
| Native strip source | `_build_strip_source` (636) | illumination-normalise, blur, dewarp, **adaptive threshold** (block scaled from `STRIP_SOURCE_BLOCK_SIZE_1600`, C 10), mask |
| Crop per staff | `stage2_detection.py` `_content_extent` (457), `_crop_and_resize` (520-561) | pad 0.5-1.5 staff heights (`CROP_MIN_PAD`/`CROP_MAX_PAD`, 393-406), grows to attached ink |
| Resize to model height | `_crop_and_resize` | isotropic to `STRIP_HEIGHT` 64 (line 27), INTER_AREA; **no staff-spacing normalisation** |
| Model input | `stage3_transcription.py` `transcribe_strip` (1557-1617) | BGR to gray (1591), resize to 64 INTER_AREA (1595), `Normalize(0.5, 0.5)` (1599); single strip, no padding |

**Training (Kaggle notebook).**

- Data: CPM "Copy" corpus, ~3.6k training samples after a positional 90/10 split (cell 9). Vocabulary built from the
  corpus with `min_count=2` (cell 4), ~500 frequency-sorted tokens. Fine-tune data: CPM `.mei` re-rendered by Verovio
  with Bravura, Petaluma, Gootville (train) and Leland (leave-one-font-out), cell 2.
- Render options (cell 2, lines 39-50 of the dump): `breaks: none`, all page margins 0, header/footer none, scale 100,
  cairosvg `scale=2.0` on white. Result: tightly cropped single-line incipits with no part label, bracket, brace,
  system-start barline, lyrics or neighbouring staff. The font renders have no `_distorted` variant.
- Loader (cell 7): grayscale, isotropic resize to 64 px (INTER_AREA), then with p=0.5 swap in the CPM `_distorted.jpg`
  (base CPM only), then `_augment`, then `(x/255-0.5)/0.5`.
- `_augment` (cell 7), all applied **after** the resize to 64: contrast 0.6-1.4 and brightness +/-35 (always);
  shadow gradient p=0.3, strength 0.15-0.45; rotation +/-3 deg p=0.3, border 255; x-stretch 0.9-1.1 p=0.3; Gaussian
  or horizontal motion blur, kernel 3/5/7, p=0.35; perspective jitter 4% p=0.3, border 255; elastic alpha 6,
  sigma 4, p=0.35. Absent: isotropic scale jitter, stroke-width jitter, JPEG/compression, binarisation, background
  tint, context (labels/brackets/lyrics/neighbour staves).
- Model (cell 5 = `stage3_transcription.py:1442-1498`): conv stem, ResNet blocks, pools (2,2),(2,2),(2,1),(2,1) so
  H/16 and W/4, then `AdaptiveAvgPool2d((1, None))` (cell 5, dump line 720) to a 512-d vector per frame, 2-layer
  BiLSTM 256 (dropout 0.3), linear, CTC.
- Base training (cell 9): AdamW 3e-4, weight decay 1e-4, cosine over 50 epochs, batch 16, `CTCLoss(zero_infinity)`,
  grad clip 5; checkpoint on distorted-val SER.
- Fine-tune (cells 11-13): AdamW 3e-5, cosine over 6 epochs, patience 3, seeded, cuDNN deterministic, seeded DataLoader
  generator; checkpoint selection on `loo_font_ser`; canary (399 samples) hard cap 3x baseline. **Clef accuracy is never
  measured during training or selection.**
- Collate and evaluation (cells 8, 9, 11): zero padding (= mid-grey after normalisation), `input_lengths = W//4`,
  evaluation decodes all frames including padding (see Headline 2). SER is the per-sample mean of
  `edit_distance / len(gt)` (cell 5 `compute_ser`, cell 9 `_evaluate_ser` line 1063 of the dump).
- Decoding: greedy CTC, no vocabulary mask (`_greedy_ctc_decode_with_confidence`, `stage3_transcription.py:1513`).

### 1.1 CRNN-CTC (PRAIG, `D:\PiyaNota_OMR_References\CRNN-CTC`)

**Preprocessing** (`utils/data_preprocessing.py`):

- Resize to `IMG_HEIGHT = 128` (line 10), aspect preserved (lines 78-79). Only `/255`, no mean/std, no inversion
  (lines 90-91). No binarisation.
- `apply_random_filter` (lines 13-32) runs on the train split only, gated at p=0.6 (line 83); inside, each op fires
  independently with p=0.5:
  - rotation +/-3 deg (35-43) via `warpAffine` with the **default black border** (bug: black wedges on a white page);
  - contrast `convertScaleAbs` alpha 0.5-1.6, beta +/-20 (46-50);
  - **erosion** kernel 3-7, 1-3 iterations (53-58). On dark-ink-on-white images `cv2.erode` grows the dark ink, so this
    is ink thickening, and at 128 px height with 7x7 and 3 iterations it is strong;
  - brightness 0.4-1.5 (61-64).
- `pad_batch_images` pads with zeros, i.e. **black** (109-112). Validation and test run with batch size 1
  (`nn/crnn/model.py`), so padding never reaches evaluation.

**Model and training** (`nn/crnn/modules.py`, `nn/crnn/model.py`, `train.py`):

- 4 conv blocks 5x5x64, 5x5x64, 3x3x128, 3x3x128, BatchNorm + LeakyReLU 0.2; pools (2,2) then (2,1)x3, so height /16,
  width /2 (`modules.py:7-54`). **Flattens channels x height (128 x 8 = 1024) into the RNN** (93-95, 105-110): no
  vertical averaging, so vertical position survives into the sequence model.
- BiLSTM 256 x 2, dropout 0.5, extra Dropout 0.5, linear (57-77). `freeze_cnn` option for transfer (84-88).
- Adam 1e-3, weight decay 1e-6 (`model.py:171-176`); CTC blank = last index, `zero_infinity` (155).
- `ctc_greedy_decoder` masks logits of tokens outside `test_vocab` to -inf before argmax (`model.py:192-207`).
- `seed_everything(42)`, up to 200 epochs, validate every 5, `ModelCheckpoint` on `val_ser`, `EarlyStopping` patience 4
  with `min_delta` 0.1 SER-percent, `precision="16-mixed"` (`train.py:293-397`). Fold-based splits.
- SER is corpus-level: summed edit distance / summed GT length (`utils/metrics.py`), plus sequence error rate.
- Ships a one-sample toy dataset and a 7-token vocabulary. No weights, no real data.

**Better than ours (with evidence):** evaluation is unpadded (batch 1), so val SER matches deployment; C x H flatten
keeps vertical detail that our average pool throws away (R7 in the prior doc, still a guess for our data); stroke-width
augmentation exists; decode-time vocabulary masking exists; corpus-level SER is the standard metric and is less
dominated by short sequences than our per-sample mean.

**Worse than ours:** black rotation border and black padding (both wrong for white-page input); no blur, perspective,
elastic, shadow or camera-simulation data; erosion magnitudes are unsafe if transplanted to 64 px; no determinism
beyond a seed (`benchmark=True`); no data at all to reproduce anything.

### 1.2 oemer (`D:\PiyaNota_OMR_References\oemer`)

oemer is not an end-to-end sequence recogniser. It is two semantic-segmentation networks plus rule-based symbol
assembly plus small sklearn classifiers, so its lessons for us are about scale handling, augmentation and clef
decisions rather than about sequence modelling.

**Inference preprocessing** (`oemer/inference.py`, `oemer/ete.py`):

- Page resized to target 3.0-4.35 Mpx (`inference.py:18-31`). Line 23's guard `3000000 <= pis <= 435000` can never be
  true, so it always resizes (bug).
- Sliding 256x256 windows, step 128, overlapping softmax averaged (`inference.py:34-102`).
- `unet_big` separates staff from symbols; `seg_net` gives stems/rests, noteheads and clefs/keys (`ete.py:154-170`).
- Dewarp from the staff-line prediction (`dewarp.py` `estimate_coords` 255, `dewarp` 282), applied to every layer
  (`ete.py:244-252`).
- All later thresholds are expressed in **unit size** (mean gap between the five line centres,
  `staffline_extraction.py:225-234`), e.g. `CLEF_ZONE_WIDTH_UNIT_RATIO` in `constant.py`, clef box minimum 1.5 unit
  (`symbol_extraction.py:217-235`), clef area ratio > 3.5 unit^2 (238-263). `extract()` raises if unit sizes across
  staves disagree by more than 10% (`staffline_extraction.py:363-366`), a loud failure.
- Clef/key classification: crop the clef-layer region, resize to a fixed 40x70 (`classifier.py:28-29, 220-229`),
  flatten pixels, SVM predicts `gclef`/`fclef` (`classifier.py:259`). Default when a staff has no clef:
  `ClefType(track % 2 + 1)` (`build_system.py:239-242`).

**Training** (`oemer/train.py`, `oemer/classifier.py`, `oemer/models/unet.py`):

- Data: DeepScoresV2 dense pages (`train.py:40-47, 424`); CvcMuscima-Distortions loader exists but is commented out
  (423).
- Photometric augmentation (`preprocess_image`, 50-108): image forced to 1-bit, background recoloured to a random
  paper tint (hue 19-60, sat 0-15%, val 70-100%), colour jitter (brightness 0.7-1.3, saturation 0.5-1.2, contrast
  0.5-1.5), blur radius 0-2, pixel shuffle 0-0.25, **JPEG quality 0-100**, **pixelization ratio 0.3-1.0**.
- Geometric augmentation (`DsDataLoader._preprocess_image`, 278-301): **random resize 0.2-1.2x** (288-293) applied to
  image and label together, then perspective transform sigma 70 (296-299).
- Windows 288x288 (default `win_size`, 413), grid step 0.5 window, shuffled (324-339); empty bottom margin discarded
  (315-323).
- Model: `semantic_segmentation` (unet.py:60-129), dilated multi-grid encoder, dropout 0.4, softmax over classes.
- Loss: sigmoid focal cross-entropy (`train.py:451`); Adam with linear warm-up then stepped decay (369-397), lr 5e-4,
  15 epochs x 1000 steps, early stop on val accuracy.
- sklearn clef/accidental/rest classifiers (`classifier.py:33-97`): patches cut from DS2 segmentation colours, rescaled
  0.6-1.3x, perspective sigma 3, re-binarised, resized to 40x70, plain `svm.SVC()`.

**Weights and licence:** weights ARE present: `checkpoints/unet_big/model.onnx` (70.8 MB) + `weights.h5`,
`checkpoints/seg_net/model.onnx` (38.4 MB), and `sklearn_models/{clef, clefs_sfns, clef_sfn, rests, rests_above8,
sfn}.model`. The local copy has **no LICENSE file**, `setup.py` has no licence field, README line 3 says it is
unmaintained and points to `BreezeWhite/oemer`. Upstream is believed to be MIT but **I did not verify it**. Until
verified, treat this copy as all-rights-reserved: ideas only, no copied code, no redistributed weights. Pins are 2021
(opencv 4.5.3.56, numpy 1.21.2, scikit-learn 0.24.2), and the sklearn `.model` files are pickles tied to that
scikit-learn version.

**Better than ours:** scale invariance by construction (unit size); much stronger scale augmentation (0.2-1.2x on the
page, 0.6-1.3x on classifier patches); compression and pixelization augmentation that simulate phone JPEG; a clef
decision that is a small independent classifier plus a layout prior, rather than one token inside a 500-way sequence
softmax; a loud failure on inconsistent staff geometry.

**Worse than ours / not transferable:** designed around piano/grand-staff layouts (track parity default assumes two
tracks alternating G/F, which contradicts open-score SATB where three of four staves are treble); no octave clef;
TensorFlow + ONNX + pinned 2021 stack; the always-resize bug; no sequence model at all, so no answer to our
SER problem.

### 1.3 Polyphonic-TrOMR (NetEase, `D:\PiyaNota_OMR_References\Polyphonic-TrOMR`)

**Status:** inference-only release. README line 5: "The training code will be open source later." No training
script, no augmentation code, no dataset. Weights `tromr/workspace/checkpoints/img2score_epoch47.pth` present
(86 MB, 261 tensors, 21.5M parameters). Remote `NetEase/Polyphonic-TrOMR`. Licence: Apache-2.0 (LICENSE; the appendix
copyright placeholder is unfilled). The weights' training data (MSD, CMSD-P, CMSD-S per README) has no stated licence.

**Preprocessing** (`tromr/staff2score.py`):

- Input is one staff image (the examples are 144x1000 single-staff crops).
- `readimg` (30-52): BGR to RGB (or alpha channel inverted), resize to height `max_height` 128, width scaled with
  aspect then floored to a multiple of `patch_size` 16 (43-47), default bilinear interpolation.
- `alb.ToGray` + `alb.Normalize(0.7931, 0.1738)` (24-28): **dataset-statistics normalisation of grayscale ink on paper**.
  No binarisation, no thresholding, no denoising.
- `preprocessing` (54-61) is missing `self` and would crash if called (bug); `predict_img2token` (74-82) calls it.
- Positional embedding is sized for `max_width` 1280 (`config.yaml`, `encoder.py:46-47`), so a strip with aspect ratio
  above 10:1 at 128 px height cannot be encoded without splitting.

**Model** (`tromr/model/encoder.py`, `decoder.py`, `tromr_arch.py`, `workspace/config.yaml`):

- Encoder: hybrid ResNetV2 (layers 2,3,7, `StdConv2dSame`) stem feeding a 4-layer ViT, dim 256, 8 heads, 16-px patches
  (`encoder.py:34-55`; config).
- Decoder: 4-layer x-transformers decoder, dim 256, cross-attention, GLU FF, attn-on-attn (`decoder.py:200-217`;
  config). **Factorised output**: each step predicts four parallel heads, rhythm (260 tokens incl. clefs, key and time
  signatures, barline, chord separator `|`), pitch (71: `nonote`, C0-B9), lift (7: accidentals incl. natural), and a
  binary note flag (`decoder.py:36-39`). Input embedding is the sum of the three token embeddings (62).
- Training loss (code present even though the training loop is not): cross-entropy per head plus a **consistency loss**
  forcing "is a note" to agree across rhythm, pitch and lift heads, weight gamma=10 (`decoder.py:153-198`).
- Decoding: autoregressive **sampling**: top-k filter (thres 0.9) then `torch.multinomial` at temperature 0.2
  (`decoder.py:96-151`; `staff2score.py:79-80`). Output is non-deterministic run to run.
- Vocabulary gaps for us: no `tie`/`slur` tokens, no octave clef (`clef-G2` only), pitch is absolute (so the model
  itself decides the clef-to-pitch mapping).
- Pins: torch 1.11.0, transformers 4.20.1, timm 0.6.5, x-transformers 0.29.2, albumentations 1.2.0, einops 0.4.1.

**Better than ours:** trained (per the README) on printed-and-photographed and screen-photographed scores, i.e. the
capture domain we deploy in; grayscale input with no binarisation; 128-px height; factorised heads that separate
"what glyph" from "where on the staff" from "which accidental", with a consistency term; attention over the whole strip,
which can in principle use context (clef position, key signature) that a BiLSTM over averaged columns sees weakly.

**Worse than ours / not transferable:** no training code, so it cannot be fine-tuned on our fonts or SATB layouts
without writing a trainer from scratch; stochastic decoding; absolute pitch output collides with our pipeline contract
(clef-aware rule-based pitch inference in Stage 3/4) and removes the one place where a voice prior can catch a clef
error; no ties; no 8vb; 2022 dependency pins that conflict with our torch 2.x + CUDA 12.1 environment (NFR-11/PIYA-112);
the README's accuracy claims have no numbers in the repo to check.

---

## 2. Side-by-side

| Aspect | Ours (PiyaNota Stage 3) | CRNN-CTC (PRAIG) | oemer | Polyphonic-TrOMR |
|---|---|---|---|---|
| Task shape | Single staff -> agnostic token sequence | Single staff -> token sequence | Page -> segmentation -> rules -> MusicXML | Single staff -> factorised token sequence |
| Input to recogniser | **Binarised** strip, INTER_AREA to 64 px, `(x-0.5)/0.5` | Grayscale, 128 px, `/255` | RGB page, 3-4.35 Mpx, 256 windows | Grayscale, 128 px, width mult. of 16, dataset mean/std |
| Scale normalisation | None beyond fixed height; staff spacing varies with crop | None beyond fixed height | **Unit size** (staff spacing) drives all rules | None beyond fixed height |
| Binarisation | Yes, adaptive (Stage 1) | No | Only on network *output* | No |
| Training data | CPM ~3.6k + 4-font Verovio re-render | Toy example only shipped | DeepScoresV2 dense | MSD + CMSD-P (print+photo) + CMSD-S (screen), not shipped |
| Photometric aug | contrast/brightness, shadow, blur, motion blur | contrast, brightness | paper tint, colour jitter, blur, pixel shuffle, **JPEG**, **pixelize** | unknown (code not released) |
| Geometric aug | rot +/-3, x-stretch, perspective 4%, elastic, all **after** resize | rot +/-3 (black border) | **resize 0.2-1.2x**, perspective sigma 70 | unknown |
| Stroke-width aug | None | **Erosion** 3-7 px, 1-3 iters | None (implicit via pixelize/blur) | unknown |
| Context in training images | None (zero-margin incipits) | None | Full pages | Full staff crops from real scores |
| Architecture | ResNet CNN -> avg-pool height -> BiLSTM x2 | 4-conv CNN -> **flatten C x H** -> BiLSTM x2 | Dilated U-Net + SVMs | ResNetV2 + ViT encoder, Transformer decoder |
| Loss | CTC | CTC | Sigmoid focal CE | CE x4 heads + consistency |
| Optimiser / schedule | AdamW 3e-4 cosine 50 ep; FT 3e-5 cosine 6 ep | Adam 1e-3, 200 ep, ES patience 4 | Adam 5e-4 warm-up + step decay | unknown |
| Batch padding | Zeros = mid-grey; eval decodes padding | Zeros = black; eval batch 1 | Fixed windows, none | n/a at inference |
| Decoding | Greedy CTC, no mask | Greedy CTC + **vocab mask** | Rules | Top-k + **sampling**, T=0.2 |
| Clef decision | 1 token in ~500-way softmax; `CLEF_FALLBACK` voice prior exists | same as ours | **Separate SVM** G/F + **layout prior** fallback | Rhythm-head token, no 8vb |
| Selection metric | Per-sample mean SER on padded batches; no clef metric | Corpus SER, unpadded | Pixel accuracy | unknown |
| Weights available | Yes (ours) | No | Yes (ONNX/h5/pickles) | Yes (.pth, 86 MB) |
| Licence | ours | **MIT** (c) 2025 OMR-PRAIG-UA-ES | **None in local copy**; upstream unverified | **Apache-2.0** (data licence unstated) |

---

## 3. Integration plan, ranked by expected benefit vs effort vs risk

Ranking rule: cheap, inference-only, measurable-on-CPM items first; retraining items next, ordered by how directly they
attack the train/test gap; model swaps last. "Benefit" bands are **estimates, not measured**. Items that duplicate a
prior-doc item say so and add only what is new.

Common validation assets (none use test photos):

- **V-CPM**: the existing CPM positional val split, clean and `_distorted.jpg` (cell 9), plus the 399-sample canary.
- **V-LOO**: the Leland leave-one-font-out renders (cell 12).
- **V-STRIP**: a new synthetic set = V-CPM distorted + V-LOO passed through a *simulated Stage 1/2 strip path*
  (illumination normalise, adaptive threshold block 31 / C 10, INTER_AREA to 64). Built offline on CPU from
  CPM/Verovio only. This is the closest non-test proxy for what Stage 3 actually receives.
- **Clef metric**: first-clef-token accuracy on each set, restricted to in-scope clefs (G-L2, F-L4), reported
  separately from SER. CPM has G-L2 62.7% and F-L4 6.4% of first clefs (prior doc), enough for a per-class number.

All results reported with both fine-tuned seeds as a range, per the retraining plan.

### P1. Measure, then remove, the binarised-input mismatch (NEW) - benefit medium-high (estimate), effort low, risk low

- What: (a) measure SER and clef accuracy of the current checkpoints on V-CPM vs V-STRIP. If V-STRIP is materially
  worse, the binarisation step is costing accuracy on data we have labels for. (b) Add an inference option that cuts
  strips from a *grayscale* illumination-normalised strip source instead of the thresholded one (Stage 1 already
  computes the normalised gray before thresholding inside `_build_strip_source`). (c) Alternatively, or additionally,
  add "Stage-1 path" binarisation as a training augmentation (see P4) so the model has seen that input.
- Why: TrOMR (`staff2score.py:24-28`) and CRNN-CTC (`data_preprocessing.py:90-91`) feed grayscale; oemer binarises only
  model output. Our training data has no binarised samples at all (cell 7).
- Touches: `stage1_preprocessing.py` `_build_strip_source` (636) and `PreprocessedPage.strip_source`;
  `stage2_detection.py` `_crop_and_resize` (520-561). The non-staff-ink mask would need to be applied as a white fill
  on the gray image, not as a binary AND.
- Kaggle retraining: not for (a)/(b). (c) needs retraining.
- Validate without test photos: V-CPM vs V-STRIP on CPU, both seeds. Note CLAUDE.md BUG-016 (binarising at 1600 px
  broke rest strokes) and the prior doc's note that BUG-011 found thresholding "inconclusive": this experiment is the
  reverse direction (removing thresholding) and is measured against labels, not eyeballed.
- Risk: the mask and lyric blanking currently rely on a binary image; a gray strip source may re-admit lyric text or
  shadows. Check with the existing `training/step3_mask_audit.py` style audit on synthetic pages.
- Licence: idea only; nothing reused.

### P2. Make validation match deployment: truncate decoding to `in_lens`, pad with white, and check batch-1 agreement (NEW) - benefit low-medium for accuracy, high for trustworthiness of every future number; effort very low; risk very low

- What: in `_evaluate_ser` / `_per_sample_ser`, decode `log_probs[:in_lens[b], b, :]`; in `ctc_collate`, pad with +1.0
  (white after normalisation) instead of 0.0; add a one-off check that batched SER equals batch-1 SER on V-CPM.
  For training, optionally sort-by-width bucketing to reduce padding, or `pack_padded_sequence` for the BiLSTM.
- Why: CRNN-CTC evaluates at batch 1 (`nn/crnn/model.py`), so its val SER matches inference. Ours decodes padded frames
  and lets the backward LSTM read mid-grey padding, a condition that never occurs in `transcribe_strip`.
- Touches: notebook cells 8, 9, 11 (evaluation code only for the measurement part).
- Kaggle retraining: none for the measurement (re-evaluate existing checkpoints on CPU or Kaggle). The white-padding
  change only helps if a model is trained with it, so it rides along with the next retrain.
- Validate: batched vs batch-1 SER difference on V-CPM and V-LOO for both seeds. If `loo_font_ser` shifts materially,
  record it next to the 2026-09-19 amendment, because checkpoint selection used the padded number.
- Risk: changes the definition of the selection metric; re-baseline canary thresholds after the change, never mix old
  and new numbers.
- Licence: idea only.

### P3. Decode-time vocabulary mask for out-of-scope clefs, with a loud flag (extends prior A6) - benefit medium on pitch (estimate), effort very low, risk medium (silent-failure risk)

- What: at Stage 3 decode, set C-clef logits (`clef.C-*`) to -inf, following `ctc_greedy_decoder`
  (`CRNN-CTC nn/crnn/model.py:192-207`, vectorised rather than its Python loop). Log the unmasked argmax clef and its
  frame probability per `strip_id` alongside the existing `raw_tokens` log line (`stage3_transcription.py`, near 1611).
  If the unmasked argmax was a C clef, raise a `clef_masked` review flag on the strip.
- Why: the observed failure is collapse to `clef.C-L3`, which is out of scope by definition. Masking forces the model's
  best in-scope clef. It does **not** make the clef right, so it must not ship without the flag, and it should be read
  together with the prior doc's A1 voice prior and A2 verifier. oemer's layout-prior fallback
  (`build_system.py:239-242`) is precedent for combining a structural prior with a classifier.
- Touches: `stage3_transcription.py` decode path (1513) and the clef stage of `infer_pitch` (863).
- Kaggle retraining: none.
- Validate: clef accuracy on V-CPM/V-LOO restricted to samples whose GT first clef is G-L2 or F-L4, masked vs
  unmasked. Also count how often the mask changes the decision on those sets.
- Risk: masking converts a visible wrong answer (C clef, detectable as out of scope) into a plausible wrong answer
  (G or F). Without the flag this *reduces* observability. That is why the flag is part of the item, not optional.
- Licence: MIT (CRNN-CTC); idea only, reimplemented in a few lines, attribution comment is sufficient.

### P4. Augmentation rework in the notebook (extends prior A3/A4) - benefit medium (estimate), effort low-medium, risk low-medium

- What, in order of expected value:
  1. **Move geometric/blur augmentation before the resize to 64**, operating at render resolution, so blur and
     elastic are relative to real stroke widths rather than 64-px pixels.
  2. **Isotropic scale jitter** before the final resize: render or crop at a random staff spacing, then resize to 64,
     plus random vertical padding 0.5-1.5 staff heights to match Stage 2's crop variability (`CROP_MIN_PAD`/
     `CROP_MAX_PAD`). oemer: 0.2-1.2x page (`train.py:288`), 0.6-1.3x patches (`classifier.py:55`).
  3. **Stroke-width jitter** both directions, at native resolution only, +/-1 px (erode or dilate with a 2x2 or 3x3
     kernel, one iteration). CRNN-CTC's 3-7 px, 1-3 iteration erosion (`data_preprocessing.py:53-58`) is far too
     strong for us: at 64 px height a staff space is ~8.5 px.
  4. **Stage-1-path binarisation** at p~0.3: illumination normalise + adaptive threshold (block 31, C 10) + INTER_AREA,
     i.e. the exact V-STRIP transform (links to P1c).
  5. **JPEG re-encode (quality 30-95)** and **pixelize / down-up sampling (ratio 0.3-1.0)**, from oemer
     (`train.py:88-101`). Phone photos are JPEG; our set has none.
  6. **Paper tint / background shift** from oemer (`train.py:54-68`), only meaningful if P1 moves inference to gray.
- Why: our set has none of scale, stroke width, compression or binarisation; the references each have at least one.
- Touches: notebook cell 7 (`CameraPrIMuSDataset.__getitem__`, `_augment`). No pipeline code.
- Kaggle retraining: yes (fine-tune from the base, or a base retrain; the ablation harness from prior A0 decides).
- Validate: V-CPM (no regression on clean/distorted, the SOW baseline guard), V-LOO, V-STRIP, and clef metric on all
  three. Change one augmentation family at a time or the effect cannot be attributed.
- Risk: stronger augmentation can lower clean CPM accuracy; the canary hard cap and the "no regression on CPM"
  success criterion both apply. Augmentation magnitudes must be chosen on V-* sets only.
- Licence: ideas only. If `augly` is used directly, it is MIT (a new dependency to pin under PIYA-112).

### P5. Staff-spacing (unit size) normalisation at inference and in training (deepens prior A3) - benefit medium (estimate), effort medium, risk medium

- What: in Stage 2, compute each strip's staff spacing from Stage 1's tracked staff (already available from
  `track_staff_curves`), and scale the crop so spacing equals the training target (CPM median 8.5 px at 64 px, prior
  doc measurement), then pad or crop vertically to 64 instead of squashing the whole crop to 64. Apply the same rule
  when building training images, so train and test share one definition.
- Why: oemer makes every decision relative to unit size (`staffline_extraction.py:225-234`, `symbol_extraction.py`
  217-263) and fails loudly when unit sizes disagree (363-366). Our strips currently land at 7.5 px median spacing vs
  8.5 px in CPM, and the value depends on how far `_content_extent` grew the crop.
- Touches: `stage2_detection.py` `_crop_and_resize` (520-561), `_content_extent` (457); notebook cell 7.
- Kaggle retraining: inference-only first (does V-STRIP with spacing-normalised crops beat V-STRIP without?). A
  matching training change is needed to get the full benefit.
- Validate: V-STRIP built at several random staff spacings, SER and clef metric vs spacing, before and after.
- Risk: ledger-line notes far above/below the staff can be cropped if the fixed-spacing window is too short; measure
  with synthetic ledger-heavy CPM samples. Add a structured log of spacing per `strip_id` (Stage 2 output dims
  already logged).
- Licence: oemer copy unlicensed: reimplement the idea, copy no code.

### P6. Separate clef classifier on the first ~5 staff spaces (deepens prior A2) - benefit high on pitch (estimate), effort medium, risk low-medium

- What: a small CNN (not a pixel-flatten SVM) that classifies {treble, bass, other/none} from a unit-size-normalised
  crop of the strip's left edge, trained on DS2 clef instances (DS2 is already local under `datasets/`) plus Verovio
  renders in 4 fonts. Its output is compared with the CRNN clef token and the voice prior; disagreement raises a
  `clef_disagreement` flag (FR-14 error state), agreement of classifier + voice prior can override the CRNN.
- Why: oemer's clef decision is an independent, tiny classifier on a normalised patch
  (`classifier.py:28-29, 82-96, 220-229`) plus a layout fallback, rather than one token in the sequence. That
  architecture is exactly what isolates the clef from the SER problem. oemer's SVM itself is not reusable (unlicensed
  copy, pickled for scikit-learn 0.24.2, and 40x70 pixel flattening is fragile to position).
- Touches: new module used by `stage3_transcription.py` (`get_clef_reference` 663 / `infer_pitch` 863); training on
  Kaggle or CPU (it is small).
- Kaggle retraining: new small model; the CRNN is untouched.
- Validate: held-out DS2 pages (piece-level split, not patch-level) and V-LOO; report per-class accuracy and the
  confusion rate that would override a correct CRNN clef.
- Risk: treble vs treble-8vb is not visually separable by either reference and probably not by this classifier either;
  Tenor stays a voice-level rule. DS2 licence must be checked before training on it for a shipped model.
- Licence: idea from oemer (unverified licence, so idea only). DS2 data licence: to verify.

### P7. Model-side changes: C x H flatten, 128-px height, freeze-for-transfer (extends prior A8) - benefit uncertain (guess), effort high, risk high

- What: (a) replace `AdaptiveAvgPool2d((1, None))` with a channels x height flatten as in CRNN-CTC
  (`modules.py:93-95, 105-110`); (b) 128-px input height (CRNN-CTC and TrOMR both use 128); (c) during font
  fine-tuning, freeze the BiLSTM and train only the CNN (the reverse of CRNN-CTC's `freeze_cnn`, `modules.py:84-88`),
  because the domain gap is visual while the sequence grammar is unchanged; this may reduce forgetting on the canary.
- Touches: `stage3_transcription.py:1442-1498` and notebook cell 5; (a)/(b) invalidate the current checkpoints.
- Kaggle retraining: yes, base retrain for (a)/(b); fine-tune only for (c).
- Validate: V-CPM, V-LOO, V-STRIP, clef metric; ml-cv-lead gate before starting.
- Risk: (a)/(b) are a full re-baseline of Stage 3 with no evidence yet that pooling is the bottleneck; do only if the
  prior doc's A0 ablation points at it. Also a latency cost (larger frames) against the 2 min/page budget.
- Licence: MIT idea (CRNN-CTC); reimplement.

### P8. TrOMR as an offline comparator only (NEW, related to prior A7) - benefit: diagnostic, not accuracy; effort medium; risk low if kept offline

- What: run the TrOMR checkpoint, with sampling replaced by argmax, in a separate pinned environment on V-CPM and V-LOO,
  converting its semantic output to our agnostic tokens for a like-for-like SER, and report clef accuracy separately.
  If a TrOMR-class model does much better on V-STRIP than ours, that is evidence the gap is model capacity and training
  data, not our preprocessing.
- Why: it is the only reference trained on print-and-photo data (README) with weights available.
- Touches: nothing in the pipeline. A throwaway script outside the stage files.
- Kaggle retraining: none.
- Validate: the comparison *is* the validation. It is a model-swap investigation, so per the review checklist the
  go/no-go measurement (raw clef accuracy from the candidate model, outside the pipeline, on non-test data) must be
  reported before any integration work. Running it on DSMN/BSN/Flashlight would count as model selection on test data:
  don't.
- Risk: its 1280-px positional limit (`config.yaml` `max_width`) means long strips must be split; its vocabulary
  cannot express ties or 8vb; semantic-to-agnostic conversion is lossy and itself a source of error.
- Licence: Apache-2.0 code; weights' training-data licence unstated, so do not ship them. NOTICE obligations apply if
  any code is copied. Dependencies (torch 1.11, transformers 4.20.1) must stay in the separate environment (NFR-11).

### P9. Report corpus-level SER alongside per-sample SER (NEW) - benefit: comparability; effort trivial; risk none

- CRNN-CTC's `utils/metrics.py` sums edit distance and GT length over the corpus; ours averages per-sample ratios
  (cell 5 `compute_ser`, cell 9). Short incipits dominate the per-sample mean. Report both; state which one the SOW
  15% figure is checked against (the prior doc's Q6 fixed it as agnostic-token-level; the aggregation is not fixed).

### Summary ranking

| Rank | Item | Stage / file | Retrain? | Benefit (estimate) | Effort | Risk |
|---|---|---|---|---|---|---|
| 1 | P2 eval matches deployment | notebook cells 8, 9, 11 | No (measure) | Low-med accuracy, high trust | Very low | Very low |
| 2 | P1 binarised-input mismatch | Stage 1 `_build_strip_source`, Stage 2 `_crop_and_resize` | No (a, b); yes (c) | Med-high | Low | Low |
| 3 | P3 clef mask + loud flag | Stage 3 decode, `infer_pitch` | No | Med (pitch) | Very low | Med (needs flag) |
| 4 | P9 corpus SER | notebook, eval scripts | No | Comparability | Trivial | None |
| 5 | P4 augmentation rework | notebook cell 7 | Yes | Med | Low-med | Low-med |
| 6 | P5 unit-size normalisation | Stage 2, notebook cell 7 | Inference first, then yes | Med | Med | Med |
| 7 | P6 separate clef classifier | new module + Stage 3 | New small model | High (pitch) | Med | Low-med |
| 8 | P8 TrOMR comparator | offline script | No | Diagnostic | Med | Low (offline) |
| 9 | P7 architecture | Stage 3 CRNN, notebook cell 5 | Yes (base) | Uncertain | High | High |

P6 has the highest estimated pitch benefit but ranks below cheaper items because P1-P3 cost hours, not days, and P2
changes the numbers every later item will be judged by. P1 and P2 should come before any further retraining.

None of P1-P9 is expected on its own to bring token SER from 44-48% to the SOW 15% target. The prior doc's A4/A5
(layout-realistic synthetic data, rendered SATB print-and-photo loop) remain the only items with a plausible path to
that, and P4/P5 are best folded into them.

---

## 4. What not to adopt, and why

1. **oemer as a pipeline stage, or its code/weights.** The local copy has no licence; the stack is TensorFlow + ONNX +
   2021 pins incompatible with PIYA-112; its rules assume piano/grand-staff tracks (the `track % 2` clef default would
   assign bass to Alto in open score, `build_system.py:239-242`); it recognises no octave clef; and swapping in a
   rule-based recogniser changes Module 1's pipeline contract (CRNN-CTC Stage 3). Use its ideas only (P5, P6).
2. **oemer's page resize (3-4.35 Mpx) and 256-px window tiling.** Irrelevant to fixed-height strips, and its guard is
   broken (`inference.py:23`).
3. **CRNN-CTC's erosion magnitudes, black rotation border and black padding** (`data_preprocessing.py:35-58, 109-112`).
   Wrong polarity for white-page data and far too strong at 64 px. Adopt the idea at +/-1 px only (P4.3).
4. **CRNN-CTC's lr 1e-3 / 200-epoch recipe for our fine-tune.** Our own seed-replicated sweep chose 3e-5 for fine-tuning;
   the reference's numbers are for from-scratch training on a different dataset and have no bearing on that decision.
5. **TrOMR's absolute-pitch output as a replacement for `infer_pitch()`.** It bypasses the clef-aware rule-based pitch
   stage required by the pipeline order and removes the point where a voice prior or clef verifier can raise a flag. A
   clef misread would become a silent, uniformly wrong pitch, which is exactly the BUG-002/BUG-011 failure class.
6. **TrOMR's sampling decoder** (`decoder.py:123-133`, temperature 0.2). Non-deterministic output is unacceptable for a
   pipeline whose results must be reproducible and reviewable; use argmax if it is ever run.
7. **TrOMR as the production model** (a model swap). No training code, so it cannot be adapted to our fonts, SATB layout,
   ties or 8vb; 2022 pins; unstated training-data licence; positional-embedding width limit. Any swap would need the
   full model-swap gate (ml-cv-lead first, go/no-go clef accuracy outside the pipeline, licensing, inference cost,
   NFR-11 pinning).
8. **TrOMR's polyphonic `|` chord grammar as-is.** It is built for piano-style multi-voice staves. Our divisi need is
   narrower and has its own plan (`docs/decisions/piya-106-chord-vocabulary-plan.md`); importing TrOMR's grammar would
   also pull the model toward closed-score reading, which is out of scope.
9. **Any preprocessing or augmentation tuned by looking at DSMN, BSN, Flashlight or `piyanota_dataset` results.** Every
   magnitude in P4/P5 is chosen on V-CPM / V-LOO / V-STRIP only. A single, pre-registered test evaluation happens after
   the choices are frozen.
10. **Binarisation-based fixes applied only at inference** (for example "threshold harder" or "thicken strokes at
    inference"). They widen the train/test gap in P1 rather than closing it. If binarised input stays, the model must see
    it in training (P1c/P4.4).

---

## 5. Open questions for the user

1. P1 changes what Stage 1 hands to Stage 2 (gray vs binary strip source). The non-staff-ink mask, lyric blanking and
   BUG-016 rest handling were all validated on binary output. Are you willing to reopen that Stage 1 work (PIYA-121),
   or should P1 be limited to the training-side fix (P1c/P4.4)?
2. P2 will change the value of `loo_font_ser` and the canary numbers that the 2026-09-19 decision relied on. Should the
   existing seed=1/seed=2 checkpoints be re-scored under the corrected evaluation before Step 3/Step 4 of the retraining
   plan continue?
3. P3/P6 add review flags (`clef_masked`, `clef_disagreement`). Which FR-14 error state should they map to in the app:
   a blocking recapture/review prompt, or a warning on the generated audio?
4. The SOW's 15% SER: per-sample mean or corpus-level (P9)? The two can differ by several points on short strips.
5. P6 would train on DeepScoresV2 clef instances. DS2's licence needs to be confirmed for a shipped model. Do you want
   that checked before any P6 work?
6. oemer's upstream (`BreezeWhite/oemer`) licence is unverified here. Only relevant if anyone wants to reuse its code or
   weights, which this note does not recommend.

---

## 6. Corrections to the prior doc

- The prior doc says the oemer weights are not in the folder. They are: `oemer/checkpoints/unet_big/model.onnx`
  (70.8 MB) + `weights.h5`, `oemer/checkpoints/seg_net/model.onnx` (38.4 MB), and six `sklearn_models/*.model`
  pickles.
- The prior doc's comparison table describes CRNN-CTC augmentation as "p=0.6 of: ...". More precisely, the filter is
  applied with p=0.6 (`data_preprocessing.py:83`) and each of the four operations inside it fires independently with
  p=0.5 (lines 13-32), so any one operation is applied to about 30% of training images and several can stack.

---

## Files consulted

Ours:
- `D:\PiyaNota-training\CLAUDE.md`
- `D:\PiyaNota-training\stage1_preprocessing.py` (431-633, 636, 1309, 360)
- `D:\PiyaNota-training\stage2_detection.py` (27, 393-406, 457, 520-561)
- `D:\PiyaNota-training\stage3_transcription.py` (655, 663, 863, 1442-1498, 1513, 1557-1617)
- `D:\PiyaNota-training\training\piyanota-training-ver-2.ipynb` (cells 2, 4, 5, 7, 8, 9, 11, 12, 13)
- `D:\PiyaNota-training\docs\decisions\piya-106-accuracy-diagnosis-and-reference-comparison.md`

CRNN-CTC (`D:\PiyaNota_OMR_References\CRNN-CTC`): `LICENSE`, `utils/data_preprocessing.py`, `utils/metrics.py`,
`nn/crnn/modules.py`, `nn/crnn/model.py`, `train.py`, `requirements.txt`.

oemer (`D:\PiyaNota_OMR_References\oemer`): `README.md`, `setup.py`, `oemer/inference.py`, `oemer/ete.py`,
`oemer/constant.py`, `oemer/train.py`, `oemer/classifier.py`, `oemer/models/unet.py`, `oemer/staffline_extraction.py`,
`oemer/symbol_extraction.py`, `oemer/dewarp.py`, `oemer/build_system.py`, `oemer/checkpoints/`, `oemer/sklearn_models/`.

Polyphonic-TrOMR (`D:\PiyaNota_OMR_References\Polyphonic-TrOMR`): `LICENSE`, `README.md`, `requirements.txt`,
`tromr/configs.py`, `tromr/inference.py`, `tromr/staff2score.py`, `tromr/model/encoder.py`, `tromr/model/decoder.py`,
`tromr/model/tromr_arch.py`, `tromr/workspace/config.yaml`, `tromr/workspace/tokenizers/*.json`,
`tromr/workspace/checkpoints/img2score_epoch47.pth` (tensor count and parameter total only).
