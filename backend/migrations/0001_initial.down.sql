-- Drops every table 0001 created (schema_migrations belongs to the runner and stays).
-- Dropping a table drops its triggers and indexes.
DROP TABLE IF EXISTS purge_log, storage_deletions, throttle_backoff, throttle_hits,
    timing_metadata, audio_tracks, job_pages, jobs, scores, password_reset_tokens, sessions, users;
DROP FUNCTION IF EXISTS set_updated_at();
