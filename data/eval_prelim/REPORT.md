# Preliminary results: camera-captured vs digital input (2026-09-28, v2)

**v2 test set: Non Nobis Domine pp.1-3 + Gaano Ko Ikaw Kamahal pp.1-9.** Each page has a digital PDF render
(300 dpi) and a phone photo of the printed copy, with author-verified GT. Both pieces are FROZEN in the Stage 1
mask split (`training/step3_mask_split.json`), so no pipeline threshold was tuned on them. 25 SATB systems,
100 staves, 1008 GT notes per condition.

- **Scope rule** (`inputs.OUT_OF_SCOPE_PAGES`): a page is scored only if every system on it is exactly S/A/T/B,
  because Stage 2 accepts or rejects whole pages.
  - Removed: Non Nobis p4 (Soprano Solo staff) and Handog p3-10 and p12 (divisi systems of 5-7 staves). All of
    these staves were already marked `excluded` in the GT.
- **Previous test set (v1):** Non Nobis pp.1-4 + Don't Stop Me Now pp.1-5 + Both Sides Now. It is kept in the
  `*_v1_allpages.*` files for disclosure; the set was changed after v1 results were seen.
- **Why v1 was dropped:** DSMN and BSN were seen during mask development, BSN has no note GT, and NN p4 is out
  of scope.

Files:
- `TEMPLATE_tables.md`: the thesis template filled in, pooled and per piece.
- `RESULTS_tables.md`: per-piece detail with CIs, clef/key/rhythm/note precision, the camera-only table for all
  5 pieces, and the pools.
- `base_stage2_failures.md`: the pages the original pipeline rejected (v1, all pages).
- `runs/results.json`: all the numbers as raw data.

## Filled template (pooled, Δ = Camera − Digital, pp)

| Model | Input | Staff detection (recall) | SER | Pitch accuracy |
|---|---|---|---|---|
| Base CRNN, original pipeline | Digital | 84.0% | 94.9% | 4.9% |
| | Camera | 56.0% | 98.0% | 4.3% |
| | Δ | −28.0 | +3.1 | −0.6 |
| Fine-tuned seed1, no classifier | Digital | 100.0% | 34.2% | 11.0% |
| | Camera | 100.0% | 43.3% | 18.1% |
| | Δ | 0.0 | +9.1 | +7.0 |
| Fine-tuned seed2, no classifier | Digital | 100.0% | 35.6% | 11.6% |
| | Camera | 100.0% | 44.1% | 22.3% |
| | Δ | 0.0 | +8.5 | +10.7 |
| Fine-tuned seed1 + clef/key classifier | Digital | 100.0% | 25.0% | 88.7% |
| | Camera | 100.0% | 33.8% | 83.3% |
| | Δ | 0.0 | +8.8 | −5.4 |
| Fine-tuned seed2 + clef/key classifier | Digital | 100.0% | 25.5% | 89.1% |
| | Camera | 100.0% | 34.8% | 83.4% |
| | Δ | 0.0 | +9.2 | −5.7 |

The 95% CIs (stave-level bootstrap) for the classifier model are:

| Condition | SER | Pitch accuracy |
|---|---|---|
| Camera | 30.4-38.4% | 79.8-86.6% |
| Digital | 22.5-28.4% | 86.3-91.4% |

## What the metrics mean

- **Pitch accuracy** is the SOW metric. GT notes and predicted notes are aligned by pitch only, and a GT note
  counts as correct if a predicted note with the same pitch is aligned to it.
  - **Duration is ignored**, so wrong timing does not lower it.
  - Wrong-pitch and missing notes do lower it, and staves lost at Stage 2 count as wrong.
- It **does not penalise extra (hallucinated) notes.** Read it together with **note precision**, the share of
  predicted notes that match a GT pitch:
  - Classifier model: 66-69% on both camera and digital.
  - So roughly 1 in 3 notes the model outputs is spurious or wrong-pitched, even when 83-89% of real notes are
    found.
  - Spot check, Gaano p2 system 1, seed1 + classifier, camera:

    | Strip | Real notes found at the right pitch | Notes predicted |
    |---|---|---|
    | Bass | 8/9 | 9 |
    | Soprano | 8/12 | 11 |
    | Tenor | 2/3 | 8 |

  - That is, pitches are mostly right where the notes are real, but the Tenor strip has 5 phantom notes.
- **SER** is agnostic-token SER (Levenshtein, slurs/ties excluded). It includes rhythm and symbol errors, which
  pitch accuracy ignores.
- **Staff detection** is the share of GT staves that Stage 2 delivered with the right (page, system, voice). It
  is **not mAP50**: there are no staff bounding-box annotations for these pages.

## Key findings

1. **Staff detection:** the updated Stage 1/2 finds every in-scope stave in both conditions (100/100). The
   original pipeline loses 28 pp on camera photos (84% → 56%) because Stage 2 rejects whole pages.
2. **Pitch:** with the clef/key classifier, pitch accuracy is 88.7-89.1% on digital and 83.3-83.4% on camera.
   Camera capture costs 5.4-5.7 pp, and the two seeds agree within 0.5 pp.
   - Without the classifier it is 11-22%, because the CRNN's own clef reading fails.
3. **SER:** camera capture adds about 9 pp for every fine-tuned configuration. The classifier lowers SER by
   about 9 pp in both conditions but doesn't shrink the camera gap, so that gap is in the note/rhythm tokens,
   not the header.
4. **No-classifier anomaly:** without the classifier, pitch accuracy is higher on camera than on digital. The
   numbers are small and driven by which clef the CRNN happens to read, so don't interpret it as a camera
   advantage.
5. **Base model:** its SER is about 95-98% in both conditions (most staves missing, the rest near-random; clef
   accuracy 0%, BUG-011), so its SER/pitch Δ says nothing about robustness. Its real camera weakness is staff
   detection.

## Caveats to state in the thesis

- Small sample: 2 pieces, 100 staves, 1008 notes per condition. The Δ values have no CI of their own; the
  per-condition CIs overlap only slightly for pitch (camera 79.8-86.6% vs digital 86.3-91.4%).
- The test set was chosen after v1 was seen. The reasons (frozen split, in-scope layout, verified GT, PDF
  available) are independent of the scores, but disclose it and keep v1 in an appendix.
- Camera-only results for the other pieces (Honneur, Handog in-scope pages, DSMN) are in `RESULTS_tables.md`.
  Honneur and Handog are in the mask TUNING split, and DSMN was seen during mask development. The CRNN,
  ClefKeyNet and YOLO never trained on any of these photos (`data/eval_fresh/PREREG.md`).
- The fine-tuned camera results reproduce the earlier `data/eval_fresh` run exactly: 0 differences across all
  metrics and CIs.

## Reproduce (from the repo root of the training tree)

```
python data/eval_prelim/run_base_original.py
python data/eval_prelim/run_finetuned.py
python data/eval_prelim/score_prelim.py
python data/eval_prelim/template_tables.py
```
