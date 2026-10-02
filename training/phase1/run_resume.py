"""Auto-resume wrapper for `cut_corpus.py run` (BUG-044).

Why: the per-worker YOLO call sometimes dies with `CUDA error: an illegal memory access` (twice in two smokes), which
stops a multi-hour unattended run. A plain rerun resumes safely: finished pages are skipped, each page result is
written atomically, and each page's seed is hashed from BASE_SEED/font/piece/page/variant, so neither the crash nor
the restart changes any page. This wrapper only relaunches the same command; it never edits cut_corpus.py (whose
sha the report records) or any page result.

Stop rules:
* clean exit (code 0) -> done;
* MAX_NO_PROGRESS consecutive attempts that finish no page -> stop (a crash that repeats on the same page is a
  real bug, not the transient BUG-044 crash, and must be looked at, not retried forever);
* MAX_ATTEMPTS attempts in total -> stop;
* no output line for STALL_MINUTES -> the process tree is killed and the attempt counts as a crash (a hung CUDA
  call would otherwise block forever; the slowest 100f page took 57 s).

Usage:
    python training/phase1/run_resume.py --log D:/.../bach_full_g2.log -- --out D:/.../bach_full_g2 --stats
Everything after `--` is passed to `cut_corpus.py run` unchanged.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

import psutil

CUT_CORPUS = Path(__file__).with_name("cut_corpus.py")
MAX_ATTEMPTS = 30
MAX_NO_PROGRESS = 2
STALL_MINUTES = 15.0
RESTART_PAUSE_S = 20.0           # lets the driver release the crashed context before the next CUDA init
PAGE_LINE = re.compile(r"^\[\d+/\d+\] ")
SECONDS_PER_MINUTE = 60.0


def _pump(stream: IO[str], q: queue.Queue[str | None]) -> None:
    """Moves child output lines into a queue so the parent can wait on it with a timeout."""
    for line in stream:
        q.put(line)
    q.put(None)


def _kill_tree(pid: int) -> None:
    """Kills the child and its spawned pool workers; a stalled CUDA worker ignores a polite terminate."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = parent.children(recursive=True) + [parent]
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=30)


def run_once(cmd: list[str], log: IO[str]) -> tuple[int, int, bool]:
    """Runs one attempt, teeing output to the log.

    Returns:
        (exit code, pages finished in this attempt, stalled).
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1)
    assert proc.stdout is not None
    q: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_pump, args=(proc.stdout, q), daemon=True).start()
    pages = 0
    stalled = False
    while True:
        try:
            line = q.get(timeout=STALL_MINUTES * SECONDS_PER_MINUTE)
        except queue.Empty:
            stalled = True
            _kill_tree(proc.pid)
            break
        if line is None:
            break
        if PAGE_LINE.match(line):
            pages += 1
        sys.stdout.write(line)
        sys.stdout.flush()
        log.write(line)
        log.flush()
    code = proc.wait()
    return (code if not stalled else -1), pages, stalled


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, required=True, help="combined log of all attempts (appended)")
    ap.add_argument("run_args", nargs=argparse.REMAINDER, help="-- then the `cut_corpus.py run` arguments")
    a = ap.parse_args()
    run_args = a.run_args[1:] if a.run_args[:1] == ["--"] else a.run_args
    if "--out" not in run_args:
        raise SystemExit("pass `-- --out <dir> ...` (the cut_corpus.py run arguments)")
    if "--force" in run_args:
        raise SystemExit("--force would redo finished pages on every restart; not allowed under the wrapper")
    out = Path(run_args[run_args.index("--out") + 1])
    cmd = [sys.executable, "-u", str(CUT_CORPUS), "run", *run_args]
    attempts: list[dict[str, object]] = []
    no_progress = 0
    final = "max_attempts"
    a.log.parent.mkdir(parents=True, exist_ok=True)
    with a.log.open("a", encoding="utf-8") as log:
        for n in range(1, MAX_ATTEMPTS + 1):
            started = dt.datetime.now().isoformat(timespec="seconds")
            log.write(f"=== run_resume attempt {n} {started}: {' '.join(cmd)}\n")
            log.flush()
            t0 = time.perf_counter()
            code, pages, stalled = run_once(cmd, log)
            attempts.append({"attempt": n, "started": started, "exit_code": code, "pages_done": pages,
                             "stalled": stalled, "minutes": round((time.perf_counter() - t0) / 60, 1)})
            out.mkdir(parents=True, exist_ok=True)
            (out / "resume_attempts.json").write_text(json.dumps(attempts, indent=1), encoding="utf-8")
            if code == 0:
                final = "complete"
                break
            no_progress = 0 if pages else no_progress + 1
            msg = (f"=== attempt {n} {'stalled' if stalled else f'exited {code}'} after {pages} pages; "
                   f"{no_progress} attempt(s) in a row without progress\n")
            log.write(msg)
            log.flush()
            sys.stdout.write(msg)
            if no_progress >= MAX_NO_PROGRESS:
                final = "no_progress"
                break
            time.sleep(RESTART_PAUSE_S)
        log.write(f"=== run_resume finished: {final}\n")
    if final != "complete":
        raise SystemExit(f"run_resume stopped: {final} (see {a.log} and {out / 'resume_attempts.json'})")


if __name__ == "__main__":
    main()
