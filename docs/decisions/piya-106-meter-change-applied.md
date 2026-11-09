# Applying mid-strip meter changes (Task 3, investigation only, 2026-11-05)

Status: investigation by ml-cv-lead review, no code changed. Verdict: applying is safe only if Stage 4 lays out bars per measure and the apply rule also checks bar durations. A Stage 3 only change is not safe.

## R3 reason

R3 is one of the continuity rules R1 to R4 added in commit 58713ba (2026-09-30, branch piya106/clefkey-wiring), documented in docs/decisions/piya-106-ser-15-plan.md under "Key / time-signature continuity R1-R4". The rule text is: a mid-strip time signature is reported (`mid_strip_meter_change` at a quorum of 3 voices, otherwise `mid_strip_meter_unconfirmed`), never applied, and its digits are no longer read as a multirest count. The only stated reason is the code comment at stage3_transcription.py:1740: "re-timing on a misread meter would shift bars".

What the history shows:

- R3 was a conservative choice made while the work was about key changes. R4 applies a key change at a 3 of 4 quorum. The meter was left out because a wrong meter changes bar length, and bar length moves every later tick, while a wrong key only changes pitches.
- An earlier branch, feature/piya107-108-meter-muting (commit 9d07da3, BUG-051), did apply a paired mid-strip meter, set `time_signature_source`, and laid out bars per measure in Stage 4. R3 replaced that behaviour in the SER plan work. No document records a measurement that showed applying was harmful. The reason is a risk argument, not a result.
- The dev replay behind R3 (654 strips, 164 systems, both seeds) had 0 meter candidates and 0 gate firings. So R3 was never tested on a piece that really changes meter, and there is no evidence for or against applying.
- Moonriver (dev data) is the first real case. The CRNN read every change correctly in all four voices (confidence 0.74 to 1.0), and discarding them produced 76,800 ticks against 58,560 in the score (docs/decisions/moonriver-time-signature-trace-2026-11-04.md).

## Risks

1. Stage 4 has one meter per system. `_consensus_time_signatures` (stage4_reconstruction.py:343-363) returns one value per (page, system) key, `_plan_layout` uses it for every bar of that system, and `_decide_pickups` and timing_export.py:95 read the same single value. Moonriver page 1 system 1 is 4/4 in bar 1 and 3/4 in bars 2 to 4. If Stage 3 stamps 3/4 on the events after the change, the per-system majority becomes 3/4 and bar 1 is laid out wrong instead. Applying in Stage 3 alone only moves the error.
2. A 4/4 reading is treated as "no evidence" by the same function, so a real change back to 4/4 (Moonriver bar 17) is invisible. This was the reason for BUG-051's `time_signature_source` field. Stage 3 on this branch no longer emits it, so Stage 4 cannot tell a detected 4/4 from a default.
3. A false quorum is costly. Three voices share the same CRNN and font, so their errors are correlated and a quorum is weaker evidence than three independent votes. A false 3/4 on a 4/4 piece makes every later bar overflow, which triggers the overflow repair (scaling, clipping, drops) and shifts the global tick of every later system in all voices. The voices stay aligned with each other, but the whole piece is wrong. Today the same misread costs nothing because it is only a flag.
4. A courtesy meter at the end of a strip (Moonriver page 2 system 1, before bar 17) has no bar after it in that strip. It must carry into the first bar of the next system, and the next system's header meter is removed by the continuation-header filter. If the carry is missed, bar 17 stays at the old meter.
5. Meter and pickup interact. `_decide_pickups` judges the first bar against the first system's meter, so a change in the first system (Moonriver) changes which first-bar lengths count as a pickup.
6. Beat is assumed to be a quarter. 3/4 versus 6/8 both give 1440 ticks per bar in `_bar_ticks`, so a 3/4 to 6/8 misread is silent in the layout and wrong in the click. This is a choral-conductor question for the 3/4 versus 6/8 rule.
7. The signal is still confidently wrong in the BUG-011 sense. The CRNN confidence is a frame mean softmax and not calibrated, so it cannot separate a true change from a correlated misread. The duration check below is the only independent signal, and it should be reported as the confirmation, not the confidence.
8. Recall evidence is thin. Moonriver is the only known positive and it motivated this change, so a pass on it shows the code works, not that it generalizes.

## Ablation design

Principle: nothing is tuned. The quorum stays 3, and the duration agreement rule is fixed before any run. The ablation observes only.

Data (all dev data, diagnostic only, never reported as accuracy):

- No-change pieces, for the false positive test: eval_prelim (Non Nobis, Honneur, Gaano, Handog, Don't Stop Me Now, digital and camera arms) and eval_fresh (same pieces, plus the Both Sides Now photos for staff counts only). Their cached Stage 1 to 3 outputs are in data/eval_fresh/runs and data/eval_prelim/runs. Expected result: events and Stage 4 output byte-identical with the flag on and off. Any difference is a finding.
- Positive piece: Moonriver p01 to p04 through backend/scripts/moonriver_diag_eval.py. It is in-sample for this change, so label it "mechanism check".
- Synthetic positives for recall: token level tests plus Phase 1 style renders with meter changes mid-strip and at system breaks (3/4, 4/4, 2/4, 6/8). This is the only place recall may be claimed, as in the R1 to R4 plan.
- Do not use piyanota_dataset photos for any decision. The prereg (data/eval_fresh/PREREG.md) lists the Non Nobis and Honneur photos as TEST-only, while the task brief and memory classify eval_prelim and eval_fresh as dev data. Resolve this before the run: use them only for the unchanged-output check, make no threshold choice from them, and say so in the report.

Switch: `APPLY_MID_METER_CHANGE` False then True, same cached Stage 3 token output (rerun Stage 3 only where the flag changes events; Stage 1 and 2 outputs are reused so the only variable is the flag). Run both CRNN seeds and report the range, never one seed.

Metrics per piece, flag off versus on:

- Meter mismatches against ground truth per bar (bars with the wrong meter), and count of bars changed.
- `bar_underfull`, `bar_overflow_clipped` and `suspected_missing_barline` counts, total ticks per voice, and total length against the reference where one exists (Moonriver 58,560).
- Pitch and rhythm change per piece, using the same scorer as before (data/eval_prelim/score_prelim.py, data/eval_fresh/score_eval.py). Note-level numbers are expected to be unchanged for bar contents, and onset alignment is what moves.
- Count of new flags and their share that are true.
- Pass rule, fixed now: the flag stays on only if no no-change piece changes output in either seed, and the number of unflagged wrong-meter bars does not rise on any piece. A single false firing on a no-change piece fails the change.

Leakage check:

- Confirm the Stage 3 checkpoints are the same files as in data/eval_dsmn/checkpoint_hashes.txt and that no run feeds ground truth tokens into the rule.
- The duration agreement rule and the quorum are set before the run and recorded with the git hash in the output.
- Ground truth meters come from the .mscz or .mxl and are read only by the scorer, never by the apply path.
- Moonriver was used to find the problem, so its result is not an estimate of recall. Do not report it as evidence of generalization.

## Change list

Required, stage3_transcription.py:

- `infer_pitch` (R3 branch, lines 1738-1745): when a system level meter map is passed (new parameter next to `system_key_changes`), set `time_signature` from that measure on and mark `time_signature_source` as applied. Without the map, keep today's behaviour. Also handle the courtesy case where no event follows the meter in the strip (carry out to the next system) and skip the old multirest handling at lines 1976 and 2460 consistently.
- `decide_mid_changes` (line 2870): return a meter map {measure_index: meter} next to the key gate, using the existing quorum `HEADER_QUORUM`, and keep `mid_strip_meter_change` as an internal flag. Add the duration agreement check here or in Stage 4.
- `scan_mid_changes` and its callers (lines 3046, 3122, 3158-3192, and `process_strip` at 2973-2994): pass the meter map through, as is done for `system_key_changes`.
- stage3_clefkey.py (line 466-494): pass the meter map into `infer_pitch`.
- Event fields: add back a source marker (`explicit`, `carried`, `inferred`, `default`) so Stage 4 can tell a real 4/4 from a default.
- Viz label at line 2512: show "applied" instead of "read, not applied" when the flag is on.

Required, stage4_reconstruction.py:

- `_consensus_time_signatures` (343-363): return a meter per measure or per bar range within a system, not one per system. Count a 4/4 with source explicit or carried as real evidence. Carry the meter across system breaks.
- `_plan_layout` (366-430): use per bar `bar_ticks`, so `n_bars` and `start_tick` are sums of per bar lengths. `layout[key]["time_signature"]` and `bar_ticks` become lists or a bar map.
- `_decide_pickups` (667-720), `_measure_span`, overflow and underfull repair (`_repair_overflow` at 1342, `_normalise_whole_rest` at 1080), and every other reader of `bar_ticks` (about 60 mentions): take the bar's own length.
- New `resolve_bar_meter(explicit, previous, bar_total_ticks)` per the plan, with the precedence explicit, carried, inferred, default.

Required, other files:

- timing_export.py:95 reads one `time_signature` per system. Use the per bar value, otherwise the click and bar lines for Moonriver stay wrong. This also feeds Task 4 bar fields.
- tests/test_meter_apply.py (new), plus tests/test_meter_and_muting.py and tests/test_stage3_key_continuity.py if present on this tree, because R3 tests ("meters reported, not applied; negatives") assert the old behaviour and must be updated.
- training/meter_ablation.py (new), as in the plan.
- Copy the changed stage files into the backend tree after the tests pass (Task 5 method).

Long-term cost: this is a logic fix, not a model fix. It uses the CRNN's meter reading as is, so it is as good as that reading on the next unseen font. The duration check is what makes it safe against the next unseen misread, and it should be kept even if the CRNN improves. The silent failure class (confidently wrong meter) is reduced by the duration check but not removed.

## Results (Task 3 implementation, 2026-11-05)

These numbers are diagnostic only. They are not accuracy figures. They come from `training/meter_ablation.py`, which runs Stages 1 to 4 on camera photos with `APPLY_MID_METER_CHANGE` off and then on. Both runs share the same CRNN tokens, so any difference comes from the meter logic alone. The run used both phase2 CRNN seeds (seed1 and seed2) and the default ClefKeyNet checkpoint, on CPU. The raw output is in `data/eval_meter_ablation/results.json`, which is gitignored, with the git head and checkpoint hashes in its meta block.

Non Nobis Domine and Honneur a Toi are test-only. The script refuses them and they were not run. No threshold or rule was tuned on any number below.

Pieces with no meter change (Gaano Ko Ikaw Kamahal, Handog, Don't Stop Me Now, Both Sides Now): for both seeds, the Stage 3 and Stage 4 events were identical with the flag off and on, apart from the new source field. Total ticks, bar counts and every bar flag count were unchanged. No bar changed length. No meter_inferred, meter_inference_rejected or meter_change_duration_mismatch flag was raised. Every bar resolved to 4/4, read explicitly at a system start or carried from the previous bar. So the pass rule held: no piece without a meter change changed its output.

Moonriver (one change, 4/4 to 3/4): for both seeds, total ticks went from 76,800 with the flag off to 58,560 with it on. 58,560 is the length of the reference score. Bars with the wrong length against the reference went from 38 of 40 to 0 of 40. bar_underfull flags went from 147 to 5 (seed1) and from 148 to 5 (seed2). One new bar_overflow_clipped flag appeared, and one divisi_rhythm_split_suspected flag went away. The meters on the run were 4/4 explicit for 2 bars, 3/4 explicit for 6 bars and 3/4 carried for 32 bars. No meter was inferred and no duration mismatch was flagged.

Limits:

- Moonriver is the piece that found the problem, so its result is in-sample. It shows the mechanism works on one piece. It is not an estimate of how often a real meter change is caught.
- Only one dev piece has a meter change, so the quorum, the duration check and bar-total inference have almost no positive evidence. The no-change pieces show only that the change does no harm there.
- Handog lost 9 of its 14 pages to the Stage 2 staff-count error (`unsupported_staff_layout`), so only 5 pages were compared. Other pieces ran in full.
- Gaano, Handog and Don't Stop Me Now photos sit in the `data/piyanota_dataset` folder. They were used here as dev data on the caller's ruling. This should be confirmed, because the project rule says the piyanota_dataset photos are test-only.
- Only camera photos were run. Digital pages for these pieces were not available on this tree.
- Inference accepts only 2/4, 3/4 and 4/4 with a quarter-note beat. A 6/8 piece would be inferred as 3/4 or rejected. Stage 4 still assumes a quarter-note beat for 6/8.
- A multirest is still counted as 1920 ticks whatever the meter, so a multirest inside a 3/4 or 2/4 passage has the wrong length.
- The CRNN meter reading is used as is, and its confidence is not calibrated. A confidently wrong meter read by a quorum of voices would still be applied. The duration check only flags it when the bar totals fit the old meter better.
