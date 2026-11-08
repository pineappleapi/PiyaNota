# PIYA-106 - Divisi reader A9: PREREG for the C-s1 pilot (FROZEN 2026-11-03)

Status: FROZEN at this commit; ml-cv-lead GO-with-conditions 2026-11-03 (text fixes 1-7 applied); user approved the freeze
commit 2026-11-03 (plan Task 8 step 2). Nothing changes after pilot launch; any later change is a dated post-hoc amendment.
The pilot COMMIT must descend from this commit (see section 14).
Where a fact is not checked against its file, it says "not verified".

Placement note: plan Task 8 names `docs/decisions/piya-106-divisi-a9-design.md` "new section 7, PREREG". Section 7 of
that file already exists ("Pre-registered choices made during the build"), so this PREREG is a separate file. The
design file keeps the rulings; this file collects them and adds what Task 8 asks for. If the user prefers it inside the
design file, move it as a section 8; no content depends on the location.

## 1. Plan Task 8 requirements and where they are met

Quoted from `docs/superpowers/plans/2026-11-01-a9-build-and-pilot.md` (Task 8):
- "write section 7 with: the kill lines and the e8 pass rule (Task 6 values);" -> section 3.
- "`--row-proj-lr-mult` (Task 3 step 5);" -> section 4.
- "the probe rerun at e4/e8: `emit` readout, `rows` tap; keep-rows "acted" if `rows` middle >= `cnn4` middle - .03;" -> section 5.
- "attribution: omitted vs wrong-step middles against A7's e3/e4 counts;" -> section 6.
- "the decision set for each 7.1/7.3 gate: the real 10-piece set (A7 14.3a) or fresh synthetic test renders (font gap);" -> section 7, resolved by section 15 items 1-3 (the CPU build of the fresh renders still needs separate user approval).
- "the C4 trigger for A10." -> section 8.
- Step 2: "send ml-cv-lead the Task 1-7 results and section 7; record its written GO (or changes). Commit. The PREREG is frozen from this commit; nothing in it changes after the pilot launches." -> done: ml-cv-lead GO-with-conditions 2026-11-03 (conditions C1-C5 and text fixes 1-7 applied), committed as the freeze commit.

## 2. Frozen inputs (hashes) and results of Tasks 1-7

| Item | Value | Source |
|---|---|---|
| v1 train manifest sha256 | `00dcfb19caeccd963edda98b70803c473973fa16766172d0ac5ffac9ae70a369` | `D:/PiyaNota/datasets/kaggle_watch_a9_build/kernel_status.json` |
| C2g freeze, train | `97cbf5fb587f5c445504ddfeb14c721f15e860dc5c6ab5e8f95c146bf4f38e8e` | same; also eval `kernel_status.json` |
| C2g freeze, held-out | `74c0059dbb3be857a1ea5d45a0673d17eef99697a18b04b8f09eb9afd9028a60` | same |
| Generated held-out manifest | `6f247e7ff4a434f7a779bcb88db0771bca3294613fd0a5b6fa07c4da8b04ca46` | `C:/Users/paul_/.claude/jobs/f2a331e8/tmp/a9_eval_done/eval_sets.json` |
| Generated held-out groups | `fccf5a524bad1ce9853b9d59cf66dedf1ff56864da331b3f585d4c029dab2f72` | same |
| Bach supplemental manifest | `71aa33d70a5ef2d241b920bbc607bf663e5ee6e5ce9ef411f77c9857b81063f4` | same |
| Supplemental per-seed `divisi-a7-sup1` | `8abf4725e861a183476870542b9235bb3125ff91bfb44278bf33c0fe4c32152a` | `eval_sets.json` `bach_supplemental.seeds` |
| `divisi-a7-sup2` | `959e12218774a9f31ca0c86bc0c13bff579fa745793bb7c2f3e62febbefc26f9` | same |
| `divisi-a7-sup3` | `3f18cb638639dd14ecae505a58b8429f82d8329cba9061e780db8ccb69d7f342` | same |
| `divisi-a7-sup4` | `10437720c9681574a44c528c4acc2e6762e0812fab717a4baad1d753da57db49` | same |
| `divisi-a7-sup5` | `17c72805a5451e6e110744e7db6826c1e3ab9dbc0f42ce7c422de860c0c5b1c0` | same (corrected 2026-11-03: the first draft spliced sup4's prefix onto sup5's suffix and dropped sup5) |
| VOCAB_EXT_A9 | 1056 tokens (864 + 192); list `training/vocab_ext_a9_tokens.txt` sha256 `a8ab6616b95bc7f9d17feeeff24f28ecba7e6eb990c329d1e4234673383f5974` | `sha256sum` of the repo file, 2026-11-03 (matches progress.md "a8ab6616...") |
| Build / eval kernel COMMIT | `a1ecf661478900cce28ba8f9e22ed483648c8ad0` (eval-only kernel `commit` field) | eval `kernel_status.json`. The v1 build kernel ran at `419b8f668f22183be76c844525aa614ee581add1` (build `kernel_status.json`); its train manifest is the one pinned above |
| Phase 2 manifest | `78165b43251f67751afc91500e812a3ce7fa06d8980a275ddadd7014d8782824` | `docs/runbooks/phase2-prep-runbook.md:75`; "verified = A7 pin" per progress.md line 179 |
| A7 v2 arm C build manifest | `fe7be1e330ab75a1c7627f16f1357e87a4544332f6e21761f54fc7dbadc39389` | pinned in `training/phase1/kaggle/divisi_a9/piyanota_divisi_a9.py:66`; UNVERIFIED on the Kaggle copy (progress.md line 185) |
| Init checkpoint `phase2_seed1.pt` | `5c444ad395179dfe6751b8de032d7a34b4a3ccfccebdd7fc28e2404c624eaf93` | `training/phase2/kaggle/divisi_a7/phase2_divisi_a7_kernel.py:40`, `divisi_a9/equiv_gpu.py:44` |
| Real stream `piyanota-divisi-a9-real` sha | not verified (no value found in the files read) | - |
| Pilot COMMIT | TBD. The pilot needs a fresh bundle at the pilot commit and a re-pinned `COMMIT`; none exists yet | progress.md line 188 |

Results to date (sources as above):
- **v1 train build (kernel `piamacc/piyanota-divisi-a9-c` v1):** train complete. 824 below-staff train members: 339 Bach
  below-staff members (824 - 485 = 339; `a9_bucket_check.json` `below_dyad` 339) + 485 generated, generated share
  485/824 = .5886 (plans: 568/947). The number of train pieces is a separate figure, also 339 (`kernel_status.json`
  `pieces.train` 339; `halves.json` itself holds half assignments, not a train-piece count); the two 339s are a coincidence and must not be conflated. Bucket check pass, all ratios vs A7
  >= 1.04 (progress.md; the 1.04 figure was not re-derived here). Kernel status `kernel_error`: the generated held-out cut hit
  the session budget (759 of 920 page results, total 700.3 min). The train manifest is untouched and is the pin above.
- **Eval-only kernel (`piamacc/piyanota-divisi-a9-c-eval` v2, `ok_eval_sets_only`, 108.6 min):** held-out cut 920/920 pages
  (865 ok, 55 dropped, 54 `no_strip_source`: the 920/865/55/54 split is from progress.md line 191; the status JSON gives
  only totals), 460 pieces, 3912 rows, below-staff 220 heads / 219 sites / 179 pieces. Supplemental: 5 seeds, 87 heads /
  43 sites / 9 pieces (the tuning half has 11 pieces, 1758 rows: 1758 from progress/brief, not in the JSON).
- **Tuning gate: PASS** = 17 build + 87 supplemental = 104 heads, 43 sites (minimums 100 / 40; user ruling 2026-11-03).
- **`supplemental_powered` = false** (87 < 100 heads alone). USER DECISION 2026-11-03, on ml-cv-lead's recommendation: the
  e4 below-staff kill line stays report-only; the supplemental set is frozen; no top-up seed. All 87 heads come from 9 pieces,
  so CIs are clustered by piece. (Recorded from the brief; the design file holds the same paragraph: design section 7,
  "Supplemental set not powered; e4 report-only; no top-up", about line 301.)
- **Arm C layer drop:** 587 generated Alto train rows carrying `layer.split` are dropped at train time (199 pieces; 575
  are T6 two-layer bars; 188 of their partner pieces are also dropped, 11 partners kept: the 188/11 split is from the
  brief and is not in the design text). Post-filter divisi train pool 19352 (generated 9713, was 10300; 10300 not found in
  any file read). Generated Alto share 25.0% -> 20.5%: accepted, no reweighting (ml-cv-lead). Effect on the overall
  generated share about 0.14 pp (inferred, not measured). The C2g "294 layer sites" are unused and the held-out 90 layer
  sites cannot be tested by arm C; they are reported as untestable.
- **Init equivalence** (`C:/Users/paul_/.claude/jobs/f2a331e8/tmp/a9_equiv_v3/equiv_gpu.json`, T4): old-row logit diff
  1.335e-05 (primary 1e-5 FAILED), 0/50 token mismatches (1516 tokens), max |logit| 21.09, relative 6.33e-07, expand-only
  control 1.335e-05 (equal: keep-rows adds nothing). CPU: 8.583e-06, 0/50 (PASS). User ruling 2026-11-03: operative
  requirement = identical tokens and diff < 1e-4, provided the control >= 1e-6 (met). Shown on the T4 only. Must be redone
  on the pilot's GPU at start; exact rule in section 9.

## 3. Kill lines and e8 pass rule (copied from `training/phase2/a9_pilot_gates.py`, KILL_LINES / PASS_RULE_E8)

A line is a kill when its condition does NOT hold. Tuning half only; test half stays closed.

| Epoch | Condition that must hold |
|---|---|
| e3 | triad_2plus >= .57; middle >= .52; head_P >= .87; dyad_2plus <= .03; above_dyad_ledger >= .68 |
| e4 | triad_2plus >= .74; middle >= .70; above_dyad_ledger >= .80; below_dyad_ledger >= .50; wrong_step_middles_per_100 <= 18 (100-strip `Random(0)` sample); dyad_2plus <= .02; camera_shift_excess <= .005 (A9 e4 delta minus A7 e8 delta) |
| any epoch | plain_below_extra_rate <= .005; canary_ok (under hard cap); non-chord SER kill rule R5 (17.6 R5; `a9_pilot_gates.SER_TOL` = 3e-4): kill iff val_ser(e) > min(val_ser(1..e-1)) + SER_TOL, e1 not judged; dyad_2plus <= .02 from e4 on |
| e8 pass | triad_2plus >= .85 and middle >= .78 |

- **below_dyad_ledger at e4 is REPORT-ONLY in this pilot** (user decision, section 2): `judge()` returns `report_only` when
  heads < 100 or sites < 40 (`BELOW_MIN_HEADS`, `BELOW_MIN_SITES`). The supplemental set has 87 heads, so the line
  is report-only by construction. The code does not need a change for this; it is the existing rule.
- **Camera-shift line** (`camera_shift_check.py`): shifts -3..3 px excluding 0, dev camera strips only, never
  `piyanota_dataset`. Raw greedy decode, no header filter.
- A missing metric returns `underpowered`, not `go`. `judge()` statuses: kill / underpowered / report_only / go.
- Mechanics (ml-cv-lead): `judge()` runs automatically and its output is saved before anyone reads metrics.
  A killed run is not resumed and not relaunched with another seed.
- Not changeable after this PREREG: lr, row-proj mult, mix shares, thresholds, vocab, pools, the supplemental set.

## 4. Training settings for the pilot

- A7 `TRAIN_ARGS` (`training/phase2/kaggle/divisi_a7/phase2_divisi_a7_kernel.py:47`): `--augment-synth --replay-ratio 0.5
  --max-epochs 8 --select-last --lr 3e-5 --vocab-a7 --arm C --divisi-share 0.20 --holdout-chord-font Gootville
  --real-share 0.05 --real-cap 32`.
- Plan Task 9 step 1 adds `--keep-rows --row-proj-lr-mult <value> --stop-after-epoch 4`.
- **`--row-proj-lr-mult` = 3.** Source: design section 7 "row_proj learning-rate multiplier" (decision smoke
  `piamacc/piyanota-a9-lr-smoke` v1: canary ratios mult 3 / mult 1 e2 1.375 / 1.210, e3 1.253 / 1.165, all <= 1.5; output-mean
  shift .029 std < 0.1). The smoke ran on 200 strips per stream, 3 epochs; it cannot show whether keep-rows acts.
  Weight decay 1e-4; no separate clip.
- **Exact pilot args (frozen with this PREREG):** A7 `TRAIN_ARGS` plus the A9 additions, arm C, seed 1:
  ```
  --seed 1 --augment-synth --replay-ratio 0.5 --max-epochs 8 --select-last --lr 3e-5 --vocab-a7 --vocab-a9 --arm C
  --divisi-share 0.20 --holdout-chord-font Gootville --real-share 0.05 --real-cap 32
  --keep-rows --row-proj-lr-mult 3 --stop-after-epoch 4 --generated-share 0.15
  ```
  Every flag name above was checked against the `ap.add_argument` calls in `training/phase2/train_phase2.py`
  (`--seed` :655, `--replay-ratio` :657, `--augment-synth` :658, `--lr` :659, `--max-epochs` :660, `--divisi-share` :673,
  `--holdout-chord-font` :676, `--select-last` :680, `--vocab-a9` :684, `--generated-share` :686, `--vocab-a7` :689,
  `--arm` :690, `--real-share` :692, `--real-cap` :693, `--keep-rows` :694, `--row-proj-lr-mult` :696,
  `--stop-after-epoch` :697). `--vocab-a9` implies `--vocab-a7` (`if a.vocab_a9: a.vocab_a7 = True`,
  `train_phase2.py` about :712), so passing both is redundant but harmless. NOT verified: the manifest / checkpoint /
  output path arguments the pilot kernel must add (the A7 kernel supplies them outside `TRAIN_ARGS`), and the A7 kernel
  passes `--arm` as the variable `ARM`, here fixed to C. `--stop-after-epoch 4` must be `<= --max-epochs` (checked at
  about :710).
- Cosine T_max stays `--max-epochs 8`; the pilot stops after e4 (`--stop-after-epoch 4`).
- **Required code/args changes before launch (BLOCKER for Task 9; none made by this draft):**
  1. Task 9's args omit `--generated-share 0.15`. Without it `ReplaySampler` draws the divisi pool uniformly (generated share
     about 9713/19352 = .50 of divisi draws, computed here from the pool sizes) and the C2g exposure figures below do not
     hold (`train_phase2.py:686`, `:326-347`). It is enforced by construction only when passed.
  2. Task 9's args omit `--vocab-a9` (`train_phase2.py:684`). `--vocab-a7` alone gives the 864-token head and quarantines the
     below-staff tokens. Whether the A9 kernel supplies `--vocab-a9` in place of `--vocab-a7` or in addition is not verified:
     `--vocab-a9` "implies --vocab-a7" per its help text.
  3. The realised generated share is not logged: `last_epoch_generated` is set (`train_phase2.py:303,330`) but never read.
     Realised divisi and real shares are logged (`divisi_share_realised`, `real_share_realised`). Log the generated share per
     epoch so the epoch-1 check in section 9 can be done.
  4. The pilot kernel, `kernel-metadata.json` and `stage_datasets.py` do not exist yet.

## 5. Presence-probe rerun (e4 and e8)

From design section 6: rerun the presence probe on the pilot's e4 and e8 checkpoints with the `emit` readout and a new tap
(`rows`) at the keep-rows layer output. Keep-rows "acted" if the `rows` middle recall >= the CNN map (`cnn4`) middle recall
minus .03 (`ACTED_TAP_MARGIN` in `a9_pilot_gates.py`). If it did not act, report it; the e4 middle and wrong-step kill
lines still decide the pilot. Baseline: the same probe on A7 e8. Drift reading from `metrics.json` (`row_proj_reading`): e4
`asym` < .05 = "did not act" (report, no kill); `asym` >= .10 = candidate (probe decides); rel > 1.0 with a canary rise = flag
"unstable". The rerun is Task 9 step 2 on Kaggle CPU; the probe's control (CNN-map top recall within .03 of the model's own)
may again return INCONCLUSIVE, as in design sections 1 and 6; that outcome is reported, not hidden.

## 6. Attribution (omitted vs wrong-step middles)

Three changes (C1 x-order labels, C2/C2g below-staff data, C3 keep-rows) plus VOCAB_EXT_A9 are confounded; this is
accepted (user, 2026-11-02). Attribution is descriptive only: count omitted and wrong-step middles at e3 and e4 on the tuning
half and compare with A7's. A7 reference (design section 1, A7 C e8 tuning half): omitted 56-57 at e3 and 17-26 at e8;
wrong-step 24-29, flat from e3 to e8. A7's own e4 counts are not stated in the design file: not verified; rescored before launch
on the same sample (17.7, R3). A fall in omitted middles points to C1; a fall in wrong-step middles points to C3 or to
more data. Neither is a causal claim. A gain on generated held-out alone says nothing about real scores.

Baselines and risk notes omitted from the first draft (design section 7); the numbers are to be recorded BEFORE launch,
none exist in the files read:
- **A7 e8 scored on the Bach supplemental set** as the baseline for the below-staff lines (design, C2 yield: "A7 e8 is
  scored on the same set as the baseline"). Not yet scored; value: not verified.
- **P2 rerun at e4** (design, "Vocabulary and mix sampler": "P2 re-run at e4"): the generated-vs-Bach image/linear probe
  (separability ~1.0 at the C2g sign-off) is rerun on the e4 checkpoint as a transfer-risk note, not a kill line.
- Also baselines to record: A7 e3/e4 omitted and wrong-step middle counts (section 6), A7 e8 camera-shift delta, A7 e8
  presence probe.

## 7. C2g, held-out, decision sets

- **Exposure (declared before the run):** formula in `train_phase2.expected_draws_per_generated_member` =
  epochs x n_divisi_per_epoch x F / n_generated_rows.
  - Declared figure in the design: 1.12 = 8 x 5,999 x .15 / 6,440. The 5,999 and the 6,440-strip pool come from the design
    text only; I did not re-derive 5,999 (open item). The 6,440 pool predates the v1 build.
  - On the v1 pool after the layer drop (generated rows 9713, section 2): 8 epochs 8 x 5999 x .15 / 9713 = **0.741** (the
    startup log prints 0.74 because it uses `--max-epochs 8`); 4-epoch pilot 4 x 5999 x .15 / 9713 = **0.371**. Pre-drop on
    10300 rows it would be 0.699. All below 3: **C2g is under-exposed by design.** Each "member" in this formula is a generated
    row (strip), not a below-staff member.
  - A null result on the Bach below-staff set means "C2g not tested" (ml-cv-lead ruling, design section 7), not "does not help".
    C2g's own value needs a separate pre-registered arm.
- **Mix:** `--generated-share 0.15` = generated rows are 15% of divisi draws, which is about 1.5% of ALL draws (corrected
  2026-11-03; the first draft and design section 7 said about 3%). Derivation from `train_phase2.py:862,874,885`:
  `n_divisi_epoch = round(.20 x Phase 1 rows / .80)`, real = `.05 x divisi / .95`, CPM replay =
  `(Phase 1 + divisi + real) x .5/.5`, so CPM is half of all draws and divisi is about .10 of all draws; generated =
  .15 x about .10 = about 1.5% (3% of the non-CPM draws; the CPM replay at .5 halves it). The 1.5% is a
  derivation, not a logged value (the 23,996 Phase 1 rows implied by 5,999 are not verified). Divisi .20 (of Phase 1 +
  divisi); real .05 (cap 32). The generated share of divisi draws is enforced by construction: `n_gen = round(F x n_divisi)`
  uniform with replacement (`train_phase2.py:326-347`).
- **C2g decoy extra-head report** (`c2g_report`): Wilson 95% upper bound (z = 1.96) of the per-site extra-head rate <= 5%,
  single and instaff decoys only; < 73 sites (`C2G_MIN_SITES`, was 60) = "underpowered"; phrase-cluster bootstrap reported beside it. With zero extras, UB
  <= .05 needs n >= z^2 x 19 = 73 sites (computed here, 73 not "about 74"). So a pass below 73 sites is
  impossible even at zero extras; `c2g_report` now reports that as "underpowered", never "fail" (section 15 item 7). The decoy-site count that will be
  used is not known yet: the frozen generator held-out had decoys single 272 / instaff 48 (progress.md line 143), before the
  render and cut drops; the realised count after the cut is not verified. The 219 below-staff sites in the held-out are
  below-staff sites, not decoys. State the realised decoy count when reporting. Held-out layer sites (90) and above-staff /
  layer_in decoys (none) are untested.
- **Decision sets:** the pilot kill lines decide on the tuning half (Bach rendered + Bach supplemental below-staff set).
  For the full run: the 7.1 test set is the 14 test-half pieces plus fresh renders (section 15 item 1); 7.3 camera pitch stays
  on camera dev and the real 10-piece set (`D:/PiyaNota/data/piyanota_dataset/10piece_test_set`) is a one-time confirmation
  only (section 15 item 2); the with/without rule also covers the fresh renders (item 3). The test half stays closed until a
  pilot pass.
- Wherever the supplemental set or the test half is used, report with and without `bach_bwv399` / `bach_bwv406`; the
  version WITHOUT them is decisive (User decision 2026-11-03, section 12 item a). C2g below 73 sites is UNDERPOWERED
  by code, not a model failure (section 12 item f).
- Generated held-out, Bach and CPM are reported separately, never blended. The below-staff recall is reported split into
  inside-A7-vocab and new-token targets; C1/C3 credit only from the inside subset (inside = both note and member token in
  `VOCAB_EXT_A7`, `below_dyad_split`).

## 8. C4 trigger for A10 (not A9)

From design section 6: on the A9 checkpoint, with the presence-probe control passing on both seeds, the LSTM-output probe
trails the keep-rows output by >= .05 on middle recall. C4 (a zero-init skip from the keep-rows output to fc) is not part
of A9.

## 9. Pilot-start and epoch-1 checks (ml-cv-lead conditions; to be run by the pilot driver)

- At start: assert every hash in section 2 that applies to the run (train manifest, C2g freezes, held-out and supplemental
  manifests, VOCAB_EXT_A9 list, `phase2_seed1.pt`).
- At start: assert the held-out, supplemental and test-half piece ids are disjoint from the train pool; assert 0 Gootville
  rows and 0 `layer.split` rows after the arm C drop.
- Generated-row checks (the earlier "realised generated share within +-1 pp" check is dropped: it is a tautology, because
  `n_gen = round(F x n_divisi)` in `ReplaySampler.__iter__`, `train_phase2.py:326`, so the realised share equals F by
  construction). Instead, at start and each epoch: assert `len(generated rows) == 9713` (post layer-drop generated rows,
  `sampler.generated`); assert every drawn generated row has `source == "generated"`; assert
  `n_gen == round(0.15 x n_divisi_epoch)` (`last_epoch_generated`). Still log the realised divisi, real and generated
  shares per epoch (needs the code change in section 4). The 9713 itself is not reconciled with the build's strip counts:
  section 11 item 14.
- Epoch 1 / start: redo the old-row logit diff and the token match against Phase 2 on the pilot's GPU. Exact rule (design
  section 7, "User ruling 2026-11-03"):
  - **Hard rule:** greedy tokens identical on all 50 strips AND old-row logit diff < 1e-4 (`OLD_ROW_LOGIT_TOL`) AND the
    expand-only control diff >= 1e-6. A token mismatch or a diff >= 1e-4 is a hard FAIL.
  - **Drift alarm (not the pass rule):** on a T4 with the same torch / cuDNN as the 2026-11-03 run (T4 result 1.335e-05),
    a diff > 1.4e-5 means HALT and investigate before training. 1.4e-5 is a drift alarm set just above the observed
    value, not a pre-derived threshold.
  - **On a NON-T4 GPU (User decision 2026-11-03, section 12 item c):** the same hard rule applies. A diff above 1.4e-5 is
    reported but is not a halt by itself.
- Report the dropped-page rates (section 10).
- Seeding (verified in `train_phase2.py`): lines 740-745 seed; `cudnn.deterministic` True and `benchmark` False;
  `ReplaySampler` takes a seeded `torch.Generator` (lines 893-899); `num_workers=0`; `run_info.json` logs device, torch,
  cuda, cudnn. GPU nondeterminism is still possible (project history: BUG-style cuDNN divergence), so a pilot is one seed,
  not a replicated result.

## 10. Leakage checks and data-quality facts

All PASS (scripts `C:/Users/paul_/.claude/jobs/f2a331e8/tmp/v/join.py`, `disj.py`, run 2026-11-03; I did not re-run them):
- 460 held-out pieces, 11 supplemental pieces (all val and tuning-half), 25 val and 14 test-half pieces: 0 overlap with
  train piece ids. The real 10-piece set names match no train id. 0 Gootville rows and 0 `layer.split` rows remain after the drop.
- **Caveat:** `bach_bwv399` (supplemental) and `bach_bwv406` (test half) share a tune group with a train piece. They are
  id-disjoint, not tune-disjoint (build `kernel_status.json`: `test_pieces_sharing_train_tune` 1). Their scores may be
  optimistic. User decision 2026-11-03 (section 12 item a): report results with and without them; the version WITHOUT
  them is decisive.
- **Page drops:** train build 338 of 3365 (10.0%; 3365 from build `kernel_status.json`, 338 from the brief). Generated pieces with
  a below-staff head 49 of 784 dropped (6.25%) vs without 67 of 1176 (5.70%). Bach piece level 116 of 849 (13.7%) vs 106 of 556
  (19.1%). Held-out 55 of 920 (5.98%); the below-staff vs other split of the held-out drops cannot be computed locally. These
  rates come from the brief and are not re-derived here. The drops may bias the below-staff set towards pages that
  render and cut cleanly.
- Hand-authored GT and the 10-piece set are diagnostic/test only; `piyanota_dataset` is never used for tuning.

## 11. Open items (not resolved here; need the user and/or ml-cv-lead)

1. The 5,999 divisi draws per epoch and the 6,440 pool in the exposure formula are from the design text only. The 0.741 and
   0.371 figures above use 5,999 and 9713 and are computed here. Confirm 5,999 from the train log or `n_divisi_epoch`.
2. The pilot kernel, args and `stage_datasets.py` do not exist; the pilot COMMIT is TBD (fresh bundle needed).
3. Generated-share logging, `--generated-share 0.15` and `--vocab-a9` must be in the pilot args (section 4).
4. A7 manifest pin `fe7be1e3` is unverified on the Kaggle copy.
5. RESOLVED (section 12 item a): report with and without `bach_bwv399` / `bach_bwv406`; the version WITHOUT is decisive (section 17 applies it to the plain-column line).
6. The 11 tuning-half pieces are both the supplemental set and the selection / kill-line set (progress.md Task 5 minor): the
   kill lines are judged on data also used for design, probe and selection (design section 5: "Discount the tuning half").
7. RESOLVED by section 15 items 1-3 (the CPU kernel run for the fresh renders still needs separate user approval).
8. The C2g Wilson UB cannot pass under about 73 sites even at zero extras, while the minimum was 60: now 73 in code (section 15 item 7).
9. A7's own e3/e4 omitted and wrong-step middle counts are needed for section 6.
10. Real stream `piyanota-divisi-a9-real` sha and its C1 relabel are not verified.
11. The "10300" generated-row count, the "188 / 11 partner" split, and the "all ratios >= 1.04" are from the brief and not found
    in the files read.
12. RESOLVED by 17.8: the supplemental-not-powered decision wording (option (a), user decision 2026-11-03).
13. Equivalence was shown on the T4 only; if the pilot GPU differs, the check must be rerun. The non-T4 rule is RESOLVED
    (section 12 item c, section 9): same hard rule, the 1.4e-5 alarm is report-only off the T4.
14. **CLOSED: 9713 generated-row denominator.** The assertion counts manifest rows (`sampler.generated`); the `kernel_status.json`
    strip counts (5684 + 2828) mismatch is reported only, not asserted. 9713 = 19939 train rows, of which the generated 10300,
    minus 587 `layer.split` rows = 10300 - 587. Facts checked read-only
    (`python -I` over `D:/PiyaNota/datasets/kaggle_watch_a9_build/build/manifest/phase2_manifest.jsonl`, 2026-11-03):
    a manifest "row" is one staff strip (one voice of one system; keys include `piece`, `page`, `system`, `voice`,
    `source`). Train split 19939 rows = 10300 `source == "generated"` + 9639 Bach. Generated rows = 2575 systems x 4 voices
    (Soprano / Alto / Tenor / Bass 2575 each) from 972 pieces. 587 of the 10300 carry `layer.split`; dropping them gives
    9713 generated, and 9713 + 9639 = 19352 = the post-filter divisi pool, so the 9713 is a consistent manifest count. The
    build `kernel_status.json` `mix.generated_section` says `strips` 5684 and `decoy_strips` 2828 (sum 8512), and
    `generated_row_share` 0.5309; none of 8512, 5684, 2828 or .5309 matches 10300, 9713 or 10300/19939 (.5166). The
    definition of "strip" there (per-system rather than per-voice? chord-bearing only? train plus val?) is not stated in
    the files read, so the difference (10300 - 8512 = 1788) is NOT reconciled. `9713 = 10300 - 587` is arithmetic from
    the manifest (scripts `C:/Users/paul_/.claude/jobs/f2a331e8/tmp/v/disj.py` and `join.py`). Row versus strip must be
    defined before the 9713 assertion in section 9 is frozen.
15. RESOLVED (section 12 item e): the `a9_pilot_gates.py` string no longer hard-codes 1.12. Real values on the v1 pool: 0.741
    for 8 epochs, 0.371 for the 4-epoch pilot (section 7; both use the unverified 5,999).
15b. **For the pilot driver (17.8 follow-up; all UNVERIFIED):** (i) the e4 scorer (`below_dyad_split`: `ext[0]` at step <= -2) and the
    tuning gate (`is_below_staff_dyad`: both heads at or below `BELOW_STAFF_UPPER_STEP`) select targets differently, so the e4 denominator
    may be larger than 69: the driver logs BOTH counts. (ii) Whether `classify_columns` counts one or two members per dyad is unverified.
    (iii) Whether the build's 17 tuning heads overlap the supplemental heads is unverified.

## 12. Decisions required from the user (listed, not resolved)

a. RESOLVED. **User decision 2026-11-03:** `bach_bwv399` (supplemental) and `bach_bwv406` (test half) share a tune group
   with a train piece. Report every result BOTH with and without them. The version WITHOUT them is the decisive one.
   Reason: conservative; the two pieces may score optimistically. (Excluding them lowers the supplemental heads / sites,
   already below 100 heads and close to 40 sites; the effect on the tuning-gate count is not computed here.) This applies
   wherever the supplemental or test-half results are used (section 7 decision sets, section 10 caveat).
b. RESOLVED by section 15 items 1-3 (ml-cv-lead per-item verdicts, 2026-11-03).
c. RESOLVED. **User decision 2026-11-03:** on a non-T4 GPU the same hard rule applies (identical greedy tokens on all 50
   strips, old-row diff < 1e-4, expand-only control >= 1e-6). The 1.4e-5 drift alarm applies only to a T4 with the same
   torch / cuDNN as the 2026-11-03 run; on another GPU a diff above 1.4e-5 is reported but is not a halt by itself.
   Reason: the 1.4e-5 value was set from one T4 result, so it has no meaning on other hardware.
d. RESOLVED. **User decision 2026-11-03:** this PREREG stays a separate file from the design doc. Reason: the design file
   keeps the rulings; this file is the freeze candidate.
e. RESOLVED. **User decision 2026-11-03:** fix the hard-coded "1.12 draws/member" string. Reason: real values are 0.741 (8
   epochs) and 0.371 (4-epoch pilot). Done: `c2g_report(sites, draws_per_member=None)` in `a9_pilot_gates.py` now builds the
   text from the passed figure (call it with `train_phase2.expected_draws_per_generated_member(...)`); without it the text
   says "see the startup log". The 5,999 is still unverified: the pilot startup log must show 5,999 divisi draws/epoch and
   9,713 generated rows, or HALT. The "C2g not tested" null reading and `under_exposed` are unchanged.
f. RESOLVED (reporting rule; code now enforces it). **User decision 2026-11-03:** a C2g "fail" below 73 sites purely for lack of sites (Wilson UB
   <= 5% needs 73 sites at zero extras) is reported as UNDERPOWERED, not as a model failure. The held-out has 219
   below-staff sites, so this is not expected. CODE DONE (section 15 item 7): `C2G_MIN_SITES` = 73 and
   `c2g_report` returns "underpowered" below it.

## 13. Post-hoc decisions

Each was made after a result was seen and before any model was scored on the pilot data. They are not pre-registered
and are reported as such.
- **1e-4 operative equivalence ruling:** post-hoc, decided after the T4 result (1.335e-05), before any model scoring.
  (The outcome labels and the 1e-5 primary gate were fixed before the T4 output was read; the 1e-4 operative ruling was not.)
- **Tuning gate on combined heads (build 17 + supplemental 87 = 104):** post-hoc, decided after the build's 17 tuning-half
  heads, before any model scoring.
- **Tuning gate accepted at the coded per-seed count (17 + 87 = 104 heads, 43 sites; unique 69 / 39 not used):** post-hoc, decided after
  seeing the head counts (87 kernel, 69 unique), before any model scoring (User decision 2026-11-03, ml-cv-lead recommended (a); 17.8).
- **No top-up / e4 below-staff line report-only:** post-hoc, decided after the 87 supplemental heads were counted, before
  any model scoring. The report-only RULE itself ("under 100 heads or 40 sites it is report-only") was pre-registered
  (design, C2 yield); only the decision to apply it without topping up is post-hoc.
- **Arm C layer drop at train time (587 rows):** post-hoc, decided after the build, before any model scoring.
- **Accepting the Alto skew (generated Alto share 25.0% -> 20.5%):** post-hoc, decided after the layer drop was counted,
  before any model scoring.
- **2nd_none waiver (>= .95 x 257 for A9):** post-hoc, decided after Bach `--a9` gave 259 vs 257 (build rules, design
  section 7), before any model scoring.
- **Train gate lowered from >= 1000 to >= 500 below-staff dyad members:** post-hoc, decided after the 10-piece C2 yield
  check (16 dyads in 654 chords), before any model scoring.
- **1.4e-5 drift alarm:** post-hoc, set after the T4 result 1.335e-05, before any model scoring.

Pre-registered, not post-hoc (fixed before the data or results that tested them): the report-only rule for under-powered
below-staff lines (design, C2 yield, written before the build); the `--row-proj-lr-mult` rule (design section 7, the lr-smoke
decision rule, written before the pilot).

## 14. Before launch (not before freeze)

- Generated-share logging added to `train_phase2.py` (section 4 item 3) and the section 9 generated-row assertions.
- Pilot kernel written, and a pilot COMMIT chosen that descends from the freeze commit. It may change only: kernel files; logging and assertions in `train_phase2.py`;
  new eval-only files (driver, `p2_auc` probe, C2g site builder, the test-renders kernel). It must NOT edit `a9_pilot_gates.py`,
  the PREREG or the design doc. The driver must always pass `plain_columns` (`judge` can still return go when it is absent)
  (no change to lr, mult, mix shares, thresholds, vocab, pools or the supplemental set).
- Verify the A7 manifest pin `fe7be1e3` on the Kaggle copy and the real-stream `piyanota-divisi-a9-real` sha (neither
  verified here).
- HALT if the startup log does not show 5,999 divisi draws per epoch and 9713 generated rows.
- Record the A7 baselines: e3 and e4 omitted and wrong-step middle counts; e8 camera-shift delta; e8 presence probe; e8
  score on the supplemental set (section 6).
- GPU equivalence rerun on the pilot GPU (section 9).
- **C4:** the pilot driver must reproduce A7's recorded integer counts EXACTLY, checked on the A7 build WITH `bach_bwv399`
  (`a8_pre_c_s{1,2}{_e3,_e4,}.json` and `a7_c_s{1,2}_tune.json` under `D:/PiyaNota/datasets/phase2_divisi_a7/`); any difference
  blocks launch.
- **R7:** the no-scorer items (pilot driver, `p2_auc`, C2g site builder) are written and committed before launch (section 17.6).

## 15. PRE-FREEZE AMENDMENT 2026-11-03 (ml-cv-lead recommended; nothing scored yet), not post-hoc

The user approved ml-cv-lead's per-item verdicts conditional on that recommendation. Each is a pre-freeze amendment, not
post-hoc, unless a line says otherwise. Where it applies, ml-cv-lead's statement: "accuracy effect on the trained model:
none; evaluation/integrity measure". This PREREG is NOT signed off and NOT frozen.

1. **Fresh test renders (7.1 test set, the 14 test-half pieces).** Built and hashed BEFORE the pilot launch (CPU kernel only,
   no GPU; the eval-only kernel took about 108 min). Pieces are ranked by SITES, not only heads (the 87 supplemental heads
   come from 9 pieces, clustered). Sized to >= 100 below-staff heads and >= 40 sites WITH `bach_bwv406` EXCLUDED. The 7.1
   decision sets are frozen by a dated amendment once the renders are hashed. **The build itself is NOT yet approved: needs
   separate user approval for the CPU kernel run.** Accuracy effect on the trained model: none; evaluation/integrity measure.
2. **7.3 camera pitch stays on camera dev.** The 10-piece real set is a ONE-TIME CONFIRMATION reading, not a gate
   (CLAUDE.md: `piyanota_dataset` photos are TEST-only, never used for training, model selection or threshold tuning). This
   replaces the earlier section 7 wording (real 10-piece set decides camera pitch) and agrees with design:58 and a7:492-493.
   Accuracy effect on the trained model: none; evaluation/integrity measure.
3. **With/without rule on the fresh renders.** The with/without `bach_bwv399` / `bach_bwv406` rule (section 12 item a) applies to
   the fresh renders too; the size floor of item 1 is checked on the set without bwv406. Accuracy effect: none; integrity measure.
4. **A7 baselines.** Score A7 on the supplemental set now (it is in the tuning half). Score A7 on the test renders SEALED, at
   the same time as A9's full run, with both seeds; compare only the inside-A7-vocab subset (A7 cannot emit below-staff
   tokens). Needs separate user approval for any compute.
5. **e8 pass rule (triad 2+ >= .85, middle >= .78): NEW RULE (pre-freeze amendment).** Uses BOTH seeds and is judged on the
   worse seed's counts. Applies to the full C-s1/C-s2 run only, not the single-seed pilot. a7:313 is the camera-pitch rule;
   this extends it to triad/middle.
6. **Floors.** Gootville font-gap (<= .05) needs >= 300 Gootville heads, else UNDERPOWERED. Plain-column extra-heads kill
   (<= .005) needs >= 400 plain columns (ideally ~1000), else UNDERPOWERED; the earlier 100-head floor proposal is WRONG (at
   n = 100 one extra is .01 > .005). **Plain-column count (read-only, 2026-11-03, `eval_divisi_a6.columns` / `step_of`, same definition as
   `plain_below_extra`):** the denominator is GT columns with no chord whose note is at step <= `LEDGER_LOW` (-2), counted only
   where the LCS aligns a predicted column, so the figures below are UPPER bounds. Frozen Bach supplemental set (5 seeds,
   1758 rows, 11 tuning-half pieces): 835 plain below-staff columns (of 15,644 plain, 22,693 all columns); only 597 are
   unique (piece, voice, page, system, column, font, token) across the 5 seeds, from 10 pieces, so the seeds are repeats of
   one note pool, not independent. v1 manifest tuning-half val rows (884 rows): 498 plain below-staff columns, 392 without
   Gootville. Verdict: >= 400 on the raw count (835), below the ~1000 ideal; on the unique count (597) and on the aligned
   subset the margin over 400 is thin. The kill line is POWERED at the raw count only. Which set feeds
   `plain_below_extra_rate` is not fixed in code (no evaluator exists in the repo; design s5 says "Bach plain below-staff
   columns", s7/line 210 says the supplemental set): RESOLVED by ml-cv-lead in section 17 (v1 tuning-half val rows +
   supplemental seeds 1-5, without bwv399, Gootville excluded). NOTE: the 835 / 597 / 498 / 392 figures above INCLUDE
   Gootville rows in the supplemental set (428 of its 1758 rows); the decisive count excluding them is in section 17.
   The pilot driver must pass the realised aligned count as
   `plain_columns`. If it is < 400, `judge` reports `underpowered` (never kill, never go) and the rate is reported only.
   CODE DONE: `a9_pilot_gates.PLAIN_COLUMN_MIN = 400`; `judge(metrics["plain_columns"])` below it gives underpowered; an
   absent `plain_columns` is judged as before plus the note "plain_columns not supplied". OPEN: the Gootville >= 300 heads
   floor has no code; it belongs to the 7.1 font-gap evaluator (`training/phase2/eval_divisi_a7.py`, with
   `HELD_OUT_GAP` / Gootville handling inherited from `eval_divisi_a6.py`), full run, not the pilot `judge`.
7. **C2g floor derived, not hard-coded.** `C2G_MIN_SITES = ceil(WILSON_Z**2 * (1-.05)/.05)` = ceil(19 z^2) = 73 at z = 1.96
   (same z as `wilson_ub`; 19 = .95/.05; 72.99 -> 73; Wilson UB at 0/72 = .0507, at 0/73 = .0500). Below 73 sites the status is
   "underpowered", not "fail". Was 60 (sections 7, 11, 12 updated; design section 7 line 191 updated). Tests: 72 sites
   underpowered; 73 with 0 extras pass.

## 16. ml-cv-lead accuracy-lever review (2026-11-03)

(a) Trained-model levers.
- `--vocab-a9` and `--generated-share 0.15` MUST be in the pilot args. Without `--vocab-a9` the below-staff tokens are
  quarantined and the ledger target cannot be learned (code, measured); without `--generated-share` generated rows are about
  0.50 of divisi draws (computed). Verify both in the startup log.
- Do NOT change now (unproven): C2g exposure 0.37/0.74; Alto skew about 0.14 pp (inferred); lr mult 3 (chosen for stability,
  not accuracy); epochs; seeds.
- Likely main limit: below-staff training volume (824 members; the 1000 floor was lowered post-hoc; inferred, size unmeasured;
  an A10 data question).
- After freeze this PREREG forbids changing lr, mult, mix shares, thresholds, vocab, pools or the supplemental set.

(b) What the C-s1 pilot (e4 of 8) can tell: early kill if triad/middle/head_P trail at e3/e4; safety lines (plain extras,
canary, camera shift, dyad_2plus); init equivalence on the pilot GPU; whether keep-rows acted (the probe may be INCONCLUSIVE).

What it cannot tell: e8 accuracy (cosine LR halfway; A7 omitted middles kept falling e3-e8); seed variance (a 70% seed gap
in history); test-half accuracy; the ledger (report-only, 87 heads / 9 pieces); the font gap (no Gootville in the tuning
half); real-photo accuracy; C2g value (under-exposed); C1/C2/C3 attribution (confounded). The tuning half also served
design, so pilot numbers are optimistic.

## 17. Pilot metric definitions (frozen with the PREREG; ml-cv-lead conditions of 2026-11-03)

Written by reading the code on 2026-11-03; nothing was scored. `judge()` (`training/phase2/a9_pilot_gates.py`) consumes the keys
below and nothing else. Where the code does not fix a definition, the line says "AMBIGUOUS in code" and is listed in 17.5.
"NO SCORER" means no function in the repo produces the key; it is written in Task 9 (the pilot driver) and must follow this section.

### 17.1 Row sets (all tuning half; the test half stays closed)

| Name | Definition | Rows |
|---|---|---|
| RS-T | v1 train manifest `D:/PiyaNota/datasets/kaggle_watch_a9_build/build/manifest/phase2_manifest.jsonl` (sha256 `00dcfb19caeccd963edda98b70803c473973fa16766172d0ac5ffac9ae70a369`), `split == "val"`, tuning half by `divisi_halves.is_test_half` with `halves.json`, `font != "Gootville"` (this is `eval_divisi_a6.load_builds(..., "val", "tuning", chord_only, 0, 0, groups, ["Gootville"])`, run 2026-11-03) | 712 strips; 517 with a `chordnote-` token (`chord_only=True`) |
| RS-S | Bach supplemental manifest (sha256 `71aa33d70a5ef2d241b920bbc607bf663e5ee6e5ce9ef411f77c9857b81063f4`; file `a9_eval_done/eval_bach_supplemental/supplemental_manifest.jsonl`), seeds `divisi-a7-sup1..5`, per-seed shas in section 2 | 1758 rows, 11 pieces, all tuning half; 428 are Gootville, so 1330 without Gootville |
| RS-C | camera dev strips from `camera_shift_check.load_dev_camera("grey")` (`eval_dev.POOLS["camera"]`, only strips present on disk), shifts -3..-1 and 1..3 px plus the unshifted base; never `piyanota_dataset` | not counted here |
| Decisive Bach pool (plain-column line) | RS-T union RS-S, WITHOUT `bach_bwv399`, Gootville excluded (ml-cv-lead ruling) | see 17.3 |

Every Bach result is also reported WITH `bach_bwv399` (section 12 item a); the version WITHOUT it decides.

### 17.2 Metric table

Decoder for every row unless stated: greedy CTC (`stage3_transcription.transcribe_strip` -> `_greedy_ctc_decode`, or the identical
`_greedy_ctc_decode_with_confidence`), CPU, `img_height` 64, no beam, no header filter. Alignment: `eval_divisi_a6.columns` (one
column per `note.*` token plus the `chordnote-*` tokens right after it) and `eval_divisi_a6.lcs_pairs` on the note token with its
staff position stripped (`shape`); a GT column with no LCS partner is "unaligned". Staff step: `step_of`, L1 = 0, so "below staff"
is `step <= LEDGER_LOW = -2` and "above ledger" is `step >= LEDGER_HIGH = 10`. Pooling: micro, sums of numerators and denominators
over all rows and seeds of the set; no cross-seed de-duplication unless stated. Decision rule for every kill line: the POINT
estimate against the threshold in section 3. CIs reported beside it use the piece as the resampling unit and decide nothing.

| judge key | Scorer (file:function) | Row set | Numerator / denominator | Notes |
|---|---|---|---|---|
| `triad_2plus` | `eval_divisi_a7.py:a7_extras` key `triad_2plus`, ratio in `stop_checks` | RS-T (as `eval_divisi_a7.main`) | GT columns with >= 2 chordnotes whose aligned predicted column has >= 2 chordnotes / GT columns with >= 2 chordnotes (unaligned = miss) | `eval_divisi_a6.evaluate` de-duplicates only `bucket` across seeds, not this counter |
| `middle` | `eval_divisi_a7.py:a7_extras` key `middle` | RS-T | for GT columns with >= 2 chordnotes: steps `sorted(distinct steps)[1:-1]` found in the aligned predicted column's step set (main head included) / number of such steps | a middle is a step, not a token |
| `head_P` | `eval_divisi_a6.py:head_pr` (printed as `P` in `eval_divisi_a7.main`) | RS-T | `tp / (tp + fp_chord + fp_plain)`; `tp` = shared steps over aligned GT chord columns; `fp_chord` = predicted steps not in GT on those; `fp_plain` = `len(predicted steps) - 1` on aligned plain GT columns | main head included in all three; predicted columns with no GT partner are not counted |
| `dyad_2plus` | `eval_divisi_a7.py:a7_extras` key `dyad_2plus` | RS-T | GT dyad columns (exactly 1 chordnote) whose aligned predicted column has >= 2 chordnotes / GT dyad columns | an over-prediction rate, lower is better |
| `above_dyad_ledger` | `diag_divisi_a8_pre.py:classify_columns` key `ledger_dyad_above`, ratio via `summary` | RULED R1 (17.6): full RS-T census, 107 above-staff dyad members (A7 random 21 + top-up 86), not the 100-strip sample | GT dyad chordnote members with `step >= 10` whose step is in the aligned predicted column's step set (main head included) / all such members; unaligned members stay in the denominator | the A8 CLI (`diag_divisi_a8_pre.main`) samples 100 random strips plus a top-up; no pilot driver exists |
| `below_dyad_ledger` | `diag_divisi_a8_pre.py:classify_columns` key `ledger_dyad_below`, or `a9_pilot_gates.py:below_dyad_split` | RS-S (design, C2 yield) | dyad members with `step <= -2`, hit as above / all such members | RULED R2 (17.6): all members (inside + new), micro-pooled over raw rows; must equal `ledger_dyad_below` (driver asserts); inside/new split reported beside it |
| `below_dyad_heads`, `below_dyad_sites` | `a9_pilot_gates.py:below_dyad_split` (`inside` + `new` denominators; `sites` list) | RS-S | heads = target members; sites = distinct (strip id, note token, member token) | RULED R2 (17.6): heads = unique (piece, voice, page, system, column ordinal, note, member); sites = distinct (piece, voice, note, member); RS-S without Gootville and without `bach_bwv399` |
| `wrong_step_middles_per_100` | `diag_divisi_a8_pre.py:classify_columns` counters `middle_wrong_step_same` + `middle_wrong_step_extra`, summed with `merge` | 100 strips: `random.Random(0).sample(pool, 100)`, pool = RS-T strips with a `chordnote-` token (517, manifest order); `diag_divisi_a8_pre.main` defaults `--n 100 --seed 0`; the ledger top-up strips are NOT in the count | a COUNT of missed middle steps over those 100 strips where the aligned predicted column holds the same (`same`) or a larger (`extra`) number of chordnotes than GT; not a rate per 100 middles | RULED R3 (17.6): `same + extra` (design band 24-29 unchanged); sample pool drops `bach_bwv399` BEFORE the Random(0) draw (17.7) |
| `plain_below_extra_rate` | `a9_pilot_gates.py:plain_below_extra`; rate = sum(extra) / sum(n) | Decisive Bach pool (17.3) | numerator = number of CHORDNOTE TOKENS in the aligned predicted column (duplicates counted); denominator = aligned GT columns with no chordnote whose main note has `step <= -2` | NOT `eval_divisi_a6.head_scores.plain_extra` (that is `len(distinct predicted steps) - 1` over ALL aligned plain columns, any step); the kill uses the a9 scorer |
| `plain_columns` | sum of `n` from `plain_below_extra` | same | aligned plain below-staff GT columns | judge floor `PLAIN_COLUMN_MIN` = 400; per ml-cv-lead the floor is read on UNIQUE aligned columns, unique = (piece, voice, system, column ORDINAL, font, note token); RULED R6 (17.6): the floor counts unique aligned columns, the rate uses raw extras / raw aligned columns |
| `canary_ok` | `train_phase2.py` (about :1000-1028) writes `metrics.json` `status` | the run's own canary strips | ok iff `canary_clean_ser <= canary_clean_hard_cap` and `canary_distorted_ser <= canary_distorted_hard_cap` | RULED R4 (17.6): `canary_ok` = status != 'HARD CAP BREACHED', cross-checked against both hard caps (`a9_pilot_gates.canary_ok_from_epoch`, raises on disagreement); a soft-floor breach is NOT a kill |
| `non_chord_ser`, `prev_non_chord_ser` | no key of this name; nearest is `metrics.json` `val_ser` (`train_phase2.val_metrics`: mean over strips of `compute_ser`, greedy `decode_batches`, `val_rows`) | pilot val rows (not RS-T) | strip-mean SER; `prev_` = previous epoch | RULED R5 (17.6): `non_chord_ser` = metrics.json `val_ser`; kill iff `val_ser(e) > min(val_ser(1..e-1)) + SER_TOL` (SER_TOL = 3e-4), e1 not judged; judge key `val_ser_best_earlier` replaces `prev_non_chord_ser` |
| `camera_shift_excess` | `camera_shift_check.py:camera_shift_delta`, then `verdict` / `compare` | RS-C | delta = mean over the six shifts of corpus SER at that shift minus corpus SER unshifted; corpus SER = sum(edit_distance) / sum(GT tokens) over strips (edge-replicate vertical shift); excess = A9 e4 delta minus A7 e8 delta; kill if excess > .005 | `compare` refuses unless both runs used the same strips, strip ids and shifts. The key `camera_shift` (the delta) is an input to the excess, not consumed by `judge` |
| `p2_auc` | NO SCORER: the P2 generated-vs-Bach probe is not in the repo; written in Task 9 | e4 checkpoint | AUC | risk note, never a kill |
| C2g keys (`c2g_report`: `n_sites`, `extra`, `rate`, `wilson_ub`, `status`, `phrase_bootstrap_ub`, `by_shared`) | `a9_pilot_gates.py:c2g_report` | generated held-out, decoy kinds `single` and `instaff` | per site `extra` = the model emitted an extra head there; rate = extra sites / sites; pass iff Wilson UB (z = 1.96) <= .05 and sites >= 73 | NO SCORER builds the site dicts (`phrase`, `kind`, `shared`, `extra`): written in Task 9. Bootstrap B = 1000, `random.Random(0)`, unit = phrase |

On `plain_below_extra`: the numerator counts tokens; the older a6 gate counts distinct steps minus one. They differ when a predicted
chordnote repeats a step or repeats the main head's step. The kill line uses the token count, as coded and tested.

### 17.3 Plain-column line: set ruling, decisive count and consequence

- **Set (ml-cv-lead ruling 2026-11-03):** the plain-column kill line uses the tuning-half Bach pool with Gootville excluded =
  RS-T (v1 tuning-half val rows) plus RS-S seeds 1-5, the version WITHOUT `bach_bwv399` decisive; the floor is checked on unique
  aligned columns. Design section 5 ("Bach plain below-staff columns", set unspecified) and design section 7 / line 210 ("the Bach
  supplemental below-staff set") disagreed; this ruling resolves it. Both wordings are SUPERSEDED as set definitions (annotated in
  the design file).
- **Decisive GT-side count (CPU, read-only, 2026-11-03, no model output; script
  `C:/Users/paul_/.claude/jobs/f2a331e8/tmp/a9cnt/cnt2.py`, run with `python -I`):** GT columns with no chordnote whose main note has
  `step <= -2`, Gootville rows excluded, `bach_bwv399` excluded, unique = (piece, voice, system, column index, font, note token)
  across RS-T and seeds 1-5. **CORRECTED by R6 (17.6): the `cnt2.py` key used the TOKEN index `i`, which shifts across seeds
  when injected chordnotes change the token count; with the column ORDINAL (font kept) the decisive unique count is 581, not 772
  (font-agnostic: 223, a lower bound on the effective n; page makes no difference). The Raw column is unaffected; the RS-T and
  RS-S unique cells below were index-keyed and are NOT recomputed.**

  | Set | Raw | Unique | Pieces |
  |---|---|---|---|
  | RS-T (712 rows) | 388 | 388 | 8 |
  | RS-S seeds 1-5, no Gootville (1330 rows) | 655 | 481 | 9 |
  | **Decisive pool, RS-T union RS-S** | 1043 | **581** (was 772, SUPERSEDED; 223 font-agnostic) | 9 |
  | (with bwv399, for the "with" report) | 1053 | 778 | 10 |

  The 835 / 597 / 498 / 392 figures of section 15 item 6 included Gootville rows in RS-S and are not the decisive numbers. These
  are GT-side upper bounds: the scorer's denominator counts only LCS-aligned columns, so the realised `plain_columns` is smaller.
  No alignment rate is known before a model is scored.
- **Consequence:** 581 >= 400 (R6), so the plain-column extras line STAYS a kill line with the 400-column floor (it is not declared
  report-only in advance). It would fall under 400 only if alignment lost more than 31% of the unique columns (not measured).
  The font-agnostic 223 shows the effective n is smaller than 581 (fonts re-draw the same places); recorded, the floor is unchanged.
- **Near-threshold risk (recorded before scoring):** the line is a point estimate, `extra / n <= .005`. At n = 400, 2 extras pass
  (.0050) and 3 kill (.0075). Poisson approximation computed here: at a true rate of .0025 (half the line) the chance of >= 3 extras
  at n = 400 is .080 (about 8%) before clustering. The earlier 13% figure belongs to n = 772 (4 extras kill) and is superseded, since R6 corrected the unique count to 581
  (223 font-agnostic). At n = 581 the line kills at >= 3 extras (581 x .005 = 2.9; 2 pass .0034, 3 kill .0052 on unique columns,
  the rate itself uses raw columns): P(X >= 3 | lambda = 581 x .0025 = 1.4525) = .179 (about 18%). At n = 223 it kills at >= 2
  extras (223 x .005 = 1.1): P(X >= 2 | lambda = .5575) = .108 (about 11%). All of these ignore piece clustering (9 pieces), which widens the spread, so a kill at 3-4 extras sits close to the
  noise and is reported with its counts. The threshold is not changed for this (frozen).
- `judge` receives the rate from `plain_below_extra` on raw pooled rows (no cross-seed de-duplication), while the floor uses unique
  columns (1043 raw vs 581 unique here). The ruling states only the floor; see 17.6 R6 (resolved).

### 17.4 Other pre-registered reading rules

- Reported CIs: Wilson plus piece bootstrap (B = 1000, seed 0, `eval_divisi_a6.piece_bootstrap_lb`), the piece as the resampling unit.
- A missing metric is "underpowered", never go; the decision is saved before anyone reads the metrics (section 3).
- Greedy decode only: no beam search and no header filter in any metric above.

### 17.5 Open items for ml-cv-lead (AMBIGUOUS in code or NO SCORER; not invented)

ITEMS 1-6 BELOW ARE RESOLVED / SUPERSEDED by the pre-freeze rulings in 17.6 (R1-R6); item 7 is refined by R7. Kept for the record.

1. RESOLVED R1. `above_dyad_ledger`: the row set is not fixed anywhere (A8 CLI = 100 random chord strips plus a top-up; design says "tuning half"). Confirm RS-T.
2. RESOLVED R2. `below_dyad_ledger` / `below_dyad_heads` / `below_dyad_sites`: all members (`ledger_dyad_below`) or only the inside-A7-vocab subset (`below_dyad_split["inside"]`) feed the line; whether Gootville and `bach_bwv399` are excluded from RS-S when counting the 87 heads / 43 sites (removing rows can only lower them, so report-only holds either way); whether heads are de-duplicated across seeds (`below_dyad_split` does not; `head_key` in `eval_divisi_a6.dedup_columns` does, for the `ledger` bucket).
3. RESOLVED R3. `wrong_step_middles_per_100`: `middle_wrong_step_same` only, or `same + extra`; and how A7's "24-29" was counted (not traced here).
4. RESOLVED R4. `canary_ok`: `judge` says "under hard cap"; `train_phase2` writes only `status` (`OK`, `soft floor breached`, `HARD CAP BREACHED`); `eval_divisi_a7.main` maps `status == "OK"` to ok, which would treat a soft-floor breach as a kill. The mapping is not in code.
5. RESOLVED R5. `non_chord_ser`: no such key; `metrics.json` `val_ser` is the only per-epoch non-divisi SER found. Confirm, and whether a strict `ser > prev` with no tolerance is intended.
6. RESOLVED R6. Plain-column line: rate on raw pooled columns (code) vs floor on unique aligned columns (ruling); confirm the pilot driver passes the unique aligned count as `plain_columns`.
7. REFINED R7 (17.6). NO SCORER, written in Task 9: the pilot driver that builds the metrics dict, the `p2_auc` probe, the C2g site-dict builder.
8. **Tuning-gate head definition: kernel vs unique. CLOSED by option (a), not redefined post hoc** (User decision 2026-11-03, ml-cv-lead recommended (a)). See 17.8.

### 17.6 ml-cv-lead pre-freeze rulings 2026-11-03 (no A9 output seen; GT only)

- **R1 `above_dyad_ledger`:** full RS-T census = 107 above-staff dyad members (A7 random 21 + top-up 86), NOT the 100-strip sample. The
  21-member random sample alone would have killed A7 s1 at e3 (14/21 = .667 < .68).
- **R2 `below_dyad_ledger`:** value = all members (inside + new), micro-pooled over raw rows; rows = RS-S without Gootville and without
  `bach_bwv399`; equals `ledger_dyad_below` (the driver ASSERTS equality); the inside/new split is reported beside it. heads = unique
  (piece, voice, page, system, column ordinal, note, member); sites = distinct (piece, voice, note, member).
- **R3 `wrong_step_middles_per_100`:** count `same + extra` (A7 recorded same 28/24 e3, 26/29 e4, 29/24 e8; extra 0-1; the design band
  24-29 is unchanged). Files: `a8_pre_c_s{1,2}{_e3,_e4,}.json` under `D:/PiyaNota/datasets/phase2_divisi_a7/`.
- **R4 `canary_ok`:** `status != 'HARD CAP BREACHED'`, cross-checked against both hard caps in run_info (NOT `status == 'OK'`: the
  mult-3 smoke breached the soft floor at every epoch). Implemented: `a9_pilot_gates.canary_ok_from_epoch(rec, run_info)` returns the
  bool that `judge` already consumes as `canary_ok`; it raises if status and caps disagree.
- **R5 `non_chord_ser`:** `metrics.json` `val_ser` (strip-mean `compute_ser` on the Phase-1 val rows, `train_phase2.py` ~:758, ~:908),
  not CPM. Kill iff `val_ser(e) > min(val_ser(1..e-1)) + SER_TOL`, `SER_TOL = 3e-4` (named constant in `a9_pilot_gates.py`); e1 is not
  judged on this line. A7's largest epoch-to-epoch rise was +9e-5; a strict `>` would have killed A7 C s1 at e4 (.00152 -> .00154).
  Key shape: the current epoch's value is `non_chord_ser`; the history enters as the NEW key `val_ser_best_earlier` (min over epochs
  1..e-1, absent at e1); `prev_non_chord_ser` is removed. Tested on the real A7 c_s1 / c_s2 series (`a7_c_s{1,2}/metrics.json`).
- **R6 plain-column line:** rate = raw extras / raw aligned columns; `plain_columns` (floor) = unique aligned columns. The older 17.3
  count (772) was wrong (token-index key); with the column ordinal and font kept it is 581; font-agnostic 223 (lower bound on the
  effective n); page makes no difference. 581 >= 400, so the line stays a kill line.
- **R7 no-scorer items:** written in Task 9, committed BEFORE launch, frozen now: (a) inputs: manifest and halves shas, checkpoint
  paths; (b) exact output keys = the judge keys + `plain_columns` + `plain_columns_raw` + the raw counts; (c) the judge output is saved
  FIRST, before any report-only number; (d) `p2_auc` and the C2g site builder are report-only and not needed for the pilot decision:
  their inputs and definitions are frozen at launch or labelled post-hoc; (e) C2g `extra` = the aligned decoy column has >= 1
  chordnote; unaligned sites count as not-extra and are reported.

### 17.7 Row-set facts recorded before launch (C3)

- RS-T contains `bach_bwv399`. The "without" rule (section 12 item a) drops it BEFORE the `random.Random(0)` 100-strip sample for
  `wrong_step_middles_per_100`, so the pool is RS-T chord strips without `bach_bwv399` (the 517 above includes it and shrinks).
- The A7 baselines (e3 / e4 / e8, both seeds) are RESCORED on that same sample (same pool, same Random(0) draw), not read from the A7
  files, which were drawn from the pool WITH `bach_bwv399`.

### 17.8 Tuning-gate head definition: kernel vs unique (CLOSED by option (a); supplemental set, read-only recount 2026-11-03)

Kernel definition (`a9_corpus.supplemental_counts`, called by `piyanota_divisi_a9.py` ~:518, then
`divisi_a7_gates.tuning_final_verdict`): across all rows (fonts included), keep ONE row per (eval_seed, piece, voice, system), the first
in manifest order (1758 rows -> 930 strips; the font of that row is whichever came first, Gootville included); on each kept strip
count every chord column that is a below-staff dyad (`is_below_staff_dyad`: exactly one chordnote, both heads at `step <= -2`) as one
head, per seed, no cross-seed dedup; sites = distinct (piece, voice, system, upper step, lower step), across seeds. Reproduced exactly
from the manifest: 87 heads / 43 sites / 9 pieces. The gate adds the build tuning half (`rendered_below_counts`: one strip per
(piece, voice, system) over all fonts, tuning-half val rows, v1 manifest sha `00dcfb19...`) = 17 (recomputed 17, 15 sites; the same under
a unique-column key).

| Definition | Supplemental heads | Sites | Pieces | Gate (needs >= 100 heads and >= 40 sites) |
|---|---|---|---|---|
| (i) kernel (coded, pre-registered) | 87 | 43 | 9 | 17 + 87 = 104 heads, 43 sites: pass |
| raw dyad columns, all 1758 rows | 164 | not computed | not computed | not the gate's definition |
| raw dyad columns, no Gootville, no bwv399 (R2 rows, 1210 rows) | 120 | | 9 | |
| (ii) R2 unique heads, dyad level: unique (piece, voice, page, system, column ordinal, note, upper member) | 69 (ml-cv-lead counted 62; NOT reproduced, close variants give 63-69) | 39 (distinct (piece, voice, note, upper)) | 9 | 17 + 69 = 86 (17 + 62 = 79) heads < 100; sites 39 < 40: would not pass |
| (ii') R2 unique heads, member level (each dyad = 2 members) | 137 | 73 (distinct (piece, voice, note, member)) | 9 | 17 + 137 = 154 heads, 73 sites: would pass; the unit (dyad column vs member) is itself ambiguous in the R2 wording |

The numbers differ because the kernel counts every font-free strip once per seed and its site key includes `system`
(so a repeated place in another system is a new site), while the unique definition collapses re-draws of the same place across seeds.
Whether the build tuning 17 and the supplemental heads overlap in pieces was not checked (the sum would double count). Scripts:
`C:/Users/paul_/.claude/jobs/f2a331e8/tmp/c5/{cnt,cnt2,b17}.py` (`python -I`; `cnt.py` re-implements `supplemental_counts` inline
because `a9_corpus` needs music21/verovio, which are not installed here).

**Closed: User decision 2026-11-03, ml-cv-lead recommended (a).** Accept the coded, pre-registered per-seed head count for the tuning
gate and DISCLOSE the limitation. Option (b) (top-up) declined; option (c) (post-hoc redefinition) rejected. Disclosure:

> The tuning gate is met at 17 + 87 = 104 heads and 43 sites under the pre-registered per-seed count (`a9_corpus.supplemental_counts`;
> design line ~224 and the docstring: heads count every column per seed, conservative on purpose). 18 of the 87 heads repeat a head from
> an earlier seed (same piece, voice, page, system, column ordinal, note, member). Distinct supplemental dyad heads number 69 (about 52
> on content; 15 more repeat at a shifted column ordinal). On distinct chords the gate would read 17 + 69 = 86 or fewer. Seeds 1-5 share
> 9 pieces; new unique heads per seed were 18, 13, 15, 14, 9 (saturating); new sites per seed 17, 10, 8, 4, 4. A repeat is the same Bach
> chord redrawn in a new context: a correlated re-render, not a new example.

The supplemental set is an EVALUATION set (tuning-half pieces, disjoint from train), so a top-up would improve measurement only, not the
trained model.

**e4 below-staff unit.** The e4 below-staff unit is the dyad column (design line 53: below-staff dyad ledger < .50 (>= 100 heads, else
UNDERPOWERED); line 176: >= 100 below-staff heads from >= 40 distinct sites). Under R2 unique (69 heads / 39 sites) or the kernel count
(87 / 43), e4 is report-only either way. A member unit (137 heads / 73 sites) would have made e4 powered and kill-capable; it was
rejected because no scorer supports it (`below_dyad_split` scores one target per column, `ext[0]`). Fixing the unit at the dyad column is
a pre-freeze reading of the pre-registered design (no A9 output seen) but it does keep the line from killing; stated openly.

## 18. Freeze checklist

- C1: done.
- C2: done (`SER_TOL` and the canary mapping are committed in `a9_pilot_gates.py`).
- C3: done (recorded, 17.7).
- C4: BEFORE LAUNCH. The pilot driver reproduces A7's integer counts exactly (section 14).
- C5: done (69 < 100 heads and 39 < 40 sites: e4 stays report-only; 17.8).

Still to happen BEFORE LAUNCH (not before freeze):
- Pilot kernel written; pilot COMMIT descends from the freeze commit and changes only the allowed set in section 14 (kernel files;
  logging/assertions in `train_phase2.py`; new eval-only files; never `a9_pilot_gates.py`, PREREG or design doc).
- Generated-share logging in `train_phase2.py`, and the section 9 generated-row assertions.
- A7 pin `fe7be1e3` verified on the Kaggle copy, and the real-stream `piyanota-divisi-a9-real` sha.
- A7 baselines recorded (section 6, 17.7).
- GPU equivalence rerun on the pilot GPU (section 9).
- Fresh test renders built (needs separate user approval).
- Pilot driver committed and reproducing A7 exactly (C4).

## 19. Post-hoc amendment 2026-11-04 (test-renders completeness rule; nothing scored, nothing sealed)

Test-renders v1 (`piamacc/piyanota-divisi-a9-testrenders`) aborted on seed 1 because three (piece, font) cells (bwv361/Petaluma,
bwv406/Leipzig, bwv406/Gootville) had no rows after Stage 2 dropped their pages (9 staff regions, not divisible by 4; `no_strip_source`).
The completeness assert added in 63889ae is not PREREG text. It is relaxed: a missing (piece, font) cell is recorded in the sealed
record as `dropped_cells`, and the build aborts only if a test piece has no rows in any font. The stop rule (>= 100 unique heads,
>= 40 sites, bwv406 excluded, max_seeds 16) is unchanged. No piece or seed was changed or removed; Stage 2 stays the cutter (train = serve).
Drops depend on the render, not on any model, and are the same render-and-cut bias recorded in section 10. Per-font comparisons (the
Gootville font gap) are reported on piece-matched cells only, and the per-font drop rate is reported next to the result.
Accuracy effect on the trained model: none; this is an evaluation-integrity change. Ruled by the user 2026-11-04 (keep Stage 2).

## 20. Post-hoc amendment 2026-11-04 (test-renders seed cap 16 -> 24; no model has scored these renders)

Test-renders v2 (`piamacc/piyanota-divisi-a9-testrenders`, orchestrator 8104e5a) ran all 16 seeds and finished `underpowered`.
First-pass result, bwv406 excluded: 212 heads, 116 unique heads, 38 sites, 9 pieces (with bwv406: 239 / 133 / 43 / 10). The unique-head
floor (100) held, the site floor (40) was missed by 2, and the Gootville floor (300 heads) was not met (212). 38 of 1120 piece x font
x seed cells were dropped by Stage 2 (Petaluma 6.7%, Gootville 6.2%, Leipzig 2.7%, Leland 1.3%, Bravura 0%; bwv406 18, bwv361 16,
bwv265 4). The first-pass sealed manifest sha is `976f97f299015f3774ef6092a718cee23e364a3536209c70410014afd22e512c` (renders tar
`db84bfdd4cc559d2b5c68f4920bc8fc5e441e4ae8f42c8a91ec2731cd815b012`).

Decision (user, with an ml-cv-lead GO-with-conditions, 2026-11-04): `TEST_MAX_SEEDS` is raised once, from 16 to 24, and never again.
The stopping variable is a count of heads and sites, not a model score, and no model has scored these renders.

Conditions, all binding:
1. This amendment is committed before any new seed runs.
2. The stop rule is unchanged: at least 100 unique heads and at least 40 sites, bwv406 excluded, evaluated after each seed. The run
   stops at the first seed where it holds. If a floor is unmet at seed 24 the result is reported `underpowered`; there is no further raise.
3. Seeds 1-16 must reproduce byte-identically. The new run builds seeds 1..24 from scratch (seeds are deterministic by seed string);
   each seed's `manifest_sha256` and `strips_sha256` for 1-16 is compared with the first-pass record, and any mismatch is reported.
4. The Gootville floor of 300 heads is unchanged and best effort: it does not stop or extend the run. If unmet, the Wilson bound
   actually reached is reported and labelled underpowered (A6 design rule, line 163). It is not relaxed.
5. bwv406 stays excluded; with-bwv406 counts are reported beside the main figures.
6. Dropped cells are not re-rendered or retried. Per-font and per-piece drop rates are reported; Gootville comparisons use
   piece-matched cells only.
7. Site counts saturate (seeds repeat one note pool). An unmet site floor at the cap means the C2g gate is reported underpowered under
   the existing rule.
8. No model is scored on these renders until the extended set is sealed. The new manifest sha supersedes `976f97f2...`, which is
   listed as superseded (first 16 seeds).
9. Every result that uses this set states that the cap went from 16 to 24 after an underpowered first pass, with the first-pass numbers above.

Accuracy effect on the trained model: none; this is an evaluation-integrity change. CPU only (GPU gives no speedup: the work is
CPU-bound rendering and OpenCV cutting).

## 21. Pre-launch amendment 2026-11-04 (noise reading, reporting, kill labelling; nothing scored on A9, thresholds untouched)

Origin: smoke v4 (ad71d8a) passed 6 of 7 plumbing checks; its GPU-reference check was a bad gate (the v1 reference came from older code and
a different row set). The ml-cv-lead full-PREREG review the same day found that the eval decodes on CPU (`eval_divisi_a6.decode_strip`),
so a re-eval of one checkpoint measures eval repeatability only; the noise that matters for reading A9 against A7 is training-seed noise.

1. Kill lines, thresholds, row sets and the one-seed rule are unchanged. A kill is a kill.
2. Noise is read from (a) A7 seed 1 vs seed 2 at the same epoch (e3, e4, e8) on the 712-row no-bwv399 sample, and (b) eval repeatability
   (same checkpoint, two evals, CPU decode). Any A9-vs-A7 comparison, and the s6 attribution, that differs by less than the larger of the
   two is reported as "no detectable change", never as a gain or a loss. This does not apply to kill-line decisions.
3. A kill within one noise width of its threshold is labelled "kill, within noise". The run still stops; any further run needs a new
   pre-registration.
4. Report-only, post hoc, from saved checkpoints: piece-bootstrap CI for plain-below (`a6.piece_bootstrap_lb`), p2_auc, the C2g report
   (a null means "not tested": exposure is 0.371 draws per generated row).
5. Confidence AUC, report-only: on A7 e8 and A9 e4, over aligned GT chord columns without bwv399, label = "predicted chordnote set equals
   the GT set", score = minimum token confidence in the column; AUC with a piece-bootstrap 95% CI (B=1000, seed 0). A usable
   confident-wrong detector remains an open item; a pass is not a safety claim for the divisi path.
6. The "any epoch" lines are judged at e3 and e4 in the pilot; a hard-cap breach at any epoch still stops training.
7. A "go" at e4 means no kill. It is not evidence of e8 accuracy. The kill-line set is also the design set (11.6), so a pass is optimistic.
8. Before launch (binding): A7 e3 and e4, seeds 1 and 2, are scored on the 712-row no-bwv399 sample as the paired baseline and the
   training-noise estimate.

Accuracy effect on the trained model: none; reporting and labelling only.

### 21.1 Correction to the s21 origin (2026-11-04, same day; nothing scored on A9)

The s21 origin paragraph says the v1 smoke reference "came from older code and a different row set". That was wrong. Local CPU scoring of
A7 e8 seed 1 on the pilot's 712 rows (`a7_on_pilot_rows.json`) reproduces the smoke v1 numbers as the WITH-bwv399 values
(0.7606 / 0.6658 / 0.9518 / 0.0063) and the smoke v4 numbers as the WITHOUT-bwv399 values (0.7642 / 0.6755 / 0.9513 / 0.0068). The v4
"failure" compared two different row subsets, so there was no GPU-vs-CPU or run-to-run difference at all; T4 and CPU agree to the digit.
Rules 1-8 of s21 stand. Rule 2(b) (eval repeatability) is already met by this agreement. Rule 8 is satisfied by `a7_on_pilot_rows.json`.
Training-seed noise (A7 s1 minus s2, without bwv399, 712 rows, maximum absolute over e3/e4/e8): triad_2plus 0.046, middle 0.031,
head_P 0.013, dyad_2plus 0.009.

### 21.2 Plain-below is report-only in this pilot (2026-11-04; nothing scored on A9; thresholds untouched)

Measured with `training/phase2/score_a7_plain_below.py` on the pilot's 712 rows without bwv399 (`evidence/a7_plain_below.json`, CPU):
the judged set has 379-383 unique plain below-staff columns (387-391 with bwv399), not 581. That is below `PLAIN_COLUMN_MIN` = 400, so
`judge()` returns `underpowered` for `plain_below_extra_rate` at every epoch (never kill, never go on that line). The rate is reported only.
A7 reference extras / columns (without bwv399): s1 e3 1/383, e4 2/383, e8 1/387; s2 e3 2/379, e4 0/383, e8 2/382 (0.00-0.53%).
At this column count 2 extras already exceed .005, so the line would be a coin flip even for A7 if the floor were met.

1. A9 "go" at e3 or e4 says nothing about plain below-staff extras; read it as "not tested".
2. The "kill, within noise" label (s21 rule 3) cannot arise from this line. Other lines still kill.
3. More plain below-staff columns need a new row set and a new pre-registration, not a launch change.

## 22. Pre-launch amendment 2026-11-04 (second seed in parallel, plain-below human gate, confident-wrong scorers; nothing scored on A9, all kill lines, thresholds and row sets untouched)

Origin: ml-cv-lead pre-launch review. A one-seed pilot cannot tell a seed-1 accident from a property of the design: A7 seed-to-seed noise (s21.1) is up to 0.046 on triad_2plus and 0.031 on middle, comparable to the distance between some kill lines and the A7 values. Nothing has been scored on A9. Section 3 kill lines, section 17 metric definitions and the section 19-21 row sets are unchanged.

### 22.1 Second seed, launched in parallel

1. A second pilot, arm C seed 2, is launched at the same time as seed 1 (kernel `piamacc/piyanota-divisi-a9-pilot-c-s2`), same pilot commit, same TRAIN_ARGS, same data, same 4-epoch stop. Only the seed and the init differ: seed 2 starts from the deployed `phase2_seed2.pt` (sha256 `f79892acbcb3a410f8a55c2b4f7289354111a29a7ed439c2990cfd755cbdaed4`, the same value as `divisi_a7/phase2_divisi_a7_kernel.py` INIT_SHA256[2]), as every A7 seed-2 run did (design freeze section 2: seed k starts from Phase 2 seed k).
2. Each seed is judged separately by `judge()` against the unchanged section 3 kill lines. No averaging, no pooling, no "best of two", no looser line for either seed.
3. Outcomes: both seeds non-kill = go to the full run. Exactly one seed killed and one non-kill = "inconclusive, needs a new PREREG"; no full run and no relaunch until that PREREG exists. Both seeds killed = kill. A "go" keeps its s21 rule 7 meaning (no kill at e4; not evidence of e8 accuracy).
4. Amendments to earlier wording. s21 rule 1 ("the one-seed rule is unchanged") and the s9 sentence "a pilot is one seed, not a replicated result" are replaced by this section: the pilot is two seeds. Section 3's "A killed run is not resumed and not relaunched with another seed" stays in force in this sense: a killed seed is never resumed and never rerun under a different seed to rescue it. Launching seed 2 now, in parallel and before either seed has been judged, is a registered design choice, not a relaunch.
5. Equivalence and start checks (s9) run on each seed's own init on its own GPU. The 2026-11-03 T4 equivalence result (1.335e-05) is seed 1 only; no seed-2 equivalence result exists before launch. The seed-2 kernel reports its own value; the hard rule (identical tokens, diff < 1e-4, control >= 1e-6) is unchanged.
6. Camera-shift line, unchanged definition: the A7 e8 reference delta is the one shipped in the camera pack (A7 e8 seed 1). Both A9 seeds are compared with that single reference. It is not a seed-matched comparison for seed 2; this is stated, not corrected, so the kill line is not altered. If a seed-2 A7 e8 camera delta is computed later, it is reported beside the line and does not decide.
7. Noise reading (s21 rule 2) applies per seed: an A9-vs-A7 comparison smaller than the A7 seed-to-seed width is "no detectable change". Per-seed kill lines are exempt from that rule, as in s21.
8. Cost note: two GPU kernels at once; whether the account may run two concurrently is a Kaggle quota matter, not part of the PREREG. If only one can run, seed 1 runs first and seed 2 follows without any change to the rules above; seed 2 must not be judged first and used to choose anything for seed 1.

### 22.2 Plain-below human gate and the C2g decoy report

1. Plain-below stays report-only in `judge()` (s21.2: about 383 judged columns, below `PLAIN_COLUMN_MIN` = 400, status `underpowered`). Added as a human gate, not a kill: if either seed shows 8 or more plain below-staff extras on the judged columns at e3 or e4, the full run is blocked until a human has reviewed the extra columns (strip images and tokens). 8 of about 383 is 2.1%, about four times the largest A7 count (2 of 383). This is a judgement threshold chosen by the author from the A7 range, not a statistically derived line, and it is not an automatic kill. Fewer than 8 does not release the full run by itself; it only means this gate does not block.
2. The C2g decoy extra-head report (`c2g_report`, section 7: Wilson upper bound of the per-site extra-head rate, single and instaff decoys only, phrase-cluster bootstrap beside it) is added to the e4 read-out for each seed, with the realised decoy-site count stated. "Underpowered" is reported as such; it is never a pass.

### 22.3 Report-only confident-wrong scorers (registered before any A9 scoring)

Purpose: s21 rule 5 reports a confidence AUC (min token confidence in a column vs "predicted chordnote set equals the GT set"). Add structural-plausibility scorers beside it, defined now so they cannot be chosen after seeing A9 output. Run on A7 e8 (seeds 1 and 2) and on A9 e4 (both seeds), same aligned GT chord columns without bwv399, same piece-bootstrap (B = 1000, seed 0).

A predicted chord column is "structurally implausible" if any of:
- a chordnote step appears twice in the column;
- a chordnote is on the same step as the main (first) note head;
- chordnote steps are not monotone in the token order used by the labels (C1 x-order / step order as defined in the label converter for the column);
- the column has more than 3 heads, or any head lies outside the ledger range allowed by the vocabulary.

Reported per checkpoint: the rate of implausible columns; AUC of the implausibility flag as a detector of "column wrong" with a piece-bootstrap 95% CI; and the false-negative rate, meaning the share of wrong columns (predicted set not equal to the GT set) that are structurally plausible. No threshold, no kill, no go/no-go depends on these numbers.

Reading limit, stated in advance: these scorers can only catch impossible output. A wrong step that is a legal chord (the common case: a plausible but wrong middle step) is by construction invisible to them, so a high false-negative rate is the expected result and does not make the design safe. A usable confident-wrong detector for the divisi path stays an open item (s21 rule 5).

### 22.4 Product side, separate ticket

Flagging chordnote columns in Stage 4 (`divisi_unvalidated` / `review_needed`, as clef/key does with `clef_key_unvalidated`) is a product change, not an experiment change. It is a separate ticket and is not part of this PREREG or the pilot.

### 22.5 Baselines checked on 2026-11-04 (recorded, nothing here scored on A9)

- A7 omitted / wrong-step middle counts at e3, e4, e8, both seeds: present in `.superpowers/sdd/2026-11-01-a9-build-and-pilot/a9_repro.json` (`runs.<seed>_<epoch>.rows`, names `*.totals.middle_*`), A8 100-strip tuning-half sample, which reproduced the recorded values. omitted / wrong-step same / extra: s1 e3 56/28/1, s1 e4 32/26/0, s1 e8 17/29/0, s2 e3 57/24/0, s2 e4 37/29/0, s2 e8 26/24/0. This replaces the s6 "not verified" for A7 e3/e4. These totals are descriptive; whether this 100-strip sample is the same one the e4 `wrong_step_middles_per_100` line uses (section 3) was not checked here.
- A7 e8 presence-probe baseline (design section 6 and section 1): present, `D:/PiyaNota/datasets/kaggle_watch_a9v2/piyanota-a9-probe-run/a9_presence_c_s1.json` and `..._s2.json` (checkpoints `c_s{1,2}_e8.pt`), pre-registered reading INCONCLUSIVE (control). `emit` middle recall: CNN map .848 / .796, LSTM input .749 / .716, LSTM output .725 / .686 (s1 / s2). The new `rows` tap has no A7 baseline by construction (A7 has no keep-rows layer); the "acted" test compares `rows` with `cnn4` on the same checkpoint.

## 23. Amendment 2026-11-05 (C2 rerun after the s22 pilot was killed at e3; FROZEN 2026-11-05 at the commit that launches the seeds)

**Why.** Both s22 seeds were killed at e3 of 8 on chord gates (s1: 3 of the e3 chord lines failed). Eval-only rescoring of
e1-e3 (RS-T, 712 rows, tuning half, so optimistic) and a thin train-side check (30 Bravura rows) show chord metrics still
rising together on held-out and train-side rows, with train loss still falling (0.212/0.146/0.119). Reading: undertraining
(about 5.6k steps by e3, new fc rows init N(0, 0.01), lr already decaying on an 8-epoch cosine), not shown to be a data
shortage (pool 19,352 real-rendered + 9,713 generated rows, about 6k draws per epoch). The train-side check is too small
to exclude a distribution mismatch. ml-cv-lead redesign 2026-11-05; the user ruled "lets judge at e8 but continue if it
passes gates to improve the accuracy".

**23.1 New run identity.** Arm C, seeds 1 and 2, run names `a9_c2_c_s{1,2}`, kernels `piyanota-divisi-a9-c2-s{1,2}`. Fresh
start from the SAME original init as s22 (seed 1: sha 5c444ad3..., seed 2: sha f79892ac...). The s22 e3 weights are NOT used.
The s22 outputs stay untouched as the evidence for this amendment.

**23.2 Changed training arguments (everything else, data, pins, row sets, halves, canary caps, as s22).**
`--max-epochs 10` (cosine T_max 10), `--stop-after-epoch 10`, `--lr 5e-5` with `--warmup-epochs 1` (per-step linear),
`--divisi-share 0.30` (about 10.3k divisi draws per epoch; exact counts pinned from the smoke log via
`--a9-expected-divisi-per-epoch` / `--a9-expected-generated-per-epoch` before the real push), `--fc-new-lr-mult 10`
(fc rows at index >= BASE_VOCAB_SIZE move 10x further per AdamW step, applied as a post-step delta because AdamW is
invariant to gradient scaling), `--row-proj-lr-mult 3` unchanged, no weighted sampling. `--reseed-per-epoch`: the sampler
generator and the numpy/torch global RNGs are reseeded with seed*1000+epoch at each epoch start. `--a9-eval-epochs 4 6 8 10`
(driver + judge only at those epochs and the last one).

**23.3 Judge (replaces s14 kill epochs and R5 for this run only).** `--a9-c2-judge`:
* Evaluated epochs: 4, 6, 8, 10 only. Canary hard cap is enforced in the training loop at every epoch; `plain_below_extra_rate`
  <= .005 (when powered; at 383 < 400 columns it is `underpowered`, so it is report-only) is judged at the evaluated epochs.
* e4 and e6: safety lines plus a hand-set collapse floor (`C2_COLLAPSE_FLOOR` = 0.10): triad_2plus or middle below it is a
  KILL (stop and diagnose). It is a prior far below any s22 value, not fit to data. Other chord lines and R5 are NOT applied;
  their values are saved in `judge_e{N}.json`. The e4/e6 values are NOT used to change any argument (no peeking).
* e8: the s22 e8 pass rule: triad_2plus >= 0.85 and middle >= 0.78 (RS-T, without bwv399), plus the s22 e4 table lines
  (wrong_step_middles_per_100, above_dyad_ledger, below_dyad_ledger, dyad_2plus <= .02), the e3 head_P line and the safety
  lines. The camera-shift line is NOT applied (the camera check runs at e4 only). A fail is a KILL; "pass" means no kill reasons in `judge_e8.json` and the run continues to e10. With 383 plain-below columns
  (< 400) the verdict string reads `underpowered`, not `go`: read the kill list, not the verdict word.
* e10 (last epoch, the shipped checkpoint under `--select-last`): same lines as e8 including the pass rule, so the shipped
  weights are held to the same bar.
* R5 from e8: kill iff val_ser(e) > min(val_ser over earlier epochs) + 1e-3 (was 3e-4). 1e-3 is a hand-set prior chosen after
  seeing s2's epoch-to-epoch swing (about 3e-3); it is not derived from a swing distribution.
* s22.2 human gate (8 extras) and the C2g report: unchanged and still due after the run; neither is a kill line here.
* Canary and CPM numbers are reported at every evaluated epoch (fc_new_lr_mult 10 raises forgetting risk on the base vocabulary).
* The e8 pass rule is a continue-training gate on RS-T tuning data that the recipe was tuned on (optimistic). It is NOT an
  accuracy claim. The final claim is made only on the RS-T test half (or fresh real photos), scored once on the final
  checkpoint, and that set is named here before the run. RS-S is NOT sealed (s22 scored it at e3 for below-staff lines) and
  no triad/middle scorer exists on it, so no checkpoint choice by RS-S is implemented: the checkpoint is the last epoch.
* Final claim scorer (named now): one-off scorer reusing `score_rs_t` / `rs_t_metrics` on the RS-T test half (14 val pieces,
  complement of the tuning half in halves.json f8783240...), triad_2plus and middle, same bwv399 handling as the e8 pass rule,
  run once on the e10 checkpoint, reported with and without bwv406 (the accepted shared-tune pair, s10/s12a), both seeds as a
  range. It supports a held-out Bach-chorale-render claim, not a real-photo claim. The scorer is not written yet.
* Attribution: lr, warmup, share (.20 to .30), fc multiplier, epochs and reseed change together. A pass says the recipe works,
  not which change mattered. The undertraining reading rests on tuning-half rescoring and a 30-row train-side check, so it
  cannot exclude a distribution gap. The confident-wrong / uncertainty problem (s22.3, s21 rule 5) stays open.
* Frozen unchanged: RS-T halves (sha f8783240...), Gootville holdout, canary caps, all s22 sets and pins.

**23.4 Resume after interruption (supersedes "no resume, no reseed" ONLY for crash/timeout).** `--resume-from <epoch ckpt>`
restores model, AdamW, scheduler state, the real-strip view budget and the metrics history, and continues at epoch+1. It
requires `--reseed-per-epoch`, matching seed / manifest sha / init sha, matching hyper-parameters in the earlier
`run_info.json`, and no KILL verdict (`pilot_killed.json` or a `judge_e*.json` with status kill) and no canary hard-cap breach.
Every owed `judge_e{N}.json` must exist for evaluated epochs before the checkpoint; if the checkpoint epoch itself is an
evaluated epoch and its judge file is missing (session died during the eval), that eval runs first. The kernel resumes only
from an attached dataset `piyanota-a9-c2-resume-s{N}` (found at any mount depth up to 5, aborts if attached but empty or
holding several run folders) and takes the newest checkpoint with all owed judge files. A KILL verdict still ends the run for
good: no resume, no reseed, no relaunch without diagnosis. A resumed run is NOT bit-identical (GPU nondeterminism; only the
draws match) and is reported as resumed, with the resume epoch.

**23.5 Launch state.** Draw counts PINNED from the C2 smoke (kernel piyanota-divisi-a9-c2-smoke, commit 3b3237e, start checks
passed): 10284 divisi draws/epoch, 1543 generated; the real C2 push refuses without them. Reviews of 2026-11-05 (senior-reviewer,
ml-cv-lead x2) are addressed. Still not done: a GPU check of the warmup and fc multiplier (the first real epoch is that check;
read epoch-1 loss and canary before trusting the run), and that DataLoader workers honour the per-epoch reseed (num_workers=0
assumed). Runtime estimate about 9.5 h of the 11 h cap per seed (fallback `--max-epochs 9`); e8 survives a timeout because every
epoch saves a checkpoint. Report both seeds as a range, never the better one.

### 23.6 Operational amendment (2026-11-06): chunked sessions

Kaggle publishes /kaggle/working only when a session ends normally, so a quota kill or a time kill loses every epoch checkpoint even though train_phase2.py saves one per epoch. To make the run recoverable on any account, the kernel now takes a staged constant STOP_AFTER (stager option --stop-after N, N in 4, 6, 8, 10, default 10). The kernel passes it as --stop-after-epoch, so a session ends cleanly after epoch N and its output, including the epoch checkpoint and judge files, is published. The next session resumes with --c2 --resume under s23.4. A budget timeout (SESSION_BUDGET_MIN) now also ends the session normally instead of aborting. The cosine T_max stays 10, no training hyper-parameter changes, and stop_after_epoch is not in the resume drift check. Chunk ends are restricted to eval epochs so no unplanned eval or judge runs. Not bit-identical to an uninterrupted run, as in s23.4. Untested on a real kernel.

## 24. Amendment 2026-11-06 (final-claim set redirected to the sealed fresh test renders; written before any scoring)

Section 23.3 names the RS-T test half (pinned v1 build) as the final-claim set. On 2026-11-06 the user directed that the final claim use the sealed fresh test renders instead (`piamacc/piyanota-divisi-a9-testrenders` v3, manifest sha 820571196f29660c..., halves sha f8783240..., 17 seeds, 14,858 strips, `no_model_scored: true` in `test_renders_sealed.json`; the cap history and first-pass numbers are in s19 and s20). Reasons: the strips of the pinned build's test half are not on disk, and its pieces were opened in the A6 test read, whereas the sealed renders were built before the pilot and no model has scored them.

Rules, all fixed before the run. The scorer is `training/phase2/a9_c2_final_scorer.py`. Each seed's e10 checkpoint is scored once, with no reruns. Subsets are: main (non-Gootville, bach_bwv406 excluded), with bwv406, and Gootville restricted to (piece, seed) cells present in all four other fonts. The headline is the piece-level min, median and max of triad_2plus and middle; the pooled ratio is context only and is not deduplicated (`dedup_columns` does not touch the A7 counters, and the 17 seeds re-render the same pieces). Heads, unique heads and sites come from the sealed build record, and a Gootville subset under 300 heads is reported underpowered. bach_bwv399 is a tuning-half piece and cannot appear. Both seeds are reported side by side as a range, never averaged. No pass or fail threshold applies. The claim is held-out Bach-chorale renders from the same generator and fonts as training, not real photos, and the confident-wrong problem stays open. A7 must later be scored on the same renders with the same scorer (s15 item 4). After this run the renders are spent for any A10 tuning or checkpoint choice. The "14 pieces" in s23.3 is corrected: the pinned build has rows for only 11 of the 14 test-half pieces.

### 24.1 Post-run record 2026-11-06 (after both seeds were scored; ml-cv-lead review)

Scorer `training/phase2/a9_c2_final_scorer.py` sha256 eeffe4be5f671bd457d8d335f8404fffc97bbdbfc6d5f2052fefb7804ae0aaee, unchanged between the first launch and the scoring runs. Results: `sealed_testrenders_s1_e10.json` (checkpoint sha256 9859b9d3...) and `sealed_testrenders_s2_e10.json` (1a6cd478...).

Run history: the first launch ran both seeds in parallel and was killed by the system for low memory before writing any output; no number from it was seen and no output file existed. Each checkpoint was then scored in one completed run, with the same scorer and pins. The claim is "one completed scoring per checkpoint", not "scored exactly once, ever".

Corrections to how the result files read: the `report_only` string in the JSON calls the tuning-half comparison "a generalisation gap only". Read it as context only: the tuning half and the sealed renders are different builds and pieces, so their difference is neither a gap nor evidence of no gap. The JSON files are not edited.

Limits to state with the numbers: the 14 pieces are 12 distinct tunes (bwv18.5-lz and -w are one tune); pieces are unweighted in the min, median and max (columns per piece range from 634 to 1621) and the median is the upper median; the pooled ratios are not deduplicated and carry no interval; the two seeds have near-identical per-piece errors (bwv426 gives 1515/1621 triad and 1524/1621 middle in both), so they are not independent confirmations; the head and site floors count the below-staff chord set in 9 pieces (10 with bwv406), not the 13 pieces behind the headline metrics, and the sites floor of 40 is met with zero margin; Gootville is underpowered (227 heads against 300) and its piece minimum is bwv406 on 28 columns, which is not evidence of a font problem; the shared-tune check for pieces other than bwv406 is not restated here and must be cited from s10 and s12a; the renders are spent for tuning and checkpoint choice; and A7 has not been scored on them, so no improvement over A7 may be claimed.

## 25. DRAFT 2026-11-06 (not frozen, not approved): real-photo reading of C2 on the 10-piece set

Status: draft for user approval and ml-cv-lead review. Nothing is scored on the real set until this is frozen, hashed and committed. The set is `D:/PiyaNota/data/piyanota_dataset/10piece_test_set` (Ale, Ama_Namin, Bahay_Kubo, Gaano_Ko_Ikaw_Kamahal, Kay_Ganda_Ng_Ating_Musika, May_Hihigit_Pa_Ba, Pangarap_Ko_Ang_Ibigin_Ka, Pangarap_Lang, Paru-parong_Bukid, Tikong_Tiko), with ground truth in `_a7_gt`. It carries over A7 14.7: a one-time confirmation reading (s15 item 2), test-only, never used for tuning or checkpoint choice.

Carried over from A7 14.7, unless the user rules otherwise: freeze and hash all test GT files, their PDF chord and split-form calls and the `accid_check` noise rate in a PREREG file first; a piece without GT at that point is out; per-bucket floors (layer bars 600; 2+ ledger and template heads 300), with a bucket under its floor reported as "underpowered, report only"; a bucket passes only when its Wilson 95% lower bound clears its threshold at its own n, also per piece; pieces with 5/4 or 7/4 meters listed before the freeze with a bar rule written then; each seed's e10 checkpoint scored once; both seeds as a range; real PDFs test layout shift, not font shift.

Decisions needed from the user before the freeze: (a) whether the A7 ground truth, partly built by an agent, is accepted as scoring GT or the result is diagnostic only (CLAUDE.md treats agent-made GT as diagnostic); (b) which camera photos per piece count (all of `camera/`, or one per piece), and whether digital PDF strips are scored as a pair; (c) which scorer produces the strips and tokens (the A7 real scorer, not located in this branch's `training/*.py` by name search; it must be found or written and reviewed); (d) the metrics and thresholds (A7 7.x thresholds were set for the A7 model; whether they carry over to C2 is open); (e) that Ama_Namin and Gaano were used in the A7 chord-reader test, so earlier A7 results exist on them; (f) the claim wording, which must say real photos of 10 pieces, descriptive, not generalisation.

### 25.1 Pre-freeze input change 2026-11-08: Kay_Ganda_Ng_Ating_Musika swapped to the "Updated Score" set

Recorded before any checkpoint has read any real-set strip (nothing is scored; the freeze has not happened). The user supplied a new Kay_Ganda set whose PDF and camera photos were both made from the MuseScore file `Kay_Ganda_merged4.mscz`, and ruled (2026-11-08) that the ground truth for Kay_Ganda is generated from that file, with no note verification, and that the piece is no longer "unsure".

What changed:
- **Inputs.** PDF: the 16-page MuseScore export replaces the 8-page raster scan. Camera: 16 photos (`p01..p16.JPG`) replace the 8 old ones. The old PDF and photos are kept out of the test set in `Kay_Ganda_Ng_Ating_Musika/_old_8page_layout/`.
- **GT.** MusicXML exported from `Kay_Ganda_merged4.mscz` with MuseScore 4 (4 parts, 69 bars), MEI by Verovio `getMEI({scoreBased: True})` as for the other pieces, labels by `merge_divisi_parts.py` with a new 16-page map (34 systems, 136 strips; the first bar of each system is read from the export's `new-system` / `new-page` markers). Chords are native in this file, so the hand-made chord/split form calls made for the old 8-staff export are not used and `forms/Kay_Ganda_Ng_Ating_Musika.json` is deleted. Plain labels keep 132 of 136 strips (4 dropped for tuplets); the tuplet-aware labels used by Arms 1 and 3 keep all 136.
- **Check run before the swap, GT files only (no model output).** Pitch and duration sets per bar, new 4-part export against the old 8-part GT export (parts 1+2, 3+4, 5+6, 7+8): equal in 67 of 69 bars. The Tenor and Bass of bar 21 differ (the old export has 13 more pitched notes there). The new file is the GT; the difference was not examined further and is not corrected.
- **Scope.** Kay_Ganda is removed from `UNSURE_PIECES` (`real_set_scorer.py`) and from `unverified_by_head_count` (`scoring_exclusions.json`); it now counts in the item 9 sub-set.
- **Provenance attestation (decision 16 item 1, user attestation).** No GT call for Kay_Ganda used model output. The GT is the MuseScore file converted by the same code as the other nine pieces.

Hashes (sha256):
- `Kay_Ganda_Ng_Ating_Musika/Updated Score/Kay_Ganda_merged4.mscz`: `ce0172a36e00cf0457a1231537d88e36826232c721f5b4948f488f1d6d22af4e`
- new PDF `Kay_Ganda_Ng_Ating_Musika/Kay_Ganda_Ng_Ating_Musika.pdf`: `ecb4e73d14f40f2f8d8c86d1d34d411b5bfab4ee2742a2905fc7d7fe4c0c7cd2`
- `_a7_gt/xml/Kay_Ganda_Ng_Ating_Musika.mei`: `e1097c75eba714ba7fb1a9a9a8d2bc9b3ad91f650302fd02f4419c1305042fc9`
- `_a7_gt/labels_tuplet/Kay_Ganda_Ng_Ating_Musika/labels.jsonl`: `01b62a3cd31ddc5167ea1370742702aba805a931c1cd8ee165a50c42281a5a1d`
- `_a7_gt/labels/Kay_Ganda_Ng_Ating_Musika/labels.jsonl`: `07c16ad6600c19971c10a921879572affab0d9b413547a0ca44c4328663ea09b`
- `real_set_gt/maps/Kay_Ganda_Ng_Ating_Musika.json`: `84bcba7b3300ae6881378e49f84078f77e687a5a7a5d086e98f2335e6bb4d6f0`
- Superseded, kept for the record: old PDF `addd0d77bfc1112cf766e48300b3e7188039bb3b5c3b15484c4c4de5ea1e531d`; old MEI `6dec457e1e081808c631ea4232cda4ffbe14abd63abf28ee116139a36a4e1393`. Old labels, map and forms are in `_a7_gt/_pre_updated_score_20261108/`.
- Full per-file list (including the 16 photos) is in `real_set_gt/SHA256SUMS.external`. The other nine pieces' labels rebuild byte-identical (all hashes verified after the rebuild).

### 25.2 DRAFT 2026-11-08 (not frozen, not approved): strip cut record and the 12 flow-review items

Cut run 1 (the result; one-shot rule applies): `cut_real_set.py` on Stage 1 + Stage 2 (`best.pt`), PDF rendered at 300 dpi gray with PyMuPDF, one image per GT page, every GT strip keeps its key (piece, page, sys, staff). Per source, GT strips cut: PDF 916/916, camera 912/916. The 4 missing are the empty Pangarap_Lang p11 (no photo; excluded from every arm by `scoring_exclusions.json`). No page failed on box count or error, so no strip is scored as an empty read for a cutter miss in this run. Per piece (GT = pdf = camera) Ale 108, Ama_Namin 48, Bahay_Kubo 48, Gaano 72, Kay_Ganda 136, May_Hihigit 128, Pangarap_Ko 104, Pangarap_Lang 120 (camera 116), Paru 60, Tikong 92.
Blind check (`check_real_cut.py`, tolerances fixed before it ran, no model output): 179/180 page-source cuts ok; no camera-vs-PDF box-centre disagreement above 0.03 on any page. 12 flags, all kept in the denominator and nothing re-cut: 8 "system grouping" flags (Gaano p5, Paru p1/p4/p5, both sources) come from the largest-gap grouping heuristic on pages where staff gaps are uneven, and PDF and camera agree on centres there; 4 "fallback" flags are the empty Pangarap_Lang p11 PDF strips. Eyeball tiles (random 14 camera strips, 10 Kay_Ganda strips): strip voice, clef, key and bar range match their labels.

Hashes: cutter `cut_real_set.py` `62ccb5415fb81f8ae20e958793938d80c53c60d9834b35013598b1de6df30fbf`; `stage1_preprocessing.py` `ada33dd209335ac6fa3550e0187add489f511206951a4ed587e083bff8567ddf`; `stage2_detection.py` `26c1c585...5b2`; `cut_divisi_real.py` `c49dbd3e...3935`; YOLO `best.pt` `f55bb851...8213`; `manifest.jsonl` `596295d5c0b128680ba3bcf3e7ae1fe4821b8709626d1c97c15ff4d65bc06ed8`; strip files `e4c12e27d42fc4875bc17bc2c70ae16e0fd08f3dc2c1ae093388d0f6dcfc1585`; `inputs.json` `15e06616b021477a416d8ae115b61f121e02a20006441504af47d42dc70595b2`; scorer `real_set_scorer.py` `5689f3329e92ac6b6aa37a6da1bc15ea9a9d5ac1ce1562466be6d48531265899` (UNSURE list edited 2026-11-08). Environment: python 3.12.10, cv2 4.13.0, torch 2.3.0+cu121, ultralytics 8.4.51, CUDA on. Full hashes are in `cut_code_sha256.txt` of the cut folder (copy it into the repo at freeze).

Status of the 12 flow-review items (plan decision 16):
1. GT closed: user accepted GT, form calls, exclusions (2026-11-07); Kay_Ganda GT regenerated 2026-11-08 (25.1). No call used model output: user attestation (record in the freeze commit message).
2. Set not pristine (Ama_Namin, Bahay_Kubo, Pangarap_Ko, Gaano seen by earlier A7 work). CLOSED in 25.3 (item 2 answer).
3. GT-denominated scoring and staves-found fraction: done for the cut (see above); key is (piece, page, sys, staff).
4. Cut QA: tiles and hashes done; photo list frozen in `inputs.json` (used and skipped files, sha256 each). Determinism rerun DONE 2026-11-08: the first rerun was stopped by the system for low memory; a second full rerun (PDF pages re-rendered, byte-identical to the first renders) gave the same `manifest_sha256`, `strip_files_sha256`, `maps_sha256`, `labels_tuplet_sha256` and the same code hashes, so the cut is deterministic.
5. CLOSED in 25.3 (constants quoted there): Paru X-head strip handling (Arm 3 mask or Arm 1 drop), ties beside excluded notes, Arm 3 DP edit costs, Arm 2 note-matching rule. Constants are in `real_set_scorer.py`; they must be quoted here before the freeze.
6. Label-only controls and unit tests exist (commit 496f208; tests pass 2026-11-08). CLOSED in 25.3 (control results printed beside each pitch number). The s1/s2 e10 checkpoints and the inference config are pinned in the "Pinned inputs" paragraph below.
7. Power rule: as plan item 7 (floors 600 layer bars, 300 heads; no seed or PDF-vs-camera claim unless the paired cluster-bootstrap CI excludes zero). Sizing recomputed 2026-11-08 for the new Kay_Ganda (`real_set_sizing.py`, output kept outside git): Arm 1 (`labels/`) keeps 825 of 916 strips (91 dropped, 9.9%) [SUPERSEDED by the 816 of 912 (10.5%) correction in 25.3], [the 11807-note and 3014-bar figures are also SUPERSEDED: the scorer's counts in 25.3 (816 of 912 strips, 13066 heads) are the ones that count, and they stay above both floors (600 bars, 300 heads)]. Arms 2 and 3 (`labels_tuplet/`) keep all 916 strips; Arm 3 masks 99 tuplet bars and scores 3293 of 3392 bars (12618 of 13133 notes). Dropped Arm 1 strips by piece: Ama_Namin 11, Gaano 19, Kay_Ganda 4, May_Hihigit 55 (43%), Pangarap_Ko 2. The 916 strips include the 4 empty Pangarap_Lang p11 strips, which leave every arm by exclusion. May_Hihigit is the piece most affected by the Arm 1 drop; per-piece numbers are reported next to the pooled one.
8. CLOSED by the user decision of 2026-11-08 (both modes, reported apart; see 25.3): scored pipeline (raw CRNN versus ClefKeyNet fixed_header, Tenor 8vb). ClefKeyNet is not gate-passed (BUG-021); header scored separately.
9. Item 9 line is now Pangarap_Ko and Tikong only (Kay_Ganda removed, 25.1); report with and without them.
10. Arm 1 side by side with Arm 3 and the dropped fraction; no pass/fail headline.
11. Confidence AUC and confident-wrong are report-only; no threshold set on this set.
12. One-shot rule for the scorer's whole life; a later fix is a recorded amendment with both numbers.
Meters (checked 2026-11-08 on the 10 `labels_tuplet` files): the only meter digit tokens are 2, 3 and 4, so no piece has a 5/4 or 7/4 bar; rule: none apply, and a 5/4 or 7/4 bar found later is reported, not rescored. User rulings 2026-11-08: both pipelines (raw CRNN and ClefKeyNet fixed_header) are scored and reported apart with no blended number (item 8); the set is pristine, with C2 design and e10 choice made on sealed renders only (item 2, user statement); the scorer's X-head, tie and Arm 3 cost rules are accepted as coded in `real_set_scorer.py` (item 5: Arm 1 drops strips holding an X-head bar; Arm 3 masks X-head and tuplet bars; Arm 2 ignores X-head notes but scores tuplet bars; slur/tie tokens beside a masked bar stay in SER and are counted; barline substitution cost 2).
`accid_check` (A7 14.7): not run on the real set. It counts font glyphs in vector PDFs for specific fonts (Leland, Maestro, TTkStava), and the real set has scans and app-made PDFs with other fonts; the real-set GT comes from the `.mscz` export plus the user-accepted by-eye checks. The A7 noise rate (4 of 439 strips, 0.9%) is quoted as a reference only, not as a measured rate for this set.
Freeze gate: ml-cv-lead sign-off (given 2026-11-08, after the wording fixes in this section), then the user's explicit approval, then a commit. Nothing is scored until then.

### 25.3 DRAFT 2026-11-08 (not frozen, not approved): scoring contract, answers to the ml-cv-lead review of 25.2

This section answers the ml-cv-lead review of 25.2 (blockers B1 to B7, missing rules M1 to M8). Every line marked OPEN had to be closed before the freeze; the only placeholder left is the freeze-commit hash. Nothing is scored until the freeze is approved.

**Corrections to 25.2.** (a) The scorer's Arm 1 keeps 816 of 912 strips (96 dropped, 10.5%), not 825 of 916. The sizing script counts 825 because it does not apply the exclusions that the scorer applies before arm assignment: the 4 empty Pangarap_Lang p11 strips and the 5 Paru strips that hold an X-head bar. The scorer's numbers are the ones that count. On the label-only control run (PDF set, header from GT) Arm 1 holds 13066 pitched heads and 24531 SER tokens, and Arms 2 and 3 hold 912 strips each. (b) The one page-source cut that did not pass in the blind check is Pangarap_Lang p11 camera (no photo exists). The 4 "fallback" flags are the PDF strips of the same page.

**Leakage and GT (M1, item 1).** No ground-truth call, form call, exclusion, arm membership, bar mask or drop decision used any model output. The GT was accepted by the user on 2026-11-07 and the Kay_Ganda GT was regenerated on 2026-11-08 from the same `.mscz` as its PDF and photos; the user attests that no call used model output. Arm membership and masks are computed from the labels and `scoring_exclusions.json` only. Known GT limit: when Kay_Ganda was swapped, bar 21 (Tenor and Bass) differed between the old and new exports by 13 pitched notes; the new GT for those two parts in bar 21 was not examined by eye. Bar 21 of Kay_Ganda is therefore listed as a diagnostic bar: if it moves a headline number by more than 0.5 pp, both numbers are reported. The scorer is frozen and has no bar-exclusion switch, so the second number is a recorded post-hoc recount that drops that bar's tokens from the same prediction files, labelled as an amendment-style report; the headline stays the frozen scorer's number.

**Cut (items 3 and 4, B7, M3, M4).** The cut is frozen as in 25.2. All photos in each piece's `camera/` folder count, as listed with sha256 in `inputs.json`; no photo is dropped, replaced or chosen after any score. PDF and camera are two media of the same notes and are never blended; the camera set is the deployment-relevant one. Pangarap_Lang p11 (4 strips, no notes) is excluded from both media, so both scored sets hold 912 strips. A staff that Stage 1/2 misses on any page counts as an empty read (wrong for every GT note and token on it, GT-denominated); `pred_present` reports the share found per piece. A predicted strip that matches no GT key is a phantom: it is ignored by the score and counted by `phantom_strips()` in the report. The four flagged pages of the blind check (Gaano p5, Paru p1, p4, p5) were looked at by eye on the camera strips on 2026-11-08: every strip carries the voice letter, clef, bar range and (Paru p5 bar 60) X-heads its label states, so the grouping flags are a heuristic fault, not a mapping fault.

**Metrics (B1).** Fermata tokens are removed from GT and prediction first. Header (clef, key, meter) is scored apart in every arm. Pitch of a head is its (diatonic step, alteration), with the alteration taken from the inline accidental, else the same-step carry in the bar, else the key signature; octave offsets (Tenor 8vb) cancel because only differences against the GT staff matter. Pitch accuracy is recall: matched GT heads over GT heads; `pred_to_gt_slots` is reported beside it. Token SER is the token edit distance (insert, delete and substitute cost 1, a barline against a non-barline costs 2) over GT tokens; Arm 1 includes header tokens, Arm 3 excludes them; plain cost-1 SER is reported beside it. Arm 1 (printed first, not a chosen headline) is the strips in `labels/` that have tokens and no masked bar. Arm 3 (bar-masked) uses `labels_tuplet/`: tuplet bars and Paru X-head bars are masked, everything else is scored. Arm 2 (pitch-only floor) uses `labels_tuplet/` with no strip dropped, matches GT and predicted heads by a longest common subsequence on the pitch set only, and ignores X-head notes. Slur and tie tokens beside a masked bar stay in SER and are counted. Constants, quoted from `real_set_scorer.py`: `BARLINE_SUB_COST` 2, `WILSON_Z` 1.96, `BOOT_N` 2000, `BOOT_SEED` 0, `IGNORED_PREFIXES` ("fermata.",), `UNDERPOWERED_LAYER_BARS` 600, `UNDERPOWERED_HEAD_N` 300, `UNSURE_PIECES` Pangarap_Ko_Ang_Ibigin_Ka and Tikong_Tiko.

**Item 5 CLOSED (B2).** User ruling 2026-11-08: Paru X-head bars (S 24, 30, 60; A 22, 30, 60; T 24, 60; B 22, 60) are not scored; the Arm 1, Arm 2 and Arm 3 treatment and the tie rule are those in the Metrics paragraph above.

**Item 6, controls (B2).** The label-only controls were run on 2026-11-08 on the real kept strips (PDF set, scorer sha256 `5689f3329e92ac6b6aa37a6da1bc15ea9a9d5ac1ce1562466be6d48531265899`; the output file is kept outside git and holds the sha256 of its inputs). Pooled pitch accuracy and token SER (Arm 1 / Arm 3; Arm 2 pitch only): GT copied as prediction 100% and 0% in every arm; constant prediction pitch 8.7% / 4.7% and 8.8% (SER 93% / 95%); shuffled prediction 18.7% / 12.0% and 18.7% (SER 93% / 97%); one barline inserted per strip pitch 98.9% / 100% (SER 3.3% / 3.6%, 803 / 899 spurious barlines counted); one barline deleted pitch 99.7% / 100% (SER 3.3% / 3.7%, 812 / 908 missed barlines counted); one note dropped per strip pitch 93.2% / 93.3% and 93.2%; every step shifted pitch 21.4% / 13.2% and 21.8%; overgenerate pitch 18.8% / 18.0% (SER 785% / 884%); missing prediction 0% and SER 100%. The controls move the metrics the way their definitions say, and no control passes as a model. The first run is the result; the controls are re-run (and the scorer re-hashed) only if the scorer changes before the freeze.

**Item 8, pipelines (B5).** Each checkpoint is scored in two modes, reported apart, with no blended number: raw CRNN (own clef, key and octave) and ClefKeyNet `fixed_header` (checkpoint `training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt`, clef by voice rule, key by per-system vote, Tenor 8vb from the classifier octave; `CLEF_KEY_GATE_PASSED` is False, so every event is flagged unvalidated). ClefKeyNet was tuned on the BUG-021 real-photo set and evaluated on fresh photos on 2026-09-28; of the pieces named there, Gaano Ko Ikaw Kamahal is one of the 10 test pieces (diagnostic only, agent-made GT, not a tuning piece). User ruling 2026-11-08: Gaano stays scored in both modes, the ClefKeyNet mode is also reported without Gaano, and the prior ClefKeyNet look at Gaano is disclosed here. The raw CRNN mode has no such prior look. The overlap check and the ClefKeyNet checkpoint sha256 are closed in the pinned-inputs paragraph below.

**Pristine set (item 2, B4).** User statement 2026-11-08: the C2 design and the choice of the e10 checkpoint used sealed renders only. Disclosed prior real-set looks: earlier A7 results and chord-reader tests on Ama_Namin, Bahay_Kubo, Pangarap_Ko and Gaano, the ClefKeyNet look at Gaano above, and the Stage 1 mask work on Ale (tuning piece), Ama_Namin and Gaano (frozen mask pieces that were looked at). The `accid_check` and form calls never saw any C2 output.

**Pairing, statistics and claims (B6, M2, M6, M8, items 7 and 10 to 12).** The cluster is the piece (10 clusters). Photos of one piece are repeats of the same notes. PDF and camera sets are paired by the key (piece, page, sys, staff); the two seeds and the two modes are paired on the same notes. The bootstrap statistic is the pooled ratio, resampling pieces with `BOOT_N` 2000 and `BOOT_SEED` 0; with 10 clusters the percentile interval is indicative only and is named `cluster_indicative` in the scorer. A claim of a difference between seeds, media or modes needs the paired piece-cluster interval to exclude zero; without that it is not claimed. The 600 bar and 300 head floors apply to the pooled count of one arm in one set; every per-piece line holds fewer than 600 bars and is report-only by that rule. The headline is never chosen after scoring: both seeds, both media, both modes and all three arms are reported in a fixed order (seed 1 then seed 2; PDF then camera; raw CRNN then ClefKeyNet; Arm 1, Arm 3, Arm 2), and Arm 1 is always printed next to Arm 3 and the dropped fraction (10.5% overall; May_Hihigit 43%), because Arm 1 keeps the easier material. Claim wording: descriptive, real photos of 10 pieces, not generalisation, no pass or fail gate. The goal (SER 15%, pitch 85%) is printed as context only. C2 is the only model scored on this set: no improvement claim over A7 or any earlier model. The scorer's CI and seed code is part of the one-shot scorer; a later fix is a recorded amendment with both numbers. Any checkpoint other than s1 e10 and s2 e10 needs a new amendment.

**Item 9 (this is the answer to ml-cv-lead's first-review point M7).** M7 asked to confirm the item 9 sub-set after the Kay_Ganda swap. Confirmed: the with-and-without line covers Pangarap_Ko_Ang_Ibigin_Ka and Tikong_Tiko only, which is exactly `UNSURE_PIECES` in `real_set_scorer.py` and `unverified_by_head_count` in `scoring_exclusions.json` (the head-count check still cannot run on those two). Kay_Ganda's PDF and photos are made from the same MuseScore file as its ground truth, so it is a normal piece and is in the sub-set that is scored, with no with-and-without split. The first-review wording said the head check "still cannot run" on Kay_Ganda; this text reads that as "needs no head check any more", because the ground truth and the images share one source file.

**Confidence (M5, N2, item 11).** Report-only; no threshold is set on this set and neither number gates anything. The code is `training/phase2/real_set_confidence.py` (pure functions, unit tested, hashed with the scorer at the freeze; the scorer itself is not changed). Note-to-slot mapping, written down before the code: (1) The unit is a predicted note slot, as the scorer builds it with `bar_slots` on the prediction's own header (clef from the prediction, key from the prediction). The module finds the token that created each slot by growing the bar one token at a time and watching `bar_slots` add a slot; it then does not re-implement the pitch logic. (2) A slot's confidence is the minimum over the token confidences of its note token and the accidental and dot tokens attached to it since the previous slot (the same min rule as `stage3_transcription`); a chord slot takes the minimum over its heads. Injected ClefKeyNet header tokens carry confidence 1.0 and are not notes. (3) The slots are matched to the GT slots with the scorer's own `lcs_len_pairs`, on the same strips, bars and masks as the scorer's Arm 3 (masked bars are not counted). A matched predicted slot is correct. Every unmatched predicted slot is wrong: a hallucinated note and a misread pitch both end up unmatched under the slot-exact match, and both count as wrong. GT slots with no predicted slot are missed notes; they have no confidence and are reported only by the scorer's recall. (4) Confident-wrong = unmatched predicted slots with confidence at least 0.9, divided by all predicted slots with confidence at least 0.9. (5) AUC = area under the ROC curve of confidence against slot-correct, over all predicted slots (matched and unmatched), per set; rank ties get half credit. The report prints the number of slots behind each figure and the share of predicted slots at or above 0.9. Hand-made unit cases: a perfect read, a hallucinated note, a confident-wrong note, a chord, and an empty prediction. Known limit: an LCS match can place a wrong note as unmatched because a neighbour was dropped, so confident-wrong is a count of unmatched notes, not proof of a misread pitch.

**ClefKeyNet mode: header injection (B5, N1), written before the code, decisions of the user on 2026-11-08.** The classifier reads Stage 1's unmasked native binary page, and the C2 cut kept only grey masked strips with no box. So the runner re-runs the cutter's page loop for the ClefKeyNet mode: `stage1_preprocessing.preprocess_score_page(photo, keep_unmasked=True)`, then `cut_divisi_real.stage2_boxes`, then the cutter's slot assignment `page_slots(maps[piece], page, rows)` (this reads the GT row keys only to name each box `(sys, staff)`, exactly as the cutter did), then `stage3_clefkey.classify_page`. For every box the runner rebuilds the strip with the cutter's own `_crop_and_resize` call and compares it byte for byte with the frozen strip file; any mismatch, or any page whose box count differs from the cut record, stops the run (the cut and the classifier input must come from the same boxes). Voice for the clef rule is the staff position in the system (0 Soprano, 1 Alto, 2 Tenor, 3 Bass); user statement 2026-11-08: all ten pieces are laid out S-A-T-B top to bottom. The `parts` field of a GT row is a source-part number, not a voice, and is not used. Decisions come from `stage3_clefkey.decide`, run per piece and per medium over the pages in page order (so keys are carried inside one piece only). The pipeline's whole-system steps are applied in the pipeline's order: the header filter `filter_header_hallucinations` (default on in `transcribe_voice_sequences`), then R1 `apply_key_continuity` (ON, as in the pipeline default), using the raw CRNN symbols of each system. R2, R3 and R4 (mid-strip key and meter changes) act on `infer_pitch` events, not on the token list that the scorer reads, so they are not part of this mode. The header is written into the token list with `stage3_clefkey.substitute_header`: every CRNN clef token and the CRNN's opening accidentals are dropped and the decided clef token and key-signature tokens are put first; the CRNN's meter tokens stay (the scorer scores the meter apart and `header_mode="own"` reads clef, key and meter from the list). Tenor 8vb has no effect on the token view because the scorer cancels octave offsets. `CLEF_KEY_GATE_PASSED` is False, so this mode is unvalidated by the project's own rule, as in the pipeline. The voice rule has not been tested on staves that carry merged parts (Ama_Namin, Paru-parong_Bukid, Pangarap_Ko, Tikong_Tiko); the report gives the clef and key header accuracy per piece, which is where a misfire would show. The clef rule is the one in `clef_voice_rules.resolve_clef`: the classifier is restricted to the clefs the voice may carry (Soprano and Alto G; Tenor G, G8vb or F; Bass F or G8vb) and the voice default applies only when the best allowed clef is below threshold; "clef by voice rule" elsewhere in this section means that. A bass-clef staff at a Soprano or Alto position (merged parts) is therefore forced to G. The ClefKeyNet mode bundles three steps (header filter, clef and key substitution, key continuity R1), so a raw-versus-ClefKeyNet difference is NOT attributable to ClefKeyNet alone; the header filter alone was about 8 to 9 pp token SER on dev data (`stage3_transcription.py` filter docstring). To separate them, the report adds a third line, "raw plus header filter only" (the filter is a pure function of the tokens and needs no images). `substitute_header` removes every clef and accidental token before the first non-header token and any later clef token; a real inline accidental before a system's first note is lost in that process and counted against this mode, and the runner records the dropped accidentals per strip in `meta` so the size of that effect is reported. "First system keeps its header" means the first retained system of a piece; the runner stops if a piece's first retained row is not page 1, system 1 (checked 2026-11-08 on the frozen manifest: every piece passes, both media). The header pass sees only manifest rows, so a page the cut lost or an unlabelled staff reduces the voice quorum and the system adjacency R1 uses; the pipeline behaves the same way on missing systems. The runner has three modes: `raw`, `filter` (raw plus the header filter, the "third report line") and `clefkey`. It also stops unless `manifest.jsonl` has sha256 `fe120cbcee3935766ad720d0c54296a44fabe5b1fbc97f20b684d44f1fc6eb3e` and the checkpoint is one of the two pinned C2 checkpoints. In `clefkey` mode `meta.decisions` holds, per strip, the decided clef, key, key source, decision flags (for example `no_classifier_geometry`, `key_no_majority`, held key) and the dropped header accidentals, so a fallback or a misfire can be traced. Confidences are written unrounded. The confidence report uses the prediction's own clef and key (`--header-mode own`, now the default) and writes `header_mode` into its JSON. The raw CRNN mode applies none of these steps: tokens are the CRNN's own, with no header filter. A smoke test checks that the injected clef and key equal the `header_override` that `infer_pitch` would use for the same decision. Each prediction file holds one checkpoint, one medium (PDF or camera) and one mode, because the scorer keys a strip by `(piece, page, sys, staff)` only and would mix media otherwise.

**Report layout: chance floors and pairs (N5).** The floors depend only on the labels and the kept strips, so they apply to the camera set unchanged. For the confidence report, AUC chance is 0.5, and the no-skill confident-wrong rate is the share of predicted slots that are unmatched. Beside every pitch number (Arm 1 / Arm 3 / Arm 2) the report prints the label-only control floors from item 6: constant prediction 8.7% / 4.7% / 8.8%; shuffled prediction 18.7% / 12.0% / 18.7%; every step shifted 21.4% / 13.2% / 21.8%; overgenerate 18.8% / 18.0% (Arm 2 not recorded in item 6, taken from `controls.json` at report time). Every paired delta names its pair in the report line (for example "seed 1 vs seed 2, camera, ClefKeyNet"); the scorer labels its two-run delta "seed-vs-seed" whatever the two runs are, so the report line, not that label, states what was paired.

**Pinned inputs (items 4 and 6, B3). All five filled 2026-11-08; the freeze commit hash and the hash of `predict_real_set.py` are added at the freeze.** (1) CLOSED, checkpoints: `D:/PiyaNota/data/a9_c2_out/s1/a9_c2_c_s1/phase2_seed1_epoch10.pt` sha256 `9859b9d37696b94a84505684374beb0db202c25fd2ea50d930df506f0802ce2a`; `D:/PiyaNota/data/a9_c2_out/s2/a9_c2_c_s2/phase2_seed2_epoch10.pt` sha256 `1a6cd47885b320a15bf81504c433f6c5505b1851c31f3d66a51525df8ceef14d`; ClefKeyNet `D:/PiyaNota/training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt` sha256 `e718d4479b1310369b64cfaf9a8f1ff433179543ffa9d1810b24c683de13fe10` (hashed 2026-11-08; the file is gitignored and lives only in the main checkout). (2) CLOSED, inference config: each strip PNG is read in colour (`cv2.IMREAD_COLOR`; the cut strips are 3-channel PNGs, and this is the same array the pipeline passes on, which `transcribe_strip` converts to grey itself; a grayscale read was tried in the smoke test and broke the strip-equality guard) and decoded by `stage3_transcription.transcribe_strip(img, model, device, 64, return_confidence=True)`: greedy CTC (beam search was a NO-GO), one strip per call (batch size 1), fp32, model in `eval()`, no test-time augmentation, strip height 64 from the grey native `strip_source`. Device is CPU, as in `eval_divisi_a6.decode_strip`, so the decode does not depend on cuDNN algorithm choice. The head size must equal `len(stage3_transcription.VOCAB_EXT_A9)` (1056 rows) or the run stops; this supersedes the 536 (`VOCAB_EXT_CHORD_TUPLET`) written in `docs/NEXT-SESSION-c2-freeze.md`, because the C2 checkpoints carry the A9 head (the smoke test shows the assert fires on the 513-row base CRNN). In `clefkey` mode `--clef-key` is required, is not defaulted, and its sha256 must equal the pinned ClefKeyNet value above or the run stops. The prediction file is `{"meta": {mode, source, checkpoint_sha256, runner_sha256, clef_key_sha256}, "strips": [{piece, page, sys, staff, tokens, confidence}]}` (`confidence` is one number per token, same length as `tokens`; the scorer reads only `strips`), one file per (checkpoint, medium, mode). Smoke test (`training/phase2/smoke_predict_real_set.py`, non-real-set material only: dev screenshot `data/raw/Digital Screenshot/IMG_5750 (1).PNG` as PDF and dev camera photo `data/raw/Raw/IMG_1081.JPG` as camera, fake S-A-T-B slots): both seeds, both media and both modes ran; one prediction per row; the rebuilt strips equal the cut strips; the injected clef and key equal `header_override`; result "SMOKE OK" on 2026-11-08. No accuracy is read from it. The runner script that writes it, `training/phase2/predict_real_set.py`, is written and committed in the freeze commit; it contains no scoring logic. Hashes of the files as reviewed (senior-reviewer and choral-conductor, 2026-11-08, findings applied) and committed: `predict_real_set.py` `093966d84bfa62457eac571d7ae5898c31ae12e337915813a7596356903949ff`, `real_set_confidence.py` `01140751e0201b9ffbae9766eb582e93a878872d68b92dc0b09eb74bbffda88d`, `test_predict_real_set.py` `f831956a588fb4f582c5003fdac9a5a5bba754155a25911edf70e1ca155d3982`, `test_real_set_confidence.py` `24c09e58d59058d80c333be26028a59e0890bbca6d1b283149d762fbf2fd6234`, `smoke_predict_real_set.py` `355632a41a53747b5aa9945bf9d3d0046902ac6d703d3bb9a557163249c6b094`. Any later edit to these five code files voids the pin. The PREREG file itself is excluded: the freeze-commit hash placeholder is filled by a recorded addendum after the commit, and that addendum does not void the pinned file hashes. (3) Code state: the scorer, cutter and check scripts are unchanged since commit `bea5f098238d6e8b75a5c9ac1e1d44cacd3da2bd`; on 2026-11-08 `git status` showed only this file modified. The freeze commit hash is added to the report after the commit, and the scorer and cutter are re-hashed against the values in the cut record. Ground-truth overlap with earlier development: Stage 1 mask thresholds were tuned on Ale among 10 tuning pieces, and Ama_Namin and Gaano were in the frozen mask set but were looked at (`training/step3_mask_split.json`, `docs/bug-tracker.md` BUG-015); Gaano is also in the ClefKeyNet fresh-photo evaluation (dev data, user ruling 2026-09-28). Checked 2026-11-08: no other of the 10 test pieces appears in the BUG-021 set (Dormi, Livin', Flashlight), in the ClefKeyNet fresh-photo set (Non Nobis, Honneur, Handog, Gaano), or in the mask split (the 10 tuning pieces, 4 frozen, 4 excluded, DSMN and BSN). Overlap with the ClefKeyNet training data was not checked, because that data is synthetic renders; this is stated, not proved. CLOSED as disclosure: Ale (Stage 1 mask tuning) and Ama_Namin (Stage 1 mask, looked at) are added to the prior-looks list in the pristine-set paragraph. (4) Full hashes: `stage2_detection.py` `26c1c5857acbc64ab33ce79af8e1c1685968d86ebbd4a1f6a592a0f7491025b2`, `cut_divisi_real.py` `c49dbd3e06e07ee2df98c71467f5bab063cb9266000b9eb891dd671f839e3935`, `best.pt` `f55bb85176876d8af6eb5d02b56e22f65193e6bbc244f2e33f59ea6234018213`, `real_set_sizing.py` `34324ee4d1f4a3e5a7ef10e96a7f90b250d0af6af78195c48dd8d49b71f9f8b9`, `check_real_cut.py` `5269df701bf20119c012ecbd4dbc45a1c877279f3badd8e9d89dac0e7de7d4c2`. (5) CLOSED, cut record: the full cut (135 MB, strips and eyeball sheets) is copied to `D:/PiyaNota/data/c2_real_cut_frozen` (outside git; the job temp folder is deleted with the job), and its record files (`cut_code_sha256.txt`, `inputs.json`, `manifest.jsonl`, `pages_log.json`, `check_flags.txt`) are in the repo at `docs/decisions/evidence_c2_cut/`. `inputs.json` sha256 `15e06616b021477a416d8ae115b61f121e02a20006441504af47d42dc70595b2`; `manifest.jsonl` file sha256 `fe120cbcee3935766ad720d0c54296a44fabe5b1fbc97f20b684d44f1fc6eb3e` (identical in both copies); the recorded `manifest_sha256` `596295d5c0b128680ba3bcf3e7ae1fe4821b8709626d1c97c15ff4d65bc06ed8` and `strip_files_sha256` `e4c12e27d42fc4875bc17bc2c70ae16e0fd08f3dc2c1ae093388d0f6dcfc1585` come from `inputs.json`. The strips are scored from the `data/` copy only.

**Freeze addendum (2026-11-08).** Frozen by commit `c7333b6a16cf85bab3fa7c86a617a305bac986ad` after ml-cv-lead sign-off and the user's explicit approval. The five code files in that commit have the sha256 values listed in 25.3 (checked before the commit). The files are LF; a checkout that converts them to CRLF changes their bytes, so score from a checkout with LF (or verify the hashes first). Scoring order: seed 1 then seed 2, PDF then camera, raw then filter then ClefKeyNet, Arm 1, 3, 2, one process at a time.

**Amendment 1 (2026-11-08, found while running; no score had been read).** The first ClefKeyNet run (seed 1, PDF) stopped on the strip-equality guard at Kay_Ganda p1: the rebuilt strip has the same shape and boxes as the frozen strip and differs by at most 2 of 255 grey levels (resampling noise between the cut session and now; checked with and without `keep_unmasked`, same result). Exact byte equality is therefore replaced by `strips_match`: same shape, maximum absolute difference at most 8 and mean absolute difference at most 0.5. A different crop box would change many pixels by large amounts, so the guard still proves the same boxes. Nothing else in the runner changed. The `raw` and `filter` modes do not use this guard, and the two seed 1 PDF prediction files already written (raw, filter) came from the frozen runner (`meta.runner_sha256` starts `093966d8`); their decode path is unchanged. New hashes: `predict_real_set.py` `821a84347d00efcaf948a15e17de953579e67bb9d2989bf2e094a4dc42e9f1f9`, `test_predict_real_set.py` `b6e8347b95b91f32f4c42ad9fcbe9e8e0dd3cb3d20619a54e1008977b80b3437`. This amendment is committed after the user reviews it.

**Amendment 2 (recorded 2026-11-08, before any C2 real-set score was read).** The seed 1 camera ClefKeyNet run first stopped on Ale page 1, system 1, staves 1 and 2: the strip rebuilt from the photo had a different width from the frozen cut (1372 against 1353, and 1202 against 1372 pixels), while the other ten strips of that page matched within the Amendment 1 tolerance (at most 8 of 255, mean 0.5). The completed seed 1 camera run then showed the problem is not local: 234 of 912 camera strips differ from the cut beyond the Amendment 1 tolerance, in every one of the ten pieces (Ale 19 of 108, Ama_Namin 19 of 48, Bahay_Kubo 14 of 48, Gaano_Ko_Ikaw_Kamahal 22 of 72, Kay_Ganda_Ng_Ating_Musika 60 of 136, May_Hihigit_Pa_Ba 25 of 128, Pangarap_Ko_Ang_Ibigin_Ka 24 of 104, Pangarap_Lang 24 of 116, Paru-parong_Bukid 13 of 60, Tikong_Tiko 14 of 92). The Stage 1 and Stage 2 source files have the same hashes as the cut record, the YOLO boxes are identical on CPU and GPU, and two rebuilds in a row agree with each other, so the cause is only partly found: for Ale page 1 box 1, `_extract_boxes` truncates YOLO floats to integers (y1 351.011, 0.011 px above an integer boundary) and the connected-component crop in `_content_extent` is a step function of the integer rows, so a tiny cross-session float difference changes the strip width. Box 2 and the other strips were not explained. ClefKeyNet reads the unmasked page at the detected box and not the rebuilt strip, so the byte comparison is an equivalence check and not an input. The runner therefore no longer stops on a mismatch: it records the strip in `meta.decisions[strip_id].rebuild_mismatch` as true, still reads ClefKeyNet from the current page and box, and the report will list every flagged strip and show the camera ClefKeyNet result with and without them. The CRNN always reads the frozen strip, so the raw and filter files are unaffected. The seed 1 PDF files were produced before this change and had no mismatch. New hash (added 2026-11-08 after all predictions, before the report was committed): `predict_real_set.py` `7c6745cf469bb88a14dc18b476c5bba111aa4e1b6ab17e5cc2a096c337f12d2e`. Which runner wrote which prediction file is recorded in each file's `meta.runner_sha256`: `093966d8` (sha256 of the CRLF working copy; the LF blob in c7333b6 is `dfcab55a2df18727d15e55db47256fa0c29cbdd50d6863703d267cdfdb7f13f3`, content identical) for seed 1 PDF raw and filter; `821a8434` (Amendment 1 runner, never committed) for seed 1 PDF ClefKeyNet and seed 1 camera raw and filter; `7c6745cf` for seed 1 camera ClefKeyNet and all seed 2 files. The flagged strips are listed in `D:/PiyaNota/data/c2_real_scores/camera_rebuild_mismatch_strips.json` (234 strips, the same set for both seeds). This amendment is committed after the user reviews it.
