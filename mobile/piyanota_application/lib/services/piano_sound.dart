import 'live_synth.dart';

/// MIDI channel for the piano: 0-3 are the voices, 9 the click.
const int kPianoChannel = 5;

/// Note on/off for the virtual piano. Rides the playback screen's one
/// FluidSynth (the app has no other real-time synth; plan decision D1).
abstract class PianoSound {
  void noteOn(int midi, int velocity);
  void noteOff(int midi);
  void releaseAll();
}

class LiveSynthPianoSound implements PianoSound {
  LiveSynthPianoSound(this._synth);

  final LiveSynth _synth;

  @override
  void noteOn(int midi, int velocity) =>
      _synth.note(kPianoChannel, midi, velocity);

  @override
  void noteOff(int midi) => _synth.note(kPianoChannel, midi, 0);

  @override
  void releaseAll() => _synth.allNotesOff(kPianoChannel);
}
