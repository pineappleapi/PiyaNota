# Non Nobis Domine ground truth: completion notes

Transcribed by an agent, then **verified by the project owner (user) on 2026-09-28**. The user lifted the CLAUDE.md
"diagnostic only" rule for this piece: results measured against it may be reported as "hand-transcribed and verified by
the author". The `piyanota_dataset` photos stay TEST-only. The frozen `gt_source.txt` header still says "provisional /
diagnostic only"; it is left byte-identical so the sha256 below holds.
Frozen 2026-09-28 before any CRNN, ClefKeyNet or Stage 3 run on these photos. The only earlier pipeline contact was the
Stage 1 mask audit (2026-09-25, no pitch output).

**Verified 2026-09-28 by the project owner (user), who reviewed the transcription and reported it correct.** No edit to
`gt_source.txt` followed, so the frozen sha256 below is unchanged.

- Source: `D:\PiyaNota\data\piyanota_dataset\non_nobis_domine_pg01.jpg` .. `_pg04.jpg` (phone photos, 3024x4032 after EXIF rotation).
- Frozen file: `gt_source.txt`, sha256 `d163dc1cbc3e1db14777cb1dd26b2130d9d4c4ac3418252673ebced203751763` (also in `gt_source.sha256`).
- Build: `python build_gt.py . --common-time` (run from this folder) -> `gt.json` + per-strip `pageNNN_sysNN_Voice.txt`.

## Counts

| Page | Systems | Bars (printed numbers) |
|---|---|---|
| 1 | 2 | 1-6, 7-12 |
| 2 | 2 | 13-19, 20-24 |
| 3 | 3 | 25-30, 31-36, 37-40 |
| 4 | 2 | 41-46, 47-53 |

- 9 systems, 53 bars, 38 strips: 36 scored (9 x S/A/T/B) + 2 excluded (page 4 "Soprano Solo" staff).
- Notes 275, rests 43, OOV items 133 (mostly two-note chords / divisi, which the CRNN vocabulary cannot represent),
  uncertain (`?`) items 9, phrase slurs 55 (counted, not in the token reference).
- Key 1 flat, common time throughout. Tenor is treble-8vb; Tenor pitches are recorded WRITTEN (sounding = written - 12,
  which `gt.json` `pitch` already applies).

## Bar-sum check

Every bar of every scored strip sums to 1920 ticks (4/4), except bar 40 (see below), which builds to 0 by design.

## Things a scorer must know

- **Chord-heavy piece.** 133 OOV items: a token-level comparison has to skip or separately score OOV spans; pitch
  accuracy on single-note events only is a much smaller set than the note count suggests.
- **Bar 40 (p3s3, last bar)** is "sung as spoken": stemless heads, unmetered, fermata. Recorded as a zero-duration
  `<OOV:spoken-unmetered ...>` item; its pitches are approximate and must not be scored.
- **Page 4 has five staves per system** (a "Soprano Solo" staff above the choir S/A/T/B), plus an "*optional" solo
  ossia (bars 51-53) between the systems. The solo staves are recorded as `EXCLUDED` strips (`voice` = `SopranoSolo`).
  Stage 2 assumes exactly 4 staves per system, so the pipeline's voice assignment on page 4 is expected to be wrong
  (solo read as Soprano, everything shifted down one voice, or a divisible-by-4 error). Score page 4 only after
  checking which detected staff maps to which GT strip; report it separately from pages 1-3.
- Page 4 bar 49 Tenor has a printed natural (B natural, `=B4`).
- Not transcribed anywhere: tenuto marks, dynamics, hairpins, tempo text ("poco rall."), lyrics, fermatas (fermatas are
  mentioned only inside OOV descriptions).

## Method

Staff lines measured per region (`lines.py`); pitches read by eye on line/space overlays (`overlay.py`, red = lines,
green = spaces) at 3-8x; filled heads cross-checked with a blob tool (`heads.py`, reports staff step against locally
measured lines; misses most hollow heads, so hollow halves/wholes were read on zoomed overlays). Ambiguous hollow chords
were checked against tie continuity and harmonic plausibility. These scripts are viewing aids only, not pipeline code.

## Leakage check (2026-09-28)

- ClefKeyNet (`train_clef_key.py`) trains on synthetic renders only and refuses any `piyanota_dataset` path; its spent
  real-val set is Dormi / Livin' / Flashlight, not Non Nobis.
- CRNN fine-tuning (`finetuned_font_seed{1,2}.pt`) used Camera-PrIMuS re-renders only.
- `training/step3_mask_split.json` lists `non_nobis_domine` as **frozen** (not in the mask tuning set).
