# PIYA-106: real camera divisi test set (pre-registration)

Status: DRAFT, 2026-10-19. Written before any photo is collected or scored. Plan:
`docs/superpowers/plans/2026-10-19-divisi-real-world.md` (Tasks 2-3).

## Why

Every A6 gate is synthetic, so it shows an upper bound only (ml-cv-lead, 2026-10-19). A real-world divisi number
needs real phone photos of real SATB pages with divisi, scored once per frozen checkpoint. No such set exists.
Non Nobis Domine has no divisi, and Phase 4 is firewalled for the whole-pipeline evaluation.

## Collection (the user)

- **Pieces:** 8-15 pieces from at least 3 publishers or engravers (for example Novello, Oxford, CPDL engravings,
  local Filipino choral editions). Each piece needs at least 1 page with same-stem divisi. Split-stem pages are
  welcome too, tagged as such.
- **Exclusions:** no Bach chorales, no piece in the Phase 2 training manifest, no Phase 4 piece and no
  `piyanota_dataset` piece. `training/divisi_real_register.py` refuses training-manifest pieces automatically,
  matching on the BWV work number (so "BWV 66.6 Christ lag..." and "BWV 66" are both refused). A piece without a
  BWV number matches only on its exact id, so name pieces by their BWV number where they have one. The
  Phase 4 and `piyanota_dataset` exclusions are the user's check, because the agent never reads those sets.
- **Capture:** phone photos taken the way choir members take them: hand-held, room light, no scanner. Use the same
  capture conditions as Phase 4.
- **Storage:** files go in `data/eval_divisi_real/photos/`, with one row per photo in
  `data/eval_divisi_real/meta.csv`: `piece,publisher,page,gt_kinds`.

## Ground truth (user-verified)

- **Format:** agnostic tokens, one strip per staff. Chord members are written as `chordnote-<pos>` after their
  base note, listed bottom to top, as in training.
- **GT kinds:** each divisi bar is tagged as `same_stem`, `split_same_rhythm` or `split_two_rhythm`. A page lists
  every kind it holds.
- **Who makes it:** an agent may draft the GT. It counts only after the user checks every chord on the page
  against the photo (CLAUDE.md: agent-made GT is diagnostic only).

## Metrics (A3 metrics, unchanged)

- **Per (GT kind, interval bucket):**
  - chordnote recall and precision, with n and Wilson 95% interval;
  - chord-member pitch accuracy;
  - `second_as_sequence`, a chord read as two notes in a row (counted as a miss);
  - confident-wrong reads at confidence ≥ 0.90.
- **Whole page:** token SER and pitch accuracy, with chords on and with chords off (the same checkpoint with
  chordnote tokens suppressed).
- **UNDERPOWERED rule:** a bucket with fewer than 300 real members is reported UNDERPOWERED with its interval,
  never as PASS or FAIL.

## Pass bar (user decision D1, OPEN)

Proposed:
- same-stem chord-member pitch accuracy ≥ 85%, with the Wilson lower bound reported;
- whole-page camera SER with chords on no worse than with chords off.

Until the user rules, results are reported without a verdict.

## Firewall

- The set is TEST-only: it is never used for training, tuning, threshold choice or checkpoint selection.
- **One look per frozen checkpoint.** Every look is logged in this doc (date, checkpoint sha, result).
- **The registry is frozen** (`--freeze`) only after the user signs off the GT. After that, any change to a photo or
  to the metadata makes registration fail.

## Look log

(none)
