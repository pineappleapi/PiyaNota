# PIYA-106 Phase 2 runbook (prep → Kaggle GPU run → G2)

Works in any chat, including the claude.ai free tier with no file access. You run the commands in PowerShell; the
chat reads what you paste back. Keep each chat small: attach only the files listed for the step you're on.

## 1. Paste this primer first (copy as is)

```
Project: PiyaNota, OMR for open-score SATB choral photos -> 4 voice audio tracks.
Ticket: PIYA-106 AC1 = token SER <= 15% on camera photos (agnostic tokens, slurs/ties excluded).
Where we are: Phase 1 (synthetic SATB strips, 25,766 strips, 5 fonts) is done and frozen.
Phase 2 = fine-tune the CRNN (from the CPM base) on those strips + Camera-PrIMuS (CPM) replay incl. 4 font re-renders,
2 seeds + 1 seed-1 run without augmentation, on Kaggle GPU (plan doc: Amendment 4).
Gate G2: dev SER (eval_prelim, camera and digital, grey strips, e1c rule) >= 3 pp below the baseline
(camera 16.26-16.55%, digital 15.90-16.64%), both seeds, no canary cap breach. AC1 is judged only at Phase 4 held-out.
Rules:
- Train/val split is by tune (all harmonisations and all 5 fonts of a melody on one side). Never by strip.
- eval_prelim pieces are DEV data: never held-out evidence, never used to pick checkpoints inside training.
- Never train on data/piyanota_dataset (test photos).
- Report both seeds as a range; never cherry-pick the better seed.
- Never paste API keys, kaggle tokens or rclone configs into the chat.
- ml-cv-lead review before training code runs and after results; senior-reviewer before any merge.
I will paste command outputs; tell me the next step from the runbook, and flag anything that differs from "expected".
```

## 2. Status checklist

Update the boxes when you commit.

- [x] P0 C: copy verified (`ok 28967 / mismatched 0 / missing 0`, manifest sha256 b1d2553575ed97d7)
- [x] P1 strip manifest + tune-grouped split (sha256 78165b43251f67751a…, train 23,997 / val 1,769 strips)
- [x] P2 `train_phase2.py` written
- [x] P3 local CPU smoke PASS
- [x] P4 `eval_dev.py` parity checks (section 4, step P4)
- [x] P5 ml-cv-lead: GO with changes (2026-10-11). All four changes are made; see Amendment 4 in the plan doc.
- [ ] Run: Kaggle push → 2 seeds → fetch → `eval_dev.py` → G2 verdict

## 3. Paths

| what | where |
|---|---|
| code (worktree) | `D:\PiyaNota\.claude\worktrees\piya106-stroke-calibration` (branch `piya106/stroke-calibration`) |
| frozen re-cut corpus | `D:\PiyaNota\datasets\phase1_recut_full` (copy: `C:\phase1_recut_full`) |
| Phase 2 manifest | `D:\PiyaNota\datasets\phase2_manifest\phase2_manifest.jsonl` (+ `_summary.json`) |
| dev strips (grey, live Stage 1/2) | `D:\PiyaNota\datasets\phase2_dev_strips\grey_live` |
| stored eval_prelim runs (GT records, ClefKeyNet decisions, binary strips) | `D:\PiyaNota-training\data\eval_prelim\runs` |
| CPM (local) | `D:\PiyaNota\datasets\CameraPriMus\CameraPrIMuS - Copy` |
| current checkpoints | `D:\PiyaNota\music_symbol_detection\{crnn_cameraprimus_transcription,finetuned_font_seed1,finetuned_font_seed2}.pt` |
| Kaggle token | `%USERPROFILE%\.kaggle\access_token` (never paste it) |

Every command below runs from the worktree root, with the system Python that already has torch, opencv and the
kaggle CLI installed (there is no venv on this PC):

```powershell
cd D:\PiyaNota\.claude\worktrees\piya106-stroke-calibration
```

## 4. Steps (Python files in the order you run them)

### P0 — verify a corpus copy: `training/phase1/verify_manifest.py`
```powershell
python training/phase1/verify_manifest.py C:\phase1_recut_full
```
Expected: `ok 28967 / mismatched 0 / missing 0  (manifest sha256 b1d2553575ed97d7)`, exit 0.
If it differs, paste the whole output. Attach nothing else.

### P1 — tune groups + manifest + split: `training/phase2/tune_groups.py`, `training/phase2/build_manifest.py`
`tune_groups.json` is committed, so only rerun `tune_groups.py` if the corpus changes (about 1 min, needs music21):
```powershell
python training/phase2/tune_groups.py D:\PiyaNota\datasets\phase1_recut_full\out
python training/phase2/build_manifest.py D:\PiyaNota\datasets\phase1_recut_full\out D:\PiyaNota\datasets\phase2_manifest
```
Expected:
- `tune_groups.py` prints `pieces 364  groups 223 ...`.
- The summary ends in `"manifest_sha256": "78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824"`.
- `"pieces_in_both_splits": 0`, `"tunes_in_both_splits": 0` and `accidental.double_sharp` 0 in both splits.
- Exit code 0.

A different sha means the corpus, the groups or the script changed: stop and paste the summary.

### P3 — local smoke: `training/phase2/train_phase2.py --smoke`
```powershell
python training/phase2/train_phase2.py --recut-out D:\PiyaNota\datasets\phase1_recut_full\out `
  --cpm-root "D:\PiyaNota\datasets\CameraPriMus\CameraPrIMuS - Copy" `
  --init D:\PiyaNota\music_symbol_detection\crnn_cameraprimus_transcription.pt `
  --seed 1 --out $env:TEMP\smoke_p2 --expect-manifest-sha 78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824 `
  --augment-synth --smoke
```
The smoke test also checks the canary is the notebook's slice (399 stems, pinned sha256). The font-rerendered CPM
isn't available locally, so `--cpm-font-root` is exercised only on Kaggle.
Expected last line: `[smoke] PASS: finite_loss=True reload_identical=True ...`. On FAIL paste the last 20 lines and
attach `training/phase2/train_phase2.py`.

### P4 — dev scorer (G2): `training/phase2/eval_dev.py`
CPU only, about 10-20 min per strip source for 2 checkpoints. Prints one table and writes
`D:\PiyaNota\datasets\phase2_eval_dev\eval_dev_<strips>_<header>.json`.

```powershell
$W = "--weights", "seed1=D:\PiyaNota\music_symbol_detection\finetuned_font_seed1.pt", "--weights", "seed2=D:\PiyaNota\music_symbol_detection\finetuned_font_seed2.pt"
python training/phase2/eval_dev.py @W --strips binary --header e1c   # parity: must equal the recorded E1c row
python training/phase2/eval_dev.py @W --strips grey --header e1b     # parity: must equal step 6 (camera 15.61-16.17%)
python training/phase2/eval_dev.py @W --strips grey --header e1c     # the G2 baseline on the live (grey) source
```
Expected (recorded): see the "P4 results" table in section 6. For a Phase 2 model replace `$W` with
`--weights p2s1=<dir>\seed1\phase2_seed1.pt --weights p2s2=<dir>\seed2\phase2_seed2.pt` and run the `grey e1c` line
(and `grey none`, since G2 is also reported without the header filter).

## 5. Kaggle run (after the P5 GO only)

1. Commit the reviewed code, then set `COMMIT` in `training/phase2/kaggle/phase2_kernel.py` to `git rev-parse HEAD`.
   - `INIT_NAME`, `TRAIN_ARGS` and `RUNS` already hold the P5 ruling: CPM base init, augmentation on, and the runs
     seed1, seed2 and seed1_noaug, within an 11 h budget.
   - Changing them means a new review.
   - The kernel file itself is not in the bundle, so editing `RUNS` (to rerun a skipped run) needs no new bundle.
2. Build the small code dataset (repo bundle + init checkpoint), outside the repo:
   ```powershell
   $D = "$env:TEMP\p2code"; New-Item -ItemType Directory -Force $D | Out-Null
   git bundle create $D\repo.bundle piya106/stroke-calibration
   Copy-Item D:\PiyaNota\music_symbol_detection\crnn_cameraprimus_transcription.pt $D\   # or the P5 init
   kaggle datasets init -p $D        # first time only: edit dataset-metadata.json -> id piamac/piyanota-phase2-code
   kaggle datasets create -p $D      # first time; later: kaggle datasets version -p $D -m "<commit>"
   ```
3. Push the kernel. `training/phase2/kaggle/kernel-metadata.json` sets the GPU and attaches four inputs:
   - the code dataset;
   - `piamac/cameraprimus`;
   - `piamac/cpm-font-augmented2`;
   - the re-cut kernel output.
   ```powershell
   kaggle kernels push -p training/phase2/kaggle
   ```
4. Poll status only (never stream the log); a 2-seed run takes hours, so check every 1-2 h:
   ```powershell
   kaggle kernels status piamac/piyanota-phase2-train
   ```
5. When it says `complete`, fetch only the small files and the two best checkpoints:
   ```powershell
   python training/phase1/kaggle/fetch_output.py piamac/piyanota-phase2-train D:\PiyaNota\datasets\phase2_run1 `
     --pattern "kernel_status\.json$|(run_info|metrics|summary)\.json$|train\.log$|phase2_seed\d\.pt$"
   ```
   Paste `kernel_status.json` and each run's `summary.json` into the chat; they're small.
   - Runs live in `seed1/`, `seed2/` and `seed1_noaug/`.
   - A run marked `skipped` or `timeout_budget` in `kernel_status.json` gets a re-push with only that run in `RUNS`.
6. Score each run with P4: `grey e1c` (the G2 rule), `grey e1b` and `grey none`. Paste the tables.
   - G2 passes only if **both** augmented seeds are >= 3 pp below the grey e1c baseline (camera 16.26-16.55%,
     digital 15.90-16.64%) in both conditions, and no canary hard cap was breached (`summary.json`).
   - A piece-level bootstrap margin comes from the per-piece JSONs before G2 is declared.
   - The `seed1_noaug` arm decides whether any gain is credited to augmentation.
   - Then ml-cv-lead reviews the result before anything else is decided.

## 6. Recorded results (fill in as you go)

**P4 results** (dev data, diagnostic only; seed1-seed2 range):

| strips / header | camera SER | camera pitch | digital SER | digital pitch | reference |
|---|---|---|---|---|---|
| binary / e1c | 26.83-28.43% | 85.16% | 16.30-16.54% | 89.78-90.18% | E1c recorded: identical (parity PASS) |
| grey / e1b | 15.61-16.17% | 88.71-89.81% | 14.86-15.70% | 90.67-90.97% | step 6: camera 15.61-16.17% (parity PASS) |
| grey / e1c | 16.26-16.55% | 88.71-89.93% | 15.90-16.64% | 90.67-90.97% | **G2 baseline** (live grey source, E1c rule) |

Fermata insertions in the baseline (grey / e1c, predicted / GT): camera 39-41 / 0, digital 30-38 / 0. A Phase 2 model
that adds clearly more is learning Bach's fermata density; report it with the G2 table.

## 7. Which files to attach to a chat (smallest first)

- Always: this runbook.
- Script questions: only the one script involved (`verify_manifest.py`, `build_manifest.py`, `eval_dev.py`,
  `phase2_kernel.py` are each < 200 lines; `train_phase2.py` is ~460).
- Results: the printed table, `summary.json`, `phase2_manifest_summary.json`, `kernel_status.json`.
- Do **not** attach `training/piyanota-training-ver-2.ipynb`, `docs/decisions/piya-106-ser-15-plan.md` (1,600+ lines)
  or `stage3_transcription.py` (3,000 lines); quote the line range you need instead.

## 8. Troubleshooting

- **Low memory while downloading Kaggle output:** never use `kaggle kernels output`; use `fetch_output.py` (streams
  1 MiB chunks, resumable: rerun the same command after a stop).
- **Windows Defender "file in use" retries** in `fetch_output.py` logs are harmless; it retries 6 times.
- **Kernel aborts with `bundle HEAD ... != reviewed commit`:** the bundle and `COMMIT` disagree; rebuild the bundle
  after committing and push a new dataset version.
- **`manifest sha256 ... != expected`:** the kernel's re-cut source isn't `piyanota-recut-full-1` or the build script
  changed; do not override the check.
- **`no GPU`:** turn on the GPU accelerator in the kernel settings (or `enable_gpu` in kernel-metadata.json).
- **Kaggle 401:** the token in `%USERPROFILE%\.kaggle\access_token` expired; make a new one on kaggle.com (Settings →
  API) and replace the file. Never paste it into a chat.
- **Path errors locally:** run everything from the worktree root shown in section 3.
