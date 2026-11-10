/// All copy of the virtual piano modal (PIYA-218).
abstract final class PianoMessages {
  static const String title = 'Piano';
  static const String description = 'Find your pitch.';
  static const String lower = 'Lower';
  static const String higher = 'Higher';
  static const String lowerA11y = 'Lower octave';
  static const String higherA11y = 'Higher octave';
  static const String openButton = 'Piano';
  static const String close = 'Close piano';
  static const String info = 'Notes chart';
  static const String chartTitle = 'Notes Chart';
  static const String chartClose = 'Close notes chart';
  static const String chartA11y =
      'Notes chart: treble clef C4 to G5, bass clef E2 to B3';
  static const String soundUnavailable =
      'Sound is unavailable on this device.';

  static String octave(int n) => 'Octave $n';

  static String keyA11y(String name, int octave) => '$name, octave $octave';
}
