# Handog ground truth: completion notes

HAND-MADE / PROVISIONAL / single annotator (agent) / not verified by a musician. Diagnostic only; not accuracy evidence.
Written 2026-09-28 before any pipeline run on these photos. The user asked for the test to proceed without their check.

- Source: `D:\PiyaNota\data\piyanota_dataset\handog_pg01.jpg` to `_pg14.jpg`.
- Frozen file: `gt_source.txt`
- sha256: `1c793588af5dd4f07ccd5c5c5f682a7610a1e9361fb13041477bfcc403077b33` (also in `gt_source.sha256`)
- **Split status: `handog` is in the Stage 1 mask TUNING set (`training/step3_mask_split.json`).** Stage 1's
  non-staff-ink mask thresholds were tuned with these photos in view, so Stage 1/2 results on Handog are not a clean
  held-out measurement. Any report must say so.

## Counts

- Transcribed: 13 four-staff (S/A/T/B) systems = 52 strips. Every bar compiles to 1920 ticks (4/4, common time).
  - p1s1, p1s2, p2s1, p2s2, p3s1 (bars 1-15); p10s2 (49-51); p11s1, p11s2 (52-57); p12s2 (62-68);
    p13s1, p13s2 (69-79); p14s1, p14s2 (80-84).
- Excluded (divisi, 5-7 staves per system): 10 systems, 57 staves, listed per staff as `<EXCLUDED divisi system: N staves>`.
  - 5 staves: p3s2, p4s1, p4s2, p5s1, p12s1. 6 staves: p8s1, p9s1, p10s1. 7 staves: p6s1, p7s1.
  - Stage 2 assumes 4 staves per system, so these layouts are unsupported. They are counted under Stage 2 coverage
    only and have no GT content.
  - Pages 3, 10 and 12 mix a divisi system with a 4-staff system on the same page (9, 10 and 9 staves). If Stage 2
    raises on those pages, their 4-staff systems count as missed.
- Key: 3 flats throughout. Repeats are not expanded.
- Uncertain (`?`) marks: 195 (including `?` inside OOV chord pitch lists).
- OOV items: 357. Almost all are the Bass line's repeated eighth-note double stops ("dza na na" ostinato) and the
  Tenor/Alto divisi, which is written as chords on one staff.
- Phrase slurs: 6.

## Method and known weak spots

- Same method as Gaano: rectified staff crops (`gt/tools/rect.py`), 4 horizontal parts per system at 1.0x with measured
  line positions (`gt/tools/show.py`), pitch read by eye. No notehead-blob cross-check.
- Two-voice staves (the Tenor's accented dotted-rhythm divisi on pages 10-11, and the whole note over the eighth
  ostinato on pages 13-14) were flattened into chords at shared onsets. The sustained upper voice is lost after its
  onset.
- Chord pitches on pages 10-14 carry many `?`s. Treat the Alto/Tenor/Bass chord pitches as the least reliable part.
- The arcs across the p13s2 -> p14s1 -> p14s2 system breaks were read as ties up to p14s1, and as phrase slurs into
  p14s2 (the pitches change there).
- Expect more annotator error here than in Gaano. This is the weakest of the agent-made GTs.
