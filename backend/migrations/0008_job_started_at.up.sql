-- Job started_at (2026-11-10): set at each claim so a per-job max wall-clock runtime can be enforced even while the heartbeat stays alive.
ALTER TABLE jobs ADD COLUMN started_at timestamptz;
