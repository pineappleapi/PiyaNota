-- WARNING: fails while any MIDI-only row exists (file_key NULL). Delete those rows (after queueing their midi_key
-- blobs in storage_deletions) first.
ALTER TABLE audio_tracks ALTER COLUMN file_key SET NOT NULL;
