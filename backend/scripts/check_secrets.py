"""Fail (exit 1) if git tracks a .env file or a file containing a credential pattern (PIYA-318)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Compiled from fragments so this file never matches its own patterns.
PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS key id": re.compile("AK" + "IA[0-9A-Z]{8}"),
    "private key": re.compile("-----" + "BEGIN"),
    "reset HMAC key value": re.compile(r"PIYA_RESET_CODE_HMAC_KEY=" + r"\s*[^\s#]"),
    "Backblaze key": re.compile("K" + "00[A-Za-z0-9+/]{20,}"),
    "Brevo key": re.compile("xkeysib" + "-"),
}
_EXAMPLE_SUFFIXES = (".example", ".sample", ".template")


def _is_env_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (name == ".env" or name.startswith(".env.")) and not name.endswith(_EXAMPLE_SUFFIXES)


def main() -> int:
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    problems: list[str] = []
    for path in tracked:
        if _is_env_file(path):
            problems.append(f"{path}: tracked .env file")
        full = Path(root) / path
        # shortcut: docs/ and *.example files are skipped (they describe or placeholder secrets);
        # a real secret pasted into docs/ is missed, so upgrade to an allowlist if that happens.
        if path.startswith("docs/") or path.endswith(_EXAMPLE_SUFFIXES) or not full.is_file():
            continue
        text = full.read_bytes().decode("utf-8", errors="ignore")
        problems += [f"{path}: {name}" for name, pat in PATTERNS.items() if pat.search(text)]
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
