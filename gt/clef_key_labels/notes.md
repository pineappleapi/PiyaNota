# Validation set: per-staff clef / key labels

- **Source:** `D:/PiyaNota/data/piyanota_dataset/realphoto_validation_set/`, two pieces only:
  - Dormi, Jesu pg01-09
  - Livin' on a Prayer pg01-10 + pg10_b
- **Not opened:** the test pieces in the same folder (dont_stop_me_now, flashlight, honneur_a_toi).
- **Labels:** `labels.json`, which carries its own schema. Its sha256 is in `labels.sha256`.
- **Coordinate frame:** EXIF-upright pixels, 3024 wide x 4032 tall. The stored JPEGs are 4032x3024 with EXIF orientation 6.
- **Builder:** `crops/build_labels.py`.
- **Overlays:** `crops/overlay/*_ov.jpg`.
- **Tenor clef check:** `crops/livin_tenor_montage.png`.
- These labels are hand-read by a single annotator with no second pass. Diagnostic use only.

## Totals

| Piece | Photos | Systems | Staves | G | G8vb | F | OTHER | Unsure |
|---|---|---|---|---|---|---|---|---|
| Dormi, Jesu | 9 | 17 | 72 | 38 | 17 | 17 | 0 | 0 |
| Livin' on a Prayer | 11 | 29 | 116 | 58 | 29 | 29 | 0 | 1 |
| **All** | 20 | 46 | 188 | 96 | 46 | 46 | 0 | 1 |

- Every staff has 5 lines.
- There are no OTHER clefs, no C clefs and no mid-staff clef changes.
- Livin pg10 and pg10_b are two photos of the same printed page, so 12 of Livin's staves are duplicates. There are 104 unique Livin staves (176 unique overall).
  - **Do not treat pg10 and pg10_b as independent samples.**
  - Keep both photos in the same split.

## Dormi, Jesu

This is a printed scan photographed on a curled page. Pages 3 and 8 curl the most; their bboxes are hand-estimated envelopes (about ±30 px).

### Clefs

- Every Tenor staff is G8vb. The 8 is clearly printed and was checked on a zoomed crop of each one.
- Bass staves are F.
- Soprano, Alto and Solo staves are G.

### Keys (staves by starting key)

- +2: 47
- -2: 13
- -5: 12

### Time signature

3/4 is printed only on pg01 s1 (all 4 staves). No mid-staff time changes.

### Mid-staff key changes (13 entries)

All of them are at a double barline. None prints cancellation naturals; only the new accidentals appear.

| Page / system | Staves | Change | Bar in system (measure) | x-fraction | Note |
|---|---|---|---|---|---|
| pg05 s1 | S, A, T, B | +2 → -2 | 6 (m.66) | ≈ 0.73 | |
| pg06 s2 | Solo, S, A, T, B | -2 → +2 | 5 (m.88) | ≈ 0.50 | "tempo I" |
| pg07 s2 | S, A, T, B | +2 → -5 | 6 (m.105) | ≈ 0.58 | A pencil circle overlaps the new Bass key signature but it is still readable. |

No courtesy key signatures at system ends.

### SATB layout per system

| Page | System 1 | System 2 |
|---|---|---|
| pg01 | S A T B (labels printed) | Solo + S A T B |
| pg02 | Solo + S A T B | S A T B |
| pg03 | S A T B | S A T B |
| pg04 | S A T B | S A T B |
| pg05 | S A T B | S A T B |
| pg06 | S A T B | Solo + S A T B |
| pg07 | Solo + S A T B | S A T B |
| pg08 | S A T B | S A T B |
| pg09 | S A T B (final system; the rest of the page is text) | — |

### Breaks the S/A/T/B top-to-bottom assumption

- Four systems have 5 staves, with a soprano-obligato "Solo" staff above the bracketed SATB: pg01 s2, pg02 s1, pg06 s2 and pg07 s1.
  - A strict group-by-4 in Stage 2 would shift every voice on these pages.
  - pg01 and pg07 have 9 staves per page, which is not divisible by 4.
- Voice labels are printed only on pg01 s1 (full names) and on the obligato staff. Everywhere else the voice comes from the layout.

### Handwriting (pencil; not labelled as print)

- pg01 s2 Bass: circles around naturals.
- pg07 s2: marks on the Soprano bar-1 accidentals, and a circle over the Bass's new key signature.
- pg09 Tenor: a circle around a lyric.

## Livin' on a Prayer

This is MuseScore engraving.

- Pages 1-7 are flat. Their bboxes come from the classical staffline finder plus a 20 px (x) / 25 px (y) margin.
- Pages 8, 9, 10 and 10_b are curled or tilted. Their bboxes are hand-estimated envelopes; pg09 s2 Bass and pg10 s2/s3 use detector values with manual adjustment.

### Clefs

- Every Tenor staff is G8vb. The 8 is small but visible on all 29 Tenor staves; see `crops/livin_tenor_montage.png`, which covers pages 2-10_b, with pg01 checked separately.
- Bass staves are F.
- Soprano and Alto staves are G.

### Keys (staves by starting key)

- -1: 92, covering pg01 through pg09 s2.
- -4: 24, covering pg10 and pg10_b (all 3 systems each).
- The pg10 s2 Bass key was re-checked on a zoomed crop in both photos: it is -4.

### Time signature

4/4 is printed only on pg01 s1.

### Mid-staff changes (all 4 staves of pg09 s2, which starts at m.88; 12 entries)

| Change | Bar in system (measure) | x-fraction |
|---|---|---|
| Time 4/4 → 3/4 | 2 (m.89) | ≈ 0.25 |
| Key -1 → -4 | 3 (m.90) | ≈ 0.42 |
| Time 3/4 → 4/4 | 3 (m.90) | ≈ 0.44 |

- The key change sits at a start-repeat barline (rehearsal I). No cancellation natural is printed.
- The 4/4 is printed right after the new key signature.
- No time signature is printed at the start of the system.

### Not changes

These double bars carry no key or time change:

- pg03 (C)
- pg04 (D/segno)
- pg05 (E/To Coda)
- pg07 (G)
- pg08 (H/D.S. al Coda)
- The end-repeat barline in s2 on both pg10 and pg10_b

### Unsure (1)

- pg09 s1 Soprano: a handwritten pencil natural+flat plus a barline near the end of the staff (x ≈ 0.92) looks like a key change.
- It is annotation, not print, so it is **not** labelled as a change.
- Heavy pencil scribble also covers bars 1-4.

### SATB layout

Every system is 4 staves, S A T B from top to bottom, with printed labels: full names on pg01 s1, and "S./A./T./B." elsewhere. Systems per page:

| Page | Systems | Start measures |
|---|---|---|
| pg01 | 3 | m.1, 9, 13 |
| pg02 | 3 | m.17, 20, 23 |
| pg03 | 3 | m.26, 29, 32 |
| pg04 | 2 | m.36, 40 |
| pg05 | 3 | m.44, 47, 51 |
| pg06 | 3 | m.55, 59, 62 |
| pg07 | 2 | m.65, 69 |
| pg08 | 2 | m.73, 78 |
| pg09 | 2 | m.83, 88 |
| pg10 / pg10_b | 3 | m.92, 96, 99 |

- Nothing in this piece breaks the S/A/T/B assumption.
- The last system on pg10 and pg10_b is short (about 2/3 of the page width).

## Implications for the classifier validation set

- **Class imbalance:**
  - Clefs: G 96, G8vb 46, F 46. There are no OTHER clefs.
  - Keys: only five values occur (+2, -1, -2, -4, -5). The -4 staves are all from one page, photographed twice.
- **Mid-staff changes are rare.** There are 25 entries in total: 17 key and 8 time, across 4 systems. That is too few to measure change detection, only to smoke-test it.

## Flashlight

Added 2026-09-26, after the user approved retiring Flashlight as a test piece and moving it to validation. The "Not opened" line at the top of this file predates that decision; it still holds for dont_stop_me_now and honneur_a_toi, which were not opened.

- **Photos:** `flashlight_pg01.jpg` .. `flashlight_pg08.jpg` (8), all 4032x3024 with EXIF orientation 6, so the same 3024x4032 upright frame.
- **Labels:** `labels_flashlight.json`, which uses the same schema as `labels.json` (only the description and the `voice` text mention Flashlight). Its sha256 is in `labels_flashlight.sha256`. `labels.json` and `labels.sha256` are unchanged.
- **Builder:** `crops/build_labels_flashlight.py`. It reads the schema from `labels.json` but never writes to it.
- **Overlays:** `crops/overlay/flashlight_pg0N_ov.jpg`.
- **Clef checks:** `crops/flashlight/tenor_clef_montage.png` (all 23 Tenor clefs) and `crops/flashlight/upper_clef_montage.png` (all 69 other clefs). The system-start crops are `crops/flashlight/pgNN_sM_start.png`.
- The bboxes are verified on the overlays: 80 come from the classical staffline finder plus the 20/25 px margin, and 12 are manual (±30 px). The manual ones are staves where the finder cut the staff short or missed the clef: the top staff of pg02, pg03, pg05, pg06 and pg08 s1 (all on folded or tilted page corners), pg05 s1 Alto, pg05 s3 Alto, pg07 s1 (all 4) and pg08 s1 Soprano.
- As with the other pieces, these are hand-read by a single annotator with no second pass. Diagnostic use only.

### Totals

| Piece | Photos | Systems | Staves | G | G8vb | F | OTHER | Unsure |
|---|---|---|---|---|---|---|---|---|
| Flashlight | 8 | 23 | 92 | 69 | 23 | 0 | 0 | 0 |

- Every staff has 5 lines. There are no C clefs, no OTHER clefs and **no Bass staff or F clef anywhere**.
- **Duplicate photos:** none. All 8 photos show different printed pages (pg01-08, m.1-56), and their file hashes all differ.

### Clefs

- The Soloist, Soprano and Alto staves are all G. None has an 8, which was checked on the zoomed montage.
- The Tenor staff is G8vb on all 23 systems. The 8 is clear on most of them. It is faint or broken but still visible on pg01 s3, pg03 s2 (the faintest), pg05 s2, pg06 s3 and pg07 s3; those records carry a note.

### Keys (staves by starting key)

- -1: 92, covering every staff on every page.

### Time signature

4/4 is printed only on pg01 s1 (all 4 staves).

### Mid-staff changes

There are none: no clef, key or time changes, and no courtesy signatures.

These look like changes but are not:

- **pg07 s2, start of bar 2 (m.49):** the flats in Soprano, Alto and Tenor are note accidentals (E-flat), not a key signature. Checked on a zoomed crop.
- **pg05 s1:** stacked whole-note dyads look like a bold "8". One is right after the Soprano key signature and one is at bar 2 of the Alto. They are not a time signature.
- **pg01 s1:** the voice names are printed above bar 4, at the end of the "Ah" intro, not at the staff start.

### Unsure

None.

### Voice layout per system

Every system is 4 staves: Soloist, Soprano, Alto, Tenor (8vb), from top to bottom, with no Bass.

- Voice labels are printed only on pg01 s1, above bar 4.
- Everywhere else the voice comes from the layout (`implied_by_layout`).
- The Soloist staff is labelled `voice: "Solo"`, reusing the Dormi Jesu value.

| Page | Systems | Start measures |
|---|---|---|
| pg01 | 3 | m.1, 8, 10 |
| pg02 | 3 | m.12, 14, 17 |
| pg03 | 3 | m.19, 21, 23 |
| pg04 | 3 | m.25, 28, 30 |
| pg05 | 3 | m.33, 35, 37 |
| pg06 | 3 | m.39, 42, 44 |
| pg07 | 3 | m.46, 48, 50 |
| pg08 | 2 | m.52, 54 (final barline) |

System start measures come from the printed measure numbers. For systems with no printed number (pg02 s1, pg03 s1, pg04 s1, pg06 s1, pg07 s1, pg08 s1), the start is inferred from the previous system's bar count.

### Breaks the S/A/T/B top-to-bottom assumption

- The whole piece does. Every system has 4 staves, but they are Solo/S/A/T, not S/A/T/B.
- A strict group-by-4 in Stage 2 would divide the staves correctly (32 or 36 staves per page, 92 in total) but then assign the voices wrongly: Soloist → Soprano, Soprano → Alto, Alto → Tenor, Tenor → Bass. Stage 3 would then treat a treble-8vb Tenor as Bass.

### Handwriting (pencil; not labelled as print)

- There are pencil note names above the Soloist staff on pg06 s3, pg07 s2-s3 and pg08 s1-s2.
- There is a scribble and signature in the pg01 top margin, outside the staves.

## Implications (all three validation pieces)

- **Combined clef counts:** G 165, G8vb 69, F 46, OTHER 0 (280 staves, 268 unique after the Livin pg10/pg10_b duplicate).
- **Keys:** Flashlight adds 92 more -1 staves, so -1 is now 184 of 280.
- **Mid-staff changes:** Flashlight adds no mid-staff changes. The total stays at 25 entries.
