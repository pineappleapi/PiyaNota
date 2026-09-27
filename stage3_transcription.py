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
 
7.  KEY_SIG_POSITIONS  (new table)
      • Conventional staff-position suffixes (e.g. "L5", "S3") at which
        key-signature accidentals appear for each clef.
      • Used by _is_keysig_position() to distinguish key-sig accidentals
        from inline accidentals after a barline.
 
8.  _is_keysig_position()  (new helper)
      • Returns True if an accidental token is at a known key-sig position
        for the active clef.
 
9.  infer_pitch()  — full rewrite
      • Replaced the two-pass linear scan + boolean flag with a 5-stage
        key-signature state machine:
          "clef"        wait for opening clef; handle dropped-clef recovery
          "keysig"      count opening key-sig accidentals safely
          "body"        normal note / rest processing
          "post_bar"    watch symbol after every barline for key changes
          "mid_keysig"  accumulate mid-piece key-sig bursts
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
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from typing import List, Optional, Tuple, Union
import json

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
# Conventional staff-position suffixes at which key-signature accidentals
# appear for each clef.  Used by _is_keysig_position() to distinguish a
# key-change accidental (after a barline) from a plain inline accidental.
#
# Treble clef sharps (engraving order): F5 C5 G5 D5 A4 E5 B4
#   → suffixes: L5 S3 L6 S4 L5 S3 L5  → unique set: {L5, S3, L6, S4}
# Treble clef flats:  Bb4 Eb5 Ab4 Db5 Gb4 Cb5 Fb4
#   → suffixes: S4 S2 S5 S3 S6 S4 S2  → unique set: {S4, S2, S5, S3, S6}
#
# NOTE: Verify these against your CameraPrIMuS training corpus — the exact
# suffix values depend on how the dataset was engraved. Inspect strips in a
# known key and check which tokens appear between the clef and the meter sign.
 
KEY_SIG_POSITIONS = {
    "clef.G-L2": {
        "accidental.sharp": {"L5", "S3", "L6", "S4"},
        "accidental.flat":  {"S4", "S2", "S5", "S3", "S6"},
    },
    "clef.G-L1": {
        "accidental.sharp": {"L5", "S3", "L6", "S4"},
        "accidental.flat":  {"S4", "S2", "S5", "S3", "S6"},
    },
    "clef.F-L4": {
        "accidental.sharp": {"L4", "S2", "L5", "S3"},
        "accidental.flat":  {"S3", "S1", "S4", "S2", "S5"},
    },
    "clef.F-L3": {
        "accidental.sharp": {"L4", "S2", "L5", "S3"},
        "accidental.flat":  {"S3", "S1", "S4", "S2", "S5"},
    },
    # C clefs are rare in SATB choral — positions approximated from standard
    # engraving. Verify before relying on mid-piece key changes for these.
    "clef.C-L1": {
        "accidental.sharp": {"L5", "S3", "L6", "S4"},
        "accidental.flat":  {"S4", "S2", "S5", "S3", "S6"},
    },
    "clef.C-L2": {
        "accidental.sharp": {"L4", "S2", "L5", "S3"},
        "accidental.flat":  {"S3", "S1", "S4", "S2"},
    },
    "clef.C-L3": {
        "accidental.sharp": {"L4", "S2", "L5", "S3"},
        "accidental.flat":  {"S3", "S1", "S4", "S2"},
    },
    "clef.C-L4": {
        "accidental.sharp": {"L3", "S1", "L4", "S2"},
        "accidental.flat":  {"S2", "L1", "S3", "S1"},
    },
}
 
 
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
    if "-" not in sym:
        return False
    suffix   = sym.split("-", 1)[1]             # "L5", "S3", etc.
    clef_map = KEY_SIG_POSITIONS.get(active_clef, {})
    valid    = clef_map.get(acc_type, set())
    return suffix in valid
 
 
# ── Pitch inference ────────────────────────────────────────────────────────────
 
def infer_pitch(
    symbols:    list,
    voice:      str = "Soprano",
    page_index: int = 1,
    sys_idx:    int = 1,
    confidences: Optional[list] = None,
) -> list:
    """
    Converts a CRNN symbol sequence into note events with MIDI pitch.

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

    Pitch formula:  M = R_c + Δ(p) + K + A
      R_c   clef reference pitch at bottom line (voice-aware via get_clef_reference)
      Δ(p)  diatonic semitone offset for staff step p
      K     key-signature alteration for this pitch class (0 if natural cancels)
      A     inline accidental offset
 
    Key-signature state machine
    ───────────────────────────
    "clef"
      Waiting for the opening clef symbol.
      • clef found                               → update active_clef /
                                                   reference_pitch, → "keysig"
      • accidental at valid key-sig position
        (clef dropped by CRNN)                   → infer clef was missed,
                                                   start counting, → "keysig"
      • accidental at wrong position             → inline pending_acc, → "body"
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
      • accidental at valid key-sig position     → start burst, → "mid_keysig"
      • accidental at wrong position             → inline, → "body"
      • clef change                              → update reference, stay
      • anything else                            → → "body", fall-through
 
    "mid_keysig"
      Accumulating a mid-piece key-sig burst.
      • accidental, same type, valid position    → count++
      • accidental, valid position, wrong type   → mixed → discard burst,
                                                   treat as inline, → "body"
      • accidental at wrong position             → commit burst, treat this
                                                   one as inline, → "body"
      • any non-accidental                       → commit burst (single
                                                   accidental OK: G major = 1#),
                                                   fall-through to body
    """
 
    # ── Initialise ────────────────────────────────────────────────────────
    active_clef     = CLEF_FALLBACK[voice]
    reference_pitch = get_clef_reference(active_clef, voice)
 
    pending_acc            = None
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
    mid_sharp       = 0
    mid_flat        = 0
    key_alterations = {}
    # PIYA-107 AC4/AC6: Camera-PrIMuS encodes a numeric time signature (e.g.
    # "3/4") as two consecutive digit.N tokens in the header, rather than a
    # metersign.* token -- confirmed against ground truth: 1586/3996 (40%) of
    # corpus samples carry no metersign token at all and rely solely on this
    # digit-pair form. Only the first two header digit tokens are the time
    # signature (numerator, then denominator); any further digit tokens
    # before the first note/rest are unrelated noise and are ignored, same
    # as prior (pre-PIYA-107) behaviour.
    meter_digits = []
 
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
 
    def _commit_mid(n_sharp, n_flat):
        if n_sharp > 0 and n_flat > 0:
            print(f"[Stage 3] {voice} p{page_index}: "
                  "mixed accidentals in mid-piece key sig — keeping previous key")
            return None          # None = don't update key_alterations
        alts = get_key_sig_alterations(n_sharp, n_flat)
        desc = (f"{n_sharp}#" if n_sharp else (f"{n_flat}b" if n_flat else "C major"))
        print(f"[Stage 3] {voice} p{page_index}: mid-piece key change {desc} -> {alts}")
        return alts
 
    if confidences is not None and len(confidences) != len(symbols):
        raise ValueError(
            f"confidences ({len(confidences)}) must be parallel to "
            f"symbols ({len(symbols)})")
    with_conf = confidences is not None
    # Confidence of the most recent accidental token. Any accidental that
    # ends up in pending_acc is necessarily the latest accidental seen (each
    # one overwrites it), so tracking it here, once, covers every branch of
    # the state machine that sets pending_acc.
    last_acc_conf = 1.0

    # ── Main loop ─────────────────────────────────────────────────────────
    for tok_idx, sym in enumerate(symbols):

        tok_conf = float(confidences[tok_idx]) if with_conf else 1.0
        acc_type = sym.split("-")[0]
        is_sharp = sym.startswith("accidental.sharp")
        is_flat  = sym.startswith("accidental.flat")
        is_acc   = sym.startswith("accidental.")
        if is_acc:
            last_acc_conf = tok_conf

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
                    pending_acc = ACCIDENTAL_OFFSET.get(acc_type, 0)
                    ks_stage    = "body"
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
 
            if is_sharp or is_flat:
                if _is_keysig_position(sym, acc_type, active_clef):
                    mid_sharp = 1 if is_sharp else 0
                    mid_flat  = 1 if is_flat  else 0
                    ks_stage  = "mid_keysig"
                else:
                    pending_acc = ACCIDENTAL_OFFSET.get(acc_type, 0)
                    ks_stage    = "body"
                continue
 
            elif sym.startswith("clef."):
                if sym in CLEF_REFERENCE:
                    active_clef     = sym
                    reference_pitch = get_clef_reference(sym, voice)
                # Stay in "post_bar" — key sig accidentals may still follow
                continue
 
            else:
                ks_stage = "body"
                # fall through to body processing below
 
        # ── "mid_keysig" ─────────────────────────────────────────────────
        elif ks_stage == "mid_keysig":
 
            if (is_sharp and mid_flat == 0) or (is_flat and mid_sharp == 0):
                if _is_keysig_position(sym, acc_type, active_clef):
                    if is_sharp:
                        mid_sharp += 1
                    else:
                        mid_flat += 1
                else:
                    # Position mismatch mid-burst: commit what we have
                    new_alts = _commit_mid(mid_sharp, mid_flat)
                    if new_alts is not None:
                        key_alterations = new_alts
                    pending_acc = ACCIDENTAL_OFFSET.get(acc_type, 0)
                    mid_sharp = mid_flat = 0
                    ks_stage  = "body"
                continue
 
            elif is_sharp or is_flat:
                # Mixed type mid-burst — discard whole burst
                print(f"[Stage 3] {voice} p{page_index}: "
                      "mixed types in mid-piece key sig burst — discarding as noise")
                pending_acc = ACCIDENTAL_OFFSET.get(acc_type, 0)
                mid_sharp = mid_flat = 0
                ks_stage  = "body"
                continue
 
            else:
                # Burst ended — commit (single accidental is valid: G maj = 1#)
                new_alts = _commit_mid(mid_sharp, mid_flat)
                if new_alts is not None:
                    key_alterations = new_alts
                mid_sharp = mid_flat = 0
                ks_stage  = "body"
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
            if sym in CLEF_REFERENCE:
                active_clef     = sym
                reference_pitch = get_clef_reference(sym, voice)
            continue
 
        # ── Inline accidental ─────────────────────────────────────────────
        if is_acc:
            pending_acc = ACCIDENTAL_OFFSET.get(acc_type, 0)
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
            loc  = pos_str[0]                        # "L" or "S"
            pos  = int(pos_str[1:])                  # integer, may be negative
            step = (pos - 1) * 2 if loc == "L" else (pos - 1) * 2 + 1
 
            bottom_letter = CLEF_BOTTOM_LETTER.get(active_clef, "E")
            delta         = _diatonic_delta(step, bottom_letter)
 
            # Accidental: natural cancels key sig for this note only
            cancel_key = False
            acc        = 0
            note_conf  = tok_conf
            if pending_acc is not None:
                note_conf = min(note_conf, last_acc_conf)
                if pending_acc == 0:     # natural sign
                    cancel_key = True
                else:
                    acc = pending_acc
            pending_acc = None
 
            pitch_class = _pitch_class_at_step(step, bottom_letter)
            key_acc     = 0 if cancel_key else key_alterations.get(pitch_class, 0)
 
            midi_pitch  = max(0, min(127,
                reference_pitch + delta + key_acc + acc))
 
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
            in_chord    = False
            ks_stage    = "post_bar"
            mid_sharp   = 0
            mid_flat    = 0
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

    Returns:
        (decoded_indices, confidences) -- parallel lists; confidences[i]
        is the mean max-softmax-probability for decoded_indices[i].
    """
    probs = log_probs.exp()  # log-softmax -> softmax probabilities
    max_probs, indices = probs.max(dim=1)
    indices = indices.tolist()
    max_probs = max_probs.tolist()

    decoded, confidences = [], []
    for idx, group in itertools.groupby(zip(indices, max_probs), key=lambda pair: pair[0]):
        if idx == BLANK_IDX:
            continue
        group_probs = [p for _, p in group]
        decoded.append(idx)
        confidences.append(sum(group_probs) / len(group_probs))
    return decoded, confidences
 
 
def transcribe_strip(
    image:             np.ndarray,
    model:             CRNN,
    device:            torch.device,
    img_height:        int = 64,
    return_confidence: bool = False,
    strip_id:          str = "",
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

    if return_confidence:
        indices, confidences = _greedy_ctc_decode_with_confidence(log_probs)
        tokens = [(IDX_TO_SYM.get(i, "<unk>"), c) for i, c in zip(indices, confidences)]
        logger.info("transcribe_strip strip_id=%s raw_tokens=%s", strip_id, [t for t, _ in tokens])
        return tokens

    indices = _greedy_ctc_decode(log_probs)
    tokens = [IDX_TO_SYM.get(i, "<unk>") for i in indices]
    logger.info("transcribe_strip strip_id=%s raw_tokens=%s", strip_id, tokens)
    return tokens
 
 
# ── Visualization ─────────────────────────────────────────────────────────────
 
COLOR_MAP = {
    "note":       "#2196F3",
    "rest":       "#FF9800",
    "clef":       "#9C27B0",
    "accidental": "#F44336",
    "barline":    "#222222",
    "dot":        "#4CAF50",
    "digit":      "#795548",
    "metersign":  "#00BCD4",
    "slur":       "#E91E63",
    "gracenote":  "#8BC34A",
    "multirest":  "#FF5722",
}
 
 
def visualize_strip(
    img:         np.ndarray,
    symbols:     list,
    voice:       str,
    page_index:  int,
    v_idx:       int,
    output_dir:  str,
    img_height:  int = 64,
) -> None:
    """
    Saves a visualization of the detected symbol sequence for one strip.
    Top panel: strip image with symbol labels overlaid.
    Bottom panel: symbol sequence color-coded by type.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h, w = gray.shape
 
    fig_w = max(14, len(symbols) * 0.45)
    fig, (ax_img, ax_sym) = plt.subplots(
        2, 1, figsize=(fig_w, 4),
        gridspec_kw={"height_ratios": [3, 1]}
    )
 
    ax_img.imshow(gray, cmap="gray", aspect="auto")
    ax_img.set_title(
        f"{voice}  |  Page {page_index}  |  vidx{v_idx}  |  {len(symbols)} symbols",
        fontsize=9, fontweight="bold"
    )
    ax_img.axis("off")
 
    for i, sym in enumerate(symbols):
        x_pos  = (i + 0.5) * w / max(len(symbols), 1)
        prefix = sym.split(".")[0]
        color  = COLOR_MAP.get(prefix, "#555555")
        ax_img.text(
            x_pos, h * 0.02, sym,
            fontsize=4.5, color=color, ha="center", va="top",
            rotation=90,
            bbox=dict(boxstyle="round,pad=0.1", fc="white", alpha=0.65, ec="none")
        )
 
    ax_sym.axis("off")
    x, y = 0.0, 0.95
    for sym in symbols:
        prefix = sym.split(".")[0]
        color  = COLOR_MAP.get(prefix, "#555555")
        short  = sym[:20] + "…" if len(sym) > 20 else sym
        ax_sym.text(
            x, y, short + "  ",
            fontsize=5, color=color,
            ha="left", va="top",
            transform=ax_sym.transAxes,
            fontfamily="monospace"
        )
        x += len(short) * 0.012
        if x > 0.95:
            x = 0.0
            y -= 0.28
 
    legend_patches = [
        mpatches.Patch(color=c, label=k)
        for k, c in COLOR_MAP.items()
    ]
    ax_sym.legend(
        handles=legend_patches, loc="lower right",
        fontsize=5, ncol=4, framealpha=0.5
    )
 
    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    fname = f"{voice}_p{page_index:03d}_vidx{v_idx}.png"
    plt.savefig(os.path.join(output_dir, fname), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [Viz] Saved -> {fname}")
 
 
# ── Full pipeline for one strip ───────────────────────────────────────────────
 
def process_strip(
    strip:      np.ndarray,
    voice:      str,
    page_index: int,
    model:      CRNN,
    device:     torch.device,
    img_height: int = 64,
    v_idx:      int = 0,
    viz_dir:    str = None,
    sys_idx:    int = 1,
    strip_id:   str = "",
) -> list:

    """Transcribes one strip and returns pitch-assigned events for Stage 4."""
    scored  = transcribe_strip(strip, model, device, img_height,
                               return_confidence=True, strip_id=strip_id)
    symbols = [s for s, _ in scored]
    events  = infer_pitch(symbols, voice=voice, page_index=page_index,
                          sys_idx=sys_idx,
                          confidences=[c for _, c in scored])

    print(f"[Stage 3] {voice} p{page_index}: "
          f"{len(symbols)} symbols -> {len(events)} events")
 
    if viz_dir and symbols:
        visualize_strip(strip, symbols, voice, page_index, v_idx, viz_dir, img_height)
 
    return events
 
 
# ── Batch processing (Stage 2 → Stage 3) ─────────────────────────────────────
 
def transcribe_voice_sequences(
    voice_sequences: dict,
    model_weights:   str = r"D:\PiyaNota (Code)\music_symbol_detection\crnn_cameraprimus_transcription.pt",
    img_height:      int = 64,
    viz_dir:         str = r"D:\PiyaNota (Code)\data\symbol_detection_viz",
    events_dir:      str = r"D:\PiyaNota (Code)\data\transcribed_symbols",   # ← add this
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

    Returns:
        {voice: [event_dict, ...]} sorted by page_index, then sys_idx, then
        tick_onset.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[Stage 3] Using device: {device}")
 
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
            events = process_strip(strip, voice_label, page_index,
                    model, device, img_height,
                    v_idx=v_idx,
                    viz_dir=viz_dir,
                    sys_idx=sys_idx,
                    strip_id=strip_id)
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
 
 
# ── CLI entry point ───────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    import argparse
    from stage2_detection import detect_staff_regions
    from stage1_preprocessing import preprocess_batch
 
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
    parser.add_argument("--viz-dir",
                    default=r"D:\PiyaNota (Code)\data\symbol_detection_viz",
                    help="Directory to save symbol visualizations")
    parser.add_argument("--events-dir",
                    default=r"D:\PiyaNota (Code)\data\transcribed_symbols",
                    help="Directory to save per-voice pitch event JSONs")
    args = parser.parse_args()
 
    pages  = preprocess_batch(args.input, args.prep, save_debug=False)
    voices = detect_staff_regions(pages,
                                  model_weights=args.yolo,
                                  output_dir=args.strips)
    events = transcribe_voice_sequences(voices,
                                    model_weights=args.weights,
                                    img_height=args.img_height,
                                    viz_dir=args.viz_dir,
                                    events_dir=args.events_dir)
    print("\nStage 3 complete. Events ready for Stage 4 (SATB reconstruction).")
 