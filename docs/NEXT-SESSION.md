# Next Session — Start Here

Handoff doc for continuing PiyaNota work in a fresh session. Read this first; it links out to the
full detail rather than repeating it. Written 2026-09-14, rewritten 2026-09-16, rewritten 2026-09-19.

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

- **`fix/bug012-border-blank-overreach`** (current branch) — no longer a single uncommitted unit; it
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
