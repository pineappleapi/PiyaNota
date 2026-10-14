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
  own logged canary, per seed". **The reference numbers are copied from the Phase 2 run logs before the training
  diff review (step 6).** ml-cv-lead quoted 2.70-2.74% clean and 4.32-4.50% distorted, but those figures were not
  found in the repo on 2026-10-14.

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
