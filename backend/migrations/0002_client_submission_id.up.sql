-- Submission idempotency key (PIYA-101): a retried upload with the same client-generated id
-- returns the original job instead of creating a duplicate. NULLs stay distinct, so jobs without
-- a key are unconstrained.
ALTER TABLE jobs ADD COLUMN client_submission_id uuid;
CREATE UNIQUE INDEX jobs_user_client_submission_idx ON jobs (user_id, client_submission_id);
