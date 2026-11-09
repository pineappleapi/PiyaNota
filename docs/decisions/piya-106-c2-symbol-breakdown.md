# PIYA-106 C2 real set: accuracy per symbol (2026-11-08)

Pooled over all 10 test pieces, one row per symbol, no per-piece split. Produced by `training/phase2/symbol_breakdown.py` from the saved raw CRNN predictions (`D:/PiyaNota/data/c2_real_preds/s{1,2}_{pdf,camera}_raw.json`, the same files behind `piya-106-c2-real-results.md`).

**Method.** Each strip's predicted token sequence is aligned to its Arm 1 label (header included, nothing masked) by a Levenshtein backtrace. Every ground-truth token is then counted as correct (same token including its staff-position suffix, so a note is correct only with the right duration class and the right position), substituted, or deleted. "Correct %" = correct / GT count of that symbol. A strip whose prediction is an empty token list counts all its GT tokens as deleted. Four camera strips have no prediction entry at all and are not counted anywhere (821 of 825 scored, 24670 of 24694 GT tokens); the PDF set is complete. Insertions have no GT symbol and are listed by predicted family. PDF and camera are never pooled; seed 1 and seed 2 are shown side by side, not averaged. Strips whose label is excluded from Arm 1 (dropped bars) are not scored. Symbol types with fewer than 30 GT tokens are left out of the type table, but all symbols are in the family table.

**Reading it.** This is label-conditioned and diagnostic: hand-authored ground truth, frozen strips, the 10 test pieces. It is not the SOW end-to-end metric. The overall figure (95.9 / 96.0 PDF, 95.4 / 95.5 camera) is token-level accuracy from this alignment. It is close to, but not the same computation as, the Arm 1 token SER in the main report (it is GT-denominated and also counts insertions as errors, which this overall figure leaves out), so do not substitute one for the other. Counts are tokens, and tokens on the same strip are correlated, so no interval is given.

**What stands out**
- **Clefs, barlines, sharps, flats and rests of quarter, sixteenth, half and whole length are essentially solved** (99 to 100 percent). Clef is 100 percent on every strip, which means the header clef is not an error source here.
- **Notes are 96 percent** (about 434 substitutions of 11807 on PDF). Beamed notes read best (98.3 to 98.6); isolated quarters (about 96), eighths (about 96) and sixteenths (92) read worse.
- **Slurs are the weakest common symbol** (PDF 91.6 / 92.1, camera 88.9 / 89.8), and the errors are almost all deletions (the model omits the slur). Slur ends and starts are similar. Slurs here are ties in the Stage 4 sense, so a deleted slur can split a tied note into two attacks in audio. This was not measured in this report.
- **Eighth rests are 89.1 percent** (53 deletions of 530), against 99.8 percent for quarter rests. Dots are about 94 percent.
- **Fermatas are 56 to 62 percent, but only 16 of them.** Fermatas are out of scope (2026-10-14 ruling), so this row is informational.
- **Layer tokens (`layer.split` and `note.*.l2`) score 0.0 percent on both seeds and both sets.** These are the independent two-voice divisi tokens; see the known-limitation section of `piya-106-c2-real-results.md`. The model never emits them correctly, which is the same finding seen per symbol. They are 289 of 24694 GT tokens, so they depress the overall figure by about 1.2 points.
- **Chord notes are 96 to 98 percent**, so same-rhythm chords are read well, consistent with the A9 result.
- **Camera vs PDF:** the largest drops are slurs (about 3 points), accidental naturals (about 3 points) and chord notes (about 1.5 points); notes, rests and dots are about equal.
- **Seed 1 vs seed 2:** within about one point everywhere except low-count rows (metersign 12 tokens: 83.3 vs 100.0 on PDF, a difference of two tokens).

---

## PDF (raw CRNN, Arm 1 labels, header included)

Strips scored: seed 1 825, seed 2 825 of 825 labelled.

### By symbol family

| Symbol | GT count | s1 correct % | s2 correct % | s1 sub / del | s2 sub / del |
|---|---|---|---|---|---|
| note | 11807 | 96.1 | 96.1 | 434 / 28 | 429 / 27 |
| barline | 3014 | 99.9 | 99.9 | 3 / 1 | 2 / 1 |
| slur | 2914 | 91.6 | 92.1 | 49 / 197 | 62 / 168 |
| accidental | 2328 | 99.3 | 99.3 | 7 / 10 | 9 / 7 |
| rest | 1356 | 94.7 | 94.7 | 9 / 63 | 9 / 63 |
| chordnote | 1326 | 97.9 | 98.1 | 7 / 21 | 3 / 22 |
| dot | 891 | 93.9 | 94.2 | 42 / 12 | 39 / 13 |
| clef | 825 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| layer | 117 | 0.0 | 0.0 | 13 / 104 | 15 / 102 |
| other | 88 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| fermata | 16 | 56.2 | 56.2 | 0 / 7 | 0 / 7 |
| metersign | 12 | 83.3 | 100.0 | 0 / 2 | 0 / 0 |

All symbols: 24694 GT tokens, correct 95.9% (s1) / 96.0% (s2).

Inserted tokens with no GT symbol, by predicted family (s1 / s2): slur 59 / 59, chordnote 28 / 38, accidental 27 / 28, note 20 / 15, fermata 10 / 11, barline 4 / 5, dot 3 / 5.

### By symbol type (GT count at least 30)

| Symbol | GT count | s1 correct % | s2 correct % | s1 sub / del | s2 sub / del |
|---|---|---|---|---|---|
| note.beamed* | 6893 | 98.3 | 98.6 | 111 / 3 | 96 / 2 |
| barline | 3014 | 99.9 | 99.9 | 3 / 1 | 2 / 1 |
| note.quarter | 2477 | 96.3 | 95.9 | 87 / 5 | 99 / 3 |
| slur.start | 1446 | 91.7 | 92.3 | 18 / 102 | 22 / 90 |
| slur.end | 1446 | 92.0 | 92.5 | 27 / 88 | 35 / 73 |
| chordnote | 1326 | 97.9 | 98.1 | 7 / 21 | 3 / 22 |
| accidental.flat | 1135 | 99.5 | 99.6 | 1 / 5 | 1 / 4 |
| note.half | 1052 | 97.2 | 97.2 | 26 / 3 | 23 / 6 |
| accidental.sharp | 924 | 99.8 | 99.9 | 2 / 0 | 1 / 0 |
| dot | 891 | 93.9 | 94.2 | 42 / 12 | 39 / 13 |
| note.eighth | 706 | 95.8 | 95.6 | 29 / 1 | 30 / 1 |
| clef.G | 618 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| rest.eighth | 530 | 89.1 | 89.1 | 5 / 53 | 6 / 52 |
| rest.quarter | 412 | 99.8 | 99.8 | 1 / 0 | 1 / 0 |
| accidental.natural | 263 | 96.6 | 96.2 | 4 / 5 | 7 / 3 |
| rest.sixteenth | 254 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| note.whole | 232 | 98.3 | 98.3 | 3 / 1 | 3 / 1 |
| note.sixteenth | 221 | 92.3 | 92.8 | 17 / 0 | 16 / 0 |
| clef.F | 207 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| note.*.l2 | 172 | 0.0 | 0.0 | 157 / 15 | 158 / 14 |
| layer.split | 117 | 0.0 | 0.0 | 13 / 104 | 15 / 102 |
| rest.whole | 93 | 98.9 | 98.9 | 1 / 0 | 1 / 0 |
| rest.half | 55 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| digit.4 | 54 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |

## CAMERA (raw CRNN, Arm 1 labels, header included)

Strips scored: seed 1 821, seed 2 821 of 825 labelled.

### By symbol family

| Symbol | GT count | s1 correct % | s2 correct % | s1 sub / del | s2 sub / del |
|---|---|---|---|---|---|
| note | 11807 | 96.0 | 96.0 | 437 / 40 | 444 / 31 |
| barline | 3010 | 99.7 | 99.8 | 6 / 2 | 4 / 2 |
| slur | 2914 | 88.9 | 89.8 | 63 / 260 | 68 / 229 |
| accidental | 2312 | 98.8 | 98.8 | 18 / 10 | 20 / 7 |
| rest | 1356 | 94.6 | 94.7 | 9 / 64 | 11 / 61 |
| chordnote | 1326 | 96.5 | 96.2 | 13 / 33 | 11 / 40 |
| dot | 891 | 93.9 | 93.8 | 39 / 15 | 42 / 13 |
| clef | 821 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| layer | 117 | 0.0 | 0.0 | 15 / 102 | 17 / 100 |
| other | 88 | 98.9 | 100.0 | 1 / 0 | 0 / 0 |
| fermata | 16 | 62.5 | 56.2 | 0 / 6 | 0 / 7 |
| metersign | 12 | 83.3 | 91.7 | 1 / 1 | 0 / 1 |

All symbols: 24670 GT tokens, correct 95.4% (s1) / 95.5% (s2).

Inserted tokens with no GT symbol, by predicted family (s1 / s2): slur 57 / 66, accidental 28 / 26, chordnote 27 / 42, note 17 / 18, fermata 10 / 10, barline 1 / 5, dot 1 / 2.

### By symbol type (GT count at least 30)

| Symbol | GT count | s1 correct % | s2 correct % | s1 sub / del | s2 sub / del |
|---|---|---|---|---|---|
| note.beamed* | 6893 | 98.4 | 98.6 | 107 / 4 | 93 / 4 |
| barline | 3010 | 99.7 | 99.8 | 6 / 2 | 4 / 2 |
| note.quarter | 2477 | 95.9 | 95.3 | 94 / 8 | 112 / 5 |
| slur.start | 1446 | 89.1 | 89.6 | 19 / 138 | 25 / 126 |
| slur.end | 1446 | 89.1 | 90.4 | 42 / 115 | 40 / 99 |
| chordnote | 1326 | 96.5 | 96.2 | 13 / 33 | 11 / 40 |
| accidental.flat | 1119 | 99.1 | 99.3 | 4 / 6 | 3 / 5 |
| note.half | 1052 | 96.9 | 97.1 | 30 / 3 | 28 / 2 |
| accidental.sharp | 924 | 99.8 | 99.9 | 2 / 0 | 1 / 0 |
| dot | 891 | 93.9 | 93.8 | 39 / 15 | 42 / 13 |
| note.eighth | 706 | 95.9 | 95.8 | 27 / 2 | 28 / 2 |
| clef.G | 615 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| rest.eighth | 530 | 89.1 | 89.1 | 5 / 53 | 8 / 50 |
| rest.quarter | 412 | 99.8 | 99.8 | 1 / 0 | 1 / 0 |
| accidental.natural | 263 | 93.9 | 93.2 | 12 / 4 | 16 / 2 |
| rest.sixteenth | 254 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| note.whole | 232 | 96.1 | 97.0 | 8 / 1 | 6 / 1 |
| note.sixteenth | 221 | 92.3 | 91.9 | 17 / 0 | 18 / 0 |
| clef.F | 206 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| note.*.l2 | 172 | 0.0 | 0.0 | 150 / 22 | 155 / 17 |
| layer.split | 117 | 0.0 | 0.0 | 15 / 102 | 17 / 100 |
| rest.whole | 93 | 97.8 | 98.9 | 1 / 1 | 1 / 0 |
| rest.half | 55 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
| digit.4 | 54 | 100.0 | 100.0 | 0 / 0 | 0 / 0 |
