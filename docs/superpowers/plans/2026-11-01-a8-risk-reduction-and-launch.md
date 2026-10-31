# A8 Risk Reduction and Kaggle Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every pre-GPU risk in the A8 design, then build the A8 corpus and launch a 3-epoch C-s1 pilot on Kaggle under account `piamacc`.

**Architecture:** One label change (chord heads in drawn left-to-right order) in the shared MEI->agnostic converter, so synthetic pages, the real A7-data stream and GT all use it. CPU checks gate every step; the A7 build/train kernels are copied to `divisi_a8/` with arm C only and new account ids. The pilot keeps A7's 8-epoch cosine schedule and stops after epoch 3.

**Tech Stack:** Python 3.13, music21, Verovio 6.3.0, PyTorch (CPU locally, T4 on Kaggle), Kaggle CLI (`python -m kaggle`).

**Spec:** `docs/decisions/piya-106-divisi-a8-design.md` (read it first; A7 background in `docs/decisions/piya-106-divisi-a7-design.md` sections 5-8, 14.x).

## Global Constraints

- Repo: `D:/PiyaNota/.claude/worktrees/piya106-stroke-calibration`, branch `piya106/stroke-calibration`. Never merge to `main`; ask the user before any merge. Commit messages `PIYA-106: <summary>`, ending with the session's attribution lines. The user pushes git to origin (agent pushes have been blocked).
- CLAUDE.md applies: plan before edit, one-line risk line before changing code, ml-cv-lead before training code and after results, choral-conductor for musical questions.
- Kaggle: CLI account is `piamacc` (`python -m kaggle ...`; `kaggle` is not on PATH). Every new kernel/dataset id is `piamacc/<slug>`. Never write the token anywhere. Old inputs live under `piamac/...` (Task 8).
- One variable: only chord-head order changes. Generator, seed `divisi-a7`, targets, 14.8 merge change, `DYAD_WAIVED = {"2nd_none": 257}`, Gootville hold-out, lr 3e-5, replay .5, divisi share .20, real share .05, cap 32, init Phase 2 seed k: all as A7.
- Thresholds are A7's, unchanged: stop checks triad 2+ >= .85, dyad 2+ <= .02 (A7 section 6); test gates A7 7.1/7.3.
- The 10-piece test set (`data/piyanota_dataset/10piece_test_set`) is never decoded in this plan (PREREG first, A7 14.7). Diagnostics use the tuning half only, Gootville excluded.
- PC memory is limited: CPU diagnostics use samples of <= 100 strips and one checkpoint at a time; long jobs run in the foreground with a timeout or as watched background jobs.
- Kaggle "Successfully ran" means exit 0 only; the verdict is the run's `kernel_status.json` (`watch_kernels.py` reads it).

## Review Focus

- MEI chord with no `@stem.dir` (real merged MEI from MuseScore): the order rule must use Verovio's default stem choice; Task 3's audit on real MEI pins it.
- Stemless (whole-note) triad with a 2nd: drawn like stem up; Task 2 test `test_whole_note_cluster_like_stem_up`.
- Layer-2 chords (`.l2`) share the converter: G1c tests must still pass, with any order change in them explained (Task 2).
- Base note not the lowest head (stem-down 2nd at the top): Stage 3 must give the same pitches and no `chordnote_below_base` flag (Task 4).
- Tied or dotted chord members: dot and `slur.start` tokens keep their own rules; only `chordnote-*` order and the `note.*` head move (Task 2 multiset test).

---

### Task 1: Pre-GPU diagnostic (ledger and middle misses)

**Files:**
- Create: `training/phase2/diag_divisi_a8_pre.py`
- Test: `tests/test_diag_divisi_a8_pre.py`

**Interfaces:**
- Consumes: `eval_divisi_a6.columns`, `lcs_pairs`, `shape`, `step_of`, `load_builds`, `decode_strip`, `LEDGER_LOW`, `LEDGER_HIGH`, `HELD_OUT_FONT`, `divisi_halves.load_groups`.
- Produces: `classify_columns(pred: list[str], gt: list[str]) -> dict[str, list[int]]` (counters, add across strips) and a CLI writing `--out <json>`.

Counters (each `[hit, n]` or a count): `ledger_dyad`, `ledger_triad` (member recall on ledger steps); `middle_omitted` (aligned predicted column lacks the step and has fewer chordnotes than GT), `middle_wrong_step` (same count, a step not in GT), `middle_unaligned`; `middle_in_2nd_triad`, `middle_no_2nd`; `miss_offset` histogram (nearest predicted head minus missed step).

- [ ] **Step 1: Write failing tests** `test_ledger_split`, `test_middle_omitted_vs_wrong_step`, `test_unaligned_column`, built from 3-4 hand token lists (a dyad with `chordnote-L7`, a triad `note.half-L2 chordnote-S2 chordnote-L4` read as `note.half-L2 chordnote-L4`, the same read as `note.half-L2 chordnote-S3 chordnote-L4`).
- [ ] **Step 2:** `python -m pytest -q tests/test_diag_divisi_a8_pre.py` -> FAIL (module missing).
- [ ] **Step 3: Implement** `classify_columns` and the CLI: `--build <dir>/build --ckpt <pt> --n 100 --seed 0 --out <json>`; rows = tuning half, Gootville excluded, chord strips only, `random.Random(seed).sample` of `n`.
- [ ] **Step 4:** tests PASS.
- [ ] **Step 5: Run** on `D:/PiyaNota/datasets/divisi_a7v2_build_c/build` with `D:/PiyaNota/datasets/phase2_divisi_a7/c_s1/a7_c_s1/phase2_seed1_epoch8.pt` and `.../c_s2/a7_c_s2/phase2_seed2_epoch8.pt` (`--n 100`, one at a time). Outputs `D:/PiyaNota/datasets/phase2_divisi_a7/a8_pre_c_s{1,2}.json`.
- [ ] **Step 6: Decide (write into the A8 design, section 4):**
  - dyad ledger recall >= .85 on both seeds: ledger risk closed (the 7.1 ledger gate counts non-triad heads).
  - otherwise STOP and ask ml-cv-lead + user: A8c (separate ledger data change) or a recorded second variable.
  - middle: report the omitted / wrong-step split, with 2nd vs no-2nd. If omissions in 2nd triads are < 50% of middle misses, ask ml-cv-lead before going on.
- [ ] **Step 7: Commit** script, test, design-doc update.

### Task 2: Drawn-order rule in the converter

**Files:**
- Modify: `training/music_to_agnostic.py` (chord emit at ~382-420)
- Test: `tests/test_chord_xorder_labels.py` (new); existing chord/G1c tests updated only where the new order changes them

**Interfaces:**
- Produces: `chord_head_order(positions: list[int], stem: str) -> list[int]`. Input: distinct staff positions ascending; `stem` in `{"up", "down", "none"}`. Output: the same positions in drawn left-to-right order. Also `default_stem(positions: list[int]) -> str` for chords without `@stem.dir`.

Rule (from the design, section 2):
```
stem "none" is treated as "up".
up:   walk positions ascending; first head on the normal (left) side; each next head flips side if it is
      exactly 1 step above the previous head, else goes back to the normal side.
down: walk positions descending; first head on the normal (right) side; same flip rule going down.
order = heads on the left side ascending, then heads on the right side ascending.
default_stem: Verovio-style; the head farthest from the middle line (position 4 = L3) decides:
      farther above -> "down", farther below -> "up", tie -> "down".
```
The `note.*` token takes `order[0]`; `chordnote-*` tokens take `order[1:]`. Accidental tokens, dots and `slur.*` keep their current bottom-to-top rules.

- [ ] **Step 1: Write failing tests** (positions: L1=0, S1=1, L2=2, ...):
  - `test_dyads_unchanged`: `chord_head_order([0, 1], s) == [0, 1]` and `([0, 4], s) == [0, 4]` for each stem.
  - `test_stem_up_cluster`: `([0, 1, 2], "up") == [0, 2, 1]`; `([0, 1, 3], "up") == [0, 3, 1]`; `([0, 2, 3], "up") == [0, 2, 3]`.
  - `test_stem_down_cluster`: `([0, 1, 2], "down") == [1, 0, 2]`; `([0, 2, 3], "down") == [2, 0, 3]`; `([0, 1, 3], "down") == [0, 1, 3]`.
  - `test_whole_note_cluster_like_stem_up`: `([0, 1, 2], "none") == [0, 2, 1]`.
  - `test_default_stem`: `default_stem([0, 2]) == "up"`; `default_stem([6, 8]) == "down"`; `default_stem([2, 6]) == "down"`.
  - `test_token_multiset_unchanged`: convert one stem-up and one stem-down cluster MEI (inline strings, as `tests/test_g1c_layers.py` builds them); the sorted token list equals the A7 output's sorted list; only the order differs.
- [ ] **Step 2:** run -> FAIL.
- [ ] **Step 3: Implement** both functions and use them in `_Reader.chord`. Stem from the MEI chord's `@stem.dir`, else `default_stem`. Update the module docstring line 22 and the comment at 385.
- [ ] **Step 4:** run new tests, then `python -m pytest -q tests/test_g1c_layers.py tests/test_phase1_build_corpus.py` and the chord converter tests; fix expectations only where the order legitimately changed (note each one in the commit message).
- [ ] **Step 5: G1 gate:** `python training/g1_converter_gate.py` (CPM has no chords): 99.557% or better, unchanged.
- [ ] **Step 6: Commit.**

### Task 3: Rule vs drawing audit (synthetic and real)

**Files:**
- Modify: `training/phase1/chord_xorder_audit.py` (add an order comparison; keep the existing report keys)
- Test: `tests/test_chord_xorder_audit.py` (new or extend)

**Interfaces:**
- Consumes: `chord_head_order`, `default_stem` (Task 2); existing `chord_heads(svg_text)` (SVG chord `data-id` -> head (x, y)).
- Produces: report keys `rule_match`, `rule_total`, `rule_mismatch_examples` (<= 20), `rule_by_shape` (`dyad`, `close`, `has2nd`, `open`). SVG `data-id` maps to the MEI chord `xml:id`.

- [ ] **Step 1: Failing test** `test_rule_matches_drawn_order` on a tiny SVG + MEI pair (one stem-up and one stem-down 2nd cluster) and `test_rule_mismatch_reported`.
- [ ] **Step 2-4:** implement `--mei-root` (MEI files beside the renders), compare the rule's order with the drawn order (x ascending, then y bottom to top), tests PASS.
- [ ] **Step 5: Synthetic audit:** render 20 Bach train pieces x 5 fonts locally with `training/phase1/render_corpus.py --vocab-a7` from the local A7 v2 corpus MEIs (`C:/Users/paul_/.claude/jobs/f2a331e8/tmp/v2_c/corpus` if still present; else rebuild those 20 pieces with `build_corpus.py --a7 C --divisi-seed divisi-a7`). Gate: `rule_match / rule_total >= 0.995` overall and >= .99 in every shape.
- [ ] **Step 6: Real audit:** render the merged real MEIs (`D:/PiyaNota/datasets/divisi_a7_labels/labels/merged_mei/` or as `merge_divisi_parts.py` writes them) with Verovio and run the same audit. Gate as step 5. Also save 20 PNG crops of 2nd-cluster chords from the PDFs (`data/chords_dataset/<piece>/*.pdf`) next to the predicted order, for the user to eyeball.
- [ ] **Step 7:** if a gate misses, STOP: list the mismatch shapes and ask choral-conductor + ml-cv-lead. Do not tune the rule to the audit without a recorded ruling.
- [ ] **Step 8: Commit.**

### Task 4: Stage 3 accepts x-ordered chords

**Files:**
- Modify: `stage3_transcription.py:1231-1240` (docstring) and `:1551` (flag)
- Test: existing Stage 3 chord tests (find with `grep -rn chordnote_below_base tests`), plus `tests/test_stage3_xorder.py` (new)

- [ ] **Step 1: Failing test** `test_xorder_chord_same_pitches`: `infer_pitch` on `note.quarter-L2 chordnote-L1 chordnote-S2` (base above a member) gives the same MIDI pitches as on `note.quarter-L1 chordnote-L2 chordnote-S2`, and no event carries `chordnote_below_base`.
- [ ] **Step 2-4:** stop setting `chordnote_below_base` (keep the pitch; the order is now drawn order, not a misread); update the docstring and any golden test that expected the flag. Tests PASS: `python -m pytest -q tests -k "stage3 or chord"`.
- [ ] **Step 5: Commit.** (The real-stream pitch check runs in Task 5, once relabelled rows exist.)

### Task 5: Relabel the real A7-data stream

**Files:**
- Create: `training/phase1/relabel_real_a8.py`
- Test: `tests/test_relabel_real_a8.py`

**Interfaces:**
- Produces: `relabel(rows: list[dict], new_labels: dict[tuple, list[str]]) -> list[dict]` keyed exactly as `cut_divisi_real.cut()` matches a label record to a strip (read `training/phase1/cut_divisi_real.py:142-190`); and a CLI writing `D:/PiyaNota/datasets/divisi_a8_real/manifest.jsonl` (strips are reused by path; nothing re-cut).

- [ ] **Step 1: Failing tests:** `test_tokens_replaced_by_key`, `test_multiset_guard` (a row whose new tokens differ as a multiset raises), `test_missing_key_raises`.
- [ ] **Step 2-4:** implement; tests PASS.
- [ ] **Step 5: Run:** regenerate labels with `merge_divisi_parts.py` (same inputs as A7: `divisi_score_maps.json`, `--split-bars` from the PDF form check) and `verify_divisi_heads.py` into `D:/PiyaNota/datasets/divisi_a8_labels/`, then `relabel_real_a8.py`. Copy `strips/` once into `D:/PiyaNota/datasets/divisi_a8_real/`. Expect 982 train-ok rows, same keys, same `train_ok`/`split`/`layered`; record the new manifest sha256.
- [ ] **Step 6: Pitch check:** for every A7 row (`D:/PiyaNota/datasets/divisi_a7_real/manifest.jsonl`) and its A8 row, the multiset of `infer_pitch` pitches is equal. 0 differences required; print the count.
- [ ] **Step 7: Commit** (script, test; not the data).

### Task 6: Pilot flag in training

**Files:**
- Modify: `training/phase2/train_phase2.py` (argparse ~519-540; epoch loop ~760-800)
- Test: `tests/test_train_phase2_divisi.py` (extend)

- [ ] **Step 1: Failing test** `test_stop_after_epoch_keeps_schedule`: with `--max-epochs 8 --stop-after-epoch 3`, the scheduler's `T_max` is 8 and the loop writes epochs 1-3 only (smoke mode on the existing fixtures).
- [ ] **Step 2-4:** add `--stop-after-epoch` (default None); break after saving that epoch's checkpoint and metrics; record it in `run_info.json`. Tests PASS.
- [ ] **Step 5: Commit.**

### Task 7: A8 build kernel (arm C), local consistency check

**Files:**
- Create: `training/phase1/kaggle/divisi_a8/piyanota_divisi_a8.py` (copy of `divisi_a7/piyanota_divisi_a7.py`), `training/phase1/kaggle/divisi_a8/kernel-metadata.json`

- [ ] **Step 1:** copy; `ARM = "C"`, ids `piamacc/piyanota-divisi-a8-c` and code dataset `piamacc/piyanota-divisi-a8-code`; docstring says A8 (x-order labels, design path).
- [ ] **Step 2: Consistency gate (local, CPU):** the corpus plans the generator writes are byte-identical to A7 v2 arm C (`build_corpus.py` is untouched): compare sha256 of every `corpus/*.plan.json` from a local 20-piece build against the same 20 pieces of the A7 v2 C build (`D:/PiyaNota/datasets/divisi_a7v2_build_c/build/corpus/`). 0 differences.
- [ ] **Step 3:** `divisi_a7_gates.py` unchanged; the Kaggle build must again show `2nd_none` 257 (waiver) and pass every gate.
- [ ] **Step 4: Commit.**

### Task 8: Kaggle inputs under `piamacc`

- [ ] **Step 1:** for each A7 input, check access as piamacc with `python -m kaggle datasets files <ref>` / `kernels files <ref>`: `piamac/piyanota-recut-full-1` (Phase 1 `out/`, pinned by `EXPECT_MANIFEST_SHA`), `piamac/cameraprimus`, `piamac/cpm-font-augmented2`.
- [ ] **Step 2:** for each one not readable, ask the user to make it public or share it with piamacc, OR upload a piamacc copy from the local source: Phase 1 `D:/PiyaNota/datasets/phase1_recut_full/` (must contain `canary_digest.json` and `out/`; `--dir-mode zip`), CameraPrIMuS `D:/PiyaNota/datasets/CameraPriMus/` (folder `CameraPrIMuS - Copy`, the canary sha in `train_phase2.py` must still match), cpm-font-augmented2 (locate locally; folders Bravura, Gootville, Leland, Petaluma). Uploading is outward-facing: confirm with the user first.
- [ ] **Step 3:** create `piamacc/piyanota-divisi-a8-real` from `D:/PiyaNota/datasets/divisi_a8_real/` (Task 5).
- [ ] **Step 4:** record the final input refs in the A8 design (section 6).

### Task 9: ml-cv-lead gate, then build launch

- [ ] **Step 1:** send ml-cv-lead the Task 1 numbers, Task 3 audit, Task 4 pitch check, Task 7 consistency result and the pilot GO rule below; get a written GO (or changes) and record it in the A8 design. Proposed pilot GO rule at epoch 3 (tuning half, eval_divisi_a7 + Task 1 script): triad 2+ >= .60 overall AND 2+ share of triads containing a 2nd >= .60 (A7 at e3: .45-.52 overall; A7 at e8: .57-.59 for 2nd triads). ml-cv-lead may change these numbers before the pilot runs; never after.
- [ ] **Step 2:** commit everything; bundle the branch at the reviewed commit (launch order in `training/phase2/kaggle/divisi_a7/stage_datasets.py` docstring: pin COMMIT uncommitted, bundle at HEAD, then commit the pin). Stage the code dataset folder like the A7 one (`repo.bundle`, `best.pt`, `camera_page_stats.json`, `parity_digest.py`, `phase2_manifest.jsonl`, `dataset-metadata.json` with id `piamacc/piyanota-divisi-a8-code`).
- [ ] **Step 3:** `python -m kaggle datasets create -p <code dir>`; wait for `ready`; `python -m kaggle kernels push -p <build kernel dir>`.
- [ ] **Step 4:** watch: `python -u training/phase1/kaggle/watch_kernels.py piamacc/piyanota-divisi-a8-c --every 300 --quiet-min 90 --fetch-dir D:/PiyaNota/datasets/kaggle_watch_a8` (background; one watcher per kernel). Verdict must be `ok`; fetch small outputs (`fetch_output.py` patterns used for A7) to `D:/PiyaNota/datasets/divisi_a8_build_c/`.
- [ ] **Step 5:** `pre_gpu_check.py` currently requires arms C and CL: allow `--build C=...` alone (test: one-arm call passes and skips the C-vs-CL comparison). Run it with `--write-pins` against an A8 copy of the GPU kernel (Task 10). Must print `PRE-GPU CHECK PASS`.

### Task 10: Pilot GPU launch (C-s1, 3 of 8 epochs)

**Files:**
- Create: `training/phase2/kaggle/divisi_a8/phase2_divisi_a8_kernel.py` (copy of the A7 kernel), `kernel-metadata.json`, `stage_datasets.py` (copy, ARMS = ("C",), SEEDS = (1, 2))

- [ ] **Step 1:** copy; `ARM = "C"`, `SEED = 1`; `TRAIN_ARGS` = A7's plus `--stop-after-epoch 3`; real stream = `piyanota-divisi-a8-real` with its new sha; inputs = the Task 8 refs; ids `piamacc/piyanota-divisi-a8-train-c-s1`; kernel source `piamacc/piyanota-divisi-a8-c`.
- [ ] **Step 2:** pins (COMMIT, divisi manifest sha from Task 9 step 5), stage, create datasets `piamacc/piyanota-divisi-a8-train-code`, push the kernel.
- [ ] **Step 3:** watch as in Task 9 step 4 (`piamacc/piyanota-divisi-a8-train-c-s1`).
- [ ] **Step 4:** fetch json/log + `epoch{1,2,3}.pt`; run `eval_divisi_a7.py` (A8 build, e1-e3) and the Task 1 script on e3; apply the GO rule from Task 9 step 1.
- [ ] **Step 5: Report** to the user and ml-cv-lead: GO -> full 8-epoch C-s1 and C-s2 runs (same kernel without `--stop-after-epoch`); NO-GO -> stop A8, no test half opened. Update memory `a7-build-status.md` (or a new `a8-status.md`) and the A8 design.
