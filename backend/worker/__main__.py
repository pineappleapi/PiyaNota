"""``python -m backend.worker --once | --loop [--health-port N]``."""

from __future__ import annotations

import os

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # CPU only; must be set before torch is imported

from backend.worker.main import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli())
