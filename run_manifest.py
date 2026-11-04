"""
PiyaNota - Run Manifest (provenance tracking for image -> audio runs)

Writes one manifest.json per pipeline run under runs/omr/<run_id>/ recording
which checkpoints, inputs, settings and environment produced a given set of
outputs, plus the raw CRNN tokens/confidences per strip.

Why this exists: Stage 3's events JSON, strips and viz PNGs are overwritten on
every run and carry no record of which CRNN checkpoint produced them. During
BUG-011 diagnosis it was impossible to tell from the files alone whether the
base Camera-PrIMuS checkpoint or a fine-tuned seed had been used. Checkpoints
are identified by SHA-256, not path, because the same filename has held
different weights (and weights move between Downloads/, crnn_weights/, etc.).

Stages accept an optional `manifest` argument and stay fully usable without
one; the manifest is purely additive and never changes pipeline outputs.
"""

import datetime as _dt
import hashlib
import json
import logging
import platform
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from types import TracebackType
from typing import Dict, Iterator, List, Optional, Sequence, Type, Union

logger = logging.getLogger(__name__)

# Bump when the manifest's top-level shape changes, so old manifests can still
# be parsed correctly by anything that compares runs.
SCHEMA_VERSION = 1

DEFAULT_RUNS_ROOT = "runs/omr"
HASH_CACHE_FILENAME = ".hash_cache.json"
HASH_CHUNK_BYTES = 1 << 20          # 1 MiB read chunks keep memory flat on ~100 MB checkpoints
CONFIDENCE_DECIMALS = 4
GIT_TIMEOUT_SECONDS = 10

# Distributions whose versions materially change pipeline output. Looked up
# via importlib.metadata so recording them never imports the heavy packages.
TRACKED_PACKAGES = (
    "torch", "torchvision", "ultralytics", "opencv-python",
    "opencv-python-headless", "numpy", "midiutil", "pydub", "midi2audio",
)

JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]


def sha256_file(path: Union[str, Path], cache_path: Optional[Path] = None) -> str:
    """Returns the SHA-256 hex digest of a file, cached by (size, mtime).

    Hashing a checkpoint costs ~1s per run; the cache avoids repeating it while
    still invalidating the moment the file is replaced or retouched.

    Args:
        path: File to hash.
        cache_path: Optional JSON cache file. Corrupt/unreadable caches are
          ignored (and rebuilt) rather than failing the run.

    Returns:
        Lowercase hex digest.
    """
    p = Path(path).resolve()
    stat = p.stat()
    key = str(p)
    fingerprint = [stat.st_size, stat.st_mtime_ns]

    cache: Dict[str, Dict[str, JsonValue]] = {}
    if cache_path is not None and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable hash cache %s: %s", cache_path, exc)
            cache = {}
        entry = cache.get(key)
        if entry is not None and entry.get("fingerprint") == fingerprint:
            return str(entry["sha256"])

    digest = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    hexdigest = digest.hexdigest()

    if cache_path is not None:
        cache[key] = {"fingerprint": fingerprint, "sha256": hexdigest}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write hash cache %s: %s", cache_path, exc)
    return hexdigest


def _git_info(repo_dir: Path) -> Dict[str, JsonValue]:
    """Records commit + dirty state; results are only reproducible from a clean tree."""
    def run(args: Sequence[str]) -> str:
        # Only trailing newlines are stripped: porcelain lines start with a
        # significant status column (" M path"), which a full strip() would eat.
        return subprocess.run(
            ["git", *args], cwd=repo_dir, capture_output=True, text=True,
            check=True, timeout=GIT_TIMEOUT_SECONDS,
        ).stdout.rstrip("\n")

    try:
        commit = run(["rev-parse", "HEAD"]).strip()
        branch = run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        # Untracked files (scratch images, notebooks) are excluded: they don't
        # affect the stage scripts, and including them would flag every run dirty.
        dirty_files = [
            line[3:] for line in run(["status", "--porcelain", "--untracked-files=no"]).splitlines()
        ]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("Git info unavailable: %s", exc)
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "commit": commit,
        "branch": branch,
        "dirty": bool(dirty_files),
        "dirty_files": dirty_files,
    }


def _environment_info() -> Dict[str, JsonValue]:
    packages: Dict[str, JsonValue] = {}
    for name in TRACKED_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None

    env: Dict[str, JsonValue] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
    }
    # torch is optional here: Stage 1/2-only callers shouldn't need it installed.
    try:
        import torch
    except ImportError:
        env["torch_runtime"] = None
        return env

    cuda_available = torch.cuda.is_available()
    env["torch_runtime"] = {
        "cuda_available": cuda_available,
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version() if cuda_available else None,
        "device_name": torch.cuda.get_device_name(0) if cuda_available else "cpu",
    }
    return env


class RunManifest:
    """Accumulates provenance for one pipeline run and writes it as JSON.

    Use as a context manager so the manifest is written even when a stage
    raises -- failed runs are the ones most worth tracing.

    Example:
        with RunManifest(args=vars(args)) as manifest:
            pages = preprocess_batch(..., manifest=manifest)
            ...
    """

    def __init__(
        self,
        runs_root: str = DEFAULT_RUNS_ROOT,
        args: Optional[Dict[str, JsonValue]] = None,
        repo_dir: Optional[str] = None,
    ) -> None:
        started = _dt.datetime.now().astimezone()
        self.run_id: str = f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.runs_root = Path(runs_root)
        self.run_dir = self.runs_root / self.run_id
        self._hash_cache = self.runs_root / HASH_CACHE_FILENAME
        self._t0 = time.perf_counter()
        repo = Path(repo_dir) if repo_dir else Path(__file__).resolve().parent

        self.data: Dict[str, JsonValue] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": "running",
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": None,
            "duration_s": None,
            "argv": list(sys.argv),
            "args": args or {},
            "git": _git_info(repo),
            "environment": _environment_info(),
            "assets": {},
            "params": {},
            "inputs": [],
            "stages": {},
            "strips": [],
            "outputs": {},
            "error": None,
        }

    # ── Recording helpers ────────────────────────────────────────────────────

    def add_asset(self, role: str, path: Union[str, Path],
                  extra: Optional[Dict[str, JsonValue]] = None) -> None:
        """Records a model/soundfont/etc. by hash so renamed or moved files stay traceable.

        A missing asset is recorded (not raised) because some are optional --
        e.g. Stage 5 falls back to .mid output when the soundfont is absent.
        """
        p = Path(path)
        entry: Dict[str, JsonValue] = {"path": str(p), "exists": p.is_file()}
        if p.is_file():
            stat = p.stat()
            entry.update({
                "abs_path": str(p.resolve()),
                "sha256": sha256_file(p, self._hash_cache),
                "size_bytes": stat.st_size,
                "modified_at": _dt.datetime.fromtimestamp(stat.st_mtime).astimezone()
                               .isoformat(timespec="seconds"),
            })
        if extra:
            entry.update(extra)
        self.data["assets"][role] = entry  # type: ignore[index]

    def set_params(self, **params: JsonValue) -> None:
        self.data["params"].update(params)  # type: ignore[union-attr]

    def add_input(self, page_index: int, path: Union[str, Path],
                  preprocessed_path: Optional[Union[str, Path]] = None) -> None:
        p = Path(path)
        self.data["inputs"].append({  # type: ignore[union-attr]
            "page_index": page_index,
            "path": str(p),
            "sha256": sha256_file(p),
            "preprocessed_path": str(preprocessed_path) if preprocessed_path else None,
        })

    def add_stage_info(self, stage: str, **info: JsonValue) -> None:
        self.data["stages"].setdefault(stage, {}).update(info)  # type: ignore[union-attr]

    def add_strip(
        self,
        strip_id: str,
        voice: str,
        page_index: int,
        sys_idx: int,
        v_idx: int,
        tokens: Sequence[str],
        confidences: Sequence[float],
        n_events: int,
        strip_shape: Sequence[int],
    ) -> None:
        """Records the raw pre-infer_pitch CRNN output, which is otherwise only logged.

        Raw tokens are what ground-truth comparisons (BUG-011-style) need;
        events alone lose clefs, key signatures and barlines.
        """
        rounded = [round(float(c), CONFIDENCE_DECIMALS) for c in confidences]
        self.data["strips"].append({  # type: ignore[union-attr]
            "strip_id": strip_id,
            "voice": voice,
            "page_index": page_index,
            "sys_idx": sys_idx,
            "v_idx": v_idx,
            "strip_shape_hw": list(strip_shape[:2]),
            "n_tokens": len(tokens),
            "n_events": n_events,
            "mean_confidence": (round(sum(rounded) / len(rounded), CONFIDENCE_DECIMALS)
                                if rounded else None),
            "tokens": list(tokens),
            "confidences": rounded,
        })

    def add_output(self, role: str, path: Union[str, Path]) -> None:
        """Hashes outputs so a later file on disk can be matched back to this run
        (the pipeline overwrites the same paths every run)."""
        p = Path(path)
        entry: Dict[str, JsonValue] = {"path": str(p), "exists": p.is_file()}
        if p.is_file():
            entry["sha256"] = sha256_file(p)
        self.data["outputs"][role] = entry  # type: ignore[index]

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Times a stage and records which one failed, then re-raises."""
        t = time.perf_counter()
        info = self.data["stages"].setdefault(name, {})  # type: ignore[union-attr]
        info["status"] = "running"
        try:
            yield
        except BaseException:
            info["status"] = "failed"
            raise
        else:
            info["status"] = "completed"
        finally:
            info["duration_s"] = round(time.perf_counter() - t, 3)

    # ── Output ───────────────────────────────────────────────────────────────

    def write(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        out = self.run_dir / "manifest.json"
        with open(out, "w", encoding="utf-8") as f:
            # default=str: an unexpected non-JSON-serializable value in a stage's
            # recorded extras (e.g. a checkpoint's own `epoch` field, whose type
            # depends on how the training notebook serialized it) should degrade to
            # a string in the manifest, not raise and mask the pipeline's exception.
            json.dump(self.data, f, indent=2, default=str)
        return out

    def __enter__(self) -> "RunManifest":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        finished = _dt.datetime.now().astimezone()
        self.data["finished_at"] = finished.isoformat(timespec="seconds")
        self.data["duration_s"] = round(time.perf_counter() - self._t0, 3)
        if exc is None:
            self.data["status"] = "completed"
        else:
            self.data["status"] = "failed"
            self.data["error"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(exc_type, exc, tb)),
            }
        # A manifest write failure must not mask the pipeline's own exception.
        try:
            out = self.write()
            print(f"[Manifest] {self.data['status']} run {self.run_id} -> {out}")
        except (OSError, TypeError, ValueError) as write_exc:
            # OSError: filesystem failure. TypeError/ValueError: JSON serialization
            # failure (default=str above should prevent this, but don't rely on it).
            # Either way, a manifest write failure must not mask a real pipeline
            # exception that's already propagating -- only re-raise it standalone.
            logger.error("Failed to write run manifest %s: %s", self.run_dir, write_exc)
            if exc is None:
                raise
