import 'package:flutter/foundation.dart';

import 'score_result.dart';

/// How Stage 4 got a measure's meter (PIYA-108 AC7, PIYA-117 AC9).
enum MeterSource {
  /// Read for this measure in its own system.
  detected,

  /// Carried over from an earlier system.
  inherited,

  /// Nothing read before it anywhere; Stage 4 assumed 4/4.
  assumed,

  /// Stage 4 could not establish one (also any value this app doesn't
  /// know, so a newer server never breaks the click).
  unknown;

  /// Whether the meter was actually read from the score, so the click
  /// can trust it (PIYA-210: `default` and `unknown` borrow the last
  /// trusted meter instead).
  bool get trusted => this == detected || this == inherited;

  static MeterSource parse(Object? value) => switch (value) {
    'detected' => detected,
    'inherited' => inherited,
    'default' => assumed,
    _ => unknown,
  };
}

/// One PIYA-117 AC9 `bars` entry: a measure of the whole piece, in ticks
/// at 480 PPQ. `groups` is reserved and ignored.
@immutable
class BarInfo {
  const BarInfo({
    required this.bar,
    required this.startTick,
    required this.durTicks,
    this.startMs,
    this.durMs,
    this.numerator,
    this.denominator,
    this.meterSource = MeterSource.unknown,
    this.pickup = false,
  });

  /// Printed measure number; 0 is the pickup.
  final int bar;
  final int startTick;

  /// Actual length: a pickup or a short final bar is shorter than its
  /// meter.
  final int durTicks;
  final int? startMs;
  final int? durMs;

  /// Both null when the meter is unusable (absent, or a denominator that
  /// isn't a power of two from 1 to 64).
  final int? numerator;
  final int? denominator;
  final MeterSource meterSource;
  final bool pickup;

  bool get hasMeter => numerator != null && denominator != null;

  static const Set<int> _denominators = {1, 2, 4, 8, 16, 32, 64};

  /// Null for an entry that can't be placed (no bar number, or bad
  /// ticks); a bad meter only makes the meter unknown. One bad entry never
  /// discards the table.
  static BarInfo? tryParse(Object? json) {
    if (json is! Map) return null;
    final bar = json['bar'];
    final startTick = json['startTick'];
    final durTicks = json['durTicks'];
    if (bar is! int || bar < 0) return null;
    if (startTick is! int || startTick < 0) return null;
    if (durTicks is! int || durTicks <= 0) return null;
    final numerator = json['numerator'];
    final denominator = json['denominator'];
    final meterOk =
        numerator is int &&
        numerator > 0 &&
        denominator is int &&
        _denominators.contains(denominator);
    final startMs = json['startMs'];
    final durMs = json['durMs'];
    return BarInfo(
      bar: bar,
      startTick: startTick,
      durTicks: durTicks,
      startMs: startMs is int && startMs >= 0 ? startMs : null,
      durMs: durMs is int && durMs >= 0 ? durMs : null,
      numerator: meterOk ? numerator : null,
      denominator: meterOk ? denominator : null,
      meterSource: MeterSource.parse(json['meterSource']),
      pickup: json['pickup'] == true,
    );
  }
}

/// A whole PIYA-117 timing file: the events, and the measure table when
/// the file has one (empty for a bare event list or an older server).
@immutable
class TimingFile {
  const TimingFile({required this.events, this.bars = const []});

  static const TimingFile empty = TimingFile(events: []);

  final List<TimingEvent> events;
  final List<BarInfo> bars;

  /// See [parseTimingEvents] for the events (which throws when there is no
  /// event list at all). A `bars` that isn't a list is no table, not an
  /// error: the click falls back to its quarter-note grid.
  static TimingFile parse(Object? json) {
    final events = parseTimingEvents(json);
    final raw = json is Map ? json['bars'] : null;
    final bars = <BarInfo>[
      if (raw is List)
        for (final entry in raw) ?BarInfo.tryParse(entry),
    ];
    mergeSort(bars, compare: (a, b) => a.startTick - b.startTick);
    return TimingFile(events: events, bars: List.unmodifiable(bars));
  }
}
