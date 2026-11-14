# Documentation index

| File | What it covers |
|---|---|
| [`deploy/render-api.md`](deploy/render-api.md) | Deploying the API on Render with Neon Postgres: environment variables, steps, deploy order. |
| [`deploy/local-worker.md`](deploy/local-worker.md) | Running the conversion worker on a laptop against the same Neon database. |
| [`backend/erd.md`](backend/erd.md) | Database schema (tables and columns); migrations in `backend/migrations/` must match it. |
| [`decisions/backend-bar-step-timing.md`](decisions/backend-bar-step-timing.md) | Why and how the backend computes per-bar timing for the playback highlight. |
| [`KNOWN-ISSUES.md`](KNOWN-ISSUES.md) | What is known to be missing or limited on `main` (stale tests, unvalidated clef/key classifier, divisi limit). |

Other places to read:

- Root [`README.md`](../README.md): what the project is, how to run it.
- [`../CLAUDE.md`](../CLAUDE.md): detailed stage-by-stage description of the pipeline.
- [`../backend/README.md`](../backend/README.md): API module map and endpoint notes.
- [`../mobile/piyanota_application/README.md`](../mobile/piyanota_application/README.md): app setup and folder map.

Research notes, training material, ground truth and old decision records are not in this repo's pushed history;
they live in the local-only `_archive/` folder.
