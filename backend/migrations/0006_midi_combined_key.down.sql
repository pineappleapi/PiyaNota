-- WARNING: dropping the column discards every stored combined-MIDI key, and no purge path can find those blobs
-- afterwards. On a database with scores, first INSERT the non-NULL keys into storage_deletions
-- (see background.queue_deletion), then run this.
ALTER TABLE scores DROP COLUMN IF EXISTS midi_combined_key;
