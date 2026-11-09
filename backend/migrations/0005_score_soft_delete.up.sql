-- Soft delete with a 7-day recovery window (V2 B11); NULL means the score is live.
ALTER TABLE scores ADD COLUMN deleted_at timestamptz;
-- Library and cap count read only live scores of one user.
CREATE INDEX scores_user_live_idx ON scores (user_id) WHERE deleted_at IS NULL;
-- The purge pass scans deleted rows by age.
CREATE INDEX scores_deleted_at_idx ON scores (deleted_at) WHERE deleted_at IS NOT NULL;
