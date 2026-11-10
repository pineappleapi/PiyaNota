import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/screens/library/score_library_screen.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';

import '../processing/processing_fakes.dart' show appContainer;
import 'capture_fakes.dart';

const _oldJob = 'job-old';

const _whole = WholeRetakeArguments(
  replacesJobId: _oldJob,
  details: ScoreDetails(title: 'Ave Maria'),
);

final _failedRow = LocalSubmission(
  clientSubmissionId: 'c-old',
  title: 'Ave Maria',
  createdAt: DateTime.now().toUtc().subtract(const Duration(minutes: 5)),
  jobId: _oldJob,
  status: SubmissionStatus.failed,
  failureCode: 'incomplete_voice_sequence',
);

/// Cards the Library draws for submissions: the rows it does not hide.
List<LocalSubmission> _cards(WidgetTester tester) {
  final rows = appContainer(tester).read(localSubmissionsProvider);
  final hidden = ScoreLibraryScreen.supersededRows(rows);
  return [
    for (final r in rows)
      if (r.status != SubmissionStatus.ready &&
          !hidden.contains(r.clientSubmissionId))
        r,
  ];
}

Future<void> _pumpWithFailedRow(WidgetTester tester, CaptureHarness h) async {
  await pumpCapture(tester, h, wholeRetake: _whole);
  await appContainer(tester).read(localSubmissionsProvider.notifier).reload();
  await tester.pump();
  expect(_cards(tester).map((r) => r.clientSubmissionId), ['c-old']);
}

/// The harness resets preferences, so the failed row is seeded after it.
CaptureHarness _harness() {
  final h = CaptureHarness();
  SharedPreferences.setMockInitialValues({
    LocalSubmissionStore.storageKey: LocalSubmissionStore.encode([_failedRow]),
  });
  return h;
}

Future<void> _sendOnePage(WidgetTester tester) async {
  await tester.tap(find.text(CaptureMessages.nextAddPages));
  await tester.pumpAndSettle();
  await tester.tap(find.bySemanticsLabel(CaptureMessages.shutter));
  await tester.pumpAndSettle();
  await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
}

void main() {
  testWidgets('retake: one card at every step, old row tombstoned only '
      'after the 202', (tester) async {
    final h = _harness();
    final pending = Completer<SubmittedJob>();
    h.upload.onSubmit = () => pending.future;
    await _pumpWithFailedRow(tester, h);

    await _sendOnePage(tester);
    await tester.pump();
    await tester.pump();

    // Sending: the old failed row is still stored but hidden by the new one.
    final rows = appContainer(tester).read(localSubmissionsProvider);
    expect(rows, hasLength(2));
    expect(rows.where((r) => r.replacesJobId == _oldJob), hasLength(1));
    expect(_cards(tester), hasLength(1));
    expect(_cards(tester).single.replacesJobId, _oldJob);
    expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);

    pending.complete(ScriptedScoreUploadApi.job);
    await tester.pumpAndSettle();

    // Accepted: old row gone and tombstoned; the new one is the only card.
    final after = appContainer(tester).read(localSubmissionsProvider);
    expect(after, hasLength(1));
    expect(after.single.jobId, ScriptedScoreUploadApi.job.jobId);
    expect(_cards(tester), hasLength(1));
    final dismissed = await const LocalSubmissionStore().loadDismissed();
    expect(dismissed.keys, containsAll(['c-old', _oldJob]));
    expect(h.upload.replacesSent, [_oldJob]);
  });

  testWidgets('replacement refused: old failed row stays, one card, and a '
      'later accepted attempt leaves exactly one row', (tester) async {
    final h = _harness();
    var attempts = 0;
    h.upload.onSubmit = () => attempts++ == 0
        ? Future.error(
            const UploadRejectedException(statusCode: 429, code: 'queue_full'),
          )
        : Future.value(ScriptedScoreUploadApi.job);
    await _pumpWithFailedRow(tester, h);

    await _sendOnePage(tester);
    await tester.pumpAndSettle();

    var rows = appContainer(tester).read(localSubmissionsProvider);
    expect(rows.map((r) => r.clientSubmissionId), contains('c-old'));
    expect(rows, hasLength(2));
    expect(_cards(tester), hasLength(1), reason: 'refused attempt stands in');
    expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);

    await tester.tap(find.text(CaptureMessages.createScoreWith(1)));
    await tester.pumpAndSettle();

    rows = appContainer(tester).read(localSubmissionsProvider);
    expect(rows, hasLength(1), reason: 'old row and refused attempt gone');
    expect(rows.single.jobId, ScriptedScoreUploadApi.job.jobId);
    expect(_cards(tester), hasLength(1));
  });

  testWidgets('a network failure keeps the old row; dismissing the failed '
      'replacement brings the old card back', (tester) async {
    final h = _harness();
    h.upload.onSubmit = () => Future.error(const UploadNetworkException());
    await _pumpWithFailedRow(tester, h);
    await _sendOnePage(tester);
    await tester.pumpAndSettle();

    expect(_cards(tester), hasLength(1));
    final c = appContainer(tester);
    final attempt = c
        .read(localSubmissionsProvider)
        .firstWhere((r) => r.replacesJobId == _oldJob);
    await c
        .read(localSubmissionsProvider.notifier)
        .dismiss(attempt.clientSubmissionId);
    expect(_cards(tester).map((r) => r.clientSubmissionId), ['c-old']);
  });

  test('replaceFailedJob removes the row and tombstones it, so a reconcile '
      'that still lists the old job cannot bring it back', () async {
    SharedPreferences.setMockInitialValues({
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode([
        _failedRow,
      ]),
    });
    final c = ProviderContainer();
    addTearDown(c.dispose);
    final n = c.read(localSubmissionsProvider.notifier);
    await n.reload();
    expect(c.read(localSubmissionsProvider), hasLength(1));
    await n.replaceFailedJob(_oldJob);
    expect(c.read(localSubmissionsProvider), isEmpty);
    expect(await const LocalSubmissionStore().load(), isEmpty);
    final dismissed = await const LocalSubmissionStore().loadDismissed();
    expect(dismissed.keys, containsAll(['c-old', _oldJob]));
  });

  test("replaceFailedJob leaves a completed job's row alone", () async {
    final ready = LocalSubmission(
      clientSubmissionId: 'c-ready',
      title: 'Done',
      createdAt: DateTime.now().toUtc(),
      jobId: 'job-ready',
      status: SubmissionStatus.ready,
    );
    SharedPreferences.setMockInitialValues({
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode([ready]),
    });
    final c = ProviderContainer();
    addTearDown(c.dispose);
    final n = c.read(localSubmissionsProvider.notifier);
    await n.reload();
    await n.replaceFailedJob('job-ready');
    expect(c.read(localSubmissionsProvider), hasLength(1));
    expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);
  });

  test('replacesJobId survives storage (restart mid-retake)', () {
    final row = LocalSubmission(
      clientSubmissionId: 'c-new',
      title: 'Ave',
      createdAt: DateTime.utc(2026, 11, 10),
      replacesJobId: _oldJob,
    );
    expect(LocalSubmission.fromJson(row.toJson())!.replacesJobId, _oldJob);
    expect(
      LocalSubmission.fromJson(row.copyWith(jobId: 'j').toJson())!
          .replacesJobId,
      _oldJob,
    );
  });
}
