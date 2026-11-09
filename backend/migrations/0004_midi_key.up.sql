-- MIDI per voice (V2 B6); nullable because scores converted before this have no MIDI.
ALTER TABLE audio_tracks ADD COLUMN midi_key text;
