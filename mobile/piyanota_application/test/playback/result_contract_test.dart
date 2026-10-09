import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';

/// PIYA-103 AC9/AC10 (`mutedMeasures`, `failedVoices`) and PIYA-117 AC9
/// (`bars`), as the app reads them.
void main() {
  Map<String, dynamic> result({
    Map<String, Object?> tracks = const {
      'soprano': 'https://cdn.test/s.mp3',
      'alto': 'https://cdn.test/a.mp3',
      'tenor': 'https://cdn.test/t.mp3',
      'bass': 'https://cdn.test/b.mp3',
    },
    Object? failed,
    Object? muted,
  }) => {
    'scoreId': 1,
    'audioTracks': tracks,
    'scoreImages': <String>[],
    'failedVoices': ?failed,
    'mutedMeasures': ?muted,
  };

  group('failedVoices (PIYA-103 AC10, PIYA-216 AC5)', () {
    test('absent: nothing failed', () {
      expect(ScoreResult.fromJson(result()).failedVoices, isEmpty);
    });

    test('a declared voice is failed and its stray track is dropped', () {
      final r = ScoreResult.fromJson(result(failed: ['tenor']));
      expect(r.declaredFailedVoices, {VoicePart.tenor});
      expect(r.failedVoices, {VoicePart.tenor});
      expect(r.audioTracks.keys, isNot(contains(VoicePart.tenor)));
    });

    test('a voice missing from audioTracks counts as failed', () {
      final r = ScoreResult.fromJson(
        result(
          tracks: {
            'soprano': 'https://cdn.test/s.mp3',
            'alto': 'https://cdn.test/a.mp3',
            'tenor': 'https://cdn.test/t.mp3',
          },
        ),
      );
      expect(r.declaredFailedVoices, isEmpty);
      expect(r.failedVoices, {VoicePart.bass});
    });

    test('unknown names and a non-list are ignored', () {
      expect(
        ScoreResult.fromJson(result(failed: ['baritone', 3])).failedVoices,
        isEmpty,
      );
      expect(
        ScoreResult.fromJson(result(failed: 'bass')).failedVoices,
        isEmpty,
      );
    });

    test('every voice failed is no result at all', () {
      expect(
        () => ScoreResult.fromJson(
          result(failed: ['soprano', 'alto', 'tenor', 'bass']),
        ),
        throwsFormatException,
      );
    });
  });

  group('mutedMeasures (PIYA-103 AC9)', () {
    test('a bar-anchored and a page-anchored entry both parse', () {
      final r = ScoreResult.fromJson(
        result(
          muted: [
            {
              'voice': 'bass',
              'bar': 4,
              'pageIndex': 0,
              'systemIndex': 0,
              'startMs': 7000,
              'endMs': 8000,
              'reason': 'bar_overflow_clipped',
            },
            {'voice': 'alto', 'bar': null, 'pageIndex': 1, 'systemIndex': 2},
          ],
        ),
      );
      expect(r.mutedMeasures, hasLength(2));
      final bass = r.mutedMeasures.first;
      expect(bass.voice, VoicePart.bass);
      expect(bass.bar, 4);
      expect(bass.startMs, 7000);
      expect(bass.endMs, 8000);
      expect(bass.reason, 'bar_overflow_clipped');
      final alto = r.mutedMeasures.last;
      expect(alto.bar, isNull);
      expect(alto.pageIndex, 1);
      expect(alto.systemIndex, 2);
    });

    test('unnameable entries are dropped, not fatal', () {
      final r = ScoreResult.fromJson(
        result(
          muted: [
            {'bar': 2},
            {'voice': 'bass'},
            {'voice': 'bass', 'bar': -1},
            'nonsense',
            {'voice': 'Soprano', 'bar': 2},
          ],
        ),
      );
      expect(r.mutedMeasures.single.voice, VoicePart.soprano);
    });

    test('an entry for a failed voice is dropped', () {
      final r = ScoreResult.fromJson(
        result(
          failed: ['bass'],
          muted: [
            {'voice': 'bass', 'bar': 4},
          ],
        ),
      );
      expect(r.mutedMeasures, isEmpty);
    });
  });

  group('timing file bars (PIYA-117 AC9)', () {
    Map<String, Object?> bar(
      int n,
      int start,
      int dur, {
      Object? num = 4,
      Object? den = 4,
      Object? source = 'detected',
      bool pickup = false,
    }) => {
      'bar': n,
      'startTick': start,
      'durTicks': dur,
      'startMs': start,
      'durMs': dur,
      'numerator': num,
      'denominator': den,
      'meterSource': source,
      'pickup': pickup,
      'groups': null,
    };

    test('a bare event list has no measure table', () {
      final file = TimingFile.parse([
        {'timestampMs': 0, 'pageIndex': 0, 'x': 1, 'y': 2, 'voice': 'Bass'},
      ]);
      expect(file.events, hasLength(1));
      expect(file.bars, isEmpty);
    });

    test('a table is sorted by tick; pickup and sources parse', () {
      final file = TimingFile.parse({
        'events': <Object>[],
        'bars': [
          bar(1, 480, 1440, num: 3, source: 'inherited'),
          bar(0, 0, 480, num: 3, pickup: true),
          bar(2, 1920, 1920, source: 'default'),
          bar(3, 3840, 1920, source: 'something-new'),
        ],
      });
      expect(file.bars.map((b) => b.bar), [0, 1, 2, 3]);
      expect(file.bars.first.pickup, isTrue);
      expect(file.bars.map((b) => b.meterSource), [
        MeterSource.detected,
        MeterSource.inherited,
        MeterSource.assumed,
        MeterSource.unknown,
      ]);
      expect(file.bars.map((b) => b.meterSource.trusted), [
        true,
        true,
        false,
        false,
      ]);
    });

    test('a bad meter is unknown, a bad entry is dropped, the table '
        'survives', () {
      final file = TimingFile.parse({
        'events': <Object>[],
        'bars': [
          bar(1, 0, 1920, den: 3),
          bar(2, 1920, 1920, num: null),
          bar(3, -1, 1920),
          bar(4, 3840, 0),
          {'startTick': 0, 'durTicks': 10},
          bar(5, 3840, 1920),
        ],
      });
      expect(file.bars.map((b) => b.bar), [1, 2, 5]);
      expect(file.bars[0].hasMeter, isFalse);
      expect(file.bars[1].hasMeter, isFalse);
      expect(file.bars[2].hasMeter, isTrue);
    });

    test('a bars field that is not a list is no table, not an error', () {
      final file = TimingFile.parse({'events': <Object>[], 'bars': 'x'});
      expect(file.bars, isEmpty);
    });
  });
}
