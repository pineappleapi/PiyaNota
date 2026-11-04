import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import 'measure_table.dart';
import 'score_result.dart';

/// Whether ⏮ skips a pickup (anacrusis) and goes to t = 0 instead of the
/// start of bar 1. Confirmed by the user 2026-10-09: ⏮ goes to t = 0, so a
/// pickup is heard. Kept as one constant (tests cover both values) in case
/// the rule is ever revisited.
const bool kSkipBackIncludesPickup = true;

/// Whether the playback line holds on a bar's left edge and jumps at each
/// bar start, instead of sliding between notes. Note x inside a bar is
/// unmeasured; only barlines are (docs/decisions/app-bar-step-playback-line.md).
const bool kBarStepLine = true;

/// Where ⏮ and ⏭ jump to (user decision 2026-10-09), from the timing
/// events alone. One pure function so the rule is easy to change:
///
/// - ⏮: the start of the earliest event in bar 1. If there is a pickup
///   (bar 0) and [includePickup] is true, t = 0 instead, so the pickup is
///   heard. No bar 1 at all: t = 0.
/// - ⏭: the start of the earliest event in the highest numbered bar.
/// - No bar numbers at all (every `bar` null): ⏮ is t = 0 and ⏭ is the
///   last event's onset. No events at all: ⏭ is null (the caller uses the
///   audio's end).
({Duration back, Duration? forward}) skipTargets(
  List<TimingEvent> events, {
  bool includePickup = kSkipBackIncludesPickup,
}) {
  int? firstOfBarOne;
  int? maxBar;
  int? firstOfMaxBar;
  var hasPickup = false;
  int? lastOnset;
  for (final event in events) {
    final t = event.timestampMs;
    if (lastOnset == null || t > lastOnset) lastOnset = t;
    final bar = event.bar;
    if (bar == null) continue;
    if (bar == 0) hasPickup = true;
    if (bar == 1 && (firstOfBarOne == null || t < firstOfBarOne)) {
      firstOfBarOne = t;
    }
    if (maxBar == null || bar > maxBar) {
      maxBar = bar;
      firstOfMaxBar = t;
    } else if (bar == maxBar && t < firstOfMaxBar!) {
      firstOfMaxBar = t;
    }
  }
  if (maxBar == null) {
    return (
      back: Duration.zero,
      forward: lastOnset == null ? null : Duration(milliseconds: lastOnset),
    );
  }
  final back = (hasPickup && includePickup) || firstOfBarOne == null
      ? Duration.zero
      : Duration(milliseconds: firstOfBarOne);
  return (back: back, forward: Duration(milliseconds: firstOfMaxBar!));
}

/// The playback indicator at one instant, in page-image pixels.
@immutable
class IndicatorPosition {
  const IndicatorPosition({
    required this.pageIndex,
    required this.systemIndex,
    required this.x,
    required this.top,
    required this.bottom,
  });

  final int pageIndex;

  /// Which system on the page, counted from 0 at the top. Lets the screen
  /// tell a jump to a new system from movement along the same one.
  final int systemIndex;
  final double x;
  final double top;
  final double bottom;

  @override
  bool operator ==(Object other) =>
      other is IndicatorPosition &&
      other.pageIndex == pageIndex &&
      other.systemIndex == systemIndex &&
      other.x == x &&
      other.top == top &&
      other.bottom == bottom;

  @override
  int get hashCode => Object.hash(pageIndex, systemIndex, x, top, bottom);

  @override
  String toString() =>
      'IndicatorPosition(page $pageIndex, system $systemIndex, x $x, '
      '$top..$bottom)';
}

/// All notes sounding from one instant on one page (a chord across the
/// voices). A list entry, never a map key: chords share a timestamp.
class _Onset {
  _Onset(this.timestampMs, this.pageIndex);

  final int timestampMs;
  final int pageIndex;
  final List<TimingEvent> events = [];
  late int system;

  double get x => events.fold<double>(0, (sum, e) => sum + e.x) / events.length;
}

/// Where the bar-step line sits from [startMs] until the next step.
class _Step {
  _Step(
    this.startMs,
    this.pageIndex,
    this.system,
    this.x,
    this.top,
    this.bottom,
  );

  final int startMs;
  final int pageIndex;
  final int system;
  final double x;
  final double top;
  final double bottom;
}

/// Maps an audio position to where the indicator band sits (PIYA-208 AC6).
///
/// Driven by the audio position the engine reports, never a wall clock,
/// so it stays right at any playback speed (PIYA-210).
class ScoreTimeline {
  ScoreTimeline(
    List<TimingEvent> events, {
    List<BarInfo> bars = const [],
    this.barStep = kBarStepLine,
  }) : events = _sorted(events) {
    for (final event in this.events) {
      final last = _onsets.isEmpty ? null : _onsets.last;
      if (last != null &&
          last.timestampMs == event.timestampMs &&
          last.pageIndex == event.pageIndex) {
        last.events.add(event);
      } else {
        _onsets.add(
          _Onset(event.timestampMs, event.pageIndex)..events.add(event),
        );
      }
    }
    _assignSystems();
    _measureSystems();
    if (barStep) _buildSteps(bars);
  }

  static final ScoreTimeline empty = ScoreTimeline(const []);

  /// Without `systemIndex`, a new system starts where the onsets jump back
  /// left by more than this share of the page's widest x: a line break.
  static const double systemBreakShare = 0.25;

  /// Without `systemTopY`/`systemBottomY`, the band reaches this share of
  /// the distance between neighbouring staves past the outermost notes, so
  /// it covers all four staves, not just the note heads.
  static const double staffGapPadShare = 0.25;

  /// Padding when a system has only one voice's notes, as a share of the
  /// page's widest x, since there is no staff spacing to measure.
  static const double singleStaffPadShare = 0.05;

  /// Every event, sorted by time (stably: file order breaks ties).
  final List<TimingEvent> events;
  final List<_Onset> _onsets = [];

  /// See [kBarStepLine]; false keeps the per-note slide.
  final bool barStep;
  final List<_Step> _steps = [];
  final Map<(int, int), ({double top, double bottom})> _systems = {};

  bool get isEmpty => _onsets.isEmpty;

  static List<TimingEvent> _sorted(List<TimingEvent> events) {
    final copy = [...events];
    mergeSort(copy, compare: (a, b) => a.timestampMs - b.timestampMs);
    return List.unmodifiable(copy);
  }

  /// Where the band sits at [position]: on the latest onset at or before
  /// it, sliding toward the next onset on the same system. Before the
  /// first onset it waits on the first one; after the last it stays there.
  IndicatorPosition? positionAt(Duration position) {
    if (_onsets.isEmpty) return null;
    final t = position.inMicroseconds / Duration.microsecondsPerMillisecond;
    if (barStep) {
      final i = _lastAtOrBefore(_steps.length, (i) => _steps[i].startMs, t);
      final step = _steps[i < 0 ? 0 : i];
      return IndicatorPosition(
        pageIndex: step.pageIndex,
        systemIndex: step.system,
        x: step.x,
        top: step.top,
        bottom: step.bottom,
      );
    }
    final found = _lastAtOrBefore(
      _onsets.length,
      (i) => _onsets[i].timestampMs,
      t,
    );
    final onset = _onsets[found < 0 ? 0 : found];
    var x = onset.x;
    if (found >= 0 && found + 1 < _onsets.length) {
      final next = _onsets[found + 1];
      if (next.pageIndex == onset.pageIndex && next.system == onset.system) {
        final span = next.timestampMs - onset.timestampMs;
        final progress = ((t - onset.timestampMs) / span).clamp(0.0, 1.0);
        x += (next.x - onset.x) * progress;
      }
    }
    final band = _systems[(onset.pageIndex, onset.system)]!;
    return IndicatorPosition(
      pageIndex: onset.pageIndex,
      systemIndex: onset.system,
      x: x,
      top: band.top,
      bottom: band.bottom,
    );
  }

  /// Binary search: the last index in 0..<[n] whose time is <= [t], or -1.
  static int _lastAtOrBefore(int n, int Function(int) timeAt, double t) {
    var low = 0;
    var high = n - 1;
    var found = -1;
    while (low <= high) {
      final mid = (low + high) >> 1;
      if (timeAt(mid) <= t) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  /// One step per bar: the backend's bar positions when every bar has
  /// them (so a bar with no events still moves the line), otherwise the
  /// downbeat x derived from the events (old stored rows). An onset whose
  /// events carry no bar number is its own step.
  void _buildSteps(List<BarInfo> bars) {
    if (bars.isNotEmpty && bars.every((b) => b.hasPosition)) {
      for (final bar in bars) {
        _steps.add(
          _Step(
            bar.startMs!,
            bar.pageIndex!,
            bar.systemIndex!,
            bar.x!,
            bar.systemTopY!,
            bar.systemBottomY!,
          ),
        );
      }
    } else {
      final byBar = <(int, int, int), List<TimingEvent>>{};
      final firstOnset = <(int, int, int), _Onset>{};
      for (final onset in _onsets) {
        final bar = onset.events.map((e) => e.bar).whereType<int>().firstOrNull;
        final band = _systems[(onset.pageIndex, onset.system)]!;
        if (bar == null) {
          _steps.add(
            _Step(
              onset.timestampMs,
              onset.pageIndex,
              onset.system,
              onset.x,
              band.top,
              band.bottom,
            ),
          );
          continue;
        }
        final key = (bar, onset.pageIndex, onset.system);
        firstOnset.putIfAbsent(key, () => onset);
        byBar.putIfAbsent(key, () => []).addAll(onset.events);
      }
      byBar.forEach((key, events) {
        final ticks = events.map((e) => e.tick).whereType<int>();
        final downbeat = ticks.isEmpty ? null : ticks.reduce(math.min);
        final xs = [
          for (final e in events)
            if (downbeat == null || e.tick == downbeat) e.x,
        ];
        final start = firstOnset[key]!;
        final band = _systems[(key.$2, key.$3)]!;
        _steps.add(
          _Step(
            start.timestampMs,
            key.$2,
            key.$3,
            xs.reduce(math.min),
            band.top,
            band.bottom,
          ),
        );
      });
    }
    mergeSort(_steps, compare: (a, b) => a.startMs - b.startMs);
  }

  void _assignSystems() {
    final widest = <int, double>{};
    for (final onset in _onsets) {
      for (final event in onset.events) {
        final current = widest[onset.pageIndex] ?? 0;
        if (event.x > current) widest[onset.pageIndex] = event.x;
      }
    }
    final derived = <int, int>{};
    final lastX = <int, double>{};
    for (final onset in _onsets) {
      final page = onset.pageIndex;
      final explicit = onset.events
          .map((e) => e.systemIndex)
          .whereType<int>()
          .firstOrNull;
      final x = onset.x;
      final previous = lastX[page];
      if (previous != null && previous - x > widest[page]! * systemBreakShare) {
        derived[page] = (derived[page] ?? 0) + 1;
      }
      lastX[page] = x;
      onset.system = explicit ?? derived[page] ?? 0;
    }
  }

  void _measureSystems() {
    final grouped = <(int, int), List<TimingEvent>>{};
    final widest = <int, double>{};
    for (final onset in _onsets) {
      grouped
          .putIfAbsent((onset.pageIndex, onset.system), () => [])
          .addAll(onset.events);
      for (final event in onset.events) {
        final current = widest[onset.pageIndex] ?? 0;
        if (event.x > current) widest[onset.pageIndex] = event.x;
      }
    }
    grouped.forEach((key, events) {
      final tops = events.map((e) => e.systemTopY).whereType<double>();
      final bottoms = events.map((e) => e.systemBottomY).whereType<double>();
      if (tops.isNotEmpty && bottoms.isNotEmpty) {
        _systems[key] = (
          top: tops.reduce((a, b) => a < b ? a : b),
          bottom: bottoms.reduce((a, b) => a > b ? a : b),
        );
        return;
      }
      _systems[key] = _derivedBand(events, widest[key.$1]!);
    });
  }

  /// The band from the notes alone: their y range, widened by a quarter
  /// of the typical distance between voices' staves.
  static ({double top, double bottom}) _derivedBand(
    List<TimingEvent> events,
    double widestX,
  ) {
    var top = double.infinity;
    var bottom = double.negativeInfinity;
    final byVoice = <Object?, List<double>>{};
    for (final event in events) {
      if (event.y < top) top = event.y;
      if (event.y > bottom) bottom = event.y;
      byVoice.putIfAbsent(event.voice, () => []).add(event.y);
    }
    final centres = [
      for (final ys in byVoice.values) ys.reduce((a, b) => a + b) / ys.length,
    ]..sort();
    final gaps = [
      for (var i = 1; i < centres.length; i++) centres[i] - centres[i - 1],
    ]..sort();
    final pad = gaps.isEmpty
        ? widestX * singleStaffPadShare
        : gaps[gaps.length ~/ 2] * staffGapPadShare;
    return (top: (top - pad).clamp(0.0, double.infinity), bottom: bottom + pad);
  }
}
