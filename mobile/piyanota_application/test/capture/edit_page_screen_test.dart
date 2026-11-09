import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/page_edit.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/capture/edit_page_screen.dart';
import 'package:piyanota_application/state/capture_providers.dart';

import 'capture_fakes.dart';

class _FailingProcessor extends FakePageImageProcessor {
  @override
  Future<String> applyEdit(String path, PageEdit edit) async =>
      throw StateError('disk full');
}

/// Opens Edit Page over a launcher and records what it pops.
Future<List<String?>> _pumpEdit(
  WidgetTester tester,
  FakePageImageProcessor processor, {
  Size size = const Size(400, 800),
  double textScale = 1,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final results = <String?>[];
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        pageImageProcessorProvider.overrideWithValue(processor),
        pageImageSourceProvider.overrideWithValue(const FakePageImageSource()),
      ],
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async => results.add(
                await Navigator.of(context).push<String>(
                  MaterialPageRoute(
                    builder: (_) => const EditPageScreen(path: 'p.jpg'),
                  ),
                ),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return results;
}

CropOverlayPainter _overlay(WidgetTester tester) => tester
    .widgetList<CustomPaint>(find.byType(CustomPaint))
    .map((p) => p.painter)
    .whereType<CropOverlayPainter>()
    .single;

void main() {
  testWidgets('Done with no change returns nothing to apply', (tester) async {
    final processor = FakePageImageProcessor();
    final results = await _pumpEdit(tester, processor);
    await tester.tap(find.text(CaptureMessages.done));
    await tester.pumpAndSettle();
    expect(results, [null]);
    expect(processor.edits, isEmpty);
  });

  testWidgets('dragging a corner crops; Done applies the edit', (tester) async {
    final processor = FakePageImageProcessor();
    final results = await _pumpEdit(tester, processor);
    final frame = tester.getRect(
      find
          .ancestor(
            of: find.byType(ClipRect).first,
            matching: find.byType(GestureDetector),
          )
          .first,
    );
    await tester.dragFrom(
      frame.topLeft + const Offset(2, 2),
      Offset(frame.width * 0.25, frame.height * 0.25),
    );
    await tester.pump();
    final crop = _overlay(tester).crop;
    expect(crop.left, closeTo(0.25, 0.05));
    expect(crop.top, closeTo(0.25, 0.05));
    expect(crop.right, 1);

    await tester.tap(find.text(CaptureMessages.done));
    await tester.pumpAndSettle();
    expect(processor.edits.single.$2.crop, crop);
    expect(results.single, 'p.jpg+edit1');
  });

  testWidgets('a drag away from the corners does not crop', (tester) async {
    final results = await _pumpEdit(tester, FakePageImageProcessor());
    final centre = tester.getCenter(find.byType(ClipRect).first);
    await tester.dragFrom(centre, const Offset(40, 40));
    await tester.pump();
    expect(_overlay(tester).crop, PageEdit.fullCrop);
    expect(results, isEmpty);
  });

  testWidgets('rotate, straighten with grid, and Reset', (tester) async {
    final processor = FakePageImageProcessor();
    await _pumpEdit(tester, processor);
    final reset = find.ancestor(
      of: find.text(CaptureMessages.reset),
      matching: find.byWidgetPredicate((w) => w is ButtonStyleButton),
    );
    expect(tester.widget<ButtonStyleButton>(reset).onPressed, isNull);

    await tester.tap(find.text(CaptureMessages.rotate));
    await tester.pump();
    expect(find.byType(RotatedBox), findsOneWidget);
    expect(tester.widget<RotatedBox>(find.byType(RotatedBox)).quarterTurns, 1);

    final slider = find.byType(Slider);
    final gesture = await tester.startGesture(tester.getCenter(slider));
    await gesture.moveBy(const Offset(40, 0));
    await tester.pump();
    expect(_overlay(tester).showGrid, isTrue, reason: 'grid while dragging');
    await gesture.up();
    await tester.pump();
    expect(_overlay(tester).showGrid, isFalse);
    expect(tester.widget<Slider>(slider).value, greaterThan(0));

    await tester.tap(reset);
    await tester.pump();
    expect(tester.widget<RotatedBox>(find.byType(RotatedBox)).quarterTurns, 0);
    expect(tester.widget<Slider>(slider).value, 0);
  });

  testWidgets('a failed save says so and stays open', (tester) async {
    final results = await _pumpEdit(tester, _FailingProcessor());
    await tester.tap(find.text(CaptureMessages.rotate));
    await tester.pump();
    await tester.tap(find.text(CaptureMessages.done));
    await tester.pumpAndSettle();
    expect(find.text(CaptureMessages.editFailed), findsOneWidget);
    expect(find.byType(EditPageScreen), findsOneWidget);
    expect(results, isEmpty);
  });

  testWidgets('320x568 at 2x text fits', (tester) async {
    await _pumpEdit(
      tester,
      FakePageImageProcessor(),
      size: const Size(320, 568),
      textScale: 2,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('meets tap-target and label guidelines', (tester) async {
    final handle = tester.ensureSemantics();
    await _pumpEdit(tester, FakePageImageProcessor());
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    handle.dispose();
  });
}
