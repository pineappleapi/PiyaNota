# PIYA-106 - Divisi reader A8: design (2026-11-01, draft for ml-cv-lead and user review)

A8 follows A7 (`piya-106-divisi-a7-design.md`), whose four GPU runs all failed their tuning-half stop checks
(section 8 of A7: the next step is a new design with its own pre-registration). Nothing here changes A7's results.

## 1. What A7's epochs show

Tuning half, Gootville excluded (`training/phase2/eval_divisi_a7.py`, outputs
`D:/PiyaNota/datasets/phase2_divisi_a7/a7_{c,cl}_s{1,2}_tune.json`). Epoch 8 unless stated.

| Run | Selected | Head P | Triad 2+ (stop .85) | Triad member | Middle | Top | Ledger | Dyad buckets |
|---|---|---|---|---|---|---|---|---|
| C-s1 | e8 | .959 | .781 | .779 | .693 | .865 | .640 | 2nd .97, 3rd .95, 8ve .99 |
| C-s2 | e8 | .960 | .751 | .765 | .667 | .862 | .674 | 2nd .97-.98, 3rd .96, 8ve .99 |
| CL-s1 | none (P max .943) | .941 | .737 | .746 | .629 | .862 | .624 | 2nd .94-.95 |
| CL-s2 | none (P max .942) | .942 | .690 | .721 | .597 | .844 | .637 | 2nd .93-.95 |

- **Dyads already pass** their A7 7.1 floors (.90; .80 for 2nds) in every run. The failure is triads and ledger.
- **Gains flatten by e7-e8** (training-time chordnote recall +.002 at e7->e8 in C-s1); the pre-registered
  undertrained reading is false in all four runs. More epochs are not the fix.
- **CL costs chords**: head P never reaches .95 and triad 2+ is lower than C on both seeds. Layer recall is .20-.23
  with precision 1.0 (half of the layer bars are read as one voice; layer bars are about 0.8% of training bars).
- Health was clean in all four runs (canary under caps every epoch, 0 `zero_infinity`, real share .05).

**Cause (ml-cv-lead, 2026-11-01; seed 1 sample, replicated on C-s2 e8, 150 triad strips):**

| Triad shape (share with 2+ chordnotes) | C-s1 | C-s2 |
|---|---|---|
| close 3rds | .97 | .81 |
| open | .86 | .83 |
| contains a 2nd | .57 | .59 |

- Chord labels list heads bottom to top (`training/music_to_agnostic.py:409`). In a triad holding a 2nd, the
  engraver puts one head of the 2nd on the other side of the stem, so the drawn left-to-right order differs from the
  label order. The build's own x-order audit (`chord_xorder_audit.py`, `xorder_report.json`) counts 3630 of 14426
  triads (25%) out of order and 0 of 34629 dyads. CTC emits in x order, so it drops the out-of-order head: the
  middle (middle .60-.69, top .84-.86; middle recall .33-.61 when a 2nd is in the triad).
- **Frame budget rejected:** GT is about .13 tokens per frame; the tightest third of triad columns has 4.5-11 frames
  for about 3.7 tokens and scores .68-.69 vs .71-.83 for wider ones (a slope, not a cap).
- **Second, smaller error: wrong position.** 12-14% of predicted chordnotes sit on a step the column does not have,
  and ledger recall is .62-.67. Not yet split into dyad vs triad members (open check, 5.2).

## 2. The change (one variable)

**Chord heads are labelled in drawn left-to-right order.**
- The `note.*` token carries the first-drawn head (leftmost; lowest among heads at the same x). The `chordnote-*`
  tokens follow in drawn x order, bottom to top within one x. Accidentals, dots and ties keep their rules.
- The order comes from the engraving rule, not from SVG, so the same converter labels synthetic pages, the real
  A7-data stream and any GT: in a chord with a 2nd, the heads of each 2nd sit on both sides of the stem; with the
  stem up the upper head of the 2nd is displaced right, with the stem down the lower head is displaced left; a run
  of 2nds alternates sides starting from the lowest head (stem up) or the highest head (stem down), which stays on
  the normal side. The A7 audit examples fit this (e.g. stem-up cluster: low and top left, middle right). Stem direction comes from the MEI/MusicXML (`stem.dir`; the generator
  sets it for every chord).
- Pitch is a set downstream, so the reading does not change. Stage 3 drops the `chordnote_below_base` flag for a
  member that is below the base only because of x order (`stage3_transcription.py:1231-1240`); the pitch was
  already kept.
- Everything else is A7: Bach divisi corpus generator and targets (incl. the 14.8 merge change and `2nd_none`
  waiver), arm C only, Phase 2 seed k init, lr 3e-5, 8 epochs, replay .5, divisi share .20, real share .05 (cap 32),
  Gootville held out. Keeping them fixed makes A7 vs A8 a test of the label order alone.

**Not in A8:**
- Layers (arm CL). They become **A8b**: layer-bar strips oversampled 4-5x with the false-split cap kept, run only
  after A8, so the two causes are not confounded.
- More epochs, a chord-size token, a count head or a column decoder (A7 section 8 candidates): the evidence points
  at label order first.

## 3. Data sources reviewed (user 2026-11-01)

| Source | What it holds | Use in A8 |
|---|---|---|
| `D:/PiyaNota/data/chords_dataset` (11 pieces) | real divisi pieces (MuseScore + PDF + camera) | Already the A7 real stream (9 pieces, 982 train-ok strips). Handog dropped (score differs from PDF) and Dont_Stop_Me_Now excluded, as ruled in A7 14.1. **Must be relabelled** with the new order, or real and synthetic labels conflict. No overlap with the 10-piece test set. |
| `D:/PiyaNota/datasets/CameraPriMus` (3996) | monophonic; 1585 with ledger notes, 405 with 2+ ledger | No chords. Already in the 50% replay (with the 4-font re-renders). Nothing new for chords. |
| `D:/PiyaNota/datasets/ds2_dense` (1714 pages) | DeepScoresV2 boxes; noteheads carry `rel_position` and `duration` | Not usable as CTC labels without a full converter (no token order, beam roles, ties; piano grand staff, not open SATB). Possible later as a real-engraving chord probe, not A8 training data. |

## 4. Pre-registered gates (unchanged from A7)
- Stop checks and selection: A7 section 6 (triad 2+ >= .85, dyad 2+ <= .02, selection rule of A6).
- Test gates: A7 7.1 and 7.3 thresholds, both seeds, lower of Wilson and piece-bootstrap LB; real-set reading as
  A7 14.7 (10-piece PREREG frozen before any A8 checkpoint is scored on it).
- Fresh test renders (new seeds) for A8; the A7 test renders are not reused for the decision.

**Expected and at risk** (projection, not a claim):
- Triad 2+: if triads with a 2nd reach the close/open level (~.85), the overall share is ~.87 (ml-cv-lead). Pass likely.
- Middle recall (gate .80): .67-.73 even on triads without a 2nd (C-s2 .73). The order fix alone may leave it short.
- Ledger (gate LB .80 / point .85 on non-triad heads): .62-.67 over all members today; the dyad-only value is unknown.
- If 5.2 shows dyad ledger is also far below .85, ledger needs its own data change, and that is a second variable:
  it is then either added with a recorded confound, or left for A8c. Decided before any GPU time.

## 5. Checks before any GPU time
1. **Label rule vs drawing:** the rule's head order matches the SVG x order (`chord_xorder_audit.py`, extended to
   compare orders) on >= 99.5% of chords in the full build, both stem directions, and on every 2nd-cluster shape.
2. **Ledger split (open):** on C-s1 e8 and C-s2 e8, ledger recall of dyad members vs triad members and the offset of
   missed heads, on a small sample (the full tuning half was declined on 2026-11-01). Decides 4's ledger item.
3. **Converter gates:** G1 (CPM) unchanged; G1c layer tests unaffected; chord G1b sample page re-checked with the new
   order. Per strip, the token multiset is identical to A7's (only chordnote order and the note token's head move).
4. **Stage 3:** golden tests updated for the order; `infer_pitch` gives the same pitches on A7 vs A8 labels.
5. **Corpus gates and pre-GPU check** as A7 (`divisi_a7_gates.py`, `pre_gpu_check.py`), arm C only.

## 6. Runs and cost
- **Pilot:** C-s1 only (about 3.6-5.6 h of T4, Kaggle account `piamacc`). Go/no-go on the tuning half: triad 2+
  >= .85 and middle >= .75 at the selected epoch. A no-go stops A8 before seed 2 (no test half opened).
- **Then:** C-s2. The decision uses both seeds, as in A7.
- Build: one CPU build (about 5 h) with the new labels.

## 7. Safety net after A8 (user rule, choral-conductor review 2026-11-01; not part of the A8 decision)
A Stage 4 repair for chords the model still emits as successive notes, flagged, never silent:
- **Overflow merge** (inside `_repair_overflow`, before the run scaler at `stage4_reconstruction.py:1237`): merge an
  adjacent, equal-duration pair a 2nd apart (no rest or barline between) into one chord only when the merge makes
  the bar total exactly the meter, exactly one set of merges does so, the onset lines up with the other voices, and
  the bar is not a pickup, a final bar or an off-grid (tuplet) overshoot. Today such bars are scaled to the wrong
  rhythm (5 quarters) or clipped as `suspected_missing_barline` (two whole notes).
- **Beam grammar** (beamed values only): two notes a 2nd apart with the same beam state in a row (e.g.
  `note.beamedRight1-L2 note.beamedRight1-S2`) is a split chord; a melody never repeats `beamedRight`.
- Every merge is flagged `suspected_split_chord` + `review_needed`; both pitches play at the same onset and
  duration (divisi). Opposite-stem pairs with different rhythms are flagged only. The firing rate is reported: a
  high rate means A8 did not work.

## 8. Meanwhile
A7 section 8 path 4 applies to v1: chords stay off, every detected chord column is flagged, Soprano and Tenor play
the top note. **Confirmed by the user 2026-11-01.**
