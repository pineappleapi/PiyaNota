# PIYA-106 (proposed) — Chord Token Vocabulary + Multi-Dataset Retraining Plan

**Status:** PLAN ONLY. Written 2026-09-25, **revised 2026-10-01** (user-approved update). Nothing implemented,
nothing trained.
**Author role:** ml-cv-lead (advisory). Music semantics: choral-conductor,
`docs/decisions/piya-106-chord-music-semantics.md` (2026-10-01; referenced, not duplicated). Not yet reviewed by
senior-reviewer.

**2026-10-01 revision: read section 10 first. It is the operative plan.** It replaces:
- the "chords are rare" premise (section 0, finding 2) with dev evidence (10.1);
- DS2 as the primary chord source (0, 3.1) with script-injected divisi in the Phase 1 Bach/Palestrina renders (10.2);
- "one `dot-*` token per chord" (2.2) with one dot per drawn head (10.4);
- the Stage B mix and curriculum (4) and the ordered steps (8) with one vocabulary-expansion arm, chords + tuplets,
  2 seeds, started from the Phase 2 checkpoint after Phase 2 (10.5, 10.8; SER-15 plan, amendment 3);
- the Stage 3 notes in 2.4 with 10.6.

Open questions 1, 3 and 4 (section 9) are answered: 10.1, the user decision "a divisi chord plays both notes"
(2026-10-01), and the CLAUDE.md ground-truth rule. Sections 1-9 stay as the 2026-09-25 record.
**Decision context:** user chose option (b): give the CRNN a real chord signal in its token vocabulary and
retrain, because Camera-PrIMuS (CPM) is monophonic and Stage 3's `chord_id` detection
(`stage3_transcription.py`, body-stage "consecutive notes sharing the same tick onset") can never fire on a
monophonic token stream: each note advances `current_tick`, so two consecutive notes never share an onset.
Repurpose labels from: (1) DeepScoresV2 dense, (2) camera-grandstaff, (3) SynthSalienceChoralSet_v1.

## 0. Bottom line up front

| Dataset | Verdict for "single-staff strips + agnostic tokens + chords" |
|---|---|
| DeepScoresV2 dense | **Fits, with real conversion work.** Symbol-level bbox + duration + staff position. Multi-font. Chord grouping must be derived. Lossy on beams/voices. ~~Primary chord source.~~ **Secondary since 2026-10-01** (10.2; `piya-106-ds2-conversion-design.md`). |
| camera-grandstaff | **Partial fit.** Labels are `**ekern` (Humdrum), not agnostic; images are 2-staff systems (closed score, out of project scope). Usable only as a *label* source: split each kern spine into a single-staff score and **re-render** (Verovio) rather than crop the given images. ~20% of onset events are chords, the best chord density of the three. Piano-style chords are not open-score SATB. |
| SynthSalienceChoralSet_v1 | **Does not fit as provided.** It is audio-domain salience matrices (CSV), no notation, no images. Cannot yield agnostic tokens. Its only value is the *metadata*: 5365 CPDL choral pieces with source `.mxl` URLs, which are real open-score SATB notation *if* fetched separately (network, per-piece license check). Treat as a separate acquisition task, not "a converted dataset". |

Two findings that change the plan and should be read before the rest:

1. **CTC frame budget makes per-note chord tokens at the same x infeasible with the current architecture**
   (Section 2.3). If not audited, `CTCLoss(zero_infinity=True)` will silently zero out the infeasible samples and
   training will look healthy while chords are never learned.
2. ~~Chords are rare in the actual deployment target.~~ **Withdrawn 2026-10-01: the dev data says otherwise.**
   Chord/divisi spans are about 17% of note onsets on the camera dev strips (14% digital), in 4 of 5 pieces, and
   they take about 88% of the hypothesis tokens hidden inside GT `<OOV>` spans (section 10.1). The rule that chords
   must not regress monophonic accuracy still holds.

## 1. What each dataset actually contains (inspected on disk, read-only)

### 1.1 DeepScoresV2 dense — `D:\PiyaNota\datasets\ds2_dense`
- Files: `deepscores_train.json` (226 MB), `deepscores_test.json` (62 MB), `images/` (1714 files),
  `instance/` (1714), `segmentation/`. Test JSON: 352 images, 244,335 annotations. The test JSON's own `info`
  string says "Deepscores validation set in the OBB format" — the naming is inconsistent (also see BUG-004's
  134/346 YOLO split). **The CRNN must define its own splits, not inherit "test" by name.**
- Page images, ~1960x2772 (e.g. `lg-75827152-aug-lilyjazz-.png`). Filenames indicate LilyPond/MuseScore renders
  with named style augmentations (e.g. `lilyjazz`), i.e. genuine multi-font/multi-engraver diversity, which is
  exactly what BUG-011 needs and complements the 5 Verovio fonts.
- Annotations: axis-aligned bbox `a_bbox`, oriented bbox `o_bbox`, `cat_id` (a pair: DeepScores id + MUSCIMA++ id),
  `comments` with `instance:#…;`, and **for noteheads only** `duration:<n>;rel_position:<int>;` (verified: the
  76,262 annotations carrying `rel_position` are exclusively `notehead{Black,Half,Whole,DoubleWhole}{OnLine,InSpace}`).
- 110 DeepScores categories: `staff` (3864 in the test JSON, median bbox height ~67 px, some degenerate 0-height —
  filter them), `clefG/F/CAlto/CTenor/clef8/clef15`, key/accidentals, `timeSig0..9/Common/CutCommon`, rests,
  `stem`, `flag*`, `beam`, `augmentationDot`, `ledgerLine`, `tie`, `slur`, `tuplet*`, dynamics, articulations, etc.
- No voice/part identity, no onset time, no explicit chord/beam-group object. Stem-sharing and x-alignment are the
  only chord evidence.
- Not measured: DS2 chord rate. My quick stem-containment probe returned 0 matches, which means the probe geometry
  was wrong, not that there are no chords. Chord rate must be measured in step 1 below before sizing anything.
- License: not stated on disk. The published DeepScoresV2 release is understood to be CC BY 4.0 (Zenodo) — **verify
  from the source page before any redistribution or model release; do not rely on this note.**

### 1.2 camera-grandstaff — `D:\PiyaNota\datasets\camera-grandstaff`
- HF `datasets` Arrow cache (PRAIG). Splits: train 41,598 / val 4,623 / test 7,661 (~570 MB). Features: `image`
  (JPEG bytes) and `transcription` (string). `dataset_info.json` has empty `license` and `citation`.
- `transcription` is **Humdrum `**ekern_1.0`, two spines** (bass clef spine, treble clef spine), with clef, key,
  meter, barlines, spine splits (`*^`/`*v`), beams (`L`/`J`), ties, and chords as space-separated tokens within a
  cell (e.g. `8ee-L 8g`). Measured on the val split: 177,107 onset cells, 34,784 contain a chord = **19.6%**.
- Images (e.g. 812x267) are camera-style renders of a **grand-staff system** (piano reduction). Two staves in one
  image = closed score = **explicitly out of project scope** (CLAUDE.md). The image pixels are therefore not
  directly usable as Stage 2-equivalent strips.
- Split provenance: rows carry no piece id. Sample crops from the same piece can plausibly sit in different splits;
  piece-disjointness is **unverified** (see leakage section).
- License: not stated on disk; upstream is a research release from PRAIG (Alicante). **Unverified.**
- Tooling on this machine already: `verovio 6.3.0`, `music21 10.5.0`, `pyarrow`, `datasets` (pip list).

### 1.3 SynthSalienceChoralSet_v1 — `D:\PiyaNota\datasets\SynthSalienceChoralSet_v1.zip`
- 2.28 GB zip (~500 GB uncompressed by the zip directory sum: **do not extract**). 26,827 members: 5,365 pieces x
  5 CSVs (`_S`, `_A`, `_T`, `_B`, `_mix`) + `sscs_metadata.csv` (5,365 rows: song name, source = `CPDL` for all,
  and a CPDL `.mxl`/`.zip` URL).
- Each CSV is a numeric salience matrix (sampled one: 360 rows x 4866 columns of 0.0/1.0 floats), i.e. a
  pitch-by-time activation grid for synthesized audio. **No notation, no images, no glyph geometry.**
- Cannot be converted to agnostic tokens (no staff positions, clef, or key info; note identity would have to be
  re-derived from a pitch grid, which is transcribing audio back into notation with unknown clef/key/spelling).
- What is genuinely useful: metadata lists 5,365 real SATB choral pieces at CPDL. Downloading those MusicXML
  files and rendering them through Verovio would produce exactly the deployment distribution (open-score
  choral, real engraved look, divisi where present). That is a **new data-acquisition task** with its own risks:
  per-piece CPDL license varies, many files are not strict SATB open score (some are 2-staff closed), URLs may
  be dead (some `.zip` archives, not `.mxl`), and it needs network access. It also should be **the test-set
  source for chord recall** rather than training data (Section 5).
- License of the zip itself: not stated on disk; underlying pieces are CPDL with per-work licenses. **Unverified.**

## 2. Chord token design

### 2.1 Options considered
| Option | Idea | Verdict |
|---|---|---|
| A. Duration-less continuation tokens | Lowest notehead = existing `note.<dur>-<pos>`; each further notehead = `chordnote-<L\|S><pos>` (bottom to top), inheriting duration/beam from the base note | **Recommended** |
| B. Zero-width marker `chord.next` between ordinary note tokens | Invisible token, no glyph anchor, costs an extra CTC frame per extra note | Rejected: worst frame cost, no visual anchor |
| C. Composite token per chord (`chord.quarter-L1+2+4`) | 1 label per chord, so no frame problem | Rejected as primary: vocabulary explodes (duration x beam variant x bottom position x interval pattern), long tail unlearnable, does not warm-start |
| D. Rewrite everything as multi-label / 2-D output (per-pitch-row heads) | Correct in principle for polyphony (SMT-style) | Out of scope: architecture change, throws away the checkpoint |

### 2.2 Option A concretely (append-only vocabulary)
- New tokens appended to the **end** of `VOCAB` (existing indices unchanged, per the notebook's own rule that
  regenerating VOCAB from a union of corpora invalidates checkpoints): `chordnote-L{-2..8}`, `chordnote-S{-2..8}`
  (~22-26 tokens; final list = whatever positions appear in the converted data, capped).
- Linearization is left-to-right by x (the only order CTC can align), ties in x resolved bottom-to-top. This means
  a chord's accidentals come first, then base note, then chordnotes. Accidental tokens already carry a staff
  position (`accidental.flat-L3`), so **pairing an accidental to its chord member is by matching position**,
  not by adjacency. This requires a small `infer_pitch` change (currently `pending_acc` applies to whatever note
  comes next).
- ~~Augmentation dot: one `dot-*` token per chord is treated as dotting the entire chord.~~ **Superseded
  2026-10-01 (10.4):** engraving draws one dot per head, so the label has one dot per head.
- Beams, stem direction: unchanged, carried by the base note token. Chordnotes never carry a beam suffix.
- Not representable in v1 (must be listed as known-lost, not silently dropped): seconds with displaced noteheads
  (same x-slot offset left/right; linearization order may flip), tuplets (BUG-015), cross-staff chords, unisons of
  two voices on one stem.

### 2.3 How CTC handles simultaneous notes (the real constraint)
`CRNN.cnn` downsamples width by 4 (two `MaxPool2d(2,2)` then only height-only pools), so T = W/4 frames. A notehead
is roughly 1.2 staff spaces wide; at Stage 2 strip scale that is on the order of 10-12 px = **~2-3 frames**. A triad
needs 3 labels (base + 2 chordnotes) inside those 2-3 frames; a 4-note chord needs 4. CTC needs at least one frame per
emitted label (plus a blank between identical adjacent labels), so triads are marginal and 4-note stacks are infeasible.
Consequences and mitigations, in priority order:
1. **Feasibility audit before any training** (data-only, no GPU): for every converted sample compute
   `min_T_required = len(labels) + count(adjacent identical labels)` versus `T = W/4` at the exact resize Stage 3
   uses. Report the infeasible fraction overall and **for chord samples specifically**. Gate: chord-sample
   infeasibility must be near zero, else the design is not trainable as specified.
2. **Log, never mask:** the notebook uses `CTCLoss(blank=BLANK_IDX, zero_infinity=True)`. Infeasible samples then
   contribute zero loss and zero gradient silently. Any chord run must count and report zero-loss samples per epoch
   (overall and chord-only). A run whose chord samples are mostly zeroed is invalid regardless of its SER.
3. If the audit fails: options are (i) halve the width stride (change the second width pool `(2,2)` to `(2,1)`), which
   keeps every weight shape (LSTM/fc unchanged) but changes feature statistics, so warm-start value drops and
   it must be treated as a new architecture with its own forgetting check; (ii) cap chords at dyads/triads in
   training labels and document that larger stacks are truncated (truncation is a silent-wrong-notes failure and must
   raise a flag at inference); (iii) fall back to composite tokens for the top-N most frequent chord shapes only.
   Do not choose among these without the audit numbers.

### 2.4 Stage 3 / infer_pitch / event emission changes (design only)
- `infer_pitch` body stage: on `chordnote-<pos>`, compute pitch with the same active clef, key signature,
  and position-matched accidental as a normal note; **do not advance `current_tick`**; set `tick_onset` and
  `duration_ticks` from the preceding base note (and its dot); set `chord_id` on the base note and every member
  explicitly (replace the dead same-onset heuristic). A `chordnote` with no preceding base note in the same body
  segment (e.g. after a barline/rest) is an orphan: emit nothing, count it, and lower the strip's confidence.
- Events keep the existing schema (`chord_id`, shared `tick_onset`). No schema change for Stage 4/5.
- Downstream check needed (not in my remit to decide): Stage 4 `_resolve_slurs` assumes one note per onset when it
  extends "the first note of a slurred group"; Stage 5 writes one MIDI track per voice, so two simultaneous notes
  on one track is technically fine. Musically, whether a divisi chord in a voice staff should sound both notes is a
  choral-conductor question (Open Question 3).
- Confidence: `_greedy_ctc_decode_with_confidence` gives per-symbol confidence. Chordnote tokens must be included in
  strip-level confidence. BUG-002/BUG-011 class risk: a model that hallucinates chordnotes or drops them
  *confidently* is the same silent-failure class in a new place. Chord-token confidence calibration is a required
  evaluation output (Section 5), not optional.

### 2.5 Checkpoint impact
- `CRNN.fc = Linear(512, VOCAB_SIZE)`. Head resize: copy old rows/biases into the first `old_V` rows of the new head;
  initialize new rows to small weights and a strongly negative bias (so chordnote starts near-never emitted, and
  monophonic behavior at step 0 is preserved). Everything else warm-starts unchanged (assuming the width-stride
  change is not taken).
- The notebook currently `assert`s `_base_ckpt["vocab"] == VOCAB`. This must become "old vocab is an exact prefix of
  new vocab", else it will (correctly) refuse to load.
- Warm-start vs retrain: warm-start from whichever PIYA-106 checkpoint is final (see dependency, Section 7). Retraining
  from scratch is more expensive, and there is no evidence yet that warm-start harms chord learning; but note the
  existing fine-tune already shows instability (seed=2 epoch-3 spike near the hard cap), so the chord fine-tune must
  inherit the same forgetting canaries, not just the same LR.
- Provenance: new checkpoint stored with `vocab`, `base_ckpt_sha256`, dataset manifests, and seeds; recorded in the
  run manifest (`run_manifest.py`).

## 3. Conversion pipelines

Common target: **one staff -> one strip at STRIP_HEIGHT=64, full staff width like Stage 2's output**, label = agnostic
token sequence in CPM style with chordnote extensions. Every conversion emits a sidecar JSON per sample (source id,
piece id, font/renderer, token provenance, dropped-symbol list) so losses are auditable.

### 3.1 DeepScoresV2 (primary source of real-look chords)
1. Parse JSON; drop degenerate `staff` boxes. Group annotations by image; split by **source piece id** parsed from
   the filename (`lg-<id>-aug-<style>-`): the same piece appears in several `aug-*` style variants, so an image-level
   split leaks (identical notation, different font).
2. For each staff bbox: gather symbols whose center is within the staff x-range and within the staff y-band expanded for
   ledger lines; sort by x. Crop the strip from the page image with the same margin/padding rule Stage 2 uses
   (`stage2_detection.py`), resize to height 64 preserving aspect ratio, exactly as Stage 3 does.
3. Map to tokens:
   - clef: `clefG`->`clef.G-L2`, `clefF`->`clef.F-L4`, `clefCAlto/CTenor`->`clef.C-L3/L4`; `clef8`/`clef15` modifiers
     have no CPM equivalent (Tenor 8vb stays visually treble, consistent with `get_clef_reference()`); flag, don't invent.
   - notes: notehead category + `duration` + `rel_position` -> `note.<dur>-<L|S><pos>`. `rel_position` -> L/S and
     integer via the CPM convention already used by `infer_pitch()`; **this mapping must be validated by round-tripping
     against CPM-known examples before use** (off-by-one here reproduces a BUG-009-style silent pitch shift).
   - beams: CPM uses `beamedLeft/Right/Both<n>`. Derive from `beam` and `stem` bboxes overlapping each notehead's stem;
     error-prone. v1 fallback: map beamed notes to the unbeamed duration token, but that creates a *label/visual
     mismatch* (the image shows a beam, the label says none). Prefer dropping any staff with unresolved beams
     from the training set over training on mislabeled ones.
   - rests, key/accidentals (`keySharp/Flat` and `accidental*` have no `rel_position` in the JSON; positions must be
     computed from bbox y relative to the staff lines), time signature digits, `augmentationDot`, barlines
     (not an explicit category: derive from vertical line/staff-height annotations if present, else drop staves
     where barlines are needed for pitch state).
   - chords: noteheads sharing a stem instance (or, absent that, x-center within ~0.6 notehead-widths and a shared
     stem bbox) -> base + `chordnote-*`, bottom to top.
4. What is lost: voices, ties/slurs (ignored by the CRNN today), tuplets (drop staves containing `tuplet*`, mirroring
   BUG-015), ornaments, dynamics, articulations; multi-staff grouping (fine, staves are cropped independently).
   Piano/orchestral staves dominate the content, so chords here are piano-style; SATB-style choral text and layout is
   absent (no lyrics baked in either, which is a mismatch with the deployed strips only if lyrics remain post-blanking).
5. Yield is not established. Report for each drop reason (beam unresolved, tuplet, missing barline, orphan symbols)
   the counts before deciding whether DS2 supplies enough chord staves.

### 3.2 camera-grandstaff (label source, re-render, do not crop)
1. Decode `transcription` (kern) with music21/Verovio's Humdrum importer; split each two-spine score into two
   single-staff scores (each spine keeps its own clef/key/meter). This drops the closed-score pairing on purpose.
2. Render each single-staff kern through Verovio in the 5 fonts of the BUG-011 plan at the strip aspect, adding the
   existing camera-distortion simulation. Labels come from the same MEI/kern -> agnostic converter that must also be
   written for CPM-compatibility (CPM's `.agnostic` was produced from MEI/PAE, and no such converter exists here for
   kern; it is the largest single piece of work in this dataset and must be validated on the CPM samples themselves:
   re-derive agnostic from CPM `.mei`, diff against shipped `.agnostic`, require ~100% match before trusting it on
   new data).
3. Chord handling: kern `8ee-L 8g` cells become base + `chordnote-*` by position. Kern has explicit note order in a
   cell, which makes chord grouping exact (an advantage over DS2).
4. Loss: closed-score context; piano writing style (wide arpeggiated stacks, 4-6 note chords, cross-staff beams,
   multiple voices in one staff via `*^` spine splits: a spine split means two simultaneous voices in one staff,
   which is a different phenomenon from a chord and must be dropped or flattened deliberately, else the labels
   are wrong). Filter to staves without spine splits for v1.
5. The provided images are **not** used as training pixels (2 staves). They may serve as a diagnostic (crop by staff
   detection) for staff-crop robustness only.
6. Chord distribution caveat: 19.6% of onsets are chords here, but piano-style; the model may learn "chord = wide
   piano voicing" and under-generalize to SATB divisi (mostly 2-note, close intervals). Cap chord size in mixing.

### 3.3 SynthSalienceChoralSet_v1
- **No conversion is possible.** Recommend deleting it from the "conversion" scope and not extracting the zip.
- Optional separate task (needs user decision): use `sscs_metadata.csv` URLs to fetch CPDL MusicXML, render via Verovio,
  and use as (a) a **held-out chord/choral evaluation set** and/or (b) a training source, with piece-level license
  screening. If used for both, the split must be by piece and the eval pieces must be locked before any tuning.
- None of the 5,365 x 5 salience CSVs can serve Stage 3.

### 3.4 Combining with the existing 5-font Verovio re-renders (BUG-011 Step 1)
- All sources emit the same `(image, token_sequence, sidecar)` triple. For CPM re-renders the label is unchanged
  and every sample is monophonic (zero chordnotes): these remain the **monophonic anchor**.
- Do not merge sources into a single pooled shuffle without recording source in every sample; every reported number
  is stratified by source and by chord/non-chord (Section 5).
- Font labels: CPM-Verovio fonts (Leipzig, Bravura, Petaluma, Gootville, Leland) vs DS2 rendering styles vs the original
  CPM font. Hold one font/style out per source as a leave-one-font-out canary (the BUG-011 plan already uses
  `loo_font_ser`).

## 4. Mixing ratio and curriculum (protect monophonic accuracy)
The numbers below are starting proposals to be swept on **synthetic validation only**, not tuned on any real set.
1. **Stage A (existing PIYA-106 fine-tune)** finishes first: CPM original + 5 fonts, monophonic, no chordnote. This is
   the baseline and the anchor checkpoint.
2. **Stage B (chord introduction):** warm-start from Stage A's best checkpoint(s) (both seeds, report as a range).
   Mix per batch approx: 50% CPM (orig + 5-font, monophonic), 30% DS2-derived (mix of chord/non-chord staves as they
   occur), 20% grandstaff-derived single-staff re-renders, with chord staves oversampled only enough that chordnote
   tokens are ~5-10% of note tokens. Sweep the ratio over at most 3 values.
3. Lower LR than Stage A's 3e-5 is likely needed for the new head only; freeze CNN for the first epoch(s), unfreeze
   with the same forgetting canaries. Head-only-first also isolates "did the new head learn chords" from "did the
   backbone drift".
4. **Hard forgetting gates** (checked every epoch, same style as the existing hard-cap/soft-floor): clean-CPM SER,
   distorted-CPM SER, and clean-CPM-in-each-font must stay within a pre-registered margin of Stage A (numeric margins
   to be set before Stage B starts, mirroring the Stage A hard cap). Any breach invalidates the epoch.
5. Monophonic-only regression check: on non-chord staves from every source the new model's SER must be no worse than
   Stage A's beyond the noise floor. The seed-to-seed noise floor is already large (7-29% same-seed, ~70% gap
   between seeds), so the margin must be set from measured noise, not a hunch.
6. Ablations required to attribute any gain: (i) Stage A vs Stage B on chord-free data (forgetting); (ii) Stage B
   with DS2 only vs DS2+grandstaff (does the piano-style source help or hurt); (iii) Stage B trained on the *same
   data with chordnotes stripped from labels* (control: does extra data alone explain any monophonic change, as opposed
   to chord vocabulary).
7. Augmentation caveat: label-noise augmentation (font jitter, distortion) can mask a gap without closing it; the
   real-photo set stays the only truth for that (Section 5).

## 5. Evaluation design
### 5.1 Sets and roles
| Set | Role | Rule |
|---|---|---|
| `D:\PiyaNota\data\piyanota_dataset` (real phone photos) | **TEST only, all of it** | Never used for training, validation, checkpoint selection, mix-ratio choice, threshold choice, or augmentation tuning. Evaluated once per frozen candidate, log every look. |
| BUG-011 48 diagnostic strips | Spent | Not reused for reporting. |
| CPM val/test (orig + 5 fonts) | Forgetting canary, reported separately | Own numbers. |
| DS2-derived val (carved from train JSON by piece id) | Model selection | Never overlaps test. |
| DS2-derived test (from `deepscores_test.json`, split by piece) | Final synthetic report | Touch once. |
| grandstaff-derived val/test | Selection / final | Re-split by piece (see 5.3). |
| CPDL/Verovio choral set (if acquired) | Chord recall on SATB-shaped material | Pieces locked before any tuning. |

Never blend: report CPM (clean, distorted, per font), DS2, grandstaff, and real-photo as separate rows, each split
into chord / non-chord staves. No single aggregate number in any merge decision.

### 5.2 Ground-truth policy for real photos
Per CLAUDE.md as relayed by the user, hand-authored ground truth is not accuracy evidence. (I could not find that
sentence in the CLAUDE.md text supplied to me; I am honoring the instruction as given and the user should confirm the
exact rule.) Consequences: any chord-recall figure on `piyanota_dataset` computed against hand-typed labels is
**diagnostic only** and must be labeled so. The only acceptable "truth" for a real-photo score would be one derived
from an independent machine-readable source of the same score (e.g. the MusicXML/MuseScore export the photo was
printed from), reported with its provenance. If `piyanota_dataset` has no such source, the real-photo chord result
is a sanity check, not evidence.

### 5.3 Leakage checks (all scripted, run before any training)
- DS2: split by source piece id (parsed from filename), not by image; assert zero piece overlap between train/val/test
  and confirm the YOLO staff detector's DS2 split is not being re-used as the CRNN's split.
- grandstaff: no piece id available. Detect near-duplicates by hashing normalized kern (transposition-invariant
  interval sequence, measure n-grams) across the shipped train/val/test; if overlap is nonzero, re-split by clustered
  piece and discard the shipped splits.
- Cross-dataset: compare DS2 / grandstaff / CPM (RISM incipits) / CPDL pieces by the same n-gram hashing to catch the
  same piece appearing in two datasets (public-domain repertoire overlaps often).
- Real photos: check that no piece in `piyanota_dataset` also appears in any training or val source (title + n-gram).
  Filipino repertoire in the photo set makes overlap unlikely with these sources, but verify, do not assume.
- Font leakage: for LOO-font canaries, verify no sample rendered in the held-out font appears in training under a
  different id (same MEI, same font).
- Checkpoint selection audit: every "best epoch" selected on a set that is disjoint from every reported set.

### 5.4 Metrics
- Chord-note recall (fraction of ground-truth chord members recovered at the right position and onset), chord-note
  precision (hallucinated chordnotes; the more dangerous error for SATB), chord-exact-match (whole chord correct).
- Token-level SER, split by chord staves vs non-chord staves, per source, per font.
- Pitch accuracy at event level with chord members matched by onset then position (an unmatched chord member counts as a
  miss, an extra as a false positive).
- Calibration: confidence of chordnote tokens vs correctness (reliability curve or at least AUROC of confidence for
  correct vs incorrect chord decisions), same for clef. Flag: if the new model is confidently wrong on chords,
  that is BUG-002/BUG-011 in a new architecture and unresolved even if accuracy rises.
- CTC diagnostic: fraction of samples with zero_infinity-zeroed loss, overall and chord-only, every epoch.
- Sample sizes: report N and a confidence interval on every number; the real-photo set's size limits what can be
  claimed. Under ~100 strips per condition, treat as diagnostic (matches Step 3 of the BUG-011 plan).

### 5.5 BUG-013 determinism precondition
BUG-013 (suspected): on the dev GTX 1650, unmodified Stage 3 gave different events across two runs on byte-identical
strips, then cuDNN crashed and the driver hung. Until it is resolved, no accuracy/chord number measured on that
GPU is admissible. Preconditions before any Stage B training or evaluation that informs a decision:
1. BUG-013 root-caused or the work is done on a non-affected device (Kaggle GPU or CPU); state the device in every result.
2. Run-to-run check: two identical evaluations of the same checkpoint on the same strips must give byte-identical
   token outputs (deterministic cuDNN flags already set in `finetune()`; add the still-unfixed seeded DataLoader
   `generator`/`worker_init_fn` on `finetune_train_loader`, cell 12, to any chord-stage loader).
3. Record checkpoint SHA, data manifest hash, seed, and device in `run_manifest.py` output for every reported number.
4. CPU-vs-GPU output agreement on a fixed strip set (tolerance stated in advance) as a canary.

## 6. Risks
| Risk | Severity | Mitigation |
|---|---|---|
| CTC cannot emit dense chord stacks in 2-3 frames; `zero_infinity` hides it | High | Feasibility audit + zero-loss counter (Section 2.3) |
| Chord capability pays off in a rare deployment case while risking monophonic regression | High | Forgetting gates, chordnote-stripped control (Section 4), size the payoff (Open Q1) |
| Label-conversion errors (rel_position -> L/S off-by-one, beam derivation, kern->agnostic) create confident wrong labels | High | Round-trip validation against CPM `.mei`/`.agnostic`; drop-not-guess policy; sidecar audit |
| DS2 image-level split leaks across `aug-*` variants | High | Split by piece id |
| grandstaff split leakage (no piece id) | Medium-High | n-gram near-duplicate detection, re-split |
| Piano-style chord distribution != SATB divisi | Medium | Cap size/mix, evaluate on CPDL choral pieces |
| Hallucinated chordnotes are a *silent* pitch error per voice | High | Precision/calibration metrics, confidence gating, orphan count |
| Vocabulary change conflicts with PIYA-106 checkpoints and evaluation | Medium | Append-only vocab, do not start until Stage A closed |
| New synthetic sources bias towards renderer look (still not real photos) | Medium | Real-photo TEST set, kept untouched |
| BUG-013 makes every GPU number untrustworthy | High | Section 5.5 precondition |
| Long DS2 full-width lines (many more symbols/strip than CPM incipits) change sequence-length distribution | Medium | Length-stratified metrics; audit T vs label length |
| Licensing of grandstaff/SSCS/CPDL unverified | Medium | Human/senior-reviewer call, verify before any redistribution |

## 7. Dependency on in-progress PIYA-106 (BUG-011 plan Steps 2-7)
- This work must **not** touch `VOCAB`, notebook cell 5 checkpoints, or `crnn_weights/finetuned_font_seed{1,2}.pt`
  while Steps 2-7 are open. Chord work produces a **new** candidate (`crnn_chord_v1_*`) evaluated afterward on the same
  real TEST set, so BUG-011's evaluation is not confounded by a simultaneous vocabulary change (this is the
  single-variable rule: font fix and chord fix are separate experiments).
- Step 2 is not formally closed (unfixed DataLoader seeding, epoch-3 near-cap spike). Stage B inherits those problems;
  fix the DataLoader `generator` seeding first.
- Steps 3-4 (fresh real-world test, single evaluation) and step 7 (confidence re-check) proceed unchanged; the chord
  model gets its own single evaluation on `piyanota_dataset` **after** the font-fine-tuned model has been evaluated,
  so the real-photo set is looked at once per frozen candidate, with the number of looks logged.
- Anything from the piyanota_dataset used to *decide* whether to start chord work (e.g. "how many real chords exist")
  is a look at TEST. Count chords from the printed scores by eye at the notation level for scoping only, and do not use
  that count to tune anything.

## 8. Ordered steps with go/no-go gates
0. **Preconditions (no GPU):** resolve or sidestep BUG-013; close PIYA-106 Stage A (Step 2 formal close, DataLoader
   seeding, Steps 3-4 evaluation of the font model). *Gate:* Stage A checkpoint(s) frozen, real-set look logged.
1. **Size the payoff (no GPU):** count chord-bearing onsets in (a) DS2 (fix the stem-sharing probe), (b) grandstaff
   (19.6% measured on val), (c) a scoping look at real SATB deployment scores. *Gate:* if deployment chord prevalence is
   negligible, present that to the user and let them confirm (b) still stands.
2. **License + provenance check** for DS2, grandstaff, CPDL (per piece). *Gate:* human sign-off; drop any source that
   cannot be used.
3. **Converter build + validation (no GPU):** kern->agnostic and DS2->agnostic; round-trip on CPM `.mei`/`.agnostic`
   for the agnostic writer; token-position mapping tests against `infer_pitch()`. *Gate:* ~100% match on CPM round-trip;
   per-source drop-reason table reviewed; hand-inspect a random sample of converted strips overlaid with tokens (diagnostic).
4. **Leakage scripts + splits frozen** (5.3). *Gate:* zero overlap; splits hashed and stored.
5. **CTC feasibility audit** (2.3). *Gate:* chord-sample infeasibility ~0 at the chosen stride, or choose a mitigation and
   re-audit. **No-go for training if this fails.**
6. **ml-cv-lead pre-training review** of the exact notebook diff (CLAUDE.md rule), including mixing ratios and forgetting
   margins written down beforehand.
7. **Stage B training** (Kaggle, deterministic flags, seeds 1 and 2, report range). Per-epoch gates: forgetting canaries,
   zero-loss counter, chordnote emission rate. *Gate:* no hard breach; chord-stripped control and ablations run.
8. **Synthetic evaluation** on frozen val/test per source (chord vs non-chord separately). *Gate:* no monophonic regression
   beyond noise floor; chord recall/precision above pre-registered floors.
9. **Stage 3 integration (code, after the model passes):** `infer_pitch` chordnote handling, position-matched accidentals,
   orphan handling; senior-reviewer + choral-conductor review; check Stage 4 slur logic.
10. **Single real-photo evaluation** on `piyanota_dataset` with calibration report; label hand-derived truth as diagnostic.
    *Gate to merge:* no regression in clef/pitch vs the Stage A model on real photos, chordnote precision acceptable,
    confidence separates right from wrong on chord tokens. Otherwise not merge-ready.

## 9. Open questions for the user
1. How common are simultaneous notes in a single voice staff in your actual SATB scores (divisi, double-stops)? If it is
   only a few percent, is option (b) still the priority over the BUG-011 real-photo gap (clef 2/48, non-clef tokens wrong)?
2. SynthSalienceChoralSet: are you willing to fetch the CPDL MusicXML via the metadata URLs (network, per-piece license) if
   the salience CSVs themselves cannot be used? Should it become the held-out chord test set rather than training data?
3. For a divisi/chord in a voice staff, should both notes sound in that voice's track? (choral-conductor should confirm;
   it also decides whether chord support helps the final audio at all.)
4. Confirm the exact CLAUDE.md rule on hand-authored ground truth; I could not locate it in the file supplied. Does
   `piyanota_dataset` have an independent machine-readable source per score?
5. Are you fine with camera-grandstaff being used only as a kern-label source (re-rendered, single-staff), not as images,
   given closed score is out of scope? Which fonts/renderers for it?
6. Licenses: who signs off on DS2 (believed CC BY 4.0, unverified), grandstaff (unstated), CPDL (per piece)?
7. Compute: is the CTC stride change (width `(2,1)` pool) acceptable if the audit fails, given it forfeits much of the
   warm-start value?
8. Sequencing: should this wait for PIYA-106 Stage A to close, or run in parallel using a separate branch and checkpoint
   namespace? (I recommend waiting on anything that touches VOCAB.)

## 10. Revision 2026-10-01: the vocabulary-expansion arm (operative)

Binding user decisions: (1) a divisi chord in one voice plays **both** notes (2026-10-01); (2) chords and tuplets
are built in **one vocabulary-expansion arm after Phase 2**, not inside it (SER-15 plan, amendment 3, frozen).
Music semantics come from `docs/decisions/piya-106-chord-music-semantics.md` (choral-conductor, "CM" below).

### 10.1 How common chords are (replaces "chords are rare")
Measured from the step 6 alignment (`budget.row_ops` on `hyp_live.json`, job tmp `step6/`), with each GT `<OOV>`
mapped to its `gt_source.txt` description. **Dev data, diagnostic, used for sizing only, never for tuning.**
Five camera pieces (227 strips) and three digital pieces (100 strips). The script is outside the repo
(`%TEMP%/oov_kinds.py`).

| | camera | digital |
|---|---|---|
| hyp tokens absorbed by `<OOV>` (seed 1-2) | 787 / 777 | 309 / 310 |
| ... by chord spans | 695 / 686 (**~88%**) | 228 / 228 (~74%) |
| ... by triplets | 54 / 54 (~7%) | 53-54 (~17%) |
| ... by two-voice / divisi-over-held / other | 38 / 37 | 28 |
| GT chord onsets vs GT note onsets | 535 vs 2,533 (**~17%** of note onsets) | 170 vs 1,008 (~14%) |
| strips with at least one chord | 88 / 227, in 4 of 5 pieces (Honneur has none) | |
| chord size (where described) | 448 dyads, 3 triads; 84 undescribed (mostly DSMN "chord e") | 156 dyads, 3 triads |
| chords by voice (camera) | Bass 268, Tenor 127, Alto 80, Soprano 60 | |

Caveats: piece-dominated (Handog has 266 of the 535 camera chords, about one chord per note); the GT is
agent-made except Non Nobis; triplet and two-voice spans are counted separately and are not chords. Divisi on
extra staves (Handog's 5-7 staff systems) is excluded by the scope rule, so it is not counted here (CM, item F).
**Consequence:** chords are a main vocabulary gap, not an edge case. On dev, the chord spans alone hide about as
many hypothesis tokens as all the scored errors combined.

### 10.2 Data source
- **Primary: script-injected divisi in the Phase 1 Bach/Palestrina corpus.** The 742 included pieces (Bach 367,
  Palestrina 375) have **no native chords**: `corpus_log_*.json` shows no "chord in a voice" skip. So every
  chord is injected. A new step in `build_corpus.py` (seeded, logged per piece like the constructed events)
  edits the music21 score after SATB normalisation, before MusicXML/MEI export:
  - Add a second pitch taken from the harmony the other voices sound at that onset (a doubling, which is how
    real divisi works), within MIN/MAX_POSITION. Mostly 3rds, 6ths and octaves (Bass octave allowed); intervals
    over an octave in S/A/T are not injected (CM V1).
  - Spans: a cadence/final chord, or a 1-4 bar passage. About 95% dyads, a few triads, no 4+.
  - Voice weights are a prior that leans to Bass/Tenor. They are not fit to 10.1.
  - **Engraving forms:** same-stem chord (`<chord>` in MEI), and **split stems, same rhythm** (two MEI layers with
    identical rhythm; CM says it is musically the same as a chord). Include **seconds with displaced heads** at a
    logged share, because CM says they are common in Filipino arrangements. Not injected: split stems with
    different rhythms, layer rests, cue/optional small notes, unison heads side by side (all out of v1, CM table).
  - Rendered through the unchanged Phase 1 pipeline: Verovio, the 5 fonts, the same layout and camera
    augmentation, cut by our Stage 1/2, labels from the converter, the SVG check, then the vocabulary guard.
- **Tuplets share this pipeline:** script-injected triplets (amendment 3) go through the same seeded injection
  step, the same render and the same checks. One corpus build makes the arm's whole new-token data.
- **Splits:** an injected variant inherits its source piece's split (`melody_groups.py`, by melody). The arm's
  validation pieces are the Phase 2 validation pieces. Keep the un-injected original of every injected strip in
  training too, so the model sees the same music both with and without the chord.
- **DS2: secondary.** Its converter drops stems with 2+ heads today (`piya-106-ds2-conversion-design.md`). Behind
  the same off flag it could label them as chords (exact grouping from the shared stem). Not part of arm v1;
  only after its D1-D3 gates. **camera-grandstaff:** only as stated in 3.2 (kern labels, re-rendered single
  staff, piano-style chords); not in arm v1. **SynthSalienceChoralSet:** only as stated in 3.3 (no conversion;
  the CPDL fetch is a separate user decision).

### 10.3 Converter, SVG check and vocabulary guard (all behind one off flag, e.g. `vocab_ext=False`)
With the flag off, behaviour stays exactly as today: chords, tuplets and multi-layer staves raise
`ConversionError`, `build_corpus.py` still refuses `music21.chord.Chord`, and the guard quarantines any new token.
Phase 2 data must be byte-identical with the flag off (check the corpus hash).
- **`training/music_to_agnostic.py`:**
  - `<chord>`: members sorted by staff position, bottom to top. The lowest is `note.<dur>-<pos>` with the chord's
    beam form; the others are `chordnote-<pos>`.
  - Drawn accidentals (verovio dialect `@accid` only, as today) go before the base note, in position order.
  - **One `dot-<pos>` per head** at each member's dot position (CPM convention: a line note's dot is in the
    space above). A double dot is two dots at the same position.
  - `slur.start/end-<pos>` per tied member.
  - Two layers in one measure: merge into chords **only** if both layers have the same onsets and durations
    (split stems, same rhythm). Otherwise keep refusing (`two-voice`, out of v1).
  - `<tuplet>`: amendment 3's `tuplet.<n>`.
  - Bar-length tracking counts a chord once.
  - Gate before use: re-run CPM G1 with the flag on (must be unchanged, since CPM has no chords), plus a G1b-style
    human check of about 30 injected strips (fonts stratified; same-stem, split-stem, seconds, dotted chords,
    tied members, accidentals on the upper member, triplets). Same pass rule: 0 systematic errors.
- **`training/phase1/svg_check.py`:**
  - Noteheads inside an SVG `chord` group, and same-x heads across layers, are compared as a set ordered bottom
    to top, not in SVG order (displaced seconds are drawn out of x order).
  - The label view counts `chordnote-*` as noteheads (today it counts only `note.`/`gracenote.`).
  - Add a `chords` count (chord groups vs base notes followed by chordnotes). Dots are already counted per glyph,
    which now matches one dot per head. Add the `tuplet` count (amendment 3).
- **`training/phase1/vocab_guard.py`:** it reads `stage3_transcription.VOCAB`. With the flag on it must read
  VOCAB plus the appended extension list (one definition in `stage3_transcription.py`, for example
  `VOCAB_EXT_CHORD_TUPLET`, appended to the end, never merged), and keep quarantining anything else.

### 10.4 Token design (kept from 2.2, with two revisions)
- Kept: append-only `chordnote-<L|S><pos>`, base note = lowest head, members bottom to top, no beam suffix on
  chordnotes, accidentals matched to members by position (CM confirms this rule).
- **Revised: dots.** One dot per drawn head (see 10.3). Stage 3 reads "dots at different positions after a chord" as
  one dot for the whole chord, and repeated dots at the same position as a double dot (CM section 4).
- **Revised: split stems, same rhythm, use the same tokens as a same-stem chord.** The agnostic label is
  stem-free and CM says the music is the same. Split stems with different rhythms are not representable
  (members inherit the base duration). Stage 4 flags it (10.6), never repairs it.
- Displaced seconds: still bottom to top. For stem-down seconds this is the reverse of x order, so report a
  separate seconds metric. If it fails, the fallback is the known-lost list with its count (CM).
- New vocabulary for the arm: `chordnote-*` (positions as the converted data produce them, capped at the
  existing note range) and `tuplet.3` (optionally `tuplet.2`).

### 10.5 Gates before training, and the arm
**Data-only gates (no GPU). A failure is a no-go for training:**
1. **CTC column-collapse measurement.** On clean renders (where SVG x maps linearly to strip x), for every chord
   column (from the leftmost accidental to the rightmost head/dot) compare the frames it spans at Stage 3's
   width stride (T = W/4) with the labels it needs (accidentals + base + chordnotes + dots, plus a blank between
   identical neighbours). Report the distribution, chord columns and tuplet groups separately, at the smallest
   augmentation scale. Gate: at most 1% of chord columns infeasible (proposed; fixed at the pre-training review).
   If it fails, choose from 2.3's options and measure again.
2. **Whole-sequence feasibility.** `min_T_required <= T` for every training sample after augmentation; infeasible
   samples are dropped and counted, never left to `zero_infinity`.

**Arm definition:**
- **Init:** the frozen Phase 2 checkpoint. If Phase 2 freezes two seeds, arm seed k starts from Phase 2 seed k.
  2 seeds; every number is a range.
- **Head expansion:** copy the old rows; new rows start small, with bias at the log-prior (amendment 3; this
  replaces 2.5's "strongly negative bias"). The checkpoint load rule becomes "old VOCAB is an exact prefix".
- **Data:** Phase 2's frozen mix plus the injected chord/tuplet strips and their un-injected originals. The share
  is proposed at the pre-training review (starting point: injected strips ~20% of samples, chordnotes ~10-15% of
  note tokens). It is not tuned on any real decode.
- **Silent-no-learning count, every epoch:** samples with loss zeroed by `zero_infinity` (chord / tuplet / other).
  Gate: 0 chord or tuplet samples zeroed. On synthetic val, count chord samples with zero chordnote emissions and
  report chordnote recall. Gate (proposed): recall above a pre-registered floor by a pre-registered epoch, else
  stop as "not learning".
- **Canary:** CPM clean/distorted scored on the **full new vocabulary, with any new-token emission counted as an
  insertion** (keeps it comparable with 0.0562-0.0926 and with Phase 2's own canary). Same hard-cap/soft-floor
  style, with the margin from the measured seed noise, set before the run.
- **Metrics (synthetic val, per font, chord and non-chord strips separate):** chordnote precision (hallucination,
  the dangerous one) and recall, chord exact-match, seconds separately, tuplet recall/precision, a
  monophonic-strip SER regression check against the Phase 2 checkpoint, and chordnote confidence calibration
  (confidently-wrong rate; the BUG-011 class).
- Not in the arm: a "continue Phase 2 without new tokens" control (user decision, 10.9). Without it the arm
  makes no claim about monophonic gains.
- Preconditions as before: deterministic flags, seeded DataLoader, device and hashes in the run manifest, and an
  ml-cv-lead review of the training diff.

### 10.6 Stage 3/4/5 changes (code after the arm passes; CM gives the music reasons)
**Stage 3 (`infer_pitch`):**
- `chordnote-<pos>`: pitch from the same clef/key/`measure_alterations` path. Same `tick_onset` and
  `duration_ticks` as the base, and `current_tick` does not advance. Set `chord_id` explicitly on the base and the
  members; this replaces the dead same-onset heuristic.
- Accidentals: the pending accidentals since the last onset are kept by position and consumed by the member at
  that position. An unmatched one keeps the BUG-033 `unanchored_accidental_dropped` flag.
- Ties (CM fix A): `slur.start/end-<pos>` go to the nearest member by position. End marks are per member, not one
  pending flag.
- Tie-carried accidentals (CM fix B): a step-to-alteration map for the previous onset's members, replacing the
  single `last_note_step` / `last_note_alteration`.
- Dots (CM fix C): as 10.4, applied to every member; the cursor advances once.
- Orphan chordnote (no base in the same onset: after a rest or barline, or on the base's own position, CM V3):
  drop it, flag `review_needed`.
- Confidence: each member's is the min of its own note and accidental tokens. The chord's is the min over its
  members. Still not a trust signal (BUG-011).
- Validators (CM V1, V2, V4): interval over an octave in S/A/T (over 12 in Bass), 3+ members, out of range.
  Flag, still play.
- `tuplet.<n>`: amendment 3 (scale durations, keep `suspected_tuplet` as the flagged fallback).

**Stage 4:** already handles simultaneous notes. `_measure_ticks`/`_make_slots` count one slot per onset,
`_rescale_slots` scales members together, the confidence drop skips shared onsets, clipping is per event with
shared onsets, and `_resolve_ties` is keyed by pitch (CM section 6, verified in code). **One change is needed:**
when a bar that contains a `chord_id` overflows, emit `divisi_rhythm_split_suspected` (`review_needed`) and do
not run-scale or clip that bar (CM Q2). Out of chord scope but flagged as the highest impact: an 8-staff
SSAATTBB system is silently re-chunked as two SATB systems in Stage 2 (CM item F).

**Stage 5:** **no change is needed for "play both notes".** `voice_notes` collapses only identical
(onset, pitch) pairs, so a divisi's second, different pitch is kept and both sound. A unison collapses to one note,
which CM confirms is correct. Same-pitch clipping is per pitch, so it does not touch the other member. Optional,
low priority: divisi bars are louder (two notes at velocity 100). Scale per member only if the user notices
(CM H).

### 10.7 Held-out (Phase 4) implications
- The Phase 4 GT labels chords and divisi **explicitly**: member pitches, shared duration, same-stem vs
  split-stem, plus seconds, two-voice (different rhythms) and triplets as their own kinds. No opaque `<OOV>` for
  any of these.
- **Pre-registered: the Phase 4 model (the Phase 2 checkpoint) has no chord or tuplet support.** Report its
  chord/tuplet regions as a separate row, with expected failure and their own counts (missed members =
  deletions, hallucinated notes = insertions), next to SER outside those regions, which stays comparable with
  step 6. Never fold them into one number.
- The arm's model gets a separate, pre-registered later look at the same held-out set (or a fresh one, 10.9).
  The look is logged, and none of the arm's choices (mix, thresholds, flags) may use Phase 4 numbers.

### 10.8 Order
0. Phase 2 trained and frozen; Phase 4 GT written with explicit chord labels (10.7).
1. Injection step, converter, SVG check and guard behind the off flag; check that Phase 2 data is unchanged with
   the flag off.
2. CPM G1 with the flag on, plus the G1b-style injected check.
3. Column-collapse and feasibility gates (10.5).
4. ml-cv-lead review of the training diff and the pre-registered thresholds.
5. Arm, 2 seeds.
6. Synthetic evaluation.
7. Stage 3/4 changes (10.6) with senior-reviewer and choral-conductor review.
8. Held-out look.

### 10.9 Decisions for the user
1. Injected-data share and the voice-weight prior (10.5). Proposal above; settled at the pre-training review.
2. Add the "continue Phase 2 without new tokens" control run (one more run per seed)? Without it, no claim
   about monophonic change can be attributed to the arm.
3. Does the arm's held-out look reuse the Phase 4 set (a second logged look) or need a fresh set?
4. DS2 chord labels: stay out of arm v1 (recommended) or join after its gates?
5. Stage 2 extra-staves divisi (CM item F): open a separate ticket now? It is not chord work, but it is a silent
   wrong-voice failure today.

**User rulings (2026-10-01):**
1. Injected chords: a large share, in ALL four voices. Soprano and Alto are weighted as much as Tenor and Bass,
   because divisi is common in every SATB voice. This replaces the Bass/Tenor-leaning voice prior; the exact share is
   still set at the pre-training review.
2. Control run: YES (continue Phase 2 without new tokens, same 2 seeds).
3. The chord model is tested on a FRESH held-out set, not a second look at the Phase 4 set.
4. DS2 chord labels: OUT of arm v1.
5. Extra-staves divisi is logged as BUG-042; the fix timing is under discussion with the user.
