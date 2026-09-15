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
- font_val_ser's stem-overlap leakage with the base model's original training data (already flagged
  inline in notebook cell 12) is **not fixed by this amendment** — it remains a known caveat and a
  separate follow-up (build a held-out font-val stem set disjoint from base-training stems). Do not
  cite font_val_ser as evidence of font-domain generalization in any go/no-go call until that follow-up
  lands.

Next: re-run `lr_sweep([1e-5], sweep_epochs=3)` (smallest-breach candidate) for the full 3-epoch budget
under this gate to get the actual clean/distorted canary trend, before touching `RUN_FINETUNING`.

## Caveats carried forward from ml-cv-lead's review (do not silently drop these)

- The BUG-011 real-screenshot evidence is effectively single-source (one piece, one engraving tool)
  even though 3 fonts total were "tested" — only the synthetic Segoe UI Symbol test is a clean,
  single-variable-isolated result; the real-screenshot data point is real but n=1-sourced.
- The Segoe UI Symbol font test was run on a bare synthetic staff, not a cluttered real strip. Font
  swap and realistic strip context (label text, dynamics) must be tested **together**, not just
  font-in-isolation, before concluding font alone closes the gap — see step 1's Condition A/B split
  in the Colab guide.
- Label-bleed is inconclusive, not ruled out, per the bug-tracker.md correction log.

## Not yet decided / blocked

- Whether the base Camera-PrIMuS training run needs to finish first, or whether fine-tuning can
  start from the currently-deployed checkpoint directly — re-confirm with the user before step 2.
- Sourcing a genuinely new real-world test set (step 3) requires new photos/screenshots the user
  needs to supply; not something this repo's existing data covers.
