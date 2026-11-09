DROP INDEX IF EXISTS jobs_user_client_submission_idx;
ALTER TABLE jobs DROP COLUMN IF EXISTS client_submission_id;
