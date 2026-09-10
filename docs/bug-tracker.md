# PiyaNota Bug Tracker

Established for PIYA-410 (originally due as the Sep 4 action item; carried into Sprint 6).
A plain in-repo file, not an external tool — this repo has no GitHub remote configured yet, and
a file-based tracker needs no account or paid/team tier, matching PIYA-410 AC3 ("accessible and
usable by a single researcher").

## How to log a bug

Add a row to the table below. **Check the last-used ID first** — sequential numbering is manual,
nothing else guards against a duplicate or skipped `BUG-NNN`. Every bug must capture (PIYA-410
AC1):

- **ID** — `BUG-NNN`, sequential.
- **Description** — what's wrong, one or two sentences.
- **Repro steps** — how to reproduce it, concretely enough that it doesn't rely on memory later.
- **Severity** — see scheme below. Doubles as priority (AC2's "severity/priority scheme") — a
  single blocker/major/minor scale is enough for a solo triager; no separate priority axis.
- **Ticket/Module** — the specific ticket it relates to (e.g. `PIYA-105`), not just a module name.
- **Status** — see vocabulary below.
- **Phase** — see tags below (PIYA-410 AC4).
- **Date logged** / **Last updated** — bump the latter whenever status changes, so triage
  velocity is reconstructable later for the thesis QA narrative.

**Scaling note:** this is a flat table by design while bug volume is low. If it grows past
~30–40 rows or gets hard to scan mid-session (most likely during PIYA-411's live-testing week),
split it into one file per bug under a `bugs/` directory, or move to CSV — not worth building
that structure now, before there's anything to organize.

## Severity scheme

Applied consistently so bugs found during live testing can be triaged quickly without inventing
criteria mid-session (PIYA-410 AC2):

| Severity | Meaning |
|---|---|
| **Blocker** | Breaks the golden path end-to-end (capture → process → playback) or causes data loss/corruption. No workaround. |
| **Major** | A specific feature or input path is broken or produces materially wrong output, but the rest of the system still works. |
| **Minor** | Cosmetic, edge-case, or low-impact — doesn't block a respondent from completing a session. |

## Status vocabulary

`open` · `in-progress` · `fixed` · `deferred` · `won't-fix`

## Phase tags

Distinguishes bugs found during earlier development sprints from respondent-facing bugs found
during the protected testing windows (PIYA-410 AC4):

- `dev-sprint` — found during Sprints 1–11 development/integration work.
- `dry-run` — found during the PIYA-409 dry-run buffer week (Oct 20–25).
- `live-testing` — found during PIYA-411/412 live usability evaluation (Oct 26–30 / Nov 3–9).

## Bugs

| ID | Description | Repro steps | Severity | Ticket/Module | Status | Phase | Date logged | Last updated |
|---|---|---|---|---|---|---|---|---|
| BUG-001 | Camera-captured images pass the post-dedup staff-count-divisible-by-4 check at a much lower rate than digital screenshots (1/7 camera pages vs. 3/6 screenshot pages), and the failure cause doesn't reduce to the single near-duplicate-box pattern seen on screenshots — raw (pre-dedup) detections hit the 16-box cap on 6/7 camera pages with lower, more spread-out confidence (0.4–0.85 vs. 0.65–0.9), indicating additional missed and/or spurious detections beyond simple duplication. This is a reliability gap on the SOW's actual primary target input (mobile-captured photos), not the screenshots used for convenience during testing. | Run `data/raw/Raw` (IMG_1081–1088, 7 camera-captured pages) and `data/raw/Digital Screenshot` (6 pages) through Stage 1 → Stage 2 with identical settings (`staff_detector_files/weights/best.pt`, default `CONF_THRESHOLD`, `min_cy_gap=30`); compare post-dedup staff-count-divisible-by-4 pass rates. Full evidence trace: `docs/tickets/module1-pipeline.md` PIYA-121. | Major *(initial assessment — pending your confirmation; not yet validated against a larger sample)* | PIYA-121 (module1-pipeline) | open | dev-sprint | 2026-09-09 | 2026-09-09 |

| BUG-002 | `print()` calls containing Unicode typographic characters (e.g. `→` U+2192) raise `UnicodeEncodeError` and crash the process outright on a Windows console/pipe using the legacy `cp1252` code page (the default unless `chcp 65001`/`PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` is set) — not a display glitch, a hard crash. Fixed in `stage1_preprocessing.py` (all 4 occurrences replaced with ASCII `->`/`deg`; re-ran the 25-sample Test A/B suite afterward, no crash, identical pass results, no `PYTHONIOENCODING` workaround needed). Fixed in `compare_omr_baselines.py` (box-drawing `─` U+2500 section dividers, not `→` — 339 characters replaced with ASCII `-`; `--help` ran clean under plain `cp1252` afterward). Fixed in the remaining 4 files, each confirmed reachable via Read before editing: `stage2_detection.py` (1 occurrence, viz-flag-gated print), `stage3_transcription.py` (6 occurrences — key-sig prints, viz-save print, symbols→events print, the per-load "Loaded weights" print which fires on every Stage 3 model load, and the events-saved print), `stage5_synthesis.py` (3 occurrences — MIDI-saved, MP3-saved, and MP3-fallback prints, all on the every-run synthesis path), `prepare_deepscore.py` (1 occurrence — the argparse `description` string, printed on `--help`). All 4 files re-verified via `ast.parse` after editing (clean) and by grepping for any remaining `→`/`─` characters to confirm the only survivors are in comments/docstrings (never passed to `print()`), not runtime-reachable. All 6 originally-affected files are now fixed. | Run any Stage 1 batch (e.g. `python stage1_preprocessing.py data/raw data/preprocessed`) from a shell whose Python stdout encoding resolves to `cp1252` (reproduced via Git Bash on Windows with no `PYTHONIOENCODING` set, while validating the `correct_perspective()` fix with 25 synthetic keystone-warped samples — all 25 hit this crash on the first sample where a quad was actually detected). | Major | PIYA-106 (module1-pipeline) | fixed | dev-sprint | 2026-09-10 | 2026-09-10 |

| BUG-003 | Cross-system `tick_onset` collision corrupts multi-system SATB audio: Stage 3's `infer_pitch()` resets `tick_onset` to 0 on every strip (once per system), but `stage4_reconstruction.reconstruct_satb()` only *sorted* by `(page_index, sys_idx, tick_onset)` without renumbering `tick_onset` itself, and `stage5_synthesis.synthesize_satb()` groups notes by raw `tick_onset` and derives absolute MIDI time straight from it. Result: system 2 onward plays on top of system 1 instead of after it, on any piece with more than one system — the common case, not an edge case. Fixed by adding `_assign_global_ticks()` in `stage4_reconstruction.py`, run after per-voice sort/slur-resolution and before the existing duration-consistency check: computes one cumulative tick offset per `(page_index, sys_idx)` system boundary (from the max end-tick across all four voices, not per-voice, so a single Stage-3 duration error in one voice doesn't compound into a growing desync between voice tracks) and adds it to every event's `tick_onset` in place. Verified two ways: (1) a synthetic 2-system fixture engineered with a deliberate per-voice duration mismatch, confirming no two events share a `tick_onset` post-fix and confirming `_check_measure_duration_consistency`'s existing mismatch warning still fires unaffected; (2) an end-to-end Stage 4 → Stage 5 smoke test (mocking `MIDIFile` to record `addNote` calls, no soundfont/ffmpeg needed) across 2 pages / 3 systems, confirming strictly monotonic, non-duplicate onset times reach the actual MIDI-timing layer, not just the intermediate event dict. A team-lead review flagged one untested gap: a voice missing an *entire* system's events (not just a note-count mismatch) at a `(page_index, sys_idx)` key where the other three voices do have events. Verified separately, no bug: `system_keys`/`system_end_tick` in `_assign_global_ticks()` are built from the union of all voices' events, so a voice contributing nothing to a given system key doesn't corrupt or zero out the shared offset computed from the voices that do — confirmed with a synthetic fixture (Tenor present in systems 1 and 3, absent from system 2; Soprano/Alto/Bass present in all three) showing Tenor's system-3 `tick_onset` correctly lands at 1440, matching the other three voices exactly, with the pre-existing `_check_measure_duration_consistency` diagnostic also firing as expected on the gap. No code change was needed. | Build a 2-system (or 2-page), 4-voice event fixture where `tick_onset` resets to 0 per system (matching real Stage 3 output) and run it through `reconstruct_satb()` then `synthesize_satb()`; check for duplicate/non-monotonic onset times in the recorded MIDI notes. Reproduced and fixed via the two scratch test scripts described above (not committed to the repo). Missing-entire-system case reproduced via a third scratch fixture, also not committed. | Blocker | PIYA-106 (module1-pipeline) | fixed | dev-sprint | 2026-09-10 | 2026-09-10 |

| BUG-004 | `evaluate_model()` in `stage2_detection.py` calls `model.val(data=data_yaml)` with no `split` argument, so Ultralytics silently defaults to the **val** split (134 images) — despite the function's own docstring claiming it "Runs mAP evaluation on the test split," and despite `data/staff_dataset/dataset.yaml` defining a distinct `test: images/test` split (346 images) that is never actually used by `train_staff_detector.py --eval`. Any mAP50 number reported via this path (including the interim PIYA-105/DeepScoresV2 eval logged 2026-09-10: mAP50 0.9766, mAP50-95 0.8654, precision 0.954, recall 0.976) is a val-split number mislabeled as test. A diagnostic attempt to independently re-run with `split="test"` hit a separate, reproducible `RuntimeError: Numpy is not available` (preceded by `UserWarning: Failed to initialize NumPy: _ARRAY_API not found`) that did not occur on the val-split run — did not reproduce on train/val, only surfaced when the test-split label cache had to be built fresh; root cause unconfirmed (possible numpy/torch ABI mismatch), not yet investigated further. | Run `"D:\PiyaNota (Code)\.venv\Scripts\python.exe" train_staff_detector.py --eval --weights staff_detector_files/weights/best.pt`; compare the split Ultralytics actually reports against `data/staff_dataset/dataset.yaml`'s `test`/`val` image counts (346 vs. 134) to confirm which split ran. | Major *(mislabels which split every mAP report to date reflects; separate NumPy crash blocks getting a real test-split number until fixed)* | PIYA-105 (module1-pipeline) | open | dev-sprint | 2026-09-10 | 2026-09-10 |

| BUG-005 | `pip install oemer` (done for an external SER-baseline comparison, `compare_omr_baselines.py`) auto-pulled an unconstrained `numpy` 2.5.3 into the shared project `.venv`, which broke `torch.from_numpy` for PiyaNota's own CRNN inference path (`RuntimeError: Numpy is not available`) — the venv's pinned `torch==2.3.0+cu121`/`torchvision==0.18.0+cu121` wheels are ABI-compiled against NumPy 1.x, so any later `pip install` of a package with a looser numpy constraint can silently regress the whole inference stack. Worked around in the moment by re-pinning `numpy==1.26.4` (already the value pinned in `requirements.txt` as of PIYA-112 today — the regression was transient, not a change to the committed pin). Risk: this can recur any time a dev/comparison-only package (oemer or otherwise) is installed into the *same* venv as the production pipeline, rather than an isolated one. | Run `"D:\PiyaNota (Code)\.venv\Scripts\python.exe" -m pip install oemer` into the project's main venv, then `python -c "import torch; torch.from_numpy(__import__('numpy').zeros(1))"` — fails until numpy is re-pinned to 1.26.4. | Minor *(worked around same-session; recurrence risk if dev/comparison tooling keeps sharing the production venv)* | PIYA-112 (module1-pipeline) | fixed | dev-sprint | 2026-09-10 | 2026-09-10 |

| BUG-006 | `oemer` (external OMR baseline, installed for a `compare_omr_baselines.py` SER comparison — not part of PiyaNota's own pipeline) fails on Camera-PrIMuS samples for two independent, sequential reasons, both external to this project's code: (a) the default `onnxruntime-gpu` 1.29.0 rejects oemer's own bundled ONNX model with a shape-inference error (`ConvTranspose` "Attribute pads must not contain negative values") — worked around by pinning `onnxruntime-gpu==1.17.1`; (b) past that fix, oemer's own `staffline_extraction.py` → `bbox.py:125` (`find_lines`) throws `IndexError: invalid index to scalar variable` on all 3/3 samples tried — appears to be oemer's staff-detection logic assuming full multi-system scanned pages, not the tiny single-staff monophonic incipits Camera-PrIMuS (and this project's own staff strips) use. No PiyaNota SER number was produced from this baseline as a result. Not a PiyaNota bug — logged because it blocks the comparison workstream and the decision of whether oemer is worth pursuing further (e.g. retrying against full-page images instead of incipits) is still open. | Into the project `.venv`: `pip install oemer`, pin `onnxruntime-gpu==1.17.1`, then run `compare_omr_baselines.py` against any Camera-PrIMuS sample — fails at the `IndexError` above on every sample tried. | Minor *(external dependency limitation, not a PiyaNota defect; blocks the baseline-comparison research task only, not the shipped pipeline)* | N/A — research/comparison tooling only | open | dev-sprint | 2026-09-10 | 2026-09-10 |

*Migrated from `docs/tickets/module1-pipeline.md` PIYA-121, which was recorded there directly as
an explicit stopgap before this tracker existed — see that file for the full evidence trace;
this row is a summary, not a replacement, so update both if the investigation continues.*
