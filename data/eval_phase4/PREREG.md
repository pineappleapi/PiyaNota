# Phase 4 PREREG, part 1: set, layout rules, GT spec (PIYA-106)

**Status:** 2026-10-15. Reviewed by ml-cv-lead (rulings in section 5) and by choral-conductor (GT format; fixes in
`gt/tools/PHASE4_GT_FORMAT.md` and `project_gt.py`). Part 1 is written before any
Phase 4 strip is cut, before any GT exists and before any model has decoded these pieces. It implements SER-15 plan
Amendment 8 (`docs/decisions/piya-106-ser-15-plan.md`), steps 8.7 (3)-(4). The reporting rules are Amendment 8.6.
Part 2 (scorer version, Stage 3 version, all checkpoint sha256s) is frozen at step 8.7 (6), before the look.

## 1. Set

The 62 `test` pages of 10 pieces in `data/piyanota_dataset/dataset_manifest.csv` (Amendment 8.2). All are camera photos
from one capture session (8.3).

| Piece | Test pages | Subgroup |
|---|---|---|
| `ama_namin` | 5 | clean |
| `salmo_150` | 5 | clean |
| `ale_nasa_langit_na_ba_ako` | 7 | mask-tuned |
| `bituing_walang_ningning` | 5 | mask-tuned |
| `folk_medley` | 10 | mask-tuned |
| `hesus_ng_aking_buhay` | 4 | mask-tuned |
| `panalangin_sa_pagiging_bukas_palad` | 5 | mask-tuned |
| `sanay_wala_nang_wakas` | 5 | mask-tuned |
| `dormi_jesu` | 5 | mask-tuned, ClefKeyNet one-shot (BUG-021) |
| `livin_on_a_prayer` | 11 | mask-tuned, ClefKeyNet one-shot (BUG-021) |

## 2. Layout rules (fixed now, applied by the GT drafter from the photo alone)

- **L1.** Only rows with split `test` are in the set. Rows marked `heldout_scope` (for these pieces, `dormi_jesu`
  pages 1, 2, 6 and 7) are not in it.
- **L2.** A printed system is in scope only if it has exactly 4 vocal staves (S, A, T, B, top to bottom). Any other
  system (5+ staves including a piano or divisi staves, BUG-042; fewer than 4) is written as `<EXCLUDED layout: ...>`
  for each of its staves. A system with any of its 4 staves partly outside the photo or covered is also excluded
  (`<EXCLUDED layout: cropped>`). The drafter decides from the photo, never from Stage 2 output.
- **L3.** Systems are numbered top to bottom over the printed in-scope and excluded systems alike, starting at 1 per
  page. A strip is scored against the GT strip with the same (page, system, voice); Stage 2's labels come from its own
  position rule. A GT strip with no Stage 2 strip is fully missed (all tokens deleted, all notes wrong) in the all-in
  figures; the found-strip figures are reported beside them; an extra Stage 2 strip is reported, not scored. This is the
  `data/eval_fresh/PREREG.md` rule. A Stage 2 failure on a page is a pipeline failure, not an exclusion. Stage 2
  failure pages stay in the all-in figures and are listed per piece in the report.
- **L4 (system map).** Stage 2 numbers its own chunks of 4, so an excluded system above in-scope ones can shift its
  index. At step 8.7 (5), working from the viz tiles only, the drafter records a map from Stage 2 (page, sys) to GT
  (page, sys). It is frozen with the GT, before any decode. Unmapped Stage 2 strips are reported as extra.

## 3. Strips (cut once, step 8.7 (4))

- Stage 1 and Stage 2 run once, one page at a time, as in `data/eval_fresh/PREREG.md`:
  `detect_staff_regions([(page.detect, page_no, page.strip_source)], ...)`, so a page that raises fails alone. The
  page number is the manifest `page` column, not the folder order (`training/run_stage12.py` batches a whole folder and
  numbers by order, so it is not used as is). The small cut script is written in step 8.7 (4) and committed with the
  strip manifest record.
- Record the commit, the sha256 of the cut script, `stage1_preprocessing.py`, `stage2_detection.py` and the YOLO
  weights, the sha256 of each per-page strip manifest and of every strip image, and the list of pages where Stage 2
  raised.
- The cut runs only after the arm freeze commit (c4db961), in a session that does not touch arm code. It prints only
  the list of pages where Stage 2 raised, never per-page staff or strip counts (they leak divisi and piano layout).
- Outputs go under `D:/PiyaNota/datasets/phase4_strips/` (outside the repo). The strip crops and viz tiles are what the
  GT drafter may look at, together with the photos.
- No model is run on these strips before the look. Re-cutting needs an amendment.

## 4. GT

- **Format:** `gt/tools/PHASE4_GT_FORMAT.md`. One `gt/<piece>/gt_source.txt` per piece.
- **Kind tags (Amendment 8.5 names to source syntax):**

  | Amendment 8.5 kind | Source | v1 | v2 |
  |---|---|---|---|
  | `chord` | `<OOV:chord ...>` | `<OOV>` | expanded |
  | `splitstem_same_rhythm` | `<OOV:splitstem ...>` | `<OOV>` | expanded, labels equal to the chord form |
  | `seconds_displaced` | a chord or splitstem with two members one step apart; derived from member steps by the part 2 report code, not tagged | `<OOV>` | expanded |
  | `triplet` | `<OOV:triplet ...>` | `<OOV>` | `<OOV>` (the arm has no `tuplet.3`, freeze section 1) |
  | `two_voice_diffrhythm` | `<OOV:twovoice ...>` | `<OOV>` | `<OOV>` |

- **Projection:** `python gt/tools/project_gt.py gt/<piece>` writes `gt/<piece>/v1/` and `gt/<piece>/v2/`; the scorer
  reads piece `<piece>/v1` or `<piece>/v2` unchanged. The script asserts v1 = v2 outside the expanded spans (tokens and
  events) and refuses any other OOV kind. `--parity` shows that v1 reproduces the committed dev `gt.json` of 4 dev pieces
  (passes as of this draft). Its sha256 is frozen in part 2.
- **Verification:** the user checks every `gt_source.txt` against the photos. Each source is then sha256-frozen in
  `gt/<piece>/gt_source.sha256`. Unverified pieces are diagnostic only (Amendment 8.5) and are listed as such.
- **Firewall (8.4):** drafting happens in a separate session that never edits arm code or config. It works only from
  photos and strip crops, never from a model decode. `project_gt.py` prints validity results and strip counts only. No
  divisi, interval, voice or OOV count of the test GT is computed or shown before the look.

## 5. Scoring rules fixed in review (ml-cv-lead, 2026-10-15)

1. **v1 hyp projection.** The scorer lets one GT `<OOV>` absorb 0-2 predicted tokens (`TOKEN_OOV_SPAN = 2`), and the v1
   `<OOV>` covers a chord's accidentals as well, so a correct arm chord reading (`acc acc note chordnote dot dot`)
   would pay insertions on v1 that Phase 2 and control never pay. Rule: the v1 hyp projection applies to all models,
   after the scorer's slur drop and before alignment. Each maximal hyp run `[accidental*] note chordnote-+ dot*` is
   collapsed to `[last accidental] note [one dot]`. A note with no chordnote is never touched, so the projection is
   the identity for Phase 2 and control; the run log asserts that, with their chordnote count = 0. After alignment,
   any collapsed run whose head note is not absorbed by a GT `<OOV>` wildcard has its removed tokens added back as
   insertions, so arm hallucinations still count on the v1 headline. The rule is code in the scorer, sha256 frozen in
   part 2. The event side is unchanged: one v1 `oov` event absorbs 0-3 predicted events, and the arm emits one per member.
2. **Seconds.** `seconds_displaced` = two members of an expanded chord or splitstem whose sorted steps differ by 1,
   computed by frozen code (sha256 in part 2) and never printed before the look. Splitstem seconds count, reported as
   their own sub-row.
3. **Triplets.** A triplet region's duration letter is its total length (three triplet quarters = `h`), since the v1
   wildcard event takes its length from it. A chord inside a triplet is tagged `triplet`. Disclosed: every triplet of
   3+ heads costs every model at least one token insertion under `TOKEN_OOV_SPAN = 2`. The cost is the same for every
   model, so it is not a model bias.

## 6. Part 2 must freeze

The scorer version with the v1 hyp projection, the seconds code, the found-strip definition, the confident-wrong
threshold (0.90, freeze doc section 7), the Stage 3 version, `project_gt.py`, and every checkpoint sha256.
