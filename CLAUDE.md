# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PiyaNota is a mobile Optical Music Recognition (OMR) system — not a proof-of-concept — that converts
photos of **open-score** (one staff per voice) printed SATB (Soprano/Alto/Tenor/Bass) choral sheet
music into four separate per-voice piano audio tracks. Closed-score (2-staff, piano-reduction-style)
SATB is explicitly out of scope. Full stack:

- **Android client** — frontend, captures/uploads score photos and plays back generated audio
- **Python + Flask API** — backend, orchestrates the ML pipeline
- **Python ML pipeline** — YOLOv8 staff detection + CRNN-CTC symbol transcription + MIDI-based
  synthesis (the five `stageN_*.py` scripts documented below)

Success criteria (SER, pitch accuracy, SUS usability score with real choir testing) and full scope
are defined in `docs/sow.md` — see the Documentation & tickets section near the bottom of this file
for the current caveat on that doc's state. There is no `run_pipeline.py` despite the README
referencing one — each stage script is runnable standalone and stage 5 exposes `run_full_pipeline()`
as the closest equivalent to a top-level runner.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# GPU (NVIDIA, CUDA 12.1) — install separately, not via requirements.txt:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
python -c "import torch; print(torch.cuda.is_available())"
```

Audio rendering (Stage 5) additionally needs `midiutil`, `pydub`, `midi2audio`, a system `fluidsynth`
install, `ffmpeg` on PATH, and a piano `.sf2` soundfont — none of these are in requirements.txt.

## Running the pipeline

Each stage's `__main__` block chains itself with everything before it, so you generally just run the
last stage you care about:

```bash
# Stage 1 only — preprocess raw photos
python stage1_preprocessing.py data/raw data/preprocessed

# Stage 2 — preprocessing + YOLOv8 staff detection → strips
python stage2_detection.py --input data/raw --weights staff_detector_files/weights/best.pt --viz

# Stage 4 — full pipeline through SATB reconstruction (no audio)
python stage4_reconstruction.py --input data/raw --weights <crnn_weights> --yolo staff_detector_files/weights/best.pt

# Stage 5 — full pipeline including MP3 synthesis
python stage5_synthesis.py --input data/raw --weights music_symbol_detection/crnn_cameraprimus_transcription.pt \
    --yolo staff_detector_files/weights/best.pt --soundfont soundfont/piano.sf2
```

Training / evaluating the YOLOv8 staff detector:

```bash
python prepare_deepscore.py --ds2 path/to/ds2_dense --out data/staff_dataset   # DeepScoresV2 → YOLO format
python train_staff_detector.py                                                  # trains, then evals
python train_staff_detector.py --eval --weights runs/train/piyanota_staff_detector/weights/best.pt
```

The CRNN-CTC symbol transcriber (Stage 3) is trained separately on Kaggle — this repo only does
inference with it (`stage3_transcription.py` loads a `.pt` checkpoint containing a `model_state` dict
plus an `epoch` field).

There is no test suite, linter, or CI config in this repo.

## Pipeline architecture

Five sequential stages, each a standalone module with its own CLI. Data flows strictly forward;
later stages import functions from earlier ones rather than duplicating logic.

1. **`stage1_preprocessing.py`** — grayscale → denoise → adaptive-threshold binarize → grid
   alignment. `correct_to_grid()` estimates rotation from *both* stafflines (horizontal Hough lines)
   and barlines (vertical Hough lines) and deskews using their average, which is more robust on
   phone photos than staffline angle alone. `blank_lyrics_regions()` blanks the band below each staff
   group to strip lyric text before detection — active in `preprocess_score_image` (this doc
   previously said it was disabled/commented out; verified 2026-09-09 that it has actually been
   active all along, unrelated to the in-progress illumination-normalization/border-blanking rework).

2. **`stage2_detection.py`** — runs a fine-tuned YOLOv8 model (`staff_detector_files/weights/best.pt`)
   to find staff-line bounding boxes on each preprocessed page, then:
   - filters by confidence, caps at 16 boxes/page (4 systems × 4 voices max)
   - sorts top-to-bottom and deduplicates boxes that land on the same staff (`_remove_duplicates`)
   - stretches every box to full page width (stafflines always span the page)
   - groups boxes into chunks of 4 and assigns `VOICE_MAP = {1: Soprano, 2: Alto, 3: Tenor, 4: Bass}`
     by vertical position within each system — **this assumes a strict top-to-bottom SATB system
     layout with no missing/extra staves per system**
   - crops + resizes each staff into a fixed-height strip (`STRIP_HEIGHT = 64`, matching Stage 3's
     CRNN input height) for the CRNN
   Also contains `train_yolov8()` / `evaluate_model()`, reused by `train_staff_detector.py`.

3. **`stage3_transcription.py`** — the core recognition stage: `CRNN` (ResNet-style CNN backbone →
   2-layer BiLSTM → CTC) decodes each strip into a sequence of Camera-PrIMuS agnostic tokens (e.g.
   `note.quarter-L4`, `clef.G-L2`, `accidental.sharp-L5`), via `_greedy_ctc_decode`. `infer_pitch()`
   then runs a 5-stage state machine (`clef → keysig → body → post_bar → mid_keysig`) over the token
   sequence to resolve each note token's staff-position suffix (e.g. `-L4`, `-S3`) into an absolute
   MIDI pitch, tracking active clef and key signature as it goes. Tenor voice is a special case:
   `get_clef_reference()` looks up voice, not just the clef token, and returns pitches an octave lower
   (`TENOR_CLEF_REFERENCE`) because a treble clef with an implicit 8vb (used for Tenor in SATB choral
   writing) is visually indistinguishable from a plain treble clef to the CRNN. Emits one JSON event
   file per voice under `data/transcribed_symbols/`.

4. **`stage4_reconstruction.py`** — merges Stage 3's per-strip events into one continuous sequence per
   voice (sorted by `page_index`, then `tick_onset`), and resolves slurs: `_resolve_slurs()` extends
   the first note of a slurred group to cover the full slur duration and marks the absorbed
   middle/end notes so Stage 5 skips them without breaking tick alignment. Raises `ValueError` if any
   of the four SATB voices came back empty — a hard requirement that all four parts were detected.

5. **`stage5_synthesis.py`** — converts each voice's event list into a single-track MIDI file (ticks
   converted to beats via `PPQ = 480`), then renders MIDI → WAV → MP3 through FluidSynth + a `.sf2`
   soundfont + pydub/ffmpeg. Falls back to returning the raw `.mid` path per voice if audio rendering
   dependencies/soundfont are missing. `run_full_pipeline()` here is the de facto single entry point
   that chains Stages 1–5.

### Directory conventions

- `data/raw/` — input score photos (create and populate manually)
- `data/preprocessed/`, `data/strips/`, `data/transcribed_symbols/` — auto-created intermediate
  outputs per stage, not checked in (see `.gitignore`)
- `data/detection_viz/`, `data/symbol_detection_viz/` — optional debug visualizations (`--viz` flags)
- `staff_detector_files/` — YOLOv8 staff-detector training artifacts (weights, PR/F1 curves,
  confusion matrix); `weights/best.pt` is the model Stage 2 loads by default
- `music_symbol_detection/crnn_cameraprimus_transcription.pt` — the pretrained CRNN checkpoint
  (trained on Kaggle) that Stage 3 loads by default
- `datasets/` — raw third-party training sets (DeepScoresV2 `ds2_dense/`, Camera-PrIMuS,
  camera-grandstaff) used only by `prepare_deepscore.py` / training, not by inference
- `.pt`/`.pth` files are tracked via Git LFS (`.gitattributes`) except `yolov8n.pt`/`yolov8s.pt`,
  which are force-included in `.gitignore`'s otherwise-blanket `*.pt` exclusion

### Voice/event data shape

The dict `{"Soprano": [...], "Alto": [...], "Tenor": [...], "Bass": [...]}` is the shared interchange
format from Stage 2 onward (strips → events → reconstructed events), always keyed by the constant
voice names, not indices. Event dicts (Stage 3+) carry `type`, `pitch` (MIDI int or `None` for rests),
`duration_ticks`, `voice`, `page_index`, `chord_id`, `symbol`, `tick_onset`, `slur`.

## Role

Act as a senior full-stack developer (10+ years), with production computer-vision-systems experience.
Pragmatic, tested code. No unnecessary abstraction — this codebase already favors flat, standalone
stage scripts over frameworks; match that.

## Behavioral policies

- State the planned change before editing, in enough detail that the direction can be redirected
  before code moves.
- Don't write or commit code until 95% confident it satisfies the ticket's acceptance criteria.
- Before changing existing code, give a one-line risk assessment of what could break.
- Quote acceptance criteria directly from the ticket file rather than assuming or paraphrasing them.
- If a ticket's criteria are ambiguous or underspecified, flag it and ask — don't guess.

## Code style

- Docstrings and comments explain *why* (non-obvious constraints, workarounds, invariants), not what.
- Strict typing: Python type hints throughout, no implicit `Any`.
- PEP 8 formatting; Google-style docstrings.
- Named constants instead of magic numbers.
- Explicit error handling — no silent `except:` blocks.

## Workflow per ticket

1. Plan
2. Explore the relevant code
3. Clarify anything ambiguous with the user
4. Give a one-line risk assessment
5. Implement
6. Self-verify against each acceptance criterion individually
7. Test
8. Report results
9. Wait for review before committing — do not commit unprompted

## Documentation & tickets

- Full requirements: `docs/sow.md`
- Sprint timeline: `docs/sprint-plan.md`
- Per-module ticket detail: `docs/tickets/module1-pipeline.md` (ML pipeline), `module2-mobile.md`
  (Android client), `module3-backend.md` (Flask API), `module4-deployment-qa.md`
- Ticket-driven skills: `.claude/skills/implement-ticket.md`, `.claude/skills/verify-ticket.md`

None of these files carry a status/done field for individual tickets — acceptance criteria and
sprint/ticket-to-sprint mapping are there, but "is PIYA-XXX actually finished" is not something the
docs themselves record. Treat sprint/ticket completion status as something to confirm with the user
in conversation, not something readable from the docs.

### Current sprint (Sprint 6, Sep 8–14)

Active tickets: PIYA-106 (Symbol Transcription), PIYA-107 (Pitch Inference), PIYA-110 (Model Loading
Optimization), PIYA-111 (Pipeline Failure/Timeout Handling), PIYA-112 (Environment Pinning).

The two tickets from the **Sep 4 action item** (the pre-Sprint-6 window per `docs/sprint-plan.md`, not
a numbered earlier sprint) were resolved in conversation with the user on 2026-09-09. As with all
ticket status per the policy above, this note itself isn't authoritative — if the user indicates
either decision changed, treat this as stale and re-confirm rather than trusting it:

- **PIYA-300** — Database & Hosting Technology Selection (Module 3). Decision recorded in
  `docs/decisions/piya-300-database-hosting.md` — PostgreSQL on Neon + a DigitalOcean CPU-only VPS +
  on-demand GPU rental via RunPod (Vast.ai fallback) for testing windows only. Provider accounts are
  not yet created — see that doc's Action Items. PIYA-311 schema work and PIYA-401 provisioning are
  unblocked to proceed against this decision.
- **PIYA-410** — Bug Tracking System Setup & Triage Process (Module 4). Tracker is
  `docs/bug-tracker.md` (in-repo markdown, no external tooling) — log bugs found during work there
  going forward, tagged with the phase they were found in (dev-sprint/dry-run/live-testing).

## Evaluation results snapshot (recorded 2026-09-14)

Full detail and methodology live in `docs/bug-tracker.md` (BUG-011, BUG-004) and
`docs/tickets/module1-pipeline.md` (PIYA-107). This is a summary pointer, not the source of truth —
treat it as stale if either doc has moved on.

- **CameraPrIMuS (CPM) — CRNN transcription + pitch inference (Stage 3):** strong on its own training
  distribution but not representative of real-world performance.
  - Ground-truth-token pitch math (`infer_pitch()` alone, real `.agnostic` tokens, no CRNN): 98.736%.
  - End-to-end CRNN, clean CPM images (500 samples / 6960 notes): 98.118% pitch accuracy.
  - End-to-end CRNN, synthetically distorted CPM images: 86.983% pitch accuracy (clears the 85% floor
    by ~2 points only).
  - SER baseline referenced in bug-tracker.md: ~98%+/~87% clean/distorted; a separate 0.70%/18.76%
    clean/distorted SER figure is noted in the confidence-decoder docstring.
  - **Does not transfer to real screenshots.** BUG-011: on 48 real phone-screenshot strips (post
    BUG-012 fix), clef recognition is 2/48 correct — the CRNN collapses to `clef.C-L3` almost always.
    Root-caused to a font/glyph domain gap (CPM's render font vs. real engraving fonts), confirmed
    general across 3 fonts and "confidently wrong" (not low-confidence). No code-only/image-preprocessing
    fix exists; requires retraining/fine-tuning on multi-font data (PIYA-106 AC4), blocked on the base
    Camera-PrIMuS training run.
  - **Correction (2026-09-14):** the previously-stated "~4.2% bounded" real-world pitch accuracy was a
    math extrapolation from the clef-misread rate alone, assuming non-clef tokens (notes/accidentals/
    rests) were otherwise correct — that assumption was false. Direct comparison of the CRNN's full
    token output against manually-read ground truth (2 independent source pages, 4 strips) shows
    non-clef output is also badly wrong: hallucinated note/rhythm clusters, missing rests, phantom
    accidentals, wrong note-count vs. the real content. ~4.2% was a ceiling under a false assumption,
    not a floor — true real-world accuracy is unmeasured and likely lower. See BUG-011 in
    `docs/bug-tracker.md` for full detail and ml-cv-lead's review.

- **DS2 Dense (DeepScoresV2) — YOLOv8 staff detector (Stage 2):** one number on record, and it is
  compromised — do not present it as a clean result.
  - Interim PIYA-105 eval logged 2026-09-10: mAP50 0.9766, mAP50-95 0.8654, precision 0.954,
    recall 0.976.
  - **BUG-004 (open):** `evaluate_model()` calls `model.val()` with no `split` argument, so this number
    is actually the **val** split (134 images), not the **test** split (346 images) defined in
    `dataset.yaml`, despite the function's docstring claiming a test-split eval. A follow-up run with
    `split="test"` hit a separate, unresolved `RuntimeError: Numpy is not available` when the test-split
    label cache had to be built fresh. There is currently no valid test-split number.

## Retraining plan for BUG-011 (real-world font domain gap)

Decision recorded 2026-09-14 in `docs/decisions/piya-106-crnn-font-retraining-plan.md`
(ml-cv-lead reviewed) — full 7-step ordered plan, decides for PIYA-106 AC4. Summary: the CRNN
(`training/pianota-transcription-training.ipynb`) is trained only on CameraPrIMuS's one synthetic
engraving font, which is why it collapses on real screenshots (BUG-011, ~4.2% bounded real-world
pitch accuracy) — this is a font/glyph domain gap, not a Filipino-content/language issue. Do **not**
start by hand-labeling real Filipino sheet music; CameraPrIMuS ships an `.mei` file per sample that
Verovio can re-render through 5 bundled SMuFL fonts with the existing `.agnostic`/`.semantic` labels
still valid (zero manual transcription) — see `training/step1-font-rerender-kaggle-guide.md` (and the
matching section built into `training/pianota-transcription-training.ipynb`) for verified, runnable
step-1 instructions (font re-rendering). Switched from Colab to Kaggle 2026-09-15 since the base CRNN
training already lives there. **Step 2 (fine-tuning) is actively in progress as of 2026-09-16** — LR
sweep, an extended trend check, and a seed-replication check (2 seeds × 2 LRs) all completed and
confirmed lr=3e-5 as the LR to use; a first real `RUN_FINETUNING` attempt produced an invalid result
(root-caused to leftover RNG state from re-running the notebook cell in-kernel without an explicit
seed) and has been fixed (hard-fail assert on missing seed, real run restructured to always fine-tune
under both seed=1 and seed=2). The two-seed `RUN_FINETUNING` run then completed, but an isolated
seed=1 reproduction check (rerun in a fresh kernel, same seed/data/hyperparameters) came back with a
starkly different, worse trajectory (hard-cap breach by epoch 2 vs. a clean 4-epoch run originally) —
root-caused to GPU-level cuDNN nondeterminism: `torch.manual_seed()` controls RNG state but not which
(possibly nondeterministic) cuDNN convolution algorithm gets selected, so seeding alone did not make
`finetune()` reproducible on GPU. Fixed 2026-09-17: `finetune()` now sets
`torch.backends.cudnn.deterministic = True` / `torch.backends.cudnn.benchmark = False` alongside its
existing seed calls. **2026-09-19: the original seed=1 sub-run's per-epoch checkpoints (the reference
this fix was meant to reproduce) were confirmed permanently lost** — not recoverable, so
"reproducible" can now only be judged as same-seed-vs-same-seed agreement under the fix, not against
that lost baseline. Two independent isolated seed=1 reproduction runs were done instead (identical
config, fresh kernel each time): both landed on best epoch 1 (`loo_font_ser` 0.0561 and 0.0523), same
epoch-1-best/soft-floor-breach-from-epoch-2/hard-cap-never-crossed/patience-stop-at-epoch-4 shape in
both — categorically unlike the pre-fix failure (hard-cap breach by epoch 2). A ~26–29% relative
divergence at epoch 3 between the two runs is real residual nondeterminism (root-caused to
`finetune_train_loader` in notebook cell 12 having `shuffle=True` with no seeded `generator=`/
`worker_init_fn` — confirmed in the notebook, not yet fixed, optional follow-up) but the metric
actually used for checkpoint selection only diverged ~7%, so it doesn't block proceeding. ml-cv-lead
reviewed all of this (three rounds) and gave a **GO** on the real two-seed `RUN_FINETUNING` run.
Separately flagged and **not yet resolved**: epoch-1-best-then-monotonic-decline showed up identically
in both reproduction runs, which ml-cv-lead reads as a real, reproducible property of `lr=3e-5` (not
noise) — fine-tuning past epoch 1 looks actively counterproductive. Shipping the epoch-1 checkpoint is
fine since checkpoint selection already picks it, but this is a separate open item, not to be silently
dropped. **The real two-seed `RUN_FINETUNING` run has since completed** (under the cuDNN fix):
seed=1 best epoch 1 (`loo_font_ser` 0.0523, exact numeric match to the second isolated repro run);
seed=2 best epoch **2**, not 1 (`loo_font_ser` 0.0886), with an epoch-3 canary-clean spike to ~89% of
the hard cap before partially recovering. Both checkpoints
(`crnn_weights/finetuned_font_seed{1,2}.pt`) are valid, neither invalidated. **ml-cv-lead's fourth
review: conditional GO to Step 3, Step 2 not formally closed.** Seed=2's best-epoch=2 disconfirms the
"epoch-1-is-always-best" read from the reproduction runs — that was checkpoint-selection luck, not a
real `lr=3e-5` property; do not switch to the `1e-5` runner-up, which lacks equivalent
seed-replication rigor and already lost to `3e-5` by ~24% relative in earlier seeded runs. The
epoch-3 near-cap spike is independently concerning (real oscillation, not just "cap held"). The ~70%
gap between seed=1's and seed=2's best values isn't cleanly within the established same-seed noise
floor (7–29%) — plausibly explained by the still-unfixed unseeded `finetune_train_loader` DataLoader
shuffle/worker RNG (notebook cell 12) rather than genuine seed-to-seed model variance. **Report both
seed checkpoints as a range — never cherry-pick seed=1's better number.** Full detail: the 2026-09-19
amendment in `docs/decisions/piya-106-crnn-font-retraining-plan.md`. **Immediate next action:** Step 3
(collect a fresh real-world test set, different piece/tool than the 48 BUG-011 diagnostic strips) may
start now, in parallel with — at the user's discretion — applying the DataLoader seeding fix; both are
needed before Step 2 is fully closed and Step 4 evaluation begins. None of this round's findings speak
to whether the actual BUG-011 real-screenshot fix works — it's purely about training stability; the
confidence/uncertainty problem (step 7) remains untouched. Steps 3–7 (fresh held-out real test set →
single evaluation → confidence re-check) are not yet started.

## Git

Commit messages: `PIYA-XXX: <summary>`. Never commit without explicit user review and approval first.

## Agent Usage Rules
- Use ml-cv-lead PROACTIVELY before writing any training/model-swap code,
  and again after results are reported, to check for leakage/overfitting.
- Use senior-reviewer MUST BE USED before any branch is proposed for merge.
- Use backend-lead for any Module 3 (API/auth/DB) change.
- Use frontend-lead for any Module 2 (Flutter/Android app) change.
- Use prompt-enhancer when a task is described informally and needs
  structuring before execution begins.