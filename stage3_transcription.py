"""
PiyaNota - Stage 3: Music Symbol Transcription and Pitch Inference
Transcribes staff strips using CRNN-CTC and infers MIDI pitch per note event.
 
Architecture:
  ResNet CNN  →  BiLSTM  →  CTC greedy decode
Vocabulary:   Camera-PrIMuS agnostic encoding
Pitch:        Rule-based diatonic mapping (clef + key sig + accidental)
 
Note: Training is done separately on Kaggle.
      This file handles inference and pitch inference only.
 
Changes vs original stage3_transcription.py
────────────────────────────────────────────
1.  CLEF_REFERENCE
      • C clef variants now carry correct bottom-line MIDI pitches
        (original had all four set to 60).
      • Tenor treble (clef.G) entries removed — Tenor transposition is now
        handled by get_clef_reference() using the voice label, not the clef
        token alone, because the CRNN cannot distinguish a plain treble clef
        from a treble-8vb clef.
 
2.  TENOR_CLEF_REFERENCE  (new table)
      • Same layout as CLEF_REFERENCE but treble variants return E3 (52)
        instead of E4 (64) — the sounding octave for Tenor in SATB choral.
 
3.  get_clef_reference()  (new helper)
      • Voice-aware lookup: returns TENOR_CLEF_REFERENCE for Tenor,
        CLEF_REFERENCE for all other voices.
      • Replaces every bare CLEF_REFERENCE[sym] call in infer_pitch().
 
4.  CLEF_FALLBACK
      • Tenor fallback changed from clef.C-L3 to clef.G-L2 (modern SATB
        choral notation almost universally uses treble clef for Tenor).
 
5.  STEP_TO_PITCH_CLASS
      • Each C clef variant now has its own correct pitch-class map
        (original shared a single map for all four C clef variants, which
        gives wrong pitch classes for C-L2 / C-L3 / C-L4).
      • Bass clef maps corrected — original used the treble-clef pitch-class
        sequence starting on "B" instead of the correct bass-clef bottom-line "G".
 
6.  KEY_SIG_OFFSETS  (removed)
      • Was empty and never referenced — deleted to avoid confusion.
 
7.  KEY_SIG_ORDER  (replaces KEY_SIG_POSITIONS, PIYA-106 2026-09-28)
      • Engraving-order staff positions of key-signature accidentals for the
        in-scope clefs (treble, bass). The old unordered table was a step off
        and missed treble Bb.

8.  _is_keysig_position()  (new helper)
      • Returns True if an accidental token is at a known key-sig position
        for the active clef.

9.  infer_pitch()  — full rewrite
      • Replaced the two-pass linear scan + boolean flag with a 4-stage
        key-signature state machine:
          "clef"        wait for opening clef; handle dropped-clef recovery
          "keysig"      count opening key-sig accidentals safely
          "body"        normal note / rest processing
          "post_bar"    watch symbol after every barline for key changes
      • Accidental semantics (PIYA-106 2026-09-28): an inline accidental must
        sit on the next note's staff position, sets the absolute alteration
        (BUG-024), and holds for that position until the barline.
      • All CLEF_REFERENCE direct lookups replaced with get_clef_reference()
        so Tenor octave transposition is applied everywhere consistently.
      • Augmentation dots: n dots give base * (2 - 1/2**n) (PIYA-109 AC3), see _dotted_ticks().
      • NOTE_DURATION_TICKS extended with "sixty_fourth" entry.
"""
 
import itertools
import logging
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms
import cv2
import numpy as np
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional, Tuple, Union
import json

if TYPE_CHECKING:
    from stage3_clefkey import StripDecision

logger = logging.getLogger(__name__)


# ── Vocabulary ────────────────────────────────────────────────────────────────
# Camera-PrIMuS agnostic vocabulary — symbols the CRNN can output.
# Blank token (index 0) is reserved for CTC.
 
VOCAB = [
    "<blank>",
    "<unk>",
    "barline-L1",
    "clef.G-L2",
    "note.quarter-L4",
    "rest.eighth-L3",
    "note.quarter-S3",
    "rest.quarter-L3",
    "note.quarter-L3",
    "note.quarter-S4",
    "metersign.C-L3",
    "note.quarter-S2",
    "dot-S3",
    "note.eighth-L4",
    "dot-S4",
    "note.eighth-S3",
    "note.eighth-S4",
    "note.quarter-L5",
    "note.quarter-L2",
    "note.eighth-L3",
    "accidental.flat-L3",
    "note.eighth-S2",
    "accidental.sharp-L5",
    "multirest-L3",
    "clef.C-L1",
    "digit.4-L2",
    "dot-S2",
    "note.eighth-L5",
    "digit.3-L4",
    "note.eighth-L2",
    "note.quarter-S5",
    "dot-S5",
    "metersign.C/-L3",
    "rest.half-L3",
    "note.half-L4",
    "accidental.sharp-S3",
    "note.half-S3",
    "note.quarter-S1",
    "accidental.flat-S4",
    "note.beamedRight1-L4",
    "note.eighth-S5",
    "note.half-L3",
    "note.beamedRight1-S3",
    "note.half-S4",
    "note.half-S2",
    "note.quarter-L6",
    "note.beamedRight1-L3",
    "note.beamedRight1-S4",
    "accidental.flat-L4",
    "digit.1-S5",
    "accidental.sharp-S2",
    "note.beamedLeft2-L4",
    "note.beamedLeft2-S3",
    "note.beamedBoth2-L4",
    "digit.2-L4",
    "note.eighth-S1",
    "note.quarter-L1",
    "note.beamedLeft1-L4",
    "note.beamedRight1-L5",
    "dot-S1",
    "note.half-L2",
    "note.half-L5",
    "note.beamedLeft1-S3",
    "rest.sixteenth-L3",
    "note.beamedBoth2-S4",
    "note.beamedRight1-S2",
    "note.beamedLeft1-S4",
    "note.beamedLeft1-L3",
    "note.beamedLeft1-S2",
    "note.beamedLeft2-S4",
    "note.beamedLeft2-L3",
    "digit.8-L2",
    "accidental.flat-S2",
    "note.beamedBoth2-L3",
    "accidental.flat-L2",
    "note.beamedBoth2-L5",
    "note.beamedBoth2-S3",
    "dot-S6",
    "note.eighth-L6",
    "note.beamedLeft2-L5",
    "note.quarter-S0",
    "note.beamedRight2-L4",
    "note.beamedRight1-S5",
    "note.beamedRight1-L2",
    "note.beamedRight2-S4",
    "note.beamedRight2-S3",
    "note.beamedLeft2-S2",
    "note.beamedBoth2-S2",
    "digit.2-L2",
    "accidental.flat-S3",
    "note.beamedLeft1-L5",
    "clef.F-L4",
    "note.quarter-S6",
    "note.beamedBoth2-S5",
    "note.sixteenth-S3",
    "note.beamedLeft2-L2",
    "digit.2-S5",
    "accidental.sharp-L4",
    "note.beamedBoth1-S3",
    "note.beamedLeft1-L2",
    "note.half-S5",
    "note.beamedRight2-L3",
    "note.beamedLeft2-S5",
    "note.beamedRight2-L5",
    "note.beamedBoth1-L4",
    "accidental.sharp-S5",
    "note.beamedBoth1-S4",
    "note.beamedRight1-L6",
    "note.eighth-L1",
    "accidental.sharp-L1",
    "note.half-S1",
    "note.beamedBoth2-L2",
    "note.beamedBoth1-L3",
    "note.beamedLeft1-S5",
    "note.beamedRight1-S1",
    "note.sixteenth-L4",
    "note.sixteenth-S4",
    "note.beamedRight2-S2",
    "note.beamedBoth1-S2",
    "digit.6-L4",
    "note.beamedRight2-S5",
    "note.beamedBoth1-L5",
    "accidental.sharp-L3",
    "note.beamedBoth2-L6",
    "note.sixteenth-L3",
    "note.eighth-S0",
    "note.beamedBoth1-L2",
    "note.beamedLeft1-S1",
    "accidental.sharp-S4",
    "dot-S0",
    "note.sixteenth-L5",
    "note.beamedLeft2-L6",
    "note.half-L6",
    "note.beamedBoth2-S1",
    "fermata.above-S6",
    "note.beamedRight2-L2",
    "note.eighth-S6",
    "note.beamedLeft1-L1",
    "note.half-L1",
    "note.beamedRight1-L1",
    "note.beamedLeft2-S1",
    "note.sixteenth-S2",
    "note.quarter-L0",
    "note.beamedBoth1-S1",
    "accidental.sharp-L2",
    "accidental.natural-L3",
    "accidental.sharp-S1",
    "note.beamedRight1-S0",
    "note.beamedBoth1-S5",
    "note.whole-S3",
    "clef.C-L3",
    "digit.3-S5",
    "note.beamedLeft1-L6",
    "note.whole-L3",
    "note.beamedRight2-L6",
    "note.beamedRight1-S6",
    "note.whole-L4",
    "note.sixteenth-L2",
    "note.beamedBoth2-L1",
    "clef.C-L4",
    "digit.4-S5",
    "note.half-S0",
    "note.beamedLeft2-L1",
    "note.beamedBoth1-S0",
    "note.beamedRight2-S1",
    "note.beamedBoth2-S6",
    "note.beamedBoth1-L1",
    "note.beamedLeft2-S6",
    "slur.start-L4",
    "slur.end-L4",
    "note.beamedBoth2-S0",
    "note.beamedLeft1-S6",
    "note.whole-S2",
    "slur.start-S4",
    "slur.end-S4",
    "note.quarter-L7",
    "gracenote.eighth-S4",
    "note.beamedRight2-L1",
    "accidental.natural-L4",
    "note.sixteenth-S5",
    "accidental.natural-S3",
    "accidental.natural-S4",
    "gracenote.eighth-L4",
    "gracenote.eighth-S3",
    "note.beamedBoth3-L4",
    "note.whole-L2",
    "slur.start-L5",
    "slur.end-L5",
    "note.beamedBoth1-L6",
    "note.beamedBoth3-S3",
    "accidental.flat-S5",
    "note.quarter-S7",
    "note.half-S6",
    "note.beamedLeft3-S3",
    "digit.6-S5",
    "note.whole-S4",
    "gracenote.eighth-L5",
    "note.beamedLeft3-L4",
    "slur.start-S3",
    "slur.end-S3",
    "accidental.flat-L5",
    "note.beamedLeft2-S0",
    "note.beamedBoth3-L3",
    "digit.7-S5",
    "digit.5-S5",
    "note.beamedBoth3-S4",
    "note.beamedRight2-S6",
    "note.whole-L5",
    "digit.8-S5",
    "note.beamedLeft3-L3",
    "gracenote.eighth-S5",
    "note.beamedBoth2-L0",
    "note.beamedLeft1-S0",
    "note.beamedBoth3-S2",
    "gracenote.eighth-L3",
    "note.sixteenth-S1",
    "note.beamedRight2-S0",
    "note.beamedBoth1-S6",
    "note.beamedBoth3-L5",
    "note.eighth-L0",
    "accidental.natural-S2",
    "slur.start-L3",
    "slur.end-L3",
    "digit.0-S5",
    "note.quarter-S-1",
    "rest.whole-L4",
    "note.sixteenth-L6",
    "note.beamedRight1-L0",
    "note.beamedRight1-L7",
    "note.beamedLeft3-L5",
    "dot-S7",
    "slur.start-S5",
    "slur.end-S5",
    "note.whole-S1",
    "digit.4-L4",
    "digit.9-S5",
    "accidental.natural-S5",
    "gracenote.eighth-S2",
    "note.beamedLeft3-S4",
    "note.beamedBoth2-L7",
    "note.beamedRight3-L4",
    "note.sixteenth-L1",
    "note.beamedBoth3-S5",
    "note.beamedLeft2-L0",
    "note.half-L0",
    "slur.start-S2",
    "slur.end-S2",
    "note.beamedLeft2-L7",
    "note.beamedLeft3-S2",
    "note.beamedRight3-S2",
    "accidental.natural-L5",
    "accidental.natural-L2",
    "slur.start-L2",
    "slur.end-L2",
    "accidental.flat-S1",
    "note.beamedRight3-S3",
    "note.beamedLeft1-L0",
    "note.beamedBoth1-L0",
    "note.quarter-L-1",
    "dot-S-1",
    "note.beamedRight3-L3",
    "note.eighth-L7",
    "note.beamedLeft3-L2",
    "note.eighth-S7",
    "note.beamedRight1-S7",
    "note.beamedBoth3-L2",
    "clef.G-L1",
    "note.beamedBoth3-L6",
    "note.beamedLeft2-S-1",
    "note.beamedRight2-L0",
    "note.beamedLeft3-S5",
    "gracenote.sixteenth-S3",
    "accidental.sharp-L6",
    "note.whole-S5",
    "note.beamedLeft1-S-1",
    "note.beamedRight3-L5",
    "note.beamedRight2-L7",
    "note.beamedBoth3-L1",
    "note.whole-L1",
    "note.beamedLeft1-L7",
    "gracenote.sixteenth-L4",
    "gracenote.sixteenth-S4",
    "digit.12-L4",
    "note.eighth-S-1",
    "gracenote.eighth-L6",
    "slur.start-L6",
    "slur.end-L6",
    "gracenote.sixteenth-L5",
    "note.beamedRight1-S-1",
    "note.beamedLeft3-L1",
    "note.whole-S0",
    "note.beamedLeft3-L6",
    "note.beamedBoth1-L-1",
    "note.sixteenth-S0",
    "note.beamedRight3-S1",
    "note.beamedBoth2-S7",
    "accidental.natural-S1",
    "gracenote.sixteenth-L3",
    "note.beamedLeft3-S1",
    "rest.thirty_second-L3",
    "note.beamedBoth3-S1",
    "note.beamedBoth1-L7",
    "note.beamedRight3-S4",
    "note.beamedBoth3-S6",
    "note.beamedLeft1-L-1",
    "slur.start-S6",
    "slur.end-S6",
    "gracenote.eighth-L2",
    "note.beamedRight2-S7",
    "note.beamedBoth1-S-1",
    "note.beamedRight3-L2",
    "accidental.flat-L1",
    "note.half-S7",
    "note.sixteenth-S6",
    "gracenote.eighth-S1",
    "accidental.sharp-S0",
    "note.beamedBoth2-S-1",
    "accidental.natural-L1",
    "accidental.sharp-L0",
    "gracenote.sixteenth-S2",
    "accidental.flat-L6",
    "note.beamedRight1-L-1",
    "note.beamedLeft3-L0",
    "slur.start-S1",
    "slur.end-S1",
    "gracenote.sixteenth-L2",
    "note.half-L7",
    "note.beamedLeft1-S7",
    "note.eighth-L-1",
    "note.beamedLeft3-S6",
    "accidental.natural-S-1",
    "slur.start-S0",
    "slur.end-S0",
    "gracenote.sixteenth-S5",
    "note.quarter-S-2",
    "note.beamedLeft3-S0",
    "note.beamedBoth3-S0",
    "note.beamedLeft1-S-2",
    "clef.C-L2",
    "slur.start-L1",
    "slur.end-L1",
    "note.half-S-1",
    "accidental.natural-L6",
    "note.whole-L0",
    "note.beamedBoth1-S-2",
    "note.beamedBoth3-S-1",
    "digit.9-L4",
    "accidental.flat-S6",
    "note.beamedLeft2-S7",
    "accidental.flat-S-1",
    "note.beamedBoth3-L7",
    "slur.start-L7",
    "slur.end-L7",
    "note.beamedRight3-S6",
    "digit.1-L2",
    "accidental.natural-S6",
    "note.sixteenth-S7",
    "note.beamedRight2-S-1",
    "note.beamedLeft3-S-1",
    "note.beamedRight1-S-2",
    "note.beamedLeft3-L7",
    "note.thirty_second-S4",
    "note.beamedRight2-L-1",
    "note.whole-L7",
    "gracenote.eighth-L0",
    "note.whole-L6",
    "note.beamedBoth1-S7",
    "note.beamedBoth4-L3",
    "note.beamedRight3-S5",
    "note.sixteenth-L0",
    "gracenote.eighth-L1",
    "note.thirty_second-L2",
    "gracenote.thirty_second-L5",
    "note.beamedRight3-L0",
    "note.beamedLeft2-L-1",
    "note.beamedBoth3-L0",
    "note.double_whole-L2",
    "note.thirty_second-S3",
    "note.beamedBoth4-L5",
    "gracenote.sixteenth-S1",
    "note.beamedLeft2-S-2",
    "note.beamedRight3-L6",
    "gracenote.beamedBoth1-S4",
    "note.beamedRight3-S0",
    "note.beamedBoth4-L4",
    "note.beamedBoth4-S4",
    "note.thirty_second-L3",
    "note.double_whole-S3",
    "accidental.flat-S7",
    "note.beamedBoth3-L-1",
    "note.beamedLeft4-S5",
    "slur.start-S7",
    "slur.end-S7",
    "rest.sixty_fourth-L3",
    "gracenote.thirty_second-S5",
    "gracenote.thirty_second-L6",
    "note.eighth-L8",
    "note.beamedRight3-L1",
    "note.beamedBoth0-S4",
    "note.thirty_second-S2",
    "gracenote.sixteenth-L6",
    "note.thirty_second-L5",
    "accidental.natural-L0",
    "note.beamedBoth2-S-2",
    "note.beamedRight1-L8",
    "note.beamedLeft3-S7",
    "slur.start-L0",
    "slur.end-L0",
    "note.quarter-L8",
    "gracenote.beamedBoth1-L4",
    "note.beamedBoth4-S5",
    "gracenote.beamedBoth2-L4",
    "gracenote.beamedBoth1-S5",
    "note.beamedRight3-S7",
    "note.beamedBoth4-S3",
    "gracenote.thirty_second-S4",
    "note.half-L-1",
    "digit.16-L2",
    "note.eighth-S-2",
    "gracenote.thirty_second-L3",
    "note.whole-S6",
    "note.beamedBoth2-L-1",
    "note.eighth-S8",
    "gracenote.quarter-L4",
    "note.thirty_second-S5",
    "slur.start-S-1",
    "slur.end-S-1",
    "gracenote.beamedBoth2-S4",
    "note.beamedRight3-L7",
    "gracenote.sixteenth-L1",
    "note.beamedLeft0-L4",
    "gracenote.thirty_second-L4",
    "gracenote.quarter-S5",
    "accidental.sharp-L7",
    "note.double_whole-S4",
    "note.beamedRight0-S6",
    "note.beamedBoth2-L8",
    "note.thirty_second-L4",
    "accidental.natural-S0",
    "gracenote.quarter-L3",
    "gracenote.quarter-S2",
    "note.beamedRight0-S5",
    "clef.F-L3",
    "note.beamedLeft0-S5",
    "note.beamedBoth3-S7",
    "gracenote.eighth-S0",
    "gracenote.thirty_second-S0",
    "note.beamedLeft0-S3",
    "note.beamedRight2-S-2",
    "note.beamedLeft1-L8",
    "dot-S8",
    "note.beamedBoth4-S1",
    "note.beamedBoth4-L2",
    "note.beamedBoth4-S2",
    "note.beamedLeft4-S3",
    "note.beamedRight4-S2",
    "note.beamedRight2-L8",
    "accidental.flat-S0",
    "accidental.sharp-S6",
    "note.beamedRight0-L3",
    "note.beamedBoth0-L3",
    "note.half-L8",
    "note.beamedBoth0-S3",
    "accidental.natural-L7",
    "note.sixteenth-L7",
    "accidental.sharp-S-2",
    "note.double_whole-L3",
    "note.beamedLeft4-L2",
    "note.beamedRight0-S3",
    "gracenote.beamedBoth1-S3",
    "note.beamedBoth0-L4",
    "slur.start-L-1",
    "slur.end-L-1",
    "gracenote.beamedBoth2-S3",
    "note.beamedLeft4-L5",
    "note.beamedLeft4-L6",
    "note.beamedLeft4-S6",
    "gracenote.beamedBoth2-L5",
    "note.beamedBoth4-L1",
    "note.beamedLeft4-S2",
    "note.thirty_second-L1",
    "note.beamedBoth0-L2",
    "gracenote.beamedBoth1-L3",
    "gracenote.quarter-S4",
    "note.quarter-L-3",
    "note.double_whole-S2",
    "gracenote.beamedBoth2-S2",
    "note.sixteenth-L-1",
    "note.beamedLeft4-S4",
    "gracenote.thirty_second-S3",
    "dot-S-2",
    "gracenote.sixteenth-S0",
    "gracenote.thirty_second-L2",
    "note.thirty_second-L-1",
    "note.whole-S-1",
    "note.thirty_second-L6",
    "note.beamedLeft0-L5",
    "note.thirty_second-S6",
    "accidental.flat-L7",
    "gracenote.beamedBoth2-S5",
    "note.beamedRight3-S-2",
    "note.beamedLeft0-S2",
    "gracenote.beamedBoth1-S2",
    "gracenote.sixteenth-L-1",
    "note.thirty_second-S1",
    "note.beamedRight0-S2",
    "gracenote.beamedBoth1-L5",
    "gracenote.quarter-S3",
    "gracenote.beamedBoth3-L6",
    "note.beamedBoth0-S2",
    "note.beamedRight0-L5",
    "note.double_whole-S6",
    "note.eighth-L-2",
]
 
BLANK_IDX  = 0
VOCAB_SIZE = len(VOCAB)
SYM_TO_IDX = {s: i for i, s in enumerate(VOCAB)}
IDX_TO_SYM = {i: s for i, s in enumerate(VOCAB)}
 
 
# ── Pitch tables ──────────────────────────────────────────────────────────────
# Reference MIDI pitch at staff position step=0 (bottom line) for each clef.
#
# MIDI: C4=60, D4=62, E4=64, F4=65, G4=67, A4=69, B4=71
#
# Treble (clef.G): bottom line = E4 = 64
# Bass   (clef.F): bottom line = G2 = 43
# C clefs: bottom-line pitch derived from C4 position on each line:
#   C-L1: C4 on line 1 (step 0)  → bottom = C4 = 60
#   C-L2: C4 on line 2 (step 2)  → 2 diatonic steps below C4 → A3 = 57
#   C-L3: C4 on line 3 (step 4)  → 4 diatonic steps below C4 → F3 = 53
#   C-L4: C4 on line 4 (step 6)  → adjusted so that 49 + DIATONIC_OFFSET[6]=11 = 60
 
CLEF_REFERENCE = {
    "clef.G-L2": 64,   # E4 — standard treble clef
    "clef.G-L1": 64,   # E4 — treble variant
    "clef.F-L4": 43,   # G2 — standard bass clef
    "clef.F-L3": 43,   # G2 — bass variant
    "clef.C-L1": 60,   # C4 — soprano clef
    "clef.C-L2": 57,   # A3 — mezzo-soprano clef
    "clef.C-L3": 53,   # F3 — alto clef
    "clef.C-L4": 50,   # D3 — tenor C clef
}
 
# Tenor voice sounds an octave lower than written when using a treble clef
# (treble-8vb / vocal tenor clef). The CRNN outputs clef.G-L2 for both
# plain treble and treble-8vb, so we resolve the transposition via voice label.
TENOR_CLEF_REFERENCE = {
    "clef.G-L2": 52,   # E3 — treble 8vb (tenor sounding pitch)
    "clef.G-L1": 52,   # E3 — treble variant 8vb
    "clef.F-L4": 43,   # G2 — bass clef (no transposition needed)
    "clef.F-L3": 43,   # G2
    "clef.C-L1": 60,
    "clef.C-L2": 57,
    "clef.C-L3": 53,
    "clef.C-L4": 49,
}
 
# Voice → default clef when no clef token is detected on the strip.
# Tenor uses treble (modern SATB choral convention) — octave shift applied
# via get_clef_reference(), not via a different clef symbol.
CLEF_FALLBACK = {
    "Soprano": "clef.G-L2",
    "Alto":    "clef.G-L2",
    "Tenor":   "clef.G-L2",   # treble-8vb; transposed in get_clef_reference()
    "Bass":    "clef.F-L4",
}
 
 
def get_clef_reference(clef: str, voice: str) -> int:
    """
    Returns the MIDI pitch of the staff bottom line (step=0) for the given
    clef, applying the Tenor octave transposition when appropriate.
 
    Tenor uses treble clef in modern scores but sounds an octave lower
    (treble-8vb). Because the CRNN cannot distinguish plain treble from
    treble-8vb, the transposition is resolved here using the voice label.
    """
    if voice == "Tenor":
        return TENOR_CLEF_REFERENCE.get(clef, CLEF_REFERENCE.get(clef, 64))
    return CLEF_REFERENCE.get(clef, 64)
 
 
# Semitone offset of each natural note letter from C, within one octave.
# Staff half-steps are fixed to the LETTER positions E-F and B-C regardless
# of which note starts a given clef's own step=0 (bottom line) -- so the
# offset from a clef's bottom line to a given diatonic step depends on that
# clef's own bottom-line letter, not a single shared table. (Previously this
# was one generic C-anchored table applied to every clef, which was only
# correct for clef.C-L1 -- whose bottom line happens to be C -- and wrong by
# up to a semitone for treble, bass, and the other C clefs; see BUG-007.)
NATURAL_LETTER_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
LETTER_ORDER            = ["C", "D", "E", "F", "G", "A", "B"]


def _diatonic_delta(step: int, bottom_letter: str) -> int:
    """
    Semitone offset from a clef's bottom line (step=0) to diatonic `step`,
    for a clef whose bottom line is the note letter `bottom_letter`.

    Staff steps advance one letter name per step (line-to-space or
    space-to-line is always a diatonic 2nd), wrapping every 7 steps/12
    semitones. `step` may be negative (ledger lines below the staff).
    """
    def abs_semitone(letter_idx: int) -> int:
        octave, pos = divmod(letter_idx, 7)
        return octave * 12 + NATURAL_LETTER_SEMITONE[LETTER_ORDER[pos]]

    start_idx = LETTER_ORDER.index(bottom_letter)
    return abs_semitone(start_idx + step) - abs_semitone(start_idx)
 
# Bottom-staff-line letter (step=0) for each clef -- used both by
# _diatonic_delta (semitone offset) and _pitch_class_at_step (letter name,
# for key-signature accidental lookup) below.
CLEF_BOTTOM_LETTER = {
    "clef.G-L2": "E",  # Treble
    "clef.G-L1": "E",
    "clef.F-L4": "G",  # Bass
    "clef.F-L3": "G",
    "clef.C-L1": "C",  # Soprano
    "clef.C-L2": "A",  # Mezzo-soprano
    "clef.C-L3": "F",  # Alto
    "clef.C-L4": "D",  # Tenor C clef
}


def _pitch_class_at_step(step: int, bottom_letter: str) -> str:
    """
    Note-letter name at diatonic `step` for a clef whose bottom line is
    `bottom_letter`. Used only to look up key-signature alterations for a
    note (the letter repeats every octave, so this needs no semitone math).

    Unlike a fixed-range lookup table, this has no bound on `step` -- real
    Camera-PrIMuS scores use far-ledger-line notes (VOCAB includes suffixes
    down to L-3/S-2 and up to L8/S8) whose diatonic step, after the BUG-009
    pos-indexing fix, falls well outside any small hardcoded range; a fixed
    table silently defaulting out-of-range steps to "C" gave wrong
    key-signature accidentals on those notes (see BUG-010 investigation).
    """
    start_idx = LETTER_ORDER.index(bottom_letter)
    return LETTER_ORDER[(start_idx + step) % 7]
 
def _staff_step(pos_str: str) -> int:
    """Diatonic step (0 = bottom line) of an agnostic position suffix like "L4", "S3", "L-1".

    Camera-PrIMuS numbers the bottom line L1 and the space above it S1 (1-indexed), so pos is shifted
    down by one before doubling (BUG-009). Shared by infer_pitch and the visualization so a notehead is
    drawn on the same step its pitch was computed from.
    """
    loc = pos_str[0]
    pos = int(pos_str[1:])
    return (pos - 1) * 2 if loc == "L" else (pos - 1) * 2 + 1


ACCIDENTAL_OFFSET = {
    "accidental.sharp":       1,
    "accidental.flat":       -1,
    "accidental.natural":     0,
    "accidental.doubleSharp": 2,
    "accidental.doubleFlat": -2,
}

# PIYA-107 AC4/AC6: metersign token -> time signature string. "metersign.C" and
# "metersign.C/" are the only two metersign symbols in VOCAB (common time and
# cut time); anything else (no metersign detected, or a token not in this map)
# falls back to the AC4-mandated default of "4/4" via DEFAULT_TIME_SIGNATURE.
TIME_SIG_TOKENS = {
    "metersign.C":  "4/4",
    "metersign.C/": "2/2",
}
DEFAULT_TIME_SIGNATURE = "4/4"
 
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
FLAT_ORDER  = ["B", "E", "A", "D", "G", "C", "F"]
 
NOTE_DURATION_TICKS = {
    "whole":           1920,
    "half":             960,
    "quarter":          480,
    "eighth":           240,
    "sixteenth":        120,
    "thirty_second":     60,
    "sixty_fourth":      30,
    "double_whole":    3840,
    "quadruple_whole": 7680,
}
 
REST_DURATION_TICKS = NOTE_DURATION_TICKS


def _dotted_ticks(base_ticks: int, n_dots: int) -> int:
    """Duration of a note/rest with ``n_dots`` augmentation dots (PIYA-109 AC3).

    Each dot adds half of what the previous one added, not half of the running total: one dot is
    1.5x, two dots 1.75x, three 1.875x. Multiplying the running total by 1.5 per dot gave 2.25x for a
    double dot. Floored to whole ticks like the old ``int(x * 1.5)``; at PPQ 480 every value down to a
    double-dotted thirty-second is exact, the first inexact one is a double-dotted sixty-fourth
    (52.5 -> 52).
    """
    return base_ticks * (2 ** (n_dots + 1) - 1) // 2 ** n_dots
 
 
# ── Key signature position tables ─────────────────────────────────────────────
#
# Staff positions of key-signature accidentals in engraving order, in the
# 1-indexed agnostic convention (L1 = bottom line, S1 = space above it; see
# BUG-009). Used to tell a key-change burst after a barline from inline
# accidentals, and to spot a key signature whose clef the CRNN dropped.
#
# Treble sharps F5 C5 G5 D5 A4 E5 B4    Treble flats Bb4 Eb5 Ab4 Db5 Gb4 Cb5 Fb4
# Bass sharps   F3 C3 G3 D3 A2 E3 B2    Bass flats   Bb2 Eb3 Ab2 Db3 Gb2 Cb3 Fb2
#
# Only the in-scope SATB clefs are listed (no C clefs, user decision
# 2026-09-26); any other clef gets no key-change detection, so its
# post-barline accidentals are treated as inline.
KEY_SIG_ORDER: dict[str, dict[str, list[str]]] = {
    "clef.G-L2": {
        "accidental.sharp": ["L5", "S3", "S5", "L4", "S2", "S4", "L3"],
        "accidental.flat":  ["L3", "S4", "S2", "L4", "L2", "S3", "S1"],
    },
    "clef.F-L4": {
        "accidental.sharp": ["L4", "S2", "S4", "L3", "S1", "S3", "L2"],
        "accidental.flat":  ["L2", "S3", "S1", "L3", "L1", "S2", "S0"],
    },
}
# A lone accidental after a barline is far more often an inline accidental (or
# a CRNN phantom) than a one-accidental key change. Each strip restarts from
# its own key signature (CRNN-read, or the clef/key classifier's in the eval
# wrapper), so a missed 1-accidental change costs at most the rest of one
# strip. Hand-set, not tuned.
MIN_MID_KEY_CHANGE_ACCIDENTALS = 2


class HeaderOverride(NamedTuple):
    """Clef, opening key and octave decided outside the CRNN (ClefKeyNet + voice rule, stage3_clefkey).

    Attributes:
        clef_token: ``clef.G-L2`` or ``clef.F-L4``.
        key: Signed key signature, +sharps / -flats.
        octave_shift: Semitones added to the clef reference (0 or -12). Replaces Stage 3's voice-based
            Tenor octave, so the two can never both apply.
    """

    clef_token: str
    key: int
    octave_shift: int


def _signed_key_counts(key: int) -> tuple[int, int]:
    """(n_sharp, n_flat) for a signed key."""
    return (key, 0) if key > 0 else (0, -key)
 
 
# ── Pitch helpers ─────────────────────────────────────────────────────────────
 
def get_key_sig_alterations(sharp_count: int, flat_count: int) -> dict:
    """
    Returns {pitch_class: semitone_offset} for the given key signature.
      2 sharps → {"F": +1, "C": +1}   (D major)
      2 flats  → {"B": -1, "E": -1}   (Bb major)
      0, 0     → {}                   (C major)
    """
    alterations = {}
    if sharp_count > 0:
        for i in range(min(sharp_count, 7)):
            alterations[SHARP_ORDER[i]] = +1
    elif flat_count > 0:
        for i in range(min(flat_count, 7)):
            alterations[FLAT_ORDER[i]] = -1
    return alterations
 
 
def _is_keysig_position(sym: str, acc_type: str, active_clef: str) -> bool:
    """
    Returns True if this accidental token sits at a conventional key-signature
    staff position for the active clef.
 
      sym        full token e.g. "accidental.sharp-L5"
      acc_type   base type  e.g. "accidental.sharp"
      active_clef           e.g. "clef.G-L2"
    """
    suffix = _position_suffix(sym)
    return suffix is not None and suffix in KEY_SIG_ORDER.get(active_clef, {}).get(acc_type, [])


def _position_suffix(sym: str) -> Optional[str]:
    """Staff-position suffix of a token ("L5", "S3", "L-1"), or None if it has none."""
    return sym.split("-", 1)[1] if "-" in sym else None


def _next_note_position(symbols: list[str], idx: int) -> Optional[str]:
    """Position of the first note after ``symbols[idx]`` in the same measure, or None.

    A barline ends the search: an accidental never modifies a note in the next bar.
    """
    for sym in symbols[idx + 1:]:
        if sym.startswith("barline"):
            return None
        if sym.startswith("note."):
            return _position_suffix(sym)
    return None


def _accidental_is_anchored(symbols: list[str], idx: int) -> bool:
    """True if the inline accidental at ``idx`` sits on the staff position of the note it precedes.

    Engraving puts an accidental directly left of its notehead on the same line/space, so an accidental
    whose next note is elsewhere is a CRNN phantom. Diagnostic only, not accuracy evidence: on the
    eval_prelim camera runs (version b, 2026-09-28; development data by user decision, rule designed
    on them) only 26-36% of predicted inline sharps were real and this rule alone moved SOW pitch
    +0.9 to +1.3 pp. Cost: an accidental the CRNN places one step off its note is dropped (seen on
    distorted Camera-PrIMuS). Accepting +-1 step was worse on every dev pool and no better on Camera-PrIMuS,
    and the greedy-CTC evidence rescue tried in BUG-033 did not recover it either.
    """
    pos = _position_suffix(symbols[idx])
    return pos is not None and _next_note_position(symbols, idx) == pos


def _header_accidental_is_inline(symbols: list[str], idx: int) -> bool:
    """True if a pre-first-note accidental directly precedes a note on its own position.

    Stricter than _accidental_is_anchored, which looks past rests and header tokens: a key signature is
    engraved before the time signature and any rest, so a glyph followed by a metersign, digit, rest or
    multirest is a (misread) key-signature glyph, not the first note's accidental. Only slur and fermata
    tokens (engraved above/below the note, emitted before it) may sit between the accidental and its note.
    """
    pos = _position_suffix(symbols[idx])
    for sym in symbols[idx + 1:]:
        if sym.startswith(("slur.", "fermata.")):
            continue
        return pos is not None and sym.startswith("note.") and _position_suffix(sym) == pos
    return False


def _is_mid_key_change(burst: list[str], symbols: list[str], burst_end: int, acc_type: str, active_clef: str,
                       min_glyphs: int = MIN_MID_KEY_CHANGE_ACCIDENTALS) -> bool:
    """True if a same-type accidental burst right after a barline is a key change, not inline accidentals.

    Requires the burst to be exactly the leading part of a printed key signature (engraving positions and
    order) with at least ``min_glyphs`` glyphs, and the next note not to sit on the last glyph's position
    (that note would be the one the accidental belongs to).
    """
    order = KEY_SIG_ORDER.get(active_clef, {}).get(acc_type)
    if order is None or not burst or len(burst) < min_glyphs:
        return False
    positions = [_position_suffix(t) for t in burst]
    if positions != order[:len(burst)]:
        return False
    return _next_note_position(symbols, burst_end - 1) != positions[-1]


def _natural_led_key_change(symbols: list[str], start: int, active_clef: str,
                            key_alterations: dict[str, int],
                            confirmed: Optional[tuple[int, int]] = None) -> Optional[tuple[int, int, int]]:
    """Detects a key change that opens with naturals cancelling the old key (e.g. 2# -> 3b: ♮♮♭♭♭).

    Engravers print cancelling naturals whenever the new key drops accidentals or switches between
    sharps and flats, which covers the common "up a step for the last verse" modulation (choral-conductor
    review 2026-09-28). The naturals must sit on the old key's positions and the optional sharp/flat burst
    after them must be the leading part of a printed key signature, so phantom naturals rarely qualify.

    Args:
        confirmed: (n_sharp, n_flat) of a key read independently (ClefKeyNet on the next system); a change
            to exactly that key may have fewer than MIN_MID_KEY_CHANGE_ACCIDENTALS glyphs (BUG-029).

    Returns:
        (n_sharp, n_flat, end) of the new key and the index after the burst, or None.
    """
    order = KEY_SIG_ORDER.get(active_clef)
    if order is None or not key_alterations:
        return None
    old_type = "accidental.sharp" if next(iter(key_alterations.values())) > 0 else "accidental.flat"
    old_positions = order[old_type][:len(key_alterations)]

    nat_end = start
    while nat_end < len(symbols) and symbols[nat_end].startswith("accidental.natural"):
        nat_end += 1
    naturals = [_position_suffix(t) for t in symbols[start:nat_end]]
    if len(set(naturals)) != len(naturals) or not set(naturals) <= set(old_positions):
        return None

    new_type = symbols[nat_end].split("-")[0] if nat_end < len(symbols) else ""
    end = nat_end
    if new_type in order:
        while end < len(symbols) and symbols[end].split("-")[0] == new_type:
            end += 1
    burst = [_position_suffix(t) for t in symbols[nat_end:end]]
    if burst:
        if burst != order[new_type][:len(burst)] or set(burst) & set(naturals):
            return None
        n_new, type_new = len(burst), new_type
    else:
        # Naturals alone only shorten the old key, cancelling the last accidentals of its order.
        n_new, type_new = len(old_positions) - len(naturals), old_type
        if set(naturals) != set(old_positions[n_new:]):
            return None

    glyphs = naturals + burst
    result = (n_new, 0) if type_new == "accidental.sharp" else (0, n_new)
    if n_new == 0:
        result = (0, 0)
    enough = len(glyphs) >= MIN_MID_KEY_CHANGE_ACCIDENTALS or result == confirmed
    if not enough or _next_note_position(symbols, end - 1) == glyphs[-1]:
        return None
    return result + (end,)


# ── Pitch inference ────────────────────────────────────────────────────────────
 
def infer_pitch(
    symbols:    list,
    voice:      str = "Soprano",
    page_index: int = 1,
    sys_idx:    int = 1,
    confidences: Optional[list] = None,
    header_override: Optional[HeaderOverride] = None,
    next_system_key: Optional[int] = None,
    trace:      Optional[list] = None,
) -> list:
    """
    Converts a CRNN symbol sequence into note events with MIDI pitch.

    header_override: clef, opening key and octave decided by ClefKeyNet (stage3_clefkey). Every CRNN clef
    token is then ignored (the CRNN's clef can't override the rule, user decision 2026-09-28), and the
    CRNN's own header accidentals are not counted into the key: one directly before a note on its own
    position is kept as that note's inline accidental, the rest are dropped (BUG-027). The time signature is still read.
    next_system_key: ClefKeyNet's key for the following system (only used with header_override). A
    post-barline burst that is exactly that key's signature is a key change even with a single glyph
    (BUG-029); otherwise MIN_MID_KEY_CHANGE_ACCIDENTALS still applies.
    trace: optional out-list for the visualization. When given, one dict per
    input token is appended with the state right AFTER that token: which
    events it created (indices into the returned list), the clef in effect
    and its reference pitch, the committed key alterations, the time
    signature and the state-machine stage. It only reads state, so the
    returned events are identical with or without it.

    confidences: optional per-token CRNN confidences, parallel to `symbols`
    (same length, else ValueError). When given, every emitted note/rest event
    carries a "confidence" float; when None (ground-truth tokens) events have
    no "confidence" key at all, so Stage 4 can tell "no signal" from "0.0".
    A note's confidence is the MIN over the tokens that determined it: its
    own note token (duration + staff position are one token) and the inline
    accidental and dot tokens that modified it. Min, not mean: one misread
    constituent (say a phantom sharp) makes the whole pitch wrong however
    confident the rest are, and averaging would dilute that. Key-signature
    accidentals and the clef also shape pitch but apply to every note, so
    they are deliberately not folded into per-note confidence.

    Pitch formula:  M = R_c + Δ(p) + A(p)
      R_c   clef reference pitch at bottom line (voice-aware via get_clef_reference)
      Δ(p)  diatonic semitone offset for staff step p
      A(p)  alteration of step p, first match wins:
              1. an anchored inline accidental on this note (absolute: sharp +1,
                 flat -1, natural 0; it replaces the key alteration, BUG-024)
              2. a tie into this note from the same step keeps the tied note's
                 alteration (across a barline too, for this note only)
              3. an earlier accidental on the same step in this measure (costs
                 pitches when the CRNN drops a cancelling natural; kept on
                 notation grounds, net +26 notes on real dev pages, BUG-033)
              4. the key-signature alteration of the step's pitch class
      Inline accidentals not on the next note's staff position are dropped as
      CRNN phantoms (_accidental_is_anchored).

    Key-signature state machine
    ───────────────────────────
    "clef"
      Waiting for the opening clef symbol.
      • clef found                               → update active_clef /
                                                   reference_pitch, → "keysig"
      • accidental at valid key-sig position
        (clef dropped by CRNN)                   → infer clef was missed,
                                                   start counting, → "keysig"
      • accidental at wrong position             → inline if anchored, → "body"
      • metersign / note / rest                  → warn, commit empty key sig,
                                                   → "body", fall-through
 
    "keysig"
      Counting opening key-sig accidentals. No ambiguity — clef confirmed.
      • accidental.sharp (no flats yet)          → ks_sharp++, cap 7
      • accidental.flat  (no sharps yet)         → ks_flat++,  cap 7
      • mixed sharp+flat                         → CTC noise, skip
      • accidental.natural                       → CTC noise, skip
      • second clef                              → update reference, stay
      • metersign                                → commit, → "body"
      • note / rest                              → commit (no metersign on
                                                   continuation strips),
                                                   → "body", fall-through
 
    "body"
      Normal note / rest / accidental processing.
      On every barline                           → → "post_bar"
 
    "post_bar"
      Symbol immediately after a barline.
      • sharp/flat burst that _is_mid_key_change → commit new key, skip the
                                                   burst, → "body"
      • naturals cancelling the old key, then an → commit new key, skip the
        optional burst (_natural_led_key_change)   glyphs, → "body"
      • any other accidental                    → → "body", fall-through
                                                   (inline if anchored)
      • clef change                              → update reference, stay
      • anything else                            → → "body", fall-through

    "fixed_header" (header_override only; replaces "clef"/"keysig")
      • clef                                     → ignored
      • accidental directly before a note on its position → inline, stay
      • other accidental                         → dropped, stay
      • metersign / time-signature digits        → read time signature
      • note / rest                              → → "body", fall-through
    """

    # ── Initialise ────────────────────────────────────────────────────────
    active_clef     = CLEF_FALLBACK[voice]
    reference_pitch = get_clef_reference(active_clef, voice)
    clef_fixed      = header_override is not None
    confirmed_next: Optional[tuple[int, int]] = None
    if header_override is not None:
        if header_override.clef_token not in CLEF_REFERENCE:
            raise ValueError(f"header_override clef {header_override.clef_token!r} not in CLEF_REFERENCE")
        active_clef     = header_override.clef_token
        reference_pitch = CLEF_REFERENCE[active_clef] + header_override.octave_shift
        if next_system_key is not None and next_system_key != header_override.key:
            confirmed_next = _signed_key_counts(next_system_key)
 
    pending_acc: Optional[int] = None
    pending_acc_conf       = 1.0
    # Inline accidental rejected by _accidental_is_anchored, kept until the next note so that note
    # carries a trace of it: a real accidental placed one step off plays a wrong pitch (BUG-033).
    dropped_acc: Optional[str] = None
    dropped_acc_count      = 0
    # (alteration, accidental confidence) set by an inline accidental, per staff step, until the next
    # barline. The confidence travels with it so every note that inherits the accidental reports it.
    measure_alterations: dict[int, tuple[int, float]] = {}
    # Step/alteration of the last note, so a tie into the same step keeps its pitch across a barline.
    last_note_step: Optional[int] = None
    last_note_alteration: int = 0
    last_note_alt_conf: float = 1.0
    # Tokens before this index were consumed by a mid-piece key-change lookahead.
    skip_until             = 0
    # Dots stack on the event they follow; its undotted length is kept so a second dot adds a quarter
    # of it rather than half of the already-dotted length.
    dot_target: Optional[dict] = None
    dot_base               = 0
    dot_count              = 0
    chord_id               = 0
    in_chord               = False
    slur_active            = False
    slur_start_idx         = -1
    slur_end_pending       = False
    pending_multirest_bars = 1
    events                 = []
    current_tick           = 0
    # PIYA-107 AC4/AC6: defaults to 4/4 until an explicit metersign token is
    # consumed (see "keysig" stage below); every emitted event carries this
    # value regardless of whether the note itself is decorated with one.
    time_signature         = DEFAULT_TIME_SIGNATURE
    # 0-based measure counter, incremented on every barline. Barline tokens
    # themselves are never appended as events (they only drive the key-sig
    # state machine below), so this is the only place measure boundaries are
    # recorded -- needed for Stage 4's per-measure duration consistency check.
    measure_index          = 0
 
    # Key-sig state
    ks_stage        = "clef"
    ks_sharp        = 0
    ks_flat         = 0
    key_alterations = {}
    header_dropped  = 0
    # PIYA-107 AC4/AC6: Camera-PrIMuS encodes a numeric time signature (e.g.
    # "3/4") as two consecutive digit.N tokens in the header, rather than a
    # metersign.* token -- confirmed against ground truth: 1586/3996 (40%) of
    # corpus samples carry no metersign token at all and rely solely on this
    # digit-pair form. Only the first two header digit tokens are the time
    # signature (numerator, then denominator); any further digit tokens
    # before the first note/rest are unrelated noise and are ignored, same
    # as prior (pre-PIYA-107) behaviour.
    meter_digits = []
    meter_seen   = False  # fixed_header: a metersign was read, so later digits are multirest counts
 
    # ── Commit helpers ────────────────────────────────────────────────────
 
    def _commit_opening(n_sharp, n_flat):
        if n_sharp > 0 and n_flat > 0:
            print(f"[Stage 3] {voice} p{page_index}: "
                  "mixed accidentals in opening key sig — defaulting to C major")
            return {}
        alts = get_key_sig_alterations(n_sharp, n_flat)
        desc = (f"{n_sharp}#" if n_sharp else (f"{n_flat}b" if n_flat else "C major"))
        print(f"[Stage 3] {voice} p{page_index}: opening key sig {desc} -> {alts}")
        return alts
 
    def _commit_mid(n_sharp: int, n_flat: int) -> dict:
        # stage3_clefkey counts this exact log line ("mid-piece key change") to flag strips for review.
        alts = get_key_sig_alterations(n_sharp, n_flat)
        desc = f"{n_sharp}#" if n_sharp else (f"{n_flat}b" if n_flat else "C major")
        print(f"[Stage 3] {voice} p{page_index}: mid-piece key change {desc} -> {alts}")
        return alts

    if header_override is not None:
        key_alterations = _commit_opening(*_signed_key_counts(header_override.key))
        ks_stage = "fixed_header"

    if confidences is not None and len(confidences) != len(symbols):
        raise ValueError(
            f"confidences ({len(confidences)}) must be parallel to "
            f"symbols ({len(symbols)})")
    with_conf = confidences is not None

    # Trace entries are written at the top of the NEXT iteration (and once
    # after the loop) rather than at each of the loop body's many `continue`
    # points, so the pitch logic below is untouched.
    traced_events = 0

    def _trace_token(idx: int) -> None:
        nonlocal traced_events
        if trace is None:
            return
        trace.append({
            "token_index":     idx,
            "symbol":          symbols[idx],
            "event_indices":   list(range(traced_events, len(events))),
            "active_clef":     active_clef,
            "reference_pitch": reference_pitch,
            "key_alterations": dict(key_alterations),
            "time_signature":  time_signature,
            "stage":           ks_stage,
            # A mid-piece key-signature burst is consumed by lookahead (skip_until), so its glyphs never
            # reach a stage of their own; this is the only way the viz can tell them from inline accidentals.
            "key_change_glyph": idx < skip_until,
            "clef_fixed":      clef_fixed,
        })
        traced_events = len(events)

    # ── Main loop ─────────────────────────────────────────────────────────
    for tok_idx, sym in enumerate(symbols):
        if tok_idx:
            _trace_token(tok_idx - 1)

        if tok_idx < skip_until:
            continue
        tok_conf = float(confidences[tok_idx]) if with_conf else 1.0
        acc_type = sym.split("-")[0]
        is_sharp = sym.startswith("accidental.sharp")
        is_flat  = sym.startswith("accidental.flat")
        is_acc   = sym.startswith("accidental.")

        # ══════════════════════════════════════════════════════════════════
        # KEY-SIG STATE MACHINE
        # ══════════════════════════════════════════════════════════════════
 
        # ── "clef" ────────────────────────────────────────────────────────
        if ks_stage == "clef":
 
            if sym.startswith("clef."):
                if sym in CLEF_REFERENCE:
                    active_clef     = sym
                    reference_pitch = get_clef_reference(sym, voice)
                ks_stage = "keysig"
                continue
 
            elif is_sharp or is_flat:
                if _is_keysig_position(sym, acc_type, active_clef):
                    print(f"[Stage 3] {voice} p{page_index}: "
                          f"clef not detected — inferring from key-sig position ({sym})")
                    ks_sharp = 1 if is_sharp else 0
                    ks_flat  = 1 if is_flat  else 0
                    ks_stage = "keysig"
                else:
                    if _accidental_is_anchored(symbols, tok_idx):
                        pending_acc      = ACCIDENTAL_OFFSET.get(acc_type, 0)
                        pending_acc_conf = tok_conf
                    else:
                        dropped_acc = sym
                        dropped_acc_count += 1
                    ks_stage = "body"
                continue

            elif (sym.startswith("metersign") or
                  sym.startswith("note.")     or
                  sym.startswith("rest.")):
                print(f"[Stage 3] Warning: {voice} p{page_index}: "
                      f"no clef detected — using fallback {active_clef}, C major assumed")
                key_alterations = _commit_opening(0, 0)
                if sym.startswith("metersign"):
                    time_signature = TIME_SIG_TOKENS.get(
                        sym.split("-")[0], time_signature)
                ks_stage        = "body"
                # fall through to body processing below
 
            elif sym.startswith("slur.end"):
                # Header slur.end = tie arriving from the previous system;
                # carry it to the first note instead of dropping it. No
                # slur.start is invented: only "end" is recorded.
                slur_end_pending = True
                continue

            else:
                continue    # barline / digit / slur.start before clef — skip
 
        # ── "fixed_header" ────────────────────────────────────────────────
        elif ks_stage == "fixed_header":

            if sym.startswith("clef."):
                continue
            elif is_acc:
                if _header_accidental_is_inline(symbols, tok_idx):
                    pending_acc      = ACCIDENTAL_OFFSET.get(acc_type, 0)
                    pending_acc_conf = tok_conf
                else:
                    header_dropped += 1
                continue
            elif sym.startswith("metersign"):
                # Stay in the header: an accidental after the metersign is still a misread key glyph
                # unless it sits directly on the first note, and must not reach body's looser anchoring.
                time_signature = TIME_SIG_TOKENS.get(sym.split("-")[0], time_signature)
                meter_seen     = True
                continue
            elif sym.startswith("digit.") and not meter_seen and len(meter_digits) < 2:
                try:
                    meter_digits.append(int(sym.split(".")[1].split("-")[0]))
                except ValueError:
                    pass
                continue
            elif sym.startswith(("note.", "rest.", "multirest", "digit.")):
                # A digit here follows a complete meter, so it is a multirest count for body.
                if len(meter_digits) == 2 and not meter_seen:
                    time_signature = f"{meter_digits[0]}/{meter_digits[1]}"
                ks_stage = "body"
                # fall through to body processing below
            elif sym.startswith("slur.end"):
                slur_end_pending = True
                continue
            else:
                continue    # barline / slur.start in header — skip

        # ── "keysig" ──────────────────────────────────────────────────────
        elif ks_stage == "keysig":
 
            if is_sharp and ks_flat == 0:
                ks_sharp = min(ks_sharp + 1, 7)
                continue
            elif is_flat and ks_sharp == 0:
                ks_flat = min(ks_flat + 1, 7)
                continue
            elif is_sharp or is_flat:
                print(f"[Stage 3] {voice} p{page_index}: "
                      f"mixed accidental in opening key sig region ({sym}) — ignoring")
                continue
            elif sym.startswith("accidental.natural"):
                continue    # natural in opening region = CTC noise
            elif sym.startswith("clef."):
                if sym in CLEF_REFERENCE:
                    active_clef     = sym
                    reference_pitch = get_clef_reference(sym, voice)
                continue
            elif sym.startswith("metersign"):
                key_alterations = _commit_opening(ks_sharp, ks_flat)
                time_signature  = TIME_SIG_TOKENS.get(
                    sym.split("-")[0], time_signature)
                ks_stage        = "body"
                continue
            elif sym.startswith("digit.") and len(meter_digits) < 2:
                # Numeric time signature (e.g. "3/4"), Camera-PrIMuS's other
                # encoding besides metersign.* -- see meter_digits comment
                # at initialisation. A 3rd+ header digit (rare CTC noise /
                # unrelated token) is left to the catch-all `else` below.
                try:
                    meter_digits.append(int(sym.split(".")[1].split("-")[0]))
                except ValueError:
                    pass
                continue
            elif sym.startswith("note.") or sym.startswith("rest."):
                # No meter sign (continuation strip) — commit on first note
                key_alterations = _commit_opening(ks_sharp, ks_flat)
                if len(meter_digits) == 2:
                    time_signature = f"{meter_digits[0]}/{meter_digits[1]}"
                ks_stage        = "body"
                # fall through to body processing below
            elif sym.startswith("slur.end"):
                # See "clef" stage: carry a header slur.end to the first note
                # (cross-system tie arrival) rather than silently dropping it.
                slur_end_pending = True
                continue
            else:
                continue    # barline / digit / slur.start in header — skip
 
        # ── "post_bar" ────────────────────────────────────────────────────
        elif ks_stage == "post_bar":

            if sym.startswith("accidental.natural"):
                change = _natural_led_key_change(symbols, tok_idx, active_clef, key_alterations,
                                                 confirmed_next)
                if change is not None:
                    n_sharp, n_flat, skip_until = change
                    key_alterations = _commit_mid(n_sharp, n_flat)
                    ks_stage = "body"
                    continue
                ks_stage = "body"
                # fall through: an inline natural candidate

            elif is_sharp or is_flat:
                burst_end = tok_idx
                while burst_end < len(symbols) and symbols[burst_end].split("-")[0] == acc_type:
                    burst_end += 1
                burst = symbols[tok_idx:burst_end]
                n = 0
                if _is_mid_key_change(burst, symbols, burst_end, acc_type, active_clef):
                    n = len(burst)
                elif _is_mid_key_change(burst[:-1], symbols, burst_end - 1, acc_type, active_clef):
                    # The last glyph sits on the next note: read it as that note's accidental and keep
                    # the rest as the key change, instead of losing the key change for the whole strip.
                    n = len(burst) - 1
                elif (confirmed_next is not None
                      and _signed_key_counts(len(burst) if is_sharp else -len(burst)) == confirmed_next
                      and _is_mid_key_change(burst, symbols, burst_end, acc_type, active_clef, min_glyphs=1)):
                    # Too short for the unconfirmed rule, but it is exactly the key ClefKeyNet reads on the
                    # next system (BUG-029).
                    n = len(burst)
                elif (confirmed_next is not None and len(burst) > 1
                      and _signed_key_counts(len(burst) - 1 if is_sharp else 1 - len(burst)) == confirmed_next
                      and _is_mid_key_change(burst[:-1], symbols, burst_end - 1, acc_type, active_clef,
                                             min_glyphs=1)):
                    # As above, with the last glyph belonging to the next note (e.g. #L5 #S3 note-S3).
                    n = len(burst) - 1
                if n:
                    new_alts = get_key_sig_alterations(n if is_sharp else 0, n if is_flat else 0)
                    # A burst repeating the current key (cautionary reprint or phantom) changes nothing;
                    # committing it would log "mid-piece key change" and flag the strip for review.
                    if new_alts != key_alterations:
                        key_alterations = _commit_mid(n if is_sharp else 0, n if is_flat else 0)
                    skip_until = tok_idx + n
                    ks_stage = "body"
                    continue
                ks_stage = "body"
                # fall through: not a key change, so each accidental is an inline candidate

            elif sym.startswith("clef."):
                if sym in CLEF_REFERENCE and not clef_fixed:
                    active_clef     = sym
                    reference_pitch = get_clef_reference(sym, voice)
                # Stay in "post_bar" — key sig accidentals may still follow
                continue

            else:
                ks_stage = "body"
                # fall through to body processing below
 
        # ══════════════════════════════════════════════════════════════════
        # BODY — process musical symbols
        # Reached by fall-through from state transitions above, or directly
        # when ks_stage was already "body" at loop top.
        # ══════════════════════════════════════════════════════════════════
 
        if ks_stage != "body":
            continue
 
        # ── Clef change mid-piece ─────────────────────────────────────────
        if sym.startswith("clef."):
            if sym in CLEF_REFERENCE and not clef_fixed:
                active_clef     = sym
                reference_pitch = get_clef_reference(sym, voice)
            continue
 
        # ── Inline accidental ─────────────────────────────────────────────
        if is_acc:
            if _accidental_is_anchored(symbols, tok_idx):
                pending_acc      = ACCIDENTAL_OFFSET.get(acc_type, 0)
                pending_acc_conf = tok_conf
            else:
                dropped_acc = sym
                dropped_acc_count += 1
            continue
 
        # ── Dot (augmentation) ────────────────────────────────────────────
        if sym.startswith("dot-"):
            # A dot never follows a multi-measure rest in engraving; stretching one would shift every
            # later bar of this voice, so a (misread) dot there is dropped.
            if events and not events[-1]["symbol"].startswith("multirest"):
                if events[-1] is not dot_target:
                    dot_target = events[-1]
                    dot_base   = dot_target["duration_ticks"]
                    dot_count  = 0
                dot_count += 1
                old_ticks = events[-1]["duration_ticks"]
                new_ticks = _dotted_ticks(dot_base, dot_count)
                events[-1]["duration_ticks"] = new_ticks
                # The cursor already advanced by old_ticks when the note/rest
                # was emitted; without also advancing by the extra half, every
                # later onset overlaps the dotted note. Only when this event
                # is the one that moved the cursor: a chord tail (in_chord)
                # never advanced it, so dotting the tail must not either.
                if (not in_chord and
                        events[-1]["tick_onset"] + old_ticks == current_tick):
                    current_tick += new_ticks - old_ticks
                if with_conf:
                    events[-1]["confidence"] = min(
                        events[-1]["confidence"], tok_conf)
            continue
 
        # ── Rest ──────────────────────────────────────────────────────────
        if sym.startswith("rest."):
            dur_name = sym.split(".")[1].split("-")[0]
            ticks    = REST_DURATION_TICKS.get(dur_name, 480)
            events.append({
                "type":           "rest",
                "pitch":          None,
                "duration_ticks": ticks,
                "voice":          voice,
                "page_index":     page_index,
                "sys_idx":        sys_idx,
                "chord_id":       None,
                "symbol":         sym,
                "tick_onset":     current_tick,
                "slur":           None,
                "measure_index":  measure_index,
                "time_signature": time_signature,
            })
            if with_conf:
                events[-1]["confidence"] = tok_conf
            current_tick += ticks
            in_chord      = False
            slur_end_pending = False   # a tie cannot run into a rest
            continue
 
        # ── Note ──────────────────────────────────────────────────────────
        if sym.startswith("note."):
            inner    = sym[5:]                       # "quarter-L4"
            dash_idx = inner.index("-")
            dur_name = inner[:dash_idx]              # "quarter", "beamedRight1", …
            pos_str  = inner[dash_idx + 1:]          # "L4", "S3", "L-1"
 
            # Map beamed variants → base duration
            for prefix in ("beamedRight", "beamedLeft", "beamedBoth"):
                if dur_name.startswith(prefix):
                    beam_num = int("".join(filter(str.isdigit, dur_name)) or 1)
                    dur_name = {
                        0: "eighth",
                        1: "eighth",
                        2: "sixteenth",
                        3: "thirty_second",
                        4: "sixty_fourth",
                    }.get(beam_num, "eighth")
                    break
 
            # Parse position suffix → diatonic step number.
            # Camera-PrIMuS agnostic encoding numbers the bottom staff line
            # L1 (not L0) and the space just above it S1 -- i.e. pos is
            # 1-indexed from the bottom line, not 0-indexed -- so pos must be
            # shifted down by one before doubling to land step=0 on the
            # bottom line, matching STEP_TO_PITCH_CLASS/_diatonic_delta's own
            # step=0-is-bottom-line convention (see BUG-009).
            step = _staff_step(pos_str)

            bottom_letter = CLEF_BOTTOM_LETTER.get(active_clef, "E")
            delta         = _diatonic_delta(step, bottom_letter)
 
            # Alteration precedence: see A(p) in the docstring.
            alt_conf = 1.0   # key-signature alterations are excluded from confidence
            if pending_acc is not None:
                alteration, alt_conf = pending_acc, pending_acc_conf
                measure_alterations[step] = (alteration, alt_conf)
            elif slur_end_pending and last_note_step == step:
                # Not stored in measure_alterations: a tie carries the accidental into the next bar for the
                # tied note only, later notes on that step fall back to the key.
                alteration, alt_conf = last_note_alteration, last_note_alt_conf
            elif step in measure_alterations:
                alteration, alt_conf = measure_alterations[step]
            else:
                alteration = key_alterations.get(_pitch_class_at_step(step, bottom_letter), 0)
            note_conf = min(tok_conf, alt_conf)
            pending_acc = None
            last_note_step, last_note_alteration, last_note_alt_conf = step, alteration, alt_conf

            midi_pitch  = max(0, min(127,
                reference_pitch + delta + alteration))
 
            ticks = NOTE_DURATION_TICKS.get(dur_name, 480)
 
            # Chord detection — consecutive notes sharing the same tick onset
            if (events
                    and events[-1]["type"] == "note"
                    and events[-1]["tick_onset"] == current_tick):
                if not in_chord:
                    chord_id += 1
                    events[-1]["chord_id"] = chord_id
                in_chord = True
                c_id     = chord_id
            else:
                in_chord = False
                c_id     = None
 
            events.append({
                "type":           "note",
                "pitch":          midi_pitch,
                "duration_ticks": ticks,
                "voice":          voice,
                "page_index":     page_index,
                "sys_idx":        sys_idx,
                "chord_id":       c_id,
                "symbol":         sym,
                "tick_onset":     current_tick,
                "slur":           ("end" if slur_end_pending
                                   else "middle" if slur_active else None),
                "measure_index":  measure_index,
                "time_signature": time_signature,
            })
            if with_conf:
                events[-1]["confidence"] = note_conf
            if dropped_acc is not None:
                events[-1]["unanchored_accidental_dropped"] = dropped_acc
                dropped_acc = None
            if slur_end_pending:
                # A tie chain (A~A~A) puts slur.end then slur.start on the
                # middle note; the later "start" overwrites "slur", so the
                # end mark is kept separately for Stage 4's tie inference.
                events[-1]["slur_end"] = True
            slur_end_pending = False
            if not in_chord:
                current_tick += ticks
            continue
 
        # ── Barline ───────────────────────────────────────────────────────
        if sym.startswith("barline"):
            pending_acc = None      # stale inline accidental — discard
            dropped_acc = None
            measure_alterations = {}
            in_chord    = False
            ks_stage    = "post_bar"
            measure_index += 1
            continue
 
        # ── Multirest ─────────────────────────────────────────────────────
        if sym.startswith("multirest"):
            ticks = NOTE_DURATION_TICKS["whole"] * pending_multirest_bars
            events.append({
                "type":           "rest",
                "pitch":          None,
                "duration_ticks": ticks,
                "voice":          voice,
                "page_index":     page_index,
                "sys_idx":        sys_idx,
                "chord_id":       None,
                "symbol":         sym,
                "tick_onset":     current_tick,
                "slur":           None,
                "measure_index":  measure_index,
                "time_signature": time_signature,
            })
            if with_conf:
                events[-1]["confidence"] = tok_conf
            current_tick += ticks
            # A multirest is engraved between exactly one pair of barlines
            # regardless of how many bars it spans (digit.N gives that count),
            # so unlike ordinary notes it needs its own measure_index bump here
            # -- the barline-token handler above only ever adds 1 per barline
            # token, which would otherwise under-count by (N-1) bars and
            # permanently desync this voice's measure_index against SATB
            # voices that notate the same span as N separate measures. Bump
            # by (N-1), not N: the barline token that follows this multirest
            # still fires normally and supplies the final +1.
            measure_index          += (pending_multirest_bars - 1)
            pending_multirest_bars  = 1
            in_chord                = False
            continue
 
        # ── Digit (multirest count) ───────────────────────────────────────
        if sym.startswith("digit."):
            try:
                pending_multirest_bars = int(sym.split(".")[1].split("-")[0])
            except ValueError:
                pass
            continue
 
        # ── Slur ─────────────────────────────────────────────────────────
        if sym.startswith("slur.start"):
            slur_active = True
            if events:
                events[-1]["slur"] = "start"
                slur_start_idx     = len(events) - 1
            continue
 
        if sym.startswith("slur.end"):
            # In Camera-PrIMuS token order slur.end sits BEFORE the note it
            # ends on (start follows note 1, end precedes note 2; verified on
            # all 676 slur pairs in the corpus, which are all semantic ties),
            # so the "end" mark belongs on the next note, not events[-1] --
            # marking events[-1] overwrote the "start" mark on note 1 and left
            # Stage 4 with no start/end pair at all.
            slur_active      = False
            slur_end_pending = True
            continue

    if symbols:
        _trace_token(len(symbols) - 1)
    if dropped_acc_count:
        print(f"[Stage 3] {voice} p{page_index} s{sys_idx}: dropped {dropped_acc_count} "
              "unanchored accidental(s) (not on the next note's staff position)")
    if header_dropped:
        print(f"[Stage 3] {voice} p{page_index} s{sys_idx}: dropped {header_dropped} CRNN header "
              "accidental(s) (key taken from header_override)")
    return events
 
 
# ── Model ─────────────────────────────────────────────────────────────────────
 
class ResNetBlock(nn.Module):
    """Basic residual block: two 3×3 convs with skip connection."""
    def __init__(self, channels: int):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn1   = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn2   = nn.BatchNorm2d(channels)
 
    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        return F.relu(x + residual)
 
 
class CRNN(nn.Module):
    """
    CRNN for music symbol recognition.
 
    CNN backbone (ResNet-style):
      Conv → Pool → ResBlock × 2 → Pool → ResBlock × 2 → Pool × 2
 
    RNN head:
      2-layer BiLSTM → linear projection → log-softmax over vocab
 
    Input:  (B, 1, H, W)  — grayscale strip, H=64 after resize
    Output: (T, B, vocab_size) — CTC-ready log-probs
    """
    def __init__(self, vocab_size: int = VOCAB_SIZE,
                 rnn_hidden: int = 256, rnn_layers: int = 2):
        super().__init__()
 
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
 
            ResNetBlock(64),
            nn.Conv2d(64, 128, 3, padding=1, bias=False),
            nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
 
            ResNetBlock(128), ResNetBlock(128),
            nn.Conv2d(128, 256, 3, padding=1, bias=False),
            nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1), (2, 1)),
 
            ResNetBlock(256), ResNetBlock(256),
            nn.Conv2d(256, 512, 3, padding=1, bias=False),
            nn.BatchNorm2d(512), nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1), (2, 1)),
 
            nn.AdaptiveAvgPool2d((1, None)),
        )
 
        self.rnn = nn.LSTM(
            input_size=512,
            hidden_size=rnn_hidden,
            num_layers=rnn_layers,
            batch_first=False,
            bidirectional=True,
            dropout=0.3 if rnn_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(rnn_hidden * 2, vocab_size)
 
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.cnn(x)
        features = features.squeeze(2)
        features = features.permute(2, 0, 1)
        output, _ = self.rnn(features)
        output = self.fc(output)
        return F.log_softmax(output, dim=2)
 
 
# Input-pixel width of one CTC frame: the two MaxPool2d(2, 2) layers in
# CRNN.cnn each halve the width; the (2, 1) pools only shrink height. Must be
# changed together with the backbone or token x-positions drift.
CNN_WIDTH_STRIDE = 4


# ── Inference ─────────────────────────────────────────────────────────────────
 
def _greedy_ctc_decode(log_probs: torch.Tensor) -> list:
    """
    Greedy CTC decoding: argmax at each timestep then collapse.
    log_probs: (T, vocab_size)
    Returns list of symbol indices (blanks and duplicates removed).
    """
    decoded, _ = _greedy_ctc_decode_with_confidence(log_probs)
    return decoded


def _greedy_ctc_decode_with_confidence(
    log_probs: torch.Tensor,
    spans_out: Optional[List[Tuple[int, int]]] = None,
) -> Tuple[List[int], List[float]]:
    """
    Greedy CTC decode that also reports a per-symbol confidence score.

    Decode logic (collapse repeats, then drop blanks) is unchanged from
    the original argmax-loop version -- grouping consecutive identical
    argmax indices via itertools.groupby is equivalent to that loop's
    "idx != prev" check, since both only merge *strictly consecutive*
    equal indices (a blank timestep between two equal non-blank runs
    still starts a new group/is not equal to prev, so it is not
    incorrectly merged).

    Confidence for each decoded symbol is the mean softmax probability
    (not log-prob) of the argmax class across every consecutive timestep
    collapsed into that symbol -- i.e. how confident the model was, on
    average, over the run of frames that produced this one output token.
    Intended for flagging likely-wrong decodes on distorted/camera-captured
    input without needing ground truth (see the 0.70% clean vs 18.76%
    distorted SER gap measured on Camera-PrIMuS this session).

    Args:
        log_probs: (T, vocab_size) log-softmax output from the CRNN.
        spans_out: If a list is given, one (first_frame, last_frame + 1)
          pair per decoded symbol is appended to it -- the CTC alignment the
          visualization uses to place each token. Passed as an out-list so
          the return value (and every existing caller) is unchanged.

    Returns:
        (decoded_indices, confidences) -- parallel lists; confidences[i]
        is the mean max-softmax-probability for decoded_indices[i].
    """
    probs = log_probs.exp()  # log-softmax -> softmax probabilities
    max_probs, indices = probs.max(dim=1)
    indices = indices.tolist()
    max_probs = max_probs.tolist()

    decoded, confidences = [], []
    frame = 0
    for idx, group in itertools.groupby(zip(indices, max_probs), key=lambda pair: pair[0]):
        group_probs = [p for _, p in group]
        start, frame = frame, frame + len(group_probs)
        if idx == BLANK_IDX:
            continue
        decoded.append(idx)
        confidences.append(sum(group_probs) / len(group_probs))
        if spans_out is not None:
            spans_out.append((start, frame))
    return decoded, confidences
 
 
def transcribe_strip(
    image:             np.ndarray,
    model:             CRNN,
    device:            torch.device,
    img_height:        int = 64,
    return_confidence: bool = False,
    strip_id:          str = "",
    spans_out:         Optional[List[Tuple[float, float]]] = None,
) -> Union[List[str], List[Tuple[str, float]]]:
    """
    Runs CRNN-CTC inference on a single staff strip.

    Args:
        image:      BGR or grayscale strip from Stage 2.
        model:      Loaded CRNN model in eval mode.
        device:     torch device.
        img_height: Must match training height used on Kaggle.
        return_confidence: If True, returns (symbol, confidence) pairs
          instead of bare symbol strings. Confidence is the mean CTC
          softmax probability across the timesteps collapsed into that
          symbol -- useful for flagging likely-wrong decodes on distorted
          input without ground truth. Defaults to False so every existing
          caller (process_strip, Stage 4's event pipeline) is unaffected.
        strip_id: Optional identifier (e.g. "page001_sys01_Soprano_vidx1")
          used only to tag diagnostic logging -- lets BUG-011-style
          misreads be traced back to a specific strip's input tensor shape
          and raw (pre-infer_pitch) decoded tokens. Purely a log tag; has
          no effect on inference.
        spans_out: If a list is given, one (x_start, x_end) pair per returned
          symbol is appended, in pixels of the input strip (before the
          height resize). This is the CTC frame alignment, not a detection:
          CTC is peaky, so a token usually owns one or two frames that land
          somewhere on its glyph, and the BiLSTM can shift that by a frame.

    Returns:
        List[str] symbols in reading order (default), or
        List[Tuple[str, float]] (symbol, confidence) pairs if
        return_confidence=True.
    """
    if len(image.shape) == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    h, w = image.shape
    new_w = max(1, int(w * img_height / h))
    image = cv2.resize(image, (new_w, img_height), interpolation=cv2.INTER_AREA)

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])
    tensor = transform(image).unsqueeze(0).to(device)
    logger.info("transcribe_strip strip_id=%s input_tensor_shape=%s", strip_id, tuple(tensor.shape))

    with torch.no_grad():
        log_probs = model(tensor)           # (T, 1, V)
    log_probs = log_probs.squeeze(1)        # (T, V)

    frame_spans: Optional[List[Tuple[int, int]]] = [] if spans_out is not None else None
    if return_confidence or frame_spans is not None:
        # Same decode as _greedy_ctc_decode (which wraps this function), so
        # asking for spans cannot change the tokens.
        indices, confidences = _greedy_ctc_decode_with_confidence(log_probs, frame_spans)
        px_per_frame = CNN_WIDTH_STRIDE * w / new_w
        if spans_out is not None and frame_spans is not None:
            spans_out.extend((s * px_per_frame, e * px_per_frame) for s, e in frame_spans)

    if return_confidence:
        tokens = [(IDX_TO_SYM.get(i, "<unk>"), c) for i, c in zip(indices, confidences)]
        logger.info("transcribe_strip strip_id=%s raw_tokens=%s", strip_id, [t for t, _ in tokens])
        return tokens

    if frame_spans is None:
        indices = _greedy_ctc_decode(log_probs)
    tokens = [IDX_TO_SYM.get(i, "<unk>") for i in indices]
    logger.info("transcribe_strip strip_id=%s raw_tokens=%s", strip_id, tokens)
    return tokens
 
 
# ── Visualization ─────────────────────────────────────────────────────────────
#
# One annotated image per strip: a box per decoded token at its CTC-aligned x
# position (and, for notes, on the staff step its pitch was computed from),
# with a sounding-pitch ASPN label (C4 = MIDI 60). Labels are derived here
# from infer_pitch's events + trace so the event JSON schema is unchanged.

VIZ_SCALE              = 4      # strips are 64 px tall; upscale so tags are readable
VIZ_LANE_HEIGHT        = 22     # px per tag row above/below the staff
VIZ_LANES_PER_SIDE     = 4
VIZ_HEADER_HEIGHT      = 30
VIZ_CAPTION_LINE       = 18
VIZ_FONT               = cv2.FONT_HERSHEY_SIMPLEX
VIZ_TAG_FONT_SCALE     = 0.5
VIZ_SMALL_FONT_SCALE   = 0.42
VIZ_TAG_PAD            = 3
# Below this mean CTC probability a box is drawn orange. The CRNN is
# confidently wrong on real photos (BUG-011), so orange flags doubt; red is
# not a correctness claim.
VIZ_LOW_CONFIDENCE     = 0.80
# Half-height of a notehead box and minimum token box width, in staff spacings.
VIZ_HEAD_HALF_HEIGHT   = 0.6
VIZ_MIN_BOX_WIDTH      = 1.2
# A row counts as a staff line when at least this fraction of it is ink; the
# strip's left part (voice name, bracket) has no lines, so this is not 1.0.
STAFF_LINE_INK_FRACTION = 0.5
STAFF_LINE_INK_LEVEL    = 128   # gray < this is ink
N_STAFF_LINES           = 5

COLOR_BOX      = (40, 40, 220)     # BGR red
COLOR_BOX_LOW  = (0, 140, 255)     # BGR orange
COLOR_TAG_BG   = (20, 20, 20)
COLOR_TAG_FG   = (255, 255, 255)
COLOR_MINOR_BG = (110, 110, 110)   # dots, slurs, inline accidentals, digits
COLOR_BARLINE  = (170, 120, 40)
COLOR_TEXT     = (30, 30, 30)

DURATION_LABELS = {
    "whole": "whole", "half": "half", "quarter": "quarter", "eighth": "8th",
    "sixteenth": "16th", "thirty_second": "32nd", "sixty_fourth": "64th",
    "double_whole": "breve", "quadruple_whole": "long",
}
ALTER_TEXT = {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}
MAJOR_BY_SHARPS = ["C", "G", "D", "A", "E", "B", "F#", "C#"]
MINOR_BY_SHARPS = ["A", "E", "B", "F#", "C#", "G#", "D#", "A#"]
MAJOR_BY_FLATS  = ["C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"]
MINOR_BY_FLATS  = ["A", "D", "G", "C", "F", "Bb", "Eb", "Ab"]
VIZ_CAPTION = ("Labels show sounding pitch; tenor parts in a plain G clef sound an octave "
               "below written.")


SEMITONES_PER_OCTAVE = 12
OCTAVE_CLEF_LETTERS = ("G", "F")  # in-scope clefs; C clefs are labelled out of scope


def _octaves_below(clef: str, reference_pitch: int) -> int:
    """Octaves a G or F clef is played below written (0 when it sounds as written).

    Read from the reference pitch infer_pitch actually used rather than from the voice, so the label
    follows the clef whatever voice it is on. The octave has two owners: Stage 3's voice rule
    (get_clef_reference) without ClefKeyNet, and the decision's octave_shift with it (where the
    voice rule is off).
    """
    letter = clef.split(".", 1)[-1].split("-")[0]
    if letter not in OCTAVE_CLEF_LETTERS or clef not in CLEF_REFERENCE:
        return 0
    return max(0, (CLEF_REFERENCE[clef] - reference_pitch) // SEMITONES_PER_OCTAVE)


def _clef_name(clef: str, reference_pitch: int) -> str:
    """Short clef name as a singer reads it; an octave-lowered G or F clef is G8vb / F8vb."""
    body = clef.split(".", 1)[1] if "." in clef else clef
    letter = body.split("-")[0]
    if letter in OCTAVE_CLEF_LETTERS:
        return f"{letter}8vb" if _octaves_below(clef, reference_pitch) else letter
    return f"{body} (out of scope)"


def _pitch_label(midi: int, step: int, clef: str, reference_pitch: int) -> Tuple[str, int]:
    """Sounding ASPN name for a note, spelled from its staff letter.

    The letter comes from the staff step under the clef in effect, and the
    alteration is whatever infer_pitch actually added (key + inline
    accidental), read back as pitch - natural. Deriving it from the MIDI value
    means the label can never disagree with what is played; a BUG-024 stacked
    accidental shows up as a visible double flat/sharp. The octave is taken
    from the natural note, so Cb5 (MIDI 71) is not renamed B4.

    Returns (name, octave) -- the octave lets the caller add the written pitch.
    """
    bottom_letter = CLEF_BOTTOM_LETTER.get(clef, "E")
    natural = reference_pitch + _diatonic_delta(step, bottom_letter)
    letter = _pitch_class_at_step(step, bottom_letter)
    octave = natural // 12 - 1
    alter = midi - natural
    acc = ALTER_TEXT.get(alter, f"?{alter:+d}")
    return f"{letter}{acc}{octave}", octave


def _duration_label(ticks: int) -> str:
    """Duration name (+ one "." per augmentation dot) for an event's final tick length."""
    for n_dots in range(4):
        for name, base in NOTE_DURATION_TICKS.items():
            if _dotted_ticks(base, n_dots) == ticks:
                return DURATION_LABELS.get(name, name) + "." * n_dots
    return f"{ticks}t"


def _key_label(alterations: dict) -> str:
    n_sharp = sum(1 for v in alterations.values() if v > 0)
    n_flat = sum(1 for v in alterations.values() if v < 0)
    if n_sharp:
        notes = " ".join(f"{p}#" for p in SHARP_ORDER[:n_sharp])
        return f"key {n_sharp}#: {notes} ({MAJOR_BY_SHARPS[n_sharp]} maj / {MINOR_BY_SHARPS[n_sharp]} min)"
    if n_flat:
        notes = " ".join(f"{p}b" for p in FLAT_ORDER[:n_flat])
        return f"key {n_flat}b: {notes} ({MAJOR_BY_FLATS[n_flat]} maj / {MINOR_BY_FLATS[n_flat]} min)"
    return "key: none (C maj / A min)"


def _find_staff_lines(gray: np.ndarray) -> Optional[List[float]]:
    """Five staff-line row centres (top to bottom), or None if the strip does not show five evenly spaced lines.

    None is a real outcome (e.g. a tilted strip): the caller then draws
    staff-height boxes instead of inventing notehead positions.
    """
    ink = (gray < STAFF_LINE_INK_LEVEL).mean(axis=1)
    rows = np.where(ink >= STAFF_LINE_INK_FRACTION)[0]
    if len(rows) == 0:
        return None
    runs: List[List[int]] = [[int(rows[0])]]
    for r in rows[1:]:
        if r == runs[-1][-1] + 1:
            runs[-1].append(int(r))
        else:
            runs.append([int(r)])
    centres = [float(np.mean(run)) for run in runs]
    if len(centres) < N_STAFF_LINES:
        return None
    best: Optional[List[float]] = None
    best_spread = float("inf")
    for i in range(len(centres) - N_STAFF_LINES + 1):
        cand = centres[i:i + N_STAFF_LINES]
        gaps = np.diff(cand)
        if gaps.min() <= 0:
            continue
        spread = float(gaps.std() / gaps.mean())
        if spread < best_spread:
            best, best_spread = cand, spread
    # More than ~25% spacing variation means these are not one staff's lines.
    return best if best is not None and best_spread < 0.25 else None


def _token_role(symbols: List[str], idx: int, stage_before: str, entry: dict) -> str:
    """What token ``idx`` did in infer_pitch, from the stage before it and its trace entry.

    The accidental rules repeat infer_pitch's own predicates (_header_accidental_is_inline,
    _accidental_is_anchored) so a glyph that pitch inference dropped is never drawn as if it applied.
    """
    symbol, stage_after = symbols[idx], entry["stage"]
    if symbol.startswith("clef."):
        return "clef_ignored" if entry.get("clef_fixed") else "clef"
    if symbol.startswith("accidental."):
        if stage_after == "keysig" or entry.get("key_change_glyph"):
            return "keysig"
        if stage_before == "fixed_header":
            return "accidental" if _header_accidental_is_inline(symbols, idx) else "header_dropped"
        if stage_before in ("clef", "body", "post_bar"):
            return "accidental" if _accidental_is_anchored(symbols, idx) else "accidental_dropped"
        return "accidental"
    if symbol.startswith("metersign"):
        return "meter"
    if symbol.startswith("digit."):
        in_header = stage_before == stage_after and stage_after in ("keysig", "fixed_header")
        return "meter" if in_header else "digit"
    for prefix, role in (("note.", "note"), ("rest.", "rest"), ("multirest", "rest"),
                         ("barline", "barline"), ("dot", "dot"), ("slur.", "slur"),
                         ("gracenote.", "grace")):
        if symbol.startswith(prefix):
            return role
    return "other"


def build_strip_labels(
    symbols:     List[str],
    events:      List[dict],
    trace:       List[dict],
    voice:       str,
    confidences: Optional[List[float]] = None,
) -> List[dict]:
    """Groups tokens into labelled items: {kind, text, sub, token_indices, event_indices, step, confidence}.

    Consecutive key-signature accidentals become one "key" item and
    consecutive time-signature tokens one "meter" item, each labelled with the
    value infer_pitch COMMITTED (read from the first body-stage trace entry
    after the group), not with a per-glyph guess.
    """
    if len(trace) != len(symbols):
        raise ValueError(f"trace ({len(trace)}) must have one entry per symbol ({len(symbols)})")
    first_stage = "fixed_header" if trace and trace[0].get("clef_fixed") else "clef"
    roles = [_token_role(symbols, i, trace[i - 1]["stage"] if i else first_stage, trace[i])
             for i in range(len(symbols))]

    def committed_after(i: int) -> dict:
        for entry in trace[i + 1:]:
            if entry["stage"] == "body":
                return entry
        return trace[-1]

    def conf_of(idxs: List[int]) -> Optional[float]:
        return min(confidences[j] for j in idxs) if confidences is not None else None

    items: List[dict] = []
    i = 0
    while i < len(symbols):
        role, sym, entry = roles[i], symbols[i], trace[i]
        if role in ("keysig", "meter", "header_dropped"):
            j = i
            while j + 1 < len(symbols) and roles[j + 1] == role:
                j += 1
            idxs = list(range(i, j + 1))
            after = committed_after(j)
            if role == "keysig":
                text = _key_label(after["key_alterations"])
            elif role == "meter":
                text = f"time {after['time_signature']}"
            else:
                text = "CRNN key glyph(s) ignored"
            items.append(dict(kind=role, text=text, sub=None, token_indices=idxs, event_indices=[],
                              step=None, confidence=conf_of(idxs)))
            i = j + 1
            continue

        text, sub, step = sym, None, None
        ev_idx = entry["event_indices"]
        if role == "clef":
            name = (_clef_name(entry["active_clef"], entry["reference_pitch"]) if sym in CLEF_REFERENCE
                    else sym)
            text = f"clef {name}"
        elif role == "clef_ignored":
            text = f"CRNN {sym.split('.', 1)[1]} ignored"
        elif role == "note" and ev_idx:
            ev = events[ev_idx[0]]
            step = _staff_step(ev["symbol"].split("-", 1)[1])
            pname, octave = _pitch_label(ev["pitch"], step, entry["active_clef"], entry["reference_pitch"])
            text = f"{pname}_{_duration_label(ev['duration_ticks'])}"
            lowered = _octaves_below(entry["active_clef"], entry["reference_pitch"])
            if lowered:
                sub = f"(written {pname[:-len(str(octave))]}{octave + lowered})"
        elif role == "rest" and ev_idx:
            ev = events[ev_idx[0]]
            if ev["symbol"].startswith("multirest"):
                text = f"rest x{ev['duration_ticks'] // NOTE_DURATION_TICKS['whole']} bars"
            else:
                text = f"rest_{_duration_label(ev['duration_ticks'])}"
        elif role in ("accidental", "accidental_dropped"):
            text = {"accidental.sharp": "#", "accidental.flat": "b", "accidental.natural": "nat",
                    "accidental.doubleSharp": "##", "accidental.doubleFlat": "bb"}.get(sym.split("-")[0], sym)
            if role == "accidental_dropped":
                text += " dropped (not on next note)"
        elif role == "dot":
            text = "dot"
        elif role == "slur":
            text = "slur(" if sym.startswith("slur.start") else ")slur"
        elif role == "digit":
            text = f"{sym.split('.')[1].split('-')[0]} bars"
        elif role == "grace":
            text = "grace (not played)"
        elif role == "barline":
            text = ""
        items.append(dict(kind=role, text=text, sub=sub, token_indices=[i], event_indices=ev_idx,
                          step=step, confidence=conf_of([i])))
        i += 1
    return items


def _draw_dashed_rect(img: np.ndarray, p0: Tuple[int, int], p1: Tuple[int, int],
                      color: Tuple[int, int, int], dash: int = 6) -> None:
    (x0, y0), (x1, y1) = p0, p1
    for x in range(x0, x1, dash * 2):
        cv2.line(img, (x, y0), (min(x + dash, x1), y0), color, 2)
        cv2.line(img, (x, y1), (min(x + dash, x1), y1), color, 2)
    for y in range(y0, y1, dash * 2):
        cv2.line(img, (x0, y), (x0, min(y + dash, y1)), color, 2)
        cv2.line(img, (x1, y), (x1, min(y + dash, y1)), color, 2)


def visualize_strip(
    img:         np.ndarray,
    symbols:     list,
    voice:       str,
    page_index:  int,
    v_idx:       int,
    output_dir:  str,
    img_height:  int = 64,
    sys_idx:     int = 1,
    spans:       Optional[List[Tuple[float, float]]] = None,
    events:      Optional[List[dict]] = None,
    trace:       Optional[List[dict]] = None,
    confidences: Optional[List[float]] = None,
    clef_key_decision: Optional["StripDecision"] = None,
) -> str:
    """
    Saves one annotated image (+ a .json sidecar) for one strip and returns the PNG path.

    With clef_key_decision (the one infer_pitch_b used) the title names ClefKeyNet as the clef/key
    source; the CRNN's own clef and header key glyphs are then tagged "ignored", as in infer_pitch.

    Each token gets a box at its CTC-aligned x-range (spans, from
    transcribe_strip(spans_out=...)); notes are boxed on the staff step their
    pitch came from, if five staff lines are found. Without spans the tokens
    are spaced evenly, which does NOT show where they are -- the title says so.
    Without events/trace (infer_pitch(trace=...)) tokens are labelled with the
    raw symbol.

    The filename carries sys_idx: several systems share a page, and without
    it each system's image overwrote the previous one.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h, w = gray.shape
    s = VIZ_SCALE

    if events is not None and trace is not None:
        items = build_strip_labels(symbols, events, trace, voice, confidences)
    else:
        items = [dict(kind=_token_role(symbols, i, "body", {"stage": "body"}), text=t, sub=None,
                      token_indices=[i],
                      event_indices=[], step=None,
                      confidence=confidences[i] if confidences is not None else None)
                 for i, t in enumerate(symbols)]

    aligned = spans is not None and len(spans) == len(symbols)
    if not aligned:
        spans = [(i * w / max(len(symbols), 1), (i + 1) * w / max(len(symbols), 1))
                 for i in range(len(symbols))]

    lines = _find_staff_lines(gray)
    spacing = float(np.mean(np.diff(lines))) if lines else h / 8
    staff_top = lines[0] - spacing / 2 if lines else 0.0
    staff_bot = lines[-1] + spacing / 2 if lines else float(h - 1)

    band = VIZ_LANE_HEIGHT * VIZ_LANES_PER_SIDE
    top_off = VIZ_HEADER_HEIGHT + band
    raw_lines = _wrap_tokens(symbols, max_chars=max(40, (w * s) // 7))
    canvas_h = top_off + h * s + band + VIZ_CAPTION_LINE * (3 + len(raw_lines))
    canvas = np.full((canvas_h, w * s, 3), 255, np.uint8)
    canvas[top_off:top_off + h * s] = cv2.cvtColor(
        cv2.resize(gray, (w * s, h * s), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)

    # Staff label with the clef in effect at the start of the strip.
    if clef_key_decision is not None:
        d = clef_key_decision
        key_text = _key_label(get_key_sig_alterations(*_signed_key_counts(d.key)))
        clef_name = _clef_name(d.clef.token, CLEF_REFERENCE[d.clef.token] + d.clef.octave_shift)
        clef_desc = f"{clef_name} (ClefKeyNet: {d.clef.source}; {key_text}, {d.key_source})"
        strip_flags = sorted(set(d.flags) | set(d.clef.flags))
        if strip_flags:
            clef_desc += f"  flags: {', '.join(strip_flags)}"
    else:
        first = next((e for e in (trace or []) if e["symbol"].startswith("clef.")), None)
        if first is None:
            fb = CLEF_FALLBACK[voice]
            clef_desc = f"{_clef_name(fb, get_clef_reference(fb, voice))} (fallback: no clef decoded)"
        else:
            clef_desc = _clef_name(first["active_clef"], first["reference_pitch"])
        clef_desc += " (CRNN clef/key, no ClefKeyNet)"
    title = (f"{voice}, {clef_desc}  |  page {page_index}, system {sys_idx}, vidx{v_idx}  |  "
             f"{len(symbols)} tokens -> {len(events or [])} events  |  "
             + ("boxes: CTC frame alignment (approximate, not detections)" if aligned
                else "NO ALIGNMENT: tokens evenly spaced, positions are not real"))
    if not lines:
        title += "  |  staff lines not found: staff-height boxes"
    cv2.putText(canvas, title, (6, 20), VIZ_FONT, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)

    lanes: dict = {"above": [[] for _ in range(VIZ_LANES_PER_SIDE)],
                   "below": [[] for _ in range(VIZ_LANES_PER_SIDE)]}

    def place(x0: int, x1: int, prefer: str) -> Tuple[str, int]:
        for side in (prefer, "below" if prefer == "above" else "above"):
            for lane, used in enumerate(lanes[side]):
                if all(x1 + 4 < a or x0 > b + 4 for a, b in used):
                    used.append((x0, x1))
                    return side, lane
        lanes[prefer][-1].append((x0, x1))
        return prefer, VIZ_LANES_PER_SIDE - 1

    sidecar: List[dict] = []
    n_tagged = 0
    for item in items:
        idxs = item["token_indices"]
        x0 = min(spans[j][0] for j in idxs)
        x1 = max(spans[j][1] for j in idxs)
        cx = (x0 + x1) / 2
        half_w = max((x1 - x0) / 2, VIZ_MIN_BOX_WIDTH * spacing / 2)
        bx0, bx1 = max(0.0, cx - half_w), min(float(w - 1), cx + half_w)
        if item["step"] is not None and lines:
            cy = lines[-1] - item["step"] * spacing / 2
            by0, by1 = cy - VIZ_HEAD_HALF_HEIGHT * spacing, cy + VIZ_HEAD_HALF_HEIGHT * spacing
        else:
            by0, by1 = staff_top, staff_bot
        conf = item["confidence"]
        low = conf is not None and conf < VIZ_LOW_CONFIDENCE
        color = COLOR_BOX_LOW if low else COLOR_BOX
        p0 = (int(bx0 * s), int(top_off + by0 * s))
        p1 = (int(bx1 * s), int(top_off + by1 * s))
        sidecar.append(dict(item, symbols=[symbols[j] for j in idxs],
                            box_px=[round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
                            low_confidence=low))

        if item["kind"] == "barline":
            xm = int(cx * s)
            cv2.line(canvas, (xm, int(top_off + staff_top * s)), (xm, int(top_off + staff_bot * s)),
                     COLOR_BARLINE, 1)
            continue
        if low:
            _draw_dashed_rect(canvas, p0, p1, color)
        else:
            cv2.rectangle(canvas, p0, p1, color, 2)

        minor = item["kind"] in ("dot", "slur", "accidental", "accidental_dropped", "digit", "grace", "other",
                                 "clef_ignored", "header_dropped")
        scale = VIZ_SMALL_FONT_SCALE if minor else VIZ_TAG_FONT_SCALE
        text = item["text"] + (f" {item['sub']}" if item["sub"] else "")
        (tw, th), _ = cv2.getTextSize(text, VIZ_FONT, scale, 1)
        tx0 = int(min(max(0, cx * s - tw / 2), w * s - tw - 2 * VIZ_TAG_PAD))
        side, lane = place(tx0, tx0 + tw + 2 * VIZ_TAG_PAD, "above" if n_tagged % 2 == 0 else "below")
        n_tagged += 1
        if side == "above":
            ty1 = top_off - lane * VIZ_LANE_HEIGHT - 3
            anchor_y = p0[1]
        else:
            ty1 = top_off + h * s + (lane + 1) * VIZ_LANE_HEIGHT - 3
            anchor_y = p1[1]
        ty0 = ty1 - th - 2 * VIZ_TAG_PAD
        cv2.line(canvas, (int(cx * s), anchor_y), (int(cx * s), ty1 if side == "above" else ty0),
                 color, 1)
        cv2.rectangle(canvas, (tx0, ty0), (tx0 + tw + 2 * VIZ_TAG_PAD, ty1),
                      COLOR_MINOR_BG if minor else COLOR_TAG_BG, -1)
        cv2.putText(canvas, text, (tx0 + VIZ_TAG_PAD, ty1 - VIZ_TAG_PAD), VIZ_FONT, scale,
                    COLOR_TAG_FG, 1, cv2.LINE_AA)

    y = top_off + h * s + band + VIZ_CAPTION_LINE
    captions = [VIZ_CAPTION,
                f"Orange dashed box = CRNN confidence < {VIZ_LOW_CONFIDENCE:.2f}; high confidence is not "
                f"correctness (BUG-011).  Raw CRNN tokens:"]
    for line in captions + raw_lines:
        cv2.putText(canvas, line, (6, y), VIZ_FONT, VIZ_SMALL_FONT_SCALE, COLOR_TEXT, 1, cv2.LINE_AA)
        y += VIZ_CAPTION_LINE

    os.makedirs(output_dir, exist_ok=True)
    stem = f"{voice}_p{page_index:03d}_s{sys_idx:02d}_vidx{v_idx}"
    png = os.path.join(output_dir, stem + ".png")
    cv2.imwrite(png, canvas)
    with open(os.path.join(output_dir, stem + ".json"), "w", encoding="utf-8") as f:
        json.dump(dict(voice=voice, page_index=page_index, sys_idx=sys_idx, v_idx=v_idx, clef=clef_desc,
                       aligned=aligned, staff_lines_px=lines, items=sidecar), f, indent=1)
    print(f"  [Viz] Saved -> {stem}.png")
    return png


def _wrap_tokens(symbols: List[str], max_chars: int) -> List[str]:
    lines, cur = [], ""
    for t in symbols:
        if cur and len(cur) + len(t) + 1 > max_chars:
            lines.append(cur)
            cur = ""
        cur = f"{cur} {t}" if cur else t
    return lines + ([cur] if cur else [])
 
 
CLEF_KEY_DISABLED_FLAG = "clef_key_disabled"  # event flag when Stage 3 runs without ClefKeyNet


# ── Full pipeline for one strip ───────────────────────────────────────────────
 
def process_strip(
    strip:      np.ndarray,
    voice:      str,
    page_index: int,
    model:      CRNN,
    device:     torch.device,
    img_height: int = 64,
    v_idx:      int = 0,
    viz_dir:    Optional[str] = None,
    sys_idx:    int = 1,
    strip_id:   str = "",
    clef_key_decision: Optional["StripDecision"] = None,
) -> list:

    """Transcribes one strip and returns pitch-assigned events for Stage 4.

    clef_key_decision: a stage3_clefkey.StripDecision; when given, clef/key/octave come from ClefKeyNet
    (version b) and every event carries ``review_needed`` / ``clef_key_flags``.
    """
    # Spans and trace are only side-outputs for the visualization; the tokens
    # and events are the same with or without them.
    spans: Optional[List[Tuple[float, float]]] = [] if viz_dir else None
    trace: Optional[list] = [] if viz_dir else None
    scored  = transcribe_strip(strip, model, device, img_height,
                               return_confidence=True, strip_id=strip_id,
                               spans_out=spans)
    symbols = [s for s, _ in scored]
    confs   = [c for _, c in scored]
    if clef_key_decision is not None:
        import stage3_clefkey  # lazy: stage3_clefkey imports this module
        events, _, _ = stage3_clefkey.infer_pitch_b(symbols, confs, voice, page_index, sys_idx,
                                                    clef_key_decision, trace=trace)
    else:
        events = infer_pitch(symbols, voice=voice, page_index=page_index,
                             sys_idx=sys_idx, confidences=confs, trace=trace)

    print(f"[Stage 3] {voice} p{page_index}: "
          f"{len(symbols)} symbols -> {len(events)} events")

    if viz_dir and symbols:
        visualize_strip(strip, symbols, voice, page_index, v_idx, viz_dir, img_height,
                        sys_idx=sys_idx, spans=spans, events=events, trace=trace,
                        confidences=confs, clef_key_decision=clef_key_decision)
 
    return events
 
 
# ── Batch processing (Stage 2 → Stage 3) ─────────────────────────────────────
 
def transcribe_voice_sequences(
    voice_sequences: dict,
    model_weights:   str = r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt",
    img_height:      int = 64,
    viz_dir:         Optional[str] = None,
    events_dir:      str = r"D:\PiyaNota (Code)\data\transcribed_symbols",   # ← add this
    clef_key_decisions: Optional[dict[str, "StripDecision"]] = None,
) -> dict:
    """
    Processes all voice strips from Stage 2 and returns event sequences.
 
    Args:
        voice_sequences: Output of Stage 2 detect_staff_regions().
          Format: {voice: [(strip, page_index, sys_idx, voice, v_idx), ...]}
          sys_idx is the 1-based system number within the page (Stage 2's
          `enumerate(systems, start=1)`) -- required in the event schema so
          that events from different systems on the same page never alias
          against each other on (page_index, measure_index) or
          (page_index, tick_onset).
        model_weights:   Path to weights file trained on Kaggle.
        img_height:      Must match the height used during Kaggle training.
        viz_dir:         Debug-only directory for per-strip visualizations; None (the default,
          and the backend path) renders nothing. Opt-in rather than on-by-default because the
          render costs time per strip and its internal checks raise, which must fail an eval run
          loudly but must never abort a user's conversion (ml-cv-lead, 2026-09-30).
        clef_key_decisions: {strip_id: stage3_clefkey.StripDecision} from
          ``stage3_clefkey.decisions_for_pages``; None runs version (a) (CRNN clef/key), and every
          event is then flagged ``clef_key_disabled`` / ``review_needed`` (the CRNN clef collapses on
          real scores, BUG-011).

    Raises:
        ValueError: clef_key_decisions is given but lacks a strip.

    Returns:
        {voice: [event_dict, ...]} sorted by page_index, then sys_idx, then
        tick_onset.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[Stage 3] Using device: {device}")
    if viz_dir:
        print(f"[Stage 3] viz ON -> {os.path.abspath(viz_dir)} (debug only; not for production)")
 
    model = CRNN(VOCAB_SIZE).to(device)
    checkpoint = torch.load(model_weights, map_location=device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    print(f"[Stage 3] Loaded weights -> {model_weights} "
          f"(epoch {checkpoint.get('epoch', '?')})")
 
    results = {}
    for voice, strips in voice_sequences.items():
        all_events = []
        for strip, page_index, sys_idx, voice_label, v_idx in strips:
            strip_id = f"page{page_index:03d}_sys{sys_idx:02d}_{voice_label}_vidx{v_idx}"
            decision = None
            if clef_key_decisions is not None:
                if strip_id not in clef_key_decisions:
                    raise ValueError(f"no clef/key decision for {strip_id} (Stage 2 manifest out of sync)")
                decision = clef_key_decisions[strip_id]
            events = process_strip(strip, voice_label, page_index,
                    model, device, img_height,
                    v_idx=v_idx,
                    viz_dir=viz_dir,
                    sys_idx=sys_idx,
                    strip_id=strip_id,
                    clef_key_decision=decision)
            if decision is None:
                for e in events:
                    e["clef_key_flags"] = [CLEF_KEY_DISABLED_FLAG, "review_needed"]
                    e["review_needed"] = True
            all_events.extend(events)
        all_events.sort(key=lambda e: (e["page_index"], e["sys_idx"], e["tick_onset"]))
        results[voice] = all_events
        print(f"[Stage 3] {voice}: {len(all_events)} total events")
    
    # ── Save per-voice event JSON files ───────────────────────────────────
    if events_dir:
        os.makedirs(events_dir, exist_ok=True)
        for voice, events in results.items():
            path = os.path.join(events_dir, f"{voice.lower()}_events.json")
            with open(path, "w") as f:
                json.dump(events, f, indent=2)
            print(f"[Stage 3] Events saved -> {path}")
 
    _report(results)
    return results
 
 
# ── Symbol Error Rate ─────────────────────────────────────────────────────────
 
def compute_ser(predicted: list, ground_truth: list) -> float:
    """SER = (S + D + I) / N using dynamic programming edit distance."""
    n = len(ground_truth)
    if n == 0:
        return 0.0
    m = len(predicted)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): dp[i][0] = i
    for j in range(m + 1): dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ground_truth[i-1] == predicted[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    return dp[n][m] / n
 
 
# ── Helpers ───────────────────────────────────────────────────────────────────
 
def load_model(model_weights: str,
               device: Optional[torch.device] = None) -> tuple:
    """Loads CRNN weights and returns (model, device)."""
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CRNN(VOCAB_SIZE).to(device)
    ckpt  = torch.load(model_weights, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return model, device
 
 
def _report(results: dict):
    print("\n[Stage 3] Event counts per voice:")
    for voice, events in results.items():
        notes = sum(1 for e in events if e["type"] == "note")
        rests = sum(1 for e in events if e["type"] == "rest")
        print(f"  {voice}: {len(events)} events ({notes} notes, {rests} rests)")
 
 
# ── Stages 1-3 runner (shared by the Stage 3/4/5 CLIs and run_full_pipeline) ──

def run_stages_1_to_3(
    input_dir:        str,
    prep_dir:         str,
    strips_dir:       str,
    yolo_weights:     str,
    crnn_weights:     str,
    clef_key_weights: Optional[str],
    img_height:       int = 64,
    **transcribe_kwargs: Any,
) -> dict:
    """Preprocesses, detects and transcribes a folder of score photos.

    Args:
        input_dir: raw score photos.
        prep_dir: Stage 1 output folder.
        strips_dir: Stage 2 output folder (also holds the strip manifest ClefKeyNet reads).
        yolo_weights: Stage 2 staff detector.
        crnn_weights: Stage 3 CRNN checkpoint.
        clef_key_weights: ClefKeyNet checkpoint; None opts out (version a, CRNN clef/key).
        img_height: CRNN input height.
        **transcribe_kwargs: passed on to ``transcribe_voice_sequences`` (viz_dir, events_dir).

    Returns:
        {voice: [event_dict, ...]} as ``transcribe_voice_sequences``.

    Raises:
        FileNotFoundError / ValueError: from ``stage3_clefkey.check_clef_key_weights``.
    """
    from stage1_preprocessing import preprocess_batch
    from stage2_detection import detect_staff_regions
    import stage3_clefkey

    ck_path = stage3_clefkey.check_clef_key_weights(clef_key_weights)
    use_ck  = ck_path is not None
    pages   = preprocess_batch(input_dir, prep_dir, save_debug=False, keep_unmasked=use_ck)
    manifest_path = str(Path(strips_dir) / stage3_clefkey.DEFAULT_PIPELINE_MANIFEST)
    voices  = detect_staff_regions(pages, model_weights=yolo_weights, output_dir=strips_dir,
                                   manifest_path=manifest_path)
    decisions = None
    if use_ck:
        ckm = stage3_clefkey.load_clef_key_model(ck_path)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        decisions, _ = stage3_clefkey.decisions_for_pages(pages, manifest, ckm)
        n_review = sum(d.review_needed for d in decisions.values())
        print(f"[Stage 3] ClefKeyNet: {len(decisions)} strip decision(s), {n_review} flagged review_needed")
    return transcribe_voice_sequences(voices, model_weights=crnn_weights, img_height=img_height,
                                      clef_key_decisions=decisions, **transcribe_kwargs)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    # Run as a script this module is __main__; register it under its import name so stage3_clefkey's
    # "import stage3_transcription" reuses it instead of executing it a second time.
    sys.modules.setdefault("stage3_transcription", sys.modules[__name__])
    import stage3_clefkey
 
    parser = argparse.ArgumentParser(
        description="PiyaNota Stage 3 — CRNN-CTC Transcription (inference only)")
    parser.add_argument("--weights",    default=r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt",
                        help="CRNN weights trained on Kaggle")
    parser.add_argument("--input",      default="data/raw")
    parser.add_argument("--prep",       default="data/preprocessed")
    parser.add_argument("--strips",     default="data/strips")
    parser.add_argument("--yolo",       default="staff_detector_files/weights/best.pt")
    parser.add_argument("--img-height", type=int, default=64,
                        help="Must match Kaggle training height")
    parser.add_argument("--viz-dir", default=None,
                    help="Opt-in debug dir for Stage 3 strip visualizations (off by default; not for production)")
    parser.add_argument("--events-dir",
                    default=r"D:\PiyaNota (Code)\data\transcribed_symbols",
                    help="Directory to save per-voice pitch event JSONs")
    stage3_clefkey.add_clef_key_args(parser)
    args = parser.parse_args()

    events = run_stages_1_to_3(args.input, args.prep, args.strips, args.yolo, args.weights,
                               stage3_clefkey.clef_key_arg(args), img_height=args.img_height,
                               viz_dir=args.viz_dir, events_dir=args.events_dir)
    print("\nStage 3 complete. Events ready for Stage 4 (SATB reconstruction).")
 