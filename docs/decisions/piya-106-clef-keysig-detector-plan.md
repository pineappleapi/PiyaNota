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
