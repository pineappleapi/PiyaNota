import 'dart:async';
import 'dart:math';

import 'package:clock/clock.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/services/metronome_click.dart';

import 'playback_engine_test.dart' show FakeAudioPlayer, rig, tracks;

const int _tempoBpm = 90;
const Duration _trackLength = Duration(seconds: 10);

/// The engine's drift trigger: the tolerance the task allows a tick.
const double _toleranceMs = 25;

/// Wall-clock sampling step of the virtual clock.
const Duration _step = Duration(milliseconds: 1);

/// Plays a click plan for the 90 BPM 4/4 score through the real engine
/// with fake voices and a fake click player on the virtual clock, with
/// realistic, unequal seek latencies, and returns the worst wall-clock
/// gap in ms between a click sounding and its beat sounding in the master
/// voice. [afterSeek] seeks mid-play first; [midSpeed] changes speed
/// mid-play.
double _worstOffsetMs(double speed, {Duration? afterSeek, double? midSpeed}) {
  var worst = 0.0;
  fakeAsync((async) {
    final click = FakeAudioPlayer()
      ..seekDelay = const Duration(milliseconds: 8);
    final r = rig(
      click: click,
      overrides: {
        for (final v in tracks().keys)
          v: FakeAudioPlayer()..seekDelay = const Duration(milliseconds: 35),
      },
    );
    final plan = planClicks(
      bars: [
        for (var i = 0; i < 5; i++)
          BarInfo(
            bar: i + 1,
            startTick: i * 1920,
            durTicks: 1920,
            numerator: 4,
            denominator: 4,
            meterSource: MeterSource.detected,
          ),
      ],
      events: const [],
      tempoBpm: _tempoBpm,
      chosenBpm: _tempoBpm,
      length: _trackLength,
    );
    unawaited(r.engine.load(tracks()));
    async.flushMicrotasks();
    unawaited(r.engine.setSpeed(speed));
    async.flushMicrotasks();
    unawaited(r.engine.attachClick(Uri.file('/tmp/click.wav')));
    async.elapse(const Duration(milliseconds: 200));
    unawaited(r.engine.play());
    async.elapse(const Duration(seconds: 1));
    if (afterSeek != null) {
      unawaited(r.engine.seek(afterSeek));
    }
    if (midSpeed != null) {
      unawaited(r.engine.setSpeed(midSpeed));
    }
    // Let the drift check and any resync settle, then measure.
    async.elapse(const Duration(seconds: 1));
    final master = r.players.values.first;
    final from = master.position;
    final pending = [
      for (var i = 0; i < plan.clicks.length; i++)
        if (plan.clicks[i] > from + const Duration(milliseconds: 100)) i,
    ].take(6).toList();
    final clickAt = <int, DateTime>{};
    final beatAt = <int, DateTime>{};
    for (var t = 0; t < 8000 && pending.isNotEmpty; t++) {
      async.elapse(_step);
      for (final i in [...pending]) {
        final beat = _beatTrackTime(i);
        if (!beatAt.containsKey(i) && master.position >= beat) {
          beatAt[i] = clock.now();
        }
        if (!clickAt.containsKey(i) && click.position >= plan.clicks[i]) {
          clickAt[i] = clock.now();
        }
        if (beatAt.containsKey(i) && clickAt.containsKey(i)) pending.remove(i);
      }
    }
    expect(pending, isEmpty, reason: 'every sampled beat was reached');
    for (final i in clickAt.keys) {
      // The plan itself is on the beat in track time.
      expect(
        (plan.clicks[i] - _beatTrackTime(i)).inMicroseconds.abs(),
        lessThan(2),
      );
      worst = max(
        worst,
        clickAt[i]!.difference(beatAt[i]!).inMicroseconds.abs() / 1000,
      );
    }
    unawaited(r.engine.dispose());
    async.flushMicrotasks();
  });
  return worst;
}

/// Beat [i] in track time: a quarter at [_tempoBpm], worked out from the
/// tempo alone, independent of the plan code.
Duration _beatTrackTime(int i) =>
    Duration(microseconds: (i * 60e6 / _tempoBpm).round());

void main() {
  group('metronome ticks stay on the beat (F8b)', () {
    for (final speed in [0.5, 0.75, 1.0, 1.25, 1.5]) {
      test('speed $speed: from the start, after a seek, and after a speed '
          'change', () {
        final results = {
          'start': _worstOffsetMs(speed),
          'seek': _worstOffsetMs(
            speed,
            afterSeek: const Duration(milliseconds: 3300),
          ),
          'speed change': _worstOffsetMs(
            speed,
            midSpeed: speed == 1.5 ? 0.75 : 1.5,
          ),
        };
        debugPrint('F8b speed $speed max tick offset ms: $results');
        for (final entry in results.entries) {
          expect(
            entry.value,
            lessThanOrEqualTo(_toleranceMs),
            reason: entry.key,
          );
        }
      });
    }
  });
}
