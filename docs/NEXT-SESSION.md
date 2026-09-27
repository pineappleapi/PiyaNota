# Next Session — Start Here

Handoff doc for continuing PiyaNota work in a fresh session. Read this first; it links out to the
full detail rather than repeating it. Written 2026-09-14, rewritten 2026-09-16, rewritten 2026-09-19,
rewritten 2026-09-24, top section added 2026-09-28.

## Fresh-photo pipeline eval: Stage 3 with and without the clef/key classifier (2026-09-28) - newest, read first

Branch `piya106/groundtruth-eval` (worktree `D:\PiyaNota-training`, no remote, nothing merged or pushed).
Full record:
- `data/eval_fresh/REPORT.md`: interpretation, limits, and abstract text reviewed by ml-cv-lead.
- `data/eval_fresh/REPORT_tables.md`: all numbers, per symbol and by voice. Confusion matrices are under `runs/scores/`.
- `data/eval_fresh/PREREG.md`: the pre-registration and Amendment 1.

Re-run from the repo root in the CPU venv (deterministic): `python data/eval_fresh/run_eval.py`, then
`score_eval.py`, then `make_tables.py`.

**What it tested:** the training-tree Stage 1/2/3 on real phone photos from `D:\PiyaNota\data\piyanota_dataset\`.
Stage 3 ran in two versions:
- **(a) as-is:** the CRNN reads the clef and key.
- **(b) `stage3_clefkey.py`:** the ClefKeyNet clef and key replace the CRNN header. `resolve_clef` is the single
  octave owner, and each system's key comes from a confident-majority vote.

Both fine-tuned CRNN seeds are reported as a range, with the original CRNN as a reference row. Pitch accuracy,
end-to-end:

| Piece (GT status) | Strips found | (a) as-is | (b) + classifier | Oracle clef/key |
|---|---|---|---|---|
| Non Nobis Domine (user-verified, **gated: PASS**) | 28/36 | 8.0-10.2% | **64.0%** (86% on found strips) | 64.0% |
| Honneur a Toi (agent GT; mask-tuning piece) | 28/28 | 10.9-15.4% | 73.3-75.9% | 76.7-78.5% |
| Gaano Ko Ikaw Kamahal (agent GT, unchecked) | 72/72 | 19.9-24.5% | 82.7-82.8% | 82.7-82.8% |
| Handog (agent GT, unchecked, weakest; mask-tuning piece) | 40/52 | 9.5-9.8% | 54.1-54.6% (78% on found strips; Bass 15-26%) | same as (b) |

- **Only Non Nobis is evidence.** Its GT was verified by the user, and it is the only gated piece (gate PASS for
  both seeds). Honneur, Gaano and Handog use agent-made GT; Gaano and Handog were never checked, at the user's
  request. Their numbers are diagnostic only and never pooled. Honneur and Handog are in the Stage 1 mask TUNING
  split, so none of their numbers are fully held out.
- **All of the gain comes from the clef/key header.** Note and rhythm tokens are unchanged. Token SER is still
  33-50%, and rhythm is 64% end-to-end on Non Nobis. Every piece uses only standard voice clefs, so a
  voice-default rule would score the same on clefs. One mid-piece key change (Gaano) was read correctly.
- **Honneur fails its reference gate on review load (39%)** because of BUG-025: the ClefKeyNet crop lands wrong
  under a page-edge shadow.
- **Stage 2 loses whole pages** that contain a non-4-staff system: Non Nobis p4 (solo staff) and 9 of 14 Handog
  pages (divisi). Logged as BUG-026.
- New bugs:
  - BUG-024: Stage 3 stacks an explicit accidental on top of the key alteration.
  - BUG-025: the clef/key crop is misplaced under page-edge shadow.
  - BUG-026: Stage 2 drops whole pages.
- **The Non Nobis, Honneur, Gaano and Handog photos are now used.** They are TEST-only anyway, so any fix for
  BUG-024/025/026 must be developed on other pieces.

**Ground truth moved to `gt/`** (see `gt/README.md`):
- `gt/non_nobis_domine/` (user-verified)
- `gt/honneur_a_toi/`
- `gt/gaano_ko_ikaw_kamahal/`
- `gt/handog/`
- `gt/dont_stop_me_now/`
- `gt/clef_key_labels/` (was `data/val_clefkey/`; SPENT)
- `gt/both_sides_now/`
- the annotation viewers, in `gt/tools/`

Crops are gitignored and can be regenerated.

**Suggested next actions (the user has not chosen yet):**
1. Wire the classifier into the real `stage3_transcription.py` path (the plan doc's "Required before wiring"
   items 1-5; `stage3_clefkey.py` is an eval-only wrapper), then re-test on fresh photos of new pieces.
2. BUG-024: a small fix in `infer_pitch` (an explicit accidental should set the absolute alteration).
3. BUG-025: fix the crop x0 under shadow, developed on non-test pages.
4. BUG-026: make Stage 2 reject only the non-4-staff systems, not the whole page.
5. If the Gaano/Handog numbers should count as more than diagnostic, the user checks their GT.
6. Note reading (SER 33-50%) is now the main source of error. That is the CRNN font/photo domain gap (BUG-011).

## Clef/key classifier - local CPU training ready (2026-09-27)

> **Superseded (2026-09-28):** the steps below are done. The T4 checkpoint was used under a user override, the
> real-val eval FAILED (BUG-021), and the Dormi/Livin'/Flashlight set is SPENT. Labels now live in
> `gt/clef_key_labels/`, and the Honneur GT is in `gt/honneur_a_toi/`. See the 2026-09-28 section above and the
> plan doc.

Branch `piya106/groundtruth-eval` (worktree `D:\PiyaNota-training`, no remote, nothing merged). Full record: `docs/decisions/piya-106-clef-keysig-detector-plan.md`, sections "2026-09-26 amendment", "2026-09-27 review of local training code" and "2026-09-27 status after the R1-R6 / E1-E4 fixes".

**Data roles:**

- **Validation only (check-only, never tuning):** Dormi Jesu, Livin' on a Prayer and Flashlight (Flashlight is retired from test). Labels are in `data/val_clefkey/` (gitignored, sha-frozen).
- **Test only:** DSMN and Honneur a Toi.
- **Ground truth:** DSMN GT has 60 strips, re-frozen at sha 72edc5ca.... Honneur GT has 28 strips, sha 80219bdc...; `data/eval_honneur/gt/build_gt.py` is the generalised converter.

**Training code:** `training/train_clef_key.py` and `training/eval_clef_key_realval.py`, with ml-cv-lead's R1-R6 / E1-E4 applied (`850f880`). The CPU-only venv `D:\venvs\piyanota-cpu` is the reference configuration. Smoke tests: S1 byte-identical x2, S3 resume identical in content.

**The GPU is not usable (BUG-019).** Do not run CUDA torch or `nvidia-smi` until the PC is rebooted and the driver is reinstalled.

**Next actions, in order:**

1. The user reboots.
2. ml-cv-lead confirms the E1 thresholds (1.0 spacing, 25%).
3. The user gives the go for the full CPU run, about 6.5-9.5 h. The command is in the plan doc.
4. Run the E4 coverage dry run.
5. Review, then run the second seed.
6. Run the one-shot real-val eval.

**Awaiting the user's choice of pipeline change:** the Stage 3 double-dot fix (suggested first; Honneur scoring needs it), FR-14 Stage 4 report wiring, or PIYA-127 handling of 5-staff (obbligato) systems.

## DSMN eval + Stage 3/4/5 review (2026-09-26)

Full record: `docs/decisions/piya-106-dsmn-heldout-eval-2026-09-26.md`. Summary: Stage 1/2 ready for Stage 3 (with caveats);
CRNN fails the SOW on DSMN (token SER 44.3-47.9% across the two seeds, pitch 10.6-11.4%, clef 2-3/23 correct), BUG-011 unfixed.
Stage 3 dot/`slur.end` and Stage 5 hanging-note-on fixed (`1f237de`, `4021323`). Stage 3/4/5 rework not ready for main until Stage 4
flags and a clef-unsure signal reach `run_full_pipeline`. PIYA-127 (FR-24 recapture, BUG-018) is drafted. Nothing merged or pushed.

## PIYA-121 update (2026-09-25) - read before the 2026-09-24 section below

Superseding note: the Stage 2 lyric mask described below (`_non_staff_ink_mask`, `mask_lyrics=`) has been REPLACED. The mask is now `non_staff_ink_mask` in Stage 1 (after dewarp) and Stage 2 only crops; strips come from a native-resolution strip source (rest/thin-glyph deformation root cause: binarising at 1600 px, BUG-016). Tie recall was the priority.

- Split by piece (`training/step3_mask_split.json`, recorded before results): frozen = ama_namin, gaano_ko_ikaw_kamahal, salmo_150, non_nobis_domine; tuning = 10 pieces; DSMN/BSN = 'seen', not frozen, not independent of tuning. 4 pieces excluded as not open-score SATB (reasons in the JSON).
- Results (`python training/step3_mask_audit.py --mode report --out data/audit`): frozen ties 120/120, slurs 25/25; tuning ties 670/684, slurs 116/117; band ink removed 0 on all 108 pages; BSN 80 strips (12/12/12/12/12/12/8) and DSMN 60 strips, SATB order OK; all 140 strips viewed at 1:1.
- Honest limits: frozen set is small (4 pieces, 23 pages); tie audit is over detector-found ties only; 14 tuning ties lost and 31 tuning beam flags not viewed; lyric residual still visible (DSMN 11/15 systems; ~3/32 sampled dataset strips legible); the old-vs-new tie comparison was dropped (unpaired candidates, slow); rest-specific before/after exists only for DSMN page 1, set-level numbers are band-wide (BUG-016).
- No Stage 3/CRNN was run on any of this. BUG-001 stays open. Nothing merged or pushed.
- Untracked `ground_truth/` and `rename_dataset/` pre-date this work and are not part of PIYA-121.

## Immediate next action (2026-09-24 update)

**PIYA-106 Step 3 (fresh real-world test set) is actively in progress**, on branch
`piya106/two-seed-rerun-amendment` (worktree `D:\PiyaNota-training`; **committed, unmerged into
main**; senior-reviewer review of the full branch requested but not yet returned at write time —
check for its report before treating this branch as merge-ready). Source material: 7 camera photos of
"Both Sides Now" (`D:\PiyaNota\data\raw\Raw\IMG_1081-1084,1086-1088.JPG`), different piece/tool from
the 48 BUG-011 diagnostic strips, matching the "Start Step 3 now" instruction below.

Getting Stage 1/2 to detect these camera photos accurately at all turned into three sequential fixes,
all committed on that branch:
- **BUG-013** — Stage 1 staff curve tracking (`track_staff_curves`) + dewarp
  (`dewarp_to_staff_grid`) + Stage 2 tracker cross-check (`_reconcile_with_classical`). Fixed wrong
  staff counts (was 6-13 per page); now 12/12/12/12/12/12/8 = 80 staves, all correct on this photo
  set. Tuned on these same 7 photos, not an independent eval.
- **BUG-014** — content-adaptive strip crop (`_content_extent`/`_crop_and_resize`) fixed notes being
  clipped at strip edges.
- **BUG-015** — lyric masking (`_non_staff_ink_mask`, `mask_lyrics=` toggle, default on). Pixel-exact audit
  2026-09-25 (`training/step3_mask_audit.py`, reproducible): 0 px removed in staff band on all 80 strips;
  (pre-tie-fix figures) 79,789 px removed = 5.8% of ALL ink (46.8% of out-of-band ink by the script's definition). True lyric
  residuals: 2 of 80 (page006_sys03_Tenor 'Aah', page003_sys01_Bass minor) + 1 unverified tiny fragment;
  dynamics/labels/brace slivers remain (non-lyric). **Tie/slur deletion defect: fixed on this branch 2026-09-25** (`_tie_bridge_runs` in `stage2_detection.py`). Re-audit on the same 80 strips (not independent): 79,789 -> 41,962 px removed, still 0 px removed in the staff band, audit 'bridging removed piece' flags 20 -> 2 strips; the new strips are a strict superset of the old ones and the difference (220 pieces) was enumerated: 209 pieces are outer-staff-line wobble now kept, 11 are ties/slurs (no lyric/neighbour fragments among them). Viewed at native resolution for ~15 of the 20 flagged strips including page003_sys02_Bass and page006_sys03_Bass; the other 5 and the original 17-strip confirmed list were NOT re-checked individually, and the 0.5 hug threshold was picked on these same strips. Two small tie/slur residuals remain (page007_sys02_Soprano arc fragment, page002_sys03_Alto tie bottom). Lyric residual unchanged at 2/80. See BUG-015 in `docs/bug-tracker.md`.

**BUG-001 (camera photos fail the divisible-by-4 staff count check) remains open by explicit user
instruction** even though this branch's fixes resolve it for this specific photo set — it needs a
fresh, different camera set to pass before it can be closed.

**senior-reviewer's verdict on the full branch (687de98..HEAD, 2026-09-24): "ready with changes
(nits only — no blocking correctness issues found)."** The nits (missing type hint, no per-strip
masking log, two test docstrings overclaiming what they check, stats not independently
reproducible from committed code) were fixed in a follow-up commit after the review. senior-reviewer
also raised three questions it explicitly left for a human, not resolved by that review and not
decided by this session — read before merging:
1. Whether to merge the partial BUG-015 mitigation now and decide the YOLO text-line fallback in a
   follow-up, or wait for the pixel-exact residual re-verification first — this directly gates
   whether Stage 3 testing can start (the "don't test Stage 3 until masking is adequate" instruction
   is itself unresolved).
2. The branch name `piya106/two-seed-rerun-amendment` no longer describes its content (this session's
   work is PIYA-121 Stage 1/2 fixes, unrelated to the PIYA-106 two-seed CRNN rerun the name
   references) — cosmetic, consider a rename before merge so history doesn't mislead future readers.
3. It couldn't find a separate committed ml-cv-lead artifact for the page006_sys03_Bass finding
   beyond the bug-tracker correction note — that finding came from a live diagnostic session (ml-cv-lead
   instrumented and traced `_non_staff_ink_mask`'s actual component decisions on that strip, not a
   new commit), so there's no separate file to point to; flagging here in case that's insufficient
   provenance for a merge decision.

**Stage 3/CRNN has deliberately NOT been run on any of these 80 strips** — explicit user instruction:
no Stage 3 testing until lyric masking is judged adequate (masking is not yet judged complete, see
BUG-015 above). This is the actual Step 4 evaluation set; don't spend it on masking-tuning iteration.

**Once masking is settled (either "good enough" or the YOLO fallback is built), the next action is
Step 4: evaluate both seed checkpoints (`finetuned_font_seed1.pt` / `finetuned_font_seed2.pt`, see
below) on this set once, reporting them as a range — do not average or cherry-pick.**

---

**Checkpoint metadata, authoritative (2026-09-26, user decision: use the files' own metadata; sha256 matches data/eval_dsmn/checkpoint_hashes.txt):** the deployed `finetuned_font_seed{1,2}.pt` are from the 2026-09-23 two-seed run, not the 2026-09-19 run: seed1 epoch 2, `loo_font_ser` 0.0926, canary clean/distorted 0.0785/0.1311; seed2 epoch 2, `loo_font_ser` 0.0562, canary 0.0492/0.0865. Report as a range (0.0562-0.0926). Older 0.0523/0.0886 figures below refer to the 2026-09-19 run whose checkpoints were overwritten.

## Earlier context: PIYA-106 Step 2 (CRNN fine-tuning) status, as of 2026-09-19

**The real two-seed `RUN_FINETUNING` run (under the cuDNN fix) is DONE.** Both checkpoints are valid
and not invalidated: `crnn_weights/finetuned_font_seed1.pt` (best epoch 1, `loo_font_ser` 0.0523) and
`crnn_weights/finetuned_font_seed2.pt` (best epoch **2**, `loo_font_ser` 0.0886, with an epoch-3
canary-clean spike to ~89% of the hard cap before partially recovering). ml-cv-lead's fourth review
this session: **conditional GO to Step 3 — Step 2 is not formally closed.**

Step 3 (above) is now underway per that conditional GO; the open items below still aren't resolved
and still don't block Step 3.

**Open items carried forward, not blocking Step 3 but not resolved — don't let these quietly drop:**
- Seed=2's best epoch was 2, not 1 — this **disconfirms** the earlier read (from two isolated seed=1
  repro runs) that "epoch-1-is-always-best" was a real property of `lr=3e-5`; it was
  checkpoint-selection luck. Do not switch to the `1e-5` runner-up candidate — it lacks equivalent
  seed-replication rigor and already lost to `3e-5` by ~24% relative in earlier seeded runs.
- Seed=2's epoch-3 canary-clean spike to ~89% of the hard cap is independently concerning — a real
  oscillation/stability signature, not just "the cap held."
- The ~70% relative gap between seed=1's best (0.0523) and seed=2's best (0.0886) is *not* cleanly
  within the established same-seed noise floor (7–29%, measured same-epoch/same-seed) — plausibly
  explained instead by `finetune_train_loader` (notebook cell 12) still having `shuffle=True` with no
  seeded `generator=`/`worker_init_fn`. **Report both seed checkpoints as a range going forward — never
  cherry-pick seed=1's better number.** Apply the DataLoader seeding fix before treating `lr=3e-5` as
  fully settled.
- At Step 4, evaluate both seed checkpoints separately against the real test set — do not average them.
- None of this round's findings say anything about whether the actual BUG-011 real-screenshot fix
  works — it's purely a training-stability question. The confidence/uncertainty problem (plan step 7)
  remains completely untouched.

Full narrative (seed-replication check results, RNG-leftover-state bug, cuDNN-nondeterminism bug and
fix, the lost-baseline finding, both reproduction runs, the real two-seed run, and all four ml-cv-lead
reviews from this session): 2026-09-16 and **2026-09-19 amendments** in
`docs/decisions/piya-106-crnn-font-retraining-plan.md`.

**Do not use `crnn_weights/finetuned_font.pt`** (first unseeded, buggy `RUN_FINETUNING` attempt) or
either `crnn_weights/finetuned_font_seed{1,2}.pt` produced **before** the 2026-09-17 cuDNN fix — those
are invalidated; only the versions from the completed run above are valid. The two
`crnn_weights/repro_check_seed1.pt` runs from this session are diagnostic-only, not Step 2 deliverables
either.

## Branches / commit state

- **`piya106/two-seed-rerun-amendment`** (worktree `D:\PiyaNota-training`, **current active branch as
  of 2026-09-24**) — Step 3 camera-photo test-set work (BUG-013/014/015 above). Commits, top to
  bottom: `b322457` lyric masking (BUG-015), `d374c2b` review follow-ups (named constants, dedupe
  `STRIP_HEIGHT`, synthetic tests), `7be14ee`/`a908579` crop fix (BUG-014) + docs, `30b5b41`/`4d46d46`
  tracker/dewarp fix (BUG-013). Not pushed (no remote on this worktree), not merged into
  `D:\PiyaNota`'s checkout. senior-reviewer review of this branch was requested at end of session —
  confirm its outcome before merging.
- **`fix/bug012-border-blank-overreach`** (earlier branch, superseded as the active one) — no longer a single uncommitted unit; it
  now carries multiple merged-in-sequence commits from BUG-012's fix through this session's Step 2
  work:
  - `59212f7` PIYA-125: fix Stage 1 border-blanking content destruction (BUG-012)
  - `6af7e1e` PIYA-106: font re-render Step 1 + two-tier canary gate for Step 2 fine-tuning
  - `6ea1faa` PIYA-106: amend retraining plan with two-tier canary gate + font_val_ser leakage finding
  - `edee99b` PIYA-106: fix font_val_ser leakage with invariant asserts + Leland LOFO probe
  - `944cdb5` PIYA-106: fix loo_font_ser checkpoint-selection leakage, add seed control to
    fine-tuning loop
  - plus a docs-only commit for this session's write-up (decision doc amendment, this file, the
    CLAUDE.md status update)
  Still pending: senior-reviewer pass + merge decision, once Step 2's real result is in — not done
  yet, don't treat this branch as merge-ready.
- **`docs/methodology-reorg`** (worktree) — documentation reorganization, unrelated to any bug fix.
  Still unmerged; unchanged this session.
- **`docs/decisions/module2-flutter-framework.md`** — untracked, unrelated Module 2 decision doc that
  showed up in `git status`. Not part of this thread's work; leave it alone unless the user raises it.

## Where the accuracy numbers actually stand

Full detail: `CLAUDE.md` → "Evaluation results snapshot" section, and `docs/bug-tracker.md`
(BUG-011, BUG-004). Unchanged since 2026-09-14 — Step 2 fine-tuning results aren't final yet, so
nothing here has been superseded by a new headline number.

- **CameraPrIMuS (the CRNN's training data):** 98%+ accuracy/SER, clean and even under synthetic
  distortion. This number is real but describes the training distribution only.
- **Real screenshots (actual deployment target):** true real-world accuracy is unmeasured and likely
  well below the old, now-retracted ~4.2% ceiling estimate. Root cause (ml-cv-lead reviewed): the
  CRNN has only ever seen one synthetic font; real engraving-software glyphs are a different shape
  it's never trained on. See BUG-011 in `docs/bug-tracker.md` for full detail.
- **DS2 Dense / YOLOv8 staff detector:** one number on record (mAP50 0.9766), but it's mislabeled —
  actually a val-split result, not test-split (BUG-004, open, unresolved NumPy crash blocking a
  real re-run). Don't quote this number as clean.

## The retraining plan — current step status

Full plan + amendments: `docs/decisions/piya-106-crnn-font-retraining-plan.md`

1. **Font re-render CameraPrIMuS via Verovio** — **done.**
2. **Fine-tune the existing CRNN checkpoint, watch clean/distorted CameraPrIMuS SER as a forgetting
   canary** — **substantively done, not formally closed.** LR sweep, extended trend check, and
   seed-replication check are done (lr=3e-5 confirmed over lr=1e-5, replicated across 2 seeds); the
   cuDNN-nondeterminism bug found after the first real two-seed run is fixed; the real two-seed final
   run under the fix is **complete** (`finetuned_font_seed1.pt` best epoch 1 / loo 0.0523,
   `finetuned_font_seed2.pt` best epoch 2 / loo 0.0886) and ml-cv-lead's fourth review gave a
   conditional GO. Not formally closed because of the open items above (DataLoader seeding gap, the
   seed1/seed2 divergence, seed=2's near-cap wobble) — none block starting Step 3, but should be
   resolved before calling Step 2 fully done.
3. Collect a **fresh** real-world test set (different piece/tool than the 48 strips already used for
   BUG-011 diagnosis) — **not started, now the active item**, needs new photos/screenshots from the
   user.
4. Evaluate once on that fresh set; token-level SER + insertion/deletion rate, not just clef/pitch
   accuracy — **not started**, blocked on step 3.
5. Only if still far short of target: escalate to hand-labeling real strips — **not started**.
6. Re-run the confidence (confident-right vs. confident-wrong) check with a real sample size —
   **not started**.
7. Treat "confidently wrong" predictions as a separate open problem from raw accuracy — **not started**.

## Things not to do without re-checking first

- Don't use `crnn_weights/finetuned_font.pt`, either `finetuned_font_seed{1,2}.pt` from before the
  2026-09-17 cuDNN fix, or `crnn_weights/repro_check_seed1.pt` — all invalidated or diagnostic-only
  (see above). The post-fix `finetuned_font_seed1.pt` / `finetuned_font_seed2.pt` (from the completed
  two-seed run) ARE valid and usable — but report them as a range (0.0562–0.0926 loo_font_ser, the files' own 2026-09-23 metadata), never
  cherry-pick seed=1's better number.
- Don't treat "epoch-1-is-always-best" as settled — that was a read from 2/2 *isolated seed=1* repro
  runs, and the real seed=2 run's best epoch was 2. Checkpoint-selection luck, not a property of
  `lr=3e-5`; disconfirmed, not confirmed, by the real two-seed run.
- Don't ignore seed=2's epoch-3 canary-clean spike (~89% of hard cap) — a real stability signature,
  flagged by ml-cv-lead's fourth review, not yet investigated.
- Don't assume the seed1/seed2 loo_font_ser gap (~70% relative) is just noise — it's larger than the
  established same-seed noise floor (7–29%) and is plausibly caused by the still-unfixed
  `finetune_train_loader` DataLoader seeding gap (cell 12, `shuffle=True`, no `generator=`/
  `worker_init_fn`).
- Don't hand-label real Filipino sheet music as a first move — the diagnosed cause is font/glyph
  shape, not content or language.
- Don't reuse the 48 BUG-011 diagnostic strips to report the retrained model's accuracy.
- Don't blend CameraPrIMuS and real-world accuracy into one aggregate number in any future report.
- Don't present a single-seed `loo_font_ser` number as a settled result — report it as a 2-seed
  range/distribution per the current notebook structure, and remember `loo_font_ser` is still
  confounded by content-familiarity leakage (Leland is held out of training, but the same passages
  Leland renders were seen by the base model in other fonts) — flag this whenever the number is
  quoted, don't present it as an independent confirmation.
- Don't commit `docs/decisions/module2-flutter-framework.md` as part of PIYA-106 work — unrelated.
- Don't commit anything without the user's explicit review/approval first (standing rule).
- Don't run Stage 3/CRNN on the 80-strip Step 3 test set until lyric masking (BUG-015) is judged
  adequate — explicit user instruction, still in force as of 2026-09-24.
- Don't treat the BUG-015 eyeballed residual list as accurate without pixel-exact re-verification —
  it has at least one confirmed false positive (page005_sys02_Alto) and the rest of the list beyond
  page006_sys03_Bass is unconfirmed either way.
- Don't close BUG-001 — still open by explicit user instruction even though this branch's fixes
  resolve it for the one photo set tested so far.

## Reference index

- `CLAUDE.md` — project instructions + evaluation results snapshot + retraining plan pointer.
- `docs/bug-tracker.md` — BUG-011 (font domain gap, full falsification trail), BUG-012 (fixed,
  merged into this branch's history), BUG-004 (DS2 Dense eval mislabeled split, open).
- `docs/tickets/module1-pipeline.md` — PIYA-107 (pitch inference) real-screenshot measurement note,
  PIYA-125 (BUG-012 fix) status.
- `docs/decisions/piya-106-crnn-font-retraining-plan.md` — the full retraining decision record,
  including the 2026-09-16 amendment with the seed-replication data and RNG-bug root cause.
- `training/step1-font-rerender-kaggle-guide.md` — verified, runnable Step 1 instructions (Kaggle).
- `training/piyanota-training-ver-2.ipynb` — the CRNN training notebook. Cell 13
  (`finetune()`/`lr_sweep()`/`RUN_FINETUNING`) is the active edit surface for Step 2; requires an
  explicit `seed=` argument now (hard assert), and the real run always trains both seed=1 and
  seed=2 from a fresh copy of the base checkpoint.
