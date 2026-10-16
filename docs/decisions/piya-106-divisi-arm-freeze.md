# PIYA-106 - Divisi arm freeze (2026-10-14)

**Status:** FROZEN at this commit. The user approved the section 1 scope on 2026-10-14; the values are ml-cv-lead's proposal of the same day and
were not changed. Every value here is now fixed. A change needs an amendment to this doc that records what
the author had seen of the Phase 4 photos by then, and its result is reported as test-informed (SER-15 plan,
Amendment 8.4).

**Inputs:**
- The design is `piya-106-chord-vocabulary-plan.md` section 10.
- ml-cv-lead proposed these values on 2026-10-14 after reading `build_corpus.py`, `music_to_agnostic.py`,
  `svg_check.py`, `vocab_guard.py` and `train_phase2.py`.
- No value comes from the 10 Phase 4 pieces. None of them has been decoded or transcribed at notation level.

**Deadline:** Sunday 2026-10-18 (user). If the arm fails a gate in section 5, or the Kaggle session has not launched
by **Sat 2026-10-17 12:00**, the arm loses its claim to the Phase 4 set and Phase 2 is scored alone.

## 1. Scope (reduced to meet the deadline; approved by the user 2026-10-14)

ml-cv-lead's verdict is that the full scope (tuplets plus split stems) cannot be done by Sunday. The reduced scope
fits with about 1 day of slack, and only if G1b passes on the first try.

| Item | v1 arm | Why |
|---|---|---|
| Same-stem dyads | IN | The thesis question |
| Triads | IN, 5% of injected onsets | Same code handles any member count |
| Seconds with displaced heads | IN, reported separately, no gate | Only an interval choice; the svg_check sort is needed anyway |
| Split stem, same rhythm | **CUT (user, 2026-10-14)** | Needs music21 Voice injection, layer merge and its own G1b cases. Labels equal the chord form by design; the GT kind tag reports it as its own row |
| Tuplets / `tuplet.3` | **CUT (user, 2026-10-14; overrides the chord plan amendment 3 bundling for v1)** | New token plus converter, SVG and Stage 3 duration code; does not answer the divisi question. GT v2 keeps triplets as `<OOV>` (Amendment 8.5) |
| Control run | IN | No new code, about 3 GPU-h; needed for the arm vs control comparison |
| Stage 3 fix C (one dot per head) | IN | Without it every dotted chord gets a double-dot duration |
| Stage 3 accidental-by-position matching, orphan drop | IN | Needed for chord member pitch |
| Stage 3 fixes A (ties), B (tie-carried accidentals) | DEFERRED | Reported as known-lost, with a count of tied chord members |
| Stage 4 `divisi_rhythm_split_suspected` | DEFERRED | Does not affect token SER or pitch |

Stage 3 code may land after Sunday, but it must be sha-frozen before the look. Its thresholds are frozen here.

## 2. Vocabulary and model

- **New tokens:** `chordnote-<pos>` for every position from `MIN_POSITION` -6 to `MAX_POSITION` 16
  (`training/phase1/build_corpus.py:49-50`): 23 tokens. The list is fixed, not taken from the data. No `tuplet.*`.
- **Loading:** the old VOCAB must be a prefix of `VOCAB_EXT_CHORD_TUPLET`. `train_phase2.load_model` currently
  hard-fails on any vocab difference, so it gains this prefix rule and nothing else.
- **Init:** for seed k, `phase2_kaggle_models/seed{k}/phase2_seed{k}.pt`. Arm and control both start from it.
- **Head expansion:**
  - Old rows are copied. New weights are drawn from N(0, 0.01), and new biases start at the minimum existing
    non-blank bias.
  - Check: the epoch-0 greedy decode of the canary and the synthetic val must be token-identical to Phase 2. If not,
    lower the new biases by 1.0 and repeat. Deterministic, uses no data beyond those two sets.

## 3. Training data (injection in `build_corpus.py`, behind `vocab_ext=False`)

- **RNG:** a separate `random.Random(f"divisi:{piece_id}")`. The Phase 1 stream is untouched, so with the flag off
  the corpus manifest must be byte-identical (sha `78165b43...`).
- **Pieces:** all 339 Phase 2 train pieces in 2 fonts (round-robin over the 5 fonts), plus all 25 val pieces in all
  5 fonts. Each piece inherits its tune-group split; assert 0 val tunes in train.
- **Where:** one span per voice-system, so S, A, T and B each get 0.25 of spans by construction (user ruling
  2026-10-01). Span length uniform 1-4 bars, capped at the system length, plus the piece's final chord.
- **Dyad interval mix:** 3rds 0.35, 6ths 0.25, octaves 0.20, 4ths/5ths 0.10, seconds 0.10.
  - The added pitch doubles a pitch another voice sounds at that onset, within `MIN_POSITION`..`MAX_POSITION`.
  - No member interval over 12 semitones, in any voice.
  - If no candidate qualifies, the onset stays single.
- **Triads:** 5% of injected onsets.
- **Share:** only strips with at least one chordnote are kept, about 9.5k. That is about 18-20% of epoch samples
  (about 24k synthetic + 9.5k injected + 18k CPM). `ReplaySampler` draws each synthetic row once per epoch, so no
  sampler change is needed.
- **Chordnote share check:** measured from the manifest, it must fall in 6-14% of note tokens. Otherwise only the
  span length is changed, before any training.

## 4. Optimisation

- AdamW, lr 3e-5 (Phase 2's seed-replicated rate), weight decay as in Phase 2, cosine schedule over 3 epochs,
  clip 5.0, `--augment-synth` on, replay 0.5. Seeds 1 and 2.
- **Fixed 3 epochs. Selection: the last epoch, always.** No patience, no real-data selection.
- **Control:** identical, except the 9.5k injected rows are replaced by a seeded draw of 9.5k synthetic train rows
  (same step count) and the old VOCAB.
- Compute: one Kaggle T4 session, about 6 GPU-h for arm s1, arm s2, control s1, control s2. The dev GTX 1650 is not
  used (BUG-013).

## 5. Gates (both seeds must pass each one, or the arm fails)

**Before training (local CPU, clean renders):**
- G1: CPM G1 rate unchanged with the flag on.
- G1b: 30 injected strips checked by the user against their renders, 0 systematic errors.
- Column collapse: at most 1.0% of chord columns infeasible at the smallest scale.
- Feasibility: at most 2% of injected train strips dropped as infeasible (T = W/4).
- Corpus: the SVG check passes, the guard quarantines 0 chordnote strips, the chordnote share is in 6-14%, and the
  split assert passes.

**During training:**
- 0 chord samples zeroed by `zero_infinity` in any epoch.
- Not-learning stop: synthetic-val chordnote recall at least 0.50 at the end of epoch 1.

**After training (synthetic, final epoch):**
- Chordnote precision at least 0.90 and recall at least 0.80 on synthetic val.
- At most 0.5 hallucinated chordnotes per 100 notes on un-injected val strips.
- Un-injected val SER at most 2x the init (Phase 2 val SER 0.259-0.263%, Amendment 5; G3 rule h precedent).
- CPM canary, with new tokens counted as insertions: no breach of the 3x-init hard cap, and the final epoch at most
  1.0 pp above Phase 2's own canary, clean and distorted (G3 rule f). The frozen rule is "relative to Phase 2's
  own logged canary, per seed". Reference values, Phase 2 epoch 6 (the deployed checkpoint), from
  `music_symbol_detection/phase2_kaggle_models/seed{1,2}/metrics.json` (also `piya-106-g2-rules.md` section 3):
  seed 1 clean 0.02695 / distorted 0.04317; seed 2 clean 0.02738 / distorted 0.04496. So the arm's final epoch must
  be at most 0.03695 / 0.05317 (seed 1) and 0.03738 / 0.05496 (seed 2). Mean per-sample SER, 399 pinned stems.

These floors only test whether chord reading works on synthetic data. Phase 2 reads synthetic strips almost
perfectly, so they say nothing about real photos (synthetic divisi lacks "div." text and real stem forms).

## 6. Stage 3/4 validators (flag only; the notes still play)

- V1: member interval over 12 semitones, in any voice.
- V2: 3 or more members.
- V4 voice range (sounding MIDI, standard choral ranges widened by 2 semitones): S 58-86, A 51-79, T 46-71,
  B 38-66. Stage 3 has no range check today, so this is new code.
- All three apply **only to events with a `chord_id`**, so Phase 2's events stay byte-identical (Amendment 8.4).

## 7. Phase 4 reporting threshold

- A token is "confident" at confidence of at least 0.90. A chord's confidence is the minimum over its members.
- Report the confident-wrong rate and AUROC, with chordnotes separately. The threshold is not tuned.

## 8. Build order (go/no-go)

1. Injection, converter `<chord>`, svg_check, VOCAB_EXT, guard, prefix load, head expansion (local CPU). Go: the
   `--smoke` runs.
2. Flag-off byte identity (local CPU). Go: manifest sha identical. No-go: fix before anything else.
3. G1 + G1b (local CPU + user, about 1-1.5 h of the user's time).
4. Column-collapse and feasibility gates (local CPU).
5. Render locally; cut on Kaggle CPU (about 1,400 pages, about 3.6 h); manifest locally; corpus gates.
6. Training diff + `--smoke` locally, then ml-cv-lead review.
7. Kaggle T4 session: arm s1, arm s2, control s1, control s2. Hard kill: not launched by Sat 12:00.
8. Synthetic eval; all section 5 gates; record every sha256; freeze.

## 9. Known confounds

- Arm vs Phase 2 mixes 3 extra epochs with the chord data. Only arm vs control isolates the chord data.
- Synthetic gates show the method can work, not that it works on real photos.
- Split stems and tuplets stay known-lost in v1.

## 10. Amendments and method notes

- **A1 (2026-10-15, chord member band; user-approved 2026-10-15):** injected chord members are restricted to staff positions -3..12
  (`build_corpus.DIVISI_MEMBER_POSITIONS`), narrower than the section 3 rule "within `MIN_POSITION`..`MAX_POSITION`".
  - Why: the first 3-piece smoke had 5 chordnote strips quarantined by the vocabulary guard, on tokens such as
    `accidental.natural-S7`, `accidental.sharp-L-2` and `note.beamedLeft1-L-2`. The old VOCAB has all three
    accidentals only at positions -3..12, and its note shapes cover uneven position ranges, so a member outside
    -3..12 can make the whole strip out of vocabulary.
  - Effect: no chordnote strip is quarantined on the smoke. The `chordnote-<pos>` tokens keep the frozen -6..16
    range (section 2); only the injection is narrower.
  - Firewall: the author has seen no Phase 4 notation. The band comes from the old VOCAB only.
- **Flag-off identity method (ml-cv-lead review, build order step 2):**
  - Rebuild all 739 Phase 1 MEI with the divisi flag off and byte-compare each `.mei` and `.plan.json` with the
    frozen corpus.
  - Compare HEAD vs the new converter tokens over 739 x 4 staves, and HEAD vs the new svg_check and vocab_guard
    verdicts over every existing render.
  - Rebuild the Phase 2 manifest and check its sha (`78165b43...`).
  - Method correction (2026-10-15): a raw byte compare cannot pass, even for unchanged code. Verovio writes
    random `xml:id`s and the build date into every MEI. The frozen corpus was built under another Python
    (its `source` paths differ), and a later commit added the `source_fixes.cross_staff_ties_removed` key. The
    compare therefore renames ids by order of first appearance, blanks dates and ignores those two plan fields.
- **Flag-off identity results (2026-10-15, local CPU, worktree code, flag off):**
  - Corpus: 739/739 `.mei` and 739/739 `.plan.json` equal to the frozen corpus after normalisation.
  - Converter: 739 pieces x 4 staves, 0 token differences, HEAD vs worktree.
  - svg_check and vocab_guard: 2195 renders (4857 pages), 0 verdict differences, HEAD vs worktree.
  - Phase 2 manifest rebuilt with the new `build_manifest.py`: sha `78165b43...`, identical.
  - Not done: a same-environment HEAD vs worktree corpus rebuild. It was stopped by the host for low memory;
    the frozen-corpus compare above covers the same question.
- **A2 (2026-10-15, head-only arm; user decision, ml-cv-lead GO with changes, frozen before any training and with
  no Phase 4 data seen):**
  - What: the Phase 2 seed-k checkpoint with CNN, BiLSTM and the old fc rows frozen. Only the 23 new chordnote fc
    rows (weight and bias) are trained (`train_phase2.py --vocab-ext --head-only`). Pitch is still computed by
    `infer_pitch`; this arm tests whether the frozen features already encode a second notehead.
  - Optimisation: AdamW, lr 1e-3, weight_decay 0, cosine to 0 over 3 epochs, no warmup, clip 5.0, seeds 1 and 2,
    `--select-last`. Same data as the arm (injected chord strips + Phase 1 replay + CPM mix).
  - The backbone is kept in eval() during training (BatchNorm running stats), asserted at every step. The old fc
    rows get zero gradient and no weight decay. At the end, every backbone tensor and old fc row must equal the
    init bit for bit (`summary.json` `head_only_identity`), else the run fails.
  - Guarantee, stated exactly: the old logits are identical to Phase 2. The decode is not guaranteed identical:
    greedy CTC collapse is non-local, so a chordnote frame inside "X X X" decodes as "X chordnote X", a duplicated
    X. This is counted as `chordnote_split_duplicates` on canary and val. Softmax probabilities also shrink with
    the larger vocabulary, so Stage 3 `confidence` and the section 7 threshold (0.90) are not identical to v1.
  - Gates: all section 5 gates apply unchanged, including the CPM canary, un-injected val SER, epoch-1 chordnote
    recall >= 0.50 (a stop there is a head-only fail and a valid "features do not encode it" result), final
    precision >= 0.90, recall >= 0.80, hallucination <= 0.5 per 100 notes and 0 chord samples zeroed.
  - Control: none extra. With the backbone frozen, the Phase 2 init (epoch-0 decode) is the head-only control.
    The existing control still isolates the chord data for the full arm only.
  - Version-2 rule: the full arm is the primary version 2. The head-only arm becomes version 2 only if the full arm
    fails any section 5 gate and the head-only arm passes all of them. Both arms and both seeds are reported
    whatever the outcome.
  - Kaggle order: arm s1, arm s2, control s1, control s2, head-only s1, head-only s2. Head-only is dropped first if
    the Sat 2026-10-17 12:00 hard kill or the GPU quota is at risk.
- **G1 rerun (2026-10-15, at 26e95ab):** 3995 CPM samples, agreement 0.99557, PASS, unchanged from before the
  chord work.
- **G1b sample (2026-10-15):** 12 manifest pieces (10 train, 2 val, seeded `random.Random("g1b-divisi")`) built
  with `build_corpus.py --divisi --pieces ...` and rendered in 5 fonts with `resvg_py` 0.5.0 (same pin as the
  Kaggle recut); 60/60 renders passed the SVG check, 0 OOV strips. Page: `g1b_page.py --divisi --seed 1`, 30
  strips, 6 per case (dyad, triad, dotted chord, member accidental, member on a ledger line). Realised interval
  mix on this subset (538 chords): 3rds .41, 6ths .28, 8ves .10, 4ths/5ths .18, 2nds .03 (target .35/.25/.20/
  .10/.10); 8ves and 2nds are short of candidates. Re-measured on the full build at the corpus gate.
- **G1b result (2026-10-16, user-scored, export `g1b_results (3).json` at 2026-10-16T04:45:03Z): PASS.** 30/30
  strips ok, 6/6 in each case (dyad, triad, dotted chord, member accidental, ledger member), 0 systematic errors.
  One triad strip (Leipzig, bach_bwv427__divisi, page 4, Tenor) carries a truncated note ("should"), marked ok.
- **Full build moved to Kaggle CPU (2026-10-16, user decision):** the local host kills large jobs for low memory.
  Kernel `piamac/piyanota-divisi-full-1` (script `training/phase1/kaggle/divisi/piyanota_divisi_full.py`, code
  dataset `piamac/piyanota-divisi-code`, bundle at `0ebc532`) pins music21 10.5.0 and verovio 6.3.0 (the G1/G1b
  versions) on top of the recut pins. It first rebuilds the 12 G1b pieces in 5 fonts and aborts unless MEI (ids
  and date normalised), plan (without `source`) and every `labels.json` equal the user-reviewed build (local dry
  run at `0ebc532`: 0 differences, 60/60 renders). Then train and val are built separately and rendered in 2 and
  5 fonts, the recut's 1-vs-4 worker check runs on 5 pages, and the whole set is cut; the x-order audit (A3) runs
  on the merged renders.
- **Chord data sources (2026-10-15, user decision):** CameraPrIMuS has no chords (0 of 3996 local samples, MEI and
  semantic), so it cannot supply chord strips. camera-grandstaff has many (3639 of 4623 val samples hold a chord)
  but needs an ekern converter, staff cropping and a split-voice filter, and is Verovio-rendered like Phase 1.
  Training data stays as frozen. After the Kaggle launch, camera-grandstaff is added as a diagnostic-only chord
  recall check (staves without split voices); it is never used for model selection or thresholds. Phase 4 remains
  the real test.
- **A3 (2026-10-15, seconds and split stems; user concern, choral-conductor and ml-cv-lead reviews, ml-cv-lead GO,
  frozen before any training and with no Phase 4 data seen):**
  - Claim scope: the thesis claims "reads same-stem (homorhythmic) divisi". Split stems with the same rhythm are
    cut (section 1) and two voices with different rhythms were never in scope; both are flagged, not modelled.
  - Label order (choral-conductor, after Gould): in a second the lower head is always on the left, for stem up,
    stem down and stemless heads, so bottom-to-top label order equals left-to-right drawn order for every dyad.
    Only clusters of 3+ heads (and 3+ stacked accidentals) differ. Chord vocabulary plan 10.4 ("for stem-down
    seconds this is the reverse of x order") is wrong for dyads. No relabelling.
  - Seconds stay at the section 3 mix. The realised share (.03 on the G1b sample) is limited by candidates (a
    second must double a pitch another voice sounds); raising the weight would only leave more onsets single.
  - Corpus gate addition: `training/phase1/chord_xorder_audit.py` counts injected chords whose drawn head x order
    disagrees with the label order, by chord size. Reported; mismatching chords go on the known-lost list.
  - Metrics addition, reported on synthetic val, the camera-grandstaff diagnostic and Phase 4, never gated:
    chordnote precision/recall per interval (2nd, 3rd, 4th/5th, 6th, 8ve, other) with n and Wilson 95% CI, and
    `second_as_sequence` (a GT second read as two successive notes at the same two positions).
  - Phase 4 expected outcome per GT kind, written before the look: same-stem chords are the primary metric;
    split stems with the same rhythm are zero-shot (labels equal the chord form); two voices with different
    rhythms are an expected failure, reported as member recall, insertions and confident-wrong count at 0.90.
  - Stage 4 flag extension (to chord vocabulary plan 10.6): a bar in one voice whose total is 1.75-2.25 bar
    lengths while the other three voices fit that bar gets `divisi_rhythm_split_suspected` + `review_needed`
    whether or not it holds a `chord_id`, and is not run-scaled or tuplet-scaled; notes play up to the bar
    length. The bounds are hand-set and never tuned on Phase 4 or `piyanota_dataset`. Report its recall on
    two-voice bars and its false-flag rate elsewhere.
  - Stage 3/4 code otherwise follows chord vocabulary plan 10.6 (chordnote events, per-position accidentals,
    per-member ties, fix C dots, orphan and unison chordnotes dropped with `review_needed`); it is written after
    the Kaggle launch and before the version-2 eval.
- **A4 (chordnote share remedy, 2026-10-16, before any training; ml-cv-lead GO with conditions):**
  - The full build at commit 0ebc532 (`DIVISI_SPAN_BARS` = (1, 4); manifest sha256 d86cc00a…6c58, 11279 strips,
    9660 with a chordnote) failed the share gate. The share is chordnote tokens over note plus chordnote tokens on
    the kept chord strips: 32234 of 183740 = 17.5% (train 17.6%, val 17.0%). Over all divisi strips it is 15.7%,
    which also fails, so the verdict does not depend on the reading. The other corpus gates passed (split assert
    0 tunes, 0 chordnote strips among the 737 not cut, G1b parity identical).
  - Remedy per section 3: only the span length changes, to (1, 1). Two estimates from the (1, 4) tokens bracket the
    truth: one under-predicts (1, 4) at 15.2%, the other over-predicts at 21.7%. Scaled to their own baseline,
    (1, 2) gives 15.0% and 12.0% (straddles 14%), and (1, 1) gives 12.4% and 8.6%. (1, 1) is the only span inside
    6-14% under both. The chorded share now leans more on each piece's final chord.
  - Kill rule: the rebuilt manifest must pass every corpus gate again. If (1, 1) misses, there is no third build
    and the divisi arm is dropped.
  - G1b: the parity reference is rebuilt at (1, 1) for the same 12 pieces; the injection and label mechanism is
    unchanged, only which bar is chorded. The user's first 30-strip check was on (1, 4) strips, and
    all 30 differ at (1, 1) (13 lost their chord). The user re-checked 30 new (1, 1) strips (`g1b_page.py --seed 1`,
    6 per case) on 2026-10-16: 30 of 30 OK, 0 notes. All 60 renders pass their checks, 0 OOV. Gate G1b: PASS.
  - Control: `--control-rows` equals the realised kept chord-strip count of the new manifest, not 9.5k.
  - Expected cost, noted before training: less chord signal per step raises the risk of missing the epoch-1
    recall stop and the final recall gate.
  - Realised dyad mix at (1, 4), train (not a gate, candidate-limited): 2nds .016, 3rds .428, 4ths/5ths .169,
    6ths .281, octaves .106.
