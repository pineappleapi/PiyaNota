"""render_corpus --exclude-font: the default rotation is unchanged and an excluded font never appears."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training" / "phase1"))
import render_corpus as rc  # noqa: E402

HELD_OUT = "Gootville"


def original_rotation(index: int, per_piece: int) -> list[str]:
    """The pre-flag expression, copied verbatim, so the default path is checked against it."""
    start = index % len(rc.FONTS)
    return [rc.FONTS[(start + k) % len(rc.FONTS)] for k in range(per_piece)]


def test_default_pool_matches_original_rotation():
    for per_piece in (1, 2, 5):
        for i in range(23):
            assert rc.fonts_for_piece(i, per_piece) == original_rotation(i, per_piece)


def test_excluded_font_never_rendered_and_rest_used_equally():
    pool = tuple(f for f in rc.FONTS if f != HELD_OUT)
    used = [f for i in range(40) for f in rc.fonts_for_piece(i, 2, pool)]
    assert HELD_OUT not in used
    assert {used.count(f) for f in pool} == {20}


def test_cli_rejects_too_many_fonts_after_exclusion(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["render_corpus.py", "--out", str(tmp_path), "--exclude-font", HELD_OUT])
    try:
        rc.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected argparse error for 5 fonts with one excluded")
