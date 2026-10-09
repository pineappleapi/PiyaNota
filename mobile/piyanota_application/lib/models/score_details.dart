import 'package:flutter/foundation.dart';

/// What the user knows about the score before capturing it (PIYA-206 step
/// 1). Only [title] is required. Key and time signature are display labels
/// only: the pipeline never uses them as recognition hints (PIYA-101 AC8).
@immutable
class ScoreDetails {
  const ScoreDetails({
    required this.title,
    this.arranger = '',
    this.keySignature,
    this.timeSignature,
    this.tempoBpm,
  });

  /// Already trimmed, 1–[maxTextLength] code points.
  final String title;

  /// Trimmed; empty means "not given", and the field is then omitted.
  final String arranger;

  /// Null is "Not sure".
  final KeySignature? keySignature;

  /// Null is "Not sure"; [TimeSignature.other] is a deliberate answer that
  /// is still not sent (PIYA-101 AC8: both omit the field).
  final TimeSignature? timeSignature;

  /// Quarter notes per minute, [minTempo]–[maxTempo]. Null means "not set";
  /// the server then uses [defaultTempo].
  final int? tempoBpm;

  /// PIYA-101 AC8 counts Unicode code points after trimming, not graphemes,
  /// so the limit is checked with `runes.length` (see [codePointLength]).
  static const int maxTextLength = 120;
  static const int minTempo = 30;
  static const int maxTempo = 240;
  static const int defaultTempo = 90;

  static int codePointLength(String text) => text.runes.length;
}

/// The 15 key signatures, by how many sharps or flats open each line.
/// [apiValue] is the exact PIYA-101 AC8 string (major key name, ASCII `#`
/// and lowercase `b`).
enum KeySignature {
  c(0, 'C', 'C major'),
  g(1, 'G', 'G major'),
  d(2, 'D', 'D major'),
  a(3, 'A', 'A major'),
  e(4, 'E', 'E major'),
  b(5, 'B', 'B major'),
  fSharp(6, 'F#', 'F♯ major'),
  cSharp(7, 'C#', 'C♯ major'),
  f(-1, 'F', 'F major'),
  bFlat(-2, 'Bb', 'B♭ major'),
  eFlat(-3, 'Eb', 'E♭ major'),
  aFlat(-4, 'Ab', 'A♭ major'),
  dFlat(-5, 'Db', 'D♭ major'),
  gFlat(-6, 'Gb', 'G♭ major'),
  cFlat(-7, 'Cb', 'C♭ major');

  const KeySignature(this.accidentals, this.apiValue, this.majorName);

  /// Positive = sharps, negative = flats, 0 = none.
  final int accidentals;
  final String apiValue;
  final String majorName;

  int get count => accidentals.abs();
  bool get isFlat => accidentals < 0;

  /// The plain-words count a singer can check against the page.
  String get countLabel {
    if (accidentals == 0) return 'No ♯ or ♭';
    final noun = isFlat ? 'flat' : 'sharp';
    return '$count $noun${count == 1 ? '' : 's'}';
  }

  /// e.g. "2 sharps · D major".
  String get label => '$countLabel · $majorName';
}

enum TimeSignature {
  fourFour('4', '4'),
  threeFour('3', '4'),
  twoFour('2', '4'),
  sixEight('6', '8'),
  twoTwo('2', '2'),
  other(null, null);

  const TimeSignature(this.beats, this.unit);

  final String? beats;
  final String? unit;

  /// PIYA-101 AC8 value, or null for [other] (the field is omitted).
  String? get apiValue => beats == null ? null : '$beats/$unit';

  String get label => apiValue ?? 'Other';
}
