"""A6 offline eval: head-level chord scoring per bucket, section 6 gates and epoch selection (PIYA-106).

    python training/phase2/eval_divisi_a6.py --build <rendered divisi build dir> --half test \
        --ckpt seed1_epoch8=<path>.pt [--ckpt ...] [--canary-ok seed1_epoch8] --out a6_eval.json

Why head level: CTC edit distance hides a missing chord member (one deletion among hundreds of tokens), so each
chord column is scored on its set of staff steps. Scoring is a port of the session diagnostic divisi_diag.py:
GT and predicted columns (a `note.*` token plus the `chordnote-*` tokens right after it) are aligned by LCS on note
shape (position stripped), so a model that reads another head of the chord as the main note still aligns. The staff
step is the repo's L1 = 0 convention (divisi_a6_gates.step_of; the diagnostic used L1 = 2).

Unit of a head count (A6.1): unique heads, key (piece, voice, system, column index, chord step set, font); a head
that a second test seed reproduces is counted once, in every bucket total and recall. Halves are tune groups from
halves.json (training/phase1/divisi_halves.py), never a piece-level crc32. The held-out font gap uses only `paired`
(5-font) strips; Gootville recall over all seeds is a diagnostic. The bootstrap is pre-registered as percentile,
B = 1000, seed 0, resampling pieces.

Gate thresholds are the pre-registered ones in docs/decisions/piya-106-divisi-a6-design.md section 6. Canary,
non-chord SER, dev pitch recall and the zero_infinity count are NOT measured here: they come from other scripts
(canary_check.py, eval_dev_nofermata.py, train log) and are reported as not_run.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "training" / "phase1")]
import divisi_halves  # noqa: E402
from divisi_a6_gates import (DEFAULT_PHASE, LEDGER_HIGH, LEDGER_LOW, MEMBER_STEPS, PHASE_FILE, STEMLESS,  # noqa: E402
                             bucket_of, head_key, phase_of, step_of)

WILSON_Z = 1.96                   # one-sided 97.5%, i.e. the lower end of a 95% interval
BOOT_N = 1000
BOOT_LOWER_PCT = 0.025
STRIP_HEIGHT = 64                 # CRNN input height (stage3 default)
UNDERPOWERED_N = 300              # design section 4: fewer test heads than this is reported, not passed
SELECT_FLOOR_N = 100              # tuning-half selection: a bucket with fewer heads is dropped from the min (A6.1)
BOOT_SEED = 0
LEDGER2_STEPS = (-4, 12)          # = build_corpus.LEDGER2_STEPS: a member here is on 2+ ledger lines (A6.4, report-only)
FALLBACK_SECOND_RECALL = 0.50     # design section 9: 2nd fallback fires below this in both seeds at epoch 4
SELECT_MIN_PRECISION = 0.95
HELD_OUT_FONT = "Gootville"
PAIRED = DEFAULT_PHASE            # the 5-font phase; the held-out delta is measured on these strips only
HELD_OUT_GAP = 0.05
AUROC_MIN = 0.80
PLAIN_EXTRA_MAX = 0.005
HALLUCINATION_PER_100_MAX = 0.1
TRIAD_EXACT_MIN = 0.75
PRECISION_MIN = 0.95
FALLBACK_BUCKET = "up"            # stem assumed when no divisi_summary stems exist (old corpora): 2nd_up only
GATE_RECALL_MIN: dict[str, float] = {"3rd": .90, "4th": .90, "5th": .90, "6th": .90, "7th": .90, "8ve": .90,
                                     "2nd_up": .80, "2nd_down": .80, "triad": .85, "ledger": .85}
SECOND_BUCKETS = ("2nd_up", "2nd_down")
ACCIDENTAL = "accidental."
NOT_RUN_GATES = ("canary clean/distorted SER", "non-chord val SER <= +0.5 pp", "dev pitch recall <= -1 pp",
                 "zero_infinity samples == 0")
PASS, FAIL, UNDERPOWERED, MISSING = "PASS", "FAIL", "UNDERPOWERED", "MISSING"
MISSING_KEYS_SHOWN = 5


def shape(tok: str) -> str:
    """Token without its staff position, e.g. `note.quarter` (the LCS alignment key)."""
    return re.sub(r"-[LS]-?\d+$", "", tok)


def columns(tokens: Sequence[str]) -> list[tuple[int, str, list[str], set[int]]]:
    """(index, note token, chordnote tokens, steps of accidentals drawn right before the note) per `note.*`."""
    cols = []
    for i, t in enumerate(tokens):
        if not t.startswith("note."):
            continue
        ext, j = [], i + 1
        while j < len(tokens) and tokens[j].startswith("chordnote-"):
            ext.append(tokens[j])
            j += 1
        acc: set[int] = set()
        k = i - 1
        while k >= 0 and tokens[k].startswith(ACCIDENTAL):
            acc.add(step_of(tokens[k]))
            k -= 1
        cols.append((i, t, ext, acc))
    return cols


def columns_of(tokens: Sequence[str]) -> list[tuple[int, str, list[str], set[int]]]:
    """Alias of `columns` (evaluate() has a local counter of the same name)."""
    return columns(tokens)


def lcs_pairs(a: Sequence[str], b: Sequence[str]) -> list[tuple[int, int]]:
    """Index pairs of a longest common subsequence (same tie-breaking as the session diagnostic)."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    i = j = 0
    pairs = []
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _member_bucket_names(note: str, ext: Sequence[str], stem: str, member: str) -> list[str]:
    """Buckets of one chord member head, from divisi_a6_gates.bucket_of (not re-derived).

    A dyad's single member takes the interval bucket; a triad member takes "triad"; any member on a ledger step
    also takes "ledger". bucket_of returns column-level lists, so the per-member split is done here.
    """
    names = [b for b in bucket_of(note, ext, stem) if b != "ledger"]
    out = [names[0]] if len(ext) == 1 else ["triad"]
    s = step_of(member)
    if s <= LEDGER_LOW or s >= LEDGER_HIGH:
        out.append("ledger")
    if s <= LEDGER2_STEPS[0] or s >= LEDGER2_STEPS[1]:
        out.append("ledger2")
    return out


def _tie_negatives(tokens: Sequence[str], cols: Sequence[tuple[int, str, list[str], set[int]]]) -> list[int]:
    """Columns whose next column, across a barline, repeats the same heads without a tie (A6.4 tie negatives)."""
    out = []
    for k in range(len(cols) - 1):
        (i, note, ext, _a), (j, nnote, next_ext, _b) = cols[k], cols[k + 1]
        between = tokens[i + 1:j]
        same = {step_of(note)} | {step_of(t) for t in ext} == {step_of(nnote)} | {step_of(t) for t in next_ext}
        if same and any(t.startswith("barline") for t in between) \
                and not any(t.startswith("slur.start") for t in between):
            out.append(k)
    return out


def head_scores(pred: Sequence[str], gt: Sequence[str], stems: Sequence[str] | None = None,
                conf: Sequence[float] | None = None, ties: Sequence[str] | None = None) -> dict[str, Any]:
    """Head-level scores of one strip.

    Args:
        pred: decoded tokens.
        gt: ground-truth tokens.
        stems: divisi_summary stem per GT chord column, left to right ("up", "down", "none"). None means the
            summary is missing: every 2nd is counted as 2nd_up (the caller warns). A list of the wrong length is
            ignored the same way as an unknown stem ("2nd_unknown").
        conf: confidence per pred token (frame-mean softmax); enables `head_conf`.
        ties: divisi_summary `tie_sources` per GT chord column ("native", "synth" or ""); a tied column's members
            also count in `tie_<source>` (A6.4, report-only). None or a wrong length: no tie buckets.

    Returns:
        Counters that add across strips (see `merge_scores`): `bucket` {name: [hit, n]} per GT member head,
        `tp`/`gt_heads`/`fp_chord`/`fp_plain` (all heads incl. the main one, as in the session diagnostic),
        `plain_cols`/`plain_extra` (extra heads on aligned GT columns without a chord), `untrained_step`
        (predicted chordnote outside MEMBER_STEPS), `triad_exact`, `acc_member`, `chord_cols`/`unaligned`,
        `pred_chordnotes`, `gt_notes`, `tie_fp` [predicted ties, n] over untied same-head repeats across a
        barline (`_tie_negatives`), `head_conf` [(confidence, is_hit)] per predicted chordnote and `cols`
        [(column index, note token, chordnote tokens, [(bucket, hit)])] per GT chord column (the dedup input).
    """
    gcols, pcols = columns(gt), columns(pred)
    aligned = dict(lcs_pairs([shape(c[1]) for c in gcols], [shape(c[1]) for c in pcols]))
    chord_gi = [k for k, c in enumerate(gcols) if c[2]]
    stem_by_col: dict[int, str] = {}
    stem_mismatch = int(stems is not None and bool(chord_gi) and len(stems) != len(chord_gi))
    for n, k in enumerate(chord_gi):
        if stems is None:
            stem_by_col[k] = FALLBACK_BUCKET
        else:
            stem_by_col[k] = stems[n] if len(stems) == len(chord_gi) else ""
    tie_by_col = dict(zip(chord_gi, ties)) if ties is not None and len(ties) == len(chord_gi) else {}
    out: dict[str, Any] = {"bucket": collections.defaultdict(lambda: [0, 0]), "tp": 0, "gt_heads": 0,
                           "fp_chord": 0, "fp_plain": 0, "plain_cols": 0, "plain_extra": 0, "untrained_step": 0,
                           "triad_exact": [0, 0], "acc_member": [0, 0], "chord_cols": len(chord_gi),
                           "unaligned": 0, "stem_mismatch": stem_mismatch, "pred_chordnotes": sum(t.startswith("chordnote-") for t in pred),
                           "gt_notes": len(gcols), "tie_fp": [0, 0], "head_conf": [], "cols": []}
    for _i, _note, ext, _acc in pcols:
        out["untrained_step"] += sum(1 for t in ext
                                     if not MEMBER_STEPS[0] <= step_of(t) <= MEMBER_STEPS[1])
    hit_pred_cols: dict[int, set[int]] = {}
    for gi, (_ti, note, ext, acc) in enumerate(gcols):
        pi = aligned.get(gi)
        ps: set[int] | None = None
        if pi is not None:
            ps = {step_of(pcols[pi][1])} | {step_of(t) for t in pcols[pi][2]}
            hit_pred_cols[pi] = {step_of(note)} | {step_of(t) for t in ext}
        if not ext:
            if ps is not None:
                out["plain_cols"] += 1
                out["plain_extra"] += len(ps) - 1
                out["fp_plain"] += len(ps) - 1
            continue
        g = {step_of(note)} | {step_of(t) for t in ext}
        out["gt_heads"] += len(g)
        if ps is None:
            out["unaligned"] += 1
        else:
            out["tp"] += len(g & ps)
            out["fp_chord"] += len(ps - g)
        if len(ext) >= 2:
            out["triad_exact"][1] += 1
            out["triad_exact"][0] += int(ps == g)
        col_hits: list[tuple[str, bool]] = []
        for member in ext:
            ok = ps is not None and step_of(member) in ps
            tie = [f"tie_{tie_by_col[gi]}"] if tie_by_col.get(gi) else []
            for name in _member_bucket_names(note, ext, stem_by_col[gi], member) + tie:
                out["bucket"][name][0] += int(ok)
                out["bucket"][name][1] += 1
                col_hits.append((name, ok))
            if step_of(member) in acc:
                out["acc_member"][1] += 1
                out["acc_member"][0] += int(ok)
        out["cols"].append((gi, note, list(ext), col_hits))
    for k in _tie_negatives(gt, gcols):
        out["tie_fp"][1] += 1
        pi = aligned.get(k)
        if pi is not None and pi + 1 < len(pcols):
            out["tie_fp"][0] += int(any(t.startswith("slur.start") for t in pred[pcols[pi][0] + 1:pcols[pi + 1][0]]))
    if conf is not None:
        for pi, (ti, _note, ext, _acc) in enumerate(pcols):
            truth = hit_pred_cols.get(pi, set())
            for off, tok in enumerate(ext, start=1):
                out["head_conf"].append((conf[ti + off], step_of(tok) in truth))
    out["bucket"] = dict(out["bucket"])
    return out


def merge_scores(parts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sums `head_scores` outputs (counters add; pair counters add elementwise)."""
    total: dict[str, Any] = {"bucket": {}, "head_conf": []}
    for p in parts:
        for k, v in p.items():
            if k == "bucket":
                for name, (h, n) in v.items():
                    cur = total["bucket"].setdefault(name, [0, 0])
                    cur[0] += h
                    cur[1] += n
            elif k == "head_conf":
                total["head_conf"].extend(v)
            elif k == "cols":
                continue   # per-strip dedup input, not a counter
            elif isinstance(v, list):
                cur = total.setdefault(k, [0, 0])
                cur[0] += v[0]
                cur[1] += v[1]
            else:
                total[k] = total.get(k, 0) + v
    return total


def wilson_lb(hit: int, n: int, z: float = WILSON_Z) -> float:
    """Wilson score lower bound; 0 when n == 0."""
    if n == 0:
        return 0.0
    p = hit / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    return (centre - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def piece_bootstrap_lb(hits_by_piece: Mapping[str, int], n_by_piece: Mapping[str, int],
                       seed: int = BOOT_SEED) -> float:
    """Lower bound of a piece-cluster bootstrap of hit/n (heads in one piece are correlated).

    Resamples pieces with replacement BOOT_N times and returns the BOOT_LOWER_PCT quantile of the pooled ratio.
    """
    pieces = [p for p in n_by_piece if n_by_piece[p] > 0]
    if not pieces:
        return 0.0
    rng = random.Random(seed)
    ratios = []
    for _ in range(BOOT_N):
        pick = [pieces[rng.randrange(len(pieces))] for _ in pieces]
        n = sum(n_by_piece[p] for p in pick)
        ratios.append(sum(hits_by_piece.get(p, 0) for p in pick) / n)
    ratios.sort()
    return ratios[int(BOOT_LOWER_PCT * BOOT_N)]


def cluster_stats(hits_by_piece: Mapping[str, int], n_by_piece: Mapping[str, int]) -> dict[str, float | None]:
    """Largest single-piece share of a bucket's heads and the design effect of clustering heads by piece.

    The design effect is 1 + (mean cluster size - 1) * rho with rho the one-way ANOVA intraclass correlation of the
    hit indicator (clipped to [0, 1]); None with fewer than two pieces. It says how many independent heads the
    bucket's n is worth: n / deff.
    """
    ns = {p: n for p, n in n_by_piece.items() if n > 0}
    total = sum(ns.values())
    if not total:
        return {"max_piece_share": None, "design_effect": None, "effective_n": None}
    share = max(ns.values()) / total
    k = len(ns)
    if k < 2 or total <= k:
        return {"max_piece_share": share, "design_effect": None, "effective_n": None}
    p_all = sum(hits_by_piece.get(p, 0) for p in ns) / total
    ssb = sum(n * (hits_by_piece.get(p, 0) / n - p_all) ** 2 for p, n in ns.items())
    ssw = sum(hits_by_piece.get(p, 0) * (1 - hits_by_piece.get(p, 0) / n) for p, n in ns.items())
    msb, msw = ssb / (k - 1), ssw / (total - k)
    n0 = (total - sum(n * n for n in ns.values()) / total) / (k - 1)
    denom = msb + (n0 - 1) * msw
    rho = min(1.0, max(0.0, (msb - msw) / denom)) if denom > 0 else 0.0
    deff = 1 + (total / k - 1) * rho
    return {"max_piece_share": share, "design_effect": deff, "effective_n": total / deff}


def auroc(scored: Sequence[tuple[float, bool]]) -> float | None:
    """AUROC of confidence for hit (positive) vs false heads, ties counted half; None if one class is empty."""
    pos = [c for c, ok in scored if ok]
    neg = [c for c, ok in scored if not ok]
    if not pos or not neg:
        return None
    ranked = sorted(scored, key=lambda x: x[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        rank_sum += avg * sum(1 for k in range(i, j + 1) if ranked[k][1])
        i = j + 1
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def select_epoch(per_epoch: Sequence[Mapping[str, Any]]) -> int:
    """1-based epoch with the highest `min_recall` among epochs with P >= .95 and the canary under its caps.

    Ties go to the earlier epoch. The caller computes `min_recall` with `min_bucket_recall`, which drops buckets with
    fewer than SELECT_FLOOR_N heads (2nd buckets also when `fallback_fired` is False). `min_recall` None means every
    bucket was dropped: that epoch is ineligible, there is nothing to select on.

    Raises:
        ValueError: no epoch is eligible (the kill rule's "no usable checkpoint" case; never silently picks one).
    """
    best, best_recall = 0, -1.0
    for k, e in enumerate(per_epoch, start=1):
        if (e["P"] >= SELECT_MIN_PRECISION and e["canary_ok"] and e["min_recall"] is not None
                and e["min_recall"] > best_recall):
            best, best_recall = k, e["min_recall"]
    if best == 0:
        raise ValueError("no epoch has P >= .95 with the canary under its caps and a bucket with enough heads")
    return best


def fallback_fired(epoch4_seed1: float, epoch4_seed2: float) -> bool:
    """True when the 2nd-bucket recall on the tuning half is below .50 at epoch 4 in both seeds."""
    return epoch4_seed1 < FALLBACK_SECOND_RECALL and epoch4_seed2 < FALLBACK_SECOND_RECALL


def min_bucket_recall(buckets: Mapping[str, Sequence[int]], drop_second: bool,
                      floor: int = SELECT_FLOOR_N) -> tuple[float | None, list[str]]:
    """(lowest recall over the gated buckets with at least `floor` heads, the gated buckets that were dropped).

    Pre-registered 2026-10-18 (supersedes the n == 0 rule of Task 7): a thin tuning-half bucket (n < floor, n == 0
    included) cannot decide a selection, so it leaves the min and is listed as `underpowered_buckets`, which the run
    reports. The result is None when every gated bucket is dropped.
    """
    names = [b for b in GATE_RECALL_MIN if not (drop_second and b in SECOND_BUCKETS)]
    thin = [b for b in names if buckets.get(b, [0, 0])[1] < floor]
    rec = [buckets[b][0] / buckets[b][1] for b in names if b not in thin]
    return (min(rec) if rec else None), thin


def head_pr(s: Mapping[str, Any]) -> tuple[float, float]:
    """(head recall, head precision) with the session diagnostic's definitions (main head included)."""
    return (s["tp"] / max(1, s["gt_heads"]),
            s["tp"] / max(1, s["tp"] + s["fp_chord"] + s["fp_plain"]))


# --------------------------------------------------------------------------- model and corpus
def load_stems(build: Path) -> dict[str, list[str]] | None:
    """Per-strip stem lists of the build's divisi_summary.json, or None (with a warning) when absent."""
    path = build / "divisi_summary.json"
    if path.exists():
        stems = json.loads(path.read_text(encoding="utf-8")).get("stems")
        if stems is not None:
            return stems
    print(f"WARNING: no stems in {path}; every 2nd is counted as 2nd_up", file=sys.stderr)
    return None


def load_rows(build: Path, split: str, half: str, chord_only: bool, limit: int, seed: int,
              groups: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Manifest rows of one split; `half` selects the tuning / test halves of the tune groups (divisi_halves).

    Raises:
        ValueError: a half is requested without `groups` (halves.json); there is no piece-level fallback.
    """
    rows = [json.loads(line) for line in
            (build / "manifest" / "phase2_manifest.jsonl").read_text(encoding="utf-8").splitlines() if line]
    rows = [r for r in rows if r["split"] == split]
    if half != "all":
        if groups is None:
            raise ValueError("--half tuning/test needs --halves (halves.json from the build kernel)")
        want_test = half == "test"
        rows = [r for r in rows if divisi_halves.is_test_half(r["piece"], groups) == want_test]
    if chord_only:
        rows = [r for r in rows if any(t.startswith("chordnote-") for t in r["tokens"])]
    if limit and len(rows) > limit:
        rows = random.Random(seed).sample(rows, limit)
    return rows


def load_cpu_model(path: str) -> Any:
    """CRNN from a checkpoint on CPU; the head size must be the chord/tuplet vocabulary."""
    import torch  # noqa: PLC0415 (heavy; keeps the pure scoring functions importable without it)
    import stage3_transcription as s3  # noqa: PLC0415
    model, _ = s3.load_model(path, torch.device("cpu"))
    size = model.fc.weight.shape[0]
    if size != len(s3.VOCAB_EXT_CHORD_TUPLET):
        raise ValueError(f"{path}: head size {size} != chord vocabulary {len(s3.VOCAB_EXT_CHORD_TUPLET)}")
    return model.eval()


def decode_strip(model: Any, png: Path) -> tuple[list[str], list[float]]:
    """Greedy decode with the frame-mean softmax confidence stage3 uses for notes."""
    import cv2  # noqa: PLC0415
    import torch  # noqa: PLC0415
    import stage3_transcription as s3  # noqa: PLC0415
    img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(png)
    pairs = s3.transcribe_strip(img, model, torch.device("cpu"), STRIP_HEIGHT, return_confidence=True)
    return [p[0] for p in pairs], [p[1] for p in pairs]


def dedup_columns(sc: dict[str, Any], row: Mapping[str, Any], seen: set[tuple[object, ...]]) -> int:
    """Rebuilds `sc["bucket"]` from the chord columns not seen before (head_key); returns the duplicates dropped.

    Why: a second test seed can inject the same chord on the same note of the same strip in the same font; scoring it
    twice would count one head as two. The first occurrence in the order given wins.
    """
    buckets: dict[str, list[int]] = {}
    dups = 0
    for gi, note, ext, hits in sc["cols"]:
        key = head_key(row, gi, note, ext)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        for name, ok in hits:
            cur = buckets.setdefault(name, [0, 0])
            cur[0] += int(ok)
            cur[1] += 1
    sc["bucket"] = buckets
    return dups


def evaluate(model: Any, build: Path, rows: Sequence[Mapping[str, Any]],
             stems: Mapping[str, Sequence[str]] | None) -> dict[str, Any]:
    """Scores every row; returns totals, per-piece bucket counters and per-font-group totals.

    A row may carry `_build`, `_stems` and `_phase` (several test folders in one run); otherwise `build`, `stems` and
    the `paired` phase apply. Groups: `in_font` / `held_out` hold `paired` strips only (the held-out delta), and
    `held_out_all` is every Gootville strip of every seed (diagnostic).
    """
    all_parts, by_piece = [], {}
    by_group: dict[str, list[dict[str, Any]]] = {"in_font": [], "held_out": [], "held_out_all": []}
    missing_keys: list[str] = []
    seen: set[tuple[object, ...]] = set()
    columns = duplicates = 0
    for r in rows:
        row_build = r.get("_build", build)
        row_stems = r["_stems"] if "_stems" in r else stems
        pred, conf = decode_strip(model, row_build / "out" / r["path"])
        key = f"{r['piece']}|{r['voice']}|{r['system']}"
        strip_stems = None if row_stems is None else row_stems.get(key)
        n_chord = sum(1 for c in columns_of(r["tokens"]) if c[2])
        if row_stems is not None and strip_stems is None and n_chord:
            missing_keys.append(key)
            strip_stems = [""] * n_chord      # unknown stem: 2nd_unknown, outside the 2nd gates
        sc = head_scores(pred, r["tokens"], strip_stems, conf, (r.get("_ties") or {}).get(key))
        columns += len(sc["cols"])
        duplicates += dedup_columns(sc, r, seen)
        all_parts.append(sc)
        by_piece.setdefault(r["piece"], []).append(sc)
        held = r["font"] == HELD_OUT_FONT
        if held:
            by_group["held_out_all"].append(sc)
        if r.get("_phase", PAIRED) == PAIRED:
            by_group["held_out" if held else "in_font"].append(sc)
        if not any(t.startswith("chordnote-") for t in r["tokens"]):
            sc["uninjected"] = [sc["pred_chordnotes"], sc["gt_notes"]]
    mismatched = sum(p["stem_mismatch"] for p in all_parts)
    if missing_keys:
        print(f"WARNING: {len(missing_keys)} chord strips have no stems entry (first: "
              f"{missing_keys[:MISSING_KEYS_SHOWN]}); their 2nds are 2nd_unknown", file=sys.stderr)
    if mismatched:
        print(f"WARNING: {mismatched} chord strips have a stems list of the wrong length; their 2nds are "
              "2nd_unknown", file=sys.stderr)
    return {"stems_missing_key": len(missing_keys), "stems_wrong_length": mismatched,
            "chord_columns": columns, "duplicate_columns": duplicates,
            "total": merge_scores(all_parts),
            "piece_buckets": {p: merge_scores(v)["bucket"] for p, v in by_piece.items()},
            "groups": {g: merge_scores(v) for g, v in by_group.items() if v},
            "uninjected": merge_scores([{"u": p["uninjected"]} for p in all_parts if "uninjected" in p])
            .get("u", [0, 0])}


def recall_gates(bucket_totals: Mapping[str, Sequence[int]],
                 piece_buckets: Mapping[str, Mapping[str, Sequence[int]]]) -> list[dict[str, Any]]:
    """Per-bucket recall gates with Wilson and piece-bootstrap bounds (lower decides), max piece share, design effect."""
    out: list[dict[str, Any]] = []
    for name, floor in GATE_RECALL_MIN.items():
        h, n = bucket_totals.get(name, [0, 0])
        hits = {p: b.get(name, [0, 0])[0] for p, b in piece_buckets.items()}
        ns = {p: b.get(name, [0, 0])[1] for p, b in piece_buckets.items()}
        wl, bl = wilson_lb(h, n), piece_bootstrap_lb(hits, ns)
        lb = min(wl, bl)
        status = MISSING if n == 0 else UNDERPOWERED if n < UNDERPOWERED_N else PASS if lb >= floor else FAIL
        out.append({"gate": f"recall {name}", "hit": h, "n": n, "recall": h / n if n else None,
                    "wilson_lb": wl, "bootstrap_lb": bl, **cluster_stats(hits, ns),
                    "target": f">= {floor}", "status": status})
    return out


def gate_table(ev: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Section 6 gates that this script can measure, each with Wilson and bootstrap bounds (lower decides)."""
    tot = ev["total"]
    out = recall_gates(tot["bucket"], ev["piece_buckets"])
    t_h, t_n = tot.get("triad_exact", [0, 0])
    out.append({"gate": "exact triad set", "hit": t_h, "n": t_n, "value": t_h / t_n if t_n else None,
                "target": f">= {TRIAD_EXACT_MIN}", "status": PASS if t_n and t_h / t_n >= TRIAD_EXACT_MIN else FAIL})
    _rec, prec = head_pr(tot)
    out.append({"gate": "head precision", "value": prec, "target": f">= {PRECISION_MIN}",
                "status": PASS if prec >= PRECISION_MIN else FAIL})
    pe = tot["plain_extra"] / max(1, tot["plain_cols"])
    out.append({"gate": "extra heads on plain columns", "value": pe, "n_plain_cols": tot["plain_cols"],
                "target": f"<= {PLAIN_EXTRA_MAX}", "status": PASS if pe <= PLAIN_EXTRA_MAX else FAIL})
    u_cn, u_notes = ev["uninjected"]
    per100 = 100 * u_cn / max(1, u_notes)
    out.append({"gate": "chordnote hallucination, un-injected strips (per 100 notes)", "value": per100,
                "chordnotes": u_cn, "notes": u_notes, "target": f"<= {HALLUCINATION_PER_100_MAX}",
                "status": "NOT_RUN" if not u_notes else PASS if per100 <= HALLUCINATION_PER_100_MAX else FAIL})
    g = ev["groups"]
    if "held_out" in g and "in_font" in g:
        rec = {k: head_pr(v)[0] for k, v in g.items()}
        gap = rec["in_font"] - rec["held_out"]
        out.append({"gate": "held-out font recall gap (paired strips)", "in_font": rec["in_font"],
                    "held_out": rec["held_out"], "value": gap, "target": f"<= {HELD_OUT_GAP}",
                    "status": PASS if gap <= HELD_OUT_GAP else FAIL})
    else:
        out.append({"gate": "held-out font recall gap (paired strips)", "target": f"<= {HELD_OUT_GAP}",
                    "status": "NOT_RUN", "note": "no paired held-out-font strips in this selection"})
    if "held_out_all" in g:
        out.append({"gate": "held-out font recall, all seeds (diagnostic)", "value": head_pr(g["held_out_all"])[0],
                    "status": "INFO"})
    out.append({"gate": "untrained-step emissions (info)", "value": tot["untrained_step"], "status": "INFO"})
    return out


def diagnostics(ev: Mapping[str, Any]) -> dict[str, Any]:
    """Accidental-member recall (diagnostic, not a gate) and the confidence AUROC (>= .80 or BUG-011 class)."""
    ah, an = ev["total"].get("acc_member", [0, 0])
    area = auroc(ev["total"]["head_conf"])
    return {"accidental_member": {"hit": ah, "n": an, "recall": ah / an if an else None,
                                  "wilson_lb": wilson_lb(ah, an)},
            "confidence_auroc": {"value": area, "n_heads": len(ev["total"]["head_conf"]),
                                 "target": f">= {AUROC_MIN}",
                                 "status": None if area is None else (PASS if area >= AUROC_MIN else
                                                                      "FAIL (BUG-011 failure class)")}}


def _jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def load_builds(builds: Sequence[Path], split: str, half: str, chord_only: bool, limit: int, seed: int,
                groups: Mapping[str, str] | None) -> tuple[list[dict[str, Any]], bool]:
    """Rows of every build folder, each tagged with its folder, stems and phase (`test_phase.json`).

    Returns the rows and whether every folder had stems.
    """
    rows: list[dict[str, Any]] = []
    all_stems = True
    for b in builds:
        stems = load_stems(b)
        all_stems &= stems is not None
        phase = phase_of(b)
        summary = b / "divisi_summary.json"
        ties = json.loads(summary.read_text(encoding="utf-8")).get("tie_sources") if summary.exists() else None
        rows += [{**r, "_build": b, "_stems": stems, "_ties": ties, "_phase": phase}
                 for r in load_rows(b, split, half, chord_only, 0, seed, groups)]
    if limit and len(rows) > limit:
        rows = random.Random(seed).sample(rows, limit)
    return rows, all_stems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, action="append", required=True,
                    help="rendered divisi build (manifest/, out/, summary); repeat for the test seed folders, in seed "
                         "order (the first occurrence of a duplicate head wins)")
    ap.add_argument("--halves", type=Path, default=None, help="halves.json from the build kernel (tune groups)")
    ap.add_argument("--ckpt", action="append", required=True, help="label=checkpoint.pt (repeatable)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--half", choices=("tuning", "test", "all"), default="all")
    ap.add_argument("--chord-strips-only", action="store_true", help="skip strips without chordnotes")
    ap.add_argument("--limit", type=int, default=0, help="fixed-seed subsample of strips (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--canary-ok", action="append", default=[], help="label whose canary is under its caps")
    ap.add_argument("--out", type=Path, default=Path("a6_eval.json"))
    a = ap.parse_args(argv)
    groups = divisi_halves.load_groups(a.halves) if a.halves else None
    clean = divisi_halves.load_clean_test_pieces(a.halves) if a.halves else None
    rows, have_stems = load_builds(a.build, a.split, a.half, a.chord_strips_only, a.limit, a.seed, groups)
    print(f"{len(rows)} strips ({a.split}, half={a.half}, chord_only={a.chord_strips_only}, builds={len(a.build)})")
    result: dict[str, Any] = {"n_strips": len(rows), "half": a.half, "stems": have_stems,
                              "not_run": list(NOT_RUN_GATES), "checkpoints": {},
                              "bootstrap": {"method": "percentile", "B": BOOT_N, "lower_quantile": BOOT_LOWER_PCT,
                                            "seed": BOOT_SEED, "resampled_unit": "piece"},
                              "head_unit": "unique heads: (piece, voice, system, column, chord step set, font)",
                              "selection_floor_n": SELECT_FLOOR_N, "builds": [str(b) for b in a.build]}
    exit_code = 0
    for item in a.ckpt:
        label, path = item.split("=", 1)
        ev = evaluate(load_cpu_model(path), a.build[0], rows, None)
        rec, prec = head_pr(ev["total"])
        gates = gate_table(ev)
        min_rec, thin = min_bucket_recall(ev["total"]["bucket"], drop_second=False)
        entry = {"stems_missing_key": ev["stems_missing_key"], "stems_wrong_length": ev["stems_wrong_length"],
                 "chord_columns": ev["chord_columns"], "duplicate_columns": ev["duplicate_columns"],
                 "duplicate_rate": ev["duplicate_columns"] / ev["chord_columns"] if ev["chord_columns"] else 0.0,
                 "head_recall": rec, "head_precision": prec, "gates": gates, "diagnostics": diagnostics(ev),
                 "buckets": ev["total"]["bucket"], "counters": {k: v for k, v in ev["total"].items()
                                                                if k not in ("bucket", "head_conf")},
                 "min_recall": min_rec, "underpowered_buckets": thin,
                 "P": prec, "canary_ok": label in a.canary_ok}
        if clean is not None:
            clean_pb = {p: b for p, b in ev["piece_buckets"].items() if p.removesuffix("__divisi") in clean}
            clean_tot: dict[str, list[int]] = {}
            for b in clean_pb.values():
                for name, (h, n) in b.items():
                    cur = clean_tot.setdefault(name, [0, 0])
                    cur[0] += h
                    cur[1] += n
            entry["clean_subset"] = {"note": "test-half pieces whose tune group has no Phase 2 train piece; diagnostic",
                                     "pieces": sorted(clean_pb), "gates": recall_gates(clean_tot, clean_pb)}
        result["checkpoints"][label] = entry
        print(f"== {label}: head recall {rec:.4f} precision {prec:.4f} (gt heads {ev['total']['gt_heads']}, "
              f"duplicate columns {ev['duplicate_columns']}/{ev['chord_columns']})")
        for g in gates:
            print(f"  [{g['status']}] {g['gate']}: " + ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                                                                for k, v in g.items()
                                                                if k not in ("gate", "status")))
            exit_code |= g["status"] in (FAIL, MISSING)
        print(f"  diagnostics: {json.dumps(_jsonable(entry['diagnostics']))}")
    a.out.write_text(json.dumps(_jsonable(result), indent=1), encoding="utf-8")
    return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())
