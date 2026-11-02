# Build context is the repo root (render.yaml: dockerfilePath backend/Dockerfile); only backend/ is copied.
# Exact patch tag (NFR-11). Not built or run on the dev machine (no Docker): first build is on Render.
FROM python:3.12.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIYA_RUN_BACKGROUND=1

RUN useradd --create-home --uid 10001 piya
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
USER piya

# One worker: 512 MB RAM, and one worker means exactly one background loop (PIYA_RUN_BACKGROUND).
# Shell form so ${PORT} expands; Render injects PORT. migrate reads DATABASE_URL.
CMD python -m backend.migrate up && exec gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT:-10000} --timeout 120 "backend.app:create_app()"
