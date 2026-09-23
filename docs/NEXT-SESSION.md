# Next Session — Start Here

Handoff doc for continuing PiyaNota work in a fresh session. Read this first; it links out to the
full detail rather than repeating it. Written 2026-09-14, rewritten 2026-09-16, rewritten 2026-09-19,
**2026-09-23 section prepended** (the 2026-09-19 retraining handoff below it is still current).

## 2026-09-23 session — resume here after the PC restart

**Why the restart:** mid-session the GPU/driver wedged (`CUDNN_STATUS_EXECUTION_FAILED` in the CRNN's
BiLSTM, then `nvidia-smi` itself hung). The user restarted the PC to reset it. First thing to check on
resume: `nvidia-smi` responds and `python -c "import torch; print(torch.cuda.is_available())"` is
`True`.

**Current branch:** `feature/piya106-run-manifest` (branched from `main` @ `2351623`). **Nothing
committed yet** — all work below is uncommitted in the working tree. Don't commit without the user's
review (standing rule); senior-reviewer must review before any merge.

### What was done

1. **Tenor strip diagnosis (ml-cv-lead).** The user asked whether Stage 3 correctly transcribed
   `data/strips/page001_sys02_Tenor_vidx3.png` (source `data/raw/IMG_1085.JPG`) with the **base**
   checkpoint `music_symbol_detection/crnn_cameraprimus_transcription.pt`. Verdict: **no** — wrong
   clef (`clef.C-L3` vs treble-8vb `G-L2`), flats instead of the 4-sharp key signature, a hallucinated
   `metersign.C`, invented eighth/beamed/sixteenth-rest content, every duration wrong; only the
   barline count (3) matched. Ranked causes: (1) font domain gap = BUG-011 (dominant, needs
   retraining); (2) binarized input + 3× thick stafflines vs Camera-PrIMuS grayscale (BUG-016,
   preprocessing-testable); (3) system bracket/double barline left of the clef possibly read as a
   C-clef half (BUG-016, hypothesis); (4) triplets unrepresentable in the vocabulary (BUG-015);
   (5) ~2–3× wider note spacing than training (BUG-016, hypothesis). Ruled out: staff height/padding,
   normalization/polarity. Also logged: viz filename collision across systems (BUG-014).
   Suggested single-variable experiments are listed in BUG-016's repro column.
2. **Run provenance tracking — `run_manifest.py` (new, PIYA-106, closes the provenance half of
   BUG-017).** User decisions: ticket **PIYA-106**; manifests saved per run to
   **`runs/omr/<run_id>/manifest.json`** (`runs/` is already git-ignored); **per-strip raw tokens +
   per-token confidences included**. Records git commit/dirty files, argv/args, environment
   (Python, torch/CUDA/cuDNN, GPU, pinned package versions), SHA-256 + size + mtime of CRNN/YOLO/
   soundfont (CRNN also records its `epoch`), raw input image hashes → page index, params (YOLO
   thresholds, `STRIP_HEIGHT`, CRNN img height, device, bpm), per-stage status + duration, per-strip
   tokens/confidences, hashed outputs (events JSONs, audio). Used as a context manager so failed runs
   still write a manifest with the failing stage + traceback.
   - Wiring (all additive, `manifest: Optional[RunManifest] = None`): `preprocess_batch()` (Stage 1),
     `detect_staff_regions()` (Stage 2), `process_strip()` + `transcribe_voice_sequences()`
     (Stage 3), `run_full_pipeline()` (Stage 5); the `__main__` blocks of Stages 3/4/5 create the
     manifest and gained a `--runs-dir` flag. `process_strip()` now calls `transcribe_strip(...,
     return_confidence=True)` — the decoded symbols are identical by construction
     (`_greedy_ctc_decode` wraps the confidence decoder), but this is **not yet empirically
     confirmed** (see below).
   - Diff: `run_manifest.py` (new), `stage1_preprocessing.py`, `stage2_detection.py`,
     `stage3_transcription.py`, `stage4_reconstruction.py`, `stage5_synthesis.py`.

### Verified so far

- All six files compile (`python -m py_compile`).
- One full Stage 1→3 CLI run into scratch dirs wrote a correct manifest: base CRNN identified by
  sha256 `b1c9803c…d47e`, epoch 11; YOLO `f55bb851…8213`; GTX 1650 / CUDA 12.4 / cuDNN 90100.
- Fixed a bug where `git status --porcelain` output was `.strip()`-ed, eating the first file's
  leading character (`.gitignore` → `gitignore`); re-checked.

### NOT yet verified — do these next, in order

1. **BUG-013 determinism check (blocks everything below) — DONE for the purpose of unblocking the
   rest; GPU-side stress-testing deliberately stopped short.** Post-restart, `nvidia-smi`/
   `torch.cuda.is_available()` both came back healthy. Ran a fresh version of last session's scratch
   script (3× fresh-process decode of the 48 saved strips, `load_model()` + `transcribe_strip()` on
   `sorted(glob(strips/*.png))`) on CPU and CUDA. **CPU: 3/3 identical — confirmed stable, not a
   code-level nondeterminism.** **CUDA: crashed on the 2nd of 3 runs** with the same
   `CUDNN_STATUS_EXECUTION_FAILED` as before the restart — reproduced, so this is real and
   GPU-specific, not a fluke. Right after, the GPU briefly refused even a trivial matmul
   (`CUDA-capable device(s) is/are busy or unavailable`) but self-recovered within ~1 min this time, no
   second restart needed. Full detail: BUG-013 in `docs/bug-tracker.md`. **User decision (2026-09-23):
   stop GPU testing, proceed CPU-only** — remaining sub-checks (GPU-stable 3/3, CPU==GPU, retry with
   `cudnn.deterministic=True`/`benchmark=False`) are intentionally not done and are **not planned**
   unless the user asks to resume them. All verification below runs CPU-only per that decision.
2. **No-behaviour-change check for the manifest branch — DONE, 2026-09-23, CPU-only, identical.** Ran
   HEAD's Stage 1–3 (exported via `git show HEAD:<file>` into a scratch dir, confirmed zero
   `run_manifest`/`RunManifest` references) against the branch's Stage 1–3 (working tree, wired through
   a real `RunManifest` exactly as the CLI's `__main__` block does), same input
   (`data/raw/IMG_1085.JPG`), both CPU-forced. CPU-forcing note: `CUDA_VISIBLE_DEVICES=""` alone wasn't
   enough — Ultralytics' YOLO call carries a `device="0"` default baked into the checkpoint's training
   args, which crashes (`Invalid device id`) once the GPU is hidden from torch, and something in its
   `device="cpu"` codepath also re-enables `torch.cuda.is_available()` afterwards; the test harness
   (disposable driver scripts, not repo code) patches `ultralytics.engine.model.Model.__call__` to
   default `device="cpu"` and pins `torch.cuda.is_available = lambda: False` before Stage 3 loads.
   Result: preprocessed page, all detected strip crops, and all 4 voice `events.json` files
   (soprano/alto/tenor/bass) are **byte-for-byte identical** between HEAD and the branch (`diff`/
   `diff -rq` both clean). The branch's `manifest.json` for that run shows `status: completed`, all
   three stages `completed` with durations, correct dirty git commit — confirms the manifest captures
   provenance without altering pipeline output.
3. **Failure-path test — DONE, 2026-09-23, all checks pass.** `with RunManifest(runs_root=<scratch>)
   as m:` with `stage1_preprocessing` completing normally then `stage2_detection` raising
   `ValueError`. Confirmed: exception re-raised out of the `with` block (not swallowed); manifest
   top-level `status: "failed"`; `stages` shows `stage1_preprocessing: completed`,
   `stage2_detection: failed`; `error` block present with `type: "ValueError"`, the original message,
   and a non-empty traceback. One environment wrinkle (not a `run_manifest.py` bug): `_environment_info()`
   calls `torch.cuda.get_device_name(0)` gated on `torch.cuda.is_available()`, and in this environment
   `CUDA_VISIBLE_DEVICES=""` alone doesn't reliably make `is_available()` return `False` (same quirk hit
   in item 2 — see there for detail), so the CPU-only test harness pins
   `torch.cuda.is_available = lambda: False` directly rather than relying on the env var.
4. **Stage 4 CLI path and Stage 5 `run_full_pipeline()` path — DONE, 2026-09-23, both clean, CPU-only.**
   Stage 4's own `__main__` (Stages 1→4, real `RunManifest`) ran to completion: 48/37/32/36 events for
   S/A/T/B (matching item 2's counts exactly, same input), 5 pre-existing SATB duration-mismatch
   warnings printed (expected data-quality noise from this test image's transcription, unrelated to the
   manifest diff — not a regression). `run_full_pipeline()` (Stages 1→5) also ran to completion:
   `pydub`/`midi2audio` are confirmed not installed in this environment, so Stage 5 hit the documented
   fallback and returned `.mid` paths for all 4 voices instead of `.mp3` — exactly the anticipated,
   acceptable outcome, not a failure. Both manifests show `status: "completed"`, all 4–5 stages
   `completed` with durations; the Stage 5 manifest additionally shows the missing `soundfont/piano.sf2`
   recorded honestly as `{"exists": false}` rather than silently dropped or crashing, and all 8 expected
   `outputs` entries (4× events, 4× audio) present. One self-inflicted slip during this check: the Stage
   4 driver script omitted explicit `events_dir`/`viz_dir` overrides, so `transcribe_voice_sequences()`
   fell through to its dead `D:\PiyaNota (Code)\...` default (BUG-017, already logged, out of scope)
   and wrote 8 scratch files there — noticed and deleted immediately, not left behind; this was a test
   script oversight, not a manifest-branch behavior change.
5. **Self-verify + senior-reviewer — DONE, 2026-09-23. Verdict: recommend merge with changes; one
   real bug found and fixed.** senior-reviewer's most important finding: `RunManifest.__exit__`
   (`run_manifest.py`) only guarded `write()` against `OSError`, but `write()`'s `json.dump()` had no
   `default=` fallback — a non-JSON-serializable value anywhere in the manifest data (concretely:
   `checkpoint.get("epoch")` flowing into `add_asset(..., extra=...)` at
   `stage3_transcription.py:1721`, whose type depends on how the Kaggle notebook serialized it) would
   raise `TypeError` inside `__exit__`, which Python would then substitute for the real pipeline
   exception already propagating — silently discarding the actual failure this feature exists to make
   traceable. **Fixed:** `write()` now passes `default=str` to `json.dump`; `__exit__`'s guard widened
   from `except OSError` to `except (OSError, TypeError, ValueError)`. Verified with two targeted
   scenarios: (a) a non-serializable value in manifest data now writes cleanly via the `str` fallback;
   (b) an unfixable write error (circular reference, which `default=str` can't help) occurring while an
   original `ValueError` is already propagating now correctly surfaces the original `ValueError`, not
   the write failure — confirmed the original masking behavior is gone. Re-ran the item-2
   no-behaviour-change check after the fix: all 4 voice `events.json` files still byte-identical to
   HEAD — the fix doesn't touch the normal-path data captured, only the failure path.

   Six other findings, **not yet acted on, left for you to weigh in on**:
   - `process_strip()` always calls `transcribe_strip(..., return_confidence=True)` even when
     `manifest=None`, paying for confidence-decode overhead on every strip regardless of whether
     anything reads it — not an output-correctness bug (verified: decoded symbols are identical
     either way), but not literally free/additive either. Could gate on `return_confidence=manifest is
     not None`.
   - The shared hash-cache file (`sha256_file()`'s size+mtime fingerprint cache) has no file locking
     and a non-atomic write — safe for a single sequential pipeline run (confirmed: a changed file
     always re-hashes, a corrupted cache self-heals), but a real race risk if this backend ever serves
     concurrent pipeline runs (relevant if Module 3 becomes multi-worker).
   - Several new `RunManifest` methods (`set_params`, `add_input`, `add_stage_info`, `write`,
     `__enter__`/`__exit__`) have no docstring, inconsistent with the rest of the module
     (`add_asset`/`add_strip`/`stage()` are documented) and with CLAUDE.md's blanket Google-style-
     docstring rule.
   - `self.data`'s loose `Dict[str, JsonValue]` typing needs six `# type: ignore[...]` comments to
     mutate — a `TypedDict` or small per-section dataclass would model it more honestly.
   - Git hygiene: the working tree currently mixes the actual PIYA-106/BUG-017 code change with this
     session's unrelated doc updates (BUG-013–016, this file, a CLAUDE.md section) *and* untracked,
     pre-existing cruft from the earlier PIYA-201 mobile-scaffold session
     (`.claude/skills/video-analyzer/`, `mobile/piyanota_application/references/` — the latter has a
     51 MB `.mp4`) — a `git add -A`/`git add .` when committing would sweep all of it in. Must stage
     named files only; the BUG-013–016 doc updates arguably belong in a separate commit from the
     BUG-017 code fix.
   - `_greedy_ctc_decode` was refactored to route through a new `_greedy_ctc_decode_with_confidence`
     rather than left untouched with confidence tracking bolted on separately — behavior-preserving
     (backed by the byte-identical no-behaviour-change result) but worth calling out explicitly as a
     second, distinct kind of change bundled into what's otherwise described as additive wiring.

   Commit message prefix: `PIYA-106:` — only after user approval; still nothing committed.

### Deliberately out of scope (logged, not fixed)

- Dead `D:\PiyaNota (Code)\...` defaults in `stage3_transcription.py` (BUG-017, second half).
- Viz filename collision (BUG-014), tuplets (BUG-015), input-distribution experiments (BUG-016).
- The user was offered — and has not yet answered — a small script to run BUG-016's experiments.

---

## Retraining handoff (written 2026-09-19 — still current)

## Immediate next action

**The real two-seed `RUN_FINETUNING` run (under the cuDNN fix) is DONE.** Both checkpoints are valid
and not invalidated: `crnn_weights/finetuned_font_seed1.pt` (best epoch 1, `loo_font_ser` 0.0523) and
`crnn_weights/finetuned_font_seed2.pt` (best epoch **2**, `loo_font_ser` 0.0886, with an epoch-3
canary-clean spike to ~89% of the hard cap before partially recovering). ml-cv-lead's fourth review
this session: **conditional GO to Step 3 — Step 2 is not formally closed.**

**Start Step 3 now** — collect a fresh real-world test set (different piece/tool than the 48 strips
already used for BUG-011 diagnosis; needs new photos/screenshots from the user). This can run in
parallel with the open item below; neither blocks the other.

**Open items carried forward, not blocking Step 3 but not resolved — don't let these quietly drop:**
- Seed=2's best epoch was 2, not 1 — this **disconfirms** the earlier read (from two isolated seed=1
  repro runs) that "epoch-1-is-always-best" was a real property of `lr=3e-5`; it was
  checkpoint-selection luck. Do not switch to the `1e-5` runner-up candidate — it lacks equivalent
  seed-replication rigor and already lost to `3e-5` by ~24% relative in earlier seeded runs.
- Seed=2's epoch-3 canary-clean spike to ~89% of the hard cap is independently concerning — a real
  oscillation/stability signature, not just "the cap held."
- The ~70% relative gap between seed=1's best (0.0523) and seed=2's best (0.0886) is *not* cleanly
  within the established same-seed noise floor (7–29%, measured same-epoch/same-seed) — plausibly
  explained instead by `finetune_train_loader` (notebook cell 12) still having `shuffle=True` with no
  seeded `generator=`/`worker_init_fn`. **Report both seed checkpoints as a range going forward — never
  cherry-pick seed=1's better number.** Apply the DataLoader seeding fix before treating `lr=3e-5` as
  fully settled.
- At Step 4, evaluate both seed checkpoints separately against the real test set — do not average them.
- None of this round's findings say anything about whether the actual BUG-011 real-screenshot fix
  works — it's purely a training-stability question. The confidence/uncertainty problem (plan step 7)
  remains completely untouched.

Full narrative (seed-replication check results, RNG-leftover-state bug, cuDNN-nondeterminism bug and
fix, the lost-baseline finding, both reproduction runs, the real two-seed run, and all four ml-cv-lead
reviews from this session): 2026-09-16 and **2026-09-19 amendments** in
`docs/decisions/piya-106-crnn-font-retraining-plan.md`.

**Do not use `crnn_weights/finetuned_font.pt`** (first unseeded, buggy `RUN_FINETUNING` attempt) or
either `crnn_weights/finetuned_font_seed{1,2}.pt` produced **before** the 2026-09-17 cuDNN fix — those
are invalidated; only the versions from the completed run above are valid. The two
`crnn_weights/repro_check_seed1.pt` runs from this session are diagnostic-only, not Step 2 deliverables
either.

## Branches / commit state

- **`fix/bug012-border-blank-overreach`** — *(2026-09-23: since merged into `main` @ `2351623`; no longer the current branch)* — no longer a single uncommitted unit; it
  now carries multiple merged-in-sequence commits from BUG-012's fix through this session's Step 2
  work:
  - `59212f7` PIYA-125: fix Stage 1 border-blanking content destruction (BUG-012)
  - `6af7e1e` PIYA-106: font re-render Step 1 + two-tier canary gate for Step 2 fine-tuning
  - `6ea1faa` PIYA-106: amend retraining plan with two-tier canary gate + font_val_ser leakage finding
  - `edee99b` PIYA-106: fix font_val_ser leakage with invariant asserts + Leland LOFO probe
  - `944cdb5` PIYA-106: fix loo_font_ser checkpoint-selection leakage, add seed control to
    fine-tuning loop
  - plus a docs-only commit for this session's write-up (decision doc amendment, this file, the
    CLAUDE.md status update)
  Still pending: senior-reviewer pass + merge decision, once Step 2's real result is in — not done
  yet, don't treat this branch as merge-ready.
- **`docs/methodology-reorg`** (worktree) — documentation reorganization, unrelated to any bug fix.
  Still unmerged; unchanged this session.
- **`docs/decisions/module2-flutter-framework.md`** — untracked, unrelated Module 2 decision doc that
  showed up in `git status`. Not part of this thread's work; leave it alone unless the user raises it.

## Where the accuracy numbers actually stand

Full detail: `CLAUDE.md` → "Evaluation results snapshot" section, and `docs/bug-tracker.md`
(BUG-011, BUG-004). Unchanged since 2026-09-14 — Step 2 fine-tuning results aren't final yet, so
nothing here has been superseded by a new headline number.

- **CameraPrIMuS (the CRNN's training data):** 98%+ accuracy/SER, clean and even under synthetic
  distortion. This number is real but describes the training distribution only.
- **Real screenshots (actual deployment target):** true real-world accuracy is unmeasured and likely
  well below the old, now-retracted ~4.2% ceiling estimate. Root cause (ml-cv-lead reviewed): the
  CRNN has only ever seen one synthetic font; real engraving-software glyphs are a different shape
  it's never trained on. See BUG-011 in `docs/bug-tracker.md` for full detail.
- **DS2 Dense / YOLOv8 staff detector:** one number on record (mAP50 0.9766), but it's mislabeled —
  actually a val-split result, not test-split (BUG-004, open, unresolved NumPy crash blocking a
  real re-run). Don't quote this number as clean.

## The retraining plan — current step status

Full plan + amendments: `docs/decisions/piya-106-crnn-font-retraining-plan.md`

1. **Font re-render CameraPrIMuS via Verovio** — **done.**
2. **Fine-tune the existing CRNN checkpoint, watch clean/distorted CameraPrIMuS SER as a forgetting
   canary** — **substantively done, not formally closed.** LR sweep, extended trend check, and
   seed-replication check are done (lr=3e-5 confirmed over lr=1e-5, replicated across 2 seeds); the
   cuDNN-nondeterminism bug found after the first real two-seed run is fixed; the real two-seed final
   run under the fix is **complete** (`finetuned_font_seed1.pt` best epoch 1 / loo 0.0523,
   `finetuned_font_seed2.pt` best epoch 2 / loo 0.0886) and ml-cv-lead's fourth review gave a
   conditional GO. Not formally closed because of the open items above (DataLoader seeding gap, the
   seed1/seed2 divergence, seed=2's near-cap wobble) — none block starting Step 3, but should be
   resolved before calling Step 2 fully done.
3. Collect a **fresh** real-world test set (different piece/tool than the 48 strips already used for
   BUG-011 diagnosis) — **not started, now the active item**, needs new photos/screenshots from the
   user.
4. Evaluate once on that fresh set; token-level SER + insertion/deletion rate, not just clef/pitch
   accuracy — **not started**, blocked on step 3.
5. Only if still far short of target: escalate to hand-labeling real strips — **not started**.
6. Re-run the confidence (confident-right vs. confident-wrong) check with a real sample size —
   **not started**.
7. Treat "confidently wrong" predictions as a separate open problem from raw accuracy — **not started**.

## Things not to do without re-checking first

- Don't use `crnn_weights/finetuned_font.pt`, either `finetuned_font_seed{1,2}.pt` from before the
  2026-09-17 cuDNN fix, or `crnn_weights/repro_check_seed1.pt` — all invalidated or diagnostic-only
  (see above). The post-fix `finetuned_font_seed1.pt` / `finetuned_font_seed2.pt` (from the completed
  two-seed run) ARE valid and usable — but report them as a range (0.0523–0.0886 loo_font_ser), never
  cherry-pick seed=1's better number.
- Don't treat "epoch-1-is-always-best" as settled — that was a read from 2/2 *isolated seed=1* repro
  runs, and the real seed=2 run's best epoch was 2. Checkpoint-selection luck, not a property of
  `lr=3e-5`; disconfirmed, not confirmed, by the real two-seed run.
- Don't ignore seed=2's epoch-3 canary-clean spike (~89% of hard cap) — a real stability signature,
  flagged by ml-cv-lead's fourth review, not yet investigated.
- Don't assume the seed1/seed2 loo_font_ser gap (~70% relative) is just noise — it's larger than the
  established same-seed noise floor (7–29%) and is plausibly caused by the still-unfixed
  `finetune_train_loader` DataLoader seeding gap (cell 12, `shuffle=True`, no `generator=`/
  `worker_init_fn`).
- Don't hand-label real Filipino sheet music as a first move — the diagnosed cause is font/glyph
  shape, not content or language.
- Don't reuse the 48 BUG-011 diagnostic strips to report the retrained model's accuracy.
- Don't blend CameraPrIMuS and real-world accuracy into one aggregate number in any future report.
- Don't present a single-seed `loo_font_ser` number as a settled result — report it as a 2-seed
  range/distribution per the current notebook structure, and remember `loo_font_ser` is still
  confounded by content-familiarity leakage (Leland is held out of training, but the same passages
  Leland renders were seen by the base model in other fonts) — flag this whenever the number is
  quoted, don't present it as an independent confirmation.
- Don't commit `docs/decisions/module2-flutter-framework.md` as part of PIYA-106 work — unrelated.
- Don't commit anything without the user's explicit review/approval first (standing rule).

## Reference index

- `CLAUDE.md` — project instructions + evaluation results snapshot + retraining plan pointer.
- `docs/bug-tracker.md` — BUG-011 (font domain gap, full falsification trail), BUG-012 (fixed,
  merged into this branch's history), BUG-004 (DS2 Dense eval mislabeled split, open).
- `docs/tickets/module1-pipeline.md` — PIYA-107 (pitch inference) real-screenshot measurement note,
  PIYA-125 (BUG-012 fix) status.
- `docs/decisions/piya-106-crnn-font-retraining-plan.md` — the full retraining decision record,
  including the 2026-09-16 amendment with the seed-replication data and RNG-bug root cause.
- `training/step1-font-rerender-kaggle-guide.md` — verified, runnable Step 1 instructions (Kaggle).
- `training/piyanota-training-ver-2.ipynb` — the CRNN training notebook. Cell 13
  (`finetune()`/`lr_sweep()`/`RUN_FINETUNING`) is the active edit surface for Step 2; requires an
  explicit `seed=` argument now (hard assert), and the real run always trains both seed=1 and
  seed=2 from a fresh copy of the base checkpoint.
