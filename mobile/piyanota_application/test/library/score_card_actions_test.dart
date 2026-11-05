import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/library_entry.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';

void main() {
  testWidgets('pencil and trash: two >=48 dp targets, no overlap, no overflow '
      'at 320 dp and 2.0x text', (tester) async {
    tester.view.physicalSize = const Size(640, 1136);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
    var edits = 0;
    var deletes = 0;

    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: const TextScaler.linear(2.0),
          ),
          child: child!,
        ),
        home: Scaffold(
          body: ScoreCard(
            entry: LibraryEntry(
              score: ScoreSummary(
                scoreId: 1,
                title: 'Bituin Walang Ningning',
                lastActivityAt: DateTime(2026, 10, 3, 12),
                arranger: 'Robert Delgado',
                pageCount: 10,
              ),
              displayTitle: 'Bituin Walang Ningning',
            ),
            onTap: () {},
            onDelete: () => deletes++,
            onEdit: () => edits++,
          ),
        ),
      ),
    );
    expect(tester.takeException(), isNull);

    final edit = tester.getRect(find.byKey(const ValueKey('score-card-edit')));
    final del = tester.getRect(find.byKey(const ValueKey('score-card-delete')));
    for (final r in [edit, del]) {
      expect(r.width, greaterThanOrEqualTo(48));
      expect(r.height, greaterThanOrEqualTo(48));
    }
    expect(edit.overlaps(del), isFalse);
    expect(del.left - edit.right, greaterThan(0));

    await tester.tap(find.byIcon(Icons.edit_rounded));
    await tester.tap(find.byIcon(Icons.delete_rounded));
    expect([edits, deletes], [1, 1]);
  });
}
