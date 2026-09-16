# PIYA-106 — CRNN Retraining Plan for Real-World Font Domain Gap (BUG-011)

**Status:** Decided 2026-09-14, ml-cv-lead reviewed. Step 1 verified runnable; steps 2–7 not yet
started. **Decides for:** `docs/tickets/module1-pipeline.md` PIYA-106 AC4, `docs/bug-tracker.md`
BUG-011.

## Why this exists

BUG-011 (bug-tracker.md) root-caused the CRNN's real-screenshot failure (clef misread on 46/48 real
strips, ~4.2% bounded real-world pitch accuracy) to a **font/glyph domain gap**: the CRNN
(`training/pianota-transcription-training.ipynb`) is trained and validated exclusively on
CameraPrIMuS — one synthetic engraving font, clean plus a programmatic camera-distortion simulation
of that *same* font. It has never seen real engraving-software output (MuseScore/Finale/Sibelius/
Verovio-default styles), and nothing image-preprocessing-only has fixed it (thresholding, dilation,
erosion all falsified — see BUG-011). This is not a Filipino-content or language issue — lyrics are
already stripped pre-detection (`blank_lyrics_regions()`), and nothing in the evidence trail
implicates script/language. It is purely: **the model has only ever seen one glyph shape.**

ml-cv-lead reviewed this plan (full transcript context: async review, 2026-09-14) before it was
adopted, per CLAUDE.md's mandatory pre-training-code review rule.

## Decision: font re-rendering before hand-labeling

**Do not start by hand-labeling real Filipino sheet music.** CameraPrIMuS's own `.agnostic`/
`.semantic` ground truth already exists for every training sample, and — newly confirmed this
session — so does an `.mei` (Music Encoding Initiative XML) file per sample, which Verovio (the tool
CameraPrIMuS's own `.mei` files were generated with) can re-render through **5 different bundled
SMuFL music fonts** (Leipzig, Bravura, Petaluma, Gootville, Leland) with **zero manual
transcription** — the note/symbol content is byte-identical, only the glyph rendering style changes,
so the existing `.agnostic`/`.semantic` labels remain valid ground truth for every re-render.

This is a genuine **data fix** (expands the training distribution) rather than a preprocessing patch,
per ml-cv-lead's cost framing — durable against any of the 5 fonts it now includes, but still only as
durable as the font list; a 6th unseen engraving tool could still fail until added.

## Ordered plan

1. **Font re-rendering (this ticket's immediate next step).** Re-render every CameraPrIMuS sample's
   `.mei` through the 5 bundled Verovio SMuFL fonts, producing new image+label pairs with no manual
   labeling. Built directly into `training/pianota-transcription-training.ipynb` (top section); see
   `training/step1-font-rerender-kaggle-guide.md` for verified, runnable instructions and rationale.
   Switched from Colab to Kaggle 2026-09-15 — the base CRNN training already runs there, and Kaggle
   attaches the CameraPrIMuS dataset natively with no download step.
2. **Fine-tune the existing CRNN checkpoint** (not train from scratch) on original + font-varied
   data. Track clean-CameraPrIMuS-SER and distorted-CameraPrIMuS-SER as catastrophic-forgetting
   canaries during training (the notebook already computes both per epoch) — set an explicit
   numeric floor before accepting a checkpoint (e.g. no more than a few points below the current
   ~98%/87% baseline), not just "didn't collapse to zero."
3. **Collect a small NEW real-world test set** before evaluating: different piece(s) than the
   "Amanamin" set already used for BUG-011 diagnosis, ideally a different engraving tool/export,
   roughly 100+ strips, balanced across the clef classes SATB actually uses (treble, treble-8vb/
   tenor — visually identical to treble, `get_clef_reference()` already resolves the octave from
   voice identity not a distinct token — and bass). **Do not touch this set until step 4** — the
   48 strips already used for BUG-011 diagnosis are spent and must not be reused to report the
   fine-tuned model's accuracy (that would be leakage).
4. **Test once** on that fresh set. Report real-world accuracy separately from the CameraPrIMuS
   number — never blended into one aggregate. **Updated 2026-09-14 (ml-cv-lead review of the
   non-clef token diagnostic, see BUG-011):** score full-sequence token-level SER (edit distance)
   against real ground truth as a first-class metric here, not just clef accuracy or pitch accuracy
   — the pre-fix baseline showed non-clef tokens (notes, accidentals, rests) are also badly wrong,
   not just offset by a bad clef. Report insertion/deletion rate separately from substitution rate:
   hallucinating extra beamed-note clusters is a different failure mode (decoder/representation
   collapse) than misreading one note's pitch, and conflating them hides which failure mode the
   font retrain actually fixes. Add a go/no-go checkpoint here, before proceeding to steps 5–7: if
   clef accuracy improves but insertion/hallucination rate on other tokens doesn't, that points to a
   second confound (real capture noise, real paper/engraving spacing, the strip-height stretch, or
   residual BUG-002 label-bleed) that font-swap alone won't fix — stop and re-diagnose rather than
   proceeding on the assumption that closing the font gap closes everything.
5. **If still far short of target**, that tells us font alone isn't sufficient — only then plan
   targeted hand-labeling of a few hundred real strips, preferring CRNN-draft + human-correction
   over from-scratch transcription (faster), with spot-audits against the source image (a human
   "correcting" a wrong draft can anchor to the model's own mistake on ambiguous glyphs).
6. **Re-run the confidence check** (wrong-vs-correct softmax confidence) on the new held-out set
   with a real sample size in both arms — the BUG-011 confidence comparison (0.79 vs 0.88) had only
   n=2 correct examples and is statistically underpowered, not a confirmed "no signal" result.
7. **Treat "confidently wrong" as a separate open problem from raw accuracy**, regardless of
   outcome — even a much-improved model needs a way to flag low-trust predictions before this ships,
   since it currently can't distinguish confident-right from confident-wrong.

## Amendment (2026-09-15): canary gate redesign after LR-sweep breach

Step 2's `finetune()` originally hard-stopped the instant either canary SER (a 95% bootstrap CI on the
base checkpoint's own per-sample SER over the held-out canary set) was crossed, with zero tolerance —
locked in by ml-cv-lead's 2026-09-14 review (step 2 above). The first LR sweep
(`lr_sweep([1e-5, 3e-5, 1e-4])`) breached the **clean** canary floor at epoch 1 for all three
candidates (never the distorted floor, which stayed 42–48% under its own floor at every LR), stopping
each run before any checkpoint could be saved.

Two independent reviews (ml-cv-lead, then ml-cv-lead again specifically on its own proposed fix's
risks, then senior-reviewer grounded in the actual notebook code) concluded: the bootstrap CI bounds
*resampling variance* (which 399 canary items you happened to draw), not *weight-perturbation
variance* (how much a fixed eval set moves once real gradient steps are taken) — so an epoch-1 breach
is close to that gate's expected behavior regardless of whether real capability was lost, not proof
fine-tuning is unsafe. It isn't pure noise either: breach magnitude scaled monotonically with LR
(7.7% → 17.2% → 75% relative overshoot), a real dose-response. Only one epoch of data existed per LR,
which cannot distinguish a transient epoch-1 bump from real, worsening catastrophic forgetting.

**Revised gate (supersedes the zero-tolerance rule above):** two-tier.
- The original bootstrap CI stays exactly as computed, but becomes a **diagnostic-only** signal — still
  logged every epoch, no longer able to stop a run on its own.
- A new **hard cap**, `CANARY_HARD_CAP_MULTIPLIER = 3.0` applied to each canary subset's own baseline
  mean SER, is the sole enforced auto-stop. This value is an explicit human judgment call (picked to
  give real headroom above the worst epoch-1 sweep result, ~0.0955 clean SER at lr=1e-4, while still
  catching genuinely runaway forgetting) — **not statistically derived**, same caveat that applied to
  the original floor. Revisit if the 3-epoch trend data below shows it's miscalibrated in either
  direction.
- Every checkpoint (per-epoch, not just "best") now saves regardless of gate status, tagged with a
  `gate_mode` field and both threshold values, so which regime produced a given checkpoint is always
  recoverable from the file itself.
- **font_val_ser's stem-overlap leakage — confirmed 100%, not a residual risk (2026-09-16).**
  Real Cell B output from the LR-sweep run: `359/359 font-val stems (100.0%) were already seen by the
  base model during its original CameraPrIMuS training`. This is not sampling variance — it's
  structural: `finetune_val_stems` is drawn from `combined_by_stem` after only `CANARY_VAL_STEMS` (the
  base model's own 399-stem val slice) is excluded, so the remaining pool is *exactly*
  `BASE_TRAIN_STEMS` (3596) by construction — any split of it is guaranteed ~100% base-training overlap,
  not a possibility that happened to land at the high end. ml-cv-lead review (2026-09-16): this gives
  `font_val_ser` **zero evidentiary value for font-domain generalization**, not reduced value — a
  BiLSTM+CTC decoder can partially recall a memorized incipit's token sequence from a weak read of an
  unfamiliar font via a learned sequence prior, so a low `font_val_ser` largely re-measures the same
  thing `canary_clean_ser` already does (memorized-content stability), not font-learning quality. It is
  **not fixed by this amendment** and does **not** block the plan's actual go/no-go (Step 4, gated on
  Step 3's fresh real-world test set, which this leak never touched) — but do not cite `font_val_ser`,
  including any number already produced by the live LR sweep, as evidence one LR "generalizes better"
  than another; treat it only as a collapse/divergence sanity check until fixed. **Required before
  `RUN_FINETUNING` is flipped to `True`:** carve a disjoint font-val stem set out of `BASE_TRAIN_STEMS`
  itself (not `CANARY_VAL_STEMS`, which must stay reserved for the forgetting probe) and exclude it from
  `finetune_train_stems` — a small change to cell 12's split logic, not a new data-collection effort.
  The hard-cap/soft-floor canary gates are unaffected by this leak (computed on the genuinely disjoint
  canary set) and remain valid stop/continue signals in the meantime.

Next: re-run `lr_sweep([1e-5], sweep_epochs=3)` (smallest-breach candidate) for the full 3-epoch budget
under this gate to get the actual clean/distorted canary trend, before touching `RUN_FINETUNING`. Per
the leakage finding above, also patch cell 12's font-val split before that flag is flipped.

## Caveats carried forward from ml-cv-lead's review (do not silently drop these)

- The BUG-011 real-screenshot evidence is effectively single-source (one piece, one engraving tool)
  even though 3 fonts total were "tested" — only the synthetic Segoe UI Symbol test is a clean,
  single-variable-isolated result; the real-screenshot data point is real but n=1-sourced.
- The Segoe UI Symbol font test was run on a bare synthetic staff, not a cluttered real strip. Font
  swap and realistic strip context (label text, dynamics) must be tested **together**, not just
  font-in-isolation, before concluding font alone closes the gap — see step 1's Condition A/B split
  in the Colab guide.
- Label-bleed is inconclusive, not ruled out, per the bug-tracker.md correction log.

## Amendment (2026-09-16): seed-replication check + RNG-leftover-state bug

Step 2's fine-tuning is now underway (font_val_ser's 100%-overlap leakage from the amendment above
was fixed by switching checkpoint/early-stop selection to `loo_font_ser`, measured on `LOO_FONT`
(Leland), which is held out of training entirely — see the fixed notebook cell 13).

**Extended trend check (no seed control):** `lr_sweep([3e-5, 1e-5], sweep_epochs=8, patience=2)` found
lr=3e-5 best at epoch 1 (`loo_font_ser` 0.0485, canary fully clean) and lr=1e-5 best at epoch 3
(0.0723). But a repeat of lr=1e-5 epoch 1 under the same uncontrolled conditions swung from 0.0608 to
0.1111 (~83% relative) between two runs — bigger than the gap being used to rank LRs — so the 0.0485
headline number could not yet be trusted.

**Seed-replication check:** added an explicit `seed` parameter to `finetune()`/`lr_sweep()` and ran
2 seeds (1, 2) × 2 LRs (3e-5, 1e-5) × 2 epochs, all else held fixed:

| seed | lr=3e-5 (best) | lr=1e-5 (best) |
|---|---|---|
| 1 | 0.0540 (epoch 1) | 0.0702 (epoch 1) |
| 2 | 0.0696 (epoch 2) | 0.0924 (epoch 2) |

lr=3e-5 beat lr=1e-5 in both seeds by a consistent ~24% relative margin — real, replicated signal for
picking lr=3e-5. But the earlier 0.0485 headline number sits *below* both seeded runs and should not
be trusted as representative; treat 0.054–0.073 as the realistic range instead. Canary hard cap was
never breached in any of the 4 runs.

ml-cv-lead review of this data flagged two open risks carried into the real run: (1) `loo_font_ser`
is itself noisy — lr=1e-5 epoch 1 still swung ~61% relative between seeds even under explicit seeding
(0.0702 vs 0.1132), so single-epoch deltas under ~0.02 aren't trustworthy signal on their own; (2)
epoch-of-best flips direction between seeds for lr=3e-5 (seed=1 peaked at epoch 1 then dropped ~81%
relative by epoch 2; seed=2 was still improving at epoch 2), and neither seed had epoch-3+ data.
Recommendation: keep lr=3e-5, raise `patience` from 2 to 3 (one more epoch of runway to tell a
recoverable dip from real decline), keep `max_epochs=6`. Also flagged a procedural-leakage risk to
carry forward: `loo_font_ser` off the single held-out font (Leland) is being used for both LR/
checkpoint selection *and* will likely be the reported "did this work" number — not fixable without a
second held-out font, but the eventual reported number should carry this caveat, not be presented as
an independent confirmation.

**RNG-leftover-state bug (found after the first real `RUN_FINETUNING` attempt):** the real run was
launched without passing `seed=` (an oversight). It reported `loo_font_ser=0.0398` at epoch 1 — lower
than every prior epoch-1 lr=3e-5 result, including the untrusted 0.0485 outlier — then degraded
monotonically for 3 more epochs (0.0469 → 0.1024 → 0.1476), with canary-clean closing to within ~7%
of its hard cap before stopping on the new patience=3. ml-cv-lead assessed this as implausible as an
independent draw (below the minimum of the seeded band, and the *second* unseeded run in a row to
beat every seeded run — a pattern, not noise) and flagged mechanism (a), leftover RNG state, as most
likely. Root-caused directly: `finetune()` only touches RNG state when `seed is not None`, and this
whole workflow runs by editing Cell C in place and re-running it in the *same* Kaggle kernel without
restarting — so an unseeded call doesn't draw fresh randomness, it inherits whatever RNG state the
previous cell execution left behind (here, the tail end of the seed-replication check's seed=2/
lr=1e-5 sub-run). `0.0398` was a deterministic replay keyed on execution history, not a real result.

**`crnn_weights/finetuned_font.pt` (the epoch-1 checkpoint from that run) must not be used downstream.**

**Fix applied (notebook cell 13):** `finetune()` now hard-fails (`assert seed is not None`) if called
without an explicit seed, closing off this class of bug. The real `RUN_FINETUNING` block is
restructured to fine-tune under both validated seeds (1 and 2), each from a fresh copy of the base
checkpoint (mirrors `lr_sweep()`'s pattern so seed 2 doesn't train on top of seed 1's weights), saving
to `crnn_weights/finetuned_font_seed{1,2}.pt` and reporting `loo_font_ser` as a 2-seed distribution,
not a single cherry-picked number.

**Status:** rerun not yet executed by the user — this is the immediate next action (see
`docs/NEXT-SESSION.md`). Once it completes, get ml-cv-lead sign-off on the 2-seed result before
treating either checkpoint as this plan's Step 2 output and moving to Step 3.

## Not yet decided / blocked

- Whether the base Camera-PrIMuS training run needs to finish first, or whether fine-tuning can
  start from the currently-deployed checkpoint directly — re-confirm with the user before step 2.
  **Superseded in practice 2026-09-16:** fine-tuning has been actively running (LR sweep, extended
  trend check, seed-replication check, and a real `RUN_FINETUNING` attempt) without this being
  re-blocked, so treat this constraint as no longer in force unless the user says otherwise.
- Sourcing a genuinely new real-world test set (step 3) requires new photos/screenshots the user
  needs to supply; not something this repo's existing data covers.
