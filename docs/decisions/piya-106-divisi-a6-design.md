# PIYA-106 - Divisi chord reader A6: design (2026-10-18)

**Status:** approved by the user on 2026-10-18, including the section 9 calls. ml-cv-lead signed off on
2026-10-18 on condition that the fixes marked "(ml-cv-lead sign-off)" below were made; they are now in. Next step:
freeze as Amendment A6 of `piya-106-divisi-arm-freeze.md`. Nothing is built yet.

**Phase 4 statement:** the author has not decoded, transcribed or viewed any Phase 4 photo at notation level. No
value below comes from Phase 4, `piyanota_dataset` or the fresh-photo eval sets.

## 1. Why

The divisi train-1 run (`piamac/piyanota-divisi-train-1`, commit 22c49b2) failed the section 5 gates in both arms
and both seeds. v1 ships without chord reading. Same-stem divisi (two or three noteheads on one stem in one
staff) is therefore lost silently, and the user needs it read. The user's instruction (2026-10-18): "Just make
sure the model will now be able to detect all manners of divisis properly, expose it to the data it needs". The
user confirmed that three-note chords and seconds (two adjacent notes drawn side by side) occur in their scores.

## 2. Evidence (zero-GPU diagnostic, synthetic divisi val, 1123 strips / 1927 chord columns)

Scripts and JSON are scratch files from this session (`divisi_diag.py`, `divisi_checks.py`). Head-level scoring:
every notehead of a chord column counts, the lowest included.

| | full fine-tune arm, s1-s2 | head-only arm (frozen v1 backbone), s1-s2 |
|---|---|---|
| head recall / precision | .750-.782 / .842-.843 | .319-.322 / .711-.713 |
| exact chord set | 54-59% | 6-7% |
| extra heads on plain notes | 6-7 | 17-19 |
| recall 2nd / 3rd / 4th-5th / 6th / 8ve | .03-.16 / .63-.73 / .45-.47 / .57-.58 / .27-.32 | .44-.53 / .47 / .23-.24 / .28-.31 / .24-.25 |
| recall triad heads | .45-.46 | .07-.08 |

- **The frozen v1 features do not carry the extra head.** A linear probe on them peaks at P .67 / R .54, and
  posterior decoding on the head-only model never reaches P .90. Options D0 and A' are dropped.
- **Posterior decoding on the arm does not help either.** At its best threshold with P >= .90, recall drops to
  .59-.65.
- **The arm sees chords but misplaces heads.** Missed heads are mostly replaced by a wrong position (600-615)
  rather than dropped (210-330). Wrong positions are 55-58% one staff step off and about 40% two steps off.
- **Recall follows training count.** Train chord columns: 3rd 5041, 6th 2985, 4th/5th 2068, 8ve 1081, 2nd 194,
  triads 371, whole-note chords 31. Octaves whose upper head sits at steps 9-11 (64-81 train examples each) are read
  0-1 times out of 44. No chord member was ever drawn above step 14, and only 8 at step 0, so ledger-line chord
  members are unseen.
- **The arm was still learning.** Chordnote recall per epoch was .19, .42, .54 (s1) over 3 epochs.
- **Resolution is enough for displaced seconds.** In the 64 px strips the interline is about 7 px (p10 5.5,
  p90 8). A displaced second sits about one notehead width (8-9 px) to the side, about 2 CNN frames at stride 4.

ml-cv-lead's read (2026-10-18): limited by data mix and epochs, not by resolution or the CTC label design.

## 3. Decision: route B' (full CRNN fine-tune on a rebuilt balanced divisi corpus)

- **Model.** Same CRNN, extended vocab (536 tokens), same label order: main `note.*` (the lowest head), then
  `chordnote-*` ascending, then dots. Start from Phase 2 seed k for seed k, lr 3e-5, CPM replay 0.5, as in the
  frozen arm.
- **Epochs.** 8, evaluated every epoch. The checkpoint is selected on the tuning half of val (the crc32-even val
  pieces, section 9) and reported on the test half and on the held-out chord font.
- **Fallback (pre-set).** If 2nd recall is below .50 at epoch 4 in both seeds, the run continues for the other
  intervals, and seconds go to route A. Route A is a per-column crop CNN on the native-resolution strip source,
  designed then and not now.

## 4. Corpus rebuild (`training/phase1/build_corpus.py` `inject_divisi`, new frozen constants)

Targets are shares of chord columns. As in section 3 of the freeze doc, the realised mix is logged, not assumed,
and the gate in section 6 checks it.

- **Member sampling.** 60% free diatonic members (any scale degree at the drawn interval from the base note,
  spelled in the key), 40% copied from a pitch another voice sounds. Copy-only is why 2nds and octaves were rare.
- **Intervals (dyads).** 2nd 12%, 3rd 16%, 4th 12%, 5th 12%, 6th 12%, 7th 5% (new class, minor 7ths only),
  8ve 16%. (choral-conductor 2026-10-18: 7ths are rare inside one section and free major 7ths do not occur;
  ml-cv-lead moved the freed 3 pp to octaves, the weakest bucket after 2nds.)
- **Musical constraints (choral-conductor, 2026-10-18).** Free members use only accidentals already in force in
  that bar (key signature plus accidentals already sounding in the bar, in any voice); minor keys default to natural
  minor and raise the 7th (and 6th) only when the bar already does. Copied members may bring their own accidental.
  Rejected and re-drawn on one stem: augmented 2nds and 4ths, diminished 5ths and 7ths, augmented unisons and any
  chromatic 2nd. Span at most an octave; at most 3 notes per stem; a member crosses the adjacent voice's sounding
  note in at most 10% of chord columns.
- **Triads.** 15% of chord columns, including inversions, triads containing a 2nd and 3-note clusters.
- **Seconds.** Every same-stem 2nd is drawn displaced by Verovio. Stems both up and down, whole-note seconds
  included. At least 30% of 2nds have stems down, so both displacement sides are seen. Seconds are reported in two
  buckets, **2nd stems up** and **2nd stems down** (ml-cv-lead sign-off: "displaced 2nd" alone equals the 2nd
  bucket).
- **Durations.** Whole 12%, half 20%, dotted 15%, quarter 33%, beamed eighths and sixteenths 20%. Targets are chosen
  with duration-weighted sampling, because the source pieces rarely contain whole notes.
- **Accidentals.** At least 12% of chord columns carry a drawn accidental on a member, including on both heads
  (lowered from 20% because free members may not add accidentals; ml-cv-lead 2026-10-18).
- **Positions.** Members stay inside the voice's range plus 2 semitones (S C4-A5, A G3-D5, T C3-A4 written an
  octave up under the treble clef, B E2-E4), clipped to staff steps -5..13 (at most 2 ledger lines; L1 = 0), and
  are near-uniform over each voice's allowed steps; the realised spread is logged. Steps -6 and 14..16 stay in the
  vocabulary but are never trained, and any of them emitted on val counts as a hallucination. Members whose
  accidental token would be out of vocabulary are re-drawn, never quarantined.
- **Ties.** Tied chords at 8% only if the converter's tie path passes a G1b re-check first. If not, they stay out,
  and the gap is recorded as known-lost.
- **Density.** 25% of strips carry no chord (hallucination canary). The rest have chords in 20-60% of note
  columns. This replaces the old 6-14% chordnote-share gate.
- **Fonts.** All five Verovio music fonts. One font is held out of chord training: it still appears in plain
  strips, because Phase 2 already trained on all five. **Builder's call: Gootville** (furthest from the MuseScore
  look of the user's scores, so it is not the font the test cares most about). This is a held-out chord font,
  not a held-out font, and is reported as such.
- **Split.** Each `<piece>__divisi` copy inherits its source piece's Phase 2 split (section 9). Val is 25 pieces,
  so the tuning and test halves are about 12 pieces each, too few heads in the rare buckets.
- **Test render (ml-cv-lead sign-off).** A separate render of the test-half val pieces in all five fonts, with 3
  injection seeds distinct from the corpus seed. Targets: at least 600 in-font heads and at least 300 held-out-font
  (Gootville) heads per bucket. Buckets: 2nd stems up, 2nd stems down, 3rd, 4th, 5th, 6th, 7th, 8ve, triad head,
  ledger-line member (step <= -2 or >= 10). Never used for training or selection. The 7th bucket may fall short
  at 5%: it is then reported as underpowered, and its gate is not lowered.

## 5. Checks before any GPU time

1. **Converter labels.** G1b re-check (user-scored) on the new forms: displaced 2nds both stem directions,
   whole-note 2nds, 7ths, clusters, triads with accidentals, ledger-line members, tied chords if included.
   choral-conductor confirms how free members (7ths especially) are spelled in minor keys before the page is built.
2. **Corpus gates.** Realised mix within ±3 pp of every target in section 4. Held-out-font chord strips absent from
   train. No Phase 1 or Phase 2 strip changed (A5 equality check, as before). Realised heads per bucket in the test
   render counted against the section 4 targets; a short bucket gets more renders now, never after training.
3. **Local smoke.** A CPU smoke of `train_phase2.py` on the new manifest gives a finite loss and reloads identically.

## 6. Pre-registered gates (both seeds must pass; reported as a range)

- **Head recall** (95% lower bound on the test render): at least .90 for each of 3rd, 4th, 5th, 6th, 7th and 8ve;
  at least .80 for 2nd stems up and 2nd stems down; at least .85 for triad heads and ledger-line members. The
  Wilson bound and a piece-cluster bootstrap bound are both reported; the lower of the two decides (heads in one
  piece are correlated).
- **Exact chord set:** at least .75 for triads.
- **Precision:** head precision at least .95.
- **Hallucination:** extra heads on plain note columns at most 0.5%; chordnote hallucination on un-injected strips
  at most 0.1 per 100 notes, with the number of notes reported.
- **Accidental members (diagnostic, not a gate):** recall of chord members that carry an accidental, with n and the
  Wilson bound.
- **Held-out chord font:** recall within 5 pp of the in-font recall.
- **Non-regression:** canary clean/distorted SER under the existing caps (seed 1 .03695/.05317, seed 2
  .03738/.05496); non-chord val SER at most +0.5 pp over Phase 2 v1; dev pitch recall drops by at most 1 pp against v1 (a paired
  note-level McNemar test is reported alongside).
- **Training:** 0 samples zeroed by zero_infinity.
- **Confidence (diagnostic, not a pass gate):** wrong heads score lower confidence than right heads, with AUROC at
  least .80. Otherwise it is logged as the BUG-011 failure class.
- **Kill rule:** if B' fails any gate other than 2nds, there is no second B' run; v1 ships with chords off. If only
  the 2nd gates fail, the chord model ships with 2nds flagged `chord_unvalidated` and route A is designed.
- **What a pass means:** passing these gates is synthetic evidence only. A small real-score divisi set is diagnostic
  only, never a gate.

## 7. Shipping

- Even when it passes, every chord event is flagged `chord_unvalidated` / `review_needed` until a real-photo check
  exists, in the same way ClefKeyNet is flagged.
- Pitch comes from `infer_pitch`, unchanged: a chordnote takes the clef, key and accidental state of a normal note.

## 8. Out of scope here

- **Split-stem two-voice writing** (stems up and stems down in one staff, often with different rhythms) is still
  only flagged (A3). User decision (2026-10-18): it is in scope, but as a separate step after A6 with its own
  design and gates. The recommended approach is a second CTC output on the same network rather than a separate
  model, trained on closed-score chorales. A split part plays **merged into its own voice's single track** (for
  example both soprano lines in the Soprano track), not as S1/S2 tracks.
- **Unison divisi** (one head with two stems) plays as one note, which is the right sound, so nothing changes.
- **Phase 4.** No A6 checkpoint is run on Phase 4 until the gates pass and the user decides.

## 9. Calls made by the author (builder check, 2026-10-18; open to user correction)

- **Checkpoint selection metric.** Pick the epoch with the highest minimum per-bucket head recall on the tuning
  half, among epochs with head precision >= .95 and canary under its caps. Ties go to the earlier epoch. 2nd
  buckets count unless the 2nd fallback has fired, in which case they are dropped from selection only. The
  epoch-4 fallback check uses the tuning half only.
- **Split.** Divisi pieces keep their Phase 2 piece split (each `<piece>__divisi` copy inherits the split of its
  source piece), so no Phase 2 train piece reaches A6 val. "Tuning half" and "test half" are the crc32 even and
  odd halves of val **pieces**, not strips. Non-chord val SER is compared on the Phase 2 val manifest, unchanged.
  If a bucket cannot reach 300 heads in the test half, its gate is reported with the Wilson bound actually reached
  and marked underpowered. It is not passed by default.
- **Size and mix.** The divisi corpus covers every Phase 2 piece as before. The divisi share is frozen at 20% ±3 pp
  of the synthetic (non-CPM) strips per epoch, train-1's realised share (6314 of 30311 = 20.8%); the 25%
  chord-free divisi strips count inside it, a fresh draw from the divisi pool is made each epoch, and the share
  is logged each epoch; CPM replay stays
  0.5 (ml-cv-lead sign-off: chord-head exposure is already about 10x train-1, so a higher share risks the canary). If 8 epochs x 2 seeds will not fit one 12 h Kaggle session,
  each seed runs in its own session. The builder measures epoch time on the smoke before launch.
- **Control arm.** Dropped. Non-regression is checked directly against Phase 2 v1 on the same sets. The confound
  (chord data versus 8 epochs of extra training) is recorded and not resolved. ml-cv-lead: acceptable, because A6
  decides only whether to ship against v1, and the kill rule ships v1 if plain reading regresses.
- **Dev pitch recall.** Measured with chordnote tokens stripped, so it needs no Stage 3/4 chord code. It checks
  only that the plain reading did not get worse.
- **2nd fallback.** The 2nd strips stay in training unchanged. Only gates and selection change. No data changes
  mid-run.

## 10. Left to the builder

- How free diatonic members are spelled in minor keys and after mid-piece key changes. Use music21's key context.
- Re-draw limits when a target cannot be met within a piece. Log the shortfall rather than looping.
- The Kaggle kernel layout, which is a copy of `phase2_divisi_kernel.py` with a new run table, epochs and pinned shas.
- The exact duration-weighting scheme, as long as the realised mix passes section 5.2.

## 10. Feasibility (Task 1)

Counted by `training/phase1/divisi_a6_feasibility.py` over the 337 train-split Bach pieces of the full-2 Phase 2
manifest (all 337 found and four-part), chord-capable notes only (not tied, grace or tuplet), after `_normalise_clefs`.
Full numbers by voice: `docs/decisions/piya-106-divisi-a6-feasibility.json`.

| class | count |
|---|---|
| whole | 230 |
| half | 4838 |
| dotted | 2461 |
| quarter | 41650 |
| beamed | 29145 |
| other | 0 |
| total | 78324 |

Rule: whole count must be at least 0.12 x 0.4 x 78324 = 3759.6. It is 230 (0.29% of notes), so duration weighting alone
cannot reach 12% of chord columns. **Decision: `merge_to_whole_needed = true`; Task 3 enables `merge_to_whole`.**
