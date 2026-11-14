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

Keep them in a launcher script **outside the repo** (it holds secrets), for example
`D:\PiyaNota-worker\start-worker.ps1`.

| Variable | Value |
|---|---|
| `PIYA_ENV` | `prod` (then the variables below marked required must be set, or the worker stops with a message naming the missing one). |
| `PIYA_DATABASE_URL` | Neon **unpooled** (direct) connection string, the same one Render uses as `DATABASE_URL`. |
| `PIYA_STORAGE_BACKEND` | `db` |
| `PIYA_MEDIA_HMAC_KEY` | Exactly the same value as on Render, so links signed by one side verify on the other. |
| `PIYA_PUBLIC_BASE_URL` | The Render URL, starting with `https://`. |
| `PIYA_RESET_CODE_HMAC_KEY`, `PIYA_LOG_HASH_KEY` | Long random strings; required in prod. |
| `PIYA_REQUIRE_HTTPS` | `true` |
| `PIYA_MAIL_BACKEND`, `PIYA_MAIL_FROM` | `log` and any sender address; the worker sends no mail, but prod needs them set. |
| `CUDA_VISIBLE_DEVICES` | `-1` to force CPU (what the golden check uses); omit to use an NVIDIA GPU. |

Model paths default to the repo's `models/` folder. Set `PIYA_YOLO_WEIGHTS`, `PIYA_CRNN_WEIGHTS`,
`PIYA_CLEFKEY_WEIGHTS` and `PIYA_SOUNDFONT` only to point somewhere else. Never write these values into a
tracked file.

## Start

The last two lines of the launcher: go to the repository root, then start the worker with the Python that has the
requirements installed.

```
Set-Location D:\PiyaNota
backend/.venv/Scripts/python -m backend.worker --loop
```

Leave it running while testing the app. If a pipeline hangs past the runtime cap the worker exits with code 3;
restart it (see `backend/README.md`, "Worker hung past the runtime cap"). End-to-end check on real photos:
`python -m backend.scripts.smoke_convert`.
