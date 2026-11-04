# Moonriver diagnostic of the app's conversion output (2026-11-04)

> **DEV DATA, DIAGNOSTIC ONLY, NOT AN ACCURACY RESULT.** Moonriver was used for tuning, so every number below is optimistic and says nothing about real-world accuracy. Use it to find failure modes, never to claim a score.

## What was measured

The question was how close the audio the app plays is to the printed score. The script `backend/scripts/moonriver_diag_eval.py` runs the worker's real adapter, `backend.worker.pipeline.run_pipeline`, with its defaults: the `phase2_seed1.pt` CRNN, ClefKeyNet on, Stage 4 with the tie fix, and Stage 5 synthesis. The inputs are the four Moonriver photos p01 to p04, baked the same way the app bakes them (EXIF orientation applied, re-encoded at quality 95), as in `smoke_convert.py`. It ran on CPU only (`CUDA_VISIBLE_DEVICES=-1`) under `D:/PiyaNota/.venv`, tempo 90. The pipeline finished with all four MP3s and no failed voices. The scored events are `result.events`, the reconstructed events that become the MIDI and MP3 files.

## Reference and exclusions

The reference is `Moonriver.mscz`, exported to MusicXML with the installed MuseScore 4 and read with music21. The score has 40 measures, 4/4 for bar 1 and 3/4 afterwards (bar 17 is 4/4 again), key of five flats, and no repeats, endings or pickup bar, so the printed order is the played order and nothing was unrolled. Tied notes are merged in the reference, grace notes are dropped, and the Tenor is read at sounding pitch.

The file has five parts: Soprano, Alto, Tenor, Bass 1 and Bass 2. It contains no chords and no measure with two layers. Bass 2 is identical to Bass 1 except in bar 40, where Bass 1 sings MIDI 49 and Bass 2 sings 37 (a divisi on the last note). I scored Bass against Bass 1 for all 40 bars, as the existing dev manifest does, and did not exclude that bar. The pipeline played 49 there, which matches Bass 1. So v1's inability to represent chords or divisi excludes nothing in this piece except that Bass 2's low note is not scored.

## Method

Pitch accuracy is reported two ways. Position-aligned means a reference note counts as right when the pipeline has a note with the same global bar and the same onset inside the bar (taken from each side's own bar start) with the same pitch. Sequence-aligned means edit distance over each voice's note pitches, so one missing note does not shift the rest; the missing, extra and wrong counts come from the distance and the match count. Rhythm accuracy uses the same two alignments on the (rest or note, duration) of notes and rests. Strict F1 matches a pipeline note to a reference note one to one when the pitch is equal and onset and duration are each within a sixteenth (120 ticks). I report it twice: with absolute onsets, and with onsets measured inside their own bar. The existing harness (`stage4_eval.score_events`, read only from the `piya106-stage4-fixes` worktree) was also run for strict and tie-agnostic SER. Overall figures pool the counts from all four voices.

## Headline numbers (dev data)

| Voice | Pitch, position | Pitch, sequence | Rhythm, position | Rhythm, sequence | Strict F1, absolute | Strict F1, bar-relative |
|---|---|---|---|---|---|---|
| Soprano | 0.877 | 1.000 | 0.831 | 0.916 | 0.048 | 0.843 |
| Alto | 0.951 | 0.963 | 0.929 | 0.941 | 0.036 | 0.876 |
| Tenor | 0.949 | 0.987 | 0.924 | 0.937 | 0.052 | 0.916 |
| Bass | 0.975 | 0.975 | 0.964 | 0.964 | 0.024 | 0.939 |
| Overall | 0.938 | 0.981 | 0.912 | 0.939 | 0.040 | 0.893 |

Overall there are 322 reference notes and 330 reference events (notes plus rests). Sequence-aligned pitch has 316 matched, 5 wrong, 1 missing and 11 extra notes. Sequence-aligned rhythm has 310 matched, 19 wrong, 1 missing and 11 extra events. The existing harness gives overall strict SER 0.085 and tie-agnostic SER 0.036 with pitch accuracy 0.983, but it scores only the three fully bar-aligned pages for Soprano (the whole of page 4 is dropped for all voices because Soprano has no numbered bars there), so it covers 306 of 318 events.

Bars: the reference has 40. The pipeline numbered 36 Soprano bars (7 more Soprano events carry no bar number), 40 Alto, 39 Tenor and 40 Bass. Bars whose total length equals the reference bar: Soprano 31, Alto 39, Tenor 36, Bass 39 of 40 each.

## Key, octave and timeline

All four voices are in the right key and the right octave. The median pitch per voice matches the reference exactly (Soprano 68, Alto 63, Tenor 57, Bass 49), the Tenor is not an octave off, and the median pitch error on aligned notes is 0 in every voice. Between 89% and 100% of notes fall in the five-flat scale in both the reference and the output. No octave errors were found among the aligned wrong notes. The review object still raised `tenor_range_suspect` for Tenor bar 1, which this check does not support.

The timeline is wrong, though. The pipeline read every bar as 4/4 (all 340 events carry `4/4`), while the score is mostly 3/4. Each 3/4 bar is laid on a 4/4 grid, so the audio has a beat of silence after most bars. This shows up as 147 `bar_underfull` flags and 16,800 to 19,440 ticks of silence per voice. Total length is 76,800 ticks against 58,560 in the score, so the audio is 31% longer, and because the notes' absolute onsets drift from bar 2 on, absolute strict F1 is 0.04 even though 89% of notes are right inside their own bar. The review object lists `mid_strip_meter_change` for the first systems but nothing flags the whole piece as being in the wrong meter.

## Dominant error types

1. Meter misread: 340 of 340 events carry 4/4, 147 underfull-bar flags, about 35 to 40 beats of inserted silence per voice, audio 31% too long. This is the largest error by far and is purely rhythmic placement; notes inside each bar are mostly correct.
2. Unmerged ties: 11 extra notes in the pitch sequence, nine of them Soprano 4 and Alto 5. Output has 5 and 17 adjacent same-pitch pairs against 1 and 12 in the reference. The reference has 16 tied notes and the pipeline merged 8 (Soprano 3 of 6, Alto 0 of 4, Tenor 4 of 3, Bass 1 of 3). Five `tie_inferred_from_slur_end` flags fired.
3. Wrong pitch: 5 substitutions (Alto 3, Bass 2): three semitone errors on aligned notes (all Alto, consistent with a missed or added accidental), three whole-tone and one larger error. No octave errors, no dropped rests (2, 3, 1, 2 rests in the output, equal to the reference).
4. Wrong durations: 19 rhythm substitutions overall (Soprano 7, Alto 5, Tenor 4, Bass 3), plus bars with the wrong total length (9 Soprano, 1 Alto, 4 Tenor, 1 Bass).
5. Bar structure: Soprano has no numbered bars on page 4 (7 events placed locally, one `bar_count_mismatch` flag) and Tenor is one bar short.

## Limits

This is one piece, tuned against, scored by a script I wrote on top of a read-only harness. The audio itself was not decoded; the claims about pitch, octave and silence come from the reconstructed events that Stage 5 renders. The pickup length was 0, matching the reference. The raw output is in `D:/PiyaNota/data/eval_moonriver_diag/` (`pipeline_out.json`, `scores.json`).
