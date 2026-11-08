# PIYA-106 C2 real set: symbol confusion (2026-11-08)

Pooled over all 10 test pieces; PDF and camera separate; seeds shown as columns. Produced by `training/phase2/symbol_confusion.py` (same alignment as `symbol_breakdown.py`). Symbol type = token without the staff-position suffix, so a note at the wrong staff position is reported as "same type, wrong position", not as a type confusion. The script also writes the full matrices (all types, all pairs) as CSV. The `(inserted)` rows are tokens the model added with no GT symbol; their last column is the total inserted count, not a GT total. Diagnostic only: hand-authored GT.

## PDF: what each ground-truth symbol is mistaken for

Pairs with at least 5 occurrences in either seed, most frequent first (seed 1 order). Rows are GT type, columns the model's reading; '(deleted)' = model omitted it.

| GT symbol | Model read | s1 | s2 | GT total |
|---|---|---|---|---|
| layer.split | (deleted) | 104 | 102 | 117 |
| slur.start | (deleted) | 102 | 90 | 1446 |
| slur.end | (deleted) | 88 | 73 | 1446 |
| note.quarter | same type, wrong position | 67 | 65 | 2477 |
| note.half.l2 | note.half | 56 | 56 | 81 |
| rest.eighth | (deleted) | 53 | 52 | 530 |
| note.quarter.l2 | chordnote | 36 | 32 | 60 |
| (inserted) | slur.end | 31 | 25 | 151 |
| (inserted) | chordnote | 28 | 38 | 151 |
| (inserted) | slur.start | 27 | 33 | 151 |
| dot | same type, wrong position | 24 | 27 | 891 |
| chordnote | (deleted) | 21 | 22 | 1326 |
| (inserted) | accidental.flat | 21 | 23 | 151 |
| note.half.l2 | chordnote | 14 | 13 | 81 |
| note.beamedLeft1 | chordnote | 13 | 7 | 2159 |
| note.eighth | note.beamedRight1 | 13 | 13 | 706 |
| note.quarter.l2 | note.quarter | 13 | 18 | 60 |
| dot | (deleted) | 12 | 13 | 891 |
| note.quarter | note.half | 11 | 11 | 2477 |
| note.beamedBoth2 | same type, wrong position | 11 | 4 | 753 |
| note.sixteenth | note.beamedLeft2 | 11 | 11 | 221 |
| slur.start | same type, wrong position | 10 | 12 | 1446 |
| rest.quarter.l2 | (deleted) | 10 | 11 | 12 |
| note.half | same type, wrong position | 10 | 10 | 1052 |
| (inserted) | fermata.above | 10 | 11 | 151 |
| dot | chordnote | 9 | 7 | 891 |
| note.beamedRight1.l2 | chordnote | 9 | 7 | 15 |
| fermata.above | (deleted) | 7 | 7 | 16 |
| (inserted) | note.beamedLeft1-S | 7 | 0 | 151 |
| note.beamedRight1 | same type, wrong position | 6 | 3 | 2259 |
| note.quarter | chordnote | 6 | 12 | 2477 |
| slur.end | same type, wrong position | 6 | 12 | 1446 |
| note.half.l2 | dot | 6 | 8 | 81 |
| slur.end | chordnote | 6 | 5 | 1446 |
| note.half | chordnote | 6 | 7 | 1052 |
| note.beamedLeft1 | same type, wrong position | 5 | 9 | 2159 |
| layer.split | note.half | 5 | 4 | 117 |
| note.beamedLeft1 | note.quarter | 5 | 4 | 2159 |
| chordnote | same type, wrong position | 5 | 3 | 1326 |
| accidental.flat | (deleted) | 5 | 4 | 1135 |
| note.eighth | note.beamedLeft2 | 5 | 5 | 706 |
| note.beamedLeft1.l2 | chordnote | 5 | 5 | 11 |
| note.quarter.l2 | dot | 5 | 4 | 60 |
| note.whole.l2 | note.whole | 5 | 5 | 12 |
| note.quarter | (deleted) | 5 | 3 | 2477 |
| note.beamedLeft2 | same type, wrong position | 5 | 4 | 709 |
| accidental.natural | (deleted) | 5 | 3 | 263 |
| note.whole.l2-S | note.beamedBoth1-S | 5 | 4 | 6 |
| note.whole.l2 | (deleted) | 5 | 5 | 12 |
| note.beamedLeft1.l2 | note.beamedLeft1 | 5 | 4 | 11 |
| note.eighth.l2 | note.eighth | 5 | 2 | 9 |
| (inserted) | barline | 4 | 5 | 151 |
| note.half | (deleted) | 3 | 6 | 1052 |
| (inserted) | dot | 3 | 5 | 151 |
| (inserted) | note.quarter | 3 | 6 | 151 |

## CAMERA: what each ground-truth symbol is mistaken for

Pairs with at least 5 occurrences in either seed, most frequent first (seed 1 order). Rows are GT type, columns the model's reading; '(deleted)' = model omitted it.

| GT symbol | Model read | s1 | s2 | GT total |
|---|---|---|---|---|
| slur.start | (deleted) | 138 | 126 | 1446 |
| slur.end | (deleted) | 115 | 99 | 1446 |
| layer.split | (deleted) | 102 | 100 | 117 |
| note.quarter | same type, wrong position | 59 | 58 | 2477 |
| note.half.l2 | note.half | 55 | 53 | 81 |
| rest.eighth | (deleted) | 53 | 50 | 530 |
| note.quarter.l2 | chordnote | 36 | 32 | 60 |
| chordnote | (deleted) | 33 | 40 | 1326 |
| (inserted) | slur.start | 29 | 39 | 141 |
| (inserted) | chordnote | 27 | 42 | 141 |
| (inserted) | slur.end | 27 | 26 | 141 |
| (inserted) | accidental.flat | 22 | 22 | 141 |
| dot | same type, wrong position | 20 | 23 | 891 |
| note.quarter | note.half | 16 | 17 | 2477 |
| dot | (deleted) | 15 | 13 | 891 |
| slur.end | same type, wrong position | 15 | 11 | 1446 |
| note.quarter.l2 | note.quarter | 15 | 15 | 60 |
| note.half.l2 | chordnote | 15 | 13 | 81 |
| note.eighth | note.beamedRight1 | 13 | 13 | 706 |
| note.half | same type, wrong position | 11 | 9 | 1052 |
| note.sixteenth | note.beamedLeft2 | 11 | 11 | 221 |
| rest.quarter.l2 | (deleted) | 10 | 11 | 12 |
| accidental.natural | accidental.sharp | 10 | 13 | 263 |
| (inserted) | fermata.above | 10 | 10 | 141 |
| note.beamedLeft1 | chordnote | 9 | 5 | 2159 |
| note.beamedRight1.l2 | chordnote | 9 | 6 | 15 |
| slur.start | same type, wrong position | 8 | 7 | 1446 |
| note.quarter | (deleted) | 8 | 5 | 2477 |
| dot | chordnote | 8 | 8 | 891 |
| layer.split | note.half | 7 | 7 | 117 |
| note.beamedRight1 | same type, wrong position | 7 | 6 | 2259 |
| note.quarter | chordnote | 7 | 10 | 2477 |
| note.beamedBoth2 | same type, wrong position | 7 | 4 | 753 |
| note.whole.l2 | (deleted) | 7 | 5 | 12 |
| accidental.flat | (deleted) | 6 | 5 | 1119 |
| fermata.above | (deleted) | 6 | 7 | 16 |
| slur.end | chordnote | 6 | 8 | 1446 |
| slur.end | accidental.natural | 6 | 6 | 1446 |
| chordnote | same type, wrong position | 5 | 6 | 1326 |
| note.beamedLeft1 | same type, wrong position | 5 | 3 | 2159 |
| note.half.l2 | (deleted) | 5 | 4 | 81 |
| note.beamedLeft1.l2 | chordnote | 5 | 6 | 11 |
| note.whole | chordnote | 5 | 3 | 232 |
| note.half.l2 | dot | 5 | 9 | 81 |
| note.sixteenth | note.eighth | 5 | 5 | 221 |
| dot | note.quarter | 5 | 3 | 891 |
| note.half | chordnote | 5 | 8 | 1052 |
| note.beamedLeft1.l2 | note.beamedLeft1 | 5 | 4 | 11 |
| note.eighth.l2 | note.eighth | 5 | 1 | 9 |
| note.quarter | note.beamedRight1 | 4 | 8 | 2477 |
| note.quarter.l2 | (deleted) | 4 | 5 | 60 |
| note.quarter | note.beamedLeft1 | 2 | 6 | 2477 |
| (inserted) | note.quarter | 2 | 5 | 141 |
| (inserted) | barline | 1 | 5 | 141 |
| note.eighth.l2 | chordnote | 1 | 5 | 9 |


# Note-only confusion matrices

Rows are the note type in the ground truth, columns what the model said. Bold diagonal = correct (right type and right staff position). "bm" = beamed (Left/Right/Both = beam position, 1/2 = beam level). "wrong position" = right note type, wrong line or space on the staff. "layer note (.l2)" = the divisi second-voice version of any note; its row pools all .l2 note types (about 210 tokens). "other" = the model said some non-note symbol (dot, slur, accidental and so on). Rows sum to GT total.

### PDF seed 1

| GT \ model said | quarter | half | whole | eighth | sixteenth | bmLeft1 | bmRight1 | bmBoth1 | bmLeft2 | bmRight2 | bmBoth2 | chordnote | layer note (.l2) | wrong position | (deleted) | other | GT total | % right |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quarter | **2385** | 11 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 6 | 0 | 67 | 5 | 0 | 2477 | 96.3 |
| half | 2 | **1023** | 1 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6 | 0 | 10 | 3 | 4 | 1052 | 97.2 |
| whole | 0 | 0 | **228** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 1 | 232 | 98.3 |
| eighth | 4 | 0 | 0 | **676** | 0 | 2 | 13 | 0 | 5 | 0 | 0 | 0 | 0 | 2 | 1 | 3 | 706 | 95.8 |
| sixteenth | 0 | 0 | 0 | 3 | **204** | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 221 | 92.3 |
| bmLeft1 | 5 | 0 | 0 | 0 | 0 | **2133** | 1 | 1 | 0 | 0 | 0 | 13 | 0 | 5 | 0 | 1 | 2159 | 98.8 |
| bmRight1 | 2 | 0 | 0 | 1 | 0 | 0 | **2240** | 1 | 0 | 0 | 0 | 2 | 0 | 6 | 2 | 5 | 2259 | 99.2 |
| bmBoth1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **321** | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 322 | 99.7 |
| bmLeft2 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | **701** | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 709 | 98.9 |
| bmRight2 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | **597** | 1 | 0 | 0 | 1 | 1 | 0 | 604 | 98.8 |
| bmBoth2 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 1 | 0 | **738** | 0 | 0 | 11 | 0 | 0 | 753 | 98.0 |
| layer note (.l2) | 13 | 56 | 5 | 5 | 0 | 7 | 3 | 1 | 3 | 2 | 3 | 71 | 0 | 0 | 15 | 26 | 210 | 0.0 |

### PDF seed 2

| GT \ model said | quarter | half | whole | eighth | sixteenth | bmLeft1 | bmRight1 | bmBoth1 | bmLeft2 | bmRight2 | bmBoth2 | chordnote | layer note (.l2) | wrong position | (deleted) | other | GT total | % right |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quarter | **2375** | 11 | 0 | 0 | 0 | 3 | 3 | 3 | 0 | 0 | 0 | 12 | 0 | 65 | 3 | 2 | 2477 | 95.9 |
| half | 2 | **1023** | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 7 | 0 | 10 | 6 | 2 | 1052 | 97.2 |
| whole | 0 | 0 | **228** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 1 | 1 | 232 | 98.3 |
| eighth | 2 | 0 | 0 | **675** | 0 | 4 | 13 | 0 | 5 | 0 | 0 | 2 | 0 | 3 | 1 | 1 | 706 | 95.6 |
| sixteenth | 0 | 0 | 0 | 3 | **205** | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 221 | 92.8 |
| bmLeft1 | 4 | 0 | 0 | 0 | 0 | **2136** | 1 | 1 | 1 | 0 | 0 | 7 | 0 | 9 | 0 | 0 | 2159 | 98.9 |
| bmRight1 | 4 | 0 | 0 | 1 | 0 | 0 | **2241** | 1 | 0 | 0 | 0 | 2 | 0 | 3 | 1 | 6 | 2259 | 99.2 |
| bmBoth1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **321** | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 322 | 99.7 |
| bmLeft2 | 0 | 0 | 0 | 0 | 1 | 2 | 0 | 0 | **701** | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 709 | 98.9 |
| bmRight2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | **600** | 1 | 0 | 0 | 0 | 1 | 0 | 604 | 99.3 |
| bmBoth2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | **747** | 1 | 0 | 4 | 0 | 0 | 753 | 99.2 |
| layer note (.l2) | 18 | 56 | 5 | 3 | 0 | 5 | 4 | 2 | 4 | 2 | 3 | 65 | 0 | 0 | 14 | 29 | 210 | 0.0 |

### CAMERA seed 1

| GT \ model said | quarter | half | whole | eighth | sixteenth | bmLeft1 | bmRight1 | bmBoth1 | bmLeft2 | bmRight2 | bmBoth2 | chordnote | layer note (.l2) | wrong position | (deleted) | other | GT total | % right |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quarter | **2375** | 16 | 0 | 0 | 0 | 2 | 4 | 2 | 0 | 0 | 0 | 7 | 0 | 59 | 8 | 4 | 2477 | 95.9 |
| half | 2 | **1019** | 1 | 1 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 11 | 3 | 7 | 1052 | 96.9 |
| whole | 0 | 2 | **223** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 0 | 1 | 1 | 0 | 232 | 96.1 |
| eighth | 1 | 0 | 0 | **677** | 0 | 1 | 13 | 0 | 1 | 0 | 0 | 2 | 0 | 1 | 2 | 8 | 706 | 95.9 |
| sixteenth | 0 | 0 | 0 | 5 | **204** | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 221 | 92.3 |
| bmLeft1 | 3 | 1 | 0 | 0 | 0 | **2136** | 2 | 2 | 1 | 0 | 0 | 9 | 0 | 5 | 0 | 0 | 2159 | 98.9 |
| bmRight1 | 2 | 0 | 0 | 1 | 0 | 0 | **2238** | 0 | 0 | 0 | 1 | 1 | 0 | 7 | 1 | 8 | 2259 | 99.1 |
| bmBoth1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **321** | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 322 | 99.7 |
| bmLeft2 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | **699** | 0 | 0 | 0 | 0 | 4 | 2 | 2 | 709 | 98.6 |
| bmRight2 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | **598** | 1 | 0 | 0 | 1 | 1 | 0 | 604 | 99.0 |
| bmBoth2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | **741** | 0 | 0 | 7 | 0 | 2 | 753 | 98.4 |
| layer note (.l2) | 15 | 55 | 4 | 5 | 0 | 6 | 2 | 0 | 3 | 2 | 3 | 71 | 0 | 0 | 22 | 22 | 210 | 0.0 |

### CAMERA seed 2

| GT \ model said | quarter | half | whole | eighth | sixteenth | bmLeft1 | bmRight1 | bmBoth1 | bmLeft2 | bmRight2 | bmBoth2 | chordnote | layer note (.l2) | wrong position | (deleted) | other | GT total | % right |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quarter | **2360** | 17 | 0 | 0 | 0 | 6 | 8 | 4 | 0 | 0 | 0 | 10 | 0 | 58 | 5 | 9 | 2477 | 95.3 |
| half | 2 | **1022** | 1 | 1 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 8 | 0 | 9 | 2 | 4 | 1052 | 97.1 |
| whole | 0 | 1 | **225** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 1 | 1 | 232 | 97.0 |
| eighth | 2 | 0 | 0 | **676** | 2 | 0 | 13 | 0 | 2 | 0 | 0 | 2 | 0 | 4 | 2 | 3 | 706 | 95.8 |
| sixteenth | 0 | 0 | 0 | 5 | **203** | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 221 | 91.9 |
| bmLeft1 | 2 | 0 | 0 | 0 | 0 | **2143** | 2 | 1 | 2 | 0 | 0 | 5 | 0 | 3 | 0 | 1 | 2159 | 99.3 |
| bmRight1 | 2 | 0 | 0 | 1 | 0 | 0 | **2237** | 2 | 0 | 2 | 0 | 3 | 0 | 6 | 0 | 6 | 2259 | 99.0 |
| bmBoth1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **321** | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 322 | 99.7 |
| bmLeft2 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | **701** | 0 | 1 | 1 | 0 | 2 | 1 | 1 | 709 | 98.9 |
| bmRight2 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | **599** | 1 | 0 | 0 | 0 | 1 | 0 | 604 | 99.2 |
| bmBoth2 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | **746** | 1 | 0 | 4 | 0 | 0 | 753 | 99.1 |
| layer note (.l2) | 15 | 54 | 4 | 2 | 0 | 6 | 4 | 2 | 5 | 2 | 3 | 65 | 0 | 0 | 19 | 29 | 210 | 0.0 |


# One-vs-rest 2x2 confusion per symbol (TP / FN / FP / TN)

For each symbol X: positive = "this ground-truth token is X". TP = X read as X (staff position ignored; the wrong-position count is shown separately and is inside TP). FN = X omitted or read as another symbol. FP = another symbol read as X, plus X tokens the model inserted. TN = all other ground-truth tokens not read as X. TN ignores insertions of other symbols, so the four cells do not sum exactly to the token total. Produced by `training/phase2/symbol_binary_matrix.py`. Symbol types with fewer than 30 GT tokens are left out.

Known labelling quirk in `symbol_breakdown.py`: its `note.beamed*` row also contains the 38 beamed divisi-layer tokens (the beamed rule is checked before the layer rule), so its `note.*.l2` row shows 172 instead of 210. The tables here separate them correctly (210).

## PDF

| Symbol | GT | s1 TP | s1 FN | s1 FP | s1 TN | s2 TP | s2 FN | s2 FP | s2 TN | wrong pos. s1 / s2 (inside TP) |
|---|---|---|---|---|---|---|---|---|---|---|
| barline | 3014 | 3010 | 4 | 7 | 21677 | 3011 | 3 | 9 | 21676 | 0 / 0 |
| note.quarter | 2477 | 2452 | 25 | 37 | 22183 | 2440 | 37 | 42 | 22181 | 67 / 65 |
| note.beamedRight1 | 2259 | 2246 | 13 | 31 | 22404 | 2244 | 15 | 29 | 22406 | 6 / 3 |
| note.beamedLeft1 | 2159 | 2138 | 21 | 16 | 22521 | 2145 | 14 | 18 | 22519 | 5 / 9 |
| slur.start | 1446 | 1336 | 110 | 33 | 23242 | 1346 | 100 | 42 | 23239 | 10 / 12 |
| slur.end | 1446 | 1337 | 109 | 45 | 23234 | 1350 | 96 | 39 | 23234 | 6 / 12 |
| chordnote | 1326 | 1303 | 23 | 147 | 23249 | 1304 | 22 | 154 | 23252 | 5 / 3 |
| accidental.flat | 1135 | 1129 | 6 | 21 | 23559 | 1130 | 5 | 23 | 23559 | 0 / 0 |
| note.half | 1052 | 1033 | 19 | 76 | 23568 | 1033 | 19 | 78 | 23565 | 10 / 10 |
| accidental.sharp | 924 | 924 | 0 | 7 | 23766 | 924 | 0 | 6 | 23767 | 2 / 1 |
| dot | 891 | 861 | 30 | 23 | 23783 | 866 | 25 | 25 | 23783 | 24 / 27 |
| note.beamedBoth2 | 753 | 749 | 4 | 6 | 23937 | 751 | 2 | 5 | 23937 | 11 / 4 |
| note.beamedLeft2 | 709 | 706 | 3 | 21 | 23965 | 705 | 4 | 23 | 23964 | 5 / 4 |
| note.eighth | 706 | 678 | 28 | 10 | 23978 | 678 | 28 | 10 | 23979 | 2 / 3 |
| clef.G | 618 | 618 | 0 | 0 | 24076 | 618 | 0 | 0 | 24076 | 0 / 0 |
| note.beamedRight2 | 604 | 598 | 6 | 3 | 24087 | 600 | 4 | 3 | 24087 | 1 / 0 |
| rest.eighth | 530 | 472 | 58 | 1 | 24163 | 472 | 58 | 1 | 24163 | 0 / 0 |
| rest.quarter | 412 | 411 | 1 | 0 | 24282 | 411 | 1 | 0 | 24282 | 0 / 0 |
| note.beamedBoth1 | 322 | 322 | 0 | 6 | 24366 | 321 | 1 | 8 | 24364 | 1 / 0 |
| accidental.natural | 263 | 254 | 9 | 9 | 24425 | 254 | 9 | 7 | 24426 | 0 / 1 |
| rest.sixteenth | 254 | 254 | 0 | 0 | 24440 | 254 | 0 | 1 | 24439 | 0 / 0 |
| note.whole | 232 | 229 | 3 | 13 | 24451 | 228 | 4 | 13 | 24450 | 1 / 0 |
| note.sixteenth | 221 | 206 | 15 | 1 | 24472 | 205 | 16 | 1 | 24472 | 2 / 0 |
| note.*.l2 | 210 | 0 | 210 | 0 | 24484 | 0 | 210 | 0 | 24484 | 0 / 0 |
| clef.F | 207 | 207 | 0 | 0 | 24487 | 207 | 0 | 0 | 24487 | 0 / 0 |
| layer.split | 117 | 0 | 117 | 0 | 24577 | 0 | 117 | 0 | 24577 | 0 / 0 |
| rest.whole | 93 | 92 | 1 | 0 | 24601 | 92 | 1 | 0 | 24601 | 0 / 0 |
| rest.half | 55 | 55 | 0 | 1 | 24638 | 55 | 0 | 1 | 24638 | 0 / 0 |
| digit.4 | 54 | 54 | 0 | 0 | 24640 | 54 | 0 | 0 | 24640 | 0 / 0 |

## CAMERA

| Symbol | GT | s1 TP | s1 FN | s1 FP | s1 TN | s2 TP | s2 FN | s2 FP | s2 TN | wrong pos. s1 / s2 (inside TP) |
|---|---|---|---|---|---|---|---|---|---|---|
| barline | 3010 | 3002 | 8 | 10 | 21651 | 3004 | 6 | 11 | 21654 | 0 / 0 |
| note.quarter | 2477 | 2434 | 43 | 35 | 22160 | 2418 | 59 | 38 | 22160 | 59 / 58 |
| note.beamedRight1 | 2259 | 2245 | 14 | 33 | 22379 | 2243 | 16 | 39 | 22374 | 7 / 6 |
| note.beamedLeft1 | 2159 | 2141 | 18 | 14 | 22499 | 2146 | 13 | 18 | 22494 | 5 / 3 |
| slur.start | 1446 | 1297 | 149 | 36 | 23217 | 1302 | 144 | 53 | 23210 | 8 / 7 |
| slur.end | 1446 | 1304 | 142 | 44 | 23207 | 1318 | 128 | 44 | 23206 | 15 / 11 |
| chordnote | 1326 | 1285 | 41 | 148 | 23223 | 1281 | 45 | 163 | 23223 | 5 / 6 |
| accidental.flat | 1119 | 1111 | 8 | 22 | 23551 | 1113 | 6 | 25 | 23548 | 2 / 2 |
| note.half | 1052 | 1030 | 22 | 88 | 23531 | 1031 | 21 | 88 | 23532 | 11 / 9 |
| accidental.sharp | 924 | 923 | 1 | 12 | 23736 | 924 | 0 | 15 | 23733 | 1 / 1 |
| dot | 891 | 857 | 34 | 21 | 23759 | 859 | 32 | 27 | 23754 | 20 / 23 |
| note.beamedBoth2 | 753 | 748 | 5 | 8 | 23912 | 750 | 3 | 8 | 23912 | 7 / 4 |
| note.beamedLeft2 | 709 | 703 | 6 | 22 | 23941 | 703 | 6 | 29 | 23934 | 4 / 2 |
| note.eighth | 706 | 678 | 28 | 14 | 23950 | 680 | 26 | 12 | 23953 | 1 / 4 |
| clef.G | 615 | 615 | 0 | 0 | 24055 | 615 | 0 | 0 | 24055 | 0 / 0 |
| note.beamedRight2 | 604 | 599 | 5 | 4 | 24062 | 599 | 5 | 5 | 24061 | 1 / 0 |
| rest.eighth | 530 | 472 | 58 | 1 | 24139 | 472 | 58 | 0 | 24140 | 0 / 0 |
| rest.quarter | 412 | 411 | 1 | 0 | 24258 | 411 | 1 | 0 | 24258 | 0 / 0 |
| note.beamedBoth1 | 322 | 322 | 0 | 6 | 24342 | 321 | 1 | 9 | 24339 | 1 / 0 |
| accidental.natural | 263 | 247 | 16 | 15 | 24396 | 245 | 18 | 11 | 24398 | 0 / 0 |
| rest.sixteenth | 254 | 254 | 0 | 0 | 24416 | 254 | 0 | 0 | 24416 | 0 / 0 |
| note.whole | 232 | 224 | 8 | 14 | 24425 | 226 | 6 | 15 | 24423 | 1 / 1 |
| note.sixteenth | 221 | 204 | 17 | 1 | 24448 | 203 | 18 | 3 | 24446 | 0 / 0 |
| note.*.l2 | 210 | 0 | 210 | 0 | 24460 | 0 | 210 | 0 | 24460 | 0 / 0 |
| clef.F | 206 | 206 | 0 | 0 | 24464 | 206 | 0 | 0 | 24464 | 0 / 0 |
| layer.split | 117 | 0 | 117 | 0 | 24553 | 0 | 117 | 0 | 24553 | 0 / 0 |
| rest.whole | 93 | 91 | 2 | 0 | 24577 | 92 | 1 | 0 | 24577 | 0 / 0 |
| rest.half | 55 | 55 | 0 | 1 | 24614 | 55 | 0 | 1 | 24614 | 0 / 0 |
| digit.4 | 54 | 54 | 0 | 0 | 24616 | 54 | 0 | 1 | 24615 | 0 / 0 |
