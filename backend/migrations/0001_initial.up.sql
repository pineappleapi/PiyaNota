-- Initial schema. Mirrors docs/backend/erd.md column for column; keep the two in sync.
-- CHECK constraints instead of ENUMs (PIYA-311 AC7) so values change without ALTER TYPE.

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE users (
    id            bigserial PRIMARY KEY,
    email         text NOT NULL UNIQUE CHECK (email = lower(btrim(email))),
    password_hash text NOT NULL,
    role          text NOT NULL DEFAULT 'choir_member' CHECK (role IN ('choir_member', 'choir_director')),
    deleted_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

CREATE TABLE password_reset_tokens (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_reset_tokens_user_idx ON password_reset_tokens (user_id);
-- At most one live reset code per user.
CREATE UNIQUE INDEX password_reset_tokens_one_live_idx ON password_reset_tokens (user_id) WHERE used_at IS NULL;

-- scores before jobs: jobs.score_id references it.
CREATE TABLE scores (
    id                  bigserial PRIMARY KEY,
    user_id             bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title               text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    arranger            text CHECK (arranger IS NULL OR char_length(arranger) BETWEEN 1 AND 120),
    page_count          smallint NOT NULL CHECK (page_count BETWEEN 1 AND 20),
    tempo_bpm           smallint NOT NULL DEFAULT 90 CHECK (tempo_bpm BETWEEN 30 AND 240),
    tempo_source        text NOT NULL CHECK (tempo_source IN ('user', 'fallback', 'default')),
    key_signature       text CHECK (key_signature IN ('C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'F', 'Bb', 'Eb', 'Ab', 'Db', 'Gb', 'Cb')),
    time_signature      text CHECK (time_signature IN ('4/4', '3/4', '2/4', '6/8', '2/2')),
    thumbnail_key       text,
    review              jsonb NOT NULL,
    muted_measures      jsonb NOT NULL DEFAULT '[]',
    failed_voices       jsonb NOT NULL DEFAULT '[]',
    failed_voice_causes jsonb NOT NULL DEFAULT '{}',
    last_accessed_at    timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scores_user_idx ON scores (user_id);

CREATE TABLE jobs (
    id                   bigserial PRIMARY KEY,
    user_id              bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    score_id             bigint REFERENCES scores (id) ON DELETE SET NULL,
    status               text NOT NULL CHECK (status IN ('queued', 'preprocessing', 'detecting_staff', 'transcribing', 'reconstructing', 'synthesizing', 'complete', 'failed', 'cancelled')),
    source               text NOT NULL CHECK (source IN ('images', 'pdf')),
    page_count           smallint NOT NULL CHECK (page_count BETWEEN 1 AND 20),
    title                text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    arranger             text CHECK (arranger IS NULL OR char_length(arranger) BETWEEN 1 AND 120),
    tempo_bpm            smallint NOT NULL DEFAULT 90 CHECK (tempo_bpm BETWEEN 30 AND 240),
    tempo_source         text NOT NULL CHECK (tempo_source IN ('user', 'fallback', 'default')),
    key_signature        text CHECK (key_signature IN ('C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'F', 'Bb', 'Eb', 'Ab', 'Db', 'Gb', 'Cb')),
    time_signature       text CHECK (time_signature IN ('4/4', '3/4', '2/4', '6/8', '2/2')),
    current_page         smallint,
    percent_complete     smallint NOT NULL DEFAULT 0 CHECK (percent_complete BETWEEN 0 AND 100),
    failure_reason       text,
    failure_page_index   smallint,
    failed_voices        jsonb NOT NULL DEFAULT '[]',
    failed_voice_causes  jsonb NOT NULL DEFAULT '{}',
    replaces_job_id      bigint REFERENCES jobs (id) ON DELETE SET NULL CHECK (replaces_job_id <> id),
    superseded_by_job_id bigint REFERENCES jobs (id) ON DELETE SET NULL CHECK (superseded_by_job_id <> id),
    completed_at         timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
-- At most one active retake per job (PIYA-311 AC8).
CREATE UNIQUE INDEX jobs_one_retake_in_flight ON jobs (replaces_job_id)
    WHERE status NOT IN ('complete', 'failed', 'cancelled');
CREATE INDEX jobs_user_status_idx ON jobs (user_id, status);
CREATE INDEX jobs_score_idx ON jobs (score_id);
CREATE INDEX jobs_superseded_by_idx ON jobs (superseded_by_job_id);

CREATE TABLE job_pages (
    id         bigserial PRIMARY KEY,
    job_id     bigint NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    page_index smallint NOT NULL CHECK (page_index >= 0),
    object_key text NOT NULL,
    width      int NOT NULL CHECK (width > 0),
    height     int NOT NULL CHECK (height > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, page_index)
);

CREATE TABLE audio_tracks (
    id         bigserial PRIMARY KEY,
    score_id   bigint NOT NULL REFERENCES scores (id) ON DELETE CASCADE,
    voice      text NOT NULL CHECK (voice IN ('soprano', 'alto', 'tenor', 'bass')),
    file_key   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (score_id, voice)
);

CREATE TABLE timing_metadata (
    id           bigserial PRIMARY KEY,
    score_id     bigint NOT NULL UNIQUE REFERENCES scores (id) ON DELETE CASCADE,
    metadata_key text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Throttle, deletion-queue and purge tables carry no FKs on purpose: they outlive the rows they
-- refer to and hold no PII (subject_key is an HMAC, never the raw value).
CREATE TABLE throttle_hits (
    id          bigserial PRIMARY KEY,
    bucket      text NOT NULL,
    subject_key text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX throttle_hits_lookup_idx ON throttle_hits (bucket, subject_key, created_at);

CREATE TABLE throttle_backoff (
    scope           text NOT NULL,
    subject_key     text NOT NULL,
    failures        int NOT NULL DEFAULT 0,
    last_failure_at timestamptz NOT NULL,
    wait_until      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, subject_key)
);

CREATE TABLE storage_deletions (
    id              bigserial PRIMARY KEY,
    object_key      text NOT NULL,
    attempts        int NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX storage_deletions_next_attempt_idx ON storage_deletions (next_attempt_at);

CREATE TABLE purge_log (
    id           bigserial PRIMARY KEY,
    user_ref     bigint NOT NULL,
    completed_at timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- schema_migrations is created by the runner (backend/migrate.py), not here.

CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER sessions_set_updated_at BEFORE UPDATE ON sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER password_reset_tokens_set_updated_at BEFORE UPDATE ON password_reset_tokens FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER jobs_set_updated_at BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER scores_set_updated_at BEFORE UPDATE ON scores FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER throttle_backoff_set_updated_at BEFORE UPDATE ON throttle_backoff FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER storage_deletions_set_updated_at BEFORE UPDATE ON storage_deletions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
