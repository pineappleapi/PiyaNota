# Honneur a Toi ground truth: completion notes

HAND-MADE / PROVISIONAL / single annotator (agent) / not verified by a musician. Diagnostic only; not accuracy evidence.
Frozen before any CRNN or pipeline run. No model or pipeline code was run.

- Source: `D:\PiyaNota\data\piyanota_dataset\honneur_a_toi_pg01.jpg`, `_pg02.jpg`, `_pg03.jpg`. The photos have EXIF orientation 6 and are 3024x4032 after rotation.
- Frozen file: `gt_source.txt`
- sha256: `80219bdc7460b435c02aac74a2b271dcd3efc738c123682b5a994584e1e66b22` (also in `gt_source.sha256`)

## Counts

| Page | Systems | Bars |
|---|---|---|
| 1 | 2 | 1-3, 4-7 |
| 2 | 3 | 8-10, 11-14, 15-18 |
| 3 | 2 | 19-22, 23-28 |

- Total: 7 systems, 28 bars, 28 strips (7 x S/A/T/B).
- Excluded strips: none.
- Uncertain (`?`) items: 6.
- OOV items: 11.
- Phrase slurs: 0. Every arc seen is a same-pitch tie.

## Method

- Each staff was rectified by tracking its 5 lines column by column (`rect.py`). Strips were viewed at 1-4x (`stack.py`).
- Pitch was read by eye against the lines and the ledger guides.
- It was cross-checked with a notehead-blob position tool (`heads.py`), which reports each head's staff step relative to the locally measured lines.
- Where the tool missed a hollow half or whole note, or two readings disagreed, the pitch was taken from printed ASCII intensity profiles.
- These helper scripts in this folder are viewing aids only. None of them is part of the pipeline.

## Per-strip bar-sum check (quarters per bar, 4/4)

All 28 strips pass: every bar sums to 4. This was checked with a small duration parser over `gt_source.txt`.

| Strip | Bars |
|---|---|
| p1s1 S/A/T/B | 4 4 4 |
| p1s2 S/A/T/B | 4 4 4 4 |
| p2s1 S/A/T/B | 4 4 4 |
| p2s2 S/A/T/B | 4 4 4 4 |
| p2s3 S/A/T/B | 4 4 4 4 |
| p3s1 S/A/T/B | 4 4 4 4 |
| p3s2 S/A/T/B | 4 4 4 4 4 4 |

- Bar 1 is a full bar, not a pickup.
- Bars 8 and 22 end on eighth-note pickups ("Hon", "A-"). These are notated inside the full bar.

## Uncertain items (`?`)

1. p2s2 Soprano bar 13: `[ e.:B3? s:C4? ] [ e:B3? e:C4? ]`. These are low ledger notes, and the step between them is hard to resolve on the photo.
2. p3s1 Soprano bar 20: `h:E4?`. The half-note head sits slightly below the bottom line (E4 vs D4).
3. p3s1 Alto bar 19: `s:G4?`. The sixteenth head is smeared by the doubled image on page 3 (G4 vs F4).

## Unresolved bars

None are unresolved for rhythm; every bar sums to 4. Pitch doubts are limited to the 6 `?` items above.

Page 3 has a doubled/ghost image, likely camera shake, and its staff lines look thickened. Page 3 pitches were therefore checked numerically, not only by eye.

## OOV counts by kind

| Kind | Count | Where |
|---|---|---|
| `<OOV:repeat-start>` | 4 | bar 9, all four voices (p2s1) |
| `<OOV:repeat-end>` | 4 | end of bar 25, all four voices (p3s2) |
| `<OOV:volta1>` | 1 | bar 15, Soprano only (bracket printed above the top staff) |
| `<OOV:volta2>` | 1 | bar 26, Soprano only |
| `<OOV:fermata>` | 1 | bar 28, Soprano only (printed only above the top staff) |
| chords/divisi | 0 | |
| grace notes | 0 | |
| D.C./segno | 0 | |

Ties crossing systems: 1 (Soprano E4, bar 7 `~>` to bar 8 `<~`).

## Layout check and deviations from the expected layout

Confirmed as expected:
- Open-score SATB, 4 staves per system.
- Soprano and Alto in G clef, Tenor in treble-8vb (G clef with an 8 below), Bass in F clef.
- Key of 3 sharps on every system.
- Common time on the first system only.
- 2 + 3 + 2 = 7 systems.

Surprises. These are not errors in the expected layout, but they matter for Stage 4 and eval:
- There is a repeat structure: a repeat-start at bar 9 and a repeat-end at the end of bar 25.
  - Volta "1" is drawn at bar 15. Its bracket ends at the bar 15/16 barline and is not continued.
  - Volta "2" is at bar 26.
  - Played order would therefore not be linear. The GT records the printed order only.
- There is a thin double barline at the end of bar 14 (end of p2s2).
- There is a fermata over the final whole notes (bar 28) and a final barline.
- Voice ranges are unusual:
  - The Soprano sits low (A3-E4) in bars 4-13, often at or below the Alto.
  - The Alto crosses above the Soprano in bars 20-21.
  - This is correct as printed; there is no staff-order swap.
- Printed accidentals: `^D4` in p2s1 Soprano (bars 9, 10), p2s2 Alto (bar 14) and p2s3 Tenor (bar 17); `^D3` in p3s1 Bass (bar 21).
- Soprano bar 22 has a double-dotted half (`h..`).
- Alto bar 18 has an eighth rest inside a beam group (`[ s:C4 re s:C4 ]`).
- Page 3's top-left corner has a dark shadow over the margin. It does not cover any notes.

## gt.json: not compiled

`data/eval_dsmn/gt/build_gt.py` cannot compile this file with only path and key edits. It would need these changes:

1. **Key.** `midi_of()` defaults to 1 flat (every B becomes Bb). It needs F, C and G raised by 1 when no accidental is printed. The key-signature token emission (`accidental.flat-L3` / `-L2`) must become three sharps:
   - Treble: `accidental.sharp-L5 accidental.sharp-S3 accidental.sharp-S5`
   - Bass: `accidental.sharp-L4 accidental.sharp-S2 accidental.sharp-S4`
2. **G8 clef (not a key/path change).** `clef = "F" if voice == "Bass" else "G"` ignores `clef:G8`.
   - Parsing the `clef:` token would work, but a decision is needed on the agnostic token for G8. Camera-PrIMuS has no 8vb clef token, so it is probably `clef.G-L2` plus the existing Tenor -12 sounding offset.
   - `step_of`/`BASE_STEP` needs a `G8` entry equal to G.
3. **Dotted and double-dotted durations (real change).**
   - The rest regex `r[whqes]` rejects the dotted rest `rq.` (p2s1 Soprano bar 8).
   - The note regex `([whqes])(\.?)` rejects `h..` (p3s1 Soprano bar 22).
   - Either would trip the `assert`.
4. **Rest inside a beam.** It is harmless: it is just not assigned a beam role. There is no change needed unless beamed rests should get a token.
5. **Paths.** Run it from `data/eval_honneur` with `gt/gt_source.txt`, same as DSMN.
