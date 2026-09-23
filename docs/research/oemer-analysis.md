# oemer — Technical Analysis

Source: [meteo-team/oemer](https://github.com/meteo-team/oemer), cloned read-only for this research
into `C:\Users\paul_\.claude\jobs\40c89960\tmp\repos\oemer`. The repo's README states it "is no longer
maintained" and points to a successor fork (`BreezeWhite/oemer`); this analysis covers only the
meteo-team clone actually inspected, not the fork.

## Overview

oemer is an end-to-end OMR system that converts a photo/scan of a music score into a MusicXML file.
Unlike PiyaNota's CRNN-CTC sequence-transcription approach, oemer is built on **image semantic
segmentation + rule-based symbolic reconstruction**: two U-Net-style segmentation models classify
every pixel of the page into staff/symbol categories, and a long chain of deterministic, hand-written
geometric/heuristic algorithms (peak-finding, bounding-box morphology, distance thresholds, SVM
classifiers for small crops) turns those pixel maps into typed musical objects (`Staff`, `NoteHead`,
`Clef`, `Barline`, `Rest`, ...), which are finally assembled into a single MusicXML `<part>`.

The CLI entry point is `oemer.ete:main` (`setup.py` `entry_points`), and the full pipeline is laid
out linearly in `oemer/ete.py::extract()`. Default inference backend is ONNX Runtime
(`onnxruntime-gpu`); TensorFlow inference is available as a fallback via
`export INFERENCE_WITH_TF=true`.

## Architecture (Pipeline Stages)

`oemer/ete.py::extract()` chains the stages below, matching the README's own "Technical Details"
section:

1. **Model prediction** (`generate_pred()` in `ete.py`) — two independent segmentation models are
   run over the raw image via `oemer.inference.inference()`:
   - `checkpoints/unet_big` — a binary-ish staff/symbol map: class 1 = stafflines, class 2 = all other
     symbols combined (`staff_symbols_map`).
   - `checkpoints/seg_net` — a finer 3-channel split: class 1 = stems/rests, class 2 = noteheads,
     class 3 = clefs/keys/accidentals (`stems_rests`, `notehead`, `clefs_keys`).
   Both models are shipped as **pretrained ONNX graphs** (`oemer/checkpoints/unet_big/model.onnx`,
   `oemer/checkpoints/seg_net/model.onnx`), each with a companion Keras `arch.json` + `weights.h5`
   (for the TF fallback path) and a `metadata.pkl` (input/output shapes, output tensor names) that
   `oemer/inference.py::inference()` reads to drive `onnxruntime.InferenceSession`.
   - Architecture: `oemer/models/unet.py::semantic_segmentation()` is an "Improved U-Net with Atrous
     Spatial Pyramid Pooling (ASPP)" — a ResNet-style encoder (`conv_block`, strided `Conv2D` + skip
     `Add`), a multi-grid dilated-convolution bottleneck (`multi_grid_layer_n`, dilation rates
     `2**ii`), and a symmetric transposed-conv decoder with encoder skip connections
     (`transpose_conv_block`). A second, unused-by-default architecture (`u_net()`) is also defined
     in the same file with a DeepLab-style ASPP bottleneck (parallel dilated `SeparableConv2D` at
     rates 1/2/6/12) — `train_model()` in `oemer/train.py` calls `semantic_segmentation()`, not
     `u_net()`. `oemer/models/naive_conv.py` also exists as a simpler baseline, unused in the shipped
     pipeline.
   - Inference is patch-based: the model has a fixed window size (`win_size`, taken from
     `input_shape[1]`), and `inference()` slides a `step_size=128` px window with overlap-averaging
     (`out /= mask`) over the (resized) full page, then `np.argmax` (or per-channel manual thresholds,
     `symbol_thresholds = [0.5, 0.4, 0.4]` in `generate_pred()`) collapses the softmax output to a
     class map.
   - This is a genuinely different modeling paradigm from PiyaNota's Stage 3: pixel-wise dense
     classification over a whole page, not a sequence model reading a cropped single-staff strip
     token-by-token.

2. **Dewarping** (`oemer/dewarp.py`) — a 6-step curve-correction (README: "Steps to dewarp the curved
   image"): `build_grid()` buckets the staffline pixel mask into small (`split_unit=11`px) on/off
   vertical strips, `build_grid_group()` labels contiguous strip-runs via
   `scipy.ndimage.label` into `GridGroup`s (roughly: one physical staff-line segment), and
   `connect_nearby_grid_group()` bridges runs interrupted by symbols/noise using a locally-fit
   `LinearRegression` trajectory. `build_mapping()` + `griddata` turn the recovered staffline
   y-positions into a dense per-pixel remap field (`coords_x`, `coords_y`), and `dewarp()` applies it
   via `cv2.remap(..., cv2.INTER_CUBIC)`. Critically, **the same warp field is applied to all five
   prediction/image layers** (`ete.py::extract()`: staff, symbols, stems_rests, clefs_keys, notehead,
   and each RGB channel of the original image) so everything stays pixel-aligned after correction.
   This handles genuine *curvature* (e.g. a photographed book page bowing near the spine), not just
   rotation.

3. **Staffline extraction** (`oemer/staffline_extraction.py::extract()`) — splits the page into
   `splits=8` vertical zones (`init_zones()`), and in each zone finds staffline y-positions by
   summing positive pixels per row and running `scipy.signal.find_peaks` on the normalized profile
   (`extract_line()`), with `filter_line_peaks()` discarding incomplete/over-long runs of 5. Adjacent
   zones are stitched and gap-filled/interpolated (`align_staffs()`) so a staff whose zone dropped a
   line (occlusion, noise) is reconstructed from its neighbors (`Staff.is_interp` flag records this).
   The critical derived quantity is `unit_size` (mean staffline gap), which every later stage's
   distance/size thresholds are expressed as a multiple of (`NoteHeadConstant` ratios in
   `oemer/constant.py`, e.g. `CLEF_WIDTH_UNIT_RATIO = 3.2173913`).

   **Track/group assignment — the system-grouping logic** lives here, in
   `further_infer_track_nums()`: it subtracts already-known stems/noteheads/clefs from the symbol
   layer, finds remaining near-vertical line segments (candidate barlines) via `bbox.find_lines()`,
   filters them by angle/position (`filter_lines()`, `min_degree=75`), and measures their height in
   `unit_size` multiples. A barline spanning multiple staff heights implies those staves are grouped
   under one system (e.g., a piano's connected treble+bass staff). The result is a **single global
   `num_track` integer for the whole page** (loop `for i in range(1, 10)` in
   `further_infer_track_nums()`), then every staff gets `st.track = idx % num_track`,
   `st.group = idx // num_track` — i.e. tracks cycle within each group in strict top-to-bottom
   order, uniformly across the whole page. See **Relevance to SATB Choral OMR** below for why this
   specific piece of code is the crux of adapting oemer to open-score choral layouts.

4. **Notehead extraction** (`oemer/notehead_extraction.py`) — morphs the noteheads channel
   (`morph_notehead()`, elliptical erode+dilate), finds bounding boxes, and uses `unit_size` to
   split boxes that likely contain more than one overlapping notehead. Half vs. whole notes (both
   rendered "solid" by the model on purpose, per the README, so morphology doesn't erase them) are
   disambiguated by region coverage ratio against the raw image. Each `NoteHead` gets a
   `staff_line_pos` (integer stafflines/spaces offset from a clef-dependent reference: D4 for treble,
   F3 for bass) plus `track`/`group` inherited from its nearest `Staff`.

5. **Note group extraction** (`oemer/note_group_extraction.py`) — clusters noteheads that share a
   stem/beat into chords (`NoteGroup`), first by vertical/horizontal proximity, then refined by
   parsed stem direction. Notably, **oemer explicitly supports two simultaneous melodic lines within
   one staff** (e.g. soprano+alto sharing one treble staff in closed-score piano writing, one
   stem-up "voice 1" and one stem-down "voice 2") — this is the MusicXML `<voice>` concept, resolved
   in `build_system.py::get_voices()` (`if group.stem_up is None and group.has_stem:` splits a group
   into `top_note_ids`/`bottom_note_ids`). This "voice" is *polyphonic-line-within-a-staff*, unrelated
   to PiyaNota's SATB = four separate staves/parts.

6. **Symbol extraction** (`oemer/symbol_extraction.py`) — clefs and sharp/flat/natural (SFN) glyphs
   are first told apart from each other by size/coverage-rate rules, then classified into concrete
   subtypes (`gclef`, `fclef`, `sharp`, ...) by pretrained **scikit-learn SVM models**
   (`oemer/sklearn_models/clef.model`, `clef_sfn.model`, `sfn.model`, `rests.model`,
   `rests_above8.model`, pickled `{model, w, h, class_map}` dicts loaded by
   `oemer/inference.py::predict()`). Barlines are extracted by cross-referencing both segmentation
   models' outputs (the stems/rests channel under-predicts barline length due to a training-data
   artifact noted directly in the README; the staff/symbol model's raw prediction is used to recover
   true length). Rests are also SVM-classified crops.

7. **Rhythm extraction** (`oemer/rhythm_extraction.py`, 646 lines — the largest single module,
   and per the README "probably the most time consuming part except for the model inference") —
   parses augmentation dots via small-region pixel-density scans near each notehead, then
   beams/flags via a multi-pass overlap-and-refine procedure against note groups, ultimately
   assigning a `NoteType` (whole/half/quarter/.../64th) to each `Voice`/`NoteGroup` and, when needed,
   **splitting a note group into upper/lower parts post hoc** once rhythm evidence disambiguates a
   two-voice staff that looked like one group.

8. **MusicXML construction** (`oemer/build_system.py::MusicXMLBuilder`) — an event/"Action" model
   (`ClefChange`, `KeyChange`, `AddNote`, `AddRest`, `AddBackup`, `AddForward`, ...), each with a
   `perform()` that appends XML elements while mutating a shared `Action.Context` (current key, per-
   track clef, per-pitch-class accidental state — i.e. a small classical key-signature/accidental
   state machine, conceptually similar to PiyaNota's `infer_pitch()` state machine but operating over
   *segmented+reconstructed* symbol objects rather than a CTC-decoded token stream). Symbols are
   grouped by `group` then sorted by x-position into `Measure`s at each `Barline` (`gen_measures()`).
   Key-signature inference (`Measure.get_key()`) counts leading `Sfn` occurrences per track with a
   sharp/flat/natural voting scheme; rhythm across tracks is reconciled by
   `Measure.align_symbols()`, which contains **`assert track_nums == 2, track_nums`** — see below,
   this is a hard structural ceiling on the whole rhythm-alignment algorithm.

## Input/Output Representation

- **Input**: a single raster image path (JPG/PNG), handled per-call — no batch/PDF handling in
  `ete.py`; `resize_image()` targets ~3–4.35 megapixels before inference.
- **Output**: one `.musicxml` file per input image (`extract()` in `ete.py` writes
  `<basename>.musicxml`), built by `MusicXMLBuilder.to_musicxml()`. MusicXML 4.0 `score-partwise`
  with **a single hardcoded `<part id="P1">`**, and `build_part_list()` (`oemer/build_system.py`)
  literally sets `part-name = "Piano"`, `instrument-name = "Piano"`,
  `instrument-sound = "keyboard.piano"`, `midi-program = 1`. Multiple staves within that one part are
  expressed via MusicXML's `<staff>` element on each `<note>`/`<rest>` (`note.track + 1`), and MIDI
  playback is not part of oemer's own output — a downstream MusicXML renderer (e.g. MuseScore) is
  assumed. There is no separate audio-rendering stage: `audio/` in the repo root contains only a
  single demo file, `audio/tabi.mp4` (a screen-capture/demo video referenced from the README), not
  code. oemer therefore does not overlap at all with PiyaNota's Stage 5 (MIDI→WAV→MP3 via
  FluidSynth); it stops at the notated-score representation.
- Internal representation is a `layers` registry (`oemer/layers.py`, not fully read but used
  pervasively via `layers.register_layer()`/`layers.get_layer()`) holding named 2D arrays (pixel
  maps) and object arrays (`staffs`, `notes`, `note_groups`, `barlines`, `clefs`, `sfns`, `rests`) —
  essentially a shared mutable blackboard that every stage function reads from and writes back into,
  rather than PiyaNota's explicit `{"Soprano": [...], ...}` per-voice event-list handoff between
  stage scripts.

## Training Approach & Data Requirements

Training code **is present** in this clone, contrary to the possibility flagged in the task — but it
is clearly a secondary, less-maintained path relative to the packaged inference CLI:

- `oemer/train.py` — `train_model()` trains the `semantic_segmentation()` U-Net (imports
  `from .models.unet import semantic_segmentation, u_net`) against **DeepScoresV2**
  (`get_deep_score_data_paths()`, expects `dataset_path/images/*.png` +
  `dataset_path/segmentation/*_seg.png`) via a custom multiprocess `DsDataLoader` that does random
  resize + `imaugs.perspective_transform` (from Facebook's `augly` library) augmentation and yields
  fixed `win_size=288` patches. A second loader, `get_cvc_data_paths()`, targets **CVC-MUSCIMA**
  (a handwritten/distortion staffline benchmark: `curvature`, `kanungo`, `rotated`,
  `staffline-thickness-variation`, etc. subfolders), used by the older `DataLoader` class (commented
  out in `train_model()` — the DeepScoresV2 path is what actually runs by default).
  Loss is `0.4·SigmoidFocalCrossEntropy + 0.6·(focal Tversky)` (`focal_tversky_loss()`), optimizer
  Adam with a custom `WarmUpLearningRate` schedule; training uses `tf.keras.callbacks.EarlyStopping`
  / `ModelCheckpoint` on `val_accuracy`.
  `oemer/classifier.py` (275 lines) separately trains/grid-searches the small SVM classifiers
  (`SVM_PARAM_GRID`, plus KNN/AdaBoost/RandomForest/GradientBoosting/Ridge/Bagging alternates
  imported but not obviously wired into a single chosen pipeline in the portion read) used for
  clef/SFN/rest sub-classification.
- **Not wired into the packaged install**: `setup.py`'s `install_requires` covers only inference
  (`onnxruntime-gpu`, `opencv-python`, `numpy`, `scipy`, `scikit-learn`, ...) plus an `extras_require
  = {'full': ['tensorflow-gpu', 'tf2onnx']}` for the TF-inference fallback. `train.py` and
  `classifier.py` both `import tensorflow_addons as tfa` and `import augly.image as imaugs`, and
  **neither package is declared anywhere in `setup.py`** — a fresh `pip install Oemer` or
  `python setup.py install` will not give you a runnable training environment; training requires
  manually reconstructing that dependency set. There is also `oemer/convert_to_onnx.py` (not fully
  inspected) presumably for turning a freshly trained Keras checkpoint back into the `.onnx` +
  `metadata.pkl` format the inference path expects.
- **Conclusion**: training code exists and looks real (loss function, LR schedule, data loaders,
  early stopping — not a stub), but this is best read as "the authors' internal training scripts
  were open-sourced alongside the product," not "this repo is a maintained training framework." No
  requirements.txt/pinned training environment, no training README section, no CI job exercises
  `train.py`, and the repo's own top line says it's unmaintained. Reproducing oemer's shipped
  checkpoints from scratch would require non-trivial environment archaeology.

## Strengths

- **Robust, well-motivated geometric reconstruction.** Steps like `align_staffs()` gap-filling
  incomplete/occluded staff detections by interpolating from neighboring zones, or
  `filter_line_peaks()` discarding degenerate < 5 or > 5 line runs, show real engineering against
  imperfect segmentation output rather than assuming the model is always right.
  - Direct **dewarping for physical page curvature** (`oemer/dewarp.py`), not just deskew/rotation —
    a materially harder problem than PiyaNota's Stage 1 (`correct_to_grid()` rotation-only deskew via
    staffline+barline Hough-line averaging). oemer's grid-based local remap can, in principle, correct
    a photographed book's page-bowing near the spine; PiyaNota's approach cannot.
- **Interpretable, debuggable intermediate state.** Every stage produces typed, inspectable Python
  objects (`Staff`, `NoteHead`, `Clef`, ...) with human-readable `__repr__`s (shown throughout the
  README), and the `layers` registry means any intermediate pixel map or object list can be dumped
  and visualized. Failure at any stage is traceable to a specific geometric rule, not an opaque
  hidden state in an RNN.
- **No end-to-end sequence-labeling domain gap for *layout* elements.** Because staffline/symbol
  detection is per-pixel segmentation over the whole page rather than classification of a pre-cropped
  fixed-height strip, oemer is less brittle to some kinds of variation PiyaNota's CRNN strip pipeline
  is sensitive to (e.g., overall page scale/rotation within reason, since `unit_size` is measured
  locally, not assumed from a fixed input height).
- Barline-driven **system/group + track inference** (`further_infer_track_nums()`) is a genuinely
  data-driven (not hardcoded) way of discovering how many staves are connected per system, which is
  more general than a fixed "always assume N staves per system" rule — as far as it goes (see
  Limitations).

## Limitations

- **Deeply baked-in 1–2-track (piano/orchestral, single-or-double-staff) assumption.**
  `Measure.align_symbols()` in `build_system.py` literally does:
  `assert track_nums == 2, track_nums` (with a `track_nums == 1` early-return path above it) — any
  page for which `get_total_track_nums()` (the global, page-wide unique-track-count derived in
  `staffline_extraction.py`) returns 3 or more **hard-crashes** the whole reconstruction. This is not
  a soft heuristic; it is a hard-coded structural ceiling.
- **Single global track/group count for the entire page.** `further_infer_track_nums()` computes one
  `num_track` and applies `st.track = idx % num_track` / `st.group = idx // num_track` uniformly to
  every staff on the page — there is no per-system override, and `extract()`
  (`oemer/staffline_extraction.py`) raises (`E.StafflineCountInconsistent`,
  `E.StafflineNotAligned`, `E.StafflineUnitSizeInconsistent`) if different zones/rows of the page
  don't agree on staff count, alignment, or unit size within tight tolerances. A page with a mix of
  system sizes (e.g. an SATB choral piece where some systems have a printed piano reduction and
  others don't) would likely fail these consistency checks outright.
- **Output is a single hardcoded "Piano" part.** `build_part_list()` always emits exactly one
  `<score-part id="P1">` named "Piano" with `midi-program = 1`; there is no part-per-voice/instrument
  concept anywhere in `build_system.py`. Multiple staves become `<staff>` numbers *within* that one
  piano part, which is semantically correct for a grand staff but semantically wrong for four
  independent vocal parts.
- **No confidence/uncertainty signal propagated end to end.** Rule thresholds
  (`symbol_thresholds = [0.5, 0.4, 0.4]`, `line_threshold=0.8`, `min_degree=75`, etc.) are fixed
  constants tuned presumably on the training/eval distribution; there's no analogue to inspecting a
  CTC decoder's per-token confidence to flag "this staff/measure is unreliable."
- **Photographed-in-the-wild robustness is unproven here.** The dewarping step is for *curvature*
  (bound-book pages), but there's no explicit illumination-normalization, adaptive-thresholding, or
  lyric-text-blanking step comparable to PiyaNota's Stage 1
  (`blank_lyrics_regions()`/adaptive-threshold binarization) — the pixel-classification burden for
  "ignore lyric text under the staff" or "handle uneven phone-camera lighting" falls entirely on the
  segmentation models' learned generalization, with no rule-based preprocessing safety net for those
  specific failure modes. Given training data is DeepScoresV2 (clean, digitally-typeset,
  engraving-rendered scores) and CVC-MUSCIMA (handwritten, but still scanned, not photographed),
  there is a real chance of a font/engraving/capture-condition domain gap analogous to PiyaNota's
  BUG-011 — just not evidenced one way or the other in this repo, since no held-out real-photo
  evaluation numbers are published here.
- **Training path is undeclared/unmaintained**, per the Training section above — `tensorflow_addons`
  and `augly` are used but never pinned in `setup.py`, and the repo is explicitly unmaintained
  upstream. Retraining or fine-tuning on new data (e.g., different engraving fonts, or a choral
  layout) would require nontrivial environment reconstruction before any modeling work could start.
- **Rhythm/beam extraction is the largest, most heuristic-dense module** (646 lines,
  `rhythm_extraction.py`) and per the README's own admission "probably the most time consuming part
  ... critical for listening experience" — a long chain of overlap/refine/re-group passes is
  inherently harder to unit-test and reason about than a learned sequence decoder, even though each
  individual rule is inspectable.

## Relevance to SATB Choral OMR

This is architecturally the most different design from PiyaNota's current CRNN-CTC approach, and the
difference cuts both ways for the SATB/open-score choral use case.

**Would segmentation sidestep the font/glyph domain gap that plagues PiyaNota's CRNN-CTC (BUG-011)?**
Partially, and only for part of the problem. PiyaNota's CRNN-CTC failure mode (documented in this
repo's own `docs/bug-tracker.md` BUG-011) is a *sequence-classification* collapse — the model
confidently emits the wrong *token* (`clef.C-L3` almost regardless of input) because it never saw
real engraving fonts during training. A segmentation model has a structurally different failure
surface: it classifies *pixels*, and a font/glyph domain gap would show up as noisy/incomplete or
shifted pixel masks for symbol classes (a mis-shaped clef glyph gets partially or wrongly segmented)
rather than a single confidently-wrong discrete label. In principle this could be *less* brittle to
render-domain shift for coarse position/layout facts (where are the stafflines, roughly where is a
notehead) since those are more local, texture-driven cues than "which exact clef glyph is this."
But oemer still leans on the same SVM SVM-classification-of-small-crops step for `clef`/`sfn`/`rest`
fine-grained typing (`oemer/symbol_extraction.py`, `oemer/sklearn_models/*.model`) — those SVMs were
themselves trained on some fixed font/rendering distribution (via `oemer/classifier.py`'s
`collect()`/training flow), so the *symbol-typing* half of the problem (is this a G-clef or F-clef,
sharp or natural) is not obviously immune to the same kind of domain gap that hit PiyaNota's CRNN —
it's just isolated to a smaller, more inspectable sub-model rather than smeared across an entire
CTC-decoded sequence. The honest read: segmentation-based staff/notehead *localization* is plausibly
more robust to font/engraving shift than CRNN-CTC sequence transcription, but *symbol identity*
classification (clef type, accidental type) still depends on a font-sensitive classifier trained on
some fixed rendering distribution, so the domain-gap risk doesn't fully disappear — it moves and
shrinks in scope rather than being eliminated.

**Could oemer's system/part-grouping logic handle 4-voice open-score SATB, and what would it cost to
adapt?** As shipped, no — and the barriers are specific, not vague:

1. `Measure.align_symbols()`'s `assert track_nums == 2, track_nums` in `oemer/build_system.py` would
   need to become a general `track_nums`-way rhythm-alignment loop (the current code special-cases
   exactly two tracks throughout: `new_track_duras = np.zeros((track_duras.shape[0],
   track_duras.shape[1]+2))`, `lead_track` picked between `0`/`1-lead_track`, etc. — this logic is
   written for two tracks specifically, not parameterized over N). Generalizing it to 4 tracks is a
   nontrivial rewrite of the core beat-alignment algorithm, not a config change.
2. `further_infer_track_nums()` in `oemer/staffline_extraction.py` infers track count from **barline
   height spanning multiple staves** — it assumes the visual cue for "these staves are one system" is
   a barline drawn through all of them (true for piano grand staff, true for orchestral score
   brackets). Open-score SATB *does* typically draw one continuous barline through all four vocal
   staves per system, so this specific heuristic might actually transfer reasonably well to detect
   "4 staves per system" — this is the one piece of the grouping logic that's plausibly reusable
   with a few threshold adjustments, not a rewrite (e.g. `barline_min_degree`, `factor=10` step in
   `further_infer_track_nums()`'s h_ratio loop would need re-tuning for 4-staff barline heights, but
   the underlying approach doesn't assume exactly 2).
3. `build_part_list()`'s hardcoded single "Piano" part is a much bigger structural gap for PiyaNota's
   actual downstream need: PiyaNota wants four *independent, separately-playable* voice tracks
   (`{"Soprano": [...], "Alto": [...], ...}`), not four staves nested inside one MusicXML part playing
   through a single piano MIDI program. Producing four separate `<score-part>` elements (one per
   voice, each its own instrument/MIDI channel) instead of one `<part>` with four `<staff>` numbers
   is a rewrite of `build_part_list()` plus every place that currently keys output by `track`
   (`decode_note()`'s `<staff>` element, `decode_rest()`, `Measure.get_track_clef()`) to key by part
   instead — a moderate, well-scoped rewrite (the `track` bookkeeping already exists and is threaded
   consistently through the codebase; it's a re-target, not new plumbing from scratch), but real
   engineering effort, not a flag flip.
4. The Tenor-clef 8vb convention (a plain treble clef visually meaning "one octave down," which
   PiyaNota's `get_clef_reference()`/`TENOR_CLEF_REFERENCE` special-cases per-voice) has **no
   analogue anywhere in oemer** — `oemer/symbol_extraction.py`'s clef classification only
   distinguishes glyph shape (`ClefType.G_CLEF`/`F_CLEF` per the grep for clef types), with no
   voice-identity or octave-transposition concept at all. This would need to be added from scratch,
   the same as it was for PiyaNota — segmentation-vs-CRNN doesn't help here, since it's a
   music-semantic disambiguation problem (visually identical glyph, different meaning depending on
   which staff/voice it's on), not a recognition problem either architecture solves for free.
5. Every consistency check in `staffline_extraction.py::extract()`
   (`StafflineCountInconsistent`, `StafflineNotAligned`, `StafflineUnitSizeInconsistent`) assumes
   *uniform* staff structure across the whole page (same staff count, same unit size, same alignment
   in every zone). Real SATB octavo pages are usually structurally uniform system-to-system (this
   actually matches oemer's assumption reasonably well, arguably better than a mixed
   piano-vocal-score page would), but any layout irregularity (a printed piano reduction on some
   systems, a divisi extra staff, differing systems-per-page counts) would trip these checks the same
   way it would trip PiyaNota's "all four SATB voices must be present" hard requirement in
   `stage4_reconstruction.py`.

**Net assessment.** oemer's barline-driven system-grouping heuristic is closer to "adapt" than
"rewrite" for open-score SATB specifically, because SATB choral engraving conventions (one barline
through all staves in a system) happen to match the visual cue oemer already keys off of. But the
two-track-hardcoded rhythm-alignment algorithm and the single-piano-part MusicXML output are real
architectural barriers requiring nontrivial rewrites, not configuration. And the Tenor 8vb problem —
arguably the single most SATB-specific piece of domain logic PiyaNota had to build — has no
counterpart in oemer at all and would need to be built from scratch regardless of which base
architecture (CRNN-CTC or segmentation+reconstruction) PiyaNota ultimately uses. Architecturally,
segmentation + rule-based reconstruction trades PiyaNota's current failure mode (a black-box sequence
model confidently hallucinating tokens, hard to debug, per BUG-011) for a different one: many
independent, individually-inspectable-but-collectively-fragile geometric assumptions (`assert
track_nums == 2` being the sharpest example) that are easier to *locate* when they break but require
real reconstruction-logic engineering — not just retraining — to *fix* for a domain the original
authors never targeted.
