-- PIYA-321: one row per user holding the last-used virtual-piano octave. No default is stored: it is
-- computed at read time from the client's voice hint until the first save. Additive, new table only.
CREATE TABLE piano_settings (
    user_id    bigint PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    octave     smallint NOT NULL CHECK (octave BETWEEN 2 AND 6),
    updated_at timestamptz NOT NULL
);
