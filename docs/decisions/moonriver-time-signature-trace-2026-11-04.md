# Moonriver time-signature trace (2026-11-04, dev data, diagnosis only)

Question: all 340 Moonriver events say 4/4, but the score is 4/4 in bar 1, 3/4 in bars 2-16, 4/4 in bar 17, then 3/4 from bar 18 to the end. Who lost the meter?

Answer: the CRNN read the meter correctly. Stage 3 saw every change, flagged it, and by design did not apply it. Stage 4 then had nothing but the default to work with.

The truth comes from the .mscz export (Moonriver.mxl): 4/4 at bar 1, 3/4 at bar 2, 4/4 at bar 17, 3/4 at bar 18. Bars 2-16 are 3/4 and bars 18-40 are 3/4.

What the CRNN emitted (Stages 1-3 rerun on CPU, same models as the diagnostic run, all four voices):

- Page 1 system 1 (bars 1-4): all four voices read digit 4 over digit 4 in the header, then after the first barline digit 3 over digit 4. Correct. Confidence 0.74 to 1.0 (lowest is the Alto and Tenor 4 numerator at 0.74 and 0.75).
- Page 1 systems 2-3, page 2 system 3, page 3 systems 1-3: no meter token in any voice. Expected, a continuation system carries no meter.
- Page 2 system 1 (bars 13-16): all four voices read 4/4 at the very end of the strip, after the last barline. This is the change to 4/4 before bar 17. Correct. Confidence 0.83 to 1.0.
- Page 2 system 2 (bars 17-20): all four voices read 4/4 in the header (dropped by the continuation-header filter, which is fine) and 3/4 after the first barline. Correct. Confidence 0.77 to 0.98.
- Page 4 system 1: Soprano and Tenor emit a lone denominator digit 4 (0.85 and 0.43), Alto and Bass nothing. Noise, below quorum. The true meter stays 3/4 and there is no change here.

The rule that decides the meter:

1. Stage 3 sets one `time_signature` per strip from the strip's opening tokens only (`stage3_transcription.py:1381`, default `DEFAULT_TIME_SIGNATURE` "4/4" at line 853; header handling at lines 1621-1711).
2. A meter after a barline is found by `_meter_at` and, in `infer_pitch`, is only appended to `mid_changes_out` and skipped (`stage3_transcription.py:1738-1745`, comment "R3: reported for review, not applied"). `decide_mid_changes` (line 2870) keeps a quorum of 3 voices and flags the whole system `mid_strip_meter_change` plus `review_needed`, and again does not apply it (docstring line 2880).
3. Events therefore keep the strip's opening meter. A strip with no header meter (every continuation system) gets 4/4 by default.
4. Stage 4 `_consensus_time_signatures` (`stage4_reconstruction.py:336-356`) takes the most common event meter per system and only lets a non-default value change the running meter. A 4/4 reading is treated as "no evidence", so it inherits the previous value. Because Stage 3 never applied 3/4, Stage 4 never saw it.

What this run shows: the quorum fired in 3 systems (page 1 system 1, page 2 system 1, page 2 system 2), all four voices each, with `mid_strip_meter_change` on the events of those systems (36 + 42 + 36 = 114 of 340 events). The flag is on the events but the saved report has no per-bar meter flag, and the meter never reached the bar layout. `mid_strip_meter_change` does not carry the new meter value into Stage 4. Stage 4 does not consume it at all.

The first meter token appears at the start of the piece (4/4), and the change to 3/4 follows one bar later in the same strip, so later changes do show as mid-strip tokens. They are read correctly and then discarded by design.

Consequence: each 3/4 bar (1440 ticks) is laid out in a 1920-tick bar, which is why the report shows 16.8k to 19.4k ticks of underfull silence per voice and a total of 76800 ticks against 58560 in the reference.

Not checked: whether applying the quorum meter would break other pieces (this was a read-only diagnosis). Raw trace data lives in `C:/Users/paul_/.claude/jobs/f4582ada/tmp/trace.json`, not in the repo.
