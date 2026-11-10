import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';
import 'package:piyanota_application/state/score_upload_providers.dart';

import '../processing/processing_fakes.dart' show appContainer;
import 'capture_fakes.dart';

/// Saving the failed row breaks (disk full, say).
class _FailCannotSave extends LocalSubmissionsController {
  @override
  Future<void> fail({
    required String clientSubmissionId,
    required String code,
  }) => Future.error(StateError('disk full'));
}

Future<void> _shootAndSend(WidgetTester tester) async {
  await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
  await tester.pumpAndSettle();
  await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
  await tester.pumpAndSettle();
}

/// Upload-in-Processing review, N1–N4 and N8.
void main() {
  testWidgets('N1: a second start with the same id while sending does not '
      'send twice', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Completer<SubmittedJob>().future;
    await pumpCapture(tester, h);
    await _shootAndSend(tester);

    final container = appContainer(tester);
    final key = h.upload.clientIdsSent.single!;
    final upload = container.read(scoreUploadsProvider)[key]!;
    container
        .read(scoreUploadsProvider.notifier)
        .start(clientId: key, details: upload.details, session: upload.session);
    await tester.pump();
    expect(h.upload.imageCalls, hasLength(1));
  });

  testWidgets('N2: Back during the upload stays on Processing and offers no '
      'Convert in Background', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () => Completer<SubmittedJob>().future;
    await pumpCapture(tester, h);
    await _shootAndSend(tester);

    expect(find.text(ProcessingMessages.convertInBackground), findsNothing);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text(ProcessingMessages.cancelUpload), findsOneWidget);
    expect(find.text(kLibraryMarker), findsNothing);
    // The raw shot goes after prepare; the page being sent must not.
    expect(h.files.deleted, isNot(contains('prepared/raw-0.jpg')));
  });

  testWidgets('N3: a failure that beats Cancel sending leaves Try again with '
      'a working Cancel sending', (tester) async {
    final h = CaptureHarness();
    final pending = Completer<SubmittedJob>();
    h.upload
      ..ignoreCancel = true
      ..onSubmit = () => pending.future;
    await pumpCapture(tester, h);
    await _shootAndSend(tester);

    await tester.tap(find.text(ProcessingMessages.cancelUpload));
    await tester.pump();
    expect(find.text(ProcessingMessages.cancelling), findsOneWidget);
    pending.completeError(const UploadNetworkException());
    await tester.pumpAndSettle();
    expect(find.text(ProcessingMessages.uploadFailedHeading), findsOneWidget);

    h.upload
      ..ignoreCancel = false
      ..onSubmit = () => Completer<SubmittedJob>().future;
    await tester.tap(find.text(ProcessingMessages.retry));
    await tester.pumpAndSettle();
    expect(find.text(ProcessingMessages.cancelling), findsNothing);
    await tester.tap(find.text(ProcessingMessages.cancelUpload));
    await tester.pumpAndSettle();
    // The cancel went through: back on Capture with the pages.
    expect(find.text(CaptureMessages.uploadCancelled), findsOneWidget);
  });

  testWidgets('N4: a failed row that cannot be saved still ends the upload '
      'on the failure view', (tester) async {
    final h = CaptureHarness();
    h.extraOverrides.add(
      localSubmissionsProvider.overrideWith(_FailCannotSave.new),
    );
    h.upload.onSubmit = () => Future.error(const UploadNetworkException());
    await pumpCapture(tester, h);
    await _shootAndSend(tester);

    expect(find.text(ProcessingMessages.uploadFailedHeading), findsOneWidget);
    expect(find.text(ProcessingMessages.retry), findsOneWidget);
  });

  testWidgets('N8: session expiry during the upload says to add the score '
      'again, not to keep following a scan', (tester) async {
    final h = CaptureHarness();
    h.upload.onSubmit = () =>
        Future.error(const UploadSessionExpiredException());
    await pumpCapture(tester, h);
    await _shootAndSend(tester);

    await tester.tap(find.text(CaptureMessages.logIn));
    await tester.pumpAndSettle();
    expect(find.text(kLoginMarker), findsOneWidget);
    expect(
      find.text(ProcessingMessages.sessionExpiredUpload),
      findsOneWidget,
    );
    expect(find.text(ProcessingMessages.sessionExpired), findsNothing);
  });
}
