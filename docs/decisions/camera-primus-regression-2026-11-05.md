# Camera-PrIMuS regression gate, branch feature/module3-backend (2026-11-05)

Verdict: **PASS.** Result is dev/synthetic-domain only (CPM). Says nothing about real screenshots (BUG-011).

## What changed since the recorded baseline
Stage 3 meter-apply (APPLY_MID_METER_CHANGE, commit 2672f4d, the only stage3 commit since merge-base 29e5375), Stage 4 failed_voices / tie-bar repair, timing x-mapping. Stage 4 and timing are downstream of pitch and do not touch this metric. Stage 3 meter-apply affects time signature, not pitch.

## Method (CPU only, CUDA_VISIBLE_DEVICES=-1; GPU numbers untrusted, BUG-013)
- Scorer: `.superpowers/sdd/2026-11-05-v2-checks/cpm_regress.py`. A rebuild: the original `end_to_end_pitch_check.py` was never committed. Sample = sorted Corpus dirs with png+jpg+agnostic+semantic, `random.Random(42).sample(.., 500)`, 6960 notes. Pitch from `infer_pitch()` note events vs `.semantic`, edit-distance alignment. Checkpoint: `music_symbol_detection/crnn_cameraprimus_transcription.pt` (base).
- Corpus: `datasets/CameraPriMus/CameraPrIMuS - Copy/Corpus` (distorted = precomputed `_distorted.jpg`).
- Commands: `CUDA_VISIBLE_DEVICES=-1 python cpm_regress.py {gt|clean|distorted} <weights>`; `CPM_CODE=<dir>` selects which code tree to import.

## Tolerance (set before running)
Expected: exact count match vs merge-base code (CRNN output unchanged, CPU deterministic, post-CRNN edits). Binomial 95% CI on 6960 notes is +/-0.31pp at 98%, +/-0.80pp at 87% (resampling bound only; this is a paired comparison on identical samples so the real band is far tighter). Pass: clean within 0.10pp, distorted within 0.25pp and >= 85%, versus recorded baseline; any difference vs merge-base is investigated.

## Results (match / sub / ins / del, acc %)
| Code | GT tokens | CRNN clean | CRNN distorted |
|---|---|---|---|
| Old root checkout (pre-BUG-024) | 6888/64/8/8 98.966 | 6829/114/12/17 **98.118** | 6054/655/41/251 **86.983** |
| merge-base 29e5375 (main) | 6923/29/8/8 99.468 | 6825/118/12/17 98.060 | 6038/671/41/251 86.753 |
| This branch (worktree) | 6923/29/8/8 99.468 | 6825/118/12/17 98.060 | 6038/671/41/251 86.753 |

- Branch vs merge-base: **identical counts in all three modes** (delta 0; distorted per-sample results also identical).
- Branch vs CLAUDE.md baseline: clean -0.058pp (-4 notes), distorted -0.230pp (-16 notes), both inside tolerance; distorted 86.75% >= 85% floor.
- The old checkout reproduces 98.118 / 86.983 exactly, which validates the rebuilt scorer. The small drop vs the baseline comes from BUG-024 (accidental rules, already in main, merged 2026-09-29), which logged clean -0.06pp and distorted -0.26pp on the base checkpoint, matching what is seen here. GT-token accuracy rose 98.966 -> 99.468 from the same change.

## Caveats
- Base checkpoint only; seed1/seed2 fine-tuned checkpoints not run.
- Synthetic CPM draw, dev data; not evidence about real-photo accuracy. Distorted margin over 85% floor is 1.75pp.
- Distorted drop is within 0.02pp of the 0.25 limit vs the recorded baseline, but is fully accounted for by BUG-024 and is 0 vs main.
