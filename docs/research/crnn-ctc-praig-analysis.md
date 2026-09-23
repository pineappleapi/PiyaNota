# CRNN-CTC (OMR-PRAIG-UA-ES) — Technical Analysis

Source repo analyzed: `OMR-PRAIG-UA-ES/CRNN-CTC` (single-commit reference implementation,
commit `73f5a7c "CRNN+CTC with training and prediction scripts"`). Read-only research pass;
no files in the cloned repo were modified. All file paths below are relative to the repo root.

## Overview

This is a research-group reference implementation of the generic CRNN+CTC architecture for
Optical Music Recognition, built on PyTorch + PyTorch Lightning + `fire` for CLI plumbing. It
is deliberately dataset-agnostic: the README's entire "Setup" section is a specification for
*how to lay out your own dataset* (`data/gt/<ds_name>/*.txt` + `data/jpg/<ds_name>/*.jpg` +
`data/splits/<ds_name>/{train,val,test}_<fold>.dat`) rather than a description of one fixed
corpus. The repo ships a single, tiny worked example (`example_dataset`, one image/label pair,
one train/val/test split file, each pointing at the same sample) purely to demonstrate the
plumbing, not as a real training set. Crucially, that one example image is a real photograph of
a scanned **medieval/early-music manuscript** (red-ruled staff, black-letter mensural/square
notation, visible ink bleed and stains) — not a synthetic modern-engraving render — which is
itself a signal about what kind of data this codebase is built to be pointed at (see
"Relevance to SATB Choral OMR" below).

This is architecturally the same *family* as PiyaNota's Stage 3 CRNN (`stage3_transcription.py`):
CNN feature extractor → BiLSTM → CTC greedy decode. The comparison below is against PiyaNota's
CRNN as described to me (ResNet-style CNN backbone → 2-layer BiLSTM → CTC) — I did not re-inspect
PiyaNota's source for this task.

## Architecture

Defined in `nn/crnn/modules.py` (`CNN`, `RNN`, `CRNN` classes) and wrapped for training in
`nn/crnn/model.py` (`CTCTrainedCRNN`, a `LightningModule`).

**CNN backbone (`CNN`, `nn/crnn/modules.py:7-54`)** — 4 conv blocks, *not* ResNet-style (no
residual/skip connections, no bottleneck blocks):

| Block | Conv | Channels | BN | Activation | Pool |
|---|---|---|---|---|---|
| 1 | 5×5, `padding="same"`, no bias | 1 → 64 | yes | LeakyReLU(0.2) | MaxPool 2×2, stride 2×2 |
| 2 | 5×5, `padding="same"`, no bias | 64 → 64 | yes | LeakyReLU(0.2) | MaxPool 2×1, stride 2×1 |
| 3 | 3×3, `padding="same"`, no bias | 64 → 128 | yes | LeakyReLU(0.2) | MaxPool 2×1, stride 2×1 |
| 4 | 3×3, `padding="same"`, no bias | 128 → 128 | yes | LeakyReLU(0.2) | MaxPool 2×1, stride 2×1 |

Only the first pooling reduces width (all others are `(2,1)`, height-only), so
`width_reduction = 2**1 = 2` while `height_reduction = 2**4 = 16` (`modules.py:33-34`). This is
the standard CRNN trick of collapsing height aggressively (to compress the staff into a single
"pixel column" of features per timestep) while preserving horizontal resolution, since horizontal
position directly maps to sequence/time order for CTC. Final channel depth is 128
(`self.out_channels = 128`), input is single-channel grayscale (`NUM_CHANNELS = 1`,
`IMG_HEIGHT = 128`, `utils/data_preprocessing.py:9-10`).

**RNN head (`RNN`, `modules.py:57-77`)** — `nn.LSTM(input_size, 256, num_layers=2,
bidirectional=True, batch_first=True, dropout=0.5)`, i.e. a genuine 2-layer BiLSTM (not GRU),
followed by `nn.Dropout(0.5)` and a `nn.Linear(256*2, output_size)` projecting the 512-dim
bidirectional hidden state to vocab logits per timestep.

**CRNN glue (`CRNN`, `modules.py:80-114`)** — reshapes the CNN's `[b, c, h, w]` output to
`[b, w, c*h]` (permute + reshape, `modules.py:105-109`) before feeding the RNN, i.e. each of the
`w` (time) steps sees the full flattened channel×height column as its feature vector
(`rnn_input_size = out_channels * (IMG_HEIGHT // height_reduction) = 128 * 8 = 1024`). Also
supports loading a **pretrained CNN and freezing it** (`freeze_cnn=True` pulls
`model_loaded.model.cnn` and sets `requires_grad=False` on all its params, `modules.py:84-88`) —
a transfer-learning hook for reusing a CNN trained on one dataset/font while fine-tuning only the
RNN+classifier on another.

**Comparison to PiyaNota's CRNN:** both are CNN→BiLSTM→CTC. The concrete difference is the CNN:
this repo's backbone is a flat 4-block plain-conv stack with no residual connections, versus
PiyaNota's described "ResNet-style" backbone (implying skip connections / a deeper receptive
field per block). The RNN head is structurally identical in shape (2-layer, bidirectional) to
what's described for PiyaNota, though this repo's hidden size (256/direction, 512 total) and
explicit `dropout=0.5` in both the LSTM and the post-LSTM layer are visible, verifiable specifics
that would need diffing against PiyaNota's actual `CRNN` class to say more.

**Loss (`model.py:41`):** `torch.nn.CTCLoss(blank=len(self.w2i), zero_infinity=True)` — the
blank token is *appended after* the real vocabulary (index `len(w2i)`), not reserved at index 0
as it is in the *data-side* vocab (see Tokenization below) — worth noting as a place a careless
port could introduce an off-by-one. `zero_infinity=True` guards against `-inf`/NaN loss on
degenerate (too-short-input-vs-target) alignments, standard CTC hygiene.

## Input/Output Representation & Tokenization

**Image preprocessing (`utils/data_preprocessing.py`):**
- Grayscale load (`cv2.IMREAD_GRAYSCALE`), then resized so height is fixed at `IMG_HEIGHT=128`
  px with aspect ratio preserved (`get_image_from_file`, lines 71-79) — width varies per sample
  and is handled by batch-level zero-padding (`pad_batch_images`, `data_preprocessing.py:109-112`)
  plus explicit sequence-length tracking (`xl` in the CTC batch) rather than a fixed input width.
- Pixel values normalized to `[0, 1]` by `/255.0` (line 91). No further channel-wise
  standardization (no mean/std normalization).

**Label format (`utils/encoding_convertions.py`, class `gtParser`):**
- Ground truth is a single line of whitespace-separated tokens per `.txt` file
  (`single_line_data=True`), read verbatim via `f.read().split()`.
- `no_sep_tok=True` strips separator/bracket artifacts (`:`, `-`, `;`, `,`, and anything matching
  `^\[`) that appear to be leftovers from a richer *semantic*-style encoding (e.g. Camera-PrIMuS's
  `-` pitch/duration separators or `[` array delimiters) — i.e. this parser is set up to consume
  an **agnostic-like flat token stream**, not semantic/structured encoding, though the actual
  tokens depend entirely on what's in the `.txt` files for a given dataset.
- The shipped example's tokens (`data/gt/example_dataset/rrTvg_11.txt`: `c4 l2 l1 , l2 , z2 l3 ,
  z2 , ...`) are **not** Camera-PrIMuS agnostic tokens (no `note.quarter-L4` style compound
  strings) — they look like a compact custom shape/position alphabet (`c4`, `l1`/`l2`/`l3`,
  `z1`/`z2`, `Xz1`), consistent with mensural-notation transcription rather than modern
  engraving-style agnostic encoding. This confirms the codebase's tokenization is **fully
  pluggable per-dataset** — the README says as much directly: *"If you use another structure just
  change the dataset class. To change the annotation reading (e.g. tokenization), change
  `encoding_convertions.py`."*

**Vocabulary construction (`utils/ctc_dataset.py`, `CTCDataset.make_vocabulary` /
`check_and_retrieve_vocabulary`, lines 138-173):**
- **Built from the training corpus, not hardcoded.** On first run, it scans every `.txt` file
  referenced by all three split files (train+val+test, `make_vocabulary` line 155 iterates
  `self.split_files`), collects the token set, sorts it, and assigns integer IDs starting at 1
  (`w2i[w] = i + 1`), reserving **index 0 for `<blank>`** (`ctc_dataset.py:170-171`) — note this
  is the *opposite* end from where `CTCLoss` puts blank (`len(w2i)`, i.e. the last index) in
  `model.py:41`+`model.py:36` (`output_size=len(self.w2i)+1`); the two are consistent internally
  (model output has one extra class beyond the vocab, and `<blank>` in `w2i` is never actually
  used as a real class id since the loss's blank index is separately fixed) but is a subtle,
  easy-to-miss asymmetry.
- The resulting `w2i`/`i2w` is cached to `data/vocabs/<ds_name>_ctc_w2i.json` (shipped example:
  `data/vocabs/example_dataset_ctc_w2i.json`, `{"Xz1": 1, "c4": 2, "l1": 3, "l2": 4, "l3": 5,
  "z1": 6, "z2": 7, "<blank>": 0}`) and reused on subsequent runs — the README explicitly warns
  to delete this file if you change the tokenization (`README.md:63`), since it's a cache, not a
  fixed spec.
- A separate `test_vocab` mechanism (`model.py:32-33, 48-52, 78-93`) allows **restricting decoding
  to a known subset of the vocab at inference time**: `ctc_greedy_decoder` masks out
  (`-float("inf")`) any class whose token isn't in a supplied `test_vocab` JSON before taking
  argmax — useful when the training vocab is a superset of what a given target dataset/domain
  should ever produce.

**Decoding (`model.py:78-93`, `ctc_greedy_decoder`):** **greedy only** — `torch.argmax` per
timestep, then `torch.unique_consecutive` to collapse repeats, then blank-index filtering. No
beam search anywhere in `predict.py` or `model.py`.

## Training Approach & Data Requirements

**Data augmentation is the most load-bearing detail here** (`utils/data_preprocessing.py:13-64`,
applied in `get_image_from_file` lines 82-87). For any sample in the `train` split (not `test`,
not `predict`), with 60% probability (`random.random() > 0.4`) the image passes through
`apply_random_filter`, which independently (each gated at its own 50% coin flip, so 0-4 of these
can stack on a single image) applies:

1. **`random_rotation`** — small rotation, `angle = random.uniform(-3, 3)` degrees, via
   `cv2.warpAffine`/`cv2.getRotationMatrix2D` about image center. Models camera/scan skew.
2. **`random_contrast`** — `cv2.convertScaleAbs(image, alpha, beta)` with
   `alpha ∈ [0.5, 1.6]`, `beta ∈ [-20, 20]` — multiplicative gain + additive offset, i.e. broad
   contrast/exposure variation.
3. **`random_erosion`** — `cv2.erode` with a random square kernel (`3`-`7` px) and
   `1`-`3` iterations — thins/degrades strokes, simulating faint ink, low-res scans, or
   over-thresholded binarization eating into glyphs.
4. **`random_brightness`** — `cv2.convertScaleAbs(image, alpha=brightness_factor, beta=0)`,
   `brightness_factor ∈ [0.4, 1.5]` — pure gain, distinct from the contrast op above.

This is a **geometric + photometric augmentation pipeline aimed at scan/camera-capture
artifacts** — rotation (skew), contrast, brightness, and erosion (stroke degradation). It is
explicitly *not* font/glyph-style augmentation: nothing here re-renders the same symbols in a
different typeface, engraving style, or notation system. It is complementary to, not a
replacement for, multi-font training.

**Training loop (`train.py`):**
- CLI via `fire.Fire(train)`, invoked as `python3 train.py -ds_name example_dataset
  -split_number 0` (`train_example.sh`).
- `seed_everything(42, benchmark=True)` at import time (`utils/seed.py`) — seeds `random`,
  `PYTHONHASHSEED`, `numpy`, `torch`, `torch.cuda`, and sets
  `torch.backends.cudnn.deterministic`/`benchmark`. Note `train.py` itself later constructs its
  `Trainer` with `deterministic=False, benchmark=False` (`train.py:108-109`), which overrides the
  cuDNN benchmark flag set by `seed_everything` — full run-to-run determinism is not actually
  guaranteed despite the seeding call. This is directly relevant context given PiyaNota's own
  documented cuDNN-nondeterminism saga (`torch.manual_seed()` not being sufficient without also
  pinning `cudnn.deterministic`/`benchmark`) — this repo has the same latent gap.
- Optimizer: Adam, `lr=1e-3`, `weight_decay=1e-6` (`model.py:57-62`), applied only to
  `requires_grad`-true params (respects `freeze_cnn`).
- Mixed precision (`precision="16-mixed"`), up to `epochs=200` (default), validated every 5
  epochs (`check_val_every_n_epoch=5`), `EarlyStopping` on `val_ser` (Sequence/Symbol Error Rate,
  `min_delta=0.1`, `mode="min"`, `divergence_threshold=100.0`), best checkpoint by `val_ser`
  (`ModelCheckpoint(monitor="val_ser", save_top_k=1, mode="min")`).
- **No curriculum learning, no explicit multi-stage schedule.** The one built-in transfer-learning
  mechanism is the `freeze_cnn`/`model_loaded` path in `CRNN.__init__` (reuse a pretrained CNN,
  train only the RNN+head on a new dataset) — but `train.py`'s `train()` function never actually
  passes `freeze=True` or `model_loaded=...` to `CTCTrainedCRNN`, so **this capability exists in
  the model class but is not wired up or demonstrated end-to-end anywhere in the shipped
  training script.** Using it would require external scripting to load a checkpoint and pass it
  through.
- Metrics: `utils/metrics.py` — `compute_metrics` returns SER (`ser`, normalized Levenshtein
  edit-distance sum over total ground-truth length, ×100) and a sequence-level error rate
  (`seq-er`, fraction of sequences with any error, ×100) — essentially the SER framing PiyaNota
  also uses.

**Training data format/corpus assumption:** the repo assumes exactly the folder convention
described in Overview — nothing here assumes CameraPrIMuS, DeepScoresV2, or any other specific
public corpus by name; the `ds_name` CLI arg and per-dataset vocab caching make it deliberately
corpus-agnostic. The one shipped example is a real scanned manuscript page crop, not a
synthetically rendered score, though with only one sample it can't be taken as evidence the repo
was "trained on real scans" in general — only that its data contract is comfortable with them.

## Strengths

- **Clean separation of concerns**: tokenization (`encoding_convertions.py`), preprocessing
  (`data_preprocessing.py`), dataset/vocab (`ctc_dataset.py`), and model (`nn/crnn/`) are cleanly
  decoupled, and the README explicitly documents the intended extension points (swap
  `encoding_convertions.py` to change tokenization; delete the vocab JSON to force a rebuild).
- **Dataset-agnostic by design** — vocabulary is derived from whatever corpus you point it at,
  not hardcoded to one token set, so the same code trains on wildly different notation systems
  (the shipped example is mensural notation, not modern engraving).
- **Real scan-artifact augmentation baked into the default training path** (rotation, contrast,
  brightness, erosion) applied unconditionally for any dataset dropped into the expected folder
  structure — a project switching corpora doesn't have to remember to add this, it's on by
  default in `get_image_from_file`.
- **Built-in transfer-learning hook** (`freeze_cnn` / `model_loaded`) for reusing a pretrained CNN
  backbone across datasets, even though unused in the example training script.
- **Restricted-vocabulary decoding** (`test_vocab` masking in `ctc_greedy_decoder`) is a simple,
  cheap way to inject domain knowledge (e.g. "this test set can't contain token X") without
  retraining.
- Correct, standard CTC hygiene: `zero_infinity=True`, `unique_consecutive` + blank-stripping
  greedy decode, per-sample sequence-length tracking (`xl`, `yl`) rather than relying on padding
  alone.

## Limitations

- **Greedy CTC decoding only** — no beam search, no language-model rescoring, no lexicon
  constraint (beyond the coarse `test_vocab` masking). For anything with ambiguous local
  token probabilities, this caps achievable accuracy relative to beam-search alternatives.
- **No font/rendering-style augmentation** — the augmentation pipeline addresses
  camera/scan-capture variation (skew, contrast, brightness, erosion) but does not vary glyph
  shape, typeface, or engraving style. If trained on a single corpus's rendering, this offers no
  built-in mechanism to generalize to a different visual font — the exact failure mode PiyaNota
  diagnosed in BUG-011. Augmentation here is orthogonal to, not a fix for, a font domain gap.
- **Transfer-learning path is unused/unverified** — `freeze_cnn`/`model_loaded` exists in
  `CRNN.__init__` but `train.py` never exercises it, so there's no demonstrated recipe (learning
  rate, freeze schedule, data mix) for actually doing the fine-tune.
- **Single, non-representative example dataset** — one image/label pair reused identically as
  train/val/test (`data/splits/example_dataset/{train,val,test}_0.dat` all point at the same
  `rrTvg_11` file). This is purely a plumbing demo; it demonstrates nothing about real-world
  accuracy or generalization and shouldn't be read as an implied benchmark.
- **cuDNN determinism gap**: `seed_everything(42, benchmark=True)` at import time is
  subsequently contradicted by `Trainer(deterministic=False, benchmark=False)` in `train.py`
  itself — reproducibility across runs is not actually guaranteed by the seeding call alone,
  matching the exact class of bug PiyaNota hit and fixed in `finetune()`.
- **No documented handling of multi-staff/multi-voice layout** — this repo operates on
  single pre-cropped strip images with a single flat token sequence per image (matching
  PiyaNota's own strip-based Stage 2→3 boundary), so it offers no reference for the
  system/voice-grouping problem PiyaNota's Stage 2 (`VOICE_MAP`, SATB layout assumptions) solves;
  that's out of scope here entirely.
- **No hyperparameter search infrastructure, no explicit config file** — parameters (epochs,
  patience, batch size, LR, weight decay) are CLI flags or hardcoded in `model.py`'s
  `configure_optimizers`, not centralized/versioned config.

## Relevance to SATB Choral OMR

This repo is architecturally the closest published reference to PiyaNota's Stage 3 CRNN (same
CNN→BiLSTM→CTC shape, same greedy-decode CTC framing, same SER-style evaluation), which makes it
a useful mirror for diagnosing *why* PiyaNota's from-scratch, single-font CRNN collapsed on real
phone-screenshot input (BUG-011) and what, if anything, this implementation does differently that
could explain more robust real-world generalization.

**What this repo does differently:**

1. **Scan/capture-artifact augmentation is on by default, unconditionally, for any dataset.**
   `apply_random_filter` (rotation ±3°, contrast, brightness, erosion) fires on ~60% of training
   samples regardless of what corpus you point the repo at (`data_preprocessing.py:82-87`). This
   is real, concrete robustness training PiyaNota's current CRNN — per the CLAUDE.md description
   of its training pipeline and the BUG-011 root cause — does not appear to have: BUG-011's root
   cause is specifically a **font/glyph domain gap** (CameraPrIMuS's one synthetic render font vs.
   real engraving fonts), which is a *different failure mode* than what this repo's augmentation
   targets. This repo's augmentation would help with skew/lighting/blur robustness but **would
   not, by itself, have prevented BUG-011** — it never perturbs glyph shape/typeface, only
   capture conditions. This is a useful, concrete data point for the comparison doc: even the
   "closest reference implementation" doesn't solve the font-generalization problem PiyaNota hit;
   it solves an adjacent, complementary problem.

2. **Vocabulary and tokenization are fully pluggable per-dataset, not hardcoded to one
   corpus's token set** (`make_vocabulary` builds from whatever `.txt` files are on disk;
   `encoding_convertions.py` is explicitly designed to be swapped). This is more a *software
   design* strength than an accuracy one, but it does mean the repo carries no implicit
   assumption that the token alphabet must match a specific corpus like Camera-PrIMuS — which is
   relevant if PiyaNota's own retraining plan (multi-font re-render via Verovio, per
   `docs/decisions/piya-106-crnn-font-retraining-plan.md`) ever needs to change or extend its
   token vocabulary; this repo's vocab-caching mechanism (delete the JSON, rebuild from corpus) is
   a clean pattern for that.

3. **The one shipped example is a real scanned manuscript, not a synthetic render** — weak
   evidence (n=1, no training run demonstrated on it) but directionally consistent with training
   corpus diversity being the more central lever than architecture for closing a domain gap: the
   repo's design implicitly expects users to supply their own (potentially real-scan) corpus
   rather than assuming a single synthetic source, unlike PiyaNota's current Stage 3 pipeline
   which (per CLAUDE.md) trains only on CameraPrIMuS's one engraving font today.

4. **Built-in CNN-freeze transfer-learning hook** (`freeze_cnn=True`, reuse a pretrained CNN,
   fine-tune only the RNN) is structurally exactly the kind of mechanism PiyaNota's own
   `finetune()` (per the font-retraining plan in CLAUDE.md) would need, though here it's
   unexercised/unverified in the shipped `train.py`. It's a plausible pattern (freeze CNN, adapt
   RNN+classifier) worth comparing against PiyaNota's actual fine-tuning approach (which, per
   CLAUDE.md, fine-tunes on Verovio multi-font re-renders rather than freezing any sub-network) —
   but this repo offers no evidence either approach is more effective, since neither path is
   benchmarked here.

**What this repo does *not* offer**, worth being explicit about for the comparison doc: no
multi-font/multi-style training strategy, no curriculum learning, no beam search decoding, no
domain-adaptation technique (adversarial, style-transfer, or otherwise), and no evidence
(benchmarked or otherwise) that its augmentation recipe transfers across notation styles or
fonts. Its robustness story is narrowly about scan/camera capture conditions, which is a real but
different axis from PiyaNota's diagnosed font/glyph domain gap. The single most transferable
concrete idea for PiyaNota from this repo is **unconditional, always-on geometric/photometric
augmentation during training** (rotation/contrast/brightness/erosion) as a cheap complement to
the font-diversity fix already underway — it targets a different, additive source of real-world
degradation (phone-camera skew/lighting/scan noise) that the Verovio multi-font re-render plan
does not itself address.
