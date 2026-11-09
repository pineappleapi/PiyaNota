import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/playback_messages.dart';

import 'playback_fakes.dart';

const _notice =
    'PiyaNota’s conversion may contain errors, so check the playback '
    'against your original score before relying on it.';

String _prompt(String voice, String pages) =>
    'Voice $voice could not be read. Do you want to continue with playback '
    'anyway? It is recommended to retake a clearer picture of page $pages of '
    'the score to be more sure of the output';

ReviewSummary _review(List<Map<String, Object?>> items) =>
    ReviewSummary.fromJson({'reviewNeeded': false, 'items': items});

Map<String, Object?> _item(String voice, {List<int>? pages}) => {
  'code': 'voice_unreadable',
  'voice': voice,
  'pageIndex': 1,
  'systemIndex': 0,
  'bar': 3,
  'pages': ?pages,
};

PlaybackHarness _harness({ReviewSummary? review, int pages = 1}) =>
    PlaybackHarness(
      ScriptedScoreResultApi([
        testResult(review: review, reviewNeeded: false, pages: pages),
      ], timing: testTiming()),
    );

final _noticeFinder = find.byKey(const ValueKey('accuracy-notice'));
final _promptFinder = find.byKey(const ValueKey('voice-unreadable-prompt'));

void main() {
  group('ReviewSummary voice flags', () {
    test('reads voice_unreadable items, 1-based pages as sent', () {
      final r = _review([
        _item('tenor', pages: [2, 3]),
        {'code': 'meter_guess', 'voice': 'alto'},
        _item('tenor', pages: [3, 4]),
      ]);
      expect(r.voiceFlags.map((f) => f.voice), [VoicePart.tenor]);
      expect(r.voiceFlags.single.pages, [2, 3, 4]);
    });

    test('a missing pages field means all pages (empty list)', () {
      expect(_review([_item('bass')]).voiceFlags.single.pages, isEmpty);
    });

    test('no items, bad items and no review block give no flags', () {
      expect(_review(const []).voiceFlags, isEmpty);
      expect(_review([_item('flute')]).voiceFlags, isEmpty);
      expect(ReviewSummary.fromJson(null).voiceFlags, isEmpty);
    });
  });

  group('general notice', () {
    testWidgets('shows the verbatim text once and can be dismissed', (
      tester,
    ) async {
      await pumpPlayback(tester, _harness());
      expect(_noticeFinder, findsOneWidget);
      expect(find.text(_notice), findsOneWidget);
      await tester.tap(find.byTooltip(PlaybackMessages.dismissNotice));
      await tester.pump();
      expect(_noticeFinder, findsNothing);
      await tester.pump(const Duration(seconds: 1));
      expect(_noticeFinder, findsNothing);
    });
  });

  group('voice prompt', () {
    testWidgets('no review items: no prompt', (tester) async {
      await pumpPlayback(tester, _harness());
      expect(_promptFinder, findsNothing);
    });

    testWidgets('names the voice and the 1-based page as sent', (tester) async {
      final review = _review([
        _item('tenor', pages: [2]),
      ]);
      await pumpPlayback(tester, _harness(review: review, pages: 3));
      expect(_promptFinder, findsOneWidget);
      expect(find.text(_prompt('Tenor', '2')), findsOneWidget);
      expect(find.text(PlaybackMessages.promptContinue), findsOneWidget);
      expect(find.text(PlaybackMessages.promptRetake), findsOneWidget);
    });

    testWidgets('no pages field: all pages are named', (tester) async {
      await pumpPlayback(
        tester,
        _harness(review: _review([_item('tenor')]), pages: 3),
      );
      expect(find.text(_prompt('Tenor', '1, 2 and 3')), findsOneWidget);
    });

    testWidgets('continue closes it and playback stays', (tester) async {
      await pumpPlayback(
        tester,
        _harness(
          review: _review([
            _item('tenor', pages: [1]),
          ]),
        ),
      );
      await tester.tap(find.text(PlaybackMessages.promptContinue));
      await settle(tester);
      expect(_promptFinder, findsNothing);
      expect(find.byKey(const ValueKey('score-scroll')), findsOneWidget);
    });

    testWidgets('retake goes to the whole-score retake for this job', (
      tester,
    ) async {
      await pumpPlayback(
        tester,
        _harness(
          review: _review([
            _item('tenor', pages: [1]),
          ]),
        ),
      );
      await tester.tap(find.text(PlaybackMessages.promptRetake));
      await settle(tester);
      await settle(tester);
      expect(
        find.text('ROUTE:whole-retake $kJobId $kTitle 90 42'),
        findsOneWidget,
      );
    });
  });

  group('bar-step line on screen', () {
    testWidgets('band holds inside a bar and jumps at the next bar', (
      tester,
    ) async {
      await pumpPlayback(tester, _harness());
      double left() =>
          tester.getRect(find.byKey(const ValueKey('playback-band'))).left;
      await tester.tap(find.byKey(const ValueKey('play-pause')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 900)); // bar 1, 2nd onset
      final first = left();
      await tester.pump(const Duration(milliseconds: 1000)); // 1.9 s, bar 1
      expect(left(), first);
      await tester.pump(const Duration(milliseconds: 800)); // 2.7 s, bar 2
      expect(left(), isNot(first));
    });
  });
}
