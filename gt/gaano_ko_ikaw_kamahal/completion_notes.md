# Gaano Ko Ikaw Kamahal ground truth: completion notes

HAND-MADE / PROVISIONAL / single annotator (agent) / not verified by a musician. Diagnostic only; not accuracy evidence.
Written 2026-09-28 before any pipeline run on these photos. The user asked for the test to proceed without their check.

- Source: `D:\PiyaNota\data\piyanota_dataset\gaano_ko_ikaw_kamahal_pg01.jpg` to `_pg09.jpg`.
- Frozen file: `gt_source.txt`
- sha256: `45077a2086b815452d131e12a03f7de9f3e5be13bbbb0a4388d468fafbd41fe1` (also in `gt_source.sha256`)
- Split status: `gaano_ko_ikaw_kamahal` is FROZEN in `training/step3_mask_split.json`. It was not used for Stage 1 mask tuning.

## Counts

- Systems: pages 1-4 have 2 each, page 5 has 3, pages 6-8 have 2 each, and page 9 has 1. That is 18 systems and 72 strips.
- Every bar compiles to 1920 ticks (4/4).
- Excluded strips: none.
- Key: 3 flats to bar 43, then 1 flat from bar 44 (page 6) to the end.
- Uncertain (`?`) marks: 67.
- OOV items: 98 (chords and triplets). These are mostly Bass/Tenor double stops and quarter/eighth triplets on pages 7-9.
- Phrase slurs: 47.

## Method and known weak spots

- Each staff was rectified (`gt/tools/rect.py`). One system at a time was viewed at 1.0x in 4 horizontal parts, with the measured line positions printed (`gt/tools/show.py`).
- Pitch was read by eye against those positions. No notehead-blob cross-check was run, unlike Honneur.
- Weak spots:
  - Pages 8-9 have dense chords and two-voice Bass writing. Multi-voice rhythms were flattened into chords at the shared onsets.
  - p9s1 has a tie from a single note into a final chord, which the format cannot express. It was dropped.
  - Several chord pitches on pages 8-9 carry `?`.
- Expect more annotator error here than in Honneur.
