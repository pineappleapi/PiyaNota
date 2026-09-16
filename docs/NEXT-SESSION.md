# Next Session — Start Here

Handoff doc for continuing PiyaNota work in a fresh session. Read this first; it links out to the
full detail rather than repeating it. Written 2026-09-14, rewritten 2026-09-16.

## Immediate next action

**Run the corrected two-seed final fine-tune on Kaggle** — Step 2 of the CRNN retraining plan
(`training/pianota-transcription-training.ipynb`, cell 13, `RUN_FINETUNING` block):

1. Paste the *current* Cell C fresh into the Kaggle kernel (don't patch just the lines that errored —
   the whole cell was rewritten this session).
2. Confirm `RUN_SEED_REPLICATION_CHECK = False` and set `RUN_FINETUNING = True`.
3. Run it. It fine-tunes from the base checkpoint under **both** seed=1 and seed=2 (not just one —
   this was an explicit choice over the cheaper single-seed option), saving
   `crnn_weights/finetuned_font_seed1.pt` and `crnn_weights/finetuned_font_seed2.pt`, and prints a
   ranked summary of `loo_font_ser` by seed at the end.
4. Paste back the full output (both `### Final fine-tune: seed=... ###` blocks plus the ranked
   summary).

**Then consult ml-cv-lead again** (per CLAUDE.md's Agent Usage Rules) before treating either
checkpoint as final or moving to Step 3 — this is required, not optional, and has been the pattern
for every round of results so far this plan.

Full narrative of how we got here (seed-replication check results, two ml-cv-lead reviews, the
RNG-leftover-state bug and its fix): 2026-09-16 amendment in
`docs/decisions/piya-106-crnn-font-retraining-plan.md`.

**Do not use `crnn_weights/finetuned_font.pt`** — it's the invalidated output of the first
(unseeded, buggy) `RUN_FINETUNING` attempt. See the amendment doc for why.

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
   canary** — **in progress.** LR sweep, extended trend check, and seed-replication check are done
   (lr=3e-5 confirmed over lr=1e-5, replicated across 2 seeds); the real two-seed final run is the
   immediate next action above.
3. Collect a **fresh** real-world test set (different piece/tool than the 48 strips already used for
   BUG-011 diagnosis) — **not started**, needs new photos/screenshots from the user.
4. Evaluate once on that fresh set; token-level SER + insertion/deletion rate, not just clef/pitch
   accuracy — **not started**, blocked on step 3.
5. Only if still far short of target: escalate to hand-labeling real strips — **not started**.
6. Re-run the confidence (confident-right vs. confident-wrong) check with a real sample size —
   **not started**.
7. Treat "confidently wrong" predictions as a separate open problem from raw accuracy — **not started**.

## Things not to do without re-checking first

- Don't use `crnn_weights/finetuned_font.pt` — invalidated (see above).
- Don't skip ml-cv-lead review of the two-seed final-run output before calling Step 2 done.
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
- `training/pianota-transcription-training.ipynb` — the CRNN training notebook. Cell 13
  (`finetune()`/`lr_sweep()`/`RUN_FINETUNING`) is the active edit surface for Step 2; requires an
  explicit `seed=` argument now (hard assert), and the real run always trains both seed=1 and
  seed=2 from a fresh copy of the base checkpoint.
