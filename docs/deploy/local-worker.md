# Conversion worker on a laptop

The API on Render only queues jobs. The worker claims a queued job from Neon, runs Stages 1 to 5 on the
photo and writes the MIDI, pages and timing back to the database (`PIYA_STORAGE_BACKEND=db`), where the API
serves them. The worker runs on the developer laptop; no hosted GPU or Hugging Face Space is used.

## Prerequisites

- The pipeline requirements installed (root `README.md`, "Setup") and the backend requirements in
  `backend/.venv` (`backend/README.md`, "Setup").
- The four model files in `models/` (root `README.md`).
- The API already deployed, so migrations are applied. The worker refuses to start on an older schema.

## Environment variables

| Variable | Value |
|---|---|
| `PIYA_DATABASE_URL` | Neon **unpooled** (direct) connection string, the same one Render uses as `DATABASE_URL`. |
| `PIYA_STORAGE_BACKEND` | `db` |
| `PIYA_MEDIA_HMAC_KEY` | Exactly the same value as on Render, so links signed by one side verify on the other. |
| `PIYA_PUBLIC_BASE_URL` | The Render URL, starting with `https://`. |

Model paths are read from `models/` unless `PIYA_YOLO_WEIGHTS`, `PIYA_CRNN_WEIGHTS`, `PIYA_CLEFKEY_WEIGHTS` or
`PIYA_SOUNDFONT` is set. Never write these values into a tracked file.

## Start

From the repository root:

```
backend/.venv/Scripts/python -m backend.worker --loop
```

Leave it running while testing the app. If a pipeline hangs past the runtime cap the worker exits with code 3;
restart it (see `backend/README.md`, "Worker hung past the runtime cap"). End-to-end check on real photos:
`python -m backend.scripts.smoke_convert`.
