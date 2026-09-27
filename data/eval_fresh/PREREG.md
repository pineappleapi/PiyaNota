# Fresh-photo evaluation: pre-registration (written 2026-09-28, before any Stage 3 run on these photos)

Purpose: measure the pipeline as it now stands (training-tree Stage 1-3) on two unseen real phone-photo
pieces, with Stage 3 in two versions:

* **(a) as-is**: `stage3_transcription.py` unchanged. The CRNN reads clef and key; Tenor is lowered by voice.
* **(b) clef/key classifier**: `stage3_clefkey.py`. ClefKeyNet + `clef_voice_rules.resolve_clef` own the
  clef and octave, and a system-level confident-majority vote owns the key. CRNN clef tokens and opening
  key accidentals are replaced; the CRNN note/rest/barline tokens are untouched.

Nothing below may be changed after the first Stage 3 output exists. Any later deviation goes in
REPORT.md under "Deviations", with a reason.

## Frozen inputs (sha256)

Code: git HEAD `78c35d8` (branch `piya106/groundtruth-eval`); the stage files are clean at HEAD.

| File | sha256 |
|---|---|
| stage1_preprocessing.py | 831f2883ccffa30931b283f2576416bf6f264a4cd0bf29907712577880d8d11e |
| stage2_detection.py | 26c1c5857acbc64ab33ce79af8e1c1685968d86ebbd4a1f6a592a0f7491025b2 |
| stage3_transcription.py | e12b0a621bfedf10af15fcf9ed250a798ca54eabda3aba9cf8ee576918da7459 |
| stage3_clefkey.py (new, version (b)) | recorded by run_eval.py in `run_meta.json` at run time |
| clef_key_core.py (frozen) | ad507cd1a5d549a13105d2a1b60dcbcbf9dab89c2639fac769fb074a9a178532 |
| clef_voice_rules.py | c9752eb7a1470f60b60f0cb57ca3c2041cc00bb01804be79a2840841f4935d07 |
| ClefKeyNet `t4_full_seed20260926_runA/clef_key_classifier.pt` | e718d4479b1310369b64cfaf9a8f1ff433179543ffa9d1810b24c683de13fe10 |
| CRNN `finetuned_font_seed1.pt` | 1192a0d03718a47d2d11acb1590b7f1c4b41fb76f1ee2ab31246551a438e7fa9 |
| CRNN `finetuned_font_seed2.pt` | 70e39bf52ef4d49488547c83d00d6ba24b8152a8632aa3f6169ad29b29431696 |
| CRNN baseline `crnn_cameraprimus_transcription.pt` (reference only) | b1c9803cebb2ce83c6c132dd70c5219bb64989659fc46a7003d357f03596d47e |
| YOLO `staff_detector_files/weights/best.pt` | f55bb85176876d8af6eb5d02b56e22f65193e6bbc244f2e33f59ea6234018213 |
| GT Non Nobis `gt_source.txt` / `gt.json` | d163dc1c...1751763 / 556212b0...6bfce |
| GT Honneur `gt_source.txt` / `gt.json` | 80219bdc...1e66b22 / aba1c4eb...5d105397 |

Photos (TEST-only; never used for training, selection or thresholds): `D:/PiyaNota/data/piyanota_dataset/`
`non_nobis_domine_pg01-04.jpg` (dbab6dad, bbd3150a, f14a667a, 7f27c4ce) and `honneur_a_toi_pg01-03.jpg`
(ed248263, ac7eb209, 62281424).

The CRNN checkpoint hashes match `data/eval_dsmn/checkpoint_hashes.txt`. ClefKeyNet's `never_used` lists
`piyanota_dataset`. The real-val set (Dormi/Livin'/Flashlight) is spent and is not used here.

## Ground-truth status

* **Non Nobis Domine** (4 pages, 36 scored S/A/T/B strips, 275 notes). Hand-transcribed and **verified by
  the author** (user, 2026-09-28). The "diagnostic only" rule is lifted for this piece by user decision.
  The frozen `gt_source.txt` header still says "provisional / diagnostic only"; it is kept byte-identical
  so its hash holds, and the README records the lift. Page 4 has 5 staves per system (Soprano Solo +
  SATB); the 2 Solo strips are excluded from the GT.
* **Honneur a Toi** (3 pages, 28 strips, 540 notes). Agent-made, **not user-verified**: its numbers are
  diagnostic only and are reported separately, never pooled into a headline claim.

## Pipeline run (identical for (a) and (b) up to Stage 3)

* Stage 1: `preprocess_score_page(photo, keep_unmasked=True)` per page (the unmasked copy is only for
  ClefKeyNet crops; the CRNN strips come from the masked native strip source, as in production).
* Stage 2: `detect_staff_regions([(page.detect, page_no, page.strip_source)], yolo, manifest_path=...)` one
  page at a time, so a page that raises (e.g. Non Nobis p4, 5 staves per system: the count is not
  divisible by 4) fails alone. **A Stage 2 failure is a pipeline failure**: every GT strip on that page is
  scored as fully missed (all tokens deleted, all notes wrong) in the end-to-end numbers, and the
  detected-strip-only numbers are reported alongside.
* Stage 2 voice labels come from Stage 2's position rule, not from the GT. A strip is scored against the GT
  strip with the same (page, system, voice). A GT strip with no such strip is a miss; an extra strip is
  reported, not scored.
* Stage 3: `transcribe_strip(return_confidence=True)` once per strip and CRNN; the same tokens feed (a)
  `infer_pitch` and (b) `stage3_clefkey.infer_pitch_b`. Reproduction check (must pass before scoring):
  for every strip, (a) events == `process_strip(...)` events exactly.
* CPU only (`CUDA_VISIBLE_DEVICES=-1`) so runs are deterministic. The driver never reads the GT.

## Version (b) rules (fixed)

* Clef: `resolve_clef(voice, clef_probs, clef_threshold=0.3, g8vb_reliable=True)`. A strip with no
  classifier geometry gets the voice default + `review_needed`. The rule's `octave_shift` is the single
  octave owner; Stage 3's voice-based Tenor lowering is switched off for (b) only.
* Key (choral-conductor option (iii), 2026-09-28): per system, only readings with max key probability
  >= `key_threshold` (0.765) vote. The CRNN never votes. A strict majority of the confident votes sets the
  key for all four strips; confident dissenters are overridden and flagged. With no majority, the previous
  system's key (piece order) is carried and all four strips are flagged; for the first system with no
  majority, the argmax of the summed probabilities is used, flagged. A confident majority always beats
  the carried key.
* Header: all CRNN `clef.*` tokens are dropped, plus every accidental before the first non-clef/non-
  accidental token; the decided clef + key-signature tokens (printed order) are prepended.
* A CRNN mid-strip key change is kept but flags the strip `review_needed`.
* Known limit: a real accidental on the first note right after the key signature is dropped with it.

## Metrics (per CRNN x version x piece; also per voice)

1. **Token SER** (agnostic tokens; Levenshtein; `<OOV>` GT tokens are wildcards; slur / `<TIEX>` tokens
   are excluded from both sides, as in the DSMN scorer). The GT header includes the clef and key, so in
   (b) the header is scored on the injected tokens.
2. **Pitch accuracy (SOW)**: GT notes aligned to predicted events (edit alignment on kind + pitch); correct
   = same sounding MIDI pitch. Denominator = all GT notes (missed notes count as wrong).
3. **Strict note accuracy**: pitch and duration both right. **Rhythm accuracy**: duration right (notes and
   rests).
4. **Per-symbol table**: for each GT symbol category (e.g. "dotted half note", "quarter rest", "eighth note
   (beamed)"): symbol correct X/Y (kind + duration) and symbol + pitch correct X/Y; and per agnostic token
   class recall / precision.
5. **Confusion matrices** (CSV + PNG): duration/symbol class (with missed / extra rows); clef (GT G / G8vb
   / F vs effective predicted clef, where (a) = the CRNN's first clef token with Tenor lowering applied);
   key (GT vs predicted; (a) parsed from Stage 3's "opening key sig" log line).
6. **Clef accuracy, key accuracy, silent-wrong clef/octave rate** (strip whose median pitch offset over
   aligned notes is a non-zero multiple of 12 and which is not flagged `review_needed`), **double-octave
   strips** (offset +/-24), **review_needed rate** per staff (flagged if clef or key flagged).
7. Report-only diagnostics (choral conductor): range check (Tenor C3-A4, Bass E2-E4 sounding), cross-system
   octave consistency, `tie_unresolved`.
8. Stage 2 coverage (strips found vs expected per page), note-count ratio, 95% bootstrap CIs over strips
   (2000 resamples, seed 0). **CRNN seeds are reported as a range, never one seed alone.**
9. Oracle C (diagnostic ceiling): GT clef + key through the (b) path, computed in the scorer.

## Gate (per CRNN seed; both fine-tuned seeds must pass; decided on Non Nobis only)

(b) vs (a):
1. silent-wrong clef/octave rate per staff: (b) <= (a);
2. 0 double-octave staves in (b);
3. SOW pitch accuracy: (b) - (a) >= 20 points;
4. `review_needed` <= 25% of staves in (b) (choral-conductor: acceptable for this run as an upper bound;
   product target ~10%, at most one confirmation per voice per piece). Flag rate is always reported next to
   the silent-wrong rate.

Honneur is reported with the same metrics as a secondary, agent-labelled check. The baseline CRNN is a
reference row only and is not gated. This is one small real-photo test (2 pieces, 64 strips). A pass or
fail says "on these photos", not "in general"; no improvement claim beyond that.

## Amendment 1 (2026-09-28, written before any pipeline run on these photos)

At the user's request, two more pieces are added: **Gaano Ko Ikaw Kamahal** (pg01-09) and **Handog** (pg01-14),
from `D:\PiyaNota\data\piyanota_dataset\`. Their GT was made by the agent and frozen before the run. The user
explicitly asked for the test to proceed without checking it.

- GT hashes (sha256 of `gt/<piece>/gt_source.txt`):
  - gaano_ko_ikaw_kamahal `45077a2086b815452d131e12a03f7de9f3e5be13bbbb0a4388d468fafbd41fe1`
  - handog `1c793588af5dd4f07ccd5c5c5f682a7610a1e9361fb13041477bfcc403077b33`
- Status: agent-made, NOT user-verified, **diagnostic only** (same as Honneur). Neither piece is gated. **The gate
  stays decided on Non Nobis only.** Gate booleans are still computed for every piece, but are marked "not gated".
- Handog divisi: 10 of its 23 systems have 5-7 staves (S/S/A/T/B, S/A/A/T/B, ...). Stage 2 assumes 4 staves per
  system, so these are unsupported layouts. Their staves are listed as EXCLUDED in the GT: they are counted in
  expected staves (Stage 2 coverage) but carry no GT content and are not scored. A page whose staff count is not a
  multiple of 4 will likely make Stage 2 raise. Any 4-staff systems on such a page (p3, p10, p12) then count as
  missed, as with Honneur page 1.
- Leakage disclosure: `handog` (like `honneur_a_toi`) is in the Stage 1 mask TUNING split
  (`training/step3_mask_split.json`). `gaano_ko_ikaw_kamahal` is FROZEN. The CRNN, ClefKeyNet and YOLO never
  trained on any piyanota_dataset photo. The Stage 1 mask thresholds did see Handog and Honneur.
- Same code, checkpoints, thresholds and scorer as the main run. The only changes are the piece lists and table
  labels, plus a note precision/F1 column in the tables. Nothing is tuned on these results.
