import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/services/metronome_click.dart';

import 'playback_fakes.dart';

List<int> _ms(ClickPlan plan) => [
  for (final click in plan.clicks) click.inMilliseconds,
];

TimingEvent _at(int ms, int? bar) => ev(ms, 0, 0, bar: bar);

void main() {
  group('planClicks', () {
    test('no bar numbers: quarters from t = 0, no accents', () {
      final plan = planClicks(
        events: [_at(0, null), _at(700, null)],
        tempoBpm: 90,
        length: const Duration(seconds: 3),
      );
      expect(_ms(plan), [0, 666, 1333, 2000, 2666]);
      expect(plan.accents, isEmpty);
      expect(plan.length, const Duration(seconds: 3));
    });

    test('anchored on the start of bar 1, accent on each bar start', () {
      // 4/4 at 120: bar 1 starts at 0.7 s, bar 2 two seconds later.
      final plan = planClicks(
        events: [_at(950, 1), _at(700, 1), _at(2700, 2), _at(3200, 2)],
        tempoBpm: 120,
        length: const Duration(seconds: 4),
      );
      // Extended back from 0.7 s to the first grid point at or after 0.
      expect(_ms(plan), [200, 700, 1200, 1700, 2200, 2700, 3200, 3700]);
      expect(plan.accents, {1, 5});
    });

    test('a pickup is counted in, but its bar is not accented', () {
      final plan = planClicks(
        events: [_at(0, 0), _at(500, 0), _at(1000, 1), _at(3000, 2)],
        tempoBpm: 120,
        length: const Duration(milliseconds: 3500),
      );
      expect(_ms(plan), [0, 500, 1000, 1500, 2000, 2500, 3000]);
      expect(plan.accents, {2, 6});
    });

    test('a bar start off the grid snaps to the nearest click', () {
      final plan = planClicks(
        events: [_at(0, 1), _at(2030, 2)],
        tempoBpm: 60,
        length: const Duration(seconds: 3),
      );
      expect(_ms(plan), [0, 1000, 2000]);
      expect(plan.accents, {0, 2});
    });

    test('no events at all: a plain grid', () {
      final plan = planClicks(
        events: const [],
        tempoBpm: 240,
        length: const Duration(seconds: 1),
      );
      expect(_ms(plan), [0, 250, 500, 750]);
      expect(plan.accents, isEmpty);
    });
  });

  group('renderClickWav', () {
    int sampleAt(ByteData data, Duration t) => data.getInt16(
      44 + (t.inMicroseconds * clickSampleRate / 1e6).round() * 2,
      Endian.little,
    );

    int peak(ByteData data, Duration from) {
      var best = 0;
      final start = (from.inMicroseconds * clickSampleRate / 1e6).round();
      for (var i = start; i < start + 400; i++) {
        best = best > data.getInt16(44 + i * 2, Endian.little).abs()
            ? best
            : data.getInt16(44 + i * 2, Endian.little).abs();
      }
      return best;
    }

    test('mono 16-bit WAV of the plan length; accents are louder', () {
      final bytes = renderClickWav(
        const ClickPlan(
          clicks: [Duration.zero, Duration(milliseconds: 500)],
          accents: {0},
          length: Duration(seconds: 1),
        ),
      );
      final data = ByteData.sublistView(bytes);
      expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
      expect(String.fromCharCodes(bytes.sublist(8, 12)), 'WAVE');
      expect(data.getUint16(22, Endian.little), 1);
      expect(data.getUint32(24, Endian.little), clickSampleRate);
      expect(bytes.length, 44 + clickSampleRate * 2);

      final accent = peak(data, Duration.zero);
      final beat = peak(data, const Duration(milliseconds: 500));
      expect(beat, greaterThan(5000));
      expect(accent, greaterThan(beat));
      // Silent between clicks.
      expect(sampleAt(data, const Duration(milliseconds: 250)), 0);
      expect(sampleAt(data, const Duration(milliseconds: 750)), 0);
    });
  });
}
