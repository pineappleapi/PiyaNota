---
title: PiyaNota Worker
emoji: 🎼
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

PiyaNota conversion worker: polls the job queue in Postgres, runs the OMR pipeline on CPU and
stores the MP3 results. It serves only `GET /health`.
