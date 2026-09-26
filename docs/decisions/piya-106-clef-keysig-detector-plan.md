# PIYA-106 - Clef and key-signature detector: YOLO or not, Stage 3 integration, validation, CRNN retraining (2026-09-26)

Author: ml-cv-lead (advisory). Status: **proposal, not implemented in the pipeline, nothing committed.**
Companion notebook: `training/piyanota-clef-keysig-kaggle.ipynb` (Kaggle, GPU T4).
Builds on `piya-106-accuracy-diagnosis-and-reference-comparison.md` (A1, A2, A6) and
`piya-106-reference-repos-preprocessing-training-review.md` (P1, P2, P4, P6).

## How to read this note

- User decisions this plan is built on (2026-09-26): C clefs are out of scope. Soprano and Alto use treble.
  Tenor uses treble, treble-8vb or bass. Bass uses bass. The SOW SER is agnostic-token-level.
- Every accuracy number that could come out of this plan belongs to one of three kinds:
  - "DS2/synthetic held-out";
  - "real-capture validation";
  - "test photos".
  They are never blended. Only the last kind is PiyaNota accuracy, and it is measured once, at the end.
- Test-only data is `piyanota_dataset` (including Flashlight), DSMN and Both Sides Now. None of it is used for
  training, checkpoint selection, calibration or thresholds anywhere in this plan.
- CRNN checkpoint facts quoted here come from the checkpoint metadata of the 2026-09-23 two-seed run, which
  is authoritative:
  - seed 1: epoch 2, `loo_font_ser` 0.0926;
  - seed 2: epoch 2, `loo_font_ser` 0.0562.

  Report them as the range **0.056-0.093 leave-one-font-out SER**, never one seed. `font_val_ser` is not
  quoted because it has a confirmed stem-overlap leak.

## Headline

1. **Do not use YOLO for this. Use a small two-head crop classifier (clef + signed key count) on the start of
   each staff that Stage 1/2 already found.** Decode-time masking of the CRNN's clef logits is a cheap
   complement, not a replacement. It cannot fix a model whose features are confidently wrong, and it
   does nothing for the key signature.
2. **The classifier input is binarised.** It is Stage 1's native adaptive-threshold strip source taken
   before the non-staff-ink mask, cut in staff-space units to a fixed 96x128. Training images go through the
   same threshold step after camera-style damage. The input size is fixed, so there is no padding and no
   true-length issue.
3. **The clef must come from the image, not from staff position.** Flashlight (a test photo) has
   Soloist / Soprano / Alto / Tenor staves with no Bass. Stage 2's positional `VOICE_MAP` therefore labels the
   Tenor staff "Bass", and a voice-prior clef would force a bass clef onto a treble-8vb staff.
   **Question for the user: is this layout in scope?** (see section 7).
4. **The CRNN still needs retraining for SER.** Fixing the header (clef + key) changes at most 1 + |key| tokens
   per strip, a few percent of token SER. The 44-48% real-strip token SER (DSMN diagnostic, 23 strips) sits
   mostly in the note body. Ranked data plan in section 6.

## 1. YOLO vs crop classifier vs decode-time masking

| | YOLOv8 detector (DS2 clef/key classes) | Crop classifier on staff start (recommended) | Decode-time masking of CRNN clef logits |
|---|---|---|---|
| What it solves | Localisation plus class, anywhere on the page | Class only, at a position Stage 1/2 already knows | Stops out-of-scope clef tokens being emitted |
| Localisation work | Re-does it, then needs extra code to assign each box to a staff and to "opening clef" vs a mid-staff change | None: x0 from `staff_left_edge()`, lines from Stage 1 tracking | None |
| Small objects | The "8" under a treble-8vb clef is about 11x15 px on a 2772-px DS2 page. Key accidentals are about 8x20 px at 1600 px. YOLO at 640-1280 input loses them or needs tiling | Crop is in staff-space units (8 px per space), so the "8" is always about 10 px regardless of photo resolution | n/a |
| Key signature | 15 accidental boxes to count and associate; count errors compound | Direct 15-way signed-count head that sees the whole key zone | Cannot help |
| Uncertainty | Box confidences are not calibrated and have no "other/unsure" semantics | Explicit `other` class, temperature scaling, selective thresholds fitted on val | None. The CRNN's clef confidence already has AUROC 0.64 (confidently wrong) |
| Training cost | Hours, plus anchor/scale tuning | Minutes (about 1.4M parameters, 96x128 input) | Zero |
| Where YOLO would win | Mid-staff clef changes, clefs on staves that Stage 1/2 missed | - | - |

The YOLO advantage (mid-staff clef changes) is out of scope for SATB choral scores. Missed staves are a
Stage 1/2 problem that YOLO-for-clefs would not fix either.

Recommended combination:
- the classifier decides the header;
- a decode-time mask of CRNN clef logits to {G-L2, F-L4} is kept only as a fallback when the classifier is
  disabled or has no geometry, always with a loud `clef_unsure` flag (prior doc P3);
- the CRNN's own clef/key tokens are logged for disagreement analysis but never trusted.

### DeepScoresV2 (DS2) as training data, and its own domain gap

Measured on `D:\PiyaNota\datasets\ds2_dense` (the dense subset of DeepScoresV2):
- Classes:
  - `clefG` 8332/2203 (train/test)
  - `clefF` 5405/1488
  - `clefCAlto` 1015/255
  - `clefCTenor` 614/167
  - `clef8` 1101/305: a separate small box, so G8vb must be reconstructed from geometry
  - `clef15` 219/76
  - `keySharp` 12685/3478
  - `keyFlat` 10954/3188
  - `keyNatural` 507/183
  - `staff` 14496/3864

  DS2 distinguishes key accidentals from inline accidentals, which makes the key label possible without
  hand work.
- G8vb:
  - An "8" sits below a G clef 621 times, but in only **53 distinct pieces**, so DS2 alone is thin evidence
    for G8vb.
  - An "8" sits above a G clef 232 times, and below an F clef 164 times.
- **Leakage in the official split:** 171 of the 178 official-test pieces also appear in official-train in
  another font. The notebook pools both files and re-splits by a hash of the piece id (70/15/15). Its `gonville`
  pages are test-only (unseen font).
- Domain gap:
  - Fonts are all LilyPond-family (emmentaler, gutenberg1939, beethoven, lilyjazz, gonville). Leland
    (MuseScore 4's default, the test photos' likely font) is absent.
  - Pages are clean anti-aliased digital rasters, never printed or photographed.
  - Layouts are mostly piano/orchestral, not 4-staff choir.
  - Hence the synthetic Verovio choir systems (Leland, Bravura, Leipzig, Petaluma; Gootville held out),
    camera-style damage before binarisation, and a real-capture validation set (section 4).

## 2. Input decision: binarised, unmasked, staff-space normalised

- **Binarised.** At inference the classifier reads `PreprocessedPage.strip_unmasked`, the native-resolution
  adaptive-threshold page before `non_staff_ink_mask()`. Two reasons:
  - It is exactly what Stage 1 already produces, so there is no second preprocessing path to drift.
  - The mask (`MASK_ATTACH_TOL_SPACINGS=0.75`, link radius 0.2 spacing) keeps only ink attached to the
    staff. The detached "8" below a treble-8vb clef can be erased by it, and it is the one detail that
    separates G from G8vb.
- **Training matches it.** Each stored grey crop goes through, in this order:
  1. camera-style damage;
  2. random resolution (12-30 px per staff space);
  3. background-normalise, blur and adaptive Gaussian threshold (block 1.8-3.5 staff spaces, C 6-14);
  4. optional stroke thinning/thickening;
  5. the same `make_input()` warp that inference uses.

  Val/test use one canonical setting (24 px per space, block 2.5 spaces, C 10). Stage 1's own block is fixed
  in pixels (31 at 1600 px, scaled with the page), which is roughly 2-3 staff spaces on ordinary layouts. The
  1.8-3.5 range covers pages with about 80-150 staff spaces across the width. **Integration must log the
  real block/spacing ratio per page** so an out-of-range page can be flagged.
- **Geometry is in staff spaces**, not pixels. The crop runs from 1 space left of the staff start to 15 right,
  and from 4 spaces above to 4 below the staff, resampled at 8 px per space with an anti-alias blur. That
  gives a fixed 96x128 input: no padding, and BatchNorm runs in eval mode, so a prediction does not depend on
  the batch. This settles the "respect true lengths" requirement for this model. The notebook's eval builds
  every input individually and evaluates it unpadded.
- **Single source of truth.** `clef_key_core.py` is written by the notebook and imported unchanged by Stage 3.
  It holds the crop constants, `staff_left_edge()`, `make_input()` and `ClefKeyNet`. `CROP_SPEC_VERSION` and
  the file's sha256 are stored in the checkpoint, and Stage 3 must refuse to load on a mismatch. The
  exported parity fixture (16 binarised crops with inputs and logits) becomes a repo test.

## 3. Stage 3 / `infer_pitch` integration spec

This spec is not implemented yet. It becomes a ticket, needs senior-reviewer review before merge, and the
feature stays OFF unless weights are passed.

### 3.1 Data plumbing (Stage 1 -> 2 -> 3)

- Stage 1: when the classifier is enabled, call `preprocess_score_image(..., keep_unmasked=True)`. It
  already returns `strip_unmasked` and `strip_staves` (`StaffBand` centre/spacing in native px).
- Stage 2: for each final (reconciled) box, find the nearest tracked `strip_staves` band by centre.
  - If one is within 1 spacing, record `{top_line_y, bottom_line_y}` = centre -/+ 2 x spacing in native px.
  - Otherwise record `no_staff_geometry`.

  Pass this, with the page's `strip_unmasked`, in a dict keyed by `strip_id`. The `voice_sequences` tuple
  `(strip, page_index, sys_idx, voice, v_idx)` stays as it is, so nothing downstream breaks.
- Stage 3:
  1. `x0 = staff_left_edge(unmasked, top, bottom, search_from_x=box_left)`;
  2. `make_input()`;
  3. batch-of-N inference (safe, see section 2);
  4. temperature-scaled softmax with the checkpoint's temperatures and thresholds.

  If there is no geometry or no `x0`, emit a `HeaderDecision` with `source="none"` and both unsure flags set.

### 3.2 `HeaderDecision` and `infer_pitch(..., header: Optional[HeaderDecision] = None)`

```python
@dataclass(frozen=True)
class HeaderDecision:
    clef_token: str            # "clef.G-L2" or "clef.F-L4" (never a C clef: out of scope)
    octave_shift: int          # 0, or -12 for treble-8vb
    key: int                   # signed: -3 = three flats
    clef_unsure: bool
    key_unsure: bool
    reasons: tuple[str, ...]   # e.g. ("clef_below_threshold", "clef_voice_mismatch")
    source: str                # "classifier" | "voice_prior" | "none"
    clef_probs: dict[str, float]
    key_prob: float
```

With `header=None`, `infer_pitch` behaves exactly as today (a regression-test requirement). With a header:

- **Reference pitch:**
  `reference = CLEF_REFERENCE[header.clef_token] + header.octave_shift`.
  - It does not go through `get_clef_reference(voice)`. The octave comes from the image (or from the rule
    below), not from the positional voice label, which Flashlight shows can be wrong.
  - Treble-8vb therefore gives E3 = 52, the same as today's `TENOR_CLEF_REFERENCE["clef.G-L2"]`.
- **Key:** commit `get_key_sig_alterations(max(key, 0), max(-key, 0))` at the start.
- **CRNN header tokens:**
  - The CRNN's leading clef token and its opening key-signature burst are consumed and ignored, and recorded
    on each event as `crnn_clef` / `crnn_key` for disagreement logging.
  - Mid-strip CRNN clef tokens are ignored (reason `mid_strip_clef_token_ignored`, since mid-staff clef
    changes are out of scope and the CRNN's clef tokens are not trustworthy).
  - A mid-strip key change is left to the CRNN but marked `key_unsure` with reason
    `mid_strip_key_change_unverified`.
- **New event fields:** `clef_unsure`, `key_unsure`, `header_reasons`, `clef_source`, `key_source`.
  - Stage 4 carries them through and raises a `review_needed` flag per affected voice/system.
  - They are not `confidence` (which stays note-level and is excluded from these decisions).

### 3.3 Clef rules (in this order)

| Step | Condition | Result |
|---|---|---|
| 1 | Predicted class is `other`, or top probability < `clef_threshold` | `clef_unsure` (`clef_out_of_scope` / `clef_below_threshold`); fall back to the voice prior (`CLEF_FALLBACK[voice]`, today's Tenor octave rule), `source="voice_prior"` |
| 2 | `G8vb` and `g8vb_reliable=True` | `clef.G-L2`, octave -12 |
| 3 | `G` or `G8vb` with `g8vb_reliable=False` (treble family) | `clef.G-L2`. Octave -12 if the staff's voice is Tenor or Bass by position, else 0, with reason `octave_from_voice_prior` (informational, not unsure) |
| 4 | `G` (plain) on a Tenor or Bass position with `g8vb_reliable=True` | `clef.G-L2`, octave -12 (choral convention: an unmarked treble on a tenor line is still 8vb), reason `plain_treble_on_low_voice_assumed_8vb` |
| 5 | `F` | `clef.F-L4`, octave 0 |
| 6 | Voice check: allowed Soprano {G}, Alto {G}, Tenor {G, G8vb, F}, Bass {F} | Mismatch -> `clef_unsure` with `clef_voice_mismatch`, but the **detected** clef is used. On Flashlight's 4th staff (labelled "Bass" by position, treble-8vb in the image) this gives the right pitch and a review flag, instead of a silent wrong-clef octave |
| 7 | CRNN clef disagrees with the header | Logged only (`crnn_clef`), no flag: the CRNN's clef is known to be wrong |

Rule 4 is an assumption. It is correct for the SATB convention but wrong for a genuine treble-clef line
labelled Tenor by position. That situation is also caught by the system-level check below.

**Can the "8" be seen?**
- In DS2 it is a separate box of about 11x15 px directly below the G bbox (0-1.5 staff spaces).
- In the crop it lands about 1.5-3 spaces below the bottom line, inside the 4-space lower margin, at about
  10 px tall.
- So it is detectable in principle. Whether it survives phone capture plus binarisation is exactly what
  `g8vb_reliable` (pre-registered on val: G8vb recall >= 0.95 and G->G8vb <= 2% on every val source with
  at least 30 G8vb) and the real-capture validation set (section 4) must show.
- Until both pass, run in treble-family mode (rule 3). Recording `g8vb_reliable=False` is an expected,
  acceptable outcome.

**System level.**
- Set `satb_layout_suspect` (with `review_needed`) on the system when its clef pattern cannot be SATB. Examples:
  - no confident F clef on any staff, while positions say Bass;
  - an F clef above a G clef.
- This is the check that catches Flashlight-style layouts before four "voices" are synthesised with the wrong
  labels.
- It does not relabel voices (that is a Stage 2 / scope decision; see section 7).

### 3.4 Key rules

- Per staff:
  - top probability < `key_threshold` -> `key_unsure` (`key_below_threshold`);
  - the key used is still the argmax, since nothing better exists;
  - `source="classifier"`.
- Per system vote (all staves of an SATB system share one key):
  - if at least 3 staves are confident and agree, that is the system key, and confident dissenters get
    `key_unsure` / `key_system_disagreement`;
  - with no consensus, all staves get `key_unsure` / `key_no_system_consensus`.
- Keys are never "corrected" silently to the vote. The flag is the output; a later ticket may choose to
  adopt the vote.

### 3.5 Minor pre-existing inconsistency noticed

`TENOR_CLEF_REFERENCE["clef.C-L4"] = 49` versus `CLEF_REFERENCE["clef.C-L4"] = 50`. This is out of scope
(C clefs) but worth a one-line fix or comment when this area is touched.

## 4. Validation plan (held out, and not the test photos)

| Set | Built from | Used for | Never used for |
|---|---|---|---|
| train | DS2 pieces with hash bucket < 70 (4 LilyPond fonts) + synthetic systems (80%, 4 Verovio fonts) | weights | anything else |
| val | DS2 buckets 70-84 + synthetic 10% | epoch selection, temperatures, thresholds, `g8vb_reliable` | reporting as final accuracy |
| DS2/synthetic test | DS2 buckets >= 85 (seen fonts), DS2 `gonville` pages of test pieces (unseen font), synthetic 10% (seen fonts), Gootville systems (unseen font); plus an augmented "stress" copy of each | one final read after val decisions are frozen | tuning |
| **Real-capture validation (new, needed before any pipeline use)** | The user generates open-score SATB and solo+SATB pages in MuseScore 4 (Leland), from music **not** in the test photos, with known clef/key per staff. Pages are printed, photographed with a phone under varied light and run through Stage 1/2. Labels come from the generating file, not from hand-reading | checking that thresholds, `g8vb_reliable` and unsure-flag AUROC transfer to camera input; may re-fit temperatures/thresholds (then report the new numbers as "real-capture val", and split it 50/50 by page into fit/check) | training the network |
| Test photos (piyanota_dataset incl. Flashlight, DSMN, BSN) | as is | one final end-to-end read after everything above is frozen | anything else |

Pre-registered go criteria for enabling the classifier in the pipeline. These are fixed now, before any
result.
- On the real-capture check half, clef accuracy on staves marked sure is >= 99% with Wilson lower bound
  >= 97%.
- The confident-and-wrong clef rate is <= 1%.
- The AUROC of confidence for right-vs-wrong is >= 0.90 for clef and key. The CRNN's clef value is 0.64.
- The same criteria apply to key.
- Sizing:
  - With about 200 real staves the Wilson half-width at 99% is about 1.5 points, which is enough to tell
    99% from 95%.
  - The 6-screenshot or 23-strip diagnostic sets are **not** adequate for this; they are diagnostics only.
- `g8vb_reliable` may only be switched on from real-capture evidence with at least 30 real G8vb staves.

Report everything per source (DS2 seen, DS2 unseen font, synthetic seen, synthetic unseen font, stress,
real-capture), never as one number.

## 5. Leakage and confound risks

1. **DS2 official split leaks pieces:** 171 of 178 test pieces are in train. Mitigated by the piece-hash
   re-split, with an assert that no piece is in two splits. The split manifest and its sha256 are exported.
2. **Multi-font duplicates:** the same piece in several fonts must share a split. Handled by splitting on the
   piece, not the image. Gonville is test-only.
3. **Calibration and thresholds on val only:** the notebook enforces this. Real-capture re-fitting uses its own
   fit/check halves.
4. **Design informed by a test photo:** the decision to trust the image over staff position was prompted by
   seeing Flashlight's layout (layout only, no tuning on its pixels). Disclose this when Flashlight is
   reported. It is a design-level contamination, not a parameter fit.
5. **DSMN/BSN were used to develop Stage 1/2** (tracker, reconcile, mask). Pipeline numbers on them are not
   independent of Stage 1/2 geometry, which this classifier depends on. Flashlight and other untouched
   `piyanota_dataset` pages are the cleaner test.
6. **DS2 pages used for classifier training cannot later serve as an independent test** of anything that
   uses this classifier.
7. **Correlated errors with the CRNN:** the CRNN was fine-tuned on Verovio re-renders in some of the same
   fonts. Agreement between the two is therefore weak evidence. Only image-independent labels (the
   real-capture set) validate either.
8. **Label shortcuts:** in synthetic data, staff names and clefs are drawn independently, and every staff
   position gets every clef. This stops the model learning "name text" or "4th staff = F".
9. **Same songs in DS2 and the test photos:** unlikely (DS2 is MuseScore-community classical/piano). The
   effect on a clef/key classifier would be negligible anyway, because it sees only the staff start.
10. **Determinism:** the notebook uses per-sample RNG seeded by (SEED, epoch, index), seeded sampler and
    loader generators, and cuDNN deterministic mode. A second-seed run is recommended before relying on the
    numbers, and both seeds are reported as a range (the lesson of the CRNN runs).

## 6. Does the CRNN also need retraining for SER? Yes.

- Header replacement changes at most 1 + |key| tokens per strip, whereas the real-strip token SER is 44-48%.
  Pitch accuracy on DSMN was 10.6-11.4% as-is and 86-88% with the ground-truth clef substituted. So this
  classifier is the biggest single **pitch** fix, but SER stays dominated by body errors: hallucinated
  clusters, missing rests, phantom accidentals.
- The current fine-tuned checkpoints (0.056-0.093 `loo_font_ser` across the two seeds, epoch 2) show
  font transfer on clean CPM-layout crops only. That says nothing about real layouts.

Prerequisites, in order (all cheap):
1. **Eval harness:** decode only up to each sample's true length (`in_lens`), pad with white instead of
   0.0 (mid-grey), and check batch-1 agreement (review doc P2).
2. **Report header and body SER separately**, per source.
3. **Match training input to inference:** train on binarised strips made by the Stage 1 path, with
   augmentation *before* the resize to 64 px (scale, stroke, JPEG, binarisation jitter). Ablate this one
   change first (review doc P1/P4).

Data for retraining, ranked by expected value per effort:
1. **Full PrIMuS (~87k incipits) re-rendered through Verovio in several fonts, embedded in layout-realistic
   context.** This means staff names, brackets, fragments of neighbouring staves, lyrics, dynamics, wider
   system spacing, and scale/stroke jitter, cut with the Stage 2 crop rule, then print/photo simulation and
   Stage 1 binarisation. Labels stay exact (zero hand work). This is the same generator family as the
   classifier's synthetic data, extended to full strips.
2. **Clef-swap rebalancing:** for key-0 incipits, re-render with the other in-scope clef and re-derive the
   note tokens. This removes the clef prior the CRNN learned from CPM's clef distribution.
3. **Print-and-photograph loop** of generated pages (the same pages as the real-capture validation set can be
   produced in larger numbers, with disjoint music for training).
4. **Open-score SATB MusicXML** (for example public-domain hymnals and chorales) rendered through MuseScore/Verovio,
   with a MusicXML/MEI -> agnostic-token converter. This gives the most realistic layouts but needs the
   converter and a chord token decision (Bass divisi).
5. **DS2-derived strips:** real engraving, but piano/orchestral and missing agnostic labels, so it needs a
   converter from DS2 annotations. Lower priority.
6. **Hand-labelled real strips:** last, only as a small validation/fine-tune set once 1-4 are exhausted.

Experimental discipline:
- Change one factor per run: binarised input only, then + layout context, then + photo simulation, then
  + clef-swap.
- Keep a renderer that is never trained on (for example MuseScore 4 CLI exports) as the held-out "unseen
  renderer" test.
- Keep a CPM-original eval to watch for forgetting.
- Report every seed as a range.
- A second notebook is not written yet. It should reuse `clef_key_core.py`'s binarisation/augmentation
  functions so that the CRNN and the classifier see identically processed pixels.

## 7. Questions for the user

1. **Is the solo + SATB layout (Flashlight: Soloist / Soprano / Alto / Tenor, no Bass) in scope?**
   - If not: the classifier's `satb_layout_suspect` flag lets the app reject such pages explicitly, instead of
     producing a mislabelled "Bass".
   - If yes: Stage 2 needs voice assignment from staff names or clefs rather than position, which is a
     separate ticket. This classifier provides the clef half of that signal, but not the name.
2. May the real-capture validation set (section 4) be made? It needs MuseScore 4, a printer and a phone,
   about 20-30 pages, and music not in the test photos. Without it, the go criteria cannot be checked and the
   classifier must stay flag-only.
3. Should a plain treble clef on a Tenor-position staff be read as 8vb (rule 4)? This is the choral
   convention and is recommended.

## 8. What the user runs on Kaggle

The notebook's first markdown cell has the click-by-click version. In short:

1. Upload DS2 as a private dataset:
   - zip `D:\PiyaNota\datasets\ds2_dense\images\` plus `deepscores_train.json` and `deepscores_test.json`,
     leaving out `instance\` and `segmentation\`;
   - upload the zip as the private dataset `piyanota-ds2-dense`;
   - attach it to the notebook with Add Input.
2. Set Accelerator to GPU T4 and Internet to On.
3. Run once with `SMOKE_TEST = True`, then set it to `False` and Save Version -> Save & Run All.
4. Download from the Output tab and place:
   - `clef_key_classifier.pt` in `music_symbol_detection\`;
   - `clef_key_core.py` in the repo root;
   - the JSON, NPZ and PNG files in `training\clef_key_artifacts\`.

   Nothing gets committed until ml-cv-lead has reviewed the metrics.

## Files

- `D:\PiyaNota-training\training\piyanota-clef-keysig-kaggle.ipynb`: the training notebook.
- `D:\PiyaNota-training\stage3_transcription.py`: integration target. Relevant parts are `CLEF_REFERENCE`,
  `TENOR_CLEF_REFERENCE`, `CLEF_FALLBACK`, `get_key_sig_alterations` and `infer_pitch`.
- `D:\PiyaNota-training\stage1_preprocessing.py`: `_build_strip_source` and `keep_unmasked`.
- `D:\PiyaNota-training\stage2_detection.py`: `VOICE_MAP`, and the strip tuples.


## 2026-09-26 amendment: validation set, data sufficiency, mid-piece key changes, local training

Author: ml-cv-lead (advisory). Status: **proposal; nothing trained, nothing implemented, nothing committed.**
Everything below was written **before any classifier result exists**, so the criteria changes in A.5 are
legitimate pre-registration amendments, not post-hoc tuning. Once a real run has been seen, none of them may
be changed again.

New inputs from the user (2026-09-26):
- The real-capture validation set is the phone photos of **Dormi Jesu** (9 pages) and **Livin' on a Prayer**
  (pg01-10 plus pg10_b), from `D:\PiyaNota\data\piyanota_dataset\realphoto_validation_set\`. The user explicitly
  approved this exception to the "piyanota_dataset is test-only" rule for these two pieces. Labels (per staff
  clef and key, including mid-staff changes) go in `data/val_clefkey/labels.json`.
- Honneur a Toi pg01-03 replaces Flashlight as the fresh CRNN test piece. DSMN (23 scored strips from pg01-05)
  remains the existing held-out test set.
- Training moves from Kaggle to the local PC: GTX 1650 4 GB, torch 2.6.0+cu124, Python 3.13, 16 GB RAM
  (measured), Windows 11. The GPU driver wedged once on 2026-09-23.

What I looked at for this amendment: the preview JPEGs of Dormi pg01 and pg06, Livin' pg03 and pg09, and
downscaled views of Flashlight pg02 and Honneur pg01. I did not open any crops or run any model on them. The
staff counts below are **estimates from those pages**. The real counts from `labels.json` replace them.

### A. Is the data enough? (question a)

#### A.1 How many staff crops the validation set gives

| Piece | Pages | Staves per page (seen) | Estimated staff starts | G (treble) | G8vb | F (bass) | Keys seen |
|---|---|---|---|---|---|---|---|
| Dormi Jesu | 9 | 9 (4-staff system + 5-staff system with a soprano obligato) | ~75-80 | ~40-45 | ~18 | ~18 | +2, -2 (with mid-staff changes both ways) |
| Livin' on a Prayer | 10 (+ pg10_b) | 8-12 (2-3 systems of 4) | ~100-120 | ~50-60 | ~25-30 | ~25-30 | -1, -4 (mid-staff change at a double bar, with a time-signature change) |
| **Total** | 19-20 | | **~175-200** | ~90-105 | **~43-48** | **~43-48** | about 4 distinct values out of 15 |

- **pg10_b.** If it is a retake of pg10, it is the same staves photographed twice. Count only one of the two
  toward n. If both are kept, they must always sit in the same fold, never one in "fit" and one in "check".
- **"Other" clefs and F clefs on a Tenor staff: expect zero.** Every Tenor staff I saw is treble-8vb and every
  Bass staff is bass clef. So the voice-mismatch path (plan section 3.3, rule 6) and the `other` class get
  **no real validation at all** from this set.
- **The class balance is better than feared for clefs, but it is still skewed in a way that matters.**
  - G8vb is about a quarter of all staves (one Tenor per system), so there are about 45 real G8vb staves. That
    clears the existing `>= 30 real G8vb` gate for `g8vb_reliable`, but only when both pieces are pooled.
  - The real problem is diversity, not balance. There are 2 engravings, 1 phone, and each clef always sits on
    the same voice.
  - The key diversity is very poor: about 4 of the 15 key values. A 99% key accuracy on this set says
    **nothing** about 5-7 sharps or flats. For those keys the only evidence stays DS2/synthetic.

#### A.2 The arithmetic for the pre-registered gate

The gate from section 4: accuracy-when-sure >= 99% with a Wilson 95% lower bound >= 97%, confident-wrong
<= 1%, AUROC >= 0.90. The Wilson lower bound only depends on n and the number of errors:

| Errors among the "sure" staves | Minimum sure staves for lower bound >= 97% | Observed accuracy at that n |
|---|---|---|
| 0 | 125 | 100% |
| 1 | 185 | 99.46% |
| 2 | 239 | 99.16% |
| 3 | 290 | 98.97% |
| 4 | 339 | 98.82% |

At exactly 99% observed:

| n sure | Wilson 95% interval | Passes lower bound >= 97%? |
|---|---|---|
| 100 | 94.6-99.8% | no |
| 150 | 95.3-99.6% | no |
| 200 | 96.4-99.7% | **no** |
| 250 | 97.1-99.8% | just |
| 300 | 97.1-99.7% | yes |

**Correction to my own section 4.** It said "about 200 real staves ... is enough to tell 99% from 95%". That is
true, but 200 is **not** enough to pass the 97% lower bound at 99% observed. That needs about 250-300 sure
staves, or at least 125 with zero errors. Also, "sure" staves are a subset: any staff marked unsure drops out
of n.

Other points on the arithmetic:
- **The confident-wrong rate** can be checked as a point estimate. It cannot be *proven* to be <= 1% at this
  size. With 0 confident-wrong in 200, the 95% upper bound is 1.9%. Proving <= 1% with zero errors needs
  about 380 staves.
- **AUROC** measures how well confidence separates right answers from wrong ones. It needs wrong answers to
  measure. If the model is as good as the gate demands, there will be about 2 wrong staves in 200, and an
  AUROC from 2 negatives is noise. A good model therefore makes AUROC un-measurable on this set. See A.5 for
  the amendment.
- **Clustering.** Wilson assumes every staff is independent. They are not: errors cluster by piece (one
  engraving) and by page (one photo). With 2 pieces, the honest statement is "reliable on these two
  engravings as photographed". It is not "reliable on any engraving". The independent check of the latter is
  the one-time Honneur/DSMN test at the end. Report a page-level cluster bootstrap interval next to Wilson.

#### A.3 What this means in one line

- About 190 staves from 2 pieces is **enough to catch a bad classifier**. At 90-95% real accuracy it will fail
  clearly.
- It is **borderline for proving** the 99% / lower-bound-97% gate. It can only pass with 0-1 errors.
- It is **not usable for fitting thresholds and then checking them on the same staves**.

#### A.4 The fit/check split from section 4 no longer works

Section 4 said the real set may re-fit temperatures/thresholds on a 50/50 page split. With about 190 staves,
each half has about 95. A 95-staff check half cannot reach the 97% lower bound even with zero errors (it
needs 125). New rule:

1. **The real set is check-only.** Temperatures, thresholds, epoch selection and `g8vb_reliable` stay fitted on
   the DS2/synthetic val splits, exactly as the notebook does now. The real set is scored once, after the run
   is frozen.
2. **If that check fails on calibration** (for example confident-wrong > 1%, or the sure-accuracy is below
   target), the fallback is leave-one-piece-out cross-fitting. Fit the temperature and threshold on N-1 real
   pieces, score the held-out piece, rotate, and report the pooled out-of-fold results. This gives an honest
   out-of-sample number using all staves. With only 2 pieces it is fragile, which is one more reason for B.3
   (adding Flashlight as a third validation piece).
3. The network weights are **never** trained on the real set.

#### A.5 Pre-registered criteria amendments (made now, before any result)

1. **AUROC gate.** It applies on the real set only if the real set has **>= 10 wrong** clef (resp. key) staves.
   Otherwise report "AUROC not estimable (k wrong)", and the AUROC >= 0.90 requirement is checked on the DS2/
   synthetic *stress* test sets, which have enough errors. Confident-wrong is then the primary real-data
   uncertainty check.
2. **Sizing target.** Pass requires the Wilson lower bound >= 97% on the pooled real check set. If the pooled
   sure-n is < 125, the result is **"not proven"**, not "pass", however clean it looks.
3. **Scope of what the gate licenses.** A pass licenses only:
   - treble / treble-8vb / bass on S/A/T/B positions;
   - the key values actually present in the real set.

   F-on-Tenor, `other`, and keys whose |key| is not present in the real set stay DS2/synthetic-only evidence.
   In the pipeline, the voice-mismatch rule (rule 6) keeps its `clef_unsure` flag whatever the classifier says.
4. **Labels.**
   - Every staff where model and label disagree is re-inspected from the image, and each outcome is logged in
     `data/val_clefkey/adjudication.json` (label kept / label corrected, with the reason).
   - At a 1% error budget, one mislabel is half the budget, so label quality matters as much as model quality.
   - Labels are corrected only on unambiguous image evidence, never "because the model said so".
5. **The inputs come from the deployment path.** Real-set crops must be produced by Stage 1
   (`keep_unmasked=True`) + Stage 2 geometry + `staff_left_edge()` + `make_input()`. They must not be
   hand-cropped. Staves that Stage 1/2 fails to give geometry for are reported as a separate coverage number
   (`no_staff_geometry` rate), never silently dropped from the denominator.

#### A.6 Is the training data sufficient?

- **In count, yes, comfortably.**
  - DS2 dense has about 18k staff boxes, most with an opening clef. About 70% go to train after the piece
    re-split and after the gonville font is removed.
  - The 3000 synthetic systems give about 8k training staves.
  - For a 1.4M-parameter, 4-way/15-way classifier with heavy augmentation, about 18k staves is plenty.
  - G8vb has about 420 DS2 training staves from about 37 pieces, plus about 2k synthetic ones.
- **In domain, not proven, and more data of the same kind would not prove it.** The known gaps:
  1. No printed-and-photographed images in training. The camera look is simulated only.
  2. Neither validation engraving's font is in training. That is intended: the real set measures exactly this.
  3. **Pencil markings.** Livin' pg09 has heavy pencil loops and scribbles crossing staff starts; Dormi has
     circled dynamics. Choir scores are annotated by singers, so this is a deployment-domain fact. The current
     augmentation has dust specks but no strokes. **Recommended before the run:** add a "pencil stroke"
     augmentation: a few random thin, grey-to-dark curves (bezier or polyline) across the crop, applied to the
     grey crop before binarisation. Disclosure: this idea came from looking at validation photos. It is
     design-level exposure (like the Flashlight layout note in section 5 item 4), not a parameter fit. Record
     it in the checkpoint metadata.
  4. Staff starts that open with cancellation naturals before a new key. They occur in older engraving styles
     when a key change coincides with a system break. DS2 marks these "ignore", and the synthetic set has none.
     This is not needed for v1. If `labels.json` shows any, report them separately.
- The MuseScore print-and-photograph set from section 4 is still the right way to cover F-on-Tenor, `other`,
  and many keys, and to get past 300 real staves. It is no longer a blocker for a first check, but it **is**
  the path to a proven pass if the two-piece check is "not proven".

### B. DSMN and Flashlight for training or validation? (question b)

#### B.1 DSMN: no, for any role (training, validation, thresholds or epoch selection)

**Yes, using DSMN would contaminate the end-to-end test, even though the classifier is a separate model.**

- DSMN pitch accuracy is 10.6-11.4% as-is and 86-88% with ground-truth clefs. The header (clef + key) is
  **the** dominant term in the pitch number we report. A classifier that has seen DSMN's staff starts, or has
  had its thresholds tuned on them, will get DSMN's headers right by memory, not by generalisation. The
  reported DSMN pitch accuracy would then jump for a reason that does not transfer to a new score.
- DSMN has one engraving, a couple of keys and four clef appearances repeated 60 times. That is exactly the
  kind of set a 1.4M-parameter CNN memorises.
- **DSMN pg06-12 are also out.** They are not among the scored strips (pg01-05), but they are the same piece,
  the same engraving, the same key, and very likely the same photo session. Training on them teaches the
  model the test's exact glyphs. Leakage happens at the piece level, not the page level. The plan already
  splits DS2 by piece for exactly this reason.
- DSMN pg01-05 are byte-identical to the test photos in `piyanota_dataset`, so there is not even a
  near-duplicate argument there.
- DSMN was also already used to develop Stage 1/2 (section 5 item 5). Adding the classifier on top would stack
  a second, larger contamination on the same test set.

#### B.2 Honneur a Toi: no, for any role

It is the new fresh test piece. Its GT is being annotated, and it must stay untouched until the one-time final
read.

#### B.3 Flashlight: yes as validation, provided it is formally retired from testing; not as training

- Since the user dropped Flashlight as a test piece, it may join the real **validation** set. Conditions:
  1. **Write the retirement down**, in `docs/bug-tracker.md` or the PIYA-106 decision record: "Flashlight
     pg01-08 retired from test on 2026-09-26, now classifier validation". Any Flashlight numbers already
     produced under `data/eval_flashlight/` stay as historical diagnostics and are never again quoted as test
     results.
  2. **Disclose the style link to Honneur.** Both look like Finale-default engraving (Maestro-style glyphs),
     and were probably photographed with the same phone. Validating on Flashlight therefore puts the Honneur
     test's engraving family into threshold/selection exposure. This is acceptable and even desirable for
     realism, but the Honneur report must say "engraving family seen in classifier validation (Flashlight)".
  3. Flashlight's layout is Soloist / S / A / T with **no Bass staff**. It adds about 90 staves (about 70 G,
     about 22 G8vb, **0 F**) and probably 1-2 key values.
- **Why validation and not training:**
  - As training data, about 90 staves next to about 18k would be swamped. They would only matter if heavily
    up-weighted, which is how overfitting to one engraving happens.
  - As validation they are worth much more. The pooled real set rises from about 190 to about 280 sure-able
    staves, which is roughly where the 97% lower bound becomes reachable (A.2).
  - It also becomes 3 pieces instead of 2, which makes leave-one-piece-out cross-fitting (A.4) meaningful.
- The user decides whether to add it. If yes, it must be added to `labels.json` **before** the classifier is
  first scored on the real set, not after a failed check.

#### B.4 Test set after this amendment

The DSMN pg01-05 scored strips plus Honneur pg01-03 are the only test data. Both Sides Now remains test-only
for Stage 1/2 purposes as before.

### C. Mid-piece key changes and clef changes (question c)

#### C.1 What the plan and notebook do today

- **The classifier only reads the staff start.** Its crop is 1 staff space left to 15 right of the first
  staff-line column. It never sees anything later in the strip.
- **The header on every new system is still covered.** Engraving convention reprints the current clef and key
  at the start of every system. After a key change, the next system starts with the new key, so the header
  classifier handles it automatically. The courtesy signature at the end of the previous system sits at the
  right edge of that strip, which the classifier never sees.
- **A mid-staff change inside a system is not seen by the classifier at all.**
  - Plan section 3.2 leaves mid-strip key changes to the CRNN, marked `key_unsure` /
    `mid_strip_key_change_unverified`.
  - It ignores mid-strip CRNN clef tokens.
  - Both example pieces have such changes:
    - Dormi pg06, system 2: 2 flats to 2 sharps at a double bar, with cancellation naturals on at least the
      lower staves; the piece also goes +2 to -2 earlier.
    - Livin' pg09, system 2: 1 flat to 4 flats at a double bar, together with a 3/4 to 4/4 change.
- **What `infer_pitch()` does today** (`stage3_transcription.py`, lines 1123-1182):
  1. Every `barline` token moves the state machine to `post_bar`.
  2. A sharp or flat right after it, at a valid key-signature position for the active clef, starts a
     `mid_keysig` burst of same-type accidentals. The burst is committed by `_commit_mid()` as the new key.
     A single accidental counts.
  3. Three weaknesses:
     - **Naturals are not understood.** A natural after a barline falls through to the body as an inline
       accidental on the next note. So a cancellation ("naturals, then the new sharps") never commits the new
       sharps: they become inline accidentals too. A change to C major, which is naturals only, is never
       committed. For Dormi's -2 to +2 change, the rest of the strip keeps 2 flats.
     - **False positives.** An ordinary inline sharp on the first note of a bar, at a key-signature position
       (for example F#5 in treble), is committed as "key change to 1 sharp" for the rest of the strip. The
       CRNN's body tokens are 44-48% wrong, so this will fire on noise. Once the classifier provides the
       correct header, this path can overwrite a correct key with a wrong one. That is a regression risk that
       does not exist while the header is wrong anyway.
     - The key-signature position test depends on `active_clef`, which today is almost always the wrong
       `clef.C-L3`.
- **How much damage does a missed mid-staff change do?** It is bounded to the rest of that one strip per
  voice, because the next system's header resets it. On Dormi pg06 system 2 that is about 40% of the notes in
  4 strips. That is too much to leave silent, but it is not a whole-piece failure.

#### C.2 Recommended v1 design (simple, no new model)

Key idea: **every system reprints the key and clef, so comparing consecutive system headers tells us for free,
from the image, whether a change happened inside a system and what the new value is.** Only the location
inside the strip is unknown. The CRNN is used only to locate the change, never to decide whether one happened
or what the new key is.

Stage 3 becomes three passes. `infer_pitch` itself only applies decisions:

1. **Pass 1 (per strip):** CRNN decode + classifier header (as in section 3). This is already batch work.
2. **Pass 2 (per system, all 4 voices together):** the system key vote from section 3.4 gives `K[s]` for every
   system `s`. Clefs are per voice: `C[v][s]`.
3. **Pass 3 (per strip):** `infer_pitch(..., header, key_plan)`. `key_plan` is a list of
   `(measure_index, key)` changes decided in pass 2. When a `key_plan` is given, the internal `mid_keysig`
   commit is **disabled**. Post-barline sharp/flat/natural bursts are still consumed as key-signature glyphs
   (so they are not applied to notes), but they no longer set the key.

Key-change rules for system `s` (pass 2):

| Case | Condition | Action | Flags |
|---|---|---|---|
| K1 | `K[s+1] == K[s]`, both confident | No change in system s. Any CRNN post-barline burst in s is treated as inline accidentals (today's `body` behaviour) | `mid_keysig_suppressed` (log only) |
| K2 | `K[s+1] != K[s]`, both confident, and CRNN bursts are found after the same `measure_index` (+/-1) in >= 2 of the system's voices | Apply `K[s+1]` (the **classifier's** value, not the CRNN count) from that measure to the end of strip s, in all voices | `key_change_located` (informational); `key_unsure` + `key_change_count_disagrees` if the CRNN's burst count does not match `K[s+1]` |
| K3 | `K[s+1] != K[s]`, but no agreeing burst | Assume the change is at the end of the system (the common "change at the system break" case, where the only glyph is the courtesy key at the right edge). Notes are unchanged | `key_unsure`, `key_change_location_unknown`, `review_needed` on system s, all voices |
| K4 | Last system (no `s+1`), or either header unsure | Apply a CRNN burst only if >= 3 of 4 voices agree on the measure and the count; otherwise ignore it | `key_unsure`, `mid_strip_key_change_unverified` |

Burst recognition (small `infer_pitch` change): after a barline, a run of **naturals** at key-signature
positions, optionally followed by a same-type sharp/flat run, is one burst. So "naturals only" means key 0,
and "naturals then sharps" means the new sharps. Naturals are no longer passed through to the next note.

Known limitation, accepted: a change and a change back within one system (A to B to A) is invisible to the
header comparison. It is rare in choral writing, and it is logged when the CRNN reports bursts that K1 then
suppresses.

Clef changes:
- **Use the same header comparison, but never the CRNN for location.** The CRNN's clef tokens are the
  confidently-wrong ones (BUG-011), so mid-strip `clef.*` tokens stay ignored (reason
  `mid_strip_clef_token_ignored`).
- If `C[v][s+1] != C[v][s]` with both confident, the new clef applies from system s+1, and system s gets
  `clef_unsure`, `clef_change_location_unknown` and `review_needed` for that voice.
- In SATB scope this realistically means a Tenor switching between treble-8vb and bass. It is rare, and it is
  always flagged, never silently wrong for more than one strip.
- Courtesy clefs at the end of a strip affect no notes.

#### C.3 What v2 would add (only if C.2's flags turn out to be frequent)

- A **barline probe**: the same classifier architecture, trained with an extra "clef: none" class and a
  "no change" key class, on crops anchored at each image-detected barline.
- Training data would be Verovio systems with mid-measure-list key changes, including cancellation naturals.
- It would replace CRNN-based location in K2/K3.
- Do not build it before v1's flag rates on the real set show it is needed.

#### C.4 Evaluating C

- `labels.json` should record, per staff, the start clef/key (the classifier target) **and** a list of
  changes with the measure number and the new value.
- There will only be about 3-6 system-level change events in Dormi + Livin'. That is **diagnostic only**:
  report each event (detected yes/no, location right yes/no), with no percentages.
- The C.2 rules are hand-set, like the Stage 4 priors, and have no statistical validation at this sample size.

### D. Local training plan (question d)

Recommendation: **convert the notebook to a terminal script, `training/train_clef_key.py`.** The reasons:
- Windows multiprocessing uses spawn. Spawn needs picklable top-level functions in an importable module with
  an `if __name__ == "__main__":` guard. Jupyter `__main__` functions do not qualify, which is why the
  notebook falls back to 1 process on Windows. As a script, the crop-extraction phases can use 8 processes.
- A terminal process with a log file survives a wedged kernel. A notebook's state does not.
- Phase caching and resume are natural in a script.

Keep the notebook in the repo as the Kaggle fallback, frozen, and note in its first cell that the script is now
the reference.

#### D.1 Spec checklist

Structure and paths:
- [ ] `clef_key_core.py` becomes a real file at the repo root (`D:\PiyaNota-training\clef_key_core.py`). The
      script imports it. `CORE_SHA256` is the sha256 of that file's bytes, and there is no string copy of it
      inside the script. Stage 3 later imports the same file.
- [ ] CLI:
      `python training\train_clef_key.py --ds2 D:\PiyaNota\datasets\ds2_dense --seed 20260926 [--smoke] [--resume RUN_DIR] [--phase prepare|train|eval|all]`.
      There is no hard-coded `/kaggle` path. `INPUT_ROOT` / `find_one()` is replaced by `--ds2`, and the
      script checks that `images\`, `deepscores_train.json` and `deepscores_test.json` all exist.
- [ ] Run directory: `training\clef_key_artifacts\<run_id>\`, where
      `run_id = f"{'smoke' if smoke else 'full'}_seed{seed}_{UTC timestamp}"`. Every JSON, NPZ, PNG and log goes
      there: `clef_key_metrics.json`, `clef_key_splits.json`, `clef_key_history.json`,
      `clef_key_parity_fixture.npz`, `preview_*.png`, `train.log` and `config.json`.
- [ ] Weights are written to the run dir only (`clef_key_classifier.pt`). **The script does not write to
      `music_symbol_detection\`.** The user copies the file there after review. Note: `.gitignore` has a blanket
      `*.pt`, so the final file needs a force-add under LFS when it is approved. Per-epoch checkpoints stay
      ignored.
- [ ] Cache directory: `training\clef_key_cache\` (add it to `.gitignore`), keyed by a hash of: core sha256,
      `STORE_*` constants, seed, `N_SYNTH_SYSTEMS`, verovio/resvg versions, and the sha256 of both DS2 JSONs.
      On a key mismatch, rebuild; never silently reuse a stale cache.

Phases, each cached and restartable:
- [ ] `prepare-ds2`:
      - Parse `deepscores_train.json`, then `deepscores_test.json`, **one at a time**, with `del d; gc.collect()`
        in between.
      - Write compact staff records (`ds2_records.json`) so the 226 MB JSON is parsed once per cache. Expected
        peak RAM for the parse is about 2-3 GB, which fits in 16 GB.
      - Extract crops with `ProcessPoolExecutor(max_workers=8)` into `ds2_raw.npy` (a uint8 memmap via
        `np.lib.format.open_memmap`, about 1 GB).
- [ ] `prepare-synth`:
      - Run Verovio + resvg with 8 processes, one toolkit per process (the current `_toolkit()` global is
        fine under spawn), into `synth_raw.npy` (about 0.7 GB).
      - Assert `verovio.toolkit().getVersion()` starts with `6.3.0` and `resvg_py` is `0.5.0`. Both are
        installed locally and match the pin.
- [ ] `prepare-eval`: build the canonical eval inputs (float16) into `eval_inputs.npz`. Stress copies are built
      at eval time, as now.
- [ ] Load RAW with `np.load(mmap_mode="r")`. Do not use `np.concatenate` on two 1 GB arrays; index across the
      two memmaps with an offset instead.

Hardware settings:
- [ ] DataLoader: `num_workers=0` (the default). The per-sample RNG `(SEED, epoch, i)` already makes the
      augmentation independent of the worker. An optional `--workers N` may be added later, but only after a
      check that the first 3 batches hash-equal the `num_workers=0` batches.
- [ ] `BATCH_SIZE = 128`, fp32. The estimated training activation memory is about 1.5 GB at 128, which fits in
      the roughly 3.3 GB usable on a display-attached 4 GB card.
- [ ] **No AMP.** The GTX 1650 has no tensor cores, so fp16 gives little speed. The GPU is not the bottleneck
      (CPU augmentation is), and AMP adds a numerics difference that would touch calibration.
- [ ] Eval batch 256 (not 512), to leave headroom.
- [ ] If an out-of-memory error happens at 128, do not silently drop to 64: stop and report. A batch change
      changes the results and must be a recorded config change.
- [ ] Call `torch.cuda.set_per_process_memory_fraction(0.85)`, so a leak fails as a Python OOM rather than
      pushing the driver.

Determinism and seeds:
- [ ] Set `CUBLAS_WORKSPACE_CONFIG=:4096:8` at the very top of the script, **before** `import torch`.
- [ ] Keep: `cudnn.deterministic=True`, `benchmark=False`, `use_deterministic_algorithms(True, warn_only=True)`
      (log any warnings it emits into `train.log`), `cv2.setNumThreads(1)`, the per-sample RNG, and the
      seeded `sampler_gen` / `loader_gen`.
- [ ] Record `VERSIONS` plus `nvidia-smi --query-gpu=name,driver_version --format=csv` output (run once at
      start, never inside the loop) in `config.json`.
- [ ] State in the metadata that the **local GTX 1650 run is the reference**. A later Kaggle T4 run is a
      different configuration, not a replication.
- [ ] Do a second-seed run (`--seed 20260927`) after the first one is reviewed, and report both as a range.

Checkpoint and resume (the driver-hang mitigation):
- [ ] After every epoch, atomically write `last.pt`: write `last.pt.tmp`, then `os.replace`.
- [ ] Also keep `ckpt_epoch_{e:02d}.pt`. These are small (about 6 MB each), so keep all of them.
- [ ] The checkpoint holds:
      - model, optimizer (AdamW) and scheduler (cosine) state;
      - epoch, `history` and `best` (score, epoch, state);
      - `sampler_gen.get_state()` and `loader_gen.get_state()`;
      - `torch.get_rng_state()`, `torch.cuda.get_rng_state_all()`, and the numpy and python RNG states;
      - the config hash, core sha256, split-manifest sha256 and cache key;
      - the device name.
- [ ] `--resume RUN_DIR` loads `last.pt`. It asserts that every hash and the device type match (a GPU run
      never resumes on CPU or the reverse), restores all RNG/generator states, and continues at `epoch + 1`.
      The `train.log` gets a `RESUMED at epoch N` line.
- [ ] Flush `train.log` after every epoch line, with `print(..., flush=True)` or `logging` with a file
      handler.
- [ ] Temperatures, thresholds, eval and export run in a separate `--phase eval` that loads the `best` state.
      A hang during eval therefore never costs training.

Smoke tests, in this order, each must pass before the next:
- [ ] S1: `--smoke` end-to-end on CPU (`CK_FORCE_CPU=1`), which exercises every phase.
- [ ] S2: `--smoke` on GPU, twice. The two `clef_key_history.json` files must be **identical**, and the final
      weights bitwise-equal (or `allclose(atol=0)` on the logits of the parity fixture).
- [ ] S3: resume test on GPU. Run a 2-epoch smoke straight through. Then run a second smoke, kill it after
      epoch 1 (or use a `--stop-after-epoch 1` flag), and resume it. The final weights and history must equal
      the straight run. **This is the acceptance test for resume. Do not start the full run until it passes.**
- [ ] S4: open `preview_inputs.png` and `preview_synthetic_systems.png` and check the crop geometry (staff
      centred, clef not cut off), as in notebook Step 13.

Full run and expected cost (estimates; the smoke run's per-phase timings replace them):

| Phase | Estimate |
|---|---|
| prepare-ds2 | 5-10 min with 8 processes (about 1700 pages); about 30 min single-process |
| prepare-synth | 5-10 min with 8 processes (3000 Verovio + resvg renders) |
| Training | CPU-bound augmentation at about 3-6 ms per sample, about 18k samples per epoch, so about 1-2 min per epoch; 24 epochs is about 40-70 min |
| Eval (+ stress copies) | about 5 min |
| Peak RAM | about 3 GB during the JSON parse, about 2-3 GB during training (memmaps) |
| Disk | about 2 GB of cache plus about 150 MB per run |

Operating the run:
- Close GPU-heavy apps (browser hardware acceleration, games) during the run.
- Do not edit Windows TDR settings.
- If `nvidia-smi` hangs again: restart the PC, then `--resume`.

Real-set check (a separate script, run once after the run is frozen and reviewed):
- [ ] `training/eval_clef_key_realval.py` runs Stage 1 (`keep_unmasked=True`) + Stage 2 geometry on the
      Dormi and Livin' photos (and Flashlight, if the user approves B.3). It builds inputs with
      `clef_key_core.make_input()`, compares them with `labels.json`, and writes
      `training\clef_key_artifacts\<run_id>\realval_metrics.json`.
- [ ] Report per piece and pooled: n, coverage (`no_staff_geometry` rate), clef/key accuracy-when-sure with
      Wilson and a page-cluster bootstrap interval, confident-wrong count and rate, AUROC (or "not estimable,
      k wrong"), the G8vb recall and G-to-G8vb rate, and the per-key-value table.
- [ ] `train_clef_key.py` never reads anything under `piyanota_dataset`. The real-set script never writes
      thresholds or temperatures back into the checkpoint. If the A.4 fallback is ever triggered, it writes a
      **new** file named `..._realfit.pt`, with the fold results recorded in it.

#### D.2 Changes to the plan and notebook because of A-C

1. Section 4 table: the "real-capture validation" row is now Dormi + Livin' (+ Flashlight if approved),
   check-only. The MuseScore print-and-photograph set becomes "needed to prove the gate if the two-piece result
   is 'not proven', and to cover F-on-Tenor, `other` and keys with 5-7 accidentals".
2. Section 4 sizing sentence: corrected by A.2 (about 250-300 sure staves, not about 200).
3. Section 4 "split it 50/50 by page into fit/check": replaced by A.4 (check-only, with a leave-one-piece-out
   fallback).
4. Go criteria: amended by A.5 (AUROC applies only with >= 10 errors, "not proven" when n < 125, scope of the
   license, label adjudication, deployment-path crops).
5. Section 3.2 (mid-strip key changes): replaced by C.2 (the header-comparison `key_plan`; `mid_keysig`
   disabled when a plan is given; naturals recognised in bursts). Section 3.2 (mid-strip clef tokens): kept as
   ignored, plus the C.2 clef-change flag.
6. Notebook/script:
   - add the pencil-stroke augmentation (A.6, disclosed);
   - convert to `train_clef_key.py` per D.1;
   - leave everything else (crop spec, classes, splits, targets, selection rule) unchanged, so `CROP_SPEC_VERSION`
     stays 1.
7. The `g8vb_reliable` gate may now use the pooled real set, if it has **>= 30 real G8vb** (about 45 expected,
   about 67 with Flashlight). It uses the same thresholds (recall >= 0.95, G-to-G8vb <= 2%), and the evidence
   is reported per piece.

### 2026-09-26 user decision: Flashlight retired as a test piece

- The user approved: Flashlight (pg01-08) is **retired as a test piece** and added to the clef/key classifier **validation** set (check-only, never training), alongside Dormi Jesu and Livin' on a Prayer.
- Any earlier Flashlight numbers or ground truth (`data/eval_flashlight/`, partial, abandoned) are history only and must not be cited as test results.
- The Honneur à Toi test report must disclose that Flashlight's engraving family was seen during validation.
- Labels are stored separately in `data/val_clefkey/labels_flashlight.json`, so the frozen `labels.json` (Dormi + Livin', 188 staves, sha256 in `labels.sha256`) stays unchanged.

## 2026-09-27 review of local training code (ml-cv-lead)

Reviewed at commit 9cde6fa, against part (d), D.2 and the Flashlight note above:

- `training/train_clef_key.py` (port of `training/piyanota-clef-keysig-kaggle.ipynb`)
- `clef_key_core.py` (sha256 ad507cd1...)
- `training/eval_clef_key_realval.py` (not yet run)

No training was run. One CPU timing probe was attempted; see the GPU section.

**Verdict: conditional GO for one full local CPU run, after fixes R1-R6. The local CPU run becomes the reference configuration.** This replaces two statements in D.1: that the local GTX 1650 run is the reference, and the 40-70 min time estimate.

### Port faithfulness and leakage

- **Port matches the notebook.** A function-by-function diff against the notebook shows only mechanical changes: type hints, the seed passed as an argument, and a `data` object instead of globals. The logic that matters is identical:
  - the piece-level sha1 split (70/15/15, gonville font test-only)
  - sampler weights
  - the val_score rule for picking the best epoch
  - per-class thresholds (max over val sources)
  - the logic that sets `g8vb_reliable`
- **Leakage guards are sound.**
  - `guard_paths` (train_clef_key.py:279-287) refuses any path under piyanota_dataset.
  - Only `--ds2` and generated synthetic data are read.
  - Temperature and selective thresholds are fitted on `Data.VAL_SETS` only, that is, val_ds2 and val_synth (1477-1536).
  - The real-validation photos are never touched by the training script.
- **Solo labels.** The "Soloist" and "Solo" entries in `SYNTH_LABELS` come from the notebook and are already disclosed in section 5.
- **Hash coupling (medium).** `run_hashes` (1301-1304) includes the training script's own sha256. `load_best_model` (1425-1444) and the eval both check it. Any edit to the script after training, even to eval-only code, blocks calibrate and eval for that run. All code must therefore be frozen before the run (R4).
- **Resume (low).** Resume (1354-1372) correctly refuses on a hash or device-type mismatch. The only issue is that the check runs after `load_data`, so a refused resume first rebuilds the cache for nothing.
- **Checkpoint names (cosmetic).** Files are named `epoch_NNN.pt`, not the spec's `ckpt_epoch_NN.pt`.

### Required fixes before the run (ranked)

- **R1 (high): make `--device` required, with no CUDA probe.** Today it defaults via `torch.cuda.is_available()` (train_clef_key.py:1766). That call initialises the NVIDIA driver even for a CPU run, and hangs when the driver is wedged.
- **R2 (high): pin and record the CPU thread count.** `torch.set_num_threads` is neither set nor recorded, and CPU float reductions can depend on the thread count. Pin it (for example 6), write it into the config and the run hash, and assert it on resume.
- **R3 (medium): update the reference wording.** The checkpoint `reference_note` (1728-1730) calls a CPU run "not the reference configuration". Change it, and amend the matching D.1 line.
- **R4 (medium): freeze all three files before the run.** This follows from the hash coupling above, and includes any E1-E4 changes that touch `train_clef_key.py`.
- **R5 (high, environment): reboot, and keep the NVIDIA driver out of the run.** Use a separate venv with the CPU-only wheel (`torch==2.6.0+cpu`), or disable the NVIDIA adapter in Device Manager for the whole run. On the cu124 wheel, a pure-CPU backward pass stalled while the driver was wedged, even with `CUDA_VISIBLE_DEVICES=""`.
- **R6 (medium): redo the smoke checks.** Re-run S1 twice (outputs must be byte-identical) and S3 (resume) on the final code and environment. The earlier smoke passes used the cu124 wheel and pre-fix code.

### Pencil-stroke augmentation (D.2.6)

Acceptable as disclosed, with conditions.

**What it does** (train_clef_key.py:184-195, 788-806, 813-814):

- It runs first in the photometric chain, with p=0.3.
- It draws 1-3 cubic Béziers, 1-3 px thick at 12 px per staff space (about 0.08-0.25 spaces), in grey 30-170.
- Strokes are drawn on the stored crop (4 spaces left, 19 right, 7 above and below). The network sees only about 46% of that area, so the effective exposure is well under 0.3. Do not describe it as "30% of samples".

**Conditions:**

- (a) Freeze its parameters now. Never retune them after any real-set result is seen.
- (b) The real-set report must restate that this augmentation was added after pencil marks were seen in real-validation photos. That is design-level exposure to the validation set, not a data leak.
- (c) The stress sets also include pencil strokes (`_stress_one`, 911-913). Disclose that their numbers are not comparable to the notebook's.
- (d) The Kaggle notebook has no pencil augmentation, so it no longer mirrors the local script.

### Eval: bbox mapping and go-criteria

**Bbox mapping** (eval_clef_key_realval.py:246-280, 344-376) is acceptable for the gate decision. Stage 1 does not need to expose its transform first.

- The eval re-derives the downscale and perspective steps by calling the private `s1._correct_perspective`. It does not invert dewarp or rotation. Labels are matched to crops by vertical IoU ≥ 0.3.
- This is acceptable because the crop geometry comes from Stage 1's own tracked bands, the same path as deployment. A mapping error can only attach a label to the wrong staff. That appears as an error, which adjudication (A.5.4) catches; it cannot produce a false pass.

**Required before any scoring:**

- **E1: residual check.** Today it only warns when the median residual exceeds 1 staff spacing. Replace the warning with:
  - a per-staff exclusion, with the excluded count reported;
  - a hard fail above a threshold fixed in advance.
- **E2: rotation audit.** Audit results per page rotation angle. On rotated pages that are not dewarped, Stage 1 does not rotate the band rows, and deployment behaves the same way. Decide in advance whether those pages count, so geometry errors are neither blamed on the classifier nor hidden.
- **E3: report both clef modes, plus coverage.**
  - Report exact 4-class and G/G8vb-collapsed results side by side.
  - Report coverage (n_sure / n_labelled) next to the verdict.
  - Today the eval reports only the mode set by the checkpoint's `g8vb_reliable`. `collapse()` (493-494, 511) scores correctness at family level, but the sure/unsure decision still uses the 4-class max probability.
  - That follows rule 1 of section 3.3 literally and costs coverage. Keep it, but show both modes, because D.2.7 and A.4 are ambiguous on this point.
- **E4: coverage dry run.** Before the real scoring, run Stage 1/2 only, with a smoke checkpoint and no scoring of the real classifier.
  - Why: Dormi pages that contain a 5-staff system currently become whole-page `pipeline_miss`. That lowers sure-n, and not at random.
  - This shows whether n_sure ≥ 125 is reachable before the one-shot scoring is spent.

**Checked and correct:**

- The verdict is "not proven" when n_sure < 125 (472-487).
- AUROC is gated at ≥ 10 wrong answers, and otherwise deferred to the stress sets (466-468).
- Confident-wrong rate is cw / n_scored.
- The page-cluster bootstrap (429-447) excludes pg10_b from the gate and scores it as a separate consistency block.
- `load_frozen` checks the core sha.
- With zero errors the bootstrap interval collapses to [1, 1]. In that case, rely on the Wilson bound.

### GPU, reference configuration and CPU time

**The GPU is unreliable. Agreed.** The evidence:

- S2 CUDA epoch-2 losses of 3.9439, 3.9457 and 3.9432, despite deterministic flags
- outputs of 2.1e+35
- hangs on 2026-09-23 and 2026-09-26
- today's probe

**Today's probe:**

- Setup: `CUDA_VISIBLE_DEVICES=""`, cu124 wheel, 6 threads on 6 physical / 12 logical cores, the real `ClefKeyNet` (1,382,195 params), batch 128.
- The forward pass completed in 2.78 s (cold). The backward pass then stalled permanently.
- An earlier probe called `torch.cuda.is_available()` and hung. That was the reviewer's mistake.
- Two python processes (PIDs 22156 and 30260) could not be killed and will be cleared by the R5 reboot.
- Likely cause: on the first backward pass, autograd queries the CUDA device count, which touches the wedged driver. This is why R5 is needed.

**Local CPU is the reference.**

- It is deterministic (the S1 rerun was byte-identical), and resume is proven (S3).
- It is the same machine and code path the eval uses.
- A Kaggle run cannot be the reference:
  - the notebook has no pencil augmentation;
  - its core sha differs (d1f10181...), so `load_frozen` refuses its checkpoint;
  - a T4 is a different numeric configuration.
- Kaggle is at most an optional cross-check. Its numbers are never reported as the result.

**CPU time estimate:**

- Compute per step: about 0.51 G MAC per sample forward, so about 390 GFLOP per forward+backward step at batch 128. A warm step takes about 3-5 s.
- One epoch takes about 9-16 min:
  - about 140-200 steps (18k training rows, up to 26k)
  - about 1.5-3 min of serial augmentation (num_workers=0)
  - about 0.5 min of validation
- 24 epochs take about 3.6-6.5 h, or up to about 9 h at 26k rows. Add 10-20 min for prep and 5-10 min for calibrate and stress sets.
- **Plan for 4-8 h, central estimate 5-6 h.** The backward pass was never actually timed, so treat this as ±50%.

### Command (after R1-R6)

```
python training\train_clef_key.py --ds2 D:\PiyaNota\datasets\ds2_dense --seed 20260926 --device cpu --phase all
```

- To resume: `--resume <run_dir> --device cpu --phase all`.
- The second seed (20260927) runs only after the first run's validation results have been reviewed.
- The real-validation eval (with E1-E4 in place) runs exactly once, on the frozen, selected checkpoint.
