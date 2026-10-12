# PIYA-106 Phase 2: G2 scoring rules (pre-registered)

Written 2026-10-12, after the Kaggle run finished and the training logs were read,
and before any eval_dev.py output for a Phase 2 checkpoint exists.
Companion to Amendment 4 in piya-106-ser-15-plan.md; this file only fixes the
ambiguities left there. Dev data, diagnostic only: AC1 is judged at Phase 4.

## 1. What is scored
- Kernel commit b5a213d (pin commit 2f63b63 changes only phase2_kernel.py). Manifest sha256 78165b43...
- G2 checkpoints: seed1/phase2_seed1.pt and seed2/phase2_seed2.pt (both epoch 6 of 6,
  selected on tune-held-out synthetic val SER, per Amendment 4 item 5).
- Per-epoch checkpoints are never scored for selection.
- Diagnostic only: seed1_noaug/phase2_seed1.pt (epoch 1 of 4 selected).
- Scorer: training/phase2/eval_dev.py, grey strips. Headers: e1c (the G2 rule), e1b and none (reported).
  Camera pool 5 pieces, digital pool 2 pieces, never pooled with each other.

## 2. Baseline and thresholds
- Baseline (deployed finetuned_font_seed1/2, grey, e1c): camera 16.26-16.55%, digital 15.90-16.64%.
- The baseline models are different training runs, so there is no seed pairing. Each Phase 2 seed is
  compared with the lowest baseline value.
- A Phase 2 seed passes a pool when pooled token SER is: camera <= 13.26%, digital <= 12.90%.
- The baseline for grey/none has not been recorded. Run it for the deployed seeds first.

## 3. Canary (CPM, 399 stems)
- Source: train_phase2.py. Hard cap = CANARY_HARD_CAP_MULTIPLIER (3.0) x the mean per-sample base SER,
  measured on the --init checkpoint at run start, clean and distorted separately. Breach stops the run
  and the epoch cannot become best. Soft floor = 95th percentile of 2,000 bootstrap means of the base
  SER; breach is a label only (GATE_MODE soft_diagnostic_hard_cap_v1).
- Values from run_info.json: seed1 [paste], seed2 [paste]. Base canary (log): clean 0.0501, distorted 0.2087;
  hard caps about 0.1502 / 0.6261.
- Canary stems are pinned by sha256 (dbe119c9...) and excluded from replay.
- Result: no epoch of any run breached the hard cap. seed1 and seed2: status OK in all 6 epochs.
  Selected epoch 6 canary: seed1 0.0270/0.0432, seed2 0.0274/0.0450. noaug: soft floor breached
  epochs 2-4 (max 0.082/0.1105).
- The hard cap is loose (0.626 distorted) relative to the deployed seeds' canary
  (2.59-2.69% / 5.73-5.83%, E6 raw). Report-only: rerun e6_grey.py on the G2 checkpoints. If either canary is
  more than 1 pp worse than the deployed seeds, the result is MARGINAL.

## 4. Decision rule
G2 = PASS only if every item holds for BOTH seeds:
a. Camera and digital pooled SER meet the section 2 thresholds (grey/e1c).
b. Per-piece paired deltas: Phase 2 SER minus baseline SER (mean of the two baseline seeds, same piece)
   is below zero in >= 4 of 5 camera pieces and in 2 of 2 digital pieces.
c. grey/e1b and grey/none pooled SER are not worse than baseline in either pool.
d. Pitch accuracy >= 85% and not more than 1 pp below the lowest baseline pitch
   (camera >= 87.71%, digital >= 89.67%).
e. No canary hard-cap breach (section 3).
- MARGINAL: a and e hold, but a point estimate is within 1 pp of its threshold, or b fails.
  ml-cv-lead review before any further GPU is spent.
- FAIL: anything else. Stop and diagnose with ml-cv-lead (plan, Phase 2 step 1).
- Bootstrap is descriptive, not a gate. n = 5 and 2 pieces cannot support a CI. Report:
  per-piece paired deltas, plus a supplementary 10,000-draw bootstrap over (page, system) units,
  RNG seed 0, labelled optimistic because it ignores piece-to-piece variance.

## 5. Reporting (nothing may be omitted)
- Both seeds as a range, never the better seed. Camera and digital never pooled.
- e1c, e1b and none side by side.
- Fermata insertions (predicted/GT) per pool. Baseline: camera 39-41, digital 30-38.
- Per-class recall for whole notes, half rests (report n), fermatas, final barlines.
- Val SER by font and by line_mult/interline tertile (from metrics.json).
- Pitch accuracy and note precision.

## 6. Attribution
- seed1_noaug removes --augment-synth only; CPM replay is augmented in every run. It diverged
  (val SER 0.80% -> 6.07% at epoch 2, soft floor breached epochs 2-4, early stop at epoch 4, selected
  epoch 1). The LR schedule is not the cause. It is not a valid control.
- A G2 result is attributed to the whole Phase 2 recipe. No claim is made that synthetic-strip
  augmentation helped or did not help.

  ### Amendment 1 (2026-10-12), recorded before any Phase 2 checkpoint was scored
Written after the baseline rerun and before eval_dev.py was run on phase2_seed1.pt / phase2_seed2.pt.

1. **Baseline parity reproduced.** Deployed finetuned_font_seed1/2, grey strips, committed code, system Python,
   `--out D:\PiyaNota\datasets\phase2_eval_dev\baseline`. Rows match the recorded runbook values:
   - grey/e1c: camera 16.26-16.55%, digital 15.90-16.64% (errors 784-798/4823 and 322-337/2025; pitch camera
     88.71-89.93%, digital 90.67-90.97%; fermata pred/gt camera 39-41/0, digital 30-38/0).
   - grey/e1b: camera 15.61-16.17%, digital 14.86-15.70% (753-780/4823 camera errors).
2. **grey/none baseline recorded (new).** Camera 20.38-21.29% (983-1027/4823), digital 24.64-25.09% (499-508/2025);
   pitch camera 88.67-90.01%, digital 90.77%. Section 4c compares Phase 2 grey/none against this.
3. **Supplementary bootstrap dropped.** eval_dev.py stores per-piece, not per-strip, results, and the pools have
   5 and 2 pieces. Rules 4a-4e are unchanged; the per-piece paired deltas in 4b are computed from the JSONs.
4. **Output folders.** Baseline JSONs: D:\PiyaNota\datasets\phase2_eval_dev\baseline. Phase 2 will be written to
   .../phase2_run1 (p2s1, p2s2) and .../phase2_noaug (diagnostic only), so no JSON is overwritten.
5. **Section 6 wording.** seed1_noaug removes `--augment-synth` only; CPM replay is augmented in every run.