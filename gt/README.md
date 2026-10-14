# gt/ - hand-made ground truth

Every ground truth in this folder was hand-made by a single annotator (an agent). Per CLAUDE.md it is **diagnostic only**:
never present a result measured against it as accuracy evidence.
**Exception: the five eval_prelim dev pieces** (`non_nobis_domine/`, `honneur_a_toi/`, `gaano_ko_ikaw_kamahal/`,
`handog/`, `dont_stop_me_now/strips_v2/`) were verified by the project owner (user). Non Nobis was verified on
2026-09-28. The user confirmed on 2026-10-14 that the other four were verified too, matching `GT_STATUS` in
`data/eval_prelim/score_prelim.py` (BUG-051). Report them as "hand-transcribed and verified by the author". Every
other folder here is still agent-made, not user-verified, and diagnostic only.
The `piyanota_dataset` photos it describes are TEST-only: never use them for training, model selection or threshold
tuning. The five dev pieces above are dev data (tuned on), not held-out test data.

Consolidated here on 2026-09-28. Previously the ground truth was spread across `ground_truth/` and several `data/` subfolders.
The `crops/` subfolders are viewing aids that can be regenerated from the photos, so they are gitignored.

| Folder | What | Frozen hash | Old location |
|---|---|---|---|
| `non_nobis_domine/` | Non Nobis Domine pg01-04: 36 scored S/A/T/B strips + 2 excluded Soprano Solo strips (page 4 has 5 staves per system). Verified by the user (2026-09-28). This is the fresh test set for the clef-rule + fine-tuned-CRNN eval (`data/eval_fresh/`). See `completion_notes.md` | `gt_source.sha256` (d163dc1c...) | new |
| `honneur_a_toi/` | Honneur a Toi pg01-03, 28 strips. Verified by the user (confirmed 2026-10-14) | `gt_source.sha256` (80219bdc...) | `data/eval_honneur/gt/` |
| `gaano_ko_ikaw_kamahal/` | Gaano Ko Ikaw Kamahal pg01-09, 72 strips. Agent-made; verified by the user (confirmed 2026-10-14). Stage 1 mask split: FROZEN | `gt_source.sha256` (45077a20...) | new |
| `handog/` | Handog pg01-14: 52 scored strips (13 four-staff systems) + 57 excluded divisi staves (10 systems of 5-7 staves). Agent-made; verified by the user (confirmed 2026-10-14); weakest GT (195 `?`, 357 OOV chords). Stage 1 mask split: TUNING | `gt_source.sha256` (1c793588...) | new |
| `dont_stop_me_now/strips_v2/` | Don't Stop Me Now, 60 strips (tokens + events, `build_gt.py`). Verified by the user (confirmed 2026-10-14) | re-frozen 72edc5ca... | `data/eval_dsmn/gt/` |
| `dont_stop_me_now/events_v1/` | Earlier DSMN event-level GT (`ground_truth/build_ground_truth.py` output; `ground_truth/test_reconstruction.py` reads it) | - | `ground_truth/dont_stop_me_now/` |
| `clef_key_labels/` | ClefKeyNet real-val labels: Dormi + Livin' (`labels.json`), Flashlight (`labels_flashlight.json`). **SPENT**: check-only, never tune on it | `*.sha256` | `data/val_clefkey/` |
| `flashlight_clef_crops/` | Flashlight clef crops only (gitignored images) | - | `data/eval_flashlight/gt/` |
| `both_sides_now/` | Both Sides Now staff-position GT (Stage 1/2 staff counts) | - | `data/test_bothSidesNow/staff_ground_truth.json` |

Code paths updated in the move:
- `training/eval_clef_key_realval.py` (`LABEL_DIR`)
- `ground_truth/test_reconstruction.py` (`GT_DIR`)
- the per-folder crop scripts
- `data/eval_dsmn/xcheck_gt.py`

Older decision docs and reports still name the old locations. They are historical records, so use the table above to find the new place.
