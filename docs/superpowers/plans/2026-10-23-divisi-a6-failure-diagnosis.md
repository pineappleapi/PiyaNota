# Divisi A6 Failure Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out, with no GPU time, why A6 fails triad recall (.626), ledger recall (.676) and exact triad set
(.301). Then pick the next route (A7) using decision rules written down before the diagnostics run.

**Architecture:** One new diagnostic script, `training/phase2/diag_divisi_a6.py`. It reuses `eval_divisi_a6.py`
for loading, column alignment and dedup, and `stage3_transcription.transcribe_strip(spans_out=...)` for the CTC
frame position of each token. It runs on the **tuning half only**, Gootville included (ml-cv-lead: the font gap was
null and it adds about 25% to n), and it also reports the Gootville-excluded verdict as a sensitivity check. It
writes one JSON file. A freeze-doc amendment records the result and the chosen route.

**Tech Stack:** Python 3, the PyTorch CPU model, the existing shared venv (`D:/PiyaNota/.venv`, run with `-I`).

**Spec:** `docs/decisions/piya-106-divisi-arm-freeze.md` A6.6 (result and ml-cv-lead review),
`docs/decisions/piya-106-divisi-a6-design.md` sections 6 and 9. Thresholds below are ml-cv-lead's pre-registration
review (2026-10-23), copied as given.

## Global Constraints

- The A6 verdict does not change. B' FAILs, and v1 ships with chords off (kill rule). This plan only chooses what
  comes next.
- Use the tuning half only. The script refuses `--half test`, because the test half must not shape the next
  hypothesis any further (ml-cv-lead, A6.6).
- Never open `D:/PiyaNota/datasets/phase4_strips/`, `piyanota_dataset` photos or test pieces. No A6 checkpoint runs
  on Phase 4.
- Use the shared venv only with `-I`, and never modify it. It has no pytest, so the tests are plain functions run by
  the one-liner in each task.
- Label every output "diagnostic". No gate thresholds are changed.
- Any A7 is a new pre-registered design with fresh test renders and ml-cv-lead pre-launch review. Kaggle pushes and
  uploads need the user's OK.
- Sample size is small: the s1e8 tuning half (Gootville excluded) has 690 triad members, 247 misses, 345 triad
  columns and 135 ledger members (`s1_tuning.json`). Every rule therefore needs a piece-level confidence interval
  and a leave-one-piece-out check, not just a point estimate.

## Definitions

- **Member:** one GT `chordnote` in a GT column with 2 or more chordnotes (the eval's `triad` bucket unit,
  divisi_a6_gates.py:81-82). The main note is not a member. A **miss** is a member whose step is absent from the
  aligned predicted column (`head_scores` semantics, eval_divisi_a6.py:213-214).
- **Dedup:** columns are deduplicated with `head_key` exactly as `dedup_columns` does, before any rate.
- **Base token after a column:** the next token after the note that is not a `chordnote`, an accidental or a `dot`
  (the converter writes a chord's dots after its chordnotes, music_to_agnostic.py:348); at the strip end it is
  `END`.
- **Frame gap:** `(x_next_start - x_note_start) * (64 / strip_height) / 4` on the predicted spans, with the strip
  width as `x_next_start` at `END`. Spans are in input-strip pixels (`transcribe_strip` docstring). The gap is
  **valid** only when the predicted note equals the GT note token and the predicted base token after it equals the
  GT base token after it. Otherwise the gap is `None`. Note: gaps come from the predicted spans, not from Verovio
  glyph coordinates (preferred by ml-cv-lead), because the build manifest stores none. The excluded fraction is
  reported.
- **Tight:** gap ≤4 frames. If tight columns hold under 15% of triad members with a valid gap, tight = gap ≤ P25 of
  valid triad-column gaps, fixed before hits are computed. The output also reports the miss rate by gap bins ≤3, 4,
  5-6, 7-9, ≥10 and None.
- **Has a 2nd:** any two GT heads of the column, main note included, are one step apart. Members are only "middle"
  or "top" (the main note is always lowest, music_to_agnostic.py:22, 372-373); position is reported, not ruled on.
- **Duration class:** `shape(note)` of the GT column, e.g. `note.quarter`.
- **Ratio:** miss rate in the group / miss rate in its complement. **Bootstrap:** piece-level, 2000 resamples, seed
  0, 95% percentile interval. **LOPO:** drop each piece in turn and recompute the point ratio and share; the rule
  must still hold every time.
- **Prior test:** among triad columns with a valid gap ≥8, the share whose aligned predicted column emits 2 or more
  chordnotes. Positive if under 0.5 (the GT rate is 1.0 there).

## Decision Rules (fixed now, before any diagnostic runs)

- **R1(a), frame gap:** tight miss rate / non-tight miss rate ≥2.0 (point) AND piece-bootstrap 95% LB ≥1.5 AND
  tight columns hold ≥40% of triad misses AND the verdict holds under leave-one-piece-out. Gap `None` is its own bin
  and counts in every share denominator.
- **R1(b), seconds:** has-2nd miss-rate ratio ≥2.0 (point) AND bootstrap LB ≥1.5 AND has-2nd columns hold ≥30% of
  triad misses AND it holds under leave-one-piece-out.
- **R1 extra condition:** the duration-stratified (Mantel-Haenszel) ratio of the passing split is ≥1.5. Otherwise
  the case goes to R3, flagged as confounded.
- **R1 → A7-crop:** a chord-column crop classifier after the CRNN (design section 9 2nd fallback, extended to all
  members). The CRNN is not retrained.
- **R2 → A7-data:** R1 fails AND both split ratios have point estimate <1.5 and bootstrap 95% UB <2.0 AND the prior
  test is positive. A7-data rebuilds the corpus with triad share .149 → .30 and 2+ ledger members 4.5% → 15%, same
  recipe, 8 epochs; dyad and non-chord non-regression must be re-gated. Note: ml-cv-lead also allows a rare-shape
  leg (rare-shape miss rate ≥1.5x common-shape). It is skipped here because it needs training-corpus shape counts,
  so R2 can only be harder to reach, never easier.
- **R3:** anything else, or the two seeds disagree. ml-cv-lead decides.
- **Ledger:** ledger counts as triad failure iff non-triad ledger-member recall ≥ .85 (point) with bootstrap LB ≥
  .80. Otherwise it is a separate A7 item.
- **Dyad-only ship option (user decision, not a rule):** the report states the net heads on tuning-half chord
  strips (GT chord member heads hit minus predicted extra heads). A dropped member emits no token, so it has no
  confidence to flag; a dyad ship would need a column-level "more heads than emitted" check. This is unresolved.

## Review Focus

- A GT triad column with no aligned predicted column: all its members are missed, gap `None`, and they stay in
  every share denominator. Test in Task 1.
- An accidental before the note or a dot after the chordnotes must not end the gap. Test in Task 1.
- A gap is valid only when the note and the next base token both match GT; a misread next base token gives `None`.
  Test in Task 1.
- Strips with `spans_out` length != token count: counted in `span_mismatch`, members kept with gap `None`. Handled
  in Task 2's CLI.
- A bootstrap resample with a zero-denominator complement must be skipped, not crash or give inf. Test in Task 2.
- `--half test` exits non-zero before loading any model. Test in Task 2.

---

### Task 1: Per-strip breakdown

**Files:**
- Create: `training/phase2/diag_divisi_a6.py`
- Test: `tests/test_diag_divisi_a6.py`

**Interfaces:**
- Consumes: from `eval_divisi_a6`: `columns`, `lcs_pairs`, `shape`, `ACCIDENTAL`, `step_of`, `LEDGER_LOW`,
  `LEDGER_HIGH`.
- Produces:
  - `frame_gaps(pred: Sequence[str], spans: Sequence[tuple[float, float]], strip_height: int, strip_width: int) -> dict[int, float]`:
    predicted `note.*` index → frame gap.
  - `triad_breakdown(pred: Sequence[str], gt: Sequence[str], gaps: Mapping[int, float]) -> dict[str, Any]` with:
    - `members`: list of dicts `{"gi", "pos", "gap", "has_2nd", "dur", "hit", "n_pred_ext"}`, one per GT triad
      member. `gi` is the GT column index, `gap` is valid or `None`, `n_pred_ext` is the aligned predicted column's
      chordnote count or `None`.
    - `ledger`: list of dicts `{"lines", "in_triad", "hit"}`, one per GT chord member (dyads included) with
      `lines > 0`.
    - `net`: `{"gained": int, "false": int}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_diag_divisi_a6.py` (plain functions):

```python
GT = ["clef.G-L2", "note.half-L1", "chordnote-L3", "chordnote-L5", "barline-L1", "note.half-L2"]

def _m(out, k):
    return [m[k] for m in out["members"]]

def test_triad_member_positions_and_miss():
    pred = ["clef.G-L2", "note.half-L1", "chordnote-L5", "barline-L1", "note.half-L2"]   # middle dropped
    out = dg.triad_breakdown(pred, GT, {1: 3.0, 4: 9.0})
    assert sorted(zip(_m(out, "pos"), _m(out, "hit"))) == [("middle", False), ("top", True)]
    assert _m(out, "gap") == [3.0, 3.0] and _m(out, "has_2nd") == [False, False]
    assert _m(out, "n_pred_ext") == [1, 1] and _m(out, "dur") == ["note.half", "note.half"]

def test_has_2nd_flags_cluster():
    gt = ["note.half-L1", "chordnote-S1", "chordnote-L3"]                  # steps 0, 1, 4
    out = dg.triad_breakdown(["note.half-L1", "chordnote-L3"], gt, {0: 6.0})
    assert _m(out, "has_2nd") == [True, True]

def test_unaligned_triad_counts_all_missed():
    out = dg.triad_breakdown(["clef.G-L2", "barline-L1"], GT, {})
    assert _m(out, "hit") == [False, False] and _m(out, "gap") == [None, None]

def test_gap_none_when_next_base_token_misread():
    pred = ["clef.G-L2", "note.half-L1", "chordnote-L3", "chordnote-L5", "rest.half-L3", "note.half-L2"]
    out = dg.triad_breakdown(pred, GT, {1: 3.0, 5: 9.0})
    assert _m(out, "gap") == [None, None] and _m(out, "hit") == [True, True]

def test_gap_ignores_preceding_accidental_and_runs_to_strip_end():
    pred = ["accidental.sharp-L3", "note.half-L1", "chordnote-L3", "note.half-L2"]
    spans = [(0, 4), (8, 12), (12, 16), (40, 44)]
    assert dg.frame_gaps(pred, spans, strip_height=64, strip_width=100) == {1: (40 - 8) / 4, 3: (100 - 40) / 4}

def test_gap_skips_dot_and_scales_height():
    pred = ["note.half-L1", "chordnote-L3", "dot-S3", "barline-L1"]
    assert dg.frame_gaps(pred, [(0, 4), (4, 8), (8, 12), (20, 24)], 64, 100)[0] == 20 / 4
    assert dg.frame_gaps(pred, [(0, 8), (8, 16), (16, 24), (40, 48)], 128, 200)[0] == 20 / 4   # 2x strip

def test_ledger_rows_flag_triad_membership():
    gt = ["note.half-L1", "chordnote-L7"]                                  # L7 = step 12, 2 ledger lines
    out = dg.triad_breakdown(["note.half-L1"], gt, {0: 5.0})
    assert out["ledger"] == [{"lines": 2, "in_triad": False, "hit": False}]
```

(`dg` is `import diag_divisi_a6 as dg` after inserting `training/phase2` on `sys.path`, as
`tests/test_eval_divisi_a6.py` does.)

- [ ] **Step 2: Run the tests to verify they fail**

```
/d/PiyaNota/.venv/Scripts/python.exe -I -c "import sys; sys.path[:0]=['tests','.']; import test_diag_divisi_a6 as t; [f() for n,f in vars(t).items() if n.startswith('test_')]"
```
Expected: `ModuleNotFoundError: No module named 'diag_divisi_a6'`.

- [ ] **Step 3: Implement `frame_gaps`, `triad_breakdown` and `ledger_lines`** in `training/phase2/diag_divisi_a6.py`.
  - Align with `lcs_pairs` on `shape` of the column notes, exactly as `head_scores` does.
  - `ledger_lines(step)` is `(LEDGER_LOW - step) // 2 + 1` below the staff and `(step - LEDGER_HIGH) // 2 + 1`
    above, else 0.

- [ ] **Step 4: Run the tests to verify they pass.** Same one-liner. Expected: no output, exit 0.

### Task 2: Rule engine and CLI

**Files:**
- Modify: `training/phase2/diag_divisi_a6.py`
- Test: `tests/test_diag_divisi_a6.py`

**Interfaces:**
- Consumes: Task 1; from `eval_divisi_a6`: `load_builds`, `load_cpu_model`, `STRIP_HEIGHT`, `columns`;
  `divisi_a6_gates.head_key`; `divisi_halves.load_groups`; `stage3_transcription.transcribe_strip`.
- Produces:
  - `ratio(members: Sequence[Mapping], in_group: Callable[[Mapping], bool | None]) -> float | None`: members where
    `in_group` returns `None` are left out; `None` if either side is empty or its miss rate is 0.
  - `mh_ratio(members, in_group) -> float | None`: Mantel-Haenszel rate ratio stratified by `dur`.
  - `boot_ci(members, stat: Callable[[Sequence[Mapping]], float | None], b: int = 2000, seed: int = 0) -> tuple[float, float] | None`:
    piece-level resample (members carry `piece`); resamples where `stat` is `None` are skipped.
  - `verdict(members, ledger) -> dict[str, Any]` with `tight_cut`, `gap_bins`, `r1a`, `r1b`, `r1_confounded`,
    `prior`, `r2`, `ledger_part_of_triad`, `route` ("A7-crop", "A7-data" or "R3").
  - CLI: `python -I training/phase2/diag_divisi_a6.py --build B --halves H --half tuning --ckpt L=PT --out OUT.json`.
    The JSON holds `label: "diagnostic, tuning half"`, `verdict` (all fonts), `verdict_no_gootville`,
    `counts_no_gootville` (`members`, `triad_columns`, `ledger`), `gap_valid_fraction`, `span_mismatch`, `net`,
    `duplicate_columns`.

- [ ] **Step 1: Write the failing tests**:

```python
def _mem(piece, hit, gap=6.0, has_2nd=False, dur="note.half"):
    return {"piece": piece, "hit": hit, "gap": gap, "has_2nd": has_2nd, "dur": dur, "gi": 0, "n_pred_ext": 2}

def test_ratio_and_none_group():
    ms = [_mem("a", False, 2), _mem("a", True, 2), _mem("b", False, 8), _mem("b", True, 8), _mem("b", True, 8),
          _mem("b", True, 8), _mem("c", False, None)]
    assert dg.ratio(ms, lambda m: None if m["gap"] is None else m["gap"] <= 4) == 0.5 / 0.25

def test_ratio_none_when_complement_never_misses():
    assert dg.ratio([_mem("a", False, 2), _mem("b", True, 8)], lambda m: m["gap"] <= 4) is None

def test_boot_ci_skips_undefined_resamples():
    ms = [_mem("a", False, 2), _mem("b", True, 8), _mem("c", False, 8)]
    lo, hi = dg.boot_ci(ms, lambda s: dg.ratio(s, lambda m: m["gap"] <= 4), b=200)
    assert lo <= hi

def test_verdict_clear_frame_gap_routes_crop():
    ms = [_mem(p, i % 4 == 0, gap=2.0) for p in "abcdefghijklmn" for i in range(20)]     # tight: 75% miss
    ms += [_mem(p, i % 10 != 0, gap=8.0) for p in "abcdefghijklmn" for i in range(40)]   # wide: 10% miss
    v = dg.verdict(ms, [])
    assert v["r1a"] and v["route"] == "A7-crop"

def test_cli_refuses_test_half():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-I", "training/phase2/diag_divisi_a6.py", "--build", "x", "--halves", "x",
                        "--half", "test", "--ckpt", "a=b", "--out", "o.json"], capture_output=True)
    assert r.returncode != 0 and b"tuning half only" in r.stderr
```

- [ ] **Step 2: Run the tests to verify the new ones fail.** Same one-liner. Expected: `AttributeError` on `ratio`.

- [ ] **Step 3: Implement `ratio`, `mh_ratio`, `boot_ci`, `verdict` and `main`.**
  - `verdict` applies the Decision Rules and Definitions verbatim. LOPO recomputes the point ratio ≥2.0 and the
    share threshold only (no bootstrap inside LOPO).
  - `main` exits with `"tuning half only"` on stderr when `--half` is not `tuning`, before any model load. It decodes
    each chord strip with `transcribe_strip(img, model, cpu, STRIP_HEIGHT, return_confidence=True, spans_out=spans)`,
    passes `img.shape` to `frame_gaps`, tags members with `piece` and `font`, and drops columns whose `head_key` was
    seen before.

- [ ] **Step 4: Run all tests.** Same one-liner, then the existing eval tests:
```
/d/PiyaNota/.venv/Scripts/python.exe -I -c "import sys; sys.path[:0]=['tests','.']; import test_eval_divisi_a6 as t; [f() for n,f in vars(t).items() if n.startswith('test_') and f.__code__.co_argcount==0 and 'raises' not in n]"
```
Expected: exit 0 for both.

- [ ] **Step 5: Commit** (only after the user reviews the diff)

```bash
git add training/phase2/diag_divisi_a6.py tests/test_diag_divisi_a6.py docs/superpowers/plans/2026-10-23-divisi-a6-failure-diagnosis.md
git commit -m "PIYA-106: A6 failure diagnostic (frame gap, seconds, ledger), tuning half only"
```

### Task 3: Run the diagnostic, review, record the route

**Files:**
- Modify: `docs/decisions/piya-106-divisi-arm-freeze.md` (append `#### A6.7`)
- Output: `D:/PiyaNota/datasets/phase2_divisi_a6/a6eval/diag_s1e8_tuning.json` (and `diag_s2eN_tuning.json` once
  seed 2 is selected)

- [ ] **Step 1: Run on s1e8 in the background:**

```
/d/PiyaNota/.venv/Scripts/python.exe -I training/phase2/diag_divisi_a6.py --build D:/PiyaNota/datasets/divisi_a6_build_v2/build --halves D:/PiyaNota/datasets/divisi_a6_build_v2/halves.json --half tuning --ckpt s1e8=D:/PiyaNota/datasets/phase2_divisi_a6/a6_s1/phase2_seed1_epoch8.pt --out D:/PiyaNota/datasets/phase2_divisi_a6/a6eval/diag_s1e8_tuning.json
```
Expected:
- Exit 0.
- `counts_no_gootville` equals `s1_tuning.json` s1e8: members 690, triad columns 345, ledger 135 (cross-check that
  this run scores like the gate run).
- `span_mismatch` under 1% of strips.

- [ ] **Step 2: Repeat on seed 2's selected epoch** once kernel v2 is fetched and selected. Both seeds must give the
  same route, else R3.

- [ ] **Step 3: ml-cv-lead post-results review** of both JSONs. Give it the Decision Rules verbatim; ask only
  whether the counts support the verdict.

- [ ] **Step 4: Append `#### A6.7 Failure diagnosis (diagnostic, tuning half)`** to the freeze doc. Include:
  - the verdicts with their counts and intervals;
  - the Gootville-excluded sensitivity;
  - the ledger attribution;
  - the net heads and the silent-drop caveat;
  - ml-cv-lead's read;
  - the route.

  State that no gate or verdict from A6.6 changes.

- [ ] **Step 5: Commit** (after user review)

```bash
git add docs/decisions/piya-106-divisi-arm-freeze.md
git commit -m "PIYA-106: A6.7 failure diagnosis and A7 route"
```

The A7 design itself is a separate brainstorm, design and plan, written only after A6.7 names the route.
