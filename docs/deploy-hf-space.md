# Deploy the conversion worker to a Hugging Face Space

The worker runs on a free CPU Space (Docker). The API stays on Render. Both share the Neon database,
and results are stored in the database (`PIYA_STORAGE_BACKEND=db`). This file was written without being
able to build the image (Docker is not available on the dev machine), so the first Space build is the
first real test.

## Which variables are secrets

Set these as Space **Secrets** (Settings, Variables and secrets, New secret):
`PIYA_DATABASE_URL`, `PIYA_MEDIA_HMAC_KEY`, `PIYA_RESET_CODE_HMAC_KEY`, `PIYA_LOG_HASH_KEY`.

Set these as plain Space **Variables** (not secret): `PIYA_STORAGE_BACKEND` (value `db`) and
`PIYA_PUBLIC_BASE_URL` (the Render URL, starting with `https://`).

The image already sets `PIYA_ENV=prod`, `PIYA_REQUIRE_HTTPS=true`, `PIYA_MAIL_BACKEND=log`,
`PIYA_MAIL_FROM` and the four model paths. Do not set them again. Production mode makes the worker
refuse to start unless the reset-code and log-hash keys are present, which is why they are listed above.
The values of `PIYA_MEDIA_HMAC_KEY`, `PIYA_RESET_CODE_HMAC_KEY` and `PIYA_LOG_HASH_KEY` should be long
random strings. The worker needs the same `PIYA_MEDIA_HMAC_KEY` as Render so that links signed by one
side are accepted by the other.

## Steps

1. Create the Space at huggingface.co/new-space. Choose SDK `Docker`, template `Blank`, hardware
   `CPU basic (free)`, visibility Private. Confirm that the page does not ask for a payment card. If it does, stop here.
2. Create a Hugging Face access token with **write** access at huggingface.co/settings/tokens. Use it as the password
   when the clone and push commands below ask for credentials.
3. Run all migrations against Neon with the **unpooled** connection string, before the worker exists. Render's start command
   runs `python -m backend.migrate up` on every boot, so step 6 applies it too. To do it by hand from the repository root:
   set `DATABASE_URL` to the unpooled string, then run `backend/.venv/Scripts/python -m backend.migrate up`, then
   `backend/.venv/Scripts/python -m backend.migrate status`. Every migration in `backend/migrations` must show as applied (latest is 0005); the worker refuses to start otherwise.
4. Open the Space, then Settings, then Variables and secrets. Add the four secrets and the two variables from the section above.
   For `PIYA_DATABASE_URL` use the Neon **unpooled** (direct) connection string, the same one that Render uses as `DATABASE_URL`.
5. On your PC, install Git LFS once with `git lfs install`, then clone the Space:
   `git clone https://huggingface.co/spaces/<your-user>/<space-name> piya-space`.
   Then copy the packaging files and the code into the clone. Run these from the repository root, replacing `<space>` with the clone path:
   - `cp deploy/space/Dockerfile deploy/space/README.md deploy/space/entrypoint.sh deploy/space/requirements-worker.txt deploy/space/.dockerignore <space>/`
   - Do **not** overwrite `<space>/.gitattributes`. Hugging Face created it with default LFS patterns. Append ours instead:
     `cat deploy/space/.gitattributes >> <space>/.gitattributes`
   - `cp -r backend <space>/backend`, then delete `<space>/backend/.venv`, `<space>/backend/tests` and every `__pycache__` folder if they were copied.
   - `cp stage1_preprocessing.py stage2_detection.py stage3_transcription.py stage3_clefkey.py stage4_reconstruction.py stage5_synthesis.py timing_export.py clef_key_core.py clef_voice_rules.py <space>/`
6. On the Render service, **change** the existing `PIYA_STORAGE_BACKEND` variable from `memory` to `db`. The repository's `render.yaml`
   now says `db`, so a blueprint sync keeps it. Also set `PIYA_MEDIA_HMAC_KEY` (same value as the Space) and `PIYA_PUBLIC_BASE_URL`
   (the Render service URL, starting with `https://`). Render then redeploys and applies the migration.
7. Copy the model files into `<space>/models/` under exactly these names. The source paths are in the main checkout (`D:/PiyaNota`),
   because the weights are not in this worktree:
   - `staff_detector_files/weights/best.pt` as `models/best.pt`
   - `music_symbol_detection/phase2_kaggle_models/seed1/phase2_seed1.pt` as `models/phase2_seed1.pt`
   - `training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt` as `models/clef_key_classifier.pt`
     (this file is ignored by version control in the main repository, so it exists only on your PC; without it every job fails with a "missing model file" log line)
   - `soundfont/piano.sf2` as `models/piano.sf2`
   Check the ClefKeyNet copy with `sha256sum models/clef_key_classifier.pt`. The expected value is
   `e718d4479b1310369b64cfaf9a8f1ff433179543ffa9d1810b24c683de13fe10`.
8. In the Space clone, run `git add .`, then `git commit -m "Add conversion worker"`, then `git push`.
   The push uploads about 160 MB through Git LFS. Hugging Face then builds the image, which takes several minutes.
9. Watch the Logs tab of the Space. A healthy start prints `Running` and no tracebacks. Then open
   `https://<your-user>-<space-name>.hf.space/health`. It must answer `ok`.
10. Add an UptimeRobot monitor: type HTTP(s), URL `https://<your-user>-<space-name>.hf.space/health`, interval 5 minutes.
    This ping stops the free Space from sleeping. Add a second monitor for Render at `/healthz`.
11. Submit one real conversion from the app. In the Space logs you must see `job claimed`. When the job finishes the app shows the audio.

## Backup (run on your PC)

Media is stored in the database, so back up the database regularly. This needs the PostgreSQL client tools. Use the unpooled URL:

`pg_dump "<unpooled Neon URL>" --format=custom --file=D:/PiyaNota-backups/piya-$(date +%F).dump`

Create the `D:/PiyaNota-backups` folder first. Restore with `pg_restore --clean --dbname "<target URL>" <file>`.

## Known limits

- The free Space has 2 CPU cores and 16 GB RAM. A multi-page score may take several minutes per job.
- The Space restarts on every push. A job that was running is recovered by the queue after its stale timeout (1200 seconds).
- If you change model files, push the new files under the same names in `models/`.
