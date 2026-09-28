"""PiyaNota - Stage 3, version (b): CRNN transcription with the clef/key classifier (ClefKeyNet).

Version (a) is ``stage3_transcription.infer_pitch`` without a header override: the CRNN's own clef and
key-signature tokens decide pitch, and Tenor is lowered an octave by voice. Version (b) is the pipeline
default since 2026-09-29 (``transcribe_voice_sequences(clef_key_decisions=...)``, built by
``decisions_for_pages``); it was first used by the fresh-photo evaluation (data/eval_fresh/PREREG.md).
It changes only where the clef, key and octave come from, through ``infer_pitch``'s ``header_override``:

* Clef: ``clef_voice_rules.resolve_clef`` (classifier + voice constraint) is the single owner. Every
  CRNN clef token is dropped, because a CRNN clef (BUG-011 collapses to clef.C-L3) would otherwise
  replace the rule's clef inside ``infer_pitch`` (user decision 2026-09-28: the CRNN's raw clef can't
  override the rule).
* Octave: the rule's ``octave_shift`` is added to the clef reference and Stage 3's voice-based Tenor
  lookup is not used, so a Tenor can't drop two octaves.
* Key: key signatures are shared by all four voices of a system (choral-conductor review 2026-09-28),
  so only confident classifier readings vote per system; with no majority the previous system's key is
  carried and the system is flagged. The CRNN never votes. Every CRNN accidental before the first
  note/rest is kept out of the key; only one directly before a note on its own position survives, as
  that note's inline accidental (BUG-027: glyphs after the time-signature digits used to be added to the key).
* CRNN mid-strip key changes are left to Stage 3 but flagged ``review_needed``. A post-barline burst
  matching the next system's classifier key counts even with one glyph (BUG-029).

Known limit: the classifier fails the real-photo gate (BUG-021, ~4.5% of clefs confidently wrong), so
its flags are kept on every event for review.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import torch

import clef_key_core as ck
import stage3_transcription as s3
from clef_voice_rules import ClefDecision, resolve_clef

# Resolved from the repo, not the working directory, so the API and CLIs find the same file. The checkpoint
# is gitignored (copy it from the training tree); the hash pins the T4 seed-20260926 run A weights that
# the BUG-021 validation and the fresh-photo eval used.
DEFAULT_CLEF_KEY_CHECKPOINT = (Path(__file__).resolve().parent / "training" / "clef_key_artifacts"
                               / "t4_full_seed20260926_runA" / "clef_key_classifier.pt")
DEFAULT_CLEF_KEY_SHA256 = "e718d4479b1310369b64cfaf9a8f1ff433179543ffa9d1810b24c683de13fe10"
# The checkpoint failed its real-photo gate (BUG-021: ~4.5% of clefs confidently wrong, which no per-strip
# flag catches). The user accepted it as the default only with every event flagged for review, so while
# this is False each version (b) event carries CLEF_KEY_UNVALIDATED_FLAG and review_needed. Set it True
# only after a gate pass on fresh photos.
CLEF_KEY_GATE_PASSED = False
CLEF_KEY_UNVALIDATED_FLAG = "clef_key_unvalidated"
SHA256_CHUNK_BYTES = 1 << 20

DEFAULT_PIPELINE_MANIFEST = "manifest.json"
INJECTED_TOKEN_CONFIDENCE = 1.0  # clef/key tokens are not folded into per-note confidence by infer_pitch
STAFF_HALF_HEIGHT_SPACINGS = 2.0  # outer staff lines = centre -/+ 2 spacings
BAND_MAX_OFFSET_SPACINGS = 1.0    # a Stage 2 box must sit within 1 spacing of a tracked staff (realval 3.1)
MID_KEY_CHANGE_MARK = "mid-piece key change"


@dataclass
class ClefKeyReading:
    """Classifier output for one Stage 2 strip (None probabilities when no staff geometry was found)."""
    strip_id: str
    voice: str
    page: int
    system: int
    clef_probs: Optional[list[float]]
    key_probs: Optional[list[float]]
    geometry: Optional[dict[str, float]] = None
    reason: str = ""


@dataclass
class StripDecision:
    """Clef, key and flags version (b) applies to one strip."""
    clef: ClefDecision
    key: int
    key_source: str
    flags: list[str] = field(default_factory=list)
    # Key of the next system in page/system order (None on the last one); lets Stage 3 accept a
    # one-glyph mid-strip key change that the classifier confirms (BUG-029).
    next_key: Optional[int] = None

    @property
    def review_needed(self) -> bool:
        return "review_needed" in self.flags or "review_needed" in self.clef.flags


@dataclass
class ClefKeyModel:
    model: ck.ClefKeyNet
    clef_temperature: float
    key_temperature: float
    clef_threshold: float
    key_threshold: float
    g8vb_reliable: bool


def load_clef_key_model(path: Path = DEFAULT_CLEF_KEY_CHECKPOINT) -> ClefKeyModel:
    """Loads the frozen checkpoint and refuses one whose crop contract differs from clef_key_core.py."""
    ckpt: dict[str, Any] = torch.load(path, map_location="cpu", weights_only=False)
    if ckpt.get("smoke_test"):
        raise RuntimeError(f"{path} is a smoke-test checkpoint")
    if ckpt["crop_spec_version"] != ck.CROP_SPEC_VERSION:
        raise RuntimeError(f"crop spec {ckpt['crop_spec_version']} != core {ck.CROP_SPEC_VERSION}")
    model = ck.ClefKeyNet(width=ckpt["arch"]["width"], dropout=ckpt["arch"]["dropout"])
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return ClefKeyModel(model, float(ckpt["clef_temperature"]), float(ckpt["key_temperature"]),
                        float(ckpt["clef_threshold"]), float(ckpt["key_threshold"]), bool(ckpt["g8vb_reliable"]))


def classify_page(page: Any, manifest: Sequence[dict[str, Any]], ckm: ClefKeyModel) -> list[ClefKeyReading]:
    """Runs the classifier on every Stage 2 strip of one page.

    Geometry follows the real-photo validation's deployment path (training/eval_clef_key_realval.py):
    the Stage 2 box is mapped onto Stage 1's UNMASKED native page, snapped to the nearest tracked staff,
    and cropped with staff_left_edge() + make_input().

    Args:
        page: stage1_preprocessing.PreprocessedPage from ``preprocess_score_page(keep_unmasked=True)``.
        manifest: This page's Stage 2 manifest entries.
    """
    unmasked, staves = page.strip_unmasked, page.strip_staves or []
    det_h, det_w = page.detect.shape[:2]
    readings: list[ClefKeyReading] = []
    inputs: list[np.ndarray] = []
    for m in manifest:
        r = ClefKeyReading(m["strip_id"], m["voice"], m["page"], m["system"], None, None)
        readings.append(r)
        if unmasked is None:
            r.reason = "no_unmasked_page (non-staff mask not applied)"
            continue
        sy, sx = unmasked.shape[0] / det_h, unmasked.shape[1] / det_w
        centre = ((m["box"]["y1"] + 0.5) * sy - 0.5 + (m["box"]["y2"] + 0.5) * sy - 0.5) / 2.0
        band = min(staves, key=lambda st: abs(st.center - centre)) if staves else None
        if band is None or abs(band.center - centre) > BAND_MAX_OFFSET_SPACINGS * band.spacing:
            r.reason = "no tracked staff within 1 spacing of the box"
            continue
        top = band.center - STAFF_HALF_HEIGHT_SPACINGS * band.spacing
        bottom = band.center + STAFF_HALF_HEIGHT_SPACINGS * band.spacing
        x0 = ck.staff_left_edge(unmasked, top, bottom, search_from_x=int(m["box"]["x1"] * sx))
        if x0 is None:
            r.reason = "staff_left_edge found no staff start"
            continue
        r.geometry = {"x0": float(x0), "top": float(top), "bottom": float(bottom)}
        inputs.append(ck.make_input(unmasked, x0, top, bottom))
    if inputs:
        with torch.no_grad():
            clef_p, key_p = ck.predict_probs(ckm.model, np.stack(inputs), ckm.clef_temperature, ckm.key_temperature,
                                             device=torch.device("cpu"))
        with_geo = [r for r in readings if r.geometry is not None]
        for r, cp, kp in zip(with_geo, clef_p, key_p):
            r.clef_probs, r.key_probs = [float(v) for v in cp], [float(v) for v in kp]
    return readings


def decide(readings: Sequence[ClefKeyReading], ckm: ClefKeyModel) -> dict[str, StripDecision]:
    """Clef per strip (voice rule) and key per system (confident-majority vote), in page/system order."""
    no_read = [1.0 / len(ck.CLEF_CLASSES)] * len(ck.CLEF_CLASSES)  # below any threshold -> voice default
    systems: dict[tuple[int, int], list[ClefKeyReading]] = {}
    for r in readings:
        systems.setdefault((r.page, r.system), []).append(r)
    out: dict[str, StripDecision] = {}
    carried: Optional[int] = None
    for key_ in sorted(systems):
        members = systems[key_]
        conf: dict[str, int] = {}
        for r in members:
            if r.key_probs is not None and max(r.key_probs) >= ckm.key_threshold:
                conf[r.strip_id] = ck.index_to_key(int(np.argmax(r.key_probs)))
        votes = Counter(conf.values())
        top = votes.most_common(1)
        sys_flags: list[str] = []
        if top and top[0][1] * 2 > len(conf):
            sys_key, source = top[0][0], "system_majority"
        elif carried is not None:
            sys_key, source = carried, "carried_from_previous_system"
            sys_flags = ["key_no_majority", "review_needed"]
        else:
            summed = np.sum([r.key_probs for r in members if r.key_probs is not None], axis=0) \
                if any(r.key_probs is not None for r in members) else None
            sys_key = ck.index_to_key(int(np.argmax(summed))) if summed is not None else 0
            source = "summed_probability_first_system" if summed is not None else "no_reading_c_major"
            sys_flags = ["key_no_majority", "review_needed"]
        carried = sys_key
        for r in members:
            flags = list(sys_flags)
            if r.strip_id in conf and conf[r.strip_id] != sys_key:
                flags += ["key_overridden_by_system", "review_needed"]
            if r.clef_probs is None:
                flags.append("no_classifier_geometry")
            decision = resolve_clef(r.voice, r.clef_probs or no_read, ckm.clef_threshold, ckm.g8vb_reliable)
            out[r.strip_id] = StripDecision(decision, sys_key, source, sorted(set(flags)))
    order = sorted(systems)
    for this, nxt in zip(order, order[1:]):
        if not _systems_adjacent(this, nxt):
            continue    # a system Stage 2 missed in between: its key is unknown, so confirm nothing
        next_key = out[systems[nxt][0].strip_id].key
        for r in systems[this]:
            out[r.strip_id].next_key = next_key
    return out


def _systems_adjacent(this: tuple[int, int], nxt: tuple[int, int]) -> bool:
    """True if (page, system) ``nxt`` directly follows ``this`` (systems are 1-based per page, Stage 2).

    A missed last system on a page can't be seen from here; only gaps within a page, a skipped page, or a
    next page that doesn't start at system 1 are caught.
    """
    page, sys_ = this
    return nxt == (page, sys_ + 1) or nxt == (page + 1, 1)


def decisions_for_pages(pages: Sequence[tuple], manifest: Sequence[dict[str, Any]],
                        ckm: ClefKeyModel) -> tuple[dict[str, StripDecision], list[ClefKeyReading]]:
    """Clef/key decisions for every Stage 2 strip of a run.

    Args:
        pages: ``stage1_preprocessing.preprocess_batch(keep_unmasked=True)`` output; the 4th element of
            each tuple is the PreprocessedPage the classifier crops from.
        manifest: Stage 2's manifest for the same run (``detect_staff_regions(manifest_path=...)``).

    Raises:
        ValueError: A page tuple lacks its PreprocessedPage (Stage 1 run without keep_unmasked).
    """
    by_page: dict[int, list[dict[str, Any]]] = {}
    for m in manifest:
        by_page.setdefault(m["page"], []).append(m)
    readings: list[ClefKeyReading] = []
    for page in pages:
        if len(page) < 4 or page[3] is None:
            raise ValueError(f"page {page[1]}: no PreprocessedPage; run preprocess_batch(keep_unmasked=True)")
        readings += classify_page(page[3], by_page.get(page[1], []), ckm)
    return decide(readings, ckm), readings


def file_sha256(path: Path) -> str:
    """Hex sha256 of a file, read in chunks (checkpoints are tens of MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(SHA256_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_clef_key_weights(path: Optional[str]) -> Optional[Path]:
    """Resolves the ClefKeyNet checkpoint for a pipeline run; None means the caller opted out.

    Missing weights fail loudly instead of falling back: without the classifier Stage 3 reads the CRNN's
    clef, which collapses on real scores (BUG-011; 8-10% pitch on the fresh-photo eval vs 64% with it).

    Args:
        path: checkpoint path, or None to run without ClefKeyNet.

    Returns:
        The resolved path, or None when opted out.

    Raises:
        FileNotFoundError: the checkpoint does not exist.
        ValueError: the default checkpoint's sha256 is not the pinned one (a stale or different copy).
    """
    if path is None:
        print("[Stage 3] WARNING: ClefKeyNet disabled; clef/key come from the CRNN (BUG-011 applies). "
              "Every event is flagged clef_key_disabled / review_needed.")
        return None
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"ClefKeyNet checkpoint not found: {resolved}. Copy it from the training tree "
            f"(training/clef_key_artifacts/t4_full_seed20260926_runA/) or pass --no-clef-key to run without it.")
    digest = file_sha256(resolved)
    if resolved == DEFAULT_CLEF_KEY_CHECKPOINT and digest != DEFAULT_CLEF_KEY_SHA256:
        raise ValueError(f"ClefKeyNet checkpoint {resolved} has sha256 {digest}, expected "
                         f"{DEFAULT_CLEF_KEY_SHA256} (T4 seed-20260926 run A). Re-copy it from the training tree.")
    print(f"[Stage 3] ClefKeyNet checkpoint {resolved} (sha256 {digest[:12]})")
    return resolved


def add_clef_key_args(parser: argparse.ArgumentParser) -> None:
    """Adds --clef-key / --no-clef-key to a stage CLI."""
    parser.add_argument("--clef-key", default=str(DEFAULT_CLEF_KEY_CHECKPOINT),
                        help="ClefKeyNet checkpoint (clef/key/octave for Stage 3)")
    parser.add_argument("--no-clef-key", action="store_true",
                        help="Run without ClefKeyNet: clef/key from the CRNN (BUG-011 applies)")


def clef_key_arg(args: argparse.Namespace) -> Optional[str]:
    """The checkpoint path from add_clef_key_args's flags, or None when opted out."""
    return None if args.no_clef_key else args.clef_key


def key_tokens(clef_token: str, key: int) -> list[str]:
    """Agnostic key-signature tokens for a signed key (+sharps / -flats) under the given clef."""
    if key == 0:
        return []
    kind = "accidental.sharp" if key > 0 else "accidental.flat"
    return [f"{kind}-{p}" for p in s3.KEY_SIG_ORDER[clef_token][kind][:abs(key)]]


def substitute_header(tokens: Sequence[str], confs: Sequence[float], clef_token: str,
                      key: int) -> tuple[list[str], list[float], dict[str, int]]:
    """Replaces the CRNN's clef and opening key signature with the decided ones (token view for SER).

    Drops every CRNN clef token (anywhere in the strip) and the accidentals before the first
    non-clef/non-accidental token, then prepends the decided clef and key-signature tokens. Pitch no
    longer comes from this sequence (``infer_pitch_b`` uses ``header_override``); it is the token
    sequence the evaluation scores for SER.
    """
    head = 0
    while head < len(tokens) and (tokens[head].startswith("clef.") or tokens[head].startswith("accidental.")):
        head += 1
    dropped_acc = sum(1 for t in tokens[:head] if t.startswith("accidental."))
    body = [(t, c) for t, c in zip(tokens[head:], confs[head:]) if not t.startswith("clef.")]
    dropped_clef = sum(1 for t in tokens if t.startswith("clef."))
    new = [clef_token] + key_tokens(clef_token, key)
    toks = new + [t for t, _ in body]
    cfs = [INJECTED_TOKEN_CONFIDENCE] * len(new) + [c for _, c in body]
    return toks, cfs, {"dropped_clef_tokens": dropped_clef, "dropped_header_accidentals": dropped_acc}


def infer_pitch_b(tokens: Sequence[str], confs: Sequence[float], voice: str, page_index: int, sys_idx: int,
                  decision: StripDecision) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Version (b) pitch inference for one strip.

    Returns:
        (events, token sequence with the decided header for SER, info). Events carry ``review_needed``
        ``clef_key_flags`` and ``clef_key_strip_flags`` (the strip's own flags); while ``CLEF_KEY_GATE_PASSED`` is False every event is flagged
        ``clef_key_unvalidated`` / ``review_needed``. ``info["flags"]`` / ``info["review_needed"]`` keep only
        the strip's own flags, so evaluations can still tell which strips raised something specific.
        ``info``'s dropped_* counts describe the SER token view (``substitute_header``), not pitch
        inference, which drops header accidentals by its own rule (``infer_pitch``'s fixed_header stage
        logs those).
    """
    toks, _, info = substitute_header(tokens, confs, decision.clef.token, decision.key)
    override = s3.HeaderOverride(decision.clef.token, decision.key, decision.clef.octave_shift)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        events = s3.infer_pitch(list(tokens), voice=voice, page_index=page_index, sys_idx=sys_idx,
                                confidences=list(confs), header_override=override,
                                next_system_key=decision.next_key)
    print(log.getvalue(), end="")
    flags = list(decision.flags) + list(decision.clef.flags)
    info["mid_key_changes"] = log.getvalue().count(MID_KEY_CHANGE_MARK)
    if info["mid_key_changes"]:
        flags += ["crnn_mid_strip_key_change", "review_needed"]
    flags = sorted(set(flags))
    event_flags = flags if CLEF_KEY_GATE_PASSED else sorted(set(flags) | {CLEF_KEY_UNVALIDATED_FLAG, "review_needed"})
    for e in events:
        e["clef_key_flags"] = event_flags
        e["clef_key_strip_flags"] = flags   # this strip's own flags; build_review reads these
        e["review_needed"] = "review_needed" in event_flags
    info.update(clef_class=decision.clef.clef_class, clef_source=decision.clef.source,
                octave_shift=decision.clef.octave_shift, key=decision.key, key_source=decision.key_source,
                flags=flags, review_needed="review_needed" in flags)
    return events, toks, info


def readings_to_json(readings: Sequence[ClefKeyReading]) -> str:
    return json.dumps([r.__dict__ for r in readings], indent=1)


def readings_from_json(text: str) -> list[ClefKeyReading]:
    return [ClefKeyReading(**d) for d in json.loads(text)]
