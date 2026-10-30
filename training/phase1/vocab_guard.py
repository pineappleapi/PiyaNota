"""Vocabulary guard for Phase 1 labels: a strip whose label the CRNN cannot output is quarantined (PIYA-106).

Why: the converter labels what Verovio draws, which can include glyphs the CRNN vocabulary has no token for (a
breve rest drawn for a whole-bar rest in 4/2, `rest.double_whole-L3`). Vocabulary expansion is ruled out for now,
so such a strip must not reach training with a label the model cannot emit, and the converter must not lie to
avoid it. The guard works per system strip, so the other strips of the same render stay usable.

The token list is imported from `stage3_transcription.VOCAB`, never copied, so the guard follows the model.
"""

from __future__ import annotations

import collections
import functools
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CTC_SPECIAL_TOKENS: frozenset[str] = frozenset({"<blank>", "<unk>"})   # never a valid label token
OOV_PREFIX = "oov:"


@functools.cache
def crnn_vocab(vocab_ext: bool | str = False) -> frozenset[str]:
    """The CRNN output tokens; with vocab_ext, the divisi arm's VOCAB_EXT_CHORD_TUPLET, or with "a7" the divisi A7
    VOCAB_EXT_A7 (layer tokens). Imported lazily because stage3 pulls in torch (about 8 s)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from stage3_transcription import VOCAB, VOCAB_EXT_A7, VOCAB_EXT_CHORD_TUPLET  # noqa: PLC0415 - heavy import
    table = VOCAB_EXT_A7 if vocab_ext == "a7" else VOCAB_EXT_CHORD_TUPLET if vocab_ext else VOCAB
    return frozenset(table) - CTC_SPECIAL_TOKENS


def oov_tokens(tokens: list[str], vocab_ext: bool | str = False) -> list[str]:
    """Distinct out-of-vocabulary tokens in label order."""
    vocab = crnn_vocab(vocab_ext)
    return list(dict.fromkeys(t for t in tokens if t not in vocab))


def apply_guard(label_rows: list[dict[str, object]], vocab_ext: bool | str = False) -> collections.Counter[str]:
    """Mark each label row usable or quarantined in place; return OOV token occurrence counts.

    A row gets `oov` (its distinct OOV tokens) and `quarantine` ("oov:<first OOV token>" or None).
    """
    counts: collections.Counter[str] = collections.Counter()
    vocab = crnn_vocab(vocab_ext)
    for row in label_rows:
        tokens: list[str] = row["tokens"]  # type: ignore[assignment]
        bad = oov_tokens(tokens, vocab_ext)
        counts.update(t for t in tokens if t not in vocab)
        row["oov"] = bad
        row["quarantine"] = f"{OOV_PREFIX}{bad[0]}" if bad else None
    return counts
