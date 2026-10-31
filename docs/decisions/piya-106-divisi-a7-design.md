# PIYA-106 - Divisi reader A7: design (2026-10-26, draft)

**Status:** draft for user review. Scope decisions come from freeze doc A6.8 and A6.9 (user, 2026-10-26). Expert inputs
are from ml-cv-lead (A7 pre-registration; combined-scope review) and choral-conductor (chord forms; Stage 4 layer
merge), all on 2026-10-26. Nothing is built. Once approved, this doc is frozen as Amendment A7 of
`piya-106-divisi-arm-freeze.md`.

**Phase 4 statement:** the author has not decoded, transcribed or viewed any Phase 4 photo at notation level. No
value below comes from Phase 4, `piyanota_dataset` or the fresh-photo eval sets.

## 1. Why

A6 failed on both seeds (A6.6). Triad member recall was .626-.633, ledger recall .676-.685 and exact triad set
.301-.314. Dyads passed. The cause is a chord-count collapse: 195-210 of 432 triad columns emit only one chordnote
(A6.7).

The user holds v1 until A7 is scored (A6.8), and widened A7 to read both kinds of divisi (A6.9):
- **(1) Same-stem chords:** 2-3 heads on one stem, with the same rhythm.
- **(2) Different-rhythm divisi:** 2 parts on one staff, each with its own note values and each filling the bar.
  This includes same-rhythm split stems (opposed stems), which reverses A3.

Playback merges everything into the voice's single track.

**Hypotheses.**
- (1) Exposure fixes the collapse: more triads, realistic chord shapes, and ledger members.
- (2) The CRNN-CTC can read a second layer when the layer is written in drawn-x order.

**Main risk (ml-cv-lead):** the collapse may come from the architecture, which emits about one chordnote per
column. The stop check in section 6 is the guard for that case, and section 8 names the next design (A8).

### 1.1 Where A5 and A6 did poorly, and what A7 does about it

| Weak point | Evidence | A7 response |
|---|---|---|
| A5: frozen features hold no second notehead (probe P .67) | freeze doc, train-1 | Full fine-tune, as in A6 |
| A5: recall tracks training count per interval (2nds 1.8%, read .03-.16) | train-1 | Dyad exposure kept at A6 levels (3.1), with a corpus gate |
| A6: triad recall .626-.633, exact set .301-.314 | A6.6 | Triad share .30, templates, stop check (6) |
| A6: one chordnote in 195-210 of 432 triad columns, top head kept | A6.7 | Stop check at .85 emission (6); A8 if it fails (8) |
| A6: the middle head is the one lost (misses: middle 220-224, top 74-83); with 2+ emitted, middle .73 vs top .93 | A6.7 | Close-spacing templates (3.1), middle gate .80, reported per epoch; accidental recall by position (7.4) |
| A6: recall flat over epochs 5-8 | A6.6 | Epochs stay 8, with no extension (6) |
| A6: ledger .676-.685; non-triad ledger .846-.869 (LB < .80); 2+ ledger .470-.478 (n 406) | A6.6, A6.7, eval JSON | Ledger share .15, n >= 1000, separate gate (3.1, 7.1) |
| A6: misses piled up in two pieces (bwv383, bwv311: 99 of 298) | A6.7 | Per-piece miss share reported, plus leave-worst-1 and leave-worst-2 gate reruns (7.1) |
| A6: tied-column member recall native .775-.799, synth .834-.839; tie token never scored | eval JSON; tuning-half breakdown (3.4) | Tie token is read (99-100%); tied misses are mostly triads (67-70%) (tuning half, diagnostic; the test-half buckets were never split). Tie-token gate kept as the only check on the token (7.1) |
| A6 s2: camera dev pitch -0.71 pp, McNemar p .013 | A6.6 | A significant camera drop of 0.5 pp or more on either seed blocks chords-on (7.3) |
| A6: a dropped head emits no token, so it has no confidence | A6.7 | Image-based head-count flag (11) |

## 2. Arms

Two arms run in one kernel, with the same seeds (1 and 2), init, lr and epochs:
- **C:** chords only, the A6 corpus with the section 3 changes.
- **CL:** C plus layer bars.

Each kind has its own stop check and its own gates. They are never combined into one aggregate.

Arm C exists for one reason. A stems-down layer-2 head at a chord's x looks like a chordnote, so layers could
worsen the collapse. Arm C keeps the chord result clean if they do.

## 3. Corpus (`training/phase1/build_corpus.py`, new seed `divisi-a7`; change only these)

Each item is a delta from A6 section 4 and A6.4. Everything not listed stays frozen.

### 3.1 Chords (both arms)

- **Triad share:** `P_TRIAD_A6` .15 changes to **.30** of chord columns.
  - Dyads then renormalise over .70, so each dyad bucket's share shrinks by about 18% (the 7th falls to about 4%).
  - The ±3 pp mix gates apply to the renormalised targets.
  - 2nds stay at .12 of dyads.
- **Dyad exposure kept (A5 lesson: recall tracks training count).** Chord-column density in chord strips rises
  inside the existing 20-60% band, so that the train count of every dyad bucket is at least .95 of its A6 build v2
  count. This is a corpus gate (5.4). If density at 60% still falls short, the build stops and the triad share is
  revisited before any GPU time. The 25% chord-free strips and the .20 divisi share stay unchanged.
- **Middle head (A6.7: the middle head is the one lost).** No accidental skew toward the middle head: ml-cv-lead
  (2026-10-26) dropped it, because the A6.7 loss is a count collapse, not an accidental-placement problem, and a
  skewed prior could teach "triad accidental means middle". Accidentals stay as A6.4, and accidental recall is
  reported by head position (7.4). Clusters and close-position templates keep the middle head 1-2 steps from a
  neighbour, which is the hard case. Data alone may not fix the middle head; the middle gate and the per-epoch
  middle recall (6) show whether it did. Ledger members stay at the conductor's outer-voice sites, never forced to
  the middle.
- **Triad forms**, about 50/50:
  - **Random intervals:** the A6 draw, clusters included. The user confirmed clusters like C4-D4-E4 occur in real
    choral scores.
  - **Chord-shape templates** (choral-conductor), with three different pitch classes or a doubled root. Never a
    doubled 3rd or leading tone.
    - Soprano: close position within an octave (3+3, 3+4, 4+3), or root-3rd-octave. Top note usually G5-A5.
    - Tenor (sounding): close position, C3-G4.
    - Alto: rare, span at most a 6th, G3-C5.
    - Bass: open only, root-5th-octave or root-octave plus a 3rd. No 3rd or 2nd with its lower note below E3.
  - **Template placement:** at least .70 of template triads are whole, half or dotted notes, often tied over the
    barline. Beamed template triads are at most .05. Templates are weighted to final bars and cadences, and to S and
    B over A and T.
  - **Eval rows:** clusters (triads containing a 2nd), templates and random intervals are reported as separate
    rows.
- **Ledger members:** `LEDGER2_MEMBER_TARGET` .05 changes to **.15**, and its cap .08 changes to **.20**.
  - Realised share must be at least .12. Raise `LEDGER2_SITE_BOOST` only if a smoke run falls short.
  - Placement follows the conductor's sites:
    - Soprano C6 as the top note only.
    - Alto A3/G3 as the bottom of an octave, 5th or 6th at a cadence.
    - Bass C2 as a low octave.
    - Bass E4 as the top of a 3rd or 6th.
    - No Tenor 2+ ledger notes.
- **Unchanged:** `MAX_CHORD_NOTES` = 3, so no 4-note same-stem chords. Accidental rules stay as in A6.4. Density
  changes only as the dyad-exposure rule above says. Ties are in 3.4.

### 3.2 Layers (arm CL only)

- **Injection:** layer 2 reuses another SATB voice's real rhythm in the same bar. That gives a different rhythm that
  still fills the bar.
  - Pitches stay within the voice's A1 band.
  - Layer 1 stems up, layer 2 stems down.
  - Rests are allowed in layer 2, including a layer-2 entry mid-bar.
- **Share:** about .08 of bars in injected strips carry a layer. The draw is independent of the chord draw, so chord
  exposure is the same as in arm C.
- **Same-rhythm split stems:** a small share, about .15 of layer bars, as its own eval row.
- **Chords inside layers:** a layer head may carry chordnotes, under the same rules as 3.1. The share is reported.
- **Limits:**
  - At most 2 layers per bar.
  - No 3-layer bars in training. In eval, a 3-layer bar is expected to be flagged.
  - No cue notes, ossia, or two stems on one head (out of scope, see section 9).

### 3.3 Fonts, split and test render

- **Fonts:** all five Verovio fonts. Gootville stays the held-out chord font. In arm CL it is also the held-out
  layer font.
- **Split:** Phase 2 val is fixed at 25 pieces: 11 in the tuning half and 14 in the test half. Adding pieces would
  leak Phase 2 train.
- **Fresh test render:** the 14 test-half pieces with new injection seeds `divisi-a7-t*`, disjoint from A6's t1-t20.
  A6 test renders and results are not evidence for A7.
- **Pre-registered n:**
  - At least 600 in-font and 300 Gootville heads per chord bucket, as in A6.
  - At least 1000 non-triad ledger heads (1+ ledger), over all 14 pieces, with no piece above a .15 share.
  - 2+ ledger heads: n of at least 300, reported only.
  - At least 600 layer bars in-font and 300 in Gootville.
  - Ties (3.4): counted as tie events (a start and its continuation are one event, not two independent columns).
    At least 200 events per gated cell, source (native, synth) x size (plain, dyad). Native ties are supply-limited
    (A6: 578 columns); a short native cell is reported as underpowered, never as a pass.
  - A short bucket gets more renders before training, never after.

### 3.4 Ties (both arms; layer ties in CL)

**A6 result (report-only there):**
- Member recall in tied chord columns was native .775-.799 (n 578) and synth .834-.839 (n 970).
- Tie false positives were 0-1 of 1476 untied repeats.
- The eval never checked that the tie token itself was read. `tie_native` and `tie_synth` count head recall only
  (`eval_divisi_a6.py`).
- **Breakdown (2026-10-26, diagnostic, tuning half, Gootville excluded; both seeds the same;
  `D:/PiyaNota/datasets/phase2_divisi_a6/a6eval/tie_breakdown_tuning.json`):**
  - Tie token: 112 of 113 tied plain notes and 100 of 100 tied chord columns emit the tie. Tie reading is not the
    problem.
  - The `tie_*` buckets count both the tie start and its continuation column.
  - Tied-column head recall by size (s1 / s2):
    - native dyad .968 / .952 (n 124);
    - synth dyad .886 / .886 (n 44);
    - native triad .729 / .708 (n 48);
    - synth triad .500 / .500 (n 16).
  - Untied columns for comparison: dyads .970 / .969, triads .639 / .636.
  - Triads are 28% of tied heads but 67-70% of tied-head misses. The low tied recall is mostly the triad collapse.
  - The synth dyad dip (.886) rests on n 44 and is not read as a finding.
  - Limits: the tuning half has 11 pieces and few ties. The test-half buckets (.775-.839) are lower but cannot be
    split without opening the test half again, which A6.6 rules out.

**Corpus:**
- **Chord ties, unchanged from A6.3/A6.4:**
  - every native Bach tie site is chorded first (`P_TIE_CHORD` 1.0);
  - synthetic barline ties at 5%, cap 8%, under the A6.4 rules;
  - untied same-pitch repeats are kept as negatives.
- **Template triads** are often tied over the barline, as the conductor asked (3.1). They go through the same
  synthetic-tie path and caps.
- **Layer ties (CL):** the A6.4 synthetic barline-tie rule also runs on layer notes, at the same 5% rate and 8% cap.
  - A tie stays within its layer.
  - A layer-2 note may tie into a one-layer bar ("unis.") at the same pitch.
  - No tie crosses layers.
  - Ties inside a bar are not synthesised (as A6.4).
- **Known gap:** cross-system ties stay uncovered (A6.4).

**Eval (new):**
- **Tie-token recall:** for each GT tied column, whether the model emits the tie after the matching predicted
  column (same `slur.start` test as `tie_fp`).
- Tie-token recall and tied head recall are both split by source (native/synth) and by column size (plain, dyad,
  triad). The triad row separates collapse from tie reading.
- **Tie false positives:** `tie_fp` as in A6.
- **Layer ties (CL):** per-layer tie-token recall, including the layer-2 to one-layer "unis." case.

## 4. Token scheme (arm CL; ml-cv-lead)

- **`layer.split`** follows the barline of a two-layer bar. The next barline closes the split, so there is no merge
  token.
- **Order:** inside a split bar, events go in drawn-x order, which keeps CTC alignment monotonic.
  - A simultaneous onset goes upper layer first.
  - The order is audited the same way `chord_xorder_audit` works now.
  - Layer-serialised order (layer 2 after layer 1) is rejected: it breaks monotonic alignment.
- **Layer-1 tokens are unchanged**, so they share data with monophonic training.
- **Layer-2 notes and rests** use fused classes, e.g. `note.eighth.l2-L2` and `rest.quarter.l2`. A prefix token would
  push the token density per frame to about 3x.
- **Chordnotes, dots and accidentals** inherit their head's layer. Accidentals use the existing per-position
  matching.
- **Vocab:** the new tokens extend the A6 chord vocab. Arm C trains on the same extended vocab with no layer
  examples, so the two arms share heads.

## 5. Checks before any GPU time

1. **G1c, converter labels.** `training/music_to_agnostic.py:588-590` allows exactly 2 layers per measure. The G1c
   gate covers:
   - layers with different rhythms;
   - same-rhythm split stems;
   - layer-2 rests and a mid-bar layer-2 entry;
   - a unison across layers;
   - chordnotes inside a layer;
   - ties within a layer, and from layer 2 into a one-layer bar;
   - tied template triads (a tie on every head).

   G1 (CPM) must stay at 99.557% or better.
2. **G1b, user-scored sample page.** It covers the new chord forms and layer bars. The conductor's checklist:
   - each triad is consonant with the other voices, or is an intended cluster;
   - spacing and the Bass low-interval limit;
   - ledger lines, shared by stacked heads, with stems lengthened;
   - the displaced head of a 2nd is on the correct side;
   - stacked accidentals are staggered;
   - the Tenor 8vb clef and the written position;
   - label head order and ledger tokens;
   - ties on every head;
   - fewer than about 2 triad columns per system outside the final chord;
   - layers: stem directions, layer-2 rests, and label x-order.
3. **Frame budget audit.** One CTC frame is 4 px of strip width (`CNN_WIDTH_STRIDE`, `stage3_transcription.py:2069`).
   - For each layer bar, (tokens + repeats) / frames must be at most 0.8.
   - Bars over the cap are widened or dropped, and the count is reported.
4. **Corpus gates.**
   - The realised mix is within ±3 pp of every target in section 3.
   - Every dyad bucket's train count is at least .95 of its A6 build v2 count (3.1).
   - Realised synthetic tie share is within 5-8%. Layer-tie and tied-template counts are reported.
   - Counts per bucket meet the pre-registered n.
   - Held-out-font chord and layer strips are absent from train.
   - The x-order audit passes.
   - No Phase 1 or Phase 2 strip changed (A5 equality check).
5. **Local smoke.** A CPU smoke of `train_phase2.py` for each arm gives a finite loss and reloads identically.

## 6. Training and stop checks

- **Training (both arms):**
  - Same init (Phase 2 seed k), lr 3e-5, replay 0.5, 8 epochs, divisi share .20.
  - One seed-arm per T4 session (11 h budget). The A6.5 short-seed rule applies.
- **Why 8 epochs, with no extension:**
  - In A6, triad recall on the tuning half was nearly flat over epochs 5-8 (.628, .626, .642 at epochs 6-8; the
    epoch-8 rise means not quite flat).
  - More epochs on the A6 data are not expected to help. A7 is a test of data, so epochs stay at 8 to keep the
    comparison with A6 clean.
  - A run is not extended if the stop check misses. Epoch count is not tuned.
  - **Undertrained reading (ml-cv-lead):** if triad emission share still rises by more than .03 per epoch over
    epochs 6-8, a stop-check fail is read as undertrained, not architectural, and does not trigger A8 (8).
- **Reported every epoch (tuning half):** triad emission share, middle recall, top recall, ledger recall, and
  tie-token recall.
- **Selection:** on the tuning half, Gootville excluded, the same procedure as A6. It is fixed before the test half
  is opened.
- **Stop check, chords (both arms):** it runs at each seed's selected epoch, on both seeds, and every epoch is
  reported.
  - Each GT triad column is LCS-aligned to its predicted column, and the predicted chordnotes are counted. An
    unmatched column counts as 0.
  - The share of triad columns with 2+ chordnotes must be at least **.85** (point estimate; the Wilson LB is
    reported).
  - Anti-gaming guard: dyad columns emitting 2+ chordnotes must be at most .02.
- **Stop check, layers (CL):** `layer.split` bar precision and recall, each at least .85 on the tuning half.
- **Failure:** if a kind fails its stop check, that kind's test-half gates are not opened. The section 8 fallback
  applies.

## 7. Pre-registered gates (test render; both seeds; the lower of Wilson and piece-bootstrap LB decides)

### 7.1 Chords (gated separately for C and for CL)

- **Triad member recall:** at least .85.
- **Exact triad set:** at least .75.
- **Middle member recall:** at least .80.
- **Dyad buckets:** at least .90, and at least .80 for each 2nd bucket (as in A6).
- **Ledger:** LB at least .80 plus a point estimate of at least .85, on non-triad ledger heads.
- **Head precision:** at least .95.
- **Hallucination:**
  - extra heads on plain columns: at most .005;
  - chordnote hallucination on un-injected strips: at most 0.1 per 100 notes.
- **Held-out font gap:** at most .05, applied to triad and ledger as well.
- **Dyads against A6 (report):** the same-seed A6 epoch-8 checkpoint is scored on the A7 test render, and each dyad
  bucket's A7 recall is set next to it. A6's t1-t20 numbers are not the baseline (12). A drop of more than 2 pp
  (about 2 SE at n 600) is named in the report, even if the .90 gate passes.
- **Piece concentration (A6.7: two pieces held a third of the misses):**
  - Each piece's share of triad and ledger misses is reported.
  - Any piece with more than .15 of a bucket's misses is named.
  - The triad, middle and ledger gates are recomputed with the worst piece left out, and again with the worst 2
    left out (A6 had two dominant pieces). All results are reported. The gate decision stays the full-set lower
    bound; the leave-out runs show whether one or two pieces drive it.
- **Ties:**
  - Tie-token recall: LB at least .90 on tied plain and dyad events, per source. A cell short of its n (3.3) is
    underpowered, not a pass.
  - Tied triad columns: tie-token recall reported; tied triad heads count in the triad gates.
  - Tie false positives (`tie_fp`): at most .005 (A6: 0-1 of 1476).
  - Tied dyad-column head recall: reported only. It is a smaller subset of the dyad gate.

### 7.2 Layers (CL)

- **`layer.split` bar recall and precision:** at least .85 each.
- **Merged-timeline note recall:** at least .85. This is the ship metric for layers, because it is what the singer
  hears. It is computed per bar as a multiset of (onset, pitch, duration).
- **Per-layer note recall (pitch + duration):** at least .85.
- **Layer-2 bar-sum exact:** reported.
- **Layer-swap rate:** reported.
- **False `layer.split` firings on single-layer bars:** at most .005. Path 2 (8) drops layer-2 events, so .01
  would mean about 2 or more bars with lost notes per piece.
- **Held-out font gap:** at most .05.
- **Layer ties:** per-layer tie-token recall at least .85 if n is at least 300; otherwise reported only.

### 7.3 Non-regression (both arms, both seeds)

- **Canary caps:** .03695/.05317 (seed 1) and .03738/.05496 (seed 2).
- **Non-chord val SER:** at most +0.5 pp.
- **Dev pitch drop:** at most 1 pp against v1, with McNemar reported.
- **Camera pitch cost (A6 s2: -0.71 pp, p .013):** if the camera dev pitch drop is significant (McNemar p < .05)
  and at least 0.5 pp on **either** seed, the arm may not ship chords on, even if the 1 pp gate passes. The two
  seeds are a range, and the worse seed counts (ml-cv-lead). A6 seed 2 would have blocked.
- **Training:** 0 samples zeroed by `zero_infinity`.

### 7.4 Diagnostics (not gates)

- Accidental members, with recall by head position (bottom, middle, top).
- Confidence AUROC.
- Confident-wrong at 0.90.
- The cluster, template and random rows.
- The same-rhythm split-stem row.

## 8. Shipping and fallback (pre-registered)

1. **CL passes both kinds:** ship CL.
2. **CL passes chords only:** ship CL with layer-2 events dropped and flagged. This needs single-layer
   non-regression and the false `layer.split` cap from 7.2.
3. **Otherwise, C passes chords:** ship C, with layer bars flagged as before (A3).
4. **Otherwise:** chords stay off. Every detected chord column is flagged, and Soprano and Tenor play the top note.

**If the chord stop check fails in arm C on both seeds**, and the undertrained reading (6) does not apply, the
collapse is read as architectural. Arm C decides, because a CL failure can come from layer interference. A mixed
result (one seed, or CL only) means path 4 and no A8 claim. The next step
is a new design, **A8**, not part of A7. It has its own pre-registration and fresh test renders, and ml-cv-lead picks
its route. A6.7 does not support a frame-rate cause (emission is flat across gaps .51-.53). Candidates include:
- an explicit chord-size token before the chordnotes;
- a per-column count head trained with the CTC;
- a column decoder that reads all heads at once.

v1 then ships on path 4 while A8 runs.

**Applies to every path:**
- All chord and layer events are flagged `chord_unvalidated` / `review_needed` until the real check (section 10)
  passes.
- Before chords ship on, two more things are needed:
  - the head-count flag (section 11) must pass;
  - real-dev non-regression must pass on both seeds.

## 9. Stage 3/4/5 changes (choral-conductor rulings; written after the gates pass)

- **Stage 3:** keep per-layer local ticks, and tag each event with `layer` (1 or 2).
- **Stage 4:** runs per layer before the merge.
  - **Bar repair:** bar sum, run-scaling and tuplet logic run on each layer alone, and only the wrong layer is
    repaired. Running `_make_slots` (`stage4_reconstruction.py:1048`) on merged layers would build mixed slots.
  - **Underfull layer 2** (editions often leave out layer-2 rests) counts as silence, with at most an info flag.
    It is never scaled or padded.
  - **Pickup:** both layers must have the same length. Vote with layer 1, and flag layer 2 if it disagrees.
  - **Ties:** resolved per layer. A layer-2 tie into a one-layer bar ("unis.") merges at the same pitch, and is
    flagged `tie_unresolved` at a different pitch. `_resolve_ties` (`:1360`) currently matches only the next onset
    group, so it would wrongly flag a layer-1 tie when a layer-2 note falls in between.
  - **`divisi_rhythm_split_suspected`:** now means "two rhythms read as one line": a one-layer bar at 1.75-2.25 bar
    lengths while the other voices fit. A new sibling flag marks a two-layer bar where one layer still does not fit.
- **Stage 5, unison across layers:**
  - A same-pitch note at the same onset plays once, at the longer duration (`stage5_synthesis.py:148` already does
    this).
  - A shorter layer that re-attacks during a longer note re-attacks. That note ends at the later of the two ends,
    and the same-pitch clip must not shorten it.
- **App wording:**
  - "Bar N: 2 parts play together in this track."
  - "Bar N: 3 or more parts on this staff, not read. Check the score."
- **Out of scope:**
  - Cue notes (they must not play, but will be read as a layer), ossia, and grace notes.
  - SSAA/TTBB 3-4-part divisi on one staff (flagged).
  - Two stems on one head (plays as one note).
  - Two-staff divisi, which breaks Stage 2's 4-staves-per-system grouping.

## 10. Real check (user's 5 MuseScore pieces plus camera photos)

- **Use:** test-only, scored once, after the synthetic gates pass. They are never used for tuning, including the
  head-count flag.
- **Ground truth:** MuseScore is exported to MusicXML or MEI and converted. A sample of the GT is spot-checked by hand,
  because the converter has never seen real exports.
- **Overlap:** the pieces must not overlap the training corpus (Bach chorales) or any test-only set (Pangarap,
  Gaano, `piyanota_dataset`).
- **Minimum n per kind:** 50 triad columns, 100 dyad columns and 50 layer bars, spread over at least 3 pieces.
  Below that, results are descriptive only.
- **Gross pass (pre-registered):** a kind passes when its point estimate is at least its synthetic gate (7.1, 7.2).
  No LB is required at this n.
- **What it reports:**
  - gross pass or fail per kind;
  - a per-piece table;
  - a digital-against-camera pair for each piece, which isolates the capture domain.
- **What it cannot claim:**
  - Generalisation, because n is 5 pieces.
  - Prevalence, because the pieces were chosen for their divisi.
  - Font shift, because Leland is a Verovio training font.

## 11. Head-count flag (needed before chords ship on)

- **Model:** a small CNN on a native-resolution grey column crop, centred on the main note's CTC frame.
  - Classes are {1, 2, 3} heads.
  - It flags a column when its count is higher than the number the CRNN emitted.
  - It shares no CRNN features, because a dropped member emits no token and so has no confidence.
- **Labels:** notehead boxes from the Verovio SVGs of A7 train pieces, in the four non-Gootville fonts.
- **Tuning:** thresholds are tuned on the tuning half only.
- **Gating:** one-shot, on the A7 test render plus Gootville.
- **Targets:**
  - catch rate on dropped-member columns: LB at least .90;
  - false flags on correct chord columns: at most .05;
  - false flags on plain columns: at most .02.
- **Baseline:** a projection-profile heuristic. It is likely brittle with displaced 2nds, ledger lines and beams.

## 12. Do not reuse from A6

- A6 test renders (t1-t20), and A6 results as evidence.
- A6 checkpoints as init.
- A6's corpus seed.
- The R1/R2 cutoffs (P25 = 9 frames, prior test .5).
- Any AUROC-derived threshold.
- Any flag threshold tuned anywhere other than the tuning half.

## 13. Cost and confounds

- **Engineering, done once:** generator, converter (G1c), eval, Stage 3/4/5 layer handling and the head-count flag.
- **GPU:** 2 arms x 2 seeds, about 4 T4 sessions, plus 10-20% for the longer layer sequences.
- **Delay:** v1 waits for this (A6.8).
- **Confound, chords:** triad share, triad forms, ledger share and chord density (raised to keep dyad exposure)
  all change together. That is acceptable for a
  data-exposure fix. The ledger gate is split from triads, and the form rows separate templates from random draws.
  A pass does not say which change caused it.
- **Confound, real data (A7.1):** the real A7-data stream (14) enters both arms. A pass therefore cannot be credited to
  synthetic exposure alone. An A8 "architectural" reading still rests on arm C's synthetic stop check only.

## 14. Amendment A7.1: real A7-data stream, test pieces, token details (2026-10-30, draft)

Sources: user decisions 2026-10-30 (in session), ml-cv-lead pre-code review 2026-10-30, choral-conductor score and
PDF form checks 2026-10-30 (rounds 4-6). Needs ml-cv-lead sign-off before the doc is frozen; no GPU run before that.

### 14.1 Real training data (user)
- **Pieces:** the 9 `data/chords_dataset` pieces, all TRAIN: Ave_Maris_Stella, Both_Sides_Now, For_Good,
  It_Is_Not_Death_to_Die, Its_Amazing, Moonriver, Nandemonaiya, No_Mount_Too_High, Vinea_mea_electa.
  - Handog is dropped: its score deviates from the PDF too much (user). Dont_Stop_Me_Now stays excluded.
  - No hold-out piece is taken from these 9 (user; replaces ml-cv-lead ruling D). The held-out pieces are the test
    pieces in 14.3, built by the same code.
  - Both_Sides_Now was the Step 3 fresh test set (`seen_not_frozen`). After this, no Both_Sides_Now CRNN number may
    be cited as evidence.
- **Scores:** checked bar by bar against the PDFs (Sonnet choral-conductor, round 5): 8 pieces aligned; For Good's
  6 tie errors and 3 phrase slurs encoded as ties were fixed. Nandemonaiya and No_Mount_Too_High PDFs and photos are
  MuseScore prints of the corrected scores (user reprint).
- **Labels:** `training/phase1/merge_divisi_parts.py` -> `D:/PiyaNota/datasets/divisi_a7_labels/v2_20261030/`.
  - Two singing parts with different rhythms on one printed staff, or a part's own two voices: two layers (s4).
  - Same-rhythm parts: chords, unless the PDF draws split stems (form check, 14.2), then layers (A6.9).
  - Dropped: tuplets, 3+ different-rhythm parts, mixed/unsure forms, and bars where the label disagrees with the
    PDF (a merged rest, an accidental drawn once but labelled three times).
- **Strips:** `training/phase1/cut_divisi_real.py` -> `D:/PiyaNota/datasets/divisi_a7_real/`. PDF pages rendered at
  300 dpi and camera photos both go through Stage 1 and Stage 2's own box rules (ml-cv-lead change 6). A page whose box
  count differs from its printed staff count is skipped, not guessed.
- **Train eligibility:** the head check must match (vector PDFs) or the PDF is raster (conductor-checked); every
  chord_merge bar confirmed `chord` and every merged layer-2 rest confirmed drawn; frame ratio <= 0.8.
- **Stream (user: share .05):** real strips enter the Phase 2 divisi stream at a fixed .05 of divisi samples, in
  both arms. Layered real strips go to CL only (ruling F); arm C gets the same non-layered real strips.
  - Views per strip over 8 epochs are reported before training and capped at 32 (4 per epoch); if the cap binds,
    the realised share is lower and is reported, never raised. Cap value: proposal, ml-cv-lead to confirm.
  - Real strips never enter selection; selection stays on the synthetic tuning half.

### 14.2 PDF form check (ml-cv-lead changes 3-5)
- Every same-rhythm merged bar (152 bars, 4 pieces) was classified from the PDF by a Sonnet choral-conductor:
  chord 131, split 12, mixed 3, unsure 0. Split bars are labelled as layers; mixed bars are dropped.
- For Good's 6 merged layer-2 rest bars: 5 drawn, 1 drawn as one merged rest (dropped).
- Remaining before training: the user's G1b-style spot check of a sample of layered real bars, with the label-noise
  rate it finds reported. Accidental glyph counts per bar on vector PDFs are not automated (one repeated-accidental
  bar was found by a label scan and dropped).

### 14.3 Test pieces (replaces section 10's "5 MuseScore pieces")
- **Real check set (user):** `D:/PiyaNota/data/piyanota_dataset/10piece_test_set`. Camera photos follow after the
  dataset build and training (user). Test-only, scored once, never used for tuning.
- **Ground truth now (user):** Ama_Namin, Bahay_Kubo, Pangarap_Ko_Ang_Ibigin_Ka, built from their MuseScore scores
  with the same builder, combining the S/A/T/B parts the way each PDF prints them. Built by Sonnet agents that report
  counts only, so the author stays blind to the test notation. Output: `10piece_test_set/_a7_gt/`.
- **Disjointness:** none of the 10 test pieces is one of the 9 training pieces (by name).
- **Open conflicts, user to rule:**
  - `ama_namin` is in the Phase 4 pre-registered test set (`data/eval_phase4/PREREG.md`). Running an A7 checkpoint
    on its photos falls under that pre-registration (no A6 checkpoint ever runs on Phase 4).
  - `Gaano_Ko_Ikaw_Kamahal` is dev data in the 7.3 dev pitch pool (`data/eval_prelim/inputs.py`); it cannot also be a
    test piece for the real check.
  - The Pangarap and Gaano PDFs were under a "do not open" rule for this author; the user lifted it for Pangarap's
    ground truth (built by a Sonnet agent).

### 14.3a User rulings on 14.3 (2026-10-30)
- `ama_namin` and `Gaano_Ko_Ikaw_Kamahal` may be A7 test pieces: the A7 test only checks that the chord / layer reader
  classifies chords correctly, so it does not reuse them as Phase 4 evidence or as the 7.3 dev pool.
- The real check set is `D:/PiyaNota/data/piyanota_dataset/10piece_test_set` (all 10 pieces), used as the user directs.
- The layered-real-bar spot check is done (user). Automated label-noise measure on the vector PDFs: accidental glyph
  counts per bar (`accid_check.py`) mismatch on 4 of 439 strips (0.9%), all For Good p5 s2 (a 6-flat courtesy key
  signature labelled with 3 flats); those strips are excluded. Raster pieces (146 strips) are not machine-checked.
- The 7-seed synthetic test-render plan (14.6) is replaced: the A7 gates are scored on the 10-piece test set (ground
  truth from its MuseScore scores, built blind; Ama_Namin, Bahay_Kubo, Pangarap done, the other 7 to follow; camera
  photos after training). The build kernel renders no synthetic test seeds.
- Real stream after all checks: 982 train-eligible strips, 508 staff-systems, 148 layered (the vocab guard drops 120
  strips whose labels the CRNN cannot emit, mostly the meter digits `digit.5-L4` / `digit.7-L4` of 5/4 and 7/4, 86 of
  them Vinea's; ml-cv-lead: keep them out of A7, odd meters need synthetic examples first). Nandemonaiya holds ~29% of
  the eligible strips; per-piece real-view shares are reported every epoch (`real_views_by_piece`).

### 14.7 ml-cv-lead sign-off conditions (2026-10-30)
- **Freeze:** GO with 14.3a and the conditions below. **Build:** after the kernel writes `halves.json` (A6 stage
  ported), the copied-share denominator counts free + copied only, and the 20-piece builds of both arms pass every
  summary gate at the launch commit (dyad train counts are judged on the full build).
- **Generator steering (compensation, not target changes):** free-member steering .57 so the realised share lands at
  the .60 +-.03 gate (20-piece: .611); template attempt probability on quarters .6 (whole/half/dotted 1.0). 2+ ledger:
  A6's any-position fallback also for random (non-template) triads while below .045 (template triads keep the
  conductor sites), site boost 6.0. 20-piece builds, both arms identical: triads .297, templates .314, 2+ ledger .062,
  free .611, ledger crossings .014, crossing .089.
- **Real-set reading (pre-registered here, before any A7 checkpoint runs):** all 10 test GT files, their PDF
  chord/split form calls and `accid_check` noise rate are frozen and hashed in a PREREG file first; a piece without GT
  at that point is out. Per-bucket n floors carry over (layer bars 600; 2+ ledger and template heads 300); a bucket
  under its floor is "underpowered, report only". A bucket passes only when its Wilson 95% lower bound clears its 7.x
  threshold at its own n, reported per piece too. C vs CL is a paired comparison on the same strips (non-overlapping
  paired CI for a layer win). Real PDFs test engraving/layout shift, not font shift (MuseScore prints use Leland);
  font claims come only from the synthetic test half (Gootville). Scored once per arm on the final checkpoint.
  Test pieces with 5/4 or 7/4 meters are listed before the PREREG freeze and their meter bars handled by a rule
  written then.
- **Before GPU:** Stage 2 parity of `cut_divisi_real.stage2_boxes` vs `detect_staff_regions` (done: 5 real pages,
  12 boxes each, identical); per-arm realised real share, groups at cap and per-piece shares; C vs CL per-bucket chord
  train counts within 10% (else reported as a confound); a confidence check (confident-right vs confident-wrong) on
  the synthetic test half for both runs; CPM clean/distorted SER and one-voice dev metrics per arm, never blended.

### 14.4 Token details
- **Rest suffix on layer 2 (ruling A):** kept, at the fixed nominal position per duration, as in layer 1 (e.g.
  `rest.quarter.l2-L3`). It carries no information; layer-2 rest position is never scored.
- **Ties (ruling B):** real labels label every same-pitch tie on the staff, whatever the layers; eval reports
  layer-1 into one-layer, layer-2 into one-layer and cross-layer ties separately. The generator keeps "no tie crosses
  layers". Stage 4 (s9) must also handle a layer-1 tie into a "unis." bar.
- **Vocab (ruling C):** `stage3_transcription.VOCAB_EXT_A7` = `VOCAB_EXT_CHORD_TUPLET` + `layer.split` + the `.l2`
  form of every `note.*` / `rest.*` token. Both arms train on it; A6 checkpoints still load.
- **G1c:** `tests/test_g1c_layers.py` (14 cases incl. an accidental in one layer only); G1 (CPM) unchanged at 99.557%.

### 14.5 ml-cv-lead rulings on the generator smoke (2026-10-30)
Smoke: 3 Bach chorales, seed `divisi-a7`. Rulings replace the matching lines of 3.1 and 3.3.
1. **Template triads:** the realised share is reported, must be >= .30, and is broken down by voice and duration
   class with its placement mix (design: >= .70 whole/half/dotted, <= .05 beamed). No bass inversions and no
   crossing relief for templates. The template row's test-render n is reported; below 300 in-font heads it is
   underpowered. (Smoke: .34; placement .65 long, 0 beamed.)
2. **2+ ledger members:** the .15 target and the >= .12 corpus gate are dropped. Ledger-site members are exempt
   from MAX_CROSSING and cross under their own cap (LEDGER_CROSS_CAP .05 of chord columns, reported). The corpus
   floor is A6 v2's realised .045; below it a plain dyad may use A6's any-position ledger draw. The 7.1 ledger gate
   (non-triad heads, 1+ ledgers) is unchanged; 2+ ledger heads stay report-only at n >= 300.
3. **Layer x-order check:** layer 1 goes first when both layers have an event at the same MEI onset; each render
   reports swaps, swaps drawn far apart, and different-onset cross-layer pairs drawn within 2 head widths
   (`meta.json` `layer_order_audit`, summed in `render_summary.json`).
4. **Real-stream view cap:** 32 views over 8 epochs per printed staff-system (the PDF strip and every camera strip
   of that staff share one budget), not per strip image. Before training, report the unique staff-systems
   (A7-data: 573 train-eligible), the realised real share and how many groups hit the cap.
5. **Freeze blockers (open):** the 14.3 conflicts and a pre-registered real check set; the measured label-noise rate
   (14.2 spot check); the test-render counts for layer bars (600 in-font / 300 Gootville), same-rhythm split bars,
   layer ties and 2+ ledger heads, planned before training (3.3 forbids adding renders after).
6. **Attribution:** A7 differs from A6 in triad share, density, templates, ledger sites, ties and the real stream at
   once. A7 vs A6 is a ship comparison only; arm C vs CL stays a clean comparison for layers.

### 14.6 20-piece smoke after the rulings (2026-10-30, first 20 Bach train pieces, seed `divisi-a7`, arm CL)
- Builds 20/20; renders 100/100 pass (5 fonts), 0 OOV. A6 on the same pieces: 1034 chords, 879 dyads, 2+ ledger .046.
- Chords 1281, triad share .293, dyads 906 (1.03 of A6 overall; small 2nd buckets swing +-15% at n ~50, so the
  per-bucket .95 gate is judged on the full build only).
- Templates .317 of triads (S 49/95, A 23/97, T 35/85, B 12/98); placement whole 22, half 33, dotted 25, quarter 38,
  beamed 1 (.67 long; design .70: reported, not forced).
- 2+ ledger members .043 (floor .045, steering target .08); ledger-site crossings .009 of chords (cap .05).
- Layers: 68 bars (3.4 per piece), same-rhythm 11, mid-bar entries 12, layer-2 rests 18, layer-1 chords in 58;
  layer ties 1 (1.5% of layer bars against 5%: underpowered, reported).
- x-order audit: 340 two-layer measures, 159 same-onset swaps (5 drawn more than 2 heads apart), 0 swaps without an
  MEI onset, 1 different-onset pair drawn within 2 heads.
- **Test-render plan (estimate from these rates, 14 test-half pieces, 5 fonts):** about 48 Gootville and 190 in-font
  layer bars per seed, so 7 seeds (`divisi-a7-t1`..`t7`) for >= 300 Gootville / >= 600 in-font layer bars; the same
  7 seeds give about 1400 in-font 2+ ledger heads and about 1000 in-font template heads per seed. Layer ties stay
  under any useful n (report only). To be confirmed against the actual test-half pieces before the build.

### 14.8 Deviation: `dyad_train.2nd_none` (2026-10-31; ml-cv-lead rulings, user chose more whole-note 2nd exposure)
- **Failure.** Full Kaggle build arm C (121dfff): `gate_fail`, only `dyad_train.2nd_none` 232/281 (.826, gate .95).
  The CL build crashed first (`kernel_error`: `_add_layer` read `.beams` on a Rest; fixed in f3ae38c); a local rerun
  of its build step gave the same 232.
- **Cause.** A 2nd is `2nd_none` (stemless) only on a whole-note site, and whole-note sites come almost only from
  whole-bar merges. A7's denser chords cannot add whole-note sites, and the dyad share fell from .85 to .70, so
  281 x .70/.85 = 231 was predictable. 3.1's "exposure kept" holds for stemmed dyads only.
- **The one change (fixed before the rerun).** A7 only, whole-bar merges only: when the merged note's first pitch
  conflicts with another voice (`_base_conflicts`), the bar's other distinct pitches are tried in bar order and the
  first that does not conflict is held (`build_corpus.py`, `kept`). The removed heads and the accidental checks follow
  the kept note. Class weights are not tilted (that would take stemmed 2nds; `2nd_down` has 20 to spare).
- **Result (full local build, both arms, same pieces/seed as Kaggle).** Base conflicts 1381 -> 812, 292 merges kept
  on another pitch, whole merges 1960 -> 2104, `duration.whole` .093 -> .0996; `2nd_none` 232 -> **257/281 (.915)**.
  Arms C and CL identical on every chord count. All other gates pass (`2nd_down` 866/890, `2nd_up` 948/939, 3rd
  2764/2858, ...). CL layer bars 1095 -> 1099.
- **Ruling: deviation recorded, no fallback** (none was fixed before the rerun; picking one after seeing 257 would be
  tuning to the gate). `DYAD_KEEP` stays .95 for every other bucket. `divisi_a7_gates.DYAD_WAIVED = {"2nd_none": 257}`:
  the gate is a WARN only at exactly 257, so a Kaggle build that does not reproduce the local count, or arms that
  diverge, still fail.
- **7.1 clarified.** ".80 for each 2nd bucket" means `2nd_up` and `2nd_down` (as in A6; stemless 2nds had no floor).
- **At test.** `2nd_none` recall is report-only, with n and a Wilson interval, never a pass. A6 vs A7 `2nd_none` recall
  is compared descriptively; a lower A7 with non-overlapping intervals is "possibly the lower exposure", credited to
  no other change.
- **Template placement on long notes** fell .633 -> .609 (whole 250 -> 238 template triads). Not a gate (3.1's .70
  was already missed and reported only); reported next to triad recall, not fixed in this iteration.
- **Builds.** The arm C build at 121dfff is superseded; both arms are rebuilt from one commit with the same seeds.
- **Later.** If whole-note 2nds matter on real choral pages, add whole-note supply in a later build (more merge
  sites), not class steering.
- **User rulings (2026-10-31).** The `2nd_none` waiver at 257 is confirmed. GPU training starts now; the 10-piece
  PREREG (14.7) is still frozen before any A7 checkpoint is scored on the real test set, so no inference runs first.
- **Builds v2 (b15582a, Kaggle):** C 299 min, CL 265 min, both `ok`; 2nd_none 257 reproduced; renders 803/803 each;
  pre_gpu_check PASS (no C vs CL chord confound, real share .05/epoch, 0 staff-systems at cap, Nandemonaiya .27/.30
  of real views reported). GPU kernels pinned to 5461a8c.
