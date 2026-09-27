"""PiyaNota - Stage 3, version (b): CRNN transcription with the clef/key classifier (ClefKeyNet).

Version (a) is ``stage3_transcription.py`` unchanged: the CRNN's own clef and key-signature tokens
decide pitch, and Tenor is lowered an octave by voice. This module is the opt-in version (b), used by
the fresh-photo evaluation (data/eval_fresh/PREREG.md). It imports Stage 3 unchanged and changes only
where the clef, key and octave come from:

* Clef: ``clef_voice_rules.resolve_clef`` (classifier + voice constraint) is the single owner. Every
  CRNN clef token is dropped, because a CRNN clef (BUG-011 collapses to clef.C-L3) would otherwise
  replace the rule's clef inside ``infer_pitch`` (user decision 2026-09-28: the CRNN's raw clef can't
  override the rule).
* Octave: Stage 3's voice-based Tenor lookup (``get_clef_reference``) is switched off for the call, and
  the rule's ``octave_shift`` is added once to every pitched event. Switching off by patching the module
  global covers all of its call sites inside ``infer_pitch``; otherwise a Tenor would drop two octaves.
* Key: key signatures are shared by all four voices of a system (choral-conductor review 2026-09-28),
  so only confident classifier readings vote per system; with no majority the previous system's key is
  carried and the system is flagged. The CRNN never votes. The CRNN's leading key-signature accidentals
  are consumed so they cannot leak into the first notes as inline accidentals.
* CRNN mid-strip key changes are left to Stage 3 but flagged ``review_needed`` (a mid-system key change
  is not in either test piece, so a firing one is a recognition error).

Known limit: a real accidental on the first note that the CRNN emits directly after the key signature
is indistinguishable from a key-signature accidental and is dropped with it.
"""
from __future__ import annotations

import contextlib
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

import numpy as np
import torch

import clef_key_core as ck
import stage3_transcription as s3
from clef_voice_rules import ClefDecision, resolve_clef

DEFAULT_CLEF_KEY_CHECKPOINT = Path("training/clef_key_artifacts/t4_full_seed20260926_runA/clef_key_classifier.pt")

# Printed key-signature positions (PrIMuS agnostic) in the order they are engraved; the same table the
# ground-truth builder uses, so a correctly recognised key produces exactly the ground-truth header tokens.
KEY_SIG_ORDER: dict[str, dict[str, list[str]]] = {
    "clef.G-L2": {"sharp": ["L5", "S3", "S5", "L4", "S2", "S4", "L3"],
                  "flat": ["L3", "S4", "S2", "L4", "S1", "S3", "L2"]},
    "clef.F-L4": {"sharp": ["L4", "S2", "S4", "L3", "S1", "S3", "L2"],
                  "flat": ["L2", "S3", "S1", "L3", "L1", "S2", "S0"]},
}
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
    return out


def key_tokens(clef_token: str, key: int) -> list[str]:
    """Agnostic key-signature tokens for a signed key (+sharps / -flats) under the given clef."""
    if key == 0:
        return []
    kind = "sharp" if key > 0 else "flat"
    return [f"accidental.{kind}-{p}" for p in KEY_SIG_ORDER[clef_token][kind][:abs(key)]]


def substitute_header(tokens: Sequence[str], confs: Sequence[float], clef_token: str,
                      key: int) -> tuple[list[str], list[float], dict[str, int]]:
    """Replaces the CRNN's clef and opening key signature with the decided ones.

    Drops every CRNN clef token (anywhere in the strip) and the accidentals before the first
    non-clef/non-accidental token, then prepends the decided clef and key-signature tokens.
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


@contextlib.contextmanager
def _voice_octave_off() -> Iterator[None]:
    """Makes Stage 3's clef reference ignore the voice (no Tenor lowering) for the duration."""
    original = s3.get_clef_reference
    s3.get_clef_reference = lambda clef, voice: s3.CLEF_REFERENCE.get(clef, 64)
    try:
        yield
    finally:
        s3.get_clef_reference = original


def infer_pitch_b(tokens: Sequence[str], confs: Sequence[float], voice: str, page_index: int, sys_idx: int,
                  decision: StripDecision) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Version (b) pitch inference for one strip.

    Returns:
        (events, header tokens actually used, info). Events carry ``review_needed`` and ``clef_key_flags``.
    """
    toks, cfs, info = substitute_header(tokens, confs, decision.clef.token, decision.key)
    log = io.StringIO()
    with _voice_octave_off(), contextlib.redirect_stdout(log):
        events = s3.infer_pitch(toks, voice=voice, page_index=page_index, sys_idx=sys_idx, confidences=cfs)
    flags = list(decision.flags) + list(decision.clef.flags)
    info["mid_key_changes"] = log.getvalue().count(MID_KEY_CHANGE_MARK)
    if info["mid_key_changes"]:
        flags += ["crnn_mid_strip_key_change", "review_needed"]
    for e in events:
        if e.get("pitch") is not None:
            e["pitch"] += decision.clef.octave_shift
    flags = sorted(set(flags))
    for e in events:
        e["clef_key_flags"] = flags
        e["review_needed"] = "review_needed" in flags
    info.update(clef_class=decision.clef.clef_class, clef_source=decision.clef.source,
                octave_shift=decision.clef.octave_shift, key=decision.key, key_source=decision.key_source,
                flags=flags, review_needed="review_needed" in flags)
    return events, toks, info


def readings_to_json(readings: Sequence[ClefKeyReading]) -> str:
    return json.dumps([r.__dict__ for r in readings], indent=1)


def readings_from_json(text: str) -> list[ClefKeyReading]:
    return [ClefKeyReading(**d) for d in json.loads(text)]
