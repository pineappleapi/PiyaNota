import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/services/metronome_click.dart';

import 'playback_fakes.dart';

List<int> _ms(ClickPlan plan) => [
  for (final click in plan.clicks) click.inMilliseconds,
];

TimingEvent _at(int ms, int? bar) => ev(ms, 0, 0, bar: bar);

const _d = ClickLevel.downbeat;
const _s = ClickLevel.secondary;
const _b = ClickLevel.beat;
const _u = ClickLevel.subdivision;

/// At this rendered tempo one tick is exactly 1 ms (60e6 / (480 x 125)
/// us), so expected times read as ticks.
const _tickMsTempo = 125;

/// A measure table from (numerator, denominator) per bar, tiling from
/// tick 0. [pickup] makes bar 0 a pickup of that many ticks; [last]
/// shortens the final bar; [sources] overrides meterSource per index.
List<BarInfo> _table(
  List<(int, int)?> meters, {
  int? pickup,
  int? last,
  Map<int, MeterSource> sources = const {},
}) {
  final bars = <BarInfo>[];
  var tick = 0;
  for (var i = 0; i < meters.length; i++) {
    final meter = meters[i];
    final full = meter == null ? 1920 : meter.$1 * 1920 ~/ meter.$2;
    final isPickup = pickup != null && i == 0;
    final dur = isPickup
        ? pickup
        : (i == meters.length - 1 && last != null ? last : full);
    bars.add(
      BarInfo(
        bar: pickup == null ? i + 1 : i,
        startTick: tick,
        durTicks: dur,
        numerator: meter?.$1,
        denominator: meter?.$2,
        meterSource:
            sources[i] ??
            (meter == null ? MeterSource.unknown : MeterSource.detected),
        pickup: isPickup,
      ),
    );
    tick += dur;
  }
  return bars;
}

/// (ms, level) of every click, with one tick = 1 ms.
List<(int, ClickLevel)> _plan(List<BarInfo> bars, {int chosenBpm = 90}) {
  final plan = planClicks(
    bars: bars,
    events: const [],
    tempoBpm: _tickMsTempo,
    chosenBpm: chosenBpm,
    length: const Duration(minutes: 1),
  );
  return [
    for (var i = 0; i < plan.clicks.length; i++)
      (plan.clicks[i].inMilliseconds, plan.levels[i]),
  ];
}

List<(int, ClickLevel)> _one(int numerator, int denominator, {int bpm = 90}) =>
    _plan(_table([(numerator, denominator)]), chosenBpm: bpm);

void main() {
  group('planClicks: simple meters click every unit', () {
    test('2/4', () => expect(_one(2, 4), [(0, _d), (480, _b)]));
    test('3/4', () => expect(_one(3, 4), [(0, _d), (480, _b), (960, _b)]));
    test('4/4: beat 3 is secondary', () {
      expect(_one(4, 4), [(0, _d), (480, _b), (960, _s), (1440, _b)]);
    });
    test('2/2 clicks half notes', () {
      expect(_one(2, 2), [(0, _d), (960, _b)]);
    });
    test('3/2', () => expect(_one(3, 2), [(0, _d), (960, _b), (1920, _b)]));
    test('3/8 clicks eighths', () {
      expect(_one(3, 8), [(0, _d), (240, _b), (480, _b)]);
    });
    test('5/4 is 3+2', () {
      expect(_one(5, 4), [
        (0, _d),
        (480, _b),
        (960, _b),
        (1440, _s),
        (1920, _b),
      ]);
    });
    test('5/8 is 3+2', () {
      expect(_one(5, 8), [(0, _d), (240, _b), (480, _b), (720, _s), (960, _b)]);
    });
    test('7/8 is 4+3', () {
      expect(_one(7, 8), [
        (0, _d),
        (240, _b),
        (480, _b),
        (720, _b),
        (960, _s),
        (1200, _b),
        (1440, _b),
      ]);
    });
    test('8/8 stresses every other eighth (MuseScore stressEvery)', () {
      expect(_one(8, 8), [
        (0, _d),
        (240, _b),
        (480, _s),
        (720, _b),
        (960, _s),
        (1200, _b),
        (1440, _s),
        (1680, _b),
      ]);
    });
    test('3/4 never subdivides, however slow', () {
      expect(_one(3, 4, bpm: 30), [(0, _d), (480, _b), (960, _b)]);
    });
  });

  group('planClicks: compound meters', () {
    test('6/8 at quarter = 90 (beat 60/min): beats only', () {
      expect(_one(6, 8), [(0, _d), (720, _b)]);
    });
    test('6/8 at quarter = 89 (beat 59.3/min): every eighth', () {
      expect(_one(6, 8, bpm: 89), [
        (0, _d),
        (240, _u),
        (480, _u),
        (720, _b),
        (960, _u),
        (1200, _u),
      ]);
    });
    test('9/8 at quarter = 60 (beat 40/min): D u u b u u b u u', () {
      expect(_one(9, 8, bpm: 60), [
        (0, _d),
        (240, _u),
        (480, _u),
        (720, _b),
        (960, _u),
        (1200, _u),
        (1440, _b),
        (1680, _u),
        (1920, _u),
      ]);
    });
    test('9/8 at 120', () {
      expect(_one(9, 8, bpm: 120), [(0, _d), (720, _b), (1440, _b)]);
    });
    test('12/8 at 120: beat 3 is secondary', () {
      expect(_one(12, 8, bpm: 120), [
        (0, _d),
        (720, _b),
        (1440, _s),
        (2160, _b),
      ]);
    });
    test('12/8 slow: subdivisions keep the beat accents', () {
      final clicks = _one(12, 8, bpm: 60);
      expect(clicks, hasLength(12));
      expect(
        [for (final (_, level) in clicks) level],
        [
          _d, _u, _u, _b, _u, _u, _s, _u, _u, _b, _u, _u, //
        ],
      );
    });
    test('6/4: beat is a dotted half, 180 is the threshold', () {
      expect(_one(6, 4, bpm: 180), [(0, _d), (1440, _b)]);
      expect(_one(6, 4, bpm: 179), [
        (0, _d),
        (480, _u),
        (960, _u),
        (1440, _b),
        (1920, _u),
        (2400, _u),
      ]);
    });
    test('15/8 at 120: five beats, 3+2', () {
      expect(_one(15, 8, bpm: 120), [
        (0, _d),
        (720, _b),
        (1440, _b),
        (2160, _s),
        (2880, _b),
      ]);
    });
  });

  group('planClicks: pickups and the final bar', () {
    test('a one-quarter pickup in 3/4 is beat 3, never a downbeat', () {
      expect(_plan(_table([(3, 4), (3, 4)], pickup: 480)), [
        (0, _b),
        (480, _d),
        (960, _b),
        (1440, _b),
      ]);
    });
    test('a two-quarter pickup in 4/4 keeps beat 3 secondary', () {
      expect(_plan(_table([(4, 4), (4, 4)], pickup: 960)), [
        (0, _s),
        (480, _b),
        (960, _d),
        (1440, _b),
        (1920, _s),
        (2400, _b),
      ]);
    });
    test('a dotted-quarter pickup in 6/8 is beat 2', () {
      expect(_plan(_table([(6, 8), (6, 8)], pickup: 720)), [
        (0, _b),
        (720, _d),
        (1440, _b),
      ]);
    });
    test('an eighth pickup in fast 6/8 is off the beat: no click', () {
      expect(_plan(_table([(6, 8), (6, 8)], pickup: 240)), [
        (240, _d),
        (960, _b),
      ]);
    });
    test('an eighth pickup in slow 6/8 is a subdivision', () {
      expect(_plan(_table([(6, 8), (6, 8)], pickup: 240), chosenBpm: 60), [
        (0, _u),
        (240, _d),
        (480, _u),
        (720, _u),
        (960, _b),
        (1200, _u),
        (1440, _u),
      ]);
    });
    test('a short final bar in 6/8 stops at its end, fast and slow', () {
      final table = _table([(6, 8), (6, 8)], last: 720);
      expect(_plan(table), [(0, _d), (720, _b), (1440, _d)]);
      expect(_plan(table, chosenBpm: 60).where((c) => c.$1 >= 1440), [
        (1440, _d),
        (1680, _u),
        (1920, _u),
      ]);
    });
    test('a pickup and the short final bar that completes it', () {
      expect(_plan(_table([(3, 4), (3, 4), (3, 4)], pickup: 480, last: 960)), [
        (0, _b),
        (480, _d),
        (960, _b),
        (1440, _b),
        (1920, _d),
        (2400, _b),
      ]);
    });
    test('a short final bar stops at its end', () {
      expect(_plan(_table([(4, 4), (4, 4)], last: 960)), [
        (0, _d),
        (480, _b),
        (960, _s),
        (1440, _b),
        (1920, _d),
        (2400, _b),
      ]);
    });
  });

  group('planClicks: meter changes', () {
    test('3/4 -> 5/8 -> 2/4 -> 6/8 -> 4/4, each from its own barline', () {
      final clicks = _plan(_table([(3, 4), (5, 8), (2, 4), (6, 8), (4, 4)]));
      expect(clicks, [
        // 3/4 at 0
        (0, _d), (480, _b), (960, _b),
        // 5/8 at 1440
        (1440, _d), (1680, _b), (1920, _b), (2160, _s), (2400, _b),
        // 2/4 at 2640
        (2640, _d), (3120, _b),
        // 6/8 at 3600 (beat 60/min at quarter = 90)
        (3600, _d), (4320, _b),
        // 4/4 at 5040
        (5040, _d), (5520, _b), (6000, _s), (6480, _b),
      ]);
    });
    test('alternating 2/4 and 3/8 every bar', () {
      expect(_plan(_table([(2, 4), (3, 8), (2, 4), (3, 8)])), [
        (0, _d),
        (480, _b),
        (960, _d),
        (1200, _b),
        (1440, _b),
        (1680, _d),
        (2160, _b),
        (2640, _d),
        (2880, _b),
        (3120, _b),
      ]);
    });
    test('only the slow compound bar subdivides', () {
      expect(_plan(_table([(2, 4), (6, 8)]), chosenBpm: 80), [
        (0, _d),
        (480, _b),
        (960, _d),
        (1200, _u),
        (1440, _u),
        (1680, _b),
        (1920, _u),
        (2160, _u),
      ]);
    });
    test('the demo score: pickup, 3/4, 5/8, 2/4, 6/8, 4/4', () {
      final clicks = _plan(
        _table([
          (3, 4),
          (3, 4),
          (3, 4),
          (5, 8),
          (2, 4),
          (6, 8),
          (6, 8),
          (4, 4),
          (4, 4),
        ], pickup: 480),
      );
      final downbeats = [
        for (final (ms, level) in clicks)
          if (level == _d) ms,
      ];
      expect(downbeats, [480, 1920, 3360, 4560, 5520, 6960, 8400, 10320]);
      expect(clicks.first, (0, _b));
    });
  });

  group('planClicks: unknown and default meters', () {
    test('inherited is trusted like detected', () {
      expect(
        _plan(_table([(3, 4), (3, 4)], sources: {1: MeterSource.inherited})),
        [(0, _d), (480, _b), (960, _b), (1440, _d), (1920, _b), (2400, _b)],
      );
    });
    test('default and unknown borrow the last trusted meter', () {
      final bars = _table(
        [(3, 4), (4, 4), null],
        sources: {1: MeterSource.assumed},
      );
      // Bar 2 is "default 4/4" but is played as the 3/4 before it; bar 3
      // (unknown, no meter, 1920 ticks) repeats the 3/4 pattern.
      expect(bars[1].durTicks, 1920);
      expect(_plan(bars), [
        (0, _d),
        (480, _b),
        (960, _b),
        (1440, _d),
        (1920, _b),
        (2400, _b),
        (2880, _d),
        (3360, _d),
        (3840, _b),
        (4320, _b),
        (4800, _d),
      ]);
    });
    test('none trusted yet: a quarter grid, first click accented only', () {
      expect(
        _plan(_table([(4, 4), (2, 4)], sources: {0: MeterSource.assumed})),
        [(0, _d), (480, _b), (960, _b), (1440, _b), (1920, _d), (2400, _b)],
      );
    });
    test('an unknown pickup with no meter anywhere counts quarters back '
        'from its end', () {
      expect(_plan(_table([null, null], pickup: 720)), [
        (240, _b),
        (720, _d),
        (1200, _b),
        (1680, _b),
        (2160, _b),
      ]);
    });
    test('an unknown pickup takes the first trusted meter after it: a '
        'dotted-quarter pickup before 6/8 is beat 2', () {
      final table = _table([null, (6, 8)], pickup: 720);
      // Fast: one click on the dotted-quarter beat, none at 240.
      expect(_plan(table, chosenBpm: 240).where((c) => c.$1 < 720), [(0, _b)]);
      expect(_plan(table).take(3), [(0, _b), (720, _d), (1440, _b)]);
      // Slow: the 6/8 subdivisions, still no downbeat.
      expect(_plan(table, chosenBpm: 60).where((c) => c.$1 < 720), [
        (0, _b),
        (240, _u),
        (480, _u),
      ]);
    });
    test('a default-meter pickup also looks forward, past unknown bars', () {
      final table = _table(
        [(4, 4), null, (6, 8)],
        pickup: 720,
        sources: {0: MeterSource.assumed},
      );
      expect(resolveMeters(table).first.$2, (numerator: 6, denominator: 8));
    });
    test('an unknown pickup with nothing trusted after it takes the last '
        'one before it', () {
      const bars = [
        BarInfo(
          bar: 1,
          startTick: 0,
          durTicks: 1440,
          numerator: 3,
          denominator: 4,
          meterSource: MeterSource.detected,
        ),
        BarInfo(bar: 2, startTick: 1440, durTicks: 480, pickup: true),
        BarInfo(bar: 3, startTick: 1920, durTicks: 1440),
      ];
      expect(resolveMeters(bars)[1].$2, (numerator: 3, denominator: 4));
    });
  });

  group('planClicks: timing', () {
    test('ticks become ms at the rendered tempo', () {
      final plan = planClicks(
        bars: _table([(2, 4), (2, 4)]),
        events: const [],
        tempoBpm: 90,
        chosenBpm: 90,
        length: const Duration(seconds: 5),
      );
      // 480 ticks = 666.67 ms at 90.
      expect(_ms(plan), [0, 666, 1333, 2000]);
    });
    test('clicks at or past the end are dropped', () {
      final plan = planClicks(
        bars: _table([(4, 4)]),
        events: const [],
        tempoBpm: _tickMsTempo,
        chosenBpm: 90,
        length: const Duration(milliseconds: 960),
      );
      expect(_ms(plan), [0, 480]);
    });
    test('clicks within 5 ms merge, keeping the louder', () {
      final bars = [
        const BarInfo(
          bar: 1,
          startTick: 0,
          durTicks: 1440,
          numerator: 3,
          denominator: 4,
          meterSource: MeterSource.detected,
        ),
        const BarInfo(
          bar: 2,
          startTick: 963,
          durTicks: 480,
          numerator: 1,
          denominator: 4,
          meterSource: MeterSource.detected,
        ),
      ];
      expect(_plan(bars), [(0, _d), (480, _b), (960, _d)]);
    });
    test('no bars: falls back to the quarter grid', () {
      final plan = planClicks(
        bars: const [],
        events: [_at(0, null)],
        tempoBpm: 240,
        chosenBpm: 90,
        length: const Duration(seconds: 1),
      );
      expect(_ms(plan), [0, 250, 500, 750]);
    });
  });

  group('subdividedBars', () {
    final bars = _table([(3, 4), (6, 8), (12, 8), (6, 4), null]);
    test('crosses at the 60-a-minute beat tempo', () {
      // Bar 4 (unknown) plays as the 6/4 before it.
      expect(subdividedBars(bars, 90), {3, 4});
      expect(subdividedBars(bars, 89), {1, 2, 3, 4});
      expect(subdividedBars(bars, 180), isEmpty);
    });
    test('an unknown bar after a compound one follows it', () {
      final tail = _table([(6, 8), null]);
      expect(subdividedBars(tail, 60), {0, 1});
    });
  });

  group('planQuarterGrid (no bars table)', () {
    test('no bar numbers: quarters from t = 0, no accents', () {
      final plan = planQuarterGrid(
        events: [_at(0, null), _at(700, null)],
        tempoBpm: 90,
        length: const Duration(seconds: 3),
      );
      expect(_ms(plan), [0, 666, 1333, 2000, 2666]);
      expect(plan.downbeats, isEmpty);
      expect(plan.length, const Duration(seconds: 3));
    });

    test('anchored on the start of bar 1, accent on each bar start', () {
      final plan = planQuarterGrid(
        events: [_at(950, 1), _at(700, 1), _at(2700, 2), _at(3200, 2)],
        tempoBpm: 120,
        length: const Duration(seconds: 4),
      );
      expect(_ms(plan), [200, 700, 1200, 1700, 2200, 2700, 3200, 3700]);
      expect(plan.downbeats, {1, 5});
    });

    test('a pickup is counted in, but its bar is not accented', () {
      final plan = planQuarterGrid(
        events: [_at(0, 0), _at(500, 0), _at(1000, 1), _at(3000, 2)],
        tempoBpm: 120,
        length: const Duration(milliseconds: 3500),
      );
      expect(_ms(plan), [0, 500, 1000, 1500, 2000, 2500, 3000]);
      expect(plan.downbeats, {2, 6});
    });

    test('a bar start off the grid snaps to the nearest click', () {
      final plan = planQuarterGrid(
        events: [_at(0, 1), _at(2030, 2)],
        tempoBpm: 60,
        length: const Duration(seconds: 3),
      );
      expect(_ms(plan), [0, 1000, 2000]);
      expect(plan.downbeats, {0, 2});
    });

    test('a bar starting outside the clicks gets no accent', () {
      final early = planQuarterGrid(
        events: [_at(1500, 1), _at(100, 2)],
        tempoBpm: 60,
        length: const Duration(seconds: 3),
      );
      expect(_ms(early), [500, 1500, 2500]);
      expect(early.downbeats, {1});

      final past = planQuarterGrid(
        events: [_at(500, 1), _at(2900, 2)],
        tempoBpm: 60,
        length: const Duration(milliseconds: 2800),
      );
      expect(_ms(past), [500, 1500, 2500]);
      expect(past.downbeats, {0});
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
        final value = data.getInt16(44 + i * 2, Endian.little).abs();
        if (value > best) best = value;
      }
      return best;
    }

    test('mono 16-bit WAV of the plan length; levels loudest first', () {
      final bytes = renderClickWav(
        ClickPlan(
          clicks: const [
            Duration.zero,
            Duration(milliseconds: 250),
            Duration(milliseconds: 500),
            Duration(milliseconds: 750),
          ],
          levels: const [_d, _s, _b, _u],
          length: const Duration(seconds: 1),
        ),
      );
      final data = ByteData.sublistView(bytes);
      expect(String.fromCharCodes(bytes.sublist(0, 4)), 'RIFF');
      expect(String.fromCharCodes(bytes.sublist(8, 12)), 'WAVE');
      expect(data.getUint16(22, Endian.little), 1);
      expect(data.getUint32(24, Endian.little), clickSampleRate);
      expect(bytes.length, 44 + clickSampleRate * 2);

      final peaks = [
        for (final ms in [0, 250, 500, 750])
          peak(data, Duration(milliseconds: ms)),
      ];
      expect(peaks[3], greaterThan(3000));
      for (var i = 0; i < 3; i++) {
        expect(peaks[i], greaterThan(peaks[i + 1]), reason: 'level $i');
      }
      // Silent between clicks.
      expect(sampleAt(data, const Duration(milliseconds: 200)), 0);
      expect(sampleAt(data, const Duration(milliseconds: 950)), 0);
    });

    test('each level has its own pitch, highest for the downbeat', () {
      const at = [0, 250, 500, 750];
      final data = ByteData.sublistView(
        renderClickWav(
          ClickPlan(
            clicks: [for (final ms in at) Duration(milliseconds: ms)],
            levels: const [_d, _s, _b, _u],
            length: const Duration(seconds: 1),
          ),
        ),
      );
      // Sign changes over each burst's first 20 ms: 2 x Hz x 0.02 s.
      int crossings(int ms) {
        final start = ms * clickSampleRate ~/ 1000;
        final n = clickSampleRate ~/ 50;
        var count = 0;
        var last = 0;
        for (var i = start; i < start + n; i++) {
          final v = data.getInt16(44 + i * 2, Endian.little).sign;
          if (v == 0) continue;
          if (last != 0 && v != last) count++;
          last = v;
        }
        return count;
      }

      final counts = [for (final ms in at) crossings(ms)];
      for (var i = 0; i < 3; i++) {
        expect(counts[i], greaterThan(counts[i + 1]), reason: '$counts');
      }
      // Downbeat well clear of the secondary; secondary near the beat.
      expect(counts[0] - counts[1], greaterThan(15), reason: '$counts');
    });

    test('each burst fades to silence at its end: no step at the cut', () {
      final data = ByteData.sublistView(
        renderClickWav(
          ClickPlan(
            clicks: const [Duration.zero],
            levels: const [_d],
            length: const Duration(milliseconds: 100),
          ),
        ),
      );
      final last = (0.04 * clickSampleRate).round() - 1;
      expect(data.getInt16(44 + last * 2, Endian.little).abs(), lessThan(10));
    });
  });
}
