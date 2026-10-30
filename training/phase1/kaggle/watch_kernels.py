"""Watch Kaggle kernels until each one ends; one stdout line per event, so a Monitor can stream it.

    python training/phase1/kaggle/watch_kernels.py piamac/piyanota-divisi-a7-c piamac/piyanota-divisi-a7-cl \
        [--every 300] [--quiet-min 90] [--fetch-dir <dir>]

Why: Kaggle's "Successfully ran" only means the script exited 0. Our kernels always exit 0 once they can write output
and put the real result in kernel_status.json (ok | gate_fail | kernel_error, or aborted / run.returncode for the GPU
kernels). On 2026-10-30 the A7 CL build crashed after 14 min and showed green, and it went unnoticed for hours.

Events: a status change; a new log line that looks like an error (Traceback, Error, abort, KernelError, Killed, OOM);
no new log output for --quiet-min minutes while running (a build step writes to its own log file, so long quiet
spells are normal: this is a hint, not a failure); and at the end the kernel_status.json verdict. Exits when every
kernel has ended. Exit code 1 if any kernel ended in anything but a clean verdict.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TERMINAL = ("COMPLETE", "ERROR", "CANCEL")       # substrings of KernelWorkerStatus.* that end a run
ERROR_LINE = re.compile(r"Traceback|Error\b|[Ee]rror:|abort|KernelError|Killed|out of memory|OOM|CUDA error")
IGNORE_LINE = re.compile(r"NbConvertApp|DeprecationWarning|FutureWarning|UserWarning|SyntaxWarning|Insufficient space")
CLEAN_VERDICTS = ("ok",)
CMD_TIMEOUT_S = 120
FETCH_TIMEOUT_S = 1800              # listing a build output (~30k files) to find one file takes minutes


def run(cmd: list[str], timeout: int = CMD_TIMEOUT_S) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                             errors="replace")
    except subprocess.TimeoutExpired:
        return ""
    return "\n".join(ln for ln in (out.stdout + out.stderr).splitlines() if "outdated `kaggle` version" not in ln)


def status_of(kernel: str) -> str:
    m = re.search(r'status "?KernelWorkerStatus\.(\w+)', run([sys.executable, "-m", "kaggle", "kernels", "status", kernel]))
    return m.group(1) if m else "UNKNOWN"


def log_lines(kernel: str) -> list[str]:
    """The run log as (stream, text) lines; the CLI prints a JSON array, possibly cut mid-stream."""
    raw = run([sys.executable, "-m", "kaggle", "kernels", "logs", kernel])
    lines: list[str] = []
    for m in re.finditer(r'"data":"((?:[^"\\]|\\.)*)"', raw):
        try:
            text = json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            text = m.group(1)
        lines += [t for t in text.splitlines() if t.strip()]
    return lines


def verdict(kernel: str, fetch_dir: Path) -> tuple[str, bool]:
    dest = fetch_dir / kernel.split("/")[1]
    run([sys.executable, str(HERE / "fetch_output.py"), kernel, str(dest), "--pattern", r"^kernel_status\.json$"],
        timeout=FETCH_TIMEOUT_S)
    p = dest / "kernel_status.json"
    if not p.is_file():
        return "no kernel_status.json in the output (the kernel died before writing it)", False
    s = json.loads(p.read_text(encoding="utf-8"))
    run_info = s.get("run") if isinstance(s.get("run"), dict) else {}
    st = s.get("status") or ("aborted" if s.get("aborted") else f"returncode {run_info.get('returncode')}")
    clean = st in CLEAN_VERDICTS or (not s.get("aborted") and run_info.get("returncode") == 0)
    detail = s.get("aborted") or ""
    return f"{st}{' - ' + str(detail)[:300] if detail else ''} ({p})", bool(clean)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kernels", nargs="+")
    ap.add_argument("--every", type=int, default=300, help="seconds between polls")
    ap.add_argument("--quiet-min", type=int, default=90, help="minutes without new log lines before a hint")
    ap.add_argument("--fetch-dir", type=Path, default=Path("D:/PiyaNota/datasets/kaggle_watch"))
    a = ap.parse_args()
    state = {k: {"status": "", "seen": 0, "last_new": time.time(), "quiet_told": False} for k in a.kernels}
    bad: list[str] = []
    while state:
        for k in list(state):
            s = state[k]
            st = status_of(k)
            if st != s["status"]:
                print(f"{k}: status {st}", flush=True)
                s["status"] = st
            lines = log_lines(k)
            if len(lines) > s["seen"]:
                for ln in lines[s["seen"]:]:
                    if ERROR_LINE.search(ln) and not IGNORE_LINE.search(ln):
                        print(f"{k}: LOG {ln[:300]}", flush=True)
                s["seen"], s["last_new"], s["quiet_told"] = len(lines), time.time(), False
            elif st == "RUNNING" and not s["quiet_told"] and time.time() - s["last_new"] > a.quiet_min * 60:
                print(f"{k}: no new log output for {a.quiet_min} min (last: {lines[-1][:200] if lines else '-'})",
                      flush=True)
                s["quiet_told"] = True
            if any(t in st for t in TERMINAL):
                text, clean = verdict(k, a.fetch_dir)
                print(f"{k}: FINISHED {st}, verdict {text}", flush=True)
                if not clean:
                    bad.append(k)
                del state[k]
        if state:
            time.sleep(a.every)
    print(f"ALL ENDED; not clean: {', '.join(bad) or 'none'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
