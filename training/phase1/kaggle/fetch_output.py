r"""Resumable, low-memory download of a Kaggle kernel's output files.

`kaggle kernels output` is unusable for the Phase 1 re-cut (about 29k files): it recurses once per 20-file page and
keeps every page's response (each carrying the full run log) alive on the stack, and it reads each file whole into
memory before writing. On 2026-10-08 that pushed the dev PC into low memory twice and the download was killed.

This script lists one page at a time in a loop and streams each file in 1 MiB chunks to `<name>.part`, renaming it
only after the byte count matches Content-Length. A file under its final name is therefore always complete, so a
rerun skips it without any network call, and a stop loses at most the file in flight. The page token is saved after
each page; if the server rejects a saved token the listing restarts from page 1 (finished files are still skipped).

Usage: python fetch_output.py <owner/kernel-slug> <dest_dir> [--pattern REGEX]
  --pattern keeps only files whose output path matches REGEX (re.search), e.g. the Phase 2 metrics and best
  checkpoints: --pattern "(metrics|summary|run_info)\.json$|phase2_seed\d\.pt$". Other files are listed but not downloaded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest

PAGE_SIZE = 200
CHUNK_BYTES = 1 << 20
MAX_TRIES = 6
HTTP_TIMEOUT_S = 120
STATE_NAME = ".fetch_state.json"
PROGRESS_EVERY = 500
# Per-file latency (a fresh TLS handshake to a signed URL) dominated at ~1 file/s; keep-alive sessions plus a few
# threads fix that. Each thread holds one chunk, so peak memory stays around WORKERS x CHUNK_BYTES.
WORKERS = 8

_local = threading.local()


def session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def safe_target(dest: Path, name: str) -> Path:
    """Map a server-supplied name to a path inside dest; refuse anything that escapes it."""
    target = (dest / name).resolve()
    if dest not in target.parents:
        raise ValueError(f"refusing output path outside {dest}: {name!r}")
    return target


def fetch_one(url: str, target: Path) -> int:
    """Stream url to target via target.part; return bytes written. Raises after MAX_TRIES failures."""
    part = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, MAX_TRIES + 1):
        try:
            with session().get(url, stream=True, timeout=HTTP_TIMEOUT_S) as r:
                r.raise_for_status()
                expected = r.headers.get("Content-Length")
                written = 0
                with part.open("wb") as f:
                    for chunk in r.iter_content(CHUNK_BYTES):
                        f.write(chunk)
                        written += len(chunk)
            if expected is not None and written != int(expected):
                raise IOError(f"short read {written}/{expected}")
            part.replace(target)
            return written
        except (requests.RequestException, IOError) as e:
            wait = min(60, 2 ** attempt)
            log(f"retry {attempt}/{MAX_TRIES} {target.name}: {e!r}; sleeping {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"giving up on {target}")


def list_page(api: KaggleApi, owner: str, slug: str, token: str | None):
    with api.build_kaggle_client() as k:
        req = ApiListKernelSessionOutputRequest()
        req.user_name, req.kernel_slug, req.page_size = owner, slug, PAGE_SIZE
        if token:
            req.page_token = token
        return k.kernels.kernels_api_client.list_kernel_session_output(req)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("dest")
    ap.add_argument("--pattern", type=re.compile, default=None)
    a = ap.parse_args()
    owner, slug = a.kernel.split("/")
    dest = Path(a.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    state_path = dest / STATE_NAME
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    token: str | None = state.get("next_page_token")

    api = KaggleApi()
    api.authenticate()
    got = skipped = nbytes = 0
    page_no = 0
    pool = ThreadPoolExecutor(WORKERS)
    while True:
        try:
            resp = list_page(api, owner, slug, token)
        except requests.HTTPError as e:
            if token is None:
                raise
            log(f"saved page token rejected ({e!r}); relisting from page 1")
            token = None
            continue
        page_no += 1
        todo = []
        for item in resp.files or []:
            if a.pattern is not None and not a.pattern.search(item.file_name):
                continue
            target = safe_target(dest, item.file_name)
            if target.exists():
                skipped += 1
            else:
                todo.append((item.url, target))
        # The whole page finishes (or raises) before its token is saved, so a resume never skips an unfinished file.
        for n in pool.map(lambda a: fetch_one(*a), todo):
            nbytes += n
            got += 1
            if got % PROGRESS_EVERY == 0:
                log(f"downloaded {got} files ({nbytes / 2**20:.0f} MiB), skipped {skipped}, page {page_no}")
        token = resp.next_page_token or None
        state_path.write_text(json.dumps({"next_page_token": token}))
        if not token:
            break
    pool.shutdown()
    state_path.unlink(missing_ok=True)
    log(f"DONE downloaded {got} files ({nbytes / 2**20:.0f} MiB), skipped {skipped} already present")


if __name__ == "__main__":
    main()
