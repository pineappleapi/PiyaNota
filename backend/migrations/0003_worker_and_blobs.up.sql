-- Worker handoff (PIYA-300): blobs lets the API and the worker process share files through Neon;
-- attempts/heartbeat_at let the worker reclaim jobs whose process died mid-conversion.
CREATE TABLE blobs (
    key text PRIMARY KEY,
    content_type text NOT NULL,
    data bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE jobs ADD COLUMN attempts smallint NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN heartbeat_at timestamptz;
