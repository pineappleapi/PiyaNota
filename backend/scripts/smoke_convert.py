"""Local end-to-end smoke of the conversion worker on real photos, CPU only.

Run from the repo root with the backend venv (psycopg, Flask) while the test Postgres is up:

    CUDA_VISIBLE_DEVICES=-1 PIYA_PIPELINE_PYTHON=<python with torch> PIYA_YOLO_WEIGHTS=... \
        backend/.venv/Scripts/python -m backend.scripts.smoke_convert <photo> [<photo> ...]

The backend venv has no torch/cv2 and the pipeline venv has no psycopg, so ``process_one`` runs in this
process and its ``runner`` runs ``run_pipeline`` in a child process (``--child``) under
PIYA_PIPELINE_PYTHON; stage events stream back over stdout so the job status still moves live.
Uses the local test database only (refuses anything but localhost/piya_test).
"""

from __future__ import annotations

import dataclasses
import io
import json
import math
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TEST_DB_HOSTS = ("localhost", "127.0.0.1")
TEST_DB_PORT = 55432
TEST_DB_NAME = "piya_test"
STAGE_PREFIX = "STAGE "
TEST_DB_URL = "postgresql://piya:piya@localhost:55432/piya_test"
RANGE_BYTES = 1024
MIN_MP3_BYTES = 1000
REPO_ROOT = Path(__file__).resolve().parents[2]


def check_test_db(url: str) -> None:
    """Refuse anything but the local test database; the smoke truncates every table.

    Raises:
        SystemExit: host, port or database name is not exactly the local test database.
    """
    refuse = SystemExit("refusing non-test database (need localhost:55432/piya_test)")
    # libpq reparses what urlparse splits off (e.g. "#?host=evil" becomes host=evil), so refuse it all.
    if any(c.isspace() or not c.isprintable() for c in url):
        raise refuse
    parts = urlparse(url)
    try:
        port = parts.port
    except ValueError:  # malformed port
        port = None
    # libpq lets ?dbname=/?host=/?port= override the components, so any query, params or fragment is refused.
    if (parts.scheme not in ("postgresql", "postgres") or parts.query or parts.params or parts.fragment
            or parts.hostname not in TEST_DB_HOSTS or port != TEST_DB_PORT or parts.path != f"/{TEST_DB_NAME}"):
        raise refuse
    # Defence in depth: ask libpq's own parser what it would connect to.
    try:
        from psycopg.conninfo import conninfo_to_dict

        info = conninfo_to_dict(url)
    except Exception as exc:  # any parse failure fails closed
        raise refuse from exc
    if (info.get("host") not in TEST_DB_HOSTS or str(info.get("port")) != str(TEST_DB_PORT)
            or info.get("dbname") != TEST_DB_NAME or "hostaddr" in info or "service" in info):
        raise refuse


def _child(args_path: str, out_path: str) -> int:
    """Child process: run the real pipeline, report stages on stdout, pickle the result."""
    sys.path.insert(0, str(REPO_ROOT))
    from backend.worker.pipeline import PipelineConfig, PipelineError, run_pipeline

    payload = pickle.loads(Path(args_path).read_bytes())

    def on_stage(status: str, percent: int) -> None:
        print(f"{STAGE_PREFIX}{status} {percent}", flush=True)

    try:
        out: Any = run_pipeline(payload["jpegs"], tempo_bpm=payload["tempo_bpm"], work_dir=Path(payload["work_dir"]),
                                config=PipelineConfig.from_env(os.environ), on_stage=on_stage, timing=payload["timing"])
    except PipelineError as exc:
        out = exc
    Path(out_path).write_bytes(pickle.dumps(out))
    return 0


def _make_runner() -> Any:
    python = os.environ["PIYA_PIPELINE_PYTHON"]

    def runner(page_jpegs: list[bytes], *, tempo_bpm: int, work_dir: Path, on_stage: Any, timing: bool) -> Any:
        tmp = Path(tempfile.mkdtemp(prefix="piya-smoke-child-"))
        args, out = tmp / "args.pkl", tmp / "out.pkl"
        args.write_bytes(pickle.dumps({"jpegs": page_jpegs, "tempo_bpm": tempo_bpm,
                                       "work_dir": str(work_dir), "timing": timing}))
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1"}  # empty string would crash ultralytics
        proc = subprocess.Popen([python, "-I", str(Path(__file__).resolve()), "--child", str(args), str(out)],
                                stdout=subprocess.PIPE, text=True, env=env)
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith(STAGE_PREFIX):
                status, percent = line[len(STAGE_PREFIX):].split()
                on_stage(status, int(percent))
        if proc.wait() != 0 or not out.exists():
            raise RuntimeError(f"pipeline child exited {proc.returncode}")
        result = pickle.loads(out.read_bytes())
        if isinstance(result, Exception):
            raise result
        return result

    return runner


def _validate_timing(timing: dict[str, Any], page_sizes: list[dict[str, int]]) -> dict[str, Any]:
    """Mirror TimingEvent.tryParse (Flutter score_result.dart): every entry must be placeable."""
    events = timing.get("events")
    assert isinstance(events, list), "timing has no events list"
    bad = 0
    for e in events:
        ok = (isinstance(e.get("timestampMs"), (int, float)) and e["timestampMs"] >= 0
              and isinstance(e.get("pageIndex"), int) and 0 <= e["pageIndex"] < len(page_sizes)
              and isinstance(e.get("x"), (int, float)) and isinstance(e.get("y"), (int, float))
              and e["x"] >= 0 and e["y"] >= 0)
        bad += not ok
    max_x = max((e["x"] for e in events), default=0)
    max_y = max((e["y"] for e in events), default=0)
    bars = timing.get("bars", [])
    last_x: dict[tuple[Any, Any], float] = {}
    bad_bars = 0
    for b in bars:  # bars arrive sorted by startTick, so x must rise within one (page, system)
        page = b.get("pageIndex")
        x = b.get("x")
        ok = (isinstance(page, int) and 0 <= page < len(page_sizes) and isinstance(x, (int, float))
              and math.isfinite(x) and 0 <= x <= page_sizes[page]["width"]
              and x > last_x.get((page, b.get("systemIndex")), -1.0))
        bad_bars += not ok
        if isinstance(x, (int, float)):
            last_x[(page, b.get("systemIndex"))] = x
    return {"events": len(events), "unplaceable": bad, "bad_bars": bad_bars, "max_x": max_x, "max_y": max_y,
            "voices": sorted({e.get("voice") for e in events if e.get("voice")}),
            "bars": len(timing.get("bars", []))}


def _app_like_jpeg(path: Path) -> bytes:
    """Bake EXIF orientation and strip EXIF, as the Flutter app does before upload (page_image_processor.dart).

    The server ignores EXIF on purpose, so a raw camera JPEG with orientation 6 would arrive sideways.
    """
    from PIL import Image, ImageOps

    buf = io.BytesIO()
    ImageOps.exif_transpose(Image.open(path)).convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()


def run(photos: list[Path]) -> int:
    from backend import db, migrate
    from backend.app import create_app
    from backend.config import load_settings
    from backend.worker.main import process_one
    import psycopg

    url = os.environ.get("TEST_DATABASE_URL", TEST_DB_URL)
    check_test_db(url)
    base = "http://localhost"
    settings = dataclasses.replace(
        load_settings({"PIYA_ENV": "test", "PIYA_DATABASE_URL": url, "PIYA_STORAGE_BACKEND": "db",
                       "PIYA_MAIL_BACKEND": "memory", "PIYA_ARGON2_TIME_COST": "1", "PIYA_ARGON2_MEMORY_KIB": "8"}),
        public_base_url=base)
    with psycopg.connect(url, autocommit=True) as conn:
        migrate.up(conn)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    with db.transaction() as conn:  # test database only: start from an empty queue
        names = [r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
            if r["tablename"] != "schema_migrations"]
        conn.execute("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE")

    pw = "smoke-pass-1"
    res = client.post("/api/auth/signup", json={"email": "smoke-convert@example.com", "password": pw,
                                                "passwordConfirmation": pw})
    assert res.status_code == 201, res.get_json()
    headers = {"Authorization": f"Bearer {res.get_json()['data']['sessionToken']}"}

    form: dict[str, Any] = {"title": "Moonriver", "tempoBpm": "90",
                            "pages": [(io.BytesIO(_app_like_jpeg(p)), p.name) for p in photos]}
    res = client.post("/api/jobs", data=form, headers=headers, content_type="multipart/form-data")
    assert res.status_code == 202, res.get_json()
    job_ref = res.get_json()["data"]["jobId"]
    job_id = int(job_ref.removeprefix("job_"))
    print(f"submitted {job_ref} with {len(photos)} pages")

    seen: list[tuple[str, float]] = []
    inner = _make_runner()

    def runner(*a: Any, on_stage: Any, **kw: Any) -> Any:
        def tap(status: str, percent: int) -> None:
            seen.append((status, time.monotonic()))
            on_stage(status, percent)
        return inner(*a, on_stage=tap, **kw)

    started = time.monotonic()
    done = process_one(storage=app.extensions["storage"], runner=runner, settings=settings)
    total_s = time.monotonic() - started
    assert done, "no job was claimed"
    with db.transaction() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    print(f"job status={job['status']} failure_reason={job['failure_reason']}")
    if job["status"] != "complete":
        return 1

    stage_s = {s: round(t2 - t1, 1) for (s, t1), (_, t2) in zip(seen, [*seen[1:], ("end", time.monotonic())])}
    res = client.get(f"/api/scores/{job['score_id']}/result", headers=headers)
    assert res.status_code == 200, res.get_json()
    data = res.get_json()["data"]
    mp3_bytes: dict[str, int] = {}
    for voice, url_ in data["audioTracks"].items():
        path = url_.removeprefix(base)
        part = client.get(path, headers={"Range": f"bytes=0-{RANGE_BYTES - 1}"})
        assert part.status_code == 206 and len(part.data) == RANGE_BYTES, (voice, part.status_code)
        full = client.get(path)
        assert full.status_code == 200 and len(full.data) > MIN_MP3_BYTES, voice
        mp3_bytes[voice] = len(full.data)
    timing_raw = client.get(data["timingMetadataUrl"].removeprefix(base), headers={"Range": "bytes=0-"})
    assert timing_raw.status_code == 206
    timing = _validate_timing(timing_raw.get_json(), data["scoreImageSizes"])
    images = [client.get(u.removeprefix(base)) for u in data["scoreImages"]]
    assert all(i.status_code == 200 and i.data[:2] == b"\xff\xd8" for i in images)

    with db.transaction() as conn:
        keys = [r["file_key"] for r in conn.execute("SELECT file_key FROM audio_tracks").fetchall()]
        keys += [r["metadata_key"] for r in conn.execute("SELECT metadata_key FROM timing_metadata").fetchall()]
        keys += [r["object_key"] for r in conn.execute("SELECT object_key FROM job_pages").fetchall()]
        keys += [r["thumbnail_key"] for r in conn.execute("SELECT thumbnail_key FROM scores").fetchall()
                 if r["thumbnail_key"]]
        stored = conn.execute("SELECT coalesce(sum(octet_length(data)), 0) AS n FROM blobs "
                              "WHERE key = ANY(%s)", (keys,)).fetchone()["n"]
        everything = conn.execute("SELECT coalesce(sum(octet_length(data)), 0) AS n FROM blobs").fetchone()["n"]
    report = {"pages": len(photos), "total_s": round(total_s, 1), "per_page_s": round(total_s / len(photos), 1),
              "stage_s": stage_s, "mp3_bytes": mp3_bytes, "cleaned_page_sizes": data["scoreImageSizes"],
              "cleaned_page_bytes": [len(i.data) for i in images], "score_blob_bytes": int(stored),
              "all_blob_bytes_incl_pending_delete": int(everything), "timing": timing,
              "failedVoices": data["failedVoices"], "review": data["review"]}
    print("REPORT " + json.dumps(report, indent=2))
    db.close_pool()
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        sys.exit(_child(sys.argv[2], sys.argv[3]))
    sys.exit(run([Path(a) for a in sys.argv[1:]]))
