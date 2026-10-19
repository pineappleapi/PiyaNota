# Divisi on Real Camera Sheets: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a divisi (same-stem chord) reader whose quality on real phone photos of SATB sheets is measured, not
assumed. It is then raised toward the SOW camera targets in order of leverage.

**Architecture:** the plan has three parts.
- **Measure first.** A pre-registered, test-only set of real camera divisi pages is built before any new training.
  Without it, every synthetic pass is an upper bound only (ml-cv-lead, 2026-10-19).
- **Finish A6 with the coverage fix.** This plan has Task 1; the A6 plan has Tasks 8-9.
- **Close the real-domain gaps.** These are, in order: base camera note reading, camera artefacts on chords, the
  engraving-font gap and split-stem divisi. Each one gets its own design and gates.

**Tech Stack:** Python 3, music21, Verovio, PyTorch CRNN-CTC, Kaggle kernels.

**Spec:** `docs/decisions/piya-106-divisi-a6-design.md` (A6), frozen in `docs/decisions/piya-106-divisi-arm-freeze.md`
(A6, A6.1, A6.2). The targets are in `docs/sow.md` and `docs/NEXT-SESSION.md`: "camera pitch > 85%, SER < 15%".

## Global Constraints

- The SOW targets are camera input, SER ≤ 15% and pitch accuracy ≥ 85% (`docs/sow.md` §NFR-2). They are whole-score
  targets; no divisi-specific target exists yet. **User decision D1** (Task 2) sets it.
- The `piyanota_dataset` photos and Phase 4 (`D:/PiyaNota/datasets/phase4_strips/`) are TEST-only:
  - never read them for training, tuning or selection;
  - no A6 checkpoint runs on Phase 4 until the A6 gates pass and the user decides.
- Hand-authored or agent-made ground truth is diagnostic only. Only user-verified GT on a pre-registered set counts
  as accuracy evidence (CLAUDE.md).
- Every chord event stays flagged `chord_unvalidated` / `review_needed` until the real-camera check (Task 3) passes
  (design §7).
- Split-stem parts play merged into their own voice's single track (user ruling 2026-10-18).
- Fermatas are out of scope (user ruling 2026-10-14).
- Kaggle launches, dataset uploads, pushes and merges need user approval. Commits use `PIYA-106: <summary>`, with the
  session trailers.
- Use the venv `D:/PiyaNota/.venv/Scripts/python.exe -I` and never modify it. Run tests one file at a time with
  system `python -m pytest <file> -q`.

## Leverage order (why this order)

Effects are listed from largest to smallest. The numbers are diagnostic, from dev data.

1. **Base camera note reading.** A chord member is never read better than the single note under it. The dev camera
   SER baseline is 16.3-16.6% (grey e1c, the G2 baseline). Non Nobis Domine pitch is 64%. The SER-15 plan (Phase 2,
   G2) owns this work, and this plan depends on it. It does not duplicate it.
2. **Camera artefacts on chords.** Camera capture adds about 9 pp SER in every configuration (`docs/NEXT-SESSION.md`).
   A6 sees chords only through synthetic camera augmentation.
3. **Engraving-font gap (BUG-011).** The corpus has 5 SMuFL fonts from one renderer.
4. **Split-stem divisi.** It is common on real sheets, and the generator cannot make it (design §8, a separate step).
5. **Rare chord shapes.** Ties, chords 2+ ledger lines out and accidentals are covered by Task 1.

## Review Focus

- **A real page whose divisi is split-stem only.** Same-stem recall cannot be computed from it. The page must be
  scored under its own GT kind, not counted as zero same-stem chords (Task 3 test
  `test_gt_kinds_scored_separately`).
- **A real chord read as two notes in a row at the same two positions** (`second_as_sequence`). It must count as a
  miss plus a reported pattern, never as a hit (Task 3 test `test_sequence_read_is_miss`).
- **A test page from a piece also present in the Bach training corpus.** It must be refused at registration (Task 2
  test `test_registration_rejects_training_piece`).
- **A bucket with n < 300 real members.** It must report UNDERPOWERED with its Wilson interval, never PASS (Task 3
  test `test_underpowered_bucket`).
- **The tie-site drain at `P_TIE_CHORD = 1.0`.** Every tie site is taken before plain sites. Duration and density
  shares must stay within ±3 pp (Task 1 smoke check).

---

### Task 1: A6 rare-chord coverage (amendment A6.3)

ml-cv-lead GO (2026-10-19) with these values. The task lands before any test render, so it is not leakage.

**Files:**
- Modify: `training/phase1/build_corpus.py:109` (`P_TIE_CHORD`), constants block `:112-113`, site choice `:1004`,
  realised stats `:1123`
- Modify: `docs/decisions/piya-106-divisi-arm-freeze.md` (append `#### A6.3`)
- Test: `tests/test_phase1_build_corpus.py`

**Interfaces:**
- Produces: the constants `LEDGER2_MEMBER_TARGET = 0.05`, `LEDGER2_SITE_BOOST = 3.0`, `LEDGER2_MEMBER_CAP = 0.08`
  and `LEDGER2_VOICES = frozenset({"Soprano", "Alto"})`. It also adds `stats["ledger2_members"]` (int) to
  `divisi_summary.json` `realised`.
- Bass E4/F#4 is excluded until choral-conductor rules on it.

- [ ] **Step 1: Write the failing tests**

```python
def test_tie_sites_always_taken():
    assert build_corpus.P_TIE_CHORD == 1.0

def test_ledger2_boost_only_under_target_and_voice():
    # helper returns the site weight multiplier
    assert build_corpus._ledger2_boost(voice="Alto", near_edge=True, realised=0, members=100) == 3.0
    assert build_corpus._ledger2_boost(voice="Alto", near_edge=True, realised=8, members=100) == 1.0   # at cap
    assert build_corpus._ledger2_boost(voice="Bass", near_edge=True, realised=0, members=100) == 1.0
    assert build_corpus._ledger2_boost(voice="Soprano", near_edge=False, realised=0, members=100) == 1.0
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest tests/test_phase1_build_corpus.py -q -k "tie_sites_always or ledger2"`
Expected: FAIL (`P_TIE_CHORD` is 0.08; `_ledger2_boost` is not defined).

- [ ] **Step 3: Implement**
  - Set `P_TIE_CHORD = 1.0`.
  - Add `_ledger2_boost(voice: str, near_edge: bool, realised: int, members: int) -> float`. It returns
    `LEDGER2_SITE_BOOST` while `realised / max(members, 1) < LEDGER2_MEMBER_TARGET` and the voice is in
    `LEDGER2_VOICES`; otherwise it returns 1.0.
  - The cap is checked separately: at `>= LEDGER2_MEMBER_CAP` the result is 1.0 even when the target logic would
    differ.
  - `near_edge` means the site's base head has `_drawn_position` ≤ -1 or ≥ 9. From there, a 2nd to 4th interval
    reaches steps ≤ -4 or ≥ 12.
  - Multiply it into the site weight at `:1004`, next to `ACCIDENTAL_SITE_BOOST`.
  - Count members with step ≤ -4 or ≥ 12 into `stats["ledger2_members"]` at `:1123`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_phase1_build_corpus.py -q`
Expected: all pass. Then run `tests/test_divisi_a6_gates.py` and `tests/test_stage4_divisi.py`, one at a time; both
pass.

- [ ] **Step 5: Smoke and gates**
  - Run: `D:/PiyaNota/.venv/Scripts/python.exe -I training/phase1/build_corpus.py --out <tmp>/a6_smoke10_r7 --composers bach --divisi <tmp>/a6_smoke10_manifest.jsonl`,
    then `tmp/smoke_shares.py` and `tmp/cov3.py` on the output.
  - Expected: rc 0, and every class and duration share within ±3 pp of target.
  - Expected: tied chords ≥ 2% of chords, 2+ ledger members at 4-8% of members, free_new 0, accidental chords ≥ 12%.
  - Also report tied chords per piece, because ties cluster in a few pieces.

- [ ] **Step 6: Eyeball**
  - Render 10 chords with a member at steps 12/13 or -4/-5 at 1:1, in two fonts.
  - Confirm that the ledger lines and the head positions match the labels.
  - If G1b never covered steps 12/13, record that in A6.3.

- [ ] **Step 7: Amendment, canary, commit**
  - Append `#### A6.3` to the freeze doc. It holds the values above, the smoke shares and "tie bucket expected
    UNDERPOWERED on the test half; reported, never PASS".
  - Regenerate the determinism canary hashes the A6 gates use.
  - Commit `PIYA-106: A6.3 tie and 2-ledger chord coverage`.
  - Re-pin `COMMIT` in `training/phase1/kaggle/divisi_a6/piyanota_divisi_a6.py` in a separate commit.
  - Rebuild `tmp/a6code/repo.bundle`.
  - Hand the user the new sha for the upload and launch. Then continue with A6 plan Tasks 8 (fetch) and 9.

---

### Task 2: Real camera divisi test set: protocol and registration

**Files:**
- Create: `docs/decisions/piya-106-divisi-real-test-set.md` (the pre-registration)
- Create: `training/divisi_real_register.py`
- Test: `tests/test_divisi_real_register.py`

**Interfaces:**
- Produces `data/eval_divisi_real/registry.json`:
  `{"frozen": bool, "pieces": [{"piece": str, "publisher": str, "pages": [str], "gt_kinds": ["same_stem"|"split_same_rhythm"|"split_two_rhythm"], "sha256": {page: str}}]}`.
- `register(photo_dir: Path, meta_csv: Path, training_pieces: set[str]) -> dict`. It raises `ValueError` on a
  piece in `training_pieces`, a missing GT kind, or any change after `frozen` is true.

- [ ] **Step 1: Write the pre-registration doc, before any photo is scored**
  - **Collection.** 8-15 pieces, at least 3 publishers or engravers, none of them Bach chorales or the 10 Phase 4
    pieces. Phone photos taken the way choir members take them, in the same capture conditions as Phase 4. Each
    piece needs at least 1 page with same-stem divisi.
  - **GT.** User-verified, per staff, in the agnostic token format. Chord members are listed bottom to top, and
    each divisi bar is tagged with its GT kind.
  - **Metrics** (A3 metrics, unchanged):
    - chordnote precision and recall per interval bucket, with n and Wilson 95% CI;
    - chord-member pitch accuracy;
    - `second_as_sequence`;
    - confident-wrong at 0.90;
    - whole-page SER and pitch accuracy with chords on vs off.
  - **User decision D1: the pass bar.** Proposed: chord-member pitch accuracy ≥ 85% on same-stem chords, Wilson
    lower bound reported; whole-page camera SER with chords on is no worse than chords off.
  - **Firewall.** One look per frozen checkpoint, every look logged, never used for tuning or selection.
- [ ] **Step 2: Write the failing tests** `test_registration_rejects_training_piece` (a Bach chorale id raises
  `ValueError`), `test_frozen_registry_immutable` (a second call after freeze with a changed page sha raises) and
  `test_gt_kind_required`.
- [ ] **Step 3: Run them and confirm they fail.** Run: `python -m pytest tests/test_divisi_real_register.py -q`.
  Expected: FAIL (module missing).
- [ ] **Step 4: Implement `register`.** `training_pieces` is read from the Phase 2 manifest piece ids
  (`phase2_manifest.jsonl`, A5 sha `78165b43…2824`), with the `__divisi` suffix stripped.
- [ ] **Step 5: Run the tests and confirm they pass.** Then commit
  `PIYA-106: divisi real camera test set registration`.
- [ ] **Step 6: Hand to the user.** The user collects the photos and verifies the GT. When the user signs off, the
  registry is frozen. This step is the critical path, so it should start now, in parallel with Task 1 and the A6
  runs.

---

### Task 3: Real-set scorer

**Files:**
- Create: `training/phase2/eval_divisi_real.py`
- Test: `tests/test_eval_divisi_real.py`

**Interfaces:**
- Consumes the frozen `registry.json` (Task 2), Stage 3 events with `chord_id` / chordnote events (Stage 3 divisi
  pairing plan, `docs/superpowers/plans/2026-10-16-stage3-divisi-pairing.md`), and `columns` plus the LCS scoring
  from `training/phase2/eval_divisi_a6.py` (A6 Task 7). Reuse them; do not reimplement.
- Produces `score(registry: Path, pred_dir: Path, gt_dir: Path) -> dict` with buckets keyed
  `(gt_kind, interval)`. Each bucket holds `n`, `recall`, `precision`, `wilson95`, `verdict` (one of
  `"PASS"`, `"FAIL"`, `"UNDERPOWERED"`), plus `second_as_sequence` and `confident_wrong_090`.

- [ ] **Step 1: Write the failing tests:**
  - `test_gt_kinds_scored_separately`: a split-only page adds 0 to the same-stem n.
  - `test_sequence_read_is_miss`: GT chord {L2, S2}, prediction L2 then S2 in a row. Expect recall 0 for the
    member and `second_as_sequence == 1`.
  - `test_underpowered_bucket`: n = 40 gives `verdict == "UNDERPOWERED"`.
  - `test_refuses_unfrozen_registry`: `frozen: false` raises `ValueError`.
- [ ] **Step 2: Run them and confirm they fail.** Then implement, rerun until they pass, and commit
  `PIYA-106: divisi real-set scorer`.

---

### Later milestones (each needs its own design doc, ml-cv-lead review and user approval; not tasks yet)

- **M-A. Base camera reading (owner: SER-15 plan, Phase 2 G2).** It is a dependency. Score the real divisi set with
  chords off on the G2 checkpoint, so that the single-note ceiling is known before any chord number is read.
- **M-B. Real camera artefacts on chords.** Print a set of the user's own **training-split** divisi renders on paper
  and photograph them the way Phase 4 was captured.
  - Labels come for free: they are the build's own `labels.json`. Strips are cut by Stages 1-2 from the photo and
    matched by staff order. Pages that fail to match are dropped.
  - This adds real camera noise with exact labels, with no transcription. The cost is user printing and photo
    time, for example 100 pages.
  - Decision D2: whether to do it, and how many pages.
- **M-C. Font and engraver gap.** Two options:
  - Turn camera-grandstaff chords into training data (today it is diagnostic only; freeze §A2 ruling). It needs an
    ekern converter, staff cropping and a split-voice filter.
  - Render non-Bach public-domain SATB in a second engraver.
  - Decision D3, after M-A and M-B results show how much of the gap remains.
- **M-D. Split-stem divisi.** A second CTC output on the same network, trained on closed-score chorales (design §8).
  It is scored on the real set's `split_*` GT kinds.
- **Ship rule.** Chords stay `review_needed` until the real set passes D1. If the real set fails, v1 ships with
  chords off, and same-stem divisi is reported as a known loss (as in A5).

## User decisions this plan needs

- **D1:** the divisi pass bar on the real set (Task 2, Step 1).
- **D2:** whether to do the print-and-photograph of training renders (M-B), and how many pages.
- **D3:** which font/engraver source to use (M-C), decided after M-A and M-B.
- **Bass 2-ledger steering:** ask choral-conductor (Task 1); the default is excluded.
