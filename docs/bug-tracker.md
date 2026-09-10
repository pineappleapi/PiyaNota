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

| BUG-003 | Cross-system `tick_onset` collision corrupts multi-system SATB audio: Stage 3's `infer_pitch()` resets `tick_onset` to 0 on every strip (once per system), but `stage4_reconstruction.reconstruct_satb()` only *sorted* by `(page_index, sys_idx, tick_onset)` without renumbering `tick_onset` itself, and `stage5_synthesis.synthesize_satb()` groups notes by raw `tick_onset` and derives absolute MIDI time straight from it. Result: system 2 onward plays on top of system 1 instead of after it, on any piece with more than one system — the common case, not an edge case. Fixed by adding `_assign_global_ticks()` in `stage4_reconstruction.py`, run after per-voice sort/slur-resolution and before the existing duration-consistency check: computes one cumulative tick offset per `(page_index, sys_idx)` system boundary (from the max end-tick across all four voices, not per-voice, so a single Stage-3 duration error in one voice doesn't compound into a growing desync between voice tracks) and adds it to every event's `tick_onset` in place. Verified two ways: (1) a synthetic 2-system fixture engineered with a deliberate per-voice duration mismatch, confirming no two events share a `tick_onset` post-fix and confirming `_check_measure_duration_consistency`'s existing mismatch warning still fires unaffected; (2) an end-to-end Stage 4 → Stage 5 smoke test (mocking `MIDIFile` to record `addNote` calls, no soundfont/ffmpeg needed) across 2 pages / 3 systems, confirming strictly monotonic, non-duplicate onset times reach the actual MIDI-timing layer, not just the intermediate event dict. | Build a 2-system (or 2-page), 4-voice event fixture where `tick_onset` resets to 0 per system (matching real Stage 3 output) and run it through `reconstruct_satb()` then `synthesize_satb()`; check for duplicate/non-monotonic onset times in the recorded MIDI notes. Reproduced and fixed via the two scratch test scripts described above (not committed to the repo). | Blocker | PIYA-106 (module1-pipeline) | fixed | dev-sprint | 2026-09-10 | 2026-09-10 |

*Migrated from `docs/tickets/module1-pipeline.md` PIYA-121, which was recorded there directly as
an explicit stopgap before this tracker existed — see that file for the full evidence trace;
this row is a summary, not a replacement, so update both if the investigation continues.*
