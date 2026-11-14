# Known issues (app-relevant)

The full research notes, bug tracker (`bug-tracker.md`) and tickets are in the local-only `_archive/docs/`.

- **`muted_measures` is always `[]`.** The API and the app accept the field, but the code that fills it
  (`apply_muted_spans`, `PipelineFailure`, the `start_tick`/`end_tick` spans from PIYA-108/109 AC8) was left
  behind when the v1 pipeline was copied in (commit 8fa6142). Bars that Stage 4 repairs lossily are therefore
  played as repaired, not silenced. Re-porting is a separate ticket. 55 tests in
  `tests/test_meter_and_muting.py` document the expected behaviour and are marked expected-failure in
  `tests/conftest.py`.
- **Failed voices and per-bar meter are live** (commits 8e83adb, 2672f4d): an empty voice is reported in
  `failed_voices` and the other voices continue.
- **Weights are not in git.** Copy `staff_detector_yolov8.pt`, `symbol_transcriber_crnn_seed1.pt`, `clef_key_classifier.pt` and `piano.sf2` into
  `models/` (gitignored). The Space image copies the same folder.
- **ClefKeyNet failed its real-photo gate** (BUG-021), so every event is flagged `clef_key_unvalidated` /
  `review_needed`. Keeping it as the default is a user decision, not a gate pass.
