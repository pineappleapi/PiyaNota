import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import '../processing/processing_fakes.dart'
    show appContainer, expectTrackerCleared, seedOldJob;
import 'capture_fakes.dart';

const _retake = CaptureRetakeArguments(
  jobId: 'job-1',
  pageIndex: 1,
  title: 'Ave Maria',
);

Future<void> _shoot(WidgetTester tester) async {
  await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
  await tester.pumpAndSettle();
}

/// PIYA-207 AC7: Capture limited to the one page a failed job names.
void main() {
  testWidgets('names the page, takes one photo, offers no PDF', (tester) async {
    final h = CaptureHarness();
    h.picker.gallery = ['g0.jpg'];
    await pumpCapture(tester, h, retake: _retake);

    expect(find.text(CaptureMessages.retakeTitle(2)), findsOneWidget);
    expect(find.text(CaptureMessages.sendRetake(2)), findsOneWidget);

    // The PDF input does nothing here: a retake is one photo.
    if (find.text(CaptureMessages.pdf).evaluate().isNotEmpty) {
      await tester.tap(find.text(CaptureMessages.pdf));
      await tester.pumpAndSettle();
    }
    expect(find.text(CaptureMessages.replacePdfTitle), findsNothing);

    await _shoot(tester);
    expect(h.camera!.shots, 1);
    await _shoot(tester);
    expect(h.camera!.shots, 1, reason: 'a second page is refused');
    expect(find.text(CaptureMessages.retakeFull), findsOneWidget);

    await tester.tap(find.text(CaptureMessages.gallery));
    await tester.pumpAndSettle();
    expect(h.processor.prepared, ['raw-0.jpg']);
  });

  testWidgets('sends via PIYA-116 and opens Processing on the new job', (
    tester,
  ) async {
    final h = CaptureHarness();
    await pumpCapture(tester, h, retake: _retake);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.sendRetake(2)));
    await tester.pumpAndSettle();

    expect(h.upload.resubmitCalls, [('job-1', 1, 'prepared/raw-0.jpg')]);
    expect(h.upload.imageCalls, isEmpty);
    expect(
      find.text('ROUTE:processing job-1-retake Ave Maria'),
      findsOneWidget,
    );

    // Back from the new Processing lands on the library, not the old one.
    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pumpAndSettle();
    expect(find.text(kLibraryMarker), findsOneWidget);
  });

  testWidgets('a page that can no longer be replaced says so', (tester) async {
    final h = CaptureHarness();
    h.upload.onResubmit = () => Future.error(
      const UploadRejectedException(
        statusCode: 409,
        code: pageNotRetakeableCode,
      ),
    );
    await pumpCapture(tester, h, retake: _retake);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.sendRetake(2)));
    await tester.pumpAndSettle();
    expect(find.textContaining('can\'t be replaced any more'), findsOneWidget);
    expect(find.textContaining('ROUTE:processing'), findsNothing);
  });

  testWidgets('closing out discards the photo and sends nothing', (
    tester,
  ) async {
    final h = CaptureHarness();
    await pumpCapture(tester, h, retake: _retake);
    await _shoot(tester);
    await tester.tap(find.byTooltip(CaptureMessages.close));
    await tester.pumpAndSettle();
    expect(find.text(CaptureMessages.discardTitle(1)), findsOneWidget);
    await tester.tap(find.text(CaptureMessages.discard));
    await tester.pumpAndSettle();

    expect(find.text(kLibraryMarker), findsOneWidget);
    expect(h.upload.resubmitCalls, isEmpty);
    expect(h.files.deleted, contains('prepared/raw-0.jpg'));
  });

  testWidgets('session expiry during a retake logs out cleanly', (
    tester,
  ) async {
    final h = CaptureHarness();
    h.upload.onResubmit = () =>
        Future.error(const UploadSessionExpiredException());
    await pumpCapture(tester, h, retake: _retake);
    await seedOldJob(tester, h.processing);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.sendRetake(2)));
    await tester.pumpAndSettle();
    expect(find.text(CaptureMessages.sessionExpired), findsOneWidget);

    await tester.tap(find.text(CaptureMessages.logIn));
    await tester.pumpAndSettle();
    expect(find.text(kLoginMarker), findsOneWidget);
    expect(h.secureStorage.values, isEmpty);
    await expectTrackerCleared(tester, h.processing);
  });

  for (final (code, forgets) in [
    (jobNotFoundCode, true),
    (pageNotRetakeableCode, false),
  ]) {
    testWidgets('$code offers a way back to the library', (tester) async {
      final h = CaptureHarness();
      h.upload.onResubmit = () => Future.error(
        UploadRejectedException(
          statusCode: code == jobNotFoundCode ? 404 : 409,
          code: code,
        ),
      );
      await pumpCapture(tester, h, retake: _retake);
      appContainer(tester)
          .read(processingJobsProvider.notifier)
          .track(_retake.jobId);
      await tester.pump();
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.sendRetake(2)));
      await tester.pumpAndSettle();

      await tester.tap(find.text(CaptureMessages.backToLibrary));
      await tester.pumpAndSettle();
      expect(find.text(kLibraryMarker), findsOneWidget);
      expect(h.upload.resubmitCalls, hasLength(1));
      expect(h.files.deleted, contains('prepared/raw-0.jpg'));
      expect(
        appContainer(tester).read(processingJobsProvider),
        forgets ? isNot(contains(_retake.jobId)) : contains(_retake.jobId),
      );
    });
  }
}
