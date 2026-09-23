# OMR Approach Comparison: TrOMR vs. CRNN-CTC (PRAIG) vs. oemer vs. PiyaNota

**Status:** Research, not a decision doc. Feeds into PIYA-106 AC4 / BUG-011 (real-world font/glyph
domain gap — see `docs/decisions/piya-106-crnn-font-retraining-plan.md`, currently mid-execution:
Step 2 fine-tuning substantively done but not formally closed, Step 3 fresh real-world test set not
yet started). Written 2026-09-23. Individual deep-dives: `tromr-analysis.md`,
`crnn-ctc-praig-analysis.md`, `oemer-analysis.md` (this repo, same directory) — this document
synthesizes those three against PiyaNota's own Stage 2/3 pipeline and asks the question the user
actually posed: can PiyaNota make CRNN-CTC transcription work, or does it need a different approach.

## The question, restated precisely

BUG-011 is not "the CRNN is a bad architecture." It's: a CRNN-CTC trained on exactly one synthetic
rendering font (CameraPrIMuS) collapses on real engraving-software output — clef recognition 2/48 on
real phone-screenshot strips, confidently wrong, with non-clef tokens also badly wrong (hallucinated
note/rhythm clusters, phantom accidentals). Nothing image-preprocessing-only has fixed it (BUG-011's
own falsified attempts: thresholding, dilation, erosion). The open question this research answers:
do any of these three external projects show that the *architecture family* (CRNN-CTC) is the actual
bottleneck — such that switching to something like TrOMR's transformer decoder or oemer's segmentation
pipeline would fix what font-retraining alone can't — or is the bottleneck purely *training data
diversity*, in which case PiyaNota's already-in-flight PIYA-106 plan is the right fix and doesn't need
an architecture change.

## Side-by-side

| | **PiyaNota (current)** | **TrOMR** | **CRNN-CTC (PRAIG)** | **oemer** |
|---|---|---|---|---|
| Core approach | CNN (ResNet-style) → 2-layer BiLSTM → CTC | CNN (ResNetV2) → ViT encoder → causal transformer decoder (4 parallel streams) | CNN (plain 4-block, no skip connections) → 2-layer BiLSTM → CTC | Two U-Net/ASPP segmentation models → rule-based reconstruction; small SVMs for symbol typing |
| Output representation | Agnostic tokens + staff-position suffix (`note.quarter-L4`), resolved to absolute pitch by a separate 5-state `infer_pitch()` state machine | Absolute pitch tokens directly (`note-C4` + lift token), no separate pitch-resolution pass | Dataset-agnostic custom alphabet (shape+position tokens), configurable per corpus | MusicXML directly, via pixel maps + rules, no learned token sequence at all |
| Per-staff or multi-staff | Per-strip (one voice's staff at a time) — matches PiyaNota's own crop-per-voice design | Single-staff only, explicitly ("Inference single staff image") | Single-image/line at a time (dataset-agnostic, no multi-staff assumption baked in) | Whole-page, multi-staff, but **hardcoded to piano's 2-track grand staff** (`assert track_nums == 2`, single hardcoded `"Piano"` MusicXML part) |
| Polyphony / chords | Not handled (monophonic per-voice line, matches SATB's one-note-per-voice-at-a-time reality) | Handled within one staff (`|`/`+`-joined token groups) | Not evidenced (single-symbol-sequence framing) | N/A — segmentation doesn't need to represent polyphony as a sequence |
| Training data used | CameraPrIMuS, one synthetic font, +camera-distortion simulation of that same font (the BUG-011 root cause) | MSD (clean) + CMSD-P (printed+photographed) + CMSD-S (screen-captured) — **explicitly three-tier, sim-to-real gap is a first-class design concern** | Dataset-agnostic loader; shipped example is a real photographed medieval manuscript, not synthetic | DeepScoresV2 + CVC-MUSCIMA (same family PiyaNota's own YOLOv8 staff detector already trains on) |
| Data augmentation | None evidenced beyond the CameraPrIMuS distortion set itself | Not visible (training code withheld) | Real, concrete: rotation/contrast/erosion/brightness on ~60% of samples — **capture-condition augmentation, not font-style augmentation** | Standard segmentation augmentation (not deeply inspected; secondary to the architecture question) |
| Tenor/SATB clef handling | `get_clef_reference()` resolves by voice identity, not a distinct token (already solves the treble/tenor-8vb ambiguity at the state-machine level) | No tenor-specific clef token in vocab — same implicit-8vb ambiguity, unsolved | No SATB-specific handling (dataset-agnostic, doesn't know what SATB is) | No concept of it anywhere in the codebase — would need building from scratch |
| Training code available | Yes (`training/piyanota-training-ver-2.ipynb`) | **No** — README promises "training code will be open source later," nothing backs it in this clone | Yes, full and runnable | Yes but undeclared/unpinned deps (`tensorflow_addons`, `augly`), inference-first packaging |
| Audio/MIDI output | Yes — Stage 5 (own scope) | No | No | No (stops at MusicXML; `audio/` is a demo video, not code) |
| Model size / inference cost | Not directly comparable without a fresh benchmark | ~86MB, comparatively light | Not stated | Two ONNX segmentation models + SVMs — likely heavier end-to-end pipeline |
| License | N/A (own code) | Apache-2.0 | Not checked | Not checked |

## Does architecture explain BUG-011? No — the evidence points the other way

This is the load-bearing finding across all three analyses, and it converges from three independent
directions:

1. **TrOMR's own strongest asset is its dataset, not its transformer decoder.** The README frames
   MSD/CMSD-P/CMSD-S explicitly as closing the sim-to-real gap — the same gap BUG-011 diagnosed.
   TrOMR uses a heavier architecture (ViT + causal transformer, 4-stream joint pitch/rhythm/lift
   prediction) but the repo itself treats *training-corpus diversity* as the thing that actually
   solves real-world robustness, not the model family. This is independent, external validation that
   PiyaNota's PIYA-106 plan (font-diversify the training data, keep the CRNN) is aimed at the right
   lever.
2. **CRNN-CTC (PRAIG)'s augmentation targets a different axis than font style — and that's the
   useful finding, not a strike against CRNN-CTC.** Its rotation/contrast/erosion/brightness
   augmentation is real and well-built, but it varies *capture conditions* (camera angle, lighting,
   ink degradation), never *glyph/font style*. It would not, by itself, have caught BUG-011 — the
   PRAIG repo's own design implicitly treats font-style generalization as someone else's problem to
   solve, because its dataset-agnostic vocab loader assumes whoever builds a corpus for it already
   handles that. This confirms font-diversity and capture-condition-diversity are two separate,
   additive problems — PiyaNota's plan currently only addresses the first.
3. **oemer's segmentation approach reduces exposure to the domain gap for localization, but not for
   symbol identity.** Pixel-wise staff/notehead segmentation is more local and texture-driven than a
   full CRNN-CTC sequence read, so it plausibly generalizes better for "where is a notehead" — but
   *what type* of symbol it is (clef, accidental) still runs through small SVM classifiers trained on
   a fixed rendering distribution (DeepScoresV2). The domain-gap risk moves downstream and shrinks in
   surface area, it doesn't disappear. This is the closest any of the three repos comes to an
   architecture-level answer to BUG-011, and it's a partial one at best.

**Conclusion: none of the three repos support switching architecture as a fix for BUG-011.** The CRNN
(ResNet-CNN → BiLSTM → CTC) is a reasonable, standard choice for this class of problem — TrOMR uses a
CNN backbone too (ResNetV2, before its ViT stage), and PRAIG's own CRNN-CTC reference implementation
is structurally the same shape PiyaNota already has. The actual lever, corroborated three separate
ways, is training-data diversity — which is exactly what PIYA-106's font re-rendering + fine-tuning
plan is already doing.

## Where PiyaNota's SATB constraint rules things out on its own

Independent of the domain-gap question, SATB (4 independent open-score voices, one staff each) is a
layout oemer cannot currently handle without a real rewrite:

- `Measure.align_symbols()`'s `assert track_nums == 2` and `build_part_list()`'s hardcoded single
  `"Piano"` MusicXML part are not config flags — they're load-bearing assumptions baked into the
  rhythm-alignment and output-construction code. Getting oemer to emit 4 independent SATB parts would
  mean rewriting the alignment algorithm and the MusicXML part-builder, not just changing an argument.
- oemer's barline-height-based track-count inference (`further_infer_track_nums()`) plausibly
  transfers to SATB's one-barline-per-system convention (this part looks adaptable), but it currently
  feeds into code that only knows how to build 2 tracks either way.
- No Tenor-8vb-clef handling exists anywhere in oemer. PiyaNota already solved this
  (`get_clef_reference()` resolves by voice identity, not token) — adopting oemer would mean rebuilding
  a solved problem.

TrOMR and PRAIG's CRNN-CTC are both single-staff-at-a-time by design, which is actually a structural
*match* for PiyaNota's existing per-voice-strip cropping (Stage 2 already isolates one staff per
crop) — neither offers native multi-voice alignment, but neither needs to, since PiyaNota already
solves that at Stage 4 (`stage4_reconstruction.py`, not at the recognition stage).

## Recommendation

1. **Keep the CRNN-CTC architecture. Finish PIYA-106 rather than starting an architecture migration.**
   The font re-rendering + fine-tuning plan already in progress is the correctly-targeted fix per all
   three external analyses above, and it's substantively done (Step 2: both seed checkpoints valid,
   not yet formally closed on the LR-stability open item; Step 3 fresh real-world test set is the
   next action per the plan doc). Restarting on TrOMR or oemer would mean re-solving "collect diverse
   training data" from scratch for a new, bigger model, with **no training code available for TrOMR**
   and **no SATB support anywhere in oemer** — strictly more work with no first-party evidence either
   one performs better on open-score choral engravings specifically.

2. **New, low-cost addition worth considering as a follow-on to PIYA-106: capture-condition
   augmentation, borrowed from PRAIG's approach.** Rotation/contrast/erosion/brightness augmentation
   during CRNN training addresses a real, different failure axis (phone-camera skew, lighting,
   paper/ink artifacts) than font-glyph domain gap, and is cheap to add to the existing fine-tuning
   notebook. This wasn't in scope for the original BUG-011 diagnosis (which isolated font as the
   single variable) but is a plausible next problem once font generalization is confirmed working —
   worth flagging as a candidate Step 7.5 or a follow-up ticket, not urgent right now.

3. **Do not adopt oemer's segmentation approach for core recognition.** Structural SATB incompatibility
   (hardcoded 2-track assumption) plus a domain-gap risk that moves rather than disappears means the
   cost/benefit doesn't clear the bar. One narrow, separable idea worth a future look: oemer's
   `dewarp.py` does real page-curvature correction (grid-based local remap) beyond PiyaNota's current
   Stage 1 rotation-only Hough deskew — real phone photos of choir scores can have page curl from
   binding, not just tilt. This is a Stage 1 preprocessing idea, decoupled from the recognition-model
   question, and could be evaluated independently if page-curvature turns out to be a real contributor
   to strip quality (not currently evidenced as a problem — would need its own diagnosis before
   prioritizing).

4. **If PIYA-106 Step 5 is ever triggered** (font retraining alone proves insufficient, requiring
   targeted hand-labeling), TrOMR's three-tier corpus structure (clean-rendered / printed-and-
   photographed / screen-captured) is a reasonable template for organizing that data collection by
   degradation type, rather than treating "real-world data" as one undifferentiated bucket.

**Bottom line: the evidence across all three repos supports staying the current course (finish
PIYA-106), not switching approach.** The one actionable idea worth layering in is capture-condition
augmentation (PRAIG), as a complement to — not a replacement for — the font-diversity fix already
underway.
