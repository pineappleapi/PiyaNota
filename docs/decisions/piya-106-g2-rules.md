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

### Amendment 2 (2026-10-14): G2 result and full section 5 report

Phase 2 JSONs (scored 2026-10-12, after Amendment 1): `D:\PiyaNota\datasets\phase2_eval_dev\phase2_run1` (grey e1c/e1b/
none), `phase2_noaug`, `nofermata_*`, `canary_check`. The section 5 items that eval_dev.py does not keep come from
`training/phase2/eval_dev_detail.py` (new: imports eval_dev unchanged and re-aggregates the same score_eval rows).
`training/phase2/eval_dev_oov.py` (new) counts predicted tokens absorbed by GT `<OOV>` wildcard spans (BUG-049/050).
Outputs: `detail_baseline/`, `detail_phase2/`, `oov/{baseline,phase2}/`. **Parity:** token SER and pitch match the eval_dev JSONs exactly for
all 8 seed x pool rows.

**Verdict: G2 = PASS for both seeds (not MARGINAL).** ml-cv-lead reviewed it on 2026-10-14 and agrees.

| Rule | p2s1-p2s2 camera | p2s1-p2s2 digital | Baseline (deployed seeds) | Result |
|---|---|---|---|---|
| 4a grey/e1c SER | 8.15-8.44% (393-407/4823) | 8.00-8.20% (162-166/2025) | 16.26-16.55 / 15.90-16.64% | pass (thresholds 13.26 / 12.90; >1 pp clear) |
| 4b per-piece deltas | 5/5 < 0 (-6.05 to -9.87 pp) | 2/2 < 0 (-4.54 to -9.22 pp) | mean of the 2 seeds per piece | pass |
| 4c grey/e1b SER | 8.07-8.38% | 8.00-8.20% | 15.61-16.17 / 14.86-15.70% | pass |
| 4c grey/none SER | 8.52-8.92% | 9.04-9.28% | 20.38-21.29 / 24.64-25.09% | pass |
| 4d pitch (SOW) | 95.30-95.62% | 96.33-96.43% | 88.71-89.93 / 90.67-90.97% | pass (floors 87.71 / 89.67) |
| 4e canary | no hard-cap breach in any epoch | | | pass |

Per-piece grey/e1c deltas (Phase 2 minus the mean of the 2 baseline seeds, pp, seed1 / seed2): camera
dont_stop_me_now -9.87/-9.30, gaano -8.18/-7.85, handog -7.67/-6.74, honneur -7.16/-8.24, non_nobis -7.26/-6.05;
digital gaano -9.03/-9.22, non_nobis -5.95/-4.54.

**Canary (section 3, report-only). Deviation from section 3:** section 3 said to rerun `e6_grey.py`. What ran
instead was `canary_check.py` (commit 0d732ce, written after Amendment 1). It scores the deployed and Phase 2 models
with one metric, the trainer's own, so the comparison is like for like; e6_grey's "E6 raw" numbers come from a
different metric. canary_check.py uses the trainer's mean per-sample SER on the 399 pinned
stems, the same metric for both models. Phase 2: clean 2.70-2.74%, distorted 4.32-4.50%. Deployed seeds: clean
4.92-7.85%, distorted 8.65-13.11%. Phase 2 is better, so the 1 pp MARGINAL rule does not trigger. These numbers are
not comparable to the "E6 raw" 2.59-2.69 / 5.73-5.83% in section 3. The outcome does not depend on the deviation,
because Phase 2 is better on both clean and distorted under this one consistent metric.

**Section 5 report (grey/e1c, both seeds as a range; baseline in brackets):**
- **Note precision is reported as a range, because GT `<OOV>` spans hide part of the output (BUG-050).** In each
  camera pool the scorer never sees 569-609 predicted note tokens: 591 GT `<OOV>` tokens each absorb up to 2
  predicted tokens at zero cost. Digital: 212 `<OOV>`, 242-254 notes. Some of these are real notes the GT could not
  encode, and some are hallucinations, so neither bound alone is right:
  - aligned only (absorbed notes left out; upper bound): camera 91.4-91.7% [82.3-83.5], digital 89.0-89.4%
    [84.8-85.8];
  - all-in (absorbed notes counted as wrong; lower bound): camera 74.3% [67.2-68.5], digital 72.1-72.3% [69.2-70.1].
  Phase 2 is better under both bounds. Event-level `headline.note_precision` (camera 75.4-75.5% [70.3-72.0],
  digital 73.2-73.3% [69.0-69.4]; F1 camera 84.2-84.3% [78.4-79.9], digital 83.2-83.3% [78.4-78.7]) sits near the
  lower bound for the same reason.
  Hallucinated notes inside `<OOV>` spans, the BUG-011 failure, are not measurable on this GT.
- Per-class recall (exact, pooled):
  - whole note: camera 84.9% both seeds, n=86 [72.1-74.4]; digital 95.7-97.9%, n=47 [93.6].
  - half rest: camera 91.7-100%, n=12 [83.3-91.7]; digital 100%, n=9 [77.8-100]. Half-rest precision camera
    100% [47.6-50.0]: the baseline's spurious half rests are gone.
  - fermata: the dev GT has none, so recall is undefined (see insertions).
  - barline: camera 94.1-94.3%, n=882 [91.8-92.4]; digital 98.3-98.9%, n=460 [98.7]. The dev GT has no separate
    final-barline class, so it is scored as part of `barline`. Synthetic val final-barline recall is 1.0 for both
    seeds (n=383, `metrics.json` watch_recall).
- Fermata insertions (raw predicted/GT): camera 80-83/0 [39-41], digital 26-28/0 [30-38]. **BUG-049** (`oov/` JSONs): fermatas in scored
  positions / inside GT `<OOV>` wildcard spans, which SER never scores: camera 34-36 / 46-47 [33-36 / 5-6], digital
  13-16 / 12-13 [27-35 / 3]. So scored fermata insertions are flat, but Phase 2 writes fermatas where
  the GT marks out-of-vocabulary symbols. All of them reach Stage 4/5. Fermata-excluded SER (eval_dev_nofermata.py;
  parity without the flag reproduces phase2_run1): camera 7.28-7.44% [15.55-15.90], digital 7.01-7.31% [14.67-15.16].
- Val SER (synthetic, tune-held-out, epoch 6): 0.259-0.263%. By font: Bravura 0.21%, Gootville 0.23-0.25%, Leipzig
  0.31-0.33%, Leland 0.26-0.29%, Petaluma 0.24-0.30%. Interline tertile 0/1/2: 0.32-0.34 / 0.22 / 0.23-0.26%.
  line_mult tertile 0/1/2: 0.29-0.30 / 0.25 / 0.22-0.24%. The about 30x gap to dev SER is the remaining
  synthetic-to-real gap.
- Diagnostic only (section 6, not a control): seed1_noaug epoch 1, camera 9.56%, digital 8.94%, pitch 94.32 /
  94.94%.

**Caveats (ml-cv-lead, 2026-10-14):**
1. The absolute ~8% is optimistic. Grey vs binary, the e1c rule and the contrast work were all chosen on these 5
   pieces. The delta against baseline (same pipeline, same GT) is the safer evidence.
2. GT for gaano, honneur and handog is agent-made and not user-verified. The digital pool is 2 of the same 5 pieces,
   so the two pools are not independent evidence.
3. No leakage found: no dev piece is a Bach chorale. eval_dev.py is unchanged since b5a213d.
4. Confident-wrong output (BUG-011, plan step 7) is not addressed by this result.
5. G2 gates GPU spend only. AC1 is judged at Phase 4 held-out.
