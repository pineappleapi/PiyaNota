# PIYA-106 - DeepScoresV2 Dense to Camera-PrIMuS agnostic tokens: conversion design (2026-09-30)

Author: ml-cv-lead. Status: **design only, no converter code.** Serves Phase 1/2 of
`docs/decisions/piya-106-ser-15-plan.md`. It adds DS2 staves as CRNN training data, for engraver/font diversity and
weak-class coverage.

**Verdict: feasible, with a CONDITIONAL GO to build.**
- Barlines are recoverable, and `rel_position` is verified (below).
- DS2 is a *secondary* source: about 1.1-1.4k unique musical staves, rendered in 4-5 fonts.
- It does not replace the PrIMuS-sourced SATB engine.
- Nothing trains on it until gates D1-D3 (section 6) and the ablation in section 8 pass.

## 0. What was measured (read-only inspection, 2026-09-30; scripts in the job temp dir, diagnostic)

| Fact | Value | Consequence |
|---|---|---|
| Barline class in JSON | **none** (136 deepscores classes, no barline) | recover from segmentation PNG (section 4) |
| Barline pixels in `segmentation/*_seg.png` | colour BGR (198,172,0), 154k px on 12 pages, 1% inside any JSON box | usable as the barline source |
| Staff lines in seg PNG | BGR (175,144,158) | not needed (staff box suffices) |
| Text (instrument names, bar numbers, tempo words) | ink, **unlabelled** in the seg PNG (white) | ignored in labels; Stage 1 mask handles it as at serve |
| `rel_position` convention | **steps above the middle line (L3 = 0), up positive**. CPM p = rel_position + 4 | verified below |
| `rel_position` vs geometry, 400 pages per split | 97.8% exact. Mismatches are offsets of 13-158 steps (the head belongs to another staff) | staff assignment = the staff where geometry equals rel_position |
| Staff box | top line to bottom line; height 66-68 px (interline about 16.75 px) | step = height / 8 |
| Duration comment | `4`, `8.`, `2..`, `log = -1` (breve), and tuplets as `16*2/3`, `8*4/5`, `16*107/120` | dots are in the comment; `*` means drop |
| Grace / cue (`*Small`, `graceNote*`) annotations | **0** in dense train and test | any drawn grace is unannotated ink, caught by the unexplained-ink check |
| Multirest (`restHBar`) number | **not annotated** (no box above any of the 27 in test) | drop the staff |
| Stem-to-head x gap (black/half heads, 12 pages) | 88% at 0-1 px, 13% at 10 px or more, 0.2% with no stem | association must be calibrated (section 3) |
| Fonts (train pages) | emmentaler 293, no-aug (LilyPond default, i.e. Emmentaler) 294, lilyjazz 285, beethoven 284, gonville 206 | **one engraver (LilyPond), 4 fonts** |
| Split hygiene | train 559 pieces / test 249. **190 test pieces and 192 of 226 test (piece, page) also appear in train, in another font** | DS2's split is by rendering, not by music |

**Side finding for BUG-004 (not edited here; for the caller to log):**
- DS2's official test split re-renders mostly the same pages as train, in a different font.
- So even a correct `split="test"` mAP for the YOLO detector is not a music-independent number.

## 1. Class to token mapping

Position p: L1 = 0, S1 = 1, and so on (`position_suffix`). Tokens are **positional**, so no pitch is needed.

| DS2 class | Token | Position source |
|---|---|---|
| `clefG` (no `clef8`) | `clef.G-L2` | geometry check only: bbox vertical centre within ±1 step of the per-font G-L2 mode, else drop (French/G-L1) |
| `clefG` + `clef8` **below** | `clef.G-L2` (the treble-8vb tenor convention G1b uses; the "8" is unlabelled) | as above |
| `clefF` | `clef.F-L4` | ±1-step check against the per-font F-L4 mode, else drop (F-L3) |
| `keySharp` / `keyFlat` | `accidental.{sharp,flat}-P` | label = `_key_sig_tokens(clef, count+kind)`; geometry only **verifies** the table |
| `keyNatural` (cancellation) | **drop the staff** (v1) | a cross-converter convention is open, see section 4 |
| `timeSig0-9` | `digit.N-L4` (upper), `digit.N-L2` (lower); adjacent digits join (`digit.12-L4`) | upper/lower by centre vs the middle line |
| `timeSigCommon` / `timeSigCutCommon` | `metersign.C-L3` / `metersign.C/-L3` | fixed |
| `notehead{Black,Half,Whole,DoubleWhole}{OnLine,InSpace}` | `note.{dur}-P` or `note.beamed{Right,Both,Left}{flags}-P` | P = rel_position + 4 |
| `augmentationDot` | `dot-P'` with P' = P+1 if P is on a line, else P (converter rule) | count must equal the dots in the duration comment |
| `accidental{Sharp,Flat,Natural,DoubleSharp,DoubleFlat}` | `accidental.{glyph}-P` of the attached head | head position, not glyph geometry (flats' bboxes sit high) |
| `rest{DoubleWhole,Whole,Half,Quarter,8th,...,128th}` | `rest.{dur}-P` at the **CPM fixed positions** (whole L4, half/others L3) | geometry within ±1.5 steps of that, else a two-voice drop |
| `fermataAbove` | `fermata.above-S6` before the note/rest it sits over | fixed S6 (CPM) |
| `tie` | `slur.start-P` after note A, `slur.end-P` before note B | same P, adjacent heads (section 3) |
| barline (seg PNG) | `barline-L1` (single, double, final and repeat all map to one token, as the converter does) | section 4 |

**Ignored (drawn, never labelled; the model must learn to skip them):**
- `slur` (phrase slurs, a real benefit, see section 8), articulations (`artic*`, including staccato dots), `dynamic*`
  and hairpins, `fingering*`, `ornament*`, `strings*`, `keyboardPedal*`, `caesura`, `segno`, `coda`, `brace`,
  `repeatDot`, `ledgerLine` (implied by P), `stem`, `beam`, `flag*` (used for duration checks only).

**Drop the staff:**
- `clefCAlto`, `clefCTenor` (project scope, and the old `clef.C-L3` collapse), `clef15`,
  `clefUnpitchedPercussion`, `clef8` above, `clef8` on F.
- `tuplet*`, `tupletBracket`, any duration with `*`.
- `tremolo*`, `ottavaBracket`, `arpeggiato`, `fermataBelow` (the vocabulary has no below; usually a lower voice),
  `restHBar`, `keyNatural`, `graceNote*` / `*Small` (none exist today; the rule is kept).
- Any token not in the CRNN checkpoint's vocabulary (e.g. an extreme ledger position): drop, never map to the
  nearest token.

## 2. Staff position

- **Heads:** p = rel_position + 4. Assign each head to the staff where round((staff_mid_y - head_cy) / step)
  == rel_position. Zero or two matches: drop the staff (cross-staff note or ambiguity).
- **rel_position verification (a D1 sub-gate, rerun on the frozen converter):**
  - On every kept staff, 100% of heads must satisfy geometry == rel_position within ±0.35 step.
  - Per font, report the residual (head_cy vs the predicted line/space y) distribution. A shift above 0.2 step in
    any font stops the build (it would mean a per-font bbox bias).
  - Cross-check class vs parity: `OnLine` ⇔ P even, `InSpace` ⇔ P odd. It must hold on 100% of kept heads; this is
    a free, independent check.
- **Non-head glyphs** use the staff box: y → p = round((staff_bottom - anchor_y) / step), with a per-class anchor:

  | Class | Anchor |
  |---|---|
  | sharp, natural, double sharp, keySharp | bbox centre |
  | flat, double flat, keyFlat | bbox bottom - 0.5 × interline (bowl centre); calibrate per font on key signatures, whose true positions come from the table |
  | dots | bbox centre |
  | rests, clefs | only checked against fixed positions |

- **Tolerance:** snap to the nearest step if |residual| ≤ 0.35 step. Otherwise the glyph is ambiguous: drop the
  staff, never round.
- **Inline accidental → head:** the nearest head to the right with gap ≤ 1.5 interline, whose centre lies inside
  the accidental's vertical extent (for flats, the lower 60%).
  - The head's P is the token position. The anchor estimate must agree within ±1 step, else drop.
  - An accidental with no head: drop.

## 3. Duration, beams, dots, ties

- **Duration** from the comment. The head class must agree:
  - Black ⇔ {4, 8, 16, 32, 64, 128}; Half ⇔ 2; Whole ⇔ 1; DoubleWhole ⇔ breve (`double_whole`).
  - A disagreement drops the staff.
- **Stem association:** stem x-range within `STEM_TOL` of the head's left or right edge, and the stem y-range
  covering the head centre ± `STEM_TOL`.
  - `STEM_TOL` is calibrated on 20 pages (starting point 0.15 interline), with the 13% at ≥10 px explained before
    freezing. They are likely stems attached at the head centre in some fonts, or side-shifted chord heads.
  - Requirement: every non-whole head has exactly one stem, and every stem has at least 1 head. A stem with more
    than 1 head is a **chord** (drop).
  - Direction = the stem's far end above or below the head.
- **Beam groups:**
  - The stem tip (far end) must fall inside a beam's **`o_bbox` polygon** dilated by 0.15 interline. Do not use
    `a_bbox`: on sloped beams it swallows neighbouring stem tips.
  - Union-find the stems over shared beams. Order each group by x: first → `Right`, last → `Left`, middle → `Both`.
  - The flag digit is the **note's own** flag count from its duration (the converter convention: dotted eighth +
    sixteenth = `beamedRight1 … beamedLeft2`). Beam counts at a stem are only a check: they must be ≥ 1 and ≤ the
    flag count.
  - Drop the staff for any of:
    - a single-stem group;
    - a rest under a beam span;
    - a group whose heads sit on two staves (cross-staff beam);
    - a beamed head with duration ≥ quarter;
    - an unbeamed head of an eighth or shorter without a flag of the same count (`flag8th*` = 1, `flag16th*` = 2, …).
- **Dots:** count the `augmentationDot` boxes whose centre is right of the head/rest, within 2 interline and
  ±0.75 step of P'.
  - For heads: must equal the dots in the comment. For rests (no comment): the count gives the dots.
  - A dot that no head or rest claims (for example the second voice's dot) drops the staff.
- **Ties:** a `tie` box's left end is within 1 interline of head A's right edge, and its right end within 1
  interline of head B's left edge, with A and B consecutive heads of the same P.
  - A tie box that starts after the staff's last head and runs to the right edge gives `slur.start` on the last
    note, if P matches.
  - A tie box that ends before the first head, after the header, gives `slur.end` on the first note (a tie across
    the break).
  - Anything else (different P, not adjacent, two candidates) drops the staff.
  - Accidentals on a tied continuation are labelled as drawn (DS2 labels are "what is drawn", the same semantics as
    the `verovio` dialect).
- **Slurs:** always unlabelled, including a slur between adjacent same-pitch notes. This matches
  `music_to_agnostic.py`, which ignores `<slur>`. Report the count of same-pitch-adjacent slurs so G1b/D2 can look.
- **Token order per event**, identical to the converter: `fermata`, `slur.end`, `accidental`, note/rest, `dot`×n,
  `slur.start`. Events are ordered by head/rest x. Header and barline tokens are placed by x.

## 4. Header, key, meter, barlines

- **Header:** the leftmost clef, then key-signature glyphs (x after the clef, before the first head or rest), then
  meter.
  - **The key is labelled from the table**: `_key_sig_tokens(clef, n + kind)`. Geometry must reproduce the table's
    first n positions exactly, else drop. This removes geometry noise from the most common header tokens.
- **Continuation staves:** LilyPond prints clef + key and no meter on each system after the first. That is exactly
  our continuation layout, and it is labelled as drawn. DS2 is a natural source of it.
- **System-start staff with no clef** (250 staves in train): drop. It means a staff-assignment failure, not a real
  layout.
- **Mid-staff changes:** a clef, key or meter glyph after the first event is labelled in x-order (the converter
  emits the same). A C clef anywhere means drop. A key change that shows cancellation naturals means drop (`keyNatural`).
- **Open convention question (it blocks both converters, not only DS2):**
  - How are cancellation naturals labelled?
  - How are courtesy key/meter glyphs at the end of a system labelled? LilyPond draws them.
  - Today `music_to_agnostic.py` does not label courtesy glyphs, and the G1b check is pending.
  - Decide once, in G1b, and apply the same rule in both converters. **Until then, drop DS2 staves where a key or
    meter glyph follows the last barline.**
  - R1 (key continuity) uses cancelling naturals as evidence, which argues for labelling them as
    `accidental.natural-P` at the cancelled key's table positions.
- **Barlines, not a blocker:**
  1. In the seg PNG, take the connected components of colour BGR(198,172,0) (±2 per channel) inside the staff band.
  2. Keep components with height ≥ 0.8 × staff height and width ≤ 0.6 interline.
  3. Merge components closer than 1.2 interline into one `barline-L1` (double, final and repeat barlines are one
     token in CPM). Components left of the clef (the system-start line) are ignored.
  4. **Verify before freezing, on 20 pages covering all 5 fonts:** confirm the colour is a barline in every font, and
     that repeat and final barlines use the same colour (if they differ, add the colours and re-verify).
  5. **Cross-check with durations** (D1): the barline count must equal the bar count implied by duration sums on
     every kept staff (section 6).
  6. **Fallback if the seg colour fails on a font:** a vertical-run detector on the image, masked by every JSON box.
     This is a different method and needs its own D1 check. Do not mix methods silently: record which one each staff
     used.
- **Final barline at the right edge:** labelled when drawn. This agrees with converter output, not with CPM gold's
  defect (see the plan: the CPM replay labels are being cleaned the same way).

## 5. Staff drop rules and expected yield

Survey of train (14,304 staves). Reasons overlap:

| Reason | Staves | Detection |
|---|---|---|
| x-stacked heads (chord / unison) | 3,940 | x-overlap > 0.5 head width |
| close heads (side-shifted second, two voices offset in x) | 2,350 | Δx < 1.05 head width at a different P |
| displaced rest (two-voice proxy) | 2,013 | rest centre > 1.5 interline from the middle line |
| C clef | 1,541 | class |
| no notes (tacet / rests only) | 1,365 | no heads (keep ≤ 2% as rest-only, otherwise drop) |
| tuplet | 787 | `*` in duration, `tuplet*` |
| rel_position mismatch | 523 | section 2 |
| key naturals / clef15 / arpeggio / fermata below / ottava / tremolo | 271 / 203 / 148 / 134 / 129 / 58 | class |
| no clef | 250 | section 4 |

- **Two voices on one staff:** any one of the following drops the staff.
  1. Opposite stem directions on heads within 1.5 head widths in x.
  2. A displaced rest.
  3. A dot or tie that no head claims.
  4. **A per-bar duration sum equal to k × the meter with k ≥ 2 (the decisive test).**
- **Yield:**
  - After the class/geometry rules: **6,309 staves (44%) from 463 pieces**, about 110k heads. By font: emmentaler
    1,407, no-aug 1,404, beethoven 1,320, lilyjazz 1,261, gonville 917.
  - Clefs: G 3,740, F 2,036, G+8 254, F+8 279 (dropped).
  - Assume 70-85% survive stem/beam/barline/bar-length checks: **about 4.4-5.4k strips**.
  - Unique music content is about 1.0-1.2k staves (each piece is rendered in about 4.6 fonts).
  - That is a font-diverse but music-narrow set, less than 2% of full PrIMuS content.
- **Only DS2 *train* is used.** DS2 test is excluded from CRNN training *and* from CRNN evaluation (piece overlap
  makes it non-independent anyway).

## 6. Quality gates (pre-registered; the converter is frozen by commit hash before D1-D3 run)

- **Held-out pieces:** before writing any rule, set aside a seeded random 10% of DS2-train **pieces** (all fonts of
  a piece together) as `ds2_holdout`.
  - Rules are developed on the other 90%.
  - D1 and D2 run on `ds2_holdout`. The same logic applies as the held-out PrIMuS G1: the rules must not be read off
    the gate set.
- **D1, automatic, on every candidate staff** (a failure drops the staff; the *rate* is the converter-health gate):
  - Bar length: each bar between two barlines must sum exactly to the running meter.
    - Exempt: the first bar of the first system of `page-1` (a pickup); the last bar of the piece's last staff.
    - A bar that crosses a system break (both halves must sum to the meter) is allowed only if a tie or a missing
      barline marks it; otherwise drop.
    - Meter unknown on a continuation page (no time signature on the page): accept only if all full bars on the page
      share one sum. That sum becomes the meter, for checking only (no meter token is emitted).
    - Whole rest alone in a bar = a full bar in any meter.
  - The barline count equals the bar count from the durations.
  - Head parity (`OnLine`/`InSpace`) matches P; the key-signature geometry matches the table; the dot counts match;
    the flag/beam counts are consistent; each non-whole head has exactly one stem.
  - **Every annotation in the staff band** is either mapped or on the ignore list.
  - **Unexplained ink:** a seg-PNG white (unlabelled) ink component inside the staff lines ±1 interline, larger than
    0.3 interline², that is not text-shaped left of the clef → drop. This catches unannotated grace notes and glyphs.
  - **Accept the converter only if** ≥ 80% of the candidate staves in `ds2_holdout` pass D1. Below that, the rules
    are wrong, not the data: diagnose, and do not loosen tolerances to pass.
  - Report pass rates per font. No font may be more than 10 pp below the mean.
- **D2, human, 30 strips from `ds2_holdout`**, checked as the model sees them (the final 64 px strip plus a 1:1
  tile, next to the label):
  - Stratified by 6 per font group (emmentaler + no-aug count as one group, 5 groups).
  - Hard cases present at least once each:
    - continuation staff with a key;
    - treble-8vb;
    - mid-staff clef change;
    - meter change;
    - a tie across a system break;
    - a mixed 8th/16th beam with a dotted rhythm;
    - inline naturals and a courtesy accidental;
    - every rest type present;
    - a fermata;
    - a phrase slur and staccato dots (these must be *unlabelled*);
    - a first staff with instrument-name text.
  - **Pass: 0 systematic errors** (the same rule failing twice, or any rule-caused error), and ≤ 2 isolated token
    errors in total. Any fix means a fresh 30 (new seed), and D1 is rerun.
- **D3, cross-converter consistency:** 10 DS2 staves are hand-transcribed to MEI, then converted by
  `music_to_agnostic.py` (`verovio` dialect) and by the DS2 converter. Token agreement must be 100% on the shared
  conventions (header, beams, ties, dots, barlines). A difference is a convention conflict to resolve, not noise.

## 7. How DS2 strips are cut (train = serve)

- **Through the frozen code (9b9e12f), not a direct crop.** A direct crop is what BUG-016 warns against: a
  different extent, no mask, no `paper_fill()`.
  1. Camera augmentation on the **page** (the Phase 1 step 5 recipe), where it is used.
  2. `stage1_preprocessing.preprocess_score_page` → the grey `strip_source` (with `paper_fill()`), the non-staff-ink
     mask, and the tracked staves.
  3. Staff boxes come from Stage 2's classical path (`_classical_boxes`). Cut with Stage 2's `_crop_and_resize`
     (INTER_AREA to `STRIP_HEIGHT`).
  4. **Not** `detect_staff_regions`: it caps at 16 boxes and groups by 4 (SATB). DS2 pages hold about 10.6
     staves in piano/orchestral layouts. That grouping is not part of the pixel path.
- **Label join:** match tracked staves to DS2 staff boxes one-to-one, through the known page transform (identity
  plus the augmentation warp): centre within 0.5 interline, in top-to-bottom order.
  - Any page where the counts differ, or any staff unmatched: drop the page. This is the plan's label-join rule, so
    labels cannot shift.
- **Residual train/serve gap:**
  - At serve time the boxes come from YOLO when YOLO and the tracker agree. Measure the edge difference between
    YOLO and classical boxes on dev pages.
  - If it is above 0.1 interline, add box jitter of that size in training.
  - YOLO itself was trained on DS2 train, so it would be over-accurate on these pages. That is another reason not to
    cut with it.
- **Resolution:** DS2 pages have an interline of about 16.75 px at 2368 px width, so they need no upscale. Record the
  staff height in px of each strip. The camera/digital dev strips are 30.5-31.25 px at 64 px input, and DS2 must land
  in the same band after the crop (report it).
- **Camera augmentation:** use the same page-level recipe and parameter ranges as the Phase 1 renders, including the
  minimum surviving dot/flag area rule.
  - Instrumental 16th/32nd beams are dense, so the erosion regime will delete secondary beams more often. Apply the
    same survive-or-drop rule to secondary beams, or the model learns to invent 16ths.
- **Record, per strip:** DS2 filename, font, piece, staff index, converter commit, Stage 1/2 commit (9b9e12f),
  augmentation parameters and seed.

## 8. ML view: value, risks, weighting, ablation, go/no-go

- **What DS2 adds that the other sources don't:**

  | Source | Content volume | Engraver / fonts | Layout | Weak-class coverage |
  |---|---|---|---|---|
  | Full PrIMuS via the SATB engine | about 87k incipits | Verovio, 5 SMuFL fonts | our SATB layout, continuation systems | volume for naturals, dotted 8ths, 8th rests, ledgers |
  | Verovio chorales | about 7k strips, narrow | Verovio | true SATB | narrow rhythm vocabulary |
  | **DS2** | **about 1.1k unique staves × 4.6 fonts** | **LilyPond engraver; Emmentaler (MuseScore 3's default), Beethoven, Gonville, LilyJAZZ** | full-width, continuation, instrument labels | **negatives:** phrase slurs, staccato, dynamics, hairpins drawn but unlabelled; 254 treble-8vb |

  - For the weak classes, **the PrIMuS-sourced SATB engine is the main lever. DS2 is a regulariser for
    engraver/font invariance**, not a volume source.
  - The same music in 4-5 fonts is useful: it is a natural font-invariance signal with identical labels.
- **Risks:**
  - **Rhythm prior shift.** DS2 is instrumental: in train, 8ths 34k, 16ths 15k, 32nds and shorter about 3.8k,
    against quarters 18k.
    - The camera model already over-reads quarter → `beamedRight1`.
    - Unweighted, DS2 could reinforce exactly that error. Resample strips toward the choral duration histogram
      (dev GT), and cap strips where more than 30% of notes are 32nd or shorter.
  - **Range shift.** Piano and orchestral ledger extremes; down-weight strips with |P - 4| > 10.
  - **Label noise.** Geometric association is noisier than MEI conversion. D1-D3 bound it, but they do not zero it.
  - **Convention mismatch** (courtesy signatures, cancellation naturals, slur vs tie) would teach a convention that
    contradicts the SATB labels. Section 4 holds these out until one decision covers both converters.
  - **Duplication.** With random page splits, DS2 validation leaks across fonts. Always split by piece.
- **Weighting in Phase 2:**
  - DS2 is **10-20% of the draws**, sampled by piece (uniform over pieces, then over fonts), after resampling to the
    choral duration histogram.
  - Per-class oversampling targets come from **step 6 (the per-class error budget, running now)**. DS2 must not set
    its own targets.
  - Replay through the same grey path as inference (6b).
- **Ablation (proves DS2 helps, not just "more data"):**
  - Arm A: Phase 1 synth + CPM replay (the G2 run). Arm B: the same, with DS2 **replacing** 15% of draws, so the
    total steps and samples stay equal.
  - Same 2 seeds, same schedule, same model selection (the synthetic-layout validation split, never dev).
  - Report:
    - dev SER per piece, camera and digital separately, with the piece-level bootstrap;
    - per-class errors on the step-6 weak classes, plus the `beamedRight1`-for-quarter substitution rate;
    - the CPM canary;
    - `ds2_holdout` SER (a DS2-domain sanity number, not a deployment claim);
    - the confident-wrong rate.
  - Optional arm C: DS2 at 15% without duration resampling. It shows whether the rhythm-prior risk is real.
- **Go/no-go for keeping DS2 in the mix:**
  - GO only if B ≥ A on dev SER on **both seeds** by at least the bootstrap margin, *or* B improves the step-6
    target classes with overall SER not worse than A (inside the margin).
  - And: no canary cap breach, the quarter → beamed substitution rate is not higher than A's, and the
    confident-wrong rate is not higher.
  - Otherwise drop DS2 and do not tune the weight on dev to rescue it. That would be tuning on dev, which the plan
    already flags as spent.
  - Dev data has been tuned on. The claim that settles it is Phase 4's held-out result, reported for the final model
    only.
- **Not claimed:**
  - DS2 does not address the confidence/uncertainty problem (retraining plan step 7).
  - A model that improves SER but stays confidently wrong still has the BUG-011 failure class.
