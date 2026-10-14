import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import '../processing/processing_fakes.dart' show appContainer;
import 'capture_fakes.dart';

const _old = 'job-1';

const _whole = WholeRetakeArguments(
  replacesJobId: _old,
  details: ScoreDetails(
    title: 'Ave Maria',
    arranger: 'Bach',
    tempoBpm: 72,
    keySignature: KeySignature.f,
    timeSignature: TimeSignature.threeFour,
  ),
  retakeOfScoreId: 7,
);

Future<void> _shoot(WidgetTester tester, [int times = 1]) async {
  for (var i = 0; i < times; i++) {
    await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
    await tester.pumpAndSettle();
  }
}

Future<void> _toPages(WidgetTester tester) async {
  await tester.tap(find.text(CaptureMessages.nextAddPages));
  await tester.pumpAndSettle();
}

/// PIYA-207 AC12: the whole score again, as a new submit that replaces
/// the old job.
void main() {
  testWidgets('details pre-filled from PIYA-102 AC8, pages start empty', (
    tester,
  ) async {
    await pumpCapture(tester, CaptureHarness(), wholeRetake: _whole);
    final title = tester.widget<TextField>(find.byType(TextField).first);
    expect(title.controller!.text, 'Ave Maria');
    final arranger = tester.widget<TextField>(find.byType(TextField).at(1));
    expect(arranger.controller!.text, 'Bach');
    await _toPages(tester);
    expect(find.text(CaptureMessages.createScoreWith(1)), findsNothing);
  });

  testWidgets('submit carries replacesJobId and the details; the tracker '
      'follows the new job in place of the old', (tester) async {
    final h = CaptureHarness();
    await pumpCapture(tester, h, wholeRetake: _whole);
    final jobs = appContainer(tester).read(processingJobsProvider.notifier);
    jobs.track(_old, title: 'Ave Maria');
    await tester.pump();
    await _toPages(tester);
    await _shoot(tester, 2);
    await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
    await tester.pumpAndSettle();

    expect(h.upload.replacesSent, [_old]);
    final sent = h.upload.detailsSent.single;
    expect(sent.title, 'Ave Maria');
    expect(sent.arranger, 'Bach');
    expect(sent.tempoBpm, 72);
    expect(sent.keySignature, KeySignature.f);
    expect(sent.timeSignature, TimeSignature.threeFour);
    expect(
      find.text(
        'ROUTE:processing ${ScriptedScoreUploadApi.job.jobId} '
        'Ave Maria',
      ),
      findsOneWidget,
    );
    final tracked = appContainer(tester).read(processingJobsProvider);
    expect(tracked, isNot(contains(_old)));
    expect(tracked[ScriptedScoreUploadApi.job.jobId]?.retakeOfScoreId, 7);
    expect(jobs.runningRetakeOf(7)?.jobId, ScriptedScoreUploadApi.job.jobId);
  });

  for (final (status, code) in [
    (404, jobNotFoundCode),
    (409, notRetakeableCode),
    (409, retakeInProgressCode),
  ]) {
    testWidgets('$code: says so, with a way back to the library', (
      tester,
    ) async {
      final h = CaptureHarness();
      final error = UploadRejectedException(statusCode: status, code: code);
      h.upload.onSubmit = () => Future.error(error);
      await pumpCapture(tester, h, wholeRetake: _whole);
      await _toPages(tester);
      await _shoot(tester);
      await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
      await tester.pumpAndSettle();
      expect(
        find.text(CaptureMessages.wholeRetakeError(error)!),
        findsOneWidget,
      );
      expect(find.textContaining('ROUTE:processing'), findsNothing);
    });
  }
}
