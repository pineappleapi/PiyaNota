import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/midi_voice_split.dart';

void main() {
  test('midiTotalTicks is the last event tick; live file keeps it', () {
    final click = buildClickMidi([(0, true), (480, false), (960, false)], 90);
    // Last click note-off: 960 + 30.
    expect(midiTotalTicks(click), 990);
    final live = buildLiveMidi(click, {9: const []}, clicks: [(1440, true)]);
    expect(midiTotalTicks(live), 1470);
  });
}
