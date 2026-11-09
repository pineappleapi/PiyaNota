# Next session: thesis Chapter 5 (Results) from the C2 real-set evaluation

Written 2026-11-08 at the end of the C2 prediction, scoring and analysis session. Branch `piya106/stroke-calibration` (local, not pushed). Everything the chapter needs is committed; nothing below depends on files outside git except the raw photos and the live prediction folder, and the predictions are also stored here compressed.

## Task for the next session

Edit the thesis paper and write the Chapter 5 results section from the C2 real-set evaluation (10 test pieces, PDF and camera versions, two checkpoints). The user has asked for this; no format has been chosen yet, so ask which template or chapter outline to follow before writing.

## Read these first, in this order

1. `docs/decisions/piya-106-c2-real-results.md` : main results report. Pitch recall and token SER per set, mode and header, seed 1 / seed 2; separation of header filter and ClefKeyNet; camera rebuild mismatch; Kay_Ganda bar 21; confidence; the divisi limitation; disclosures. This is the source of truth for every headline number.
2. `docs/decisions/piya-106-c2-symbol-breakdown.md` : accuracy per symbol type, pooled over all pieces.
3. `docs/decisions/piya-106-c2-symbol-confusion.md` : what each symbol is mistaken for, note-only matrices, and one-vs-rest TP/FN/FP/TN per symbol.
4. `docs/decisions/piya-106-divisi-a9-prereg.md` : the pre-registration (section 25.2 / 25.3), Amendments 1 and 2. Describes what was fixed before the run.
5. `docs/decisions/piya-106-c2-real-photo-plan.md` and `docs/decisions/evidence_c2_cut/` : how the test pieces and strips were chosen and cut.

## Evidence stored in git (`docs/decisions/evidence_c2_real/`)

| Folder | Content |
|---|---|
| `predictions/` | The 12 prediction files, gzipped: seed 1 / seed 2 x PDF / camera x raw CRNN / header filter / ClefKeyNet. Each holds per-strip predicted tokens and confidences. |
| `scores/` | The scorer outputs (`score_*`, `conf_*`, `controls_*`, `camera_rebuild_mismatch_strips.json`) and the rerun check file (gzipped). The `.txt` files are the one-line summaries. |
| `confusion_csv/` | Full type-vs-type confusion matrices, one CSV per set and seed. |
| `SHA256.txt` | sha256 of every original file (before gzip) with its original path. |

To rerun the per-symbol scripts, gunzip the prediction files into `D:/PiyaNota/data/c2_real_preds/` (the scripts read that folder through `PRED_DIR` in `training/phase2/symbol_breakdown.py`) and run, from `training/phase2/`:

```
python symbol_breakdown.py --out <file.md>
python symbol_confusion.py --out <file.md> --csv-dir <dir>
python symbol_binary_matrix.py --out <file.md>
```

The original photos and frozen strips are not in git: `D:/PiyaNota/data/piyanota_dataset/10piece_test_set/` (ground truth in `_a7_gt/labels/`). The prediction runner is `training/phase2/predict_real_set.py` and the scorer is `training/phase2/real_set_scorer.py`; the runner hash history is in section "Disclosures" of the results report.

## Headline numbers (all from the results report; label-conditioned strip scores, seed 1 / seed 2)

- Arm 1 pitch recall, raw CRNN, own header: PDF 96.7 / 96.7, camera 96.2 / 95.8. Arm 1 token SER: PDF 4.6 / 4.5, camera 5.1 / 5.1. Arm 3 (header stripped, bar-masked): pitch 96.4 / 96.6 PDF and 96.1 / 95.6 camera; SER 5.1 / 5.0 PDF and 5.7 / 5.6 camera.
- Pitch control floors (labels only): constant 8.7%, shuffled 18.7%, every step shifted 21.4% (Arm 1).
- ClefKeyNet header lowers own-header pitch by 0.4 to 0.7 pp against the CRNN's own header; most of the loss is one piece (Kay_Ganda). The ClefKeyNet gate remains failed (BUG-021).
- Per-symbol accuracy (this session): clef 100%, barline 99.7 to 99.9%, accidentals 98.8 to 99.3%, notes about 96%, slurs 88.9 to 92.1% (almost all deletions), eighth rests 89.1% (all deletions), dots about 94%.
- Independent two-voice divisi (`layer.split`, `.l2` notes): 0% correct in the token tables, 34 to 98% pitch recall on layer strips by piece. It is an accepted project limitation (user decision 2026-11-08), explains Ama_Namin's 78.7% pooled pitch (its ordinary strips score 99.4%), and is written up in the results report.

## Rules the chapter must respect

- `CLAUDE.md` behavioral policy: hand-authored ground truth is diagnostic only. Never present numbers measured against it as accuracy evidence. All the numbers above use the hand-authored ground truth for the test pieces, so the chapter must label them as label-conditioned strip scores, say how the ground truth was made, and not call them the SOW end-to-end result. Ask the user how the thesis should frame them before writing any "accuracy" sentence.
- Do not compare C2 with A7 or claim improvement (the PREREG sets no pass or fail line). Do not blend PDF and camera. Report seeds as a range, never one seed. The SOW goals (SER 15 percent, pitch 85 percent) are not applied to these scores.
- Fermatas are out of scope (ruling 2026-10-14); the per-symbol tables show them for information only.
- All camera numbers are conditional on the frozen strip cut: 234 of 912 camera strips rebuild differently from the frozen cut (cause only partly found).

## Known gaps and open items

- The camera tables cover 821 of 825 labelled strips: 4 strips have no prediction entry and are not counted anywhere (PDF is complete).
- `symbol_breakdown.py` counts the 38 beamed divisi-layer tokens in its `note.beamed*` row (the beamed rule runs before the layer rule), so its `note.*.l2` row shows 172 rather than 210. The confusion document separates them correctly. The percentages in the breakdown document are otherwise unaffected.
- In the results report, the disclosure paragraph still says Amendments 1 and 2 are "uncommitted until the user reviews them". They were committed in `5d63c29`; the sentence is stale and should be corrected if the report is edited.
- The overall token accuracy in the per-symbol document is not the same computation as the Arm 1 SER, so quote them separately.
- The `parts/` folder in the live prediction directory is not copied; it only holds the per-piece parts of three merged files.
- Not done and not requested: flagging layer strips `review_needed`; a per-piece meter-token table; paired intervals between modes.

## Commits from this session

`5d63c29` results report, PREREG Amendments 1 and 2, runner tolerance and mismatch flag; `c190412` divisi limitation recorded; `61fb999` per-symbol accuracy; `e963c4e` confusion matrices and scripts; the commit that adds this note and `evidence_c2_real/` is the latest on the branch (`git log --oneline -3`).
