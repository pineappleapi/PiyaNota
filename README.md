# PiyaNota

PiyaNota turns a photo of **open-score** printed SATB choral music (one staff per voice: Soprano, Alto,
Tenor, Bass) into four piano audio tracks, one per voice. It is a thesis project with three parts:

| Part | Folder | What it is |
|---|---|---|
| Android app | `mobile/piyanota_application/` | Flutter app: photograph a score, upload it, play the four voices. |
| API | `backend/` | Flask API (auth, uploads, job queue, library) deployed on Render, with Postgres on Neon. |
| Recognition pipeline | repo root (`stage*.py` and helpers) | Reads the photo and writes the MIDI/audio. Run by the conversion worker in `backend/worker/`. |

Start with [`docs/README.md`](docs/README.md) for the documentation map. [`CLAUDE.md`](CLAUDE.md) is the long
project guide (it is also the instruction file for the Claude Code assistant used on this repo).

## How a photo becomes audio

```
photo -> Stage 1 preprocess -> Stage 2 find staves -> Stage 3 read symbols -> Stage 4 build four voices -> Stage 5 MIDI + audio
```

| Stage | File | Job |
|---|---|---|
| 1 | `stage1_preprocessing.py` | Grayscale, denoise, binarize, straighten the page and each staff, mask non-staff ink. |
| 2 | `stage2_detection.py` | YOLOv8 finds each staff; the four staves of a system become Soprano/Alto/Tenor/Bass strips. |
| 3 | `stage3_transcription.py` | CRNN-CTC reads each strip into music tokens, then `infer_pitch()` turns them into MIDI pitches. |
| 4 | `stage4_reconstruction.py` | Merges strips into one timeline per voice: ties, bars, pickup, meter, repairs, review flags. |
| 5 | `stage5_synthesis.py` | Writes one MIDI per voice and renders MP3 through FluidSynth. |

Helpers at the root, all imported by flat name (the worker image and the tests rely on that):

| File | Role | Used by |
|---|---|---|
| `stage3_clefkey.py` | Stage 3 variant that takes clef, key and octave from the clef/key classifier instead of the CRNN. This is the default. | Stage 3/4/5 CLIs, `run_full_pipeline` |
| `clef_key_core.py` | The clef/key classifier network and its crop definition. One file shared with the Kaggle training notebook, so it must not change on its own. | `stage3_clefkey.py`, `clef_voice_rules.py` |
| `clef_voice_rules.py` | Limits the classifier's clef to the clefs that voice actually uses. | `stage3_clefkey.py`, tests |
| `timing_export.py` | Maps Stage 4 events to page pixels and milliseconds for the app's note highlight. Pure Python, no torch. | `backend/worker/main.py` |

The full details of each stage are in `CLAUDE.md` (section "Pipeline architecture").

## Repo map

```
README.md  CLAUDE.md  render.yaml  requirements.txt
stage1..stage5, stage3_clefkey, clef_key_core, clef_voice_rules, timing_export   (the pipeline)
backend/     Flask API, worker, migrations, scripts, tests   (see backend/README.md)
mobile/      Flutter app                                      (see its README)
tests/       pipeline tests                                   (pytest)
docs/        deploy guides, ERD, decisions, known issues      (see docs/README.md)
models/      model weights + soundfont, NOT in git            (see below)
.claude/     assistant tooling (agents, hooks), not app code
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
# GPU (optional, NVIDIA CUDA 12.1), install separately:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Stage 5 audio also needs a system `fluidsynth`, `ffmpeg` on PATH, and the packages listed (commented) in
`requirements.txt`.

**Model files are not in git.** Put these four files in `models/` (the pipeline and the worker read them from
there):

- `staff_detector_yolov8.pt` (Stage 2)
- `symbol_transcriber_crnn_seed1.pt` (Stage 3)
- `clef_key_classifier.pt` (clef/key classifier)
- `piano.sf2` (soundfont)

Paths can be overridden with `PIYA_YOLO_WEIGHTS`, `PIYA_CRNN_WEIGHTS`, `PIYA_CLEFKEY_WEIGHTS` and `PIYA_SOUNDFONT`.

## Run the pipeline

Each stage script runs everything before it, so run the last stage you need. Put photos in `data/raw/`.

```bash
python stage5_synthesis.py --input data/raw \
    --weights models/symbol_transcriber_crnn_seed1.pt \
    --yolo models/staff_detector_yolov8.pt \
    --soundfont models/piano.sf2
```

There is no `run_pipeline.py`. `run_full_pipeline()` in `stage5_synthesis.py` is the single entry point the
worker calls. Stages 1 to 4 can be run the same way (`python stage2_detection.py --input data/raw --viz`).

## Run the tests

```bash
python -m pytest tests -q                    # pipeline: 117 pass, 55 expected failures (tests/conftest.py)
python -m pytest backend/tests -q            # backend: needs Postgres on localhost:55432
cd mobile/piyanota_application
flutter analyze && flutter test
```

The 55 expected failures are tests for muted-span/meter-vote code that is not on `main` (see
`docs/KNOWN-ISSUES.md`).

## Deploying

- API: Render builds `backend/Dockerfile` from `render.yaml`. Guide: [`docs/deploy/render-api.md`](docs/deploy/render-api.md).
- Conversion worker: runs on the developer laptop against the same Neon database. Guide:
  [`docs/deploy/local-worker.md`](docs/deploy/local-worker.md).

## Scope

Open-score SATB only. Closed-score (two-staff piano-reduction style) is out of scope. Fermatas are out of scope. Two rhythms on one staff (`layer.split` divisi) are a known limit: Stage 4 flags the bar for review.
