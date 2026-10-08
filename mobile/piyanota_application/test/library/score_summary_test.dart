import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/library_entry.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';

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

    test('falls back to lastProcessedAt when lastAccessedAt is unusable', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 7,
        'lastAccessedAt': 'yesterday',
        'lastProcessedAt': '2026-09-01T00:00:00Z',
      });
      expect(score.lastActivityAt, DateTime.utc(2026, 9, 1));
    });

    test('reads composer and pageCount as contract fields', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 552,
        'title': 'Bayan Ko',
        'lastAccessedAt': '2026-09-03T14:22:00Z',
        'composer': 'Constancio de Guzman',
        'pageCount': 4,
        'thumbnailUrl': 'https://cdn.piyanota.app/thumbs/552.png',
      });
      expect(score.composer, 'Constancio de Guzman');
      expect(score.pageCount, 4);
      expect(score.thumbnailUrl, 'https://cdn.piyanota.app/thumbs/552.png');
    });

    test('drops missing, blank or mistyped fields instead of rejecting', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 7,
        'title': '   ',
        'lastAccessedAt': 'yesterday',
        'thumbnailUrl': 42,
        'composer': '',
        'pageCount': '14',
      });
      expect(score.title, isNull);
      expect(score.lastActivityAt, isNull);
      expect(score.thumbnailUrl, isNull);
      expect(score.composer, isNull);
      expect(score.pageCount, isNull);
    });

    test('a non-string title or zero pageCount is dropped', () {
      final score = ScoreSummary.fromJson({
        'scoreId': 7,
        'title': 12,
        'pageCount': 0,
      });
      expect(score.title, isNull);
      expect(score.pageCount, isNull);
    });

    for (final entry in <String, Map<String, dynamic>>{
      'missing scoreId': {'title': 'x', 'lastAccessedAt': '2026-10-01'},
      'string scoreId': {'scoreId': '7', 'title': 'x'},
      'null scoreId': {'scoreId': null, 'title': 'x'},
      'zero scoreId': {'scoreId': 0, 'title': 'x'},
    }.entries) {
      test('rejects ${entry.key}', () {
        expect(() => ScoreSummary.fromJson(entry.value), throwsFormatException);
      });
    }
  });

  group('buildLibraryEntries: sort by last opened', () {
    test('newest first regardless of input order; undated last by title', () {
      final entries = buildLibraryEntries([
        ScoreSummary(
          scoreId: 1,
          title: 'Old',
          lastActivityAt: DateTime.utc(2026, 9, 1),
        ),
        const ScoreSummary(scoreId: 2, title: 'Zebra'),
        ScoreSummary(
          scoreId: 3,
          title: 'New',
          lastActivityAt: DateTime.utc(2026, 10, 3),
        ),
        const ScoreSummary(scoreId: 4, title: 'apple'),
        ScoreSummary(
          scoreId: 5,
          title: 'Mid',
          lastActivityAt: DateTime.utc(2026, 9, 20),
        ),
      ]);
      expect(entries.map((e) => e.scoreId), [3, 5, 1, 4, 2]);
    });
  });

  group('buildLibraryEntries: untitled numbering', () {
    test('untitled entries are numbered by scoreId, not display order', () {
      final entries = buildLibraryEntries([
        ScoreSummary(scoreId: 1, lastActivityAt: DateTime.utc(2026, 9, 1)),
        ScoreSummary(
          scoreId: 2,
          title: 'Paraiso',
          lastActivityAt: DateTime.utc(2026, 9, 2),
        ),
        ScoreSummary(scoreId: 3, lastActivityAt: DateTime.utc(2026, 10, 1)),
        const ScoreSummary(scoreId: 4),
      ]);
      expect(entries.map((e) => e.scoreId), [3, 2, 1, 4]);
      expect(entries.map((e) => e.displayTitle), [
        'New Score (1)',
        'Paraiso',
        'New Score',
        'New Score (2)',
      ]);
    });

    test('opening a score never renumbers any untitled row', () {
      final scores = [
        ScoreSummary(scoreId: 1, lastActivityAt: DateTime.utc(2026, 9, 1)),
        ScoreSummary(scoreId: 2, lastActivityAt: DateTime.utc(2026, 9, 2)),
        ScoreSummary(scoreId: 3, lastActivityAt: DateTime.utc(2026, 9, 3)),
      ];
      Map<int, String> labels(List<ScoreSummary> list) => {
        for (final e in buildLibraryEntries(list)) e.scoreId: e.displayTitle,
      };
      final before = labels(scores);
      // Score 1 is opened and jumps from last to first.
      final after = labels([
        scores[0].copyWith(lastActivityAt: DateTime.utc(2026, 10, 8)),
        scores[1],
        scores[2],
      ]);
      expect(after, before);
      expect(before, {1: 'New Score', 2: 'New Score (1)', 3: 'New Score (2)'});
    });

    test('identical real titles are shown as they are', () {
      final entries = buildLibraryEntries([
        const ScoreSummary(scoreId: 1, title: 'Paraiso'),
        const ScoreSummary(scoreId: 2, title: 'Paraiso'),
      ]);
      expect(entries.map((e) => e.displayTitle), ['Paraiso', 'Paraiso']);
    });

    test('a single untitled entry is plain "New Score"', () {
      final entries = buildLibraryEntries([const ScoreSummary(scoreId: 1)]);
      expect(entries.single.displayTitle, 'New Score');
    });

    test('a real title "New Score" joins the numbered sequence', () {
      final entries = buildLibraryEntries([
        ScoreSummary(
          scoreId: 1,
          title: 'New Score',
          lastActivityAt: DateTime.utc(2026, 9, 1),
        ),
        ScoreSummary(scoreId: 2, lastActivityAt: DateTime.utc(2026, 10, 1)),
      ]);
      // Score 1 (the literal title) was created first, so it keeps the
      // plain label even though score 2 sorts above it.
      expect(entries.map((e) => e.scoreId), [2, 1]);
      expect(entries.map((e) => e.displayTitle), [
        'New Score (1)',
        'New Score',
      ]);
    });

    test('generated labels skip a real title that already uses them', () {
      final entries = buildLibraryEntries([
        ScoreSummary(scoreId: 1, lastActivityAt: DateTime.utc(2026, 10, 3)),
        ScoreSummary(scoreId: 2, lastActivityAt: DateTime.utc(2026, 10, 2)),
        // Sorts last, but its title is reserved before numbering starts.
        ScoreSummary(
          scoreId: 3,
          title: 'new score (1)',
          lastActivityAt: DateTime.utc(2026, 9, 1),
        ),
      ]);
      expect(entries.map((e) => e.displayTitle), [
        'New Score',
        'New Score (2)',
        'new score (1)',
      ]);
    });
  });

  group('filterLibraryEntries (title, composer, date)', () {
    final entries = buildLibraryEntries([
      ScoreSummary(
        scoreId: 1,
        title: 'Bahay Kubo',
        composer: 'A.O. Veneracion',
        lastActivityAt: DateTime(2026, 9, 21, 12),
      ),
      ScoreSummary(
        scoreId: 2,
        title: 'Paraiso',
        composer: 'Ryan Cayabyab',
        lastActivityAt: DateTime(2026, 10, 3, 12),
      ),
      ScoreSummary(scoreId: 3, lastActivityAt: DateTime(2025, 1, 5, 12)),
    ]);

    List<int> ids(String q) =>
        filterLibraryEntries(entries, q).map((e) => e.scoreId).toList();

    test('blank query returns everything, newest first', () {
      expect(ids('  '), [2, 1, 3]);
    });

    test('matches title case-insensitively and partially', () {
      expect(ids('AHAY k'), [1]);
      expect(ids('rai'), [2]);
    });

    test('matches composer', () {
      expect(ids('cayab'), [2]);
      expect(ids('veneracion'), [1]);
    });

    test('matches the displayed date', () {
      expect(ids('oct'), [2]);
      expect(ids('oct 3'), [2]);
      expect(ids('2026'), [2, 1]);
      expect(ids('sep 21, 2026'), [1]);
    });

    test('matches the display title of an untitled entry', () {
      expect(ids('new score'), [3]);
    });

    test('no match is empty', () {
      expect(ids('zzz'), isEmpty);
    });
  });

  group('LibraryMessages.cardSubtitle', () {
    test('leads with the date; extras only when present', () {
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

    test('no stray separator when parts are missing', () {
      expect(
        LibraryMessages.cardSubtitle(
          const ScoreSummary(scoreId: 1, composer: 'Ryan Cayabyab'),
        ),
        'Ryan Cayabyab',
      );
      expect(
        LibraryMessages.cardSubtitle(
          const ScoreSummary(scoreId: 1, pageCount: 3),
        ),
        '3 pages',
      );
      expect(
        LibraryMessages.cardSubtitle(const ScoreSummary(scoreId: 1)),
        isEmpty,
      );
    });
  });
}
