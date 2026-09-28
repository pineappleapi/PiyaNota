# PIYA-106 — CRNN Retraining Plan for Real-World Font Domain Gap (BUG-011)

**Status:** Decided 2026-09-14, ml-cv-lead reviewed. Step 1 verified runnable; steps 2–7 not yet
started. **Decides for:** `docs/tickets/module1-pipeline.md` PIYA-106 AC4, `docs/bug-tracker.md`
BUG-011.

## Why this exists

BUG-011 (bug-tracker.md) root-caused the CRNN's real-screenshot failure (clef misread on 46/48 real
strips, ~4.2% bounded real-world pitch accuracy) to a **font/glyph domain gap**: the CRNN
(`training/piyanota-training-ver-2.ipynb`) is trained and validated exclusively on
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
   labeling. Built directly into `training/piyanota-training-ver-2.ipynb` (top section); see
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

## Amendment (2026-09-19): cuDNN-fix reproduction confirmed via same-seed comparison; GO on the real two-seed run

**Original baseline is permanently lost.** The per-epoch checkpoints from the real two-seed
`RUN_FINETUNING` run's seed=1 sub-run (the "clean 4-epoch" reference the cuDNN fix above was meant to
reproduce) are confirmed gone — user does not have them, not recoverable. This closes off directly
comparing a post-fix rerun against real original numbers; "reproducible" can only mean same-seed-vs-
same-seed agreement under the fix from here on.

**Two independent isolated seed=1 reproduction runs**, same config each time (`seed=1`, `lr=3e-5`,
`max_epochs=6`, `patience=3`, fresh kernel), both via the dedicated `repro_model = ...` cell
(`weights_out="crnn_weights/repro_check_seed1.pt"` — diagnostic-only, not a Step 2 deliverable):

| Epoch | Run 1 loo_font_ser | Run 1 canary clean | Run 2 loo_font_ser | Run 2 canary clean |
|---|---|---|---|---|
| 1 | 0.0561 | 0.0490 | 0.0523 | 0.0445 |
| 2 | 0.0925 | 0.0872 | 0.0789 | 0.0706 |
| 3 | 0.1198 | 0.1153 | 0.0855 | 0.0851 |
| 4 | 0.1067 | 0.0982 | 0.0906 | 0.0878 |

Both runs: best epoch 1, soft-floor breach every epoch from 2 on (diagnostic only), hard caps (clean
0.1502 / distorted 0.6261) never crossed, patience-stop at epoch 4. Same shape both times —
categorically unlike the pre-fix failure (hard-cap breach by epoch 2 vs. a clean run), which is the
property that actually matters for trusting a checkpoint-selection run.

**ml-cv-lead reviewed this in three rounds** (all three async reviews this session):
1. After run 1 alone: *partial confirmation, not a clean go* — flagged n=1 as thin evidence, flagged
   that the comparison was against a verbal description of the lost original (not real numbers), and
   flagged the epoch-1-best-then-decline shape as a possible independent LR/schedule concern.
2. Follow-up once the original checkpoints were confirmed unrecoverable: recommended a second
   same-seed=1 repro (the only way left to test the fix's actual determinism claim) before spending
   compute on the real two-seed run; noted best-checkpoint selection already de-risks shipping even if
   the decline's cause stays unexplained, but said not to close that finding silently.
3. After run 2: **GO.** The two runs agreeing on every qualitative property (not just magnitude) is
   what matters. The ~26–29% relative divergence at epoch 3 (loo_font_ser 0.1198 vs 0.0855; canary
   clean 0.1153 vs 0.0851) is real residual nondeterminism, not just noise — but the metric actually
   acted on, best-checkpoint selection, only diverged ~7% (epoch 1: 0.0561 vs 0.0523), so it doesn't
   block proceeding.

**Root cause of the residual divergence, confirmed in the notebook (not yet fixed):**
`finetune_train_loader = DataLoader(finetune_train_ds, batch_size=16, shuffle=True, ...)` in cell 12
has no seeded `generator=` and no `worker_init_fn` — unseeded shuffle/worker RNG is the likely source.
Offered to the user as an optional parallel improvement (per ml-cv-lead, not required to trust this
run's output); not applied as of this writing. Open follow-up.

**Epoch-1-best-then-monotonic-decline, identical in 2/2 independent runs, is flagged as MORE
concerning, not less.** ml-cv-lead's read: this is a real, reproducible property of `lr=3e-5` (fine-
tuning past epoch 1 is actively counterproductive on this metric), not noise. Shipping the epoch-1
checkpoint is pragmatically fine since checkpoint selection already picks it — but this must be logged
as a separate open item and not silently closed once Step 2 wraps.

**The real two-seed `RUN_FINETUNING` run (under the cuDNN fix) has now completed.** Results:

| seed | best epoch | best loo_font_ser | notes |
|---|---|---|---|
| 1 | 1 | 0.0523 | exact numeric match to the second isolated seed=1 repro run above |
| 2 | 2 | 0.0886 | epoch 3 canary-clean spiked to 0.1344 — ~89% of the 0.1502 hard cap, closest any run has come to breaching it, before partially recovering by epoch 4–5 |

Checkpoints: `crnn_weights/finetuned_font_seed1.pt`, `crnn_weights/finetuned_font_seed2.pt` — both
valid (produced under the cuDNN fix), neither invalidated.

**ml-cv-lead's final review (fourth round this session): conditional GO to Step 3, Step 2 not fully
closed.**
1. Seed=2's best-epoch=2 **disconfirms** the "epoch-1-is-always-best" read from the two isolated repro
   runs — that was checkpoint-selection luck on `lr=3e-5`, not a real property of it. Do **not** switch
   to the `1e-5` runner-up candidate though — it's never had equivalent seed-replication rigor at this
   budget, and `3e-5` still beat it ~24% relative in the earlier seeded 2-epoch runs; swapping now would
   trade a known instability for an unquantified one.
2. The epoch-3 near-hard-cap spike (seed=2) is **independently concerning** — a real
   stability/oscillation signature, not just "never technically breached." The hard cap's safety margin
   is thinner in practice than assumed when `CANARY_HARD_CAP_MULTIPLIER = 3.0` was set.
3. The ~70% relative gap between seed=1's best (0.0523) and seed=2's best (0.0886) is **not cleanly
   "within the established noise floor"** — that floor (7%/26–29%) was same-epoch, same-seed; this
   compares different best-epochs across different seeds. More telling: seed=1's own epoch-2 value
   (0.0782) is already close to seed=2's epoch-2 best (0.0886) — suggesting seed=2 had a systematically
   noisier trajectory overall, plausibly from the still-unfixed unseeded `finetune_train_loader`
   shuffle/worker RNG (see above), not a clean independent draw from one distribution.
4. **Carry forward BOTH seed checkpoints, reported as a range — do not cherry-pick seed=1's better
   number** (the plan already required this). **Step 3 (fresh real-world test set collection) may start
   in parallel** — it's orthogonal to this finding. But the epoch-1-vs-2 flip and the near-cap wobble
   must be logged as open, unresolved findings, not silently closed, and the DataLoader seeding fix
   should be applied before treating `lr=3e-5` as fully settled. At Step 4, evaluate both seed
   checkpoints separately against real data — do not average them. None of this is evidence about
   whether the actual BUG-011 real-screenshot fix works — it's purely about training stability; the
   confidence/uncertainty problem (plan step 7) remains completely untouched regardless of outcome.

**Status:** Step 2 substantively done (both checkpoints exist, usable, not invalidated) but **not
formally closed** — the LR-stability question above is an open item, not a blocker for starting Step 3.
**Immediate next action:** start Step 3 — collect a fresh real-world test set (different piece/tool
than the 48 BUG-011 diagnostic strips) — in parallel with, at the user's discretion, applying the
DataLoader seeding fix noted above. Both are needed before Step 2 can be called fully closed and before
Step 4 evaluation begins.

### Amendment 2026-09-23 -- second real two-seed `RUN_FINETUNING` run; "reproducible under the cuDNN fix" falsified

A fresh two-seed run (same tracked notebook, `RUN_FINETUNING=True`, cuDNN determinism fix present,
Step 1 data read from the persisted `piamac/cpm-font-augmented2` dataset, lr=3e-5) did **not** reproduce
the 2026-09-19 numbers. Both checkpoints were verified on disk and their metadata matches the logs:
`finetuned_font_seed1.pt` (epoch 2, `loo_font_ser` 0.0926) and `finetuned_font_seed2.pt` (epoch 2,
`loo_font_ser` 0.0562). Hardware/torch/cuDNN versions for this run were **not logged**.

| Run | seed=1 best (epoch) | seed=2 best (epoch) |
|---|---|---|
| 2026-09-19 repro runs (isolated) | 0.0561 (1), 0.0523 (1) | -- |
| 2026-09-19 real two-seed run | 0.0523 (1) | 0.0886 (2) |
| 2026-09-23 real two-seed run | 0.0926 (2) | 0.0562 (2) |

Per-epoch, 2026-09-23: seed=1 `loo_font_ser` 0.1145 / 0.0926 / 0.1815 with the canary clean hard cap
(0.1502) **breached at epoch 3** (0.1730), stopped there; seed=2 0.0877 / 0.0562 / 0.0880 / 0.1055 /
0.1182, stopped by patience after epoch 5. Seed=1 epoch 1 took 968s vs ~500s for every other epoch
(possible different GPU node or cold cache -- unconfirmed).

**ml-cv-lead review (5th round) -- verdict: sound with caveats.**
1. Seed=1 epoch-1 best moved 0.0523 -> 0.1145 with identical seed and code (>2x). Two plausible
   causes, not separable from the logs: (a) different Kaggle GPU / cuDNN / driver stack --
   `cudnn.deterministic=True` only guarantees determinism within one hardware+software stack; (b) the
   still-unseeded `finetune_train_loader` shuffle. The earlier 4-digit agreement between two runs was
   likely a shared hardware path or coincidence. The 7% / 26-29% same-seed noise floor was measured on
   one stack and does not carry over. **The claim "reproducible under the cuDNN fix" is withdrawn.**
2. **Report every run as a range** -- best `loo_font_ser` spans 0.052 to 0.093 across all runs (1.8x).
   Do not average, and do not call either seed "better": the seed ranking flipped between the two real
   runs, so seed identity carries no information; run-level variance dominates.
3. Best-at-epoch-1/2-then-decline or oscillation now appears in 4 of 5 runs and every run ends worse
   than its best: a property of constant `lr=3e-5` on this data, not a seed effect. It does **not**
   favour `1e-5` (still no replication behind it). Warmup + cosine decay (`T_max` = 3-4 epochs, keep
   early stopping) is a reasonable single-variable ablation -- run it as a separately labelled
   experiment after the DataLoader seeding fix, not folded into Step 2's closure. The canary hard cap
   is actively load-bearing (seed=1 breached at epoch 3 here; seed=2 reached ~89% of it on 2026-09-19).
4. **Step 3 may start now; Step 2 stays open.** Carry both seed checkpoints of the current run into
   Step 4 and evaluate them separately, never averaged (the 2026-09-19 checkpoints, if still held, may
   be evaluated as well, also separately).

**Corrections / caveats.** The 2026-09-19 amendment above states seed=1's own epoch-2 value as 0.0782;
that figure was not verified against a saved log in this review -- treat it as unverified. The
Leland-held-out `loo_font_ser` is used for per-epoch best-selection, so its best value is optimistically
biased and is not an unbiased estimate; it is also a single held-out font (n=1), a weak proxy for
unseen real fonts. `font_val_ser` has a confirmed stem-overlap leak and must not be cited. Step 4 must
also re-measure CameraPrIMuS clean/distorted numbers to check for forgetting (the canary is a proxy,
not a replacement). None of this speaks to confidence calibration (step 7), and none of it is evidence
about whether the BUG-011 real-screenshot fix works.

**Follow-ups (before any further fine-tuning):** seed the `finetune_train_loader` shuffle (notebook
cell 12/13) and log GPU model + torch/CUDA/cuDNN versions per run -- implemented in the commit that
follows this amendment. Step 3 (fresh real-world test set) remains the next action and needs new
photos/screenshots from the user.

### Amendment 2026-09-26 -- which checkpoints are deployed

**Checkpoint metadata, authoritative (2026-09-26, user decision: use the files' own metadata; sha256 matches data/eval_dsmn/checkpoint_hashes.txt):** the deployed `finetuned_font_seed{1,2}.pt` are from the 2026-09-23 two-seed run, not the 2026-09-19 run: seed1 epoch 2, `loo_font_ser` 0.0926, canary clean/distorted 0.0785/0.1311; seed2 epoch 2, `loo_font_ser` 0.0562, canary 0.0492/0.0865. Report as a range (0.0562-0.0926). The 0.0523/0.0886 figures above refer to the 2026-09-19 run whose checkpoints were overwritten.

## Not yet decided / blocked

- Whether the base Camera-PrIMuS training run needs to finish first, or whether fine-tuning can
  start from the currently-deployed checkpoint directly — re-confirm with the user before step 2.
  **Superseded in practice 2026-09-16:** fine-tuning has been actively running (LR sweep, extended
  trend check, seed-replication check, and a real `RUN_FINETUNING` attempt) without this being
  re-blocked, so treat this constraint as no longer in force unless the user says otherwise.
- Sourcing a genuinely new real-world test set (step 3) requires new photos/screenshots the user
  needs to supply; not something this repo's existing data covers.
