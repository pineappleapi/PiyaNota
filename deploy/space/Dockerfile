# Hugging Face Space (Docker SDK, CPU basic). The build context is the Space repo root, laid out as
# docs/deploy-hf-space.md describes: backend/, the stage modules, models/, and this directory's files.
# Not built on the dev machine (no Docker): the first build happens on Hugging Face.
FROM python:3.12.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CUDA_VISIBLE_DEVICES=-1 \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    PIYA_ENV=prod \
    PIYA_REQUIRE_HTTPS=true \
    PIYA_MAIL_BACKEND=log \
    PIYA_MAIL_FROM=noreply@piyanota.invalid \
    PIYA_YOLO_WEIGHTS=/app/models/best.pt \
    PIYA_CRNN_WEIGHTS=/app/models/phase2_seed1.pt \
    PIYA_CLEFKEY_WEIGHTS=/app/models/clef_key_classifier.pt \
    PIYA_SOUNDFONT=/app/models/piano.sf2

# fluidsynth + ffmpeg: Stage 5 renders MIDI to WAV to MP3. libgl1/libglib2.0-0: opencv-python imports them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fluidsynth ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 piya
WORKDIR /app

COPY requirements-worker.txt requirements-worker.txt
RUN pip install -r requirements-worker.txt

COPY backend/ backend/
COPY stage1_preprocessing.py stage2_detection.py stage3_transcription.py stage3_clefkey.py \
     stage4_reconstruction.py stage5_synthesis.py timing_export.py clef_key_core.py \
     clef_voice_rules.py ./
COPY models/ models/
COPY entrypoint.sh entrypoint.sh
# A Windows checkout may have turned the line endings into CRLF, which breaks the script.
RUN sed -i 's/\r$//' entrypoint.sh

USER piya
EXPOSE 7860
CMD ["sh", "entrypoint.sh"]
