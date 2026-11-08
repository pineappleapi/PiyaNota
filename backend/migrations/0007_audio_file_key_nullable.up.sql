-- MIDI-only scores (2026-11-08): new conversions store no MP3, so file_key must allow NULL. Old rows keep their key.
ALTER TABLE audio_tracks ALTER COLUMN file_key DROP NOT NULL;
