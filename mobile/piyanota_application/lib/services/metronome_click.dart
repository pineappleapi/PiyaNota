import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../models/measure_table.dart';
import '../models/score_result.dart';

/// How strongly a click sounds (PIYA-210 "Accent levels", loudest first).
/// Each is a distinct pitch and level, so they can be told apart by ear.
enum ClickLevel {
  /// Offset 0 of a measure.
  downbeat,

  /// The first click of each later group: beat 3 of 4/4 and 12/8, the
  /// second group of 5 and 7.
  secondary,

  /// Any other beat click.
  beat,

  /// A unit that is not on a beat (only in a slow compound meter).
  subdivision,
}

/// When the metronome clicks (PIYA-209/210), in the time of the rendered
/// tracks (the score's `tempoBpm`), so the engine's speed change (rate =
/// chosen BPM / `tempoBpm`) turns tick `t` into `t x 60000 / (480 x
/// chosen BPM)` ms, as PIYA-210 asks. Not `@immutable`: its constructor
/// checks the two lists line up, which a const one can't.
class ClickPlan {
  ClickPlan({required this.clicks, required this.levels, required this.length})
    : assert(clicks.length == levels.length, 'one level per click');

  /// Onsets in order, all at or after 0 and before [length].
  final List<Duration> clicks;

  /// The level of each click in [clicks].
  final List<ClickLevel> levels;

  /// The track's length: the longest voice, so the click never outlasts
  /// the music nor stops before it.
  final Duration length;

  /// Indexes of the downbeat clicks.
  Set<int> get downbeats => {
    for (var i = 0; i < levels.length; i++)
      if (levels[i] == ClickLevel.downbeat) i,
  };
}

/// Ticks per quarter note in the timing file and the rendered MIDI.
const int ticksPerQuarter = 480;
const int _ticksPerWhole = ticksPerQuarter * 4;

/// PIYA-210: a compound beat at or above this many per minute is clicked
/// once per beat; below it every unit is clicked.
const double compoundBeatThreshold = 60;

/// Two clicks closer than this (a pickup's last click and bar 1's
/// downbeat after rounding, say) are one click: the louder one stays.
const Duration clickMergeWindow = Duration(milliseconds: 5);

/// Lays the click out per measure from the timing file's `bars` (PIYA-117
/// AC9) by the PIYA-210 "Metronome click layout" rules. [chosenBpm] only
/// decides whether slow compound beats are subdivided; the times are in
/// rendered time at [tempoBpm]. With no [bars] it falls back to
/// [planQuarterGrid] on [events].
ClickPlan planClicks({
  required List<BarInfo> bars,
  required List<TimingEvent> events,
  required int tempoBpm,
  required int chosenBpm,
  required Duration length,
}) {
  if (bars.isEmpty) {
    return planQuarterGrid(events: events, tempoBpm: tempoBpm, length: length);
  }
  final usPerTick =
      Duration.microsecondsPerMinute / (ticksPerQuarter * tempoBpm);
  final lengthUs = length.inMicroseconds;
  final raw = <({int us, ClickLevel level})>[];
  for (final (bar, meter) in resolveMeters(bars)) {
    for (final (tick, level) in _barClicks(bar, meter, chosenBpm)) {
      final us = ((bar.startTick + tick) * usPerTick).round();
      if (us >= 0 && us < lengthUs) raw.add((us: us, level: level));
    }
  }
  mergeSort(raw, compare: (a, b) => a.us - b.us);
  final clicks = <Duration>[];
  final levels = <ClickLevel>[];
  for (final click in raw) {
    if (clicks.isNotEmpty &&
        click.us - clicks.last.inMicroseconds <
            clickMergeWindow.inMicroseconds) {
      if (click.level.index < levels.last.index) levels.last = click.level;
      continue;
    }
    clicks.add(Duration(microseconds: click.us));
    levels.add(click.level);
  }
  return ClickPlan(clicks: clicks, levels: levels, length: length);
}

/// A meter as the click uses it.
typedef Meter = ({int numerator, int denominator});

/// Pairs each bar with the meter its clicks use (PIYA-210 "Unknown
/// meter"): its own when [MeterSource.trusted], else the last trusted
/// meter before it, else null (a plain quarter grid).
///
/// A pickup without a trusted meter of its own looks forward instead,
/// to the first trusted meter after it: it is the end of a bar of the
/// meter that follows it, and there is normally nothing before it. Only
/// then the last one before it, then null (quarters counted back).
List<(BarInfo, Meter?)> resolveMeters(List<BarInfo> bars) {
  Meter? meterOf(BarInfo bar) => bar.meterSource.trusted && bar.hasMeter
      ? (numerator: bar.numerator!, denominator: bar.denominator!)
      : null;
  Meter? last;
  final resolved = <(BarInfo, Meter?)>[];
  for (var i = 0; i < bars.length; i++) {
    final bar = bars[i];
    final own = meterOf(bar);
    if (own != null) last = own;
    if (own == null && bar.pickup) {
      Meter? next;
      for (var j = i + 1; j < bars.length && next == null; j++) {
        next = meterOf(bars[j]);
      }
      resolved.add((bar, next ?? last));
      continue;
    }
    resolved.add((bar, last));
  }
  return resolved;
}

/// The compound measures (by index in [bars]) that are clicked on every
/// unit at [chosenBpm]. The plan only changes with speed when this set
/// does (PIYA-210 "Speed changes"), so the controller re-plans only then.
Set<int> subdividedBars(List<BarInfo> bars, int chosenBpm) {
  final resolved = resolveMeters(bars);
  return {
    for (var i = 0; i < resolved.length; i++)
      if (resolved[i].$2 case final meter?)
        if (_isCompound(meter) && _subdivides(meter, chosenBpm)) i,
  };
}

bool _isCompound(Meter meter) =>
    meter.numerator > 3 && meter.numerator % 3 == 0;

/// The beat tempo of a compound meter is chosen BPM x denominator / 12
/// (6/8 at quarter = 90 is 60 beats a minute).
bool _subdivides(Meter meter, int chosenBpm) =>
    chosenBpm * meter.denominator / 12 < compoundBeatThreshold;

/// MuseScore's `stressEvery` on beats per bar (gap doc item 8): every 3rd
/// beat if divisible by 3, else every 2nd if divisible by 2, else one at
/// beat (n+1)/2 + 1 (1-based), so 5 = 3+2 and 7 = 4+3.
Set<int> _secondaryBeats(int beats) {
  if (beats % 3 == 0) return {for (var b = 3; b < beats; b += 3) b};
  if (beats % 2 == 0) return {for (var b = 2; b < beats; b += 2) b};
  if (beats >= 5) return {(beats + 1) ~/ 2};
  return const {};
}

/// One full measure of [meter]: each click's offset from the barline in
/// ticks, and its level.
List<(int, ClickLevel)> _fullBar(Meter meter, int chosenBpm) {
  final unit = _ticksPerWhole ~/ meter.denominator;
  final compound = _isCompound(meter);
  final beatUnits = compound ? 3 : 1;
  final secondary = _secondaryBeats(meter.numerator ~/ beatUnits);
  final subdivide = compound && _subdivides(meter, chosenBpm);
  return [
    for (var u = 0; u < meter.numerator; u++)
      if (u % beatUnits == 0)
        (
          u * unit,
          u == 0
              ? ClickLevel.downbeat
              : secondary.contains(u ~/ beatUnits)
              ? ClickLevel.secondary
              : ClickLevel.beat,
        )
      else if (subdivide)
        (u * unit, ClickLevel.subdivision),
  ];
}

/// [bar]'s clicks as (offset from its barline in ticks, level).
List<(int, ClickLevel)> _barClicks(BarInfo bar, Meter? meter, int chosenBpm) {
  final length = bar.durTicks;
  if (meter == null) {
    // No meter known: quarters from the barline, only the first accented.
    // A pickup's quarters are counted back from its end instead, so they
    // land on bar 1's grid, and none is a downbeat.
    if (bar.pickup) {
      return [
        for (var t = length - ticksPerQuarter; t >= 0; t -= ticksPerQuarter)
          (t, ClickLevel.beat),
      ].reversed.toList();
    }
    return [
      for (var t = 0; t < length; t += ticksPerQuarter)
        (t, t == 0 ? ClickLevel.downbeat : ClickLevel.beat),
    ];
  }
  final pattern = _fullBar(meter, chosenBpm);
  final full = meter.numerator * (_ticksPerWhole ~/ meter.denominator);
  if (bar.pickup) {
    // The end of a full bar: the pickup starts `skip` ticks into it, and
    // each click keeps that position's accent. Never a downbeat (a pickup
    // as long as a full bar, not expected, gets a plain beat there).
    final skip = full - length;
    return [
      for (final (offset, level) in pattern)
        if (offset >= skip)
          (
            offset - skip,
            level == ClickLevel.downbeat ? ClickLevel.beat : level,
          ),
    ];
  }
  // A short final bar stops at its end; a bar longer than its meter (not
  // expected) repeats the pattern rather than going silent.
  return [
    for (var start = 0; start < length; start += full)
      for (final (offset, level) in pattern)
        if (start + offset < length) (start + offset, level),
  ];
}

/// The grid of quarter notes at [tempoBpm], anchored on the start of bar 1
/// (the earliest timestamp of any event with `bar == 1`) and extended
/// backwards into a pickup, so the pickup is counted in too. With no bar
/// numbers at all the grid starts at t = 0. Used only for a timing file
/// without a `bars` table (PIYA-210: "It remains only as the fallback for
/// a timing file with no `bars`.").
///
/// Downbeats: the grid point nearest the first timestamp of each bar from
/// 1 on (bar 0 is a pickup, which starts mid-bar). With no bar numbers,
/// none: every click is a plain beat. A bar whose first timestamp falls
/// outside the clicks gets no downbeat rather than one on the edge click.
ClickPlan planQuarterGrid({
  required List<TimingEvent> events,
  required int tempoBpm,
  required Duration length,
}) {
  final periodUs = Duration.microsecondsPerMinute / tempoBpm;
  final firstOfBar = <int, int>{};
  for (final event in events) {
    final bar = event.bar;
    if (bar == null || bar < 1) continue;
    final known = firstOfBar[bar];
    if (known == null || event.timestampMs < known) {
      firstOfBar[bar] = event.timestampMs;
    }
  }
  final anchorUs = (firstOfBar[1] ?? 0) * 1000.0;
  // The earliest grid point at or after 0 that lines up with bar 1.
  final startUs = anchorUs - (anchorUs / periodUs).floor() * periodUs;
  final lengthUs = length.inMicroseconds;
  final clicks = <Duration>[
    for (var k = 0; startUs + k * periodUs < lengthUs; k++)
      Duration(microseconds: (startUs + k * periodUs).round()),
  ];
  final accents = <int>{
    for (final ms in firstOfBar.values)
      if (ms * 1000 >= startUs && ms * 1000 < lengthUs)
        ((ms * 1000 - startUs) / periodUs).round(),
  };
  return ClickPlan(
    clicks: clicks,
    levels: [
      for (var i = 0; i < clicks.length; i++)
        accents.contains(i) ? ClickLevel.downbeat : ClickLevel.beat,
    ],
    length: length,
  );
}

/// The click track as 16-bit mono PCM WAV. Each click is a short decaying
/// sine (a woodblock-ish tick); its pitch and level follow its
/// [ClickLevel], so the four levels sound distinct.
@visibleForTesting
Uint8List renderClickWav(ClickPlan plan) {
  const sampleRate = clickSampleRate;
  final total = (plan.length.inMicroseconds * sampleRate / 1e6).ceil();
  final pcm = ByteData(total * 2);
  final clickSamples = (_clickSeconds * sampleRate).round();
  final fadeSamples = (_fadeSeconds * sampleRate).round();
  for (var index = 0; index < plan.clicks.length; index++) {
    final (freq, level) = _voicing[plan.levels[index]]!;
    final gain = level * _pcmMax;
    final start = (plan.clicks[index].inMicroseconds * sampleRate / 1e6)
        .round();
    for (var i = 0; i < clickSamples && start + i < total; i++) {
      final t = i / sampleRate;
      // A linear fade over the last samples, so the cut-off at
      // _clickSeconds leaves no step (an audible tick of its own).
      final fade = math.min(1.0, (clickSamples - i) / fadeSamples);
      final sample =
          math.sin(2 * math.pi * freq * t) *
          math.exp(-t / _decaySeconds) *
          fade;
      pcm.setInt16((start + i) * 2, (sample * gain).round(), Endian.little);
    }
  }
  return _wavFile(pcm.buffer.asUint8List(), sampleRate);
}

const int clickSampleRate = 22050;
const double _clickSeconds = 0.04;
const double _decaySeconds = 0.008;
const double _fadeSeconds = 0.002;

/// (Hz, level 0-1) per click level: higher and louder for stronger ones.
const Map<ClickLevel, (double, double)> _voicing = {
  ClickLevel.downbeat: (1600, 0.9),
  // Close to the beat, so beat 3 of 4/4 isn't heard as a new bar; the
  // downbeat alone is high and loud.
  ClickLevel.secondary: (1100, 0.62),
  ClickLevel.beat: (1000, 0.55),
  ClickLevel.subdivision: (800, 0.3),
};
const int _pcmMax = 32767;

Uint8List _wavFile(Uint8List pcm, int sampleRate) {
  const channels = 1;
  const bytesPerSample = 2;
  const headerSize = 44;
  final header = ByteData(headerSize)
    ..setUint32(0, 0x52494646) // RIFF
    ..setUint32(4, 36 + pcm.length, Endian.little)
    ..setUint32(8, 0x57415645) // WAVE
    ..setUint32(12, 0x666d7420) // fmt
    ..setUint32(16, 16, Endian.little)
    ..setUint16(20, 1, Endian.little) // PCM
    ..setUint16(22, channels, Endian.little)
    ..setUint32(24, sampleRate, Endian.little)
    ..setUint32(28, sampleRate * channels * bytesPerSample, Endian.little)
    ..setUint16(32, channels * bytesPerSample, Endian.little)
    ..setUint16(34, bytesPerSample * 8, Endian.little)
    ..setUint32(36, 0x64617461) // data
    ..setUint32(40, pcm.length, Endian.little);
  return (BytesBuilder(copy: false)
        ..add(header.buffer.asUint8List())
        ..add(pcm))
      .takeBytes();
}

/// Writes [plan] as a WAV under a unique name in the app's temp dir and
/// returns its URI. Synthesis runs off the UI isolate (a long score is
/// several MB of PCM). The caller deletes the file when done with it.
typedef ClickTrackWriter = Future<Uri> Function(ClickPlan plan);

Future<Uri> writeClickTrack(ClickPlan plan) async {
  final dir = await getTemporaryDirectory();
  final file = File(
    '${dir.path}/metronome_click_'
    '${DateTime.now().microsecondsSinceEpoch}.wav',
  );
  await Isolate.run(() => file.writeAsBytesSync(renderClickWav(plan)));
  return file.uri;
}
