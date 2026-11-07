-- Combined playback MIDI (one file per score, not per voice, so it lives on scores); NULL for older scores.
ALTER TABLE scores ADD COLUMN midi_combined_key text;
