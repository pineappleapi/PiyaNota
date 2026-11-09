"""Fail (exit 1) if git tracks a .env file or a file containing a credential pattern (PIYA-318)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Compiled from fragments so this file never matches its own patterns.
PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS key id": re.compile("AK" + "IA[0-9A-Z]{8}"),
    "private key": re.compile("-----" + "BEGIN [A-Z ]*PRIVATE KEY-----"),
    # Horizontal whitespace only, not \s: an empty assignment must not swallow the next line.
    # Backticks and angle brackets excluded so docs and placeholders do not match.
    "reset HMAC key value": re.compile(
        r"""PIYA_RESET_CODE_HMAC_KEY[ \t]*=[ \t]*["']?[^\s#`"'<>]"""
    ),
    "Backblaze key": re.compile("K" + "00[A-Za-z0-9+/]{20,}"),
    "Brevo key": re.compile("xkeysib" + "-[0-9a-f]{20,}"),
    "database URL with password": re.compile(r"postgres(?:ql)?://[^:\s/]+:[^@\s]+@(?!localhost|127\.0\.0\.1)"),
}
_EXAMPLE_SUFFIXES = (".example", ".sample", ".template")
# The example env file ships a placeholder HMAC value by design (reviewed); any other tracked file
# with a value is a leak.
_ALLOWED: dict[str, frozenset[str]] = {
    "backend/.env.example": frozenset({"reset HMAC key value"}),
}
_NUL = b"\x00"


def _is_env_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (name == ".env" or name.startswith(".env.")) and not name.endswith(_EXAMPLE_SUFFIXES)


def scan_text(text: str) -> list[str]:
    """Names of the secret patterns found in ``text``."""
    return [name for name, pat in PATTERNS.items() if pat.search(text)]


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
        if not full.is_file():  # deleted in the working tree but still indexed
            continue
        data = full.read_bytes()
        if _NUL in data:  # binary
            continue
        found = set(scan_text(data.decode("utf-8", errors="ignore"))) - _ALLOWED.get(path, frozenset())
        problems += [f"{path}: {n}" for n in sorted(found)]
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
