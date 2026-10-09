import 'dart:io';
import 'dart:isolate';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../models/score_result.dart';

/// When the metronome clicks (PIYA-209/210, user decisions 2026-10-09),
/// in the time of the rendered tracks: one click per quarter note at the
/// score's `tempoBpm`, so the engine's speed change (rate = chosen BPM /
/// `tempoBpm`) turns it into a click at the chosen BPM.
@immutable
class ClickPlan {
  const ClickPlan({
    required this.clicks,
    required this.accents,
    required this.length,
  });

  /// Onsets in order, from the first grid point at or after 0.
  final List<Duration> clicks;

  /// Indexes into [clicks] that start a bar (the higher, louder click).
  final Set<int> accents;

  /// The track's length: the longest voice, so the click never outlasts
  /// the music nor stops before it.
  final Duration length;
}

/// The grid of quarter notes at [tempoBpm], anchored on the start of bar 1
/// (the earliest timestamp of any event with `bar == 1`) and extended
/// backwards into a pickup, so the pickup is counted in too. With no bar
/// numbers at all the grid starts at t = 0.
///
/// Accents: the grid point nearest the first timestamp of each bar from 1
/// on (bar 0 is a pickup, which starts mid-bar). With no bar numbers, no
/// accents: the meter is unknown, so every click is the same. A bar whose
/// first timestamp falls outside the clicks (before the grid starts, or at
/// or past the end) gets no accent rather than one on the edge click.
///
/// A bar's first timestamp is its first *event*. That is its downbeat
/// because PIYA-117 AC7 includes rest events, so a bar that opens on a
/// rest still has an event there. (A timing file without rest events
/// would put such a bar's accent on its first note instead.)
ClickPlan planClicks({
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
  }..removeWhere((index) => index >= clicks.length);
  return ClickPlan(clicks: clicks, accents: accents, length: length);
}

/// The click track as 16-bit mono PCM WAV. Each click is a short decaying
/// sine (a woodblock-ish tick); a bar start is higher and louder.
@visibleForTesting
Uint8List renderClickWav(ClickPlan plan) {
  const sampleRate = clickSampleRate;
  final total = (plan.length.inMicroseconds * sampleRate / 1e6).ceil();
  final pcm = ByteData(total * 2);
  final clickSamples = (_clickSeconds * sampleRate).round();
  for (var index = 0; index < plan.clicks.length; index++) {
    final accent = plan.accents.contains(index);
    final freq = accent ? _accentHz : _beatHz;
    final gain = (accent ? _accentLevel : _beatLevel) * _pcmMax;
    final start = (plan.clicks[index].inMicroseconds * sampleRate / 1e6)
        .round();
    for (var i = 0; i < clickSamples && start + i < total; i++) {
      final t = i / sampleRate;
      final sample =
          math.sin(2 * math.pi * freq * t) * math.exp(-t / _decaySeconds);
      pcm.setInt16((start + i) * 2, (sample * gain).round(), Endian.little);
    }
  }
  return _wavFile(pcm.buffer.asUint8List(), sampleRate);
}

const int clickSampleRate = 22050;
const double _clickSeconds = 0.04;
const double _decaySeconds = 0.008;
const double _beatHz = 1000;
const double _accentHz = 1600;
const double _beatLevel = 0.55;
const double _accentLevel = 0.85;
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
