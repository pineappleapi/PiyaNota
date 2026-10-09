import 'dart:ui' show Size;

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/score_timeline.dart';
import 'package:piyanota_application/models/voice_part.dart';

import 'playback_fakes.dart';

void main() {
  group('skipTargets (⏮/⏭ rule)', () {
    test('no pickup: ⏮ is bar 1, ⏭ is the last bar', () {
      final targets = skipTargets(testTiming());
      expect(targets.back, const Duration(milliseconds: 500));
      expect(targets.forward, const Duration(milliseconds: 3500));
    });

    final withPickup = [
      ev(0, 50, 100, bar: 0),
      ev(400, 80, 100, bar: 1),
      ev(900, 120, 100, bar: 1),
      ev(1400, 200, 100, bar: 2),
    ];

    test('pickup with the flag on: ⏮ is t = 0', () {
      expect(skipTargets(withPickup, includePickup: true).back, Duration.zero);
    });

    test('pickup with the flag off: ⏮ is bar 1', () {
      expect(
        skipTargets(withPickup, includePickup: false).back,
        const Duration(milliseconds: 400),
      );
    });

    test('the default follows kSkipBackIncludesPickup', () {
      expect(
        skipTargets(withPickup).back,
        skipTargets(withPickup, includePickup: kSkipBackIncludesPickup).back,
      );
    });

    test('earliest event of the last bar wins, in any order', () {
      final events = [
        ev(2000, 300, 100, bar: 4),
        ev(1800, 280, 400, bar: 4),
        ev(500, 50, 100, bar: 1),
      ];
      expect(skipTargets(events).forward, const Duration(milliseconds: 1800));
    });

    test('no bar numbers: ⏮ is 0, ⏭ the last onset', () {
      final targets = skipTargets([ev(300, 1, 1), ev(2600, 2, 1)]);
      expect(targets.back, Duration.zero);
      expect(targets.forward, const Duration(milliseconds: 2600));
    });

    test('some bars null: they are ignored for bar targets', () {
      final targets = skipTargets([
        ev(100, 1, 1),
        ev(700, 2, 1, bar: 1),
        ev(9000, 3, 1),
        ev(1500, 4, 1, bar: 2),
      ]);
      expect(targets.back, const Duration(milliseconds: 700));
      expect(targets.forward, const Duration(milliseconds: 1500));
    });

    test('no events: ⏭ is left to the caller', () {
      final targets = skipTargets(const []);
      expect(targets.back, Duration.zero);
      expect(targets.forward, isNull);
    });
  });

  group('parsing', () {
    test('voice names are case-insensitive', () {
      expect(parseVoicePart('Soprano'), VoicePart.soprano);
      expect(parseVoicePart('ALTO'), VoicePart.alto);
      expect(parseVoicePart(' tenor '), VoicePart.tenor);
      expect(parseVoicePart('baritone'), isNull);
      expect(parseVoicePart(3), isNull);
    });

    test('timing file: list or {events}, bad entries skipped, sorted', () {
      final raw = [
        {'timestampMs': 900, 'pageIndex': 0, 'x': 5, 'y': 5, 'bar': 2},
        {'timestampMs': 'x', 'pageIndex': 0, 'x': 5, 'y': 5},
        {'timestampMs': 100, 'pageIndex': -1, 'x': 5, 'y': 5},
        {'timestampMs': 100, 'pageIndex': 0, 'x': 7, 'y': 9, 'bar': 0},
      ];
      for (final json in [
        raw,
        {'events': raw},
      ]) {
        final events = parseTimingEvents(json);
        expect(events.map((e) => e.timestampMs), [100, 900]);
        expect(events.first.bar, 0);
      }
      expect(() => parseTimingEvents({'nope': 1}), throwsFormatException);
    });

    test('a system box needs both edges, bottom below top', () {
      final event = TimingEvent.tryParse({
        'timestampMs': 0,
        'pageIndex': 0,
        'x': 1,
        'y': 1,
        'systemTopY': 50,
        'systemBottomY': 40,
      })!;
      expect(event.systemTopY, isNull);
      expect(event.systemBottomY, isNull);
    });

    test('result: missing review means review needed; tracks by voice', () {
      final result = ScoreResult.fromJson({
        'scoreId': 7,
        'audioTracks': {
          'SOPRANO': 'https://cdn/s.mp3',
          'Alto': '',
          'tenor': 'https://cdn/t.mp3',
        },
        'scoreImages': ['https://cdn/p1.png'],
        'scoreImageSizes': [
          {'width': 1300, 'height': 1575},
        ],
      });
      expect(result.audioTracks.keys, {VoicePart.soprano, VoicePart.tenor});
      expect(result.review.reviewNeeded, isTrue);
      expect(result.pageSizeAt(0), const Size(1300, 1575));
      expect(result.pageSizeAt(1), isNull);
      expect(
        () => ScoreResult.fromJson({'scoreId': 7, 'audioTracks': {}}),
        throwsFormatException,
      );
    });

    test('an explicit reviewNeeded false is respected', () {
      final review = ReviewSummary.fromJson({'reviewNeeded': false});
      expect(review.reviewNeeded, isFalse);
    });
  });

  group('ScoreTimeline', () {
    test('uses the given system box when present', () {
      final position = ScoreTimeline(testTiming())
          .positionAt(const Duration(milliseconds: 500))!;
      expect(position.systemIndex, 0);
      expect(position.top, 60);
      expect(position.bottom, 500);
      expect(position.x, 100);
    });

    test('interpolates x toward the next onset on the same system', () {
      final timeline = ScoreTimeline(testTiming());
      expect(
        timeline.positionAt(const Duration(milliseconds: 1000))!.x,
        closeTo(200, 1e-9),
      );
      // 2.5 s → 3.5 s crosses to system 1: no sliding back across the page.
      final beforeBreak = timeline.positionAt(
        const Duration(milliseconds: 3000),
      )!;
      expect(beforeBreak.x, 600);
      expect(beforeBreak.systemIndex, 0);
      final after = timeline.positionAt(const Duration(milliseconds: 3600))!;
      expect(after.systemIndex, 1);
      expect(after.top, 760);
    });

    test('before the first onset it waits there; after the last it stays', () {
      final timeline = ScoreTimeline(testTiming());
      expect(timeline.positionAt(Duration.zero)!.x, 100);
      expect(timeline.positionAt(const Duration(seconds: 60))!.x, 400);
    });

    test('derives systems and band from x jumps and y spread', () {
      // No systemIndex/systemTopY: two voices per onset, 100 px apart.
      final events = [
        for (final (ms, x, base) in [
          (0, 100.0, 200.0),
          (500, 800.0, 200.0),
          (1000, 120.0, 700.0),
        ]) ...[
          ev(ms, x, base, voice: VoicePart.soprano),
          ev(ms, x, base + 100, voice: VoicePart.bass),
        ],
      ];
      final timeline = ScoreTimeline(events);
      final first = timeline.positionAt(Duration.zero)!;
      expect(first.systemIndex, 0);
      expect(first.top, 175); // 200 - 0.25 * 100
      expect(first.bottom, 325);
      final second = timeline.positionAt(const Duration(milliseconds: 1000))!;
      expect(second.systemIndex, 1);
      expect(second.top, 675);
    });

    test('chord notes sharing a timestamp form one onset', () {
      final timeline = ScoreTimeline([
        ev(0, 100, 10, voice: VoicePart.soprano),
        ev(0, 110, 20, voice: VoicePart.alto),
        ev(1000, 300, 10, voice: VoicePart.soprano),
      ]);
      expect(timeline.positionAt(Duration.zero)!.x, 105);
      expect(
        timeline.positionAt(const Duration(milliseconds: 500))!.x,
        closeTo(202.5, 1e-9),
      );
    });

    test('empty timeline has no position', () {
      expect(ScoreTimeline.empty.positionAt(Duration.zero), isNull);
      expect(ScoreTimeline.empty.isEmpty, isTrue);
    });
  });
}
