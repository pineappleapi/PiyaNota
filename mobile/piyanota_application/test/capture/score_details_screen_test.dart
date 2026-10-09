import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/capture/capture_screen.dart';
import 'package:piyanota_application/screens/capture/score_details_screen.dart';

import 'capture_fakes.dart';

Finder get _titleField => find.byType(TextField).first;
Finder get _arrangerField => find.byType(TextField).at(1);

ElevatedButton _next(WidgetTester tester) => tester.widget<ElevatedButton>(
  find.ancestor(
    of: find.text(CaptureMessages.nextAddPages),
    matching: find.byType(ElevatedButton),
  ),
);

Future<void> _tapNext(WidgetTester tester) async {
  await tester.ensureVisible(find.text(CaptureMessages.nextAddPages));
  await tester.tap(find.text(CaptureMessages.nextAddPages));
  await tester.pumpAndSettle();
}

Future<void> _choose(WidgetTester tester, String tile, String option) async {
  final tileFinder = find.bySemanticsLabel(RegExp('^$tile: '));
  // Dismiss the keyboard first, as a user would; a focused field otherwise
  // scrolls itself back into view.
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  // The form is a lazy ListView: off-screen tiles aren't built yet.
  await tester.scrollUntilVisible(
    tileFinder,
    80,
    scrollable: find.byType(Scrollable).first,
  );
  // At large text the whole page scrolls, so the tile can be built yet
  // still off-screen.
  await tester.ensureVisible(tileFinder);
  await tester.pumpAndSettle();
  await tester.tap(tileFinder);
  await tester.pumpAndSettle();
  final optionFinder = find.bySemanticsLabel(option);
  await tester.ensureVisible(optionFinder);
  await tester.tap(optionFinder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('title is required, autofocused, and gates Next', (tester) async {
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    expect(find.text(CaptureMessages.detailsTitle), findsOneWidget);
    expect(tester.widget<TextField>(_titleField).autofocus, isTrue);
    expect(_next(tester).onPressed, isNull);

    await tester.enterText(_titleField, '   ');
    await tester.pump();
    expect(_next(tester).onPressed, isNull, reason: 'blank is not a title');

    await tester.enterText(_titleField, 'Ave Maria');
    await tester.pump();
    expect(_next(tester).onPressed, isNotNull);
  });

  testWidgets('title and arranger stop at 120 code points', (tester) async {
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    // Each "𝄞" is one code point but two UTF-16 units.
    await tester.enterText(_titleField, '𝄞' * 130);
    await tester.enterText(_arrangerField, 'a' * 130);
    await tester.pump();
    final title = tester.widget<TextField>(_titleField).controller!.text;
    final arranger = tester.widget<TextField>(_arrangerField).controller!.text;
    expect(ScoreDetails.codePointLength(title), ScoreDetails.maxTextLength);
    expect(arranger.length, ScoreDetails.maxTextLength);
  });

  test('CodePointLimitFormatter never splits a surrogate pair', () {
    const formatter = CodePointLimitFormatter(2);
    final out = formatter.formatEditUpdate(
      TextEditingValue.empty,
      const TextEditingValue(text: 'a𝄞b'),
    );
    expect(out.text, 'a𝄞');
  });

  testWidgets('answers reach Capture and survive coming back', (tester) async {
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    await tester.enterText(_titleField, '  Ave Maria ');
    await tester.enterText(_arrangerField, 'Schubert');
    await _choose(tester, CaptureMessages.keyTile, KeySignature.d.label);
    await _choose(
      tester,
      CaptureMessages.beatsTile,
      TimeSignature.threeFour.label,
    );
    expect(
      find.bySemanticsLabel(
        '${CaptureMessages.keyTile}: ${KeySignature.d.label}',
      ),
      findsOneWidget,
    );

    await tester.scrollUntilVisible(
      find.bySemanticsLabel(RegExp('^${CaptureMessages.speedTile}: ')),
      80,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.ensureVisible(
      find.bySemanticsLabel(RegExp('^${CaptureMessages.speedTile}: ')),
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.bySemanticsLabel(RegExp('^${CaptureMessages.speedTile}: ')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip(CaptureMessages.faster));
    await tester.pump();
    await tester.tap(find.text(CaptureMessages.done));
    await tester.pumpAndSettle();

    await _tapNext(tester);
    final capture = tester.widget<CaptureScreen>(find.byType(CaptureScreen));
    expect(capture.details.title, 'Ave Maria');
    expect(capture.details.arranger, 'Schubert');
    expect(capture.details.keySignature, KeySignature.d);
    expect(capture.details.timeSignature, TimeSignature.threeFour);
    expect(capture.details.tempoBpm, ScoreDetails.defaultTempo + 1);

    await tester.tap(find.byTooltip(CaptureMessages.close));
    await tester.pumpAndSettle();
    expect(find.byType(ScoreDetailsScreen), findsOneWidget);
    expect(
      tester.widget<TextField>(_titleField).controller!.text.trim(),
      'Ave Maria',
    );
    expect(
      find.bySemanticsLabel(
        '${CaptureMessages.beatsTile}: ${TimeSignature.threeFour.label}',
      ),
      findsOneWidget,
    );
  });

  testWidgets('"Not sure" clears an answer', (tester) async {
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    await _choose(tester, CaptureMessages.keyTile, KeySignature.f.label);
    await _choose(tester, CaptureMessages.keyTile, CaptureMessages.notSure);
    expect(
      find.bySemanticsLabel(
        '${CaptureMessages.keyTile}: ${CaptureMessages.notSure}',
      ),
      findsOneWidget,
    );
  });

  testWidgets('Cancel returns to the library', (tester) async {
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    await tester.ensureVisible(find.text(CaptureMessages.cancel));
    await tester.tap(find.text(CaptureMessages.cancel));
    await tester.pumpAndSettle();
    expect(find.text(kLibraryMarker), findsOneWidget);
  });

  testWidgets('320x568 at 2x text: no overflow, Next reachable', (
    tester,
  ) async {
    await pumpCapture(
      tester,
      CaptureHarness(),
      startOnDetails: true,
      size: const Size(320, 568),
      textScale: 2,
    );
    expect(tester.takeException(), isNull);
    await tester.enterText(_titleField, 'Ave Maria');
    await _choose(tester, CaptureMessages.keyTile, KeySignature.cFlat.label);
    expect(tester.takeException(), isNull);
    await _tapNext(tester);
    expect(find.byType(CaptureScreen), findsOneWidget);
  });

  testWidgets('meets tap-target, label and contrast guidelines', (
    tester,
  ) async {
    final handle = tester.ensureSemantics();
    await pumpCapture(tester, CaptureHarness(), startOnDetails: true);
    await tester.enterText(_titleField, 'Ave Maria');
    await tester.pump();
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    handle.dispose();
  });
}
