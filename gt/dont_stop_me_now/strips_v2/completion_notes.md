# DSMN ground-truth completion notes (2026-09-26)

**Status:** HAND-MADE, PROVISIONAL, SINGLE ANNOTATOR (an agent), NOT VERIFIED BY A MUSICIAN.
This is diagnostic ground truth only. It was read from the photos
`data/test_dataset/dont_stop_me_now_pg01-05.jpg` (crops in `gt/crops/`) and the `gt/heads.py` notehead helper.
No CRNN was run and no CRNN output (full_seed*, before_fix, after_fix, baseline, score.json) was opened.

## What was added

| System | Bars | Strips |
|---|---|---|
| p1s3 | 6-8 | S A T B |
| p2s1 | 9-11 | S A T B |
| p2s2 | 12-14 | S A T B |
| p2s3 | 15-17 | S A T B |
| p3s3 | 24-26 | S A T B |
| p4s1 | 27-29 | S A T B |
| p4s2 | 30-32 | S A T B |
| p4s3 | 33-35 (ends in a double bar) | S A T B |
| p5s3 | 42-44 | S A T B |

In total that is 9 systems and 36 strips. None were excluded. `gt_source.txt` now holds 60 strip lines: the 24 original lines plus these 36.

I confirmed the system count first: every page has 3 systems × 4 staves.

The 36 lines were inserted in page/system/voice order:
- p1s3 and p2 go after p1s2.
- p3s3 and p4 go after p3s2.
- p5s3 goes after p5s2.

The original 24 lines, the header and the closing comment are byte-identical. A `diff` against the backup shows 0 removed lines and 36 added. The file keeps its CRLF line endings.

Backups made before any edit:
- `gt/gt_source.pre_completion.txt`
- `gt/build_gt.pre_completion.py`
- `gt/gt.pre_completion.json`

## Compiler change (build_gt.py): accidentals

The header already documented accidentals as `<[^_=]?>`, but the note regex rejected them. Several new strips need them:
- Eb5 in the Tenor, p1s3 and p4s1
- F#4 and F#3 in p2s1, p4s2 and p5s3
- B-natural 2 in the Bass, p4s3

What I added:
- An optional `^` (sharp), `_` (flat) or `=` (natural) prefix on the pitch.
- An `accidental.<sharp|flat|natural>-<pos>` agnostic token, emitted before the note, which is PrIMuS order.
- Standard carry of the accidental to the end of the bar, per letter and octave.
- Carry across a barline through a tie. Rests reset the tie carry.
- Event pitch is computed from the natural letter plus the accidental.

Check: rebuilding the original 24 lines with the new compiler gives a `gt.json` byte-identical to the pre-change output, and the printed summary is identical too.

`gt/gt_source.sha256` still holds the hash of the frozen 24-line source (`9af7d7ab...`). I did not update it. The new source hashes to `72edc5ca82be76ec03a4e2502d3c72fe2df97a99b9ca5f5deaeee3ef08ec33d4`. Whoever owns the freeze should decide whether to re-freeze.

## Build result

`python gt/build_gt.py` (run from `data/eval_dsmn`) ran clean: no parse errors and no assertion failures. It wrote 60 entries to `gt/gt.json` plus the per-strip `.txt` files.

Every bar of all 36 new strips sums to 1920 ticks (4/4). The only bar that does not sum is the old p1s1 Tenor pickup, bar 0 = 240 ticks, which is expected.

## Uncertain spots (marked `?` where the notation allows it)

- **p2s3 Tenor, bar 17:** the half note could be E5 or F5. I encoded it as `h:E5?~`. I read the arc from it to the first beamed E5 as a tie, because that eighth carries no syllable.
- **p4s1 Bass, bar 28, "doo" quarter:** I read `q:B3?`, with the head just above the top line. It could be A3 if the head is on the line.
- **p4s2 Soprano, bar 31, "I'm" eighth:** I read it as G4 from a zoom. `heads.py` said F4, but it had shifted its note list because it misses hollow heads (it skipped the dotted half).
- **Ties versus slurs.** Several arcs between same-pitch notes were read as ties because the second note has no lyric syllable:
  - p1s3 S, A and T, bar 7
  - p4s1 S, A and T, bar 27
  - p4s1 Soprano, bar 28, D4 eighth to quarter
  - p4s1 Bass, bar 28
  - p4s2 Alto and Tenor, bar 30 into 31
  - p5s3 Soprano, bar 43, A4 eighth to quarter
- **Phrase slurs** (arcs between different pitches) are counted with `#slurs`, not encoded as ties:
  - p4s2 Soprano: A4 "heit" to the G4 dotted half
  - p5s3 Soprano: the long A4-to-D4 arc
- **Chord pitches inside `<OOV:...>`** are approximate or omitted. They are not in the token reference anyway.
- `heads.py` misses hollow heads and failed to find the staff lines on p3s3 Tenor. For those I relied on zoomed crops.

## OOV items (duration-bearing unless stated)

**Chords or dyads:**
- p2s1 Tenor, bar 9
- p2s3 Soprano, bar 15
- p2s3 Bass, bar 16
- p3s3 Soprano, bars 25-26
- p3s3 Alto, bar 26
- p3s3 Tenor, bars 24-26
- p3s3 Bass, bar 26
- p4s1 Tenor, bar 29 (Bb4+D5 written)
- p4s1 Bass, bar 27 (F2+F3)
- p4s3 Soprano and Tenor, bar 34 (all 8 eighths)
- p5s3 Alto, bar 42
- p5s3 Tenor, bar 44 (G4+F5)

**Two-voice writing within one staff, encoded as zero-duration OOV plus the lyric-carrying voice:**
- **p3s3 Tenor, bar 25:** an upper-voice F5 eighth ("me."), tied into bar 26.
- **p3s3 Tenor, bar 26:** an upper-voice dotted-half F5 over the lower voice `q.:C5 e:C5~ [ e:C5 e:C5 ] re`, followed by a two-voice eighth chord.
  - Alternative: exclude the strip, as the existing p3s1 Tenor was.
- **p4s3 Alto, bar 35:** an upper-voice dotted-half G4, tied in, plus a quarter rest, over the lower voice `re e:C4 q:C4 e:C4 q.:C4`.
  - The bar-34 G4 that ties into it is encoded with `~>` (tie to something outside the token reference). This reuses the "tie leaves system" marker, because a plain `~` would make the compiler emit `slur.end` before the lower-voice C4.

## Bars that do not sum to 4/4

None as encoded. Read naively left to right, p3s3 Tenor bar 25 is 4.5 beats, because the upper-voice F5 eighth sits on top of a full 4/4 lower voice. It is encoded as a zero-duration OOV, so the bar sums to 1920.

## Disagreements with existing lines

None found. The existing lines were not changed.

Continuity checks across system boundaries were consistent:
- p2s1 ties `~>` into p2s2 `<~` in all 4 voices.
- p2s2 Bass `C3~>` continues as p2s3 `C3<~`.
- p2s3 Soprano `A4~>` continues as the existing p3s1 `q:A4<~`.
- p2s3 Alto `F4~>` continues as the existing p3s1 `e:F4<~`.
- p4s2 S, A and T `~>` continue as p4s3 `<~`.
- No ties are expected at p1s2→p1s3, p3s2→p3s3, p4s3→p5s1 or p5s2→p5s3, and none were written.

Note that the p5s3 Soprano bar 43 motif `[A4 A4 B4 A4~]` differs from the existing p5s2 bar 39 `[A4 A4 C5 A4~]`. I checked with `heads.py`: p5s2 really does have C5 there. This is a variation in the score, not a disagreement.
