"""Secondary G2 figure: eval_dev.py with fermata tokens dropped from predictions before scoring (SER only).
Wraps se.score_strip; eval_dev.py is imported unchanged. Without --drop-fermata it is a no-op (parity check)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
drop = "--drop-fermata" in sys.argv
sys.argv = [x for x in sys.argv if x != "--drop-fermata"]

import eval_dev as ed  # noqa: E402

_orig = ed.se.score_strip


def _score(g, sub, *rest):
    if drop and sub is not None:
        sub = [x for x in sub if not str(x).startswith("fermata")]
    return _orig(g, sub, *rest)


ed.se.score_strip = _score

if __name__ == "__main__":
    sys.exit(ed.main())