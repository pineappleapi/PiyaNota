import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';

import '../processing/processing_fakes.dart' show appContainer;
import 'capture_fakes.dart';

Future<void> _shoot(WidgetTester tester) async {
  await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
  await tester.pumpAndSettle();
}

Future<void> _send(WidgetTester tester) async {
  await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
  await tester.pumpAndSettle();
}

Future<void> _retry(WidgetTester tester) async {
  await tester.tap(find.text(ProcessingMessages.retry));
  await tester.pumpAndSettle();
}

/// Task 3: a local row exists before the upload, carries the id the server
/// sees, and ends processing (with the job) or failed (with the reason).
void main() {
  testWidgets('the row is written before the 202 and holds the sent id', (
    tester,
  ) async {
    final h = CaptureHarness();
    final pending = Completer<SubmittedJob>();
    h.upload.onSubmit = () => pending.future;
    await pumpCapture(tester, h);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
    await tester.pump();
    await tester.pump();

    final container = appContainer(tester);
    final during = container.read(localSubmissionsProvider).single;
    expect(during.status, SubmissionStatus.processing);
    expect(during.jobId, isNull);
    expect(h.upload.clientIdsSent.single, during.clientSubmissionId);
    expect(during.clientSubmissionId, hasLength(36));

    pending.complete(ScriptedScoreUploadApi.job);
    await tester.pumpAndSettle();
    final after = container.read(localSubmissionsProvider).single;
    expect(after.clientSubmissionId, during.clientSubmissionId);
    expect(after.jobId, ScriptedScoreUploadApi.job.jobId);
    expect(after.status, SubmissionStatus.processing);
  });

  for (final (status, code) in [
    (429, 'queue_full'),
    (409, 'score_limit_reached'),
    (429, 'too_many_active_jobs'),
    (409, 'some_future_code'),
  ]) {
    testWidgets('$status $code marks the row failed with that code', (
      tester,
    ) async {
      final h = CaptureHarness();
      h.upload.onSubmit = () =>
          Future.error(UploadRejectedException(statusCode: status, code: code));
      await pumpCapture(tester, h);
      await _shoot(tester);
      await _send(tester);

      final row = appContainer(tester).read(localSubmissionsProvider).single;
      expect(row.status, SubmissionStatus.failed);
      expect(row.failureCode, code);
      expect(row.jobId, isNull);
    });
  }

  testWidgets('a network drop keeps the id: the resend is the same '
      'submission and the row goes back to processing', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Future.error(const UploadNetworkException());
    await pumpCapture(tester, h);
    await _shoot(tester);
    await _send(tester);
    final container = appContainer(tester);
    expect(
      container.read(localSubmissionsProvider).single.failureCode,
      SubmissionFailure.network,
    );

    // "Try again" on Processing.
    h.upload.onSubmit = null;
    await _retry(tester);
    expect(h.upload.clientIdsSent, hasLength(2));
    expect(h.upload.clientIdsSent[1], h.upload.clientIdsSent[0]);
    final rows = container.read(localSubmissionsProvider);
    expect(rows, hasLength(1));
    expect(rows.single.jobId, ScriptedScoreUploadApi.job.jobId);
    expect(rows.single.failureCode, isNull);
  });

  testWidgets('a definite refusal frees the id: the next send is new', (
    tester,
  ) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Future.error(
      const UploadRejectedException(statusCode: 429, code: 'queue_full'),
    );
    await pumpCapture(tester, h);
    await _shoot(tester);
    await _send(tester);

    h.upload.onSubmit = null;
    await _retry(tester);
    expect(h.upload.clientIdsSent[1], isNot(h.upload.clientIdsSent[0]));
  });

  testWidgets('editing the pages after a network drop sends a NEW submission '
      '(the edit is not lost to an idempotent replay)', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Future.error(const UploadNetworkException());
    await pumpCapture(tester, h);
    await _shoot(tester);
    await _send(tester);
    await backToEditPages(tester);

    h.upload.onSubmit = null;
    await _shoot(tester); // a second page: the content differs now
    await tester.tap(find.text(CaptureMessages.createScoreWith(2)));
    await tester.pumpAndSettle();
    expect(h.upload.clientIdsSent, hasLength(2));
    expect(h.upload.clientIdsSent[1], isNot(h.upload.clientIdsSent[0]));
  });

  testWidgets('Cancel sending tells the server by client id and drops the '
      'row', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Completer<SubmittedJob>().future;
    await pumpCapture(tester, h);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
    await tester.pumpAndSettle();
    await tester.tap(find.text(CaptureMessages.cancelUpload));
    await tester.pumpAndSettle();

    expect(h.cancelApi.ids, [h.upload.clientIdsSent.single]);
    expect(appContainer(tester).read(localSubmissionsProvider), isEmpty);
  });

  testWidgets('Cancel sending then Send again uses a new id', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Completer<SubmittedJob>().future;
    await pumpCapture(tester, h);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
    await tester.pumpAndSettle();
    await tester.tap(find.text(CaptureMessages.cancelUpload));
    await tester.pumpAndSettle();

    await tester.pump(const Duration(seconds: 10)); // snack off the button
    await tester.pumpAndSettle();
    h.upload.onSubmit = null;
    await _send(tester);
    expect(h.upload.clientIdsSent, hasLength(2));
    expect(h.upload.clientIdsSent[1], isNot(h.upload.clientIdsSent[0]));
  });

  testWidgets('Cancel sending offline still drops the row (tombstone)', (
    tester,
  ) async {
    final h = CaptureHarness();
    h.cancelApi.error = const ProcessingNetworkException();
    h.upload.onSubmit = () => Completer<SubmittedJob>().future;
    await pumpCapture(tester, h);
    await _shoot(tester);
    await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
    await tester.pumpAndSettle();
    await tester.tap(find.text(CaptureMessages.cancelUpload));
    await tester.pumpAndSettle();

    expect(appContainer(tester).read(localSubmissionsProvider), isEmpty);
    expect(
      (await const LocalSubmissionStore().loadDismissed()).keys,
      contains(h.upload.clientIdsSent.single),
    );
  });

  testWidgets('race: the upload lands after the cancel and gets 409 '
      'submission_cancelled: no error card, no row, a new id next time', (
    tester,
  ) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Future.error(
      const UploadRejectedException(
        statusCode: 409,
        code: submissionCancelledCode,
      ),
    );
    await pumpCapture(tester, h);
    await _shoot(tester);
    await _send(tester);

    expect(find.text(CaptureMessages.uploadCancelled), findsOneWidget);
    expect(find.text(CaptureMessages.network), findsNothing);
    expect(appContainer(tester).read(localSubmissionsProvider), isEmpty);

    await tester.pump(const Duration(seconds: 10)); // snack off the button
    await tester.pumpAndSettle();
    h.upload.onSubmit = null;
    await _send(tester);
    expect(h.upload.clientIdsSent[1], isNot(h.upload.clientIdsSent[0]));
  });
}
