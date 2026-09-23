# TrOMR (Polyphonic-TrOMR) — Technical Analysis

Repo analyzed: NetEase's `Polyphonic-TrOMR` (paper: *"TrOMR: Transformer-Based Polyphonic Optical
Music Recognition"*). Inference-only release — the README states "The training code will be open
source later," and no training script, dataset loader, augmentation pipeline, or optimizer/schedule
config exists anywhere in this repo. All statements below about training are inferred from the
inference-time preprocessing, the model's loss functions (present in `model/decoder.py` even though
unused at inference), the tokenizer vocabularies, and the README's dataset description — not from a
visible training loop.

## Overview

TrOMR is a single-staff, image-to-sequence OMR model: one cropped staff-line image in, one linear
token sequence out, produced autoregressively by a Transformer decoder cross-attending to a hybrid
CNN+ViT encoder. It is explicitly **polyphonic** — it recognizes chords (simultaneous notes within one
staff, e.g. piano-style multi-note events), not just monophonic single-note-at-a-time lines — but it
is still fundamentally a **single-staff-at-a-time** model: nothing in `tromr/` reasons across multiple
staves, systems, or voices simultaneously. `tromr/inference.py`'s docstring literally says "Inference
single staff image." The repo ships a small entry point (`tromr/inference.py` →
`tromr/staff2score.py::StaffToScore`), a 3-file model package (`tromr/model/`: `encoder.py`,
`decoder.py`, `tromr_arch.py`), a `workspace/` with a pretrained checkpoint
(`img2score_epoch47.pth`, ~86 MB) and four token-vocabulary JSON files, and four worked examples
under `examples/`.

## Architecture

### Encoder — hybrid CNN backbone + ViT (`tromr/model/encoder.py`)

`get_encoder()` builds a **ResNetV2** stem (`timm.models.resnetv2.ResNetV2`, `preact=False,
stem_type='same', conv_layer=StdConv2dSame`) with `backbone_layers = [2, 3, 7]` (from
`workspace/config.yaml`), feeding into `timm.models.vision_transformer_hybrid.HybridEmbed`, which in
turn feeds a `CustomVisionTransformer` (subclass of `timm`'s `VisionTransformer`). This is **not** a
pure ViT-style raw-pixel patch embedding — it's the same "hybrid embedding" pattern as
DeiT-hybrid/TrOCR: a CNN (ResNetV2 stages 2/3/7) downsamples the image first, and the ViT patches
operate on the CNN's feature map rather than raw pixels. `config.yaml` names this `encoder_structure:
hybrid` explicitly (a config knob that implies a non-hybrid mode may have existed at some point, but
only the hybrid path is implemented in this repo).

Config dims: `encoder_dim: 256`, `encoder_depth: 4`, `encoder_heads: 8`, `patch_size: 16`,
`max_height: 128`, `max_width: 1280`, `channels: 1` (grayscale). This is a small transformer — 4
layers, 256-dim — much smaller than a standard ViT-Base (12 layers, 768-dim); combined with the
checkpoint's ~86 MB total size (encoder + decoder + embeddings), TrOMR is a lightweight model by
Transformer-OMR standards.

`CustomVisionTransformer.forward_features()` (encoder.py lines 16-32) does something specific worth
noting: it computes a **custom 2D positional-embedding index** (`pos_emb_ind`) that accounts for the
fact that the actual patch grid width (`w`, image-dependent) is smaller than the model's fixed max
width (`self.width//patch_size`), by striding through a positional-embedding table sized for the full
`max_width` and skipping the unused columns per row. This lets one image-agnostic position-embedding
table serve variable-width staff crops up to `max_width`, while still encoding true row/column
position — important because staff images are extremely wide/short (aspect ratio far from square),
unlike typical ViT inputs.

### Decoder — autoregressive Transformer with 4 parallel output streams (`tromr/model/decoder.py`)

`ScoreTransformerWrapper` (a thin wrapper around `x_transformers.x_transformers.Decoder`, i.e. the
`x-transformers` library's standard causal decoder with cross-attention) embeds and predicts **four
parallel token streams per position** rather than one merged vocabulary:

- `rhythm` — event type + clef + key signature + time signature + barline + duration
  (`num_rhythm_tokens: 260`, see vocab below)
- `pitch` — absolute note name + octave (`num_pitch_tokens: 71`)
- `lift` — accidental state: `lift_null`, `lift_##`, `lift_#`, `lift_bb`, `lift_b`, `lift_N`
  (`num_lift_tokens: 7`)
- `note` — a binary auxiliary stream, `nonote`/`note` (`num_note_tokens: 2`), used only to compute a
  consistency loss, not part of the final output the demo prints

Each stream has its own `TokenEmbedding`; the three real embeddings are **summed** with a shared
`AbsolutePositionalEmbedding` before entering the shared `attn_layers` (`x = self.rhythm_emb(rhythms)
+ self.pitch_emb(pitchs) + self.lift_emb(lifts) + self.pos_emb(rhythms)`, decoder.py line 62) — so
there is one shared Transformer stack, but four separate linear heads (`to_logits_lift/pitch/rhythm/
note`) reading it out, and four separate cross-entropy losses in `ScoreDecoder.forward()`
(decoder.py lines 167-181).

`decoder_args` in `config.yaml` (`attn_on_attn: true`, `cross_attend: true`, `ff_glu: true`) selects
Attention-on-Attention and GLU feed-forward variants from `x-transformers` — standard "make the
decoder stronger per-parameter" tricks, not domain-specific to OMR.

**Consistency loss** (`ScoreDecoder.calConsistencyLoss`, decoder.py lines 183-198): because rhythm,
pitch, and lift are predicted as three independent softmax distributions that must actually agree
about *which positions are notes at all* (rhythm has its own note-vs-non-note subset via
`noteindexes`/`note_mask`; pitch and lift have their own `nonote` token id 0), the model would
otherwise be free to have rhythm say "this is a note" while pitch says "this is nonote." The
consistency loss is an L1 penalty (weighted `gamma=10`) between the three streams' softmax mass on
"is this a note," keeping the three parallel predictions coherent at every step — a structural fix
for a problem specific to multi-stream factorized token prediction, not present in single-vocabulary
OMR decoders like a CRNN-CTC's.

**Generation is full-recompute autoregressive sampling, not greedy/beam, and has no KV cache**
(`ScoreDecoder.generate`, decoder.py lines 95-151): each step re-runs the *entire* growing sequence
through `self.net` (no cached keys/values), applies top-k filtering (`top_k`, thres 0.9) then
temperature-scaled softmax + `torch.multinomial` sampling independently per stream, and stops when
all three EOS-signalling rhythm tokens have fired or `max_seq_len` (256) is reached. `tromr/
inference.py` and `staff2score.py` both default `temperature` low (0.2–0.25) via
`args.get('temperature', .2)`, so output is close to deterministic-argmax in practice but is not
literally deterministic run-to-run — a detail worth flagging for anyone wanting exact reproducibility
in a pipeline (unlike a CTC greedy decoder, which is exactly deterministic given fixed weights).

## Input/Output Representation & Tokenization

### Input

`StaffToScore.readimg()` (staff2score.py lines 30-52): loads with OpenCV, converts to grayscale (3-ch
duplicated then sliced to 1 channel via `alb.ToGray` + `[:1]`), resizes to a **fixed height of 128 px**
(`max_height`) with width scaled proportionally then floored to a multiple of `patch_size=16`, then
normalizes with dataset-derived mean/std `(0.7931, 0.7931, 0.7931)`/`(0.1738, 0.1738, 0.1738)` — a
very bright/high-mean, low-variance normalization consistent with white-background sheet-music scans
(not natural-image ImageNet stats). This is a **single-staff crop pipeline**, structurally identical
in spirit to PiyaNota's Stage 2 strip extraction (`STRIP_HEIGHT = 64`) — both systems assume upstream
staff detection/cropping has already isolated one staff before this model ever sees the image. TrOMR
does not do its own staff detection; that's out of scope for this repo entirely.

### Output — richer than PrIMuS "agnostic," closer to (but not identical to) PrIMuS "semantic"

Compare the demo output strings in `README.md` and `examples/1.txt`:

```
clef-F4+keySignature-CM+note-E3_eighth.|note-C4_eighth.+note-E3_sixteenth|note-D4_sixteenth+...+barline
```

Contrast with Camera-PrIMuS **agnostic** tokens PiyaNota's Stage 3 consumes (`note.quarter-L4`,
`clef.G-L2`): agnostic tokens encode a note's **staff position** (`-L4`, `-S3`) and require a
downstream stateful pass (PiyaNota's `infer_pitch()` clef→keysig→body state machine) to resolve that
into an absolute MIDI pitch, tracking which clef/key is currently active. **TrOMR's `pitch` stream
predicts the absolute note name + octave directly** (`note-C4`, `note-F4#` after merging with `lift`)
— there is no separate staff-position-to-pitch resolution step at inference time; the model has
learned to fuse "where is this glyph vertically on the staff" and "what's the active clef/key" into a
single classification target itself, jointly, per position. This is structurally closer to PrIMuS's
**semantic** encoding (which also encodes absolute pitch rather than staff position) than to agnostic,
though TrOMR's factored 4-stream format (rhythm/pitch/lift/note as parallel vocabularies) is its own
scheme, not a drop-in match for either PrIMuS format.

Key vocabulary facts, read directly from `tromr/workspace/tokenizers/tokenizer_rhythm.json`:
- 10 clef tokens: `clef-C1..C5`, `clef-F3/F4/F5`, `clef-G1/G2` — **no tenor-specific or
  octave-shifted "vocal tenor" clef token** (e.g. no `clef-G2-8vb` equivalent). A plain treble
  (`clef-G2`) is the only G-clef-on-line-2 token available.
- 15 major-key `keySignature-*` tokens (`CM` through `GbM`/`C#M` etc. — majors only, by name, no
  explicit accidental-count encoding, no minor-key tokens).
- Full `timeSignature-*` enumeration (fractions like `4/4`, `6/8`, plus `C`/`C/` for common/cut time)
  — PiyaNota's current pipeline has no explicit time-signature token/handling at all.
- `barline` as its own token — polyphonic *within* one staff is expressed by `|`-separated
  simultaneous notes inside one time-slot, and successive time-slots/events are `+`-separated
  (confirmed by the `tokenizer_*.json` pre-tokenizer rules: `+` is split-and-removed as an event
  delimiter, `|` is split-and-*isolated*, i.e. kept as a real token marking a chord boundary within an
  event).
- `note-<duration>` / `rest-<duration>` / `multirest-<N>` durations, including dotted variants
  (`note-quarter.`) — durations range breve through 128th, plus ~100 distinct `multirest-N` bar-count
  tokens for multi-bar rests, which PrIMuS agnostic/PiyaNota's event schema has no equivalent for.

`tokenizer_pitch.json` is a flat 71-entry table `note-C0` … `note-B9` (all 7 letter names × 10
octaves, no accidental baked in — accidental is entirely the `lift` stream's job) — i.e., pitch class
+ octave is the *only* thing the pitch stream encodes; sharps/flats/naturals are resolved by
elementwise-merging the `pitch` and `lift` streams at post-processing time in `tromr/inference.py`'s
`__main__` block (lines 19-36), which literally string-concatenates `predpitch[j] + lift + "_" +
duration`. This merge step is pure string post-processing done in the demo script, not inside the
model.

## Training Approach & Data Requirements

No training code is in this repo (README: "training code will be open source later"), so the
following is inferred, not observed directly as a script:

- **Loss** (visible in `ScoreDecoder.forward`, decoder.py): sum of four cross-entropies (rhythm,
  pitch, lift, note) plus the weighted L1 consistency loss between streams. Standard teacher-forced
  sequence loss — `rhythmsi = rhythms[:, :-1]`, `rhythmso = rhythms[:, 1:]`, i.e. next-token
  prediction, same as any autoregressive LM.
- **Datasets** (from `README.md`'s Dataset section — no code, description only): three datasets are
  named — **MSD** ("electronic sheet music with clear symbols" — i.e. clean rendered/engraved score
  images, analogous to Camera-PrIMuS), **CMSD-P** ("printed and photographed," described as having
  "rather blurred" symbols and "jagged lines" — i.e. real phone/camera photos of printed scores), and
  **CMSD-S** ("taken on a screen," with "moiré," simulated lighting and jitter effects). The README's
  own framing is explicit: *"These operations make our data very close to the real application
  scenarios."* This is the single most relevant fact in this repo for PiyaNota's current problem
  (BUG-011): TrOMR's authors apparently trained across a synthetic-clean/photographed-print/
  photographed-screen spread deliberately to close exactly the kind of domain gap PiyaNota is
  currently diagnosing (CRNN trained only on one CameraPrIMuS synthetic font collapses on real
  screenshots). None of MSD/CMSD-P/CMSD-S's images, labels, or generation pipeline are included in
  this repo, so it can't be used directly, but the *strategy* (multi-domain training including
  photographed and screen-captured variants of the same ground truth, not just one rendering font) is
  directly transferable as a plan, independent of the architecture.
- **Ground truth format**: the four-stream tokenized event strings described above — presumably
  derived per-staff from MusicXML/MEI-style source via a linearization step, analogous to how
  Camera-PrIMuS derives `.agnostic`/`.semantic` from MusicXML, but the derivation code isn't in this
  repo.
- **No augmentation code is visible** (`albumentations` and `albumentations.pytorch.ToTensorV2` are
  imported and used only for the fixed grayscale+normalize+tensor conversion at *inference* time in
  `staff2score.py`; nothing in the repo constructs an `alb.Compose` with actual augmentation ops like
  rotation/blur/noise). Given CMSD-P/CMSD-S's descriptions, augmentation (or literal separate
  photographing/re-photographing of scores) almost certainly happened during dataset construction, not
  as an on-the-fly transform visible here.
- **Optimizer/schedule**: not present anywhere in this repo — no training script exists to show it.

**Could this directly train on real phone-photo SATB scans?** Architecturally yes — the model expects
a single fixed-height grayscale staff-crop and a token-sequence label, so if PiyaNota had (crop,
label) pairs it's a compatible shape of problem. But there's no released path from
"photograph a page + know its notes" to the label format shown here; whatever ground-truth generation
pipeline produced CMSD-P/CMSD-S's labels is exactly the part NetEase hasn't published.

## Strengths

- **Explicit polyphony support** (chord tokens via the `|` separator) that Camera-PrIMuS
  agnostic/PiyaNota's current pipeline doesn't need for SATB (each SATB voice's staff is monophonic
  by definition) but that demonstrates the token scheme scales beyond single-note-per-onset.
- **Direct absolute-pitch prediction** (pitch+lift streams) sidesteps needing a separate, brittle
  clef/key state-machine pass after decoding — the model itself is responsible for correctly fusing
  visual clef context into every note's absolute pitch class, rather than deferring that to
  post-hoc symbolic logic.
- **Time-signature and multi-bar-rest tokens** exist in the vocabulary — richer coverage of real
  notation than PiyaNota's current event schema, which doesn't carry time signature at all.
- **Small model** (4-layer/256-dim encoder and decoder, ~86 MB combined checkpoint) relative to
  typical Transformer-OMR designs — plausibly practical to run without a beefy GPU, though the
  no-KV-cache autoregressive decode loop (full self-attention recompute per token, up to 256 steps,
  times 3 streams sharing one forward pass) is not optimized for low-latency serving as shipped.
- **Consistency loss** is a clean, transferable idea independent of TrOMR's specific architecture:
  whenever a model factorizes note attributes into multiple parallel prediction heads, an explicit
  loss term keeping "is this position a note" agreed-upon across heads is cheap insurance against the
  heads drifting apart during training.
- **README explicitly names training on photographed and screen-captured data** (CMSD-P, CMSD-S) as
  a deliberate strategy for real-world robustness — validates that this is a known, addressed problem
  in the OMR literature, not a PiyaNota-specific oversight.

## Limitations

- **Training code, datasets, and label-generation pipeline are all withheld** ("training code will be
  open source later" — repo shows no evidence it was ever added). Nothing here is directly
  fine-tunable or reproducible from this repo alone; it's architecture-and-inference-only.
- **No staff/system detection** — TrOMR assumes a pre-cropped single-staff image is handed to it. It
  solves none of PiyaNota's Stage 1/2 problems (deskew, lyric-band blanking, YOLO staff detection,
  SATB voice assignment by vertical position).
- **No cross-staff/multi-voice reasoning** — each staff is transcribed independently; there's nothing
  here about aligning multiple simultaneous staves (e.g. matching up S/A/T/B onsets across four
  separate strips), which PiyaNota's Stage 4 (`stage4_reconstruction.py`) has to solve on its own
  regardless of which per-staff recognizer is used.
- **No tenor-clef-with-implicit-8vb handling visible in the vocabulary** — `tokenizer_rhythm.json`'s
  clef tokens are the 10 standard clef-position tokens with no octave-transposition variant, so the
  exact visual ambiguity behind PiyaNota's BUG-011 root cause (plain treble clef vs. treble-with-
  implicit-8vb used for Tenor, visually indistinguishable) is not something TrOMR's token scheme
  appears to disambiguate either — it would face the analogous risk of predicting a `clef-G2` +
  correct-looking pitches that are actually an octave off for a tenor part, unless its training data
  specifically covered that voice-dependent transposition convention (unknown, not visible from this
  repo).
- **Non-deterministic generation by default** (temperature+top-k+multinomial sampling, no beam
  search, no greedy option exposed) — reproducibility across runs at a fixed checkpoint is not
  guaranteed the way CTC greedy decoding is.
- **No KV-caching in `ScoreDecoder.generate`** — each of up to 256 decode steps reprocesses the whole
  sequence so far through the full decoder stack; this is a real inference-cost concern for anything
  latency-sensitive.
- **Small demo/example set only** — four worked examples (`examples/photo{1..4}.jpg` +
  corresponding `.png`/`.txt`), no quantitative eval numbers (SER/accuracy tables) present anywhere in
  this repo — any accuracy claims live only in the associated paper, not in this code release.
- **Apache-2.0 licensed** (confirmed via `LICENSE`), so architecture ideas or even code could legally
  be adapted into PiyaNota if desired, but doing so would still require building the entire missing
  training pipeline (loss code exists; data, labels, and augmentation do not) from scratch.

## Relevance to SATB Choral OMR

PiyaNota's actual problem, per `CLAUDE.md` and the current bug tracker, is: a CRNN-CTC transcriber
trained on one synthetic Camera-PrIMuS rendering font collapses on real phone-screenshot strips
(BUG-011 — clef recognition 2/48 correct, non-clef output also badly wrong on direct inspection), and
the fix in progress is font-diversity fine-tuning (multi-SMuFL-font re-rendering of the same
CameraPrIMuS `.mei` sources), not yet extended to real photographed content. Against that backdrop:

1. **The architecture doesn't change PiyaNota's core exposure.** TrOMR is, like PiyaNota's CRNN, a
   per-staff-crop recognizer — it inherits whatever domain gap exists between its training images and
   real photos exactly the same way a CRNN does. Swapping architectures (CTC-CRNN → Transformer
   encoder-decoder) doesn't inherently fix a font/rendering domain-gap problem; nothing about
   self-attention vs. CTC makes a model robust to unseen glyph styles it never saw in training. The
   fix has to come from training-data diversity either way — which is exactly the direction PiyaNota's
   retraining plan (`docs/decisions/piya-106-crnn-font-retraining-plan.md`) is already taking.

2. **TrOMR's README is the strongest piece of *external* evidence that PiyaNota's diagnosis and
   remediation strategy are on the right track.** NetEase explicitly describes training across
   clean-rendered (MSD), photographed-print (CMSD-P), and photographed-screen (CMSD-S) domains
   specifically to approximate real deployment conditions — i.e., a published, paper-associated OMR
   system independently converged on "train across multiple rendering/capture domains, not just one
   synthetic font" as necessary for real-world performance. That's directly corroborating for
   PiyaNota's Step 1 font-diversity retraining plan, though TrOMR goes further (actual photographed
   images, not just alternate synthetic fonts) — PiyaNota's own retraining-plan Steps 3+ (collecting a
   real-world test set) point the same direction TrOMR's CMSD-P dataset already represents.

3. **Direct absolute-pitch prediction (pitch+lift streams) is architecturally interesting for the
   SATB clef problem specifically**, because PiyaNota's current design explicitly separates "decode
   glyph tokens" (Stage 3 CRNN, staff-position-relative) from "resolve to MIDI pitch" (Stage 3
   `infer_pitch()` state machine, clef-aware) — and BUG-011's root cause is that the CRNN's *clef*
   token prediction alone collapses, which then poisons the downstream state machine regardless of how
   good the state machine's logic is. A TrOMR-style design collapses that two-stage dependency into a
   single model that must get clef-context-dependent pitch right directly — which could either help
   (no separate brittle post-hoc clef-tracking step to compound errors) or simply relocate the same
   failure mode into the model's joint pitch classification (still needs correct implicit clef
   understanding, just without a legible intermediate token to debug against). Given BUG-011 showed
   the model was "confidently wrong" about clef, not low-confidence, this isn't obviously a net win —
   an opaque joint pitch/clef fusion could make the same failure harder to diagnose, not easier,
   compared to PiyaNota's current architecture where the wrong clef token is at least directly visible
   in the CRNN's decoded output.

4. **Nothing here addresses PiyaNota's actual open-score, one-staff-per-voice, 4-voice layout
   problem.** TrOMR transcribes one staff in isolation and has no concept of "this staff is the Tenor
   voice, expect a treble clef with implicit 8vb" or of aligning four simultaneous staves into
   synchronized parts — that's entirely PiyaNota's own Stage 2 (`VOICE_MAP`, position-based S/A/T/B
   assignment) and Stage 4 (`stage4_reconstruction.py`, per-voice event merging) problem, and TrOMR
   offers no prior art on it one way or the other.

5. **Polyphony support is irrelevant to PiyaNota's SATB use case** — each SATB voice is a single
   melodic line per staff (this is precisely why open-score, one-staff-per-voice SATB is tractable at
   all under a monophonic-per-staff assumption); TrOMR's chord-handling (`|`-joined simultaneous
   notes) solves a problem PiyaNota's domain doesn't have, so it isn't a reason to prefer TrOMR's
   token scheme over a simpler monophonic one.

6. **Practically, adopting TrOMR wholesale would mean re-solving the same training-data problem
   PiyaNota already has**, for a bigger and more complex model (multi-stream Transformer
   encoder-decoder with a from-scratch loss/label pipeline to rebuild, since none of NetEase's
   training code/data ships), without first-party evidence it would generalize any better to open-
   score SATB choral engravings specifically — its published examples and dataset description
   (piano-reduction-style single/grand-staff notation, chord-heavy) are a different notational genre
   than open-score four-voice choral writing. The most actionable takeaway is the *strategy* (train
   across synthetic + photographed-print + photographed-screen domains) rather than the *model*, and
   that strategy is already the direction PiyaNota's own Step 1 (font re-rendering) and Step 3
   (real-world test-set collection) are heading, independent of whether TrOMR's specific architecture
   is ever adopted.
