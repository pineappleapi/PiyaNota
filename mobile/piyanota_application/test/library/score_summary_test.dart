import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/state/score_library_providers.dart';

void main() {
  group('ScoreSummary.fromJson', () {
    test('prefers lastAccessedAt over lastProcessedAt', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 7,
        'title': 'Paraiso',
        'lastAccessedAt': '2026-10-01T00:00:00Z',
        'lastProcessedAt': '2026-09-01T00:00:00Z',
      });
      expect(score.lastActivityAt, DateTime.utc(2026, 10, 1));
    });

    test('drops mistyped optional fields instead of rejecting the entry', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 7,
        'title': 'Paraiso',
        'lastAccessedAt': '2026-10-01T00:00:00Z',
        'thumbnailUrl': 42,
        'composer': '',
        'pageCount': '14',
      });
      expect(score.thumbnailUrl, isNull);
      expect(score.composer, isNull);
      expect(score.pageCount, isNull);
    });

    for (final entry in <String, Map<String, dynamic>>{
      'missing scoreId': {'title': 'x', 'lastAccessedAt': '2026-10-01'},
      'string scoreId': {
        'scoreId': '7',
        'title': 'x',
        'lastAccessedAt': '2026-10-01',
      },
      'missing title': {'scoreId': 7, 'lastAccessedAt': '2026-10-01'},
      'missing timestamp': {'scoreId': 7, 'title': 'x'},
      'unparseable timestamp': {
        'scoreId': 7,
        'title': 'x',
        'lastAccessedAt': 'yesterday',
      },
    }.entries) {
      test('rejects ${entry.key}', () {
        expect(
          () => ScoreSummary.fromJson(entry.value),
          throwsFormatException,
        );
      });
    }
  });

  group('filterScoresByTitle (AC3)', () {
    final scores = [
      ScoreSummary(scoreId: 1, title: 'Bahay Kubo', lastActivityAt: DateTime(2026)),
      ScoreSummary(scoreId: 2, title: 'Paraiso', lastActivityAt: DateTime(2026)),
    ];

    test('blank query returns everything', () {
      expect(filterScoresByTitle(scores, '  '), scores);
    });

    test('matches case-insensitively and partially', () {
      expect(filterScoresByTitle(scores, 'AHAY k').map((s) => s.scoreId), [1]);
      expect(filterScoresByTitle(scores, 'rai').map((s) => s.scoreId), [2]);
      expect(filterScoresByTitle(scores, 'zzz'), isEmpty);
    });
  });

  group('LibraryMessages.cardSubtitle (AC2)', () {
    test('always leads with the date; extras only when present', () {
      final bare = ScoreSummary(
        scoreId: 1,
        title: 'x',
        lastActivityAt: DateTime(2026, 10, 3, 12),
      );
      final full = ScoreSummary(
        scoreId: 2,
        title: 'y',
        lastActivityAt: DateTime(2026, 9, 28, 12),
        composer: 'Ryan Cayabyab',
        pageCount: 1,
      );
      expect(LibraryMessages.cardSubtitle(bare), 'Oct 3, 2026');
      expect(
        LibraryMessages.cardSubtitle(full),
        'Sep 28, 2026 • Ryan Cayabyab • 1 page',
      );
    });
  });
}
