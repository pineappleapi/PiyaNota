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
are defined in `_archive/docs/sow.md` (local only). There is no `run_pipeline.py` despite the README
referencing one — each stage script is runnable standalone and stage 5 exposes `run_full_pipeline()`
as the closest equivalent to a top-level runner.

## Repo layout (since the 2026-11-12 cleanup)

Only app code is at the root: `backend/`, `deploy/`, `mobile/`, `tests/`, `docs/` (deploy, ERD, timing,
`KNOWN-ISSUES.md`) and the nine pipeline modules. Everything else (research, `ground_truth/`, `gt/`, `data/`,
`training/`, `staff_detector_files/`, the rest of `docs/`, one-off scripts, mobile reference mockups) lives in
`_archive/`, which is committed locally only and never pushed. Any `docs/`, `training/`, `data/`,
`ground_truth/` or `staff_detector_files/` path below that is not in the app list above means `_archive/<path>`.
Weights and the soundfont default to the gitignored `models/` folder (`staff_detector_yolov8.pt`, `symbol_transcriber_crnn_seed1.pt`,
`clef_key_classifier.pt`, `piano.sf2`), the layout the worker reads. `tests/` has 11 files
(117 pass, 55 expected-failures in `tests/conftest.py`); `backend/tests` needs Postgres at localhost:55432.
`_archive/golden/golden_check.py` is the golden-output check (10-piece camera set, CPU): run it before and after
any refactor. `python _archive/golden/golden_check.py check`.

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
python stage2_detection.py --input data/raw --weights models/staff_detector_yolov8.pt --viz

# Stage 4 — full pipeline through SATB reconstruction (no audio)
python stage4_reconstruction.py --input data/raw --weights <crnn_weights> --yolo models/staff_detector_yolov8.pt

# Stage 5 — full pipeline including MP3 synthesis
python stage5_synthesis.py --input data/raw --weights models/symbol_transcriber_crnn_seed1.pt \
    --yolo models/staff_detector_yolov8.pt --soundfont models/piano.sf2
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

Tests: `python -m pytest tests -q` (pipeline), `python -m pytest backend/tests -q` (backend, needs Postgres), `flutter analyze` and `flutter test` (app). There is no linter or CI config.

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
   **Camera-photo rectification (2026-09-24, branch `piya106/two-seed-rerun-amendment`, committed, unmerged;
   BUG-013/BUG-001):** `track_staff_curves()` follows each 5-line staff as a curve (tolerates tilt, curl,
   uneven spacing); `dewarp_to_staff_grid()` straightens each staff with a per-column vertical remap, only
   when drift ≥ `DEWARP_MIN_DRIFT_PX` (5 px) so the dewarp step itself is a no-op on clean screenshots (the page is still changed by the non-staff-ink mask, so output is NOT bit-identical to before 2026-09-25); tracked staff rows are
   restored after border/lyric blanking (which previously erased real staves on camera pages).
   **Non-staff-ink mask + native strip source (2026-09-25, PIYA-121, same branch, BUG-015/BUG-016, committed, unmerged):** after dewarp, `non_staff_ink_mask()` erases ink that is neither the tracked staff nor connected (gap-bridged 0.2 spacing) to it - lyrics, titles, page-edge shadows - while keeping beams, ties, flags, rests and ledger-line notes. Detection/tracking stay at `DETECT_MAX_DIM` = 1600 px; the strip source is binarised once at native resolution (<= 4032 px) through the same perspective matrix and the same upsampled dewarp map, because binarising rests at 1600 px broke their ~1.6 px strokes. `training/run_stage12.py` regenerates strips, manifest, viz and 1:1 eyeball tiles; `training/step3_mask_audit.py` audits ties/beams/band ink (limits in its docstring and BUG-015).

2. **`stage2_detection.py`** — runs a fine-tuned YOLOv8 model (`models/staff_detector_yolov8.pt`)
   to find staff-line bounding boxes on each preprocessed page, then:
   - filters by confidence, caps at 16 boxes/page (4 systems × 4 voices max)
   - sorts top-to-bottom and deduplicates boxes that land on the same staff (`_remove_duplicates`)
   - stretches every box to full page width (stafflines always span the page)
   - groups boxes into chunks of 4 and assigns `VOICE_MAP = {1: Soprano, 2: Alto, 3: Tenor, 4: Bass}`
     by vertical position within each system — **this assumes a strict top-to-bottom SATB system
     layout with no missing/extra staves per system**
   - crops + resizes each staff into a fixed-height strip (`STRIP_HEIGHT = 64`, matching Stage 3's
     CRNN input height) for the CRNN
   - `_reconcile_with_classical()` cross-checks YOLO against Stage 1's tracked staves: same count and
     centres → YOLO boxes kept unchanged; otherwise tracked staves are used **only if** their count is
     divisible by 4, else YOLO's boxes stay and the divisible-by-4 `ValueError` still fires. On the 7
     Both Sides Now camera photos (tracker + YOLO) this gives 12/12/12/12/12/12/8 staves, all correct (was
     6–13 per page). Developed on those photos — not an independent eval; see BUG-013.
   - **Non-staff-ink masking now lives in Stage 1 (PIYA-121, 2026-09-25; supersedes the earlier Stage 2 mask; BUG-015):** Stage 2 does NOT mask. Strips are cut from the Stage 1 native-resolution strip source (`PreprocessedPage.strip_source`, mapped through the same geometry and dewarp as the 1600 px detection page) with an INTER_AREA shrink to `STRIP_HEIGHT` (BUG-016). Known residuals: band-overlapping dust, handwriting, dynamics and left-edge label text survive by design; Stage 3 effect unmeasured.
   Also contains `train_yolov8()` / `evaluate_model()`, reused by `train_staff_detector.py`.

3. **`stage3_transcription.py`** — the core recognition stage: `CRNN` (ResNet-style CNN backbone →
   2-layer BiLSTM → CTC) decodes each strip into a sequence of Camera-PrIMuS agnostic tokens (e.g.
   `note.quarter-L4`, `clef.G-L2`, `accidental.sharp-L5`), via `_greedy_ctc_decode`. `infer_pitch()`
   then runs a 5-stage state machine (`clef → keysig → body → post_bar → mid_keysig`) over the token
   sequence to resolve each note token's staff-position suffix (e.g. `-L4`, `-S3`) into an absolute
   MIDI pitch, tracking active clef and key signature as it goes. Tenor voice is a special case:
   `get_clef_reference()` looks up voice, not just the clef token, and returns pitches an octave lower
   (`TENOR_CLEF_REFERENCE`) because a treble clef with an implicit 8vb (used for Tenor in SATB choral
   writing) is visually indistinguishable from a plain treble clef to the CRNN. **ClefKeyNet (2026-09-29,
   branch `piya106/clefkey-wiring`, BUG-027/029):** the Stage 3/4/5 CLIs and `run_full_pipeline` go through
   `run_stages_1_to_3()`: Stage 1 keeps the unmasked page, Stage 2 writes `strips/manifest.json`,
   `stage3_clefkey.decisions_for_pages` decides clef (voice rule), key (per-system vote) and octave, and
   `infer_pitch(header_override=..., next_system_key=...)` uses them. In that `fixed_header` mode CRNN clefs are
   ignored and no CRNN header accidental counts into the key. The CLI default checkpoint is
   `models/clef_key_classifier.pt` (the t4_full_seed20260926_runA checkpoint; resolved from the repo; its sha256 is checked only at that default path; gitignored, copy it from the
   training tree). Missing weights raise, and `--no-clef-key` opts out (CRNN clef/key, BUG-011).
   `run_full_pipeline` defaults to the checkpoint too; `clef_key_weights=None` opts out and flags every
   event `clef_key_disabled` / `review_needed`. A mid-strip key change counts with one glyph when it
   matches ClefKeyNet's key on the next adjacent system (BUG-029). The classifier still fails
   its real-photo gate (BUG-021). Keeping it the default is a user decision (2026-09-29), NOT a gate pass: while
   `stage3_clefkey.CLEF_KEY_GATE_PASSED` is False every event is flagged `clef_key_unvalidated` / `review_needed`, and
   `stage5_synthesis.run_full_pipeline_with_report()` returns the client `review` object for PIYA-103 AC6 (provenance
   stays internal). Revisit the default after the fresh held-out photo results. Emits one JSON event
   file per voice under `data/transcribed_symbols/`.

4. **`stage4_reconstruction.py`** — merges Stage 3's per-strip events into one continuous sequence per
   voice (sorted by `page_index`, `sys_idx`, then `tick_onset`), then:
   - **Ties, not slurs:** only a true tie merges (an explicit `tie_to_next`, or a slur whose two ends
     are adjacent same-pitch notes with no rest between, including across a system break); phrase
     slurs over different pitches never change audio. In Camera-PrIMuS every `slur.*` token is a
     tie, so the CRNN has never seen a phrase slur. Merged notes fold into the first (`tie_span`,
     `tied_note_ids`); a tie with no continuation is flagged `tie_unresolved`.
   - **Global ticks:** each system starts at `pickup + previous bars × bar_ticks` (bar length from the
     time signature), and each event keeps only its offset inside its own bar, so one misread rhythm
     stays in its bar and cannot shift the other voices. A short first bar on the first strip of the
     first page may be a pickup; it is right-aligned so bar 1's downbeat lands on the same tick in every
     voice. The pickup length is chosen by evidence scoring (`_decide_pickups`): candidates are "no
     pickup", each voice's first-bar length and the length implied by each short final bar; votes come
     from voices agreeing (full first bars vote for "no pickup"), final bars that complement the
     first, matching rhythms, standard lengths and a small no-pickup prior. A structural pre-check
     handles a lone real pickup (one voice has one extra short bar whose total minus that bar equals
     the others' total, as in Don't Stop Me Now Tenor). A candidate is accepted only with score ≥ 2.0
     and a lead ≥ 0.75; otherwise short first bars are placed as bar 1 with `pickup_suspect` listing the
     top candidates. Deviant voices are still right-aligned (longer first bars keep their last L ticks)
     and flagged `pickup_length_mismatch`. All scoring constants are hand-set priors, not fit to data.
   - **Overflow never fails the conversion:** a bar over its length is repaired, not dropped. A run of
     ≥3 same-duration slots (rests included) is scaled to fit — an exact 3-in-2 triplet gets 2/3
     durations (`suspected_tuplet`), anything ambiguous is spread evenly (`bar_overflow_run_scaled`),
     and everything after the run shifts left so the bar ends exactly on its length. With no scalable
     run, the fallback is whole-bar scaling (off-grid, ≥0.75), clipping, or a confidence-based drop
     (only when every note has a `confidence`); a total near a multiple of the bar is flagged
     `suspected_missing_barline` and clipped. The beat is assumed to be a quarter (wrong for 6/8).
   - **Flags, not silent repair:** `reconstruct_satb_with_report()` returns a report (`flags`,
     `pickup_ticks`, `total_ticks`, `systems`) — e.g. `pickup_detected`, `bar_underfull`,
     `bar_overflow_clipped`, `bar_count_mismatch`, `tie_unresolved`. Flags that need a human carry
     `review_needed`.
   An empty voice is reported in `failed_voices` and the others continue; `ValueError` only when all
   four are empty (PIYA-108 AC4/AC5, 2026-10-09). Bars are laid out per measure at their own meter
   (PIYA-108 AC6/AC7). The muted-span part (a `start_tick`/`end_tick` span that Stage 5 renders silent,
   PIYA-108 AC8 / PIYA-109 AC8) is NOT on main: `muted_measures` is always `[]` (`docs/KNOWN-ISSUES.md`).
   Known gaps: mid-bar system breaks are not handled. Same-stem divisi chords are supported: the A9 C2
   CRNN emits `chordnote-*` tokens, Stage 3 turns them into simultaneous notes that share a `chord_id`
   (unique per strip, so key it on `(page_index, sys_idx, chord_id)`), and Stage 5 plays them together.
   Two rhythms on one staff (`layer.split`) are not handled (accepted limitation, 2026-11-08): Stage 4's
   split-stem check (`divisi_rhythm_split_suspected`) clips that bar to its length and flags it
   `review_needed`. `tests/test_stage4_divisi.py` covers that check.

5. **`stage5_synthesis.py`** — converts each voice's event list into a single-track MIDI file (ticks
   converted to beats via `PPQ = 480`), then renders MIDI → WAV → MP3 through FluidSynth + a `.sf2`
   soundfont + pydub/ffmpeg. Falls back to returning the raw `.mid` path per voice if audio rendering
   dependencies/soundfont are missing. `run_full_pipeline()` here is the de facto single entry point
   that chains Stages 1–5. `PPQ` must equal Stage 4's `TICKS_PER_QUARTER` (checked at import, raises
   `RuntimeError`). All four voices are padded to the same length (through the last event end, not the
   last bar end; a sustain-pedal-off event pins the end), identical (onset, pitch) notes collapse to the
   longest, and same-pitch overlaps are clipped with a warning so no note-on is left without a note-off.

### Directory conventions

- `data/raw/` — input score photos (create and populate manually); `data/preprocessed/`, `data/strips/`,
  `data/transcribed_symbols/` and the `--viz` folders are auto-created per stage and gitignored.
- `models/` — gitignored weights and soundfont: `staff_detector_yolov8.pt` (Stage 2),
  `symbol_transcriber_crnn_seed1.pt` (Stage 3; the A9 C2 chord fine-tune, epoch 10 of seed 1, fine-tuned on
  Kaggle from the phase-2 base `phase2_seed1.pt`), `clef_key_classifier.pt`, `piano.sf2`.
- Training code, datasets, ground truth and detector training artifacts are not in the pushed repo; they are in
  the local `_archive/` (see the layout section).

### Voice/event data shape

The dict `{"Soprano": [...], "Alto": [...], "Tenor": [...], "Bass": [...]}` is the shared interchange
format from Stage 2 onward (strips → events → reconstructed events), always keyed by the constant
voice names, not indices. Event dicts (Stage 3+) carry `type`, `pitch` (MIDI int or `None` for rests),
`duration_ticks`, `voice`, `page_index`, `sys_idx`, `chord_id`, `symbol`, `tick_onset`, `slur`,
`measure_index`, `time_signature`. `tick_onset`, `measure_index` and (in Stage 3 output) ticks are
local to each system strip; Stage 4 rewrites `tick_onset` to a global tick and keeps the original as
`local_tick_onset`, and adds `global_bar` (1-based, 0 = pickup, `None` = local-placement fallback),
`tie_to_next`, `tie_span` and `tied_note_ids`. Stage 3 adds `confidence` (min over the note's note,
accidental and dot tokens) only when run on CRNN output; it is absent on ground-truth events. It ranks
likely misreads within a bar but is not a trust signal (BUG-011: confidently wrong). It is a frame-mean softmax, not a calibrated
probability, and excludes the clef, key signature and omitted tokens; Stage 4 uses it only as an
overflow tie-break, and every Stage 4 threshold/weight is a hand-set prior with no held-out validation. A note preceded (in the same bar) by an inline accidental that
failed position anchoring carries `unanchored_accidental_dropped` (the dropped token; BUG-033). Hand-authored ground truth
(`ground_truth/build_ground_truth.py`) additionally carries `note_id`, `written_pitch`, `chord_tail`
and `source_image`.

## Mobile client (Module 2)

Lives at `mobile/piyanota_application/` — Flutter, **Android only** (no iOS requirement; see
`_archive/docs/decisions/module2-flutter-framework.md` for why Flutter was chosen over native). State
management is Riverpod (`flutter_riverpod`); note the pinned `^3.4.3` removed the legacy
`StateProvider` — see that decision doc's 2026-09-17 addendum before reaching for it in new code.

- **Design system:** `.claude/agents/frontend-piyanota.md` is the source of truth for palette,
  typography, spacing, and layout-adaptivity — every screen's styling should trace to a token there,
  not be improvised inline. It in turn always cross-checks the framework decision doc above and the
  Figma exports in `docs/design/figma/` (reference-only, not shipped in the app).
- **Brand assets:** shipped logos/gradients live in
  `mobile/piyanota_application/assets/branding/` and are declared in `pubspec.yaml`.
- **Verify before reporting done:** `flutter analyze` and `flutter test`, run from
  `mobile/piyanota_application/`; both must be clean. `flutter run -d <device-id>` /
  `flutter build apk --release` to check on a physical device (`flutter devices` to list).
- Session tokens use `flutter_secure_storage` (Keystore-backed), never `shared_preferences` — the
  latter is reserved for non-secret flags (e.g. onboarding-completed).

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
- Hand-authored ground truth (e.g. `ground_truth/`) is diagnostic only: never present results measured
  against it, or against the 6-screenshot set, as accuracy evidence. The `piyanota_dataset` photos are
  TEST-only and never used for training, model selection or threshold tuning.

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

Current docs are indexed in `docs/README.md`. The SOW, sprint plan, per-module tickets, bug tracker, decision
records and the evaluation history (BUG-011 font gap, ClefKeyNet gate failure BUG-021, fresh-photo eval, CTC
beam-search no-go, CRNN font-retraining plan, checkpoint metadata) are in the local-only `_archive/docs/`.
The previous full version of this file, with those sections, is `_archive/CLAUDE-full-2026-11-14.md`.
Ticket-driven skills: `.claude/skills/implement-ticket.md`, `.claude/skills/verify-ticket.md`.

The tickets carry no done field. Confirm with the user whether a PIYA-XXX ticket is finished; do not infer it
from the docs.

## Known limits (summary; details in `docs/KNOWN-ISSUES.md`)

- The CRNN was trained on one synthetic font and then fine-tuned on several fonts; it does not reach its
  CameraPrIMuS numbers on real photos. Token errors in notes remain the main source of wrong audio.
- ClefKeyNet failed its real-photo gate (BUG-021). It stays the default by user decision, so every event is
  flagged `clef_key_unvalidated` / `review_needed`.
- The YOLOv8 staff-detector number on record is the val split, not the test split (BUG-004).
- Hand-authored ground truth and the 6-screenshot set are diagnostic only; the `piyanota_dataset` photos are
  test-only. Never present results against them as accuracy evidence.

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

## Backend

Module 3 (Flask API) lives in `backend/`; setup and tests are in `backend/README.md`, deployment in
`docs/deploy/render-api.md`. The live contract check is `python -m backend.scripts.smoke <base_url>`.
