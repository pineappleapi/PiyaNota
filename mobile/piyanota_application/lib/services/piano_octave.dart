import '../models/voice_part.dart';

/// Octave and MIDI rules of the virtual piano (PIYA-218 AC 13, 18, 25-27, 39).
const int kPianoMinOctave = 2;
const int kPianoMaxOctave = 6;
const int kPianoMiddleCOctave = 4;
const int kPianoLowVoiceOctave = 3;
const int kPianoNoteVelocity = 100;

/// White keys C..B as semitone offsets from the octave's C.
const List<int> kWhiteKeyOffsets = [0, 2, 4, 5, 7, 9, 11];

/// MIDI number of C in [octave]: C4 = 60.
int midiForC(int octave) => 12 * (octave + 1);

bool isValidOctave(Object? value) =>
    value is int && value >= kPianoMinOctave && value <= kPianoMaxOctave;

/// Tenor and bass sing low; everyone else, and a missing voice, opens on 4.
int defaultOctaveFor(VoicePart? voice) =>
    (voice == VoicePart.tenor || voice == VoicePart.bass)
    ? kPianoLowVoiceOctave
    : kPianoMiddleCOctave;
