-- Cancel-before-submit intent (2026-11-10): the app may cancel a clientSubmissionId whose upload has not reached
-- the server yet; the later submit with that id is rejected. Additive, new table only. Pruned after 7 days.
CREATE TABLE cancelled_submissions (
    user_id              bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    client_submission_id uuid NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, client_submission_id)
);
