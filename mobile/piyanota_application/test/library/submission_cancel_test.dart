import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/submission_reconcile_providers.dart';

import '../processing/processing_fakes.dart';

/// Task 7: explicit cancel of a persisted converting row.
void main() {
  const settle = Duration(seconds: 2);

  LocalSubmission row(String id, {String? jobId}) => LocalSubmission(
    clientSubmissionId: id,
    title: 'Row $id',
    createdAt: DateTime.now().toUtc().subtract(const Duration(minutes: 20)),
    jobId: jobId,
  );

  late ScriptedSubmissionCancelApi cancelApi;

  setUp(() => cancelApi = ScriptedSubmissionCancelApi());

  ProviderContainer container(
    ScriptedProcessingApi api,
    List<LocalSubmission> rows,
  ) {
    SharedPreferences.setMockInitialValues({
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode(rows),
    });
    final c = ProviderContainer(
      overrides: [
        processingApiProvider.overrideWithValue(api),
        submissionCancelApiProvider.overrideWithValue(cancelApi),
        jobListApiProvider.overrideWithValue(_ListOf(const [])),
      ],
    );
    addTearDown(c.dispose);
    return c;
  }

  List<String> ids(ProviderContainer c) => [
    for (final r in c.read(localSubmissionsProvider)) r.clientSubmissionId,
  ];

  group('LocalSubmissionsController.cancel', () {
    test('success drops the row and tombstones it', () async {
      final api = ScriptedProcessingApi();
      final c = container(api, [row('a', jobId: 'j1')]);
      final n = c.read(localSubmissionsProvider.notifier);
      expect(await n.cancel('a'), CancelOutcome.cancelled);
      expect(api.cancels, 1);
      expect(ids(c), isEmpty);
      final dismissed = await const LocalSubmissionStore().loadDismissed();
      expect(dismissed.keys, containsAll(['a', 'j1']));
    });

    test('409 keeps the row (already finished)', () async {
      final api = ScriptedProcessingApi()
        ..cancelError = const ProcessingConflictException();
      final c = container(api, [row('a', jobId: 'j1')]);
      expect(
        await c.read(localSubmissionsProvider.notifier).cancel('a'),
        CancelOutcome.alreadyFinished,
      );
      expect(ids(c), ['a']);
      expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);
    });

    test('404 drops the row', () async {
      final api = ScriptedProcessingApi()
        ..cancelError = const ProcessingJobNotFoundException();
      final c = container(api, [row('a', jobId: 'j1')]);
      expect(
        await c.read(localSubmissionsProvider.notifier).cancel('a'),
        CancelOutcome.notFound,
      );
      expect(ids(c), isEmpty);
    });

    test('network error keeps the row, retryable', () async {
      final api = ScriptedProcessingApi()
        ..cancelError = const ProcessingNetworkException();
      final c = container(api, [row('a', jobId: 'j1')]);
      expect(
        await c.read(localSubmissionsProvider.notifier).cancel('a'),
        CancelOutcome.failed,
      );
      expect(ids(c), ['a']);
    });

    test('pre-202 row: cancelled by its client id, row removed and '
        'tombstoned', () async {
      final api = ScriptedProcessingApi();
      final c = container(api, [row('a')]);
      expect(
        await c.read(localSubmissionsProvider.notifier).cancel('a'),
        CancelOutcome.cancelled,
      );
      expect(api.cancels, 0);
      expect(cancelApi.ids, ['a']);
      expect(ids(c), isEmpty);
      expect(
        (await const LocalSubmissionStore().loadDismissed()).keys,
        contains('a'),
      );
    });

    test(
      'pre-202 row the server finished meanwhile is kept, not dropped',
      () async {
        cancelApi.answer = (jobId: 'j7', status: 'complete');
        final c = container(ScriptedProcessingApi(), [row('a')]);
        expect(
          await c.read(localSubmissionsProvider.notifier).cancel('a'),
          CancelOutcome.alreadyFinished,
        );
        expect(ids(c), ['a']);
        expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);
      },
    );

    test('pre-202 network error keeps the row for another try', () async {
      cancelApi.error = const ProcessingNetworkException();
      final c = container(ScriptedProcessingApi(), [row('a')]);
      expect(
        await c.read(localSubmissionsProvider.notifier).cancel('a'),
        CancelOutcome.failed,
      );
      expect(ids(c), ['a']);
      expect(await const LocalSubmissionStore().loadDismissed(), isEmpty);
    });

    test(
      'pre-202 network error with dismissOnFailure still tombstones',
      () async {
        cancelApi.error = const ProcessingNetworkException();
        final c = container(ScriptedProcessingApi(), [row('a')]);
        expect(
          await c
              .read(localSubmissionsProvider.notifier)
              .cancel('a', dismissOnFailure: true),
          CancelOutcome.failed,
        );
        expect(ids(c), isEmpty);
        expect(
          (await const LocalSubmissionStore().loadDismissed()).keys,
          contains('a'),
        );
      },
    );
  });

  testWidgets('card shows Cancel only while converting', (tester) async {
    var taps = 0;
    Widget card(bool failed) => MaterialApp(
      home: Scaffold(
        body: LocalSubmissionCard(
          title: 'Ave Maria',
          failed: failed,
          failureCode: null,
          onDismiss: () {},
          onCancel: () => taps++,
        ),
      ),
    );
    await tester.pumpWidget(card(false));
    final cancel = find.byKey(const ValueKey('submission-cancel'));
    expect(tester.getSize(cancel).height, greaterThanOrEqualTo(48));
    await tester.tap(cancel);
    expect(taps, 1);
    await tester.pumpWidget(card(true));
    expect(cancel, findsNothing);
  });

  testWidgets('library: Cancel asks first, then removes the row', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      'onboarding_completed': true,
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode([
        row('lib', jobId: 'j9'),
      ]),
    });
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final api = ScriptedProcessingApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(
            FakeAuthApi(latency: Duration.zero),
          ),
          processingApiProvider.overrideWithValue(api),
          jobListApiProvider.overrideWithValue(
            _ListOf([
              (
                jobId: 'j9',
                clientSubmissionId: 'lib',
                title: 'Row lib',
                createdAt: null,
                status: const ProcessingStatus(
                  stage: ProcessingStage.transcribing,
                  percentComplete: 10,
                ),
              ),
            ]),
          ),
        ],
        child: const PiyaNotaApp(),
      ),
    );
    await tester.pump();
    await tester.pump(splashIntroDuration);
    await tester.pump(settle);
    await tester.enterText(
      find.byType(TextFormField).at(0),
      FakeAuthApi.demoEmail,
    );
    await tester.enterText(
      find.byType(TextFormField).at(1),
      FakeAuthApi.demoPassword,
    );
    await tester.pump();
    final logIn = find.widgetWithText(ElevatedButton, 'Log In');
    await tester.ensureVisible(logIn);
    await tester.tap(logIn);
    await tester.pump();
    await tester.pump(settle);
    await tester.pump(FakeScoreLibraryApi.defaultLatency + settle);
    await tester.pump(settle);

    final cancel = find.byKey(const ValueKey('submission-cancel'));
    expect(find.text('Row lib'), findsOneWidget);
    expect(find.text(LibraryMessages.cancelSubmission), findsOneWidget);

    // Keep scanning: nothing happens.
    await tester.tap(cancel);
    await tester.pump(settle);
    expect(find.text(ProcessingMessages.cancelTitle), findsOneWidget);
    await tester.tap(find.text(ProcessingMessages.keepScanning));
    await tester.pump(settle);
    expect(api.cancels, 0);
    expect(find.text('Row lib'), findsOneWidget);

    await tester.tap(cancel);
    await tester.pump(settle);
    await tester.tap(find.text(ProcessingMessages.confirmCancel));
    await tester.pump(settle);
    await tester.pump(settle);
    expect(api.cancels, 1);
    expect(find.text('Row lib'), findsNothing);
    expect(find.text(ProcessingMessages.scanCancelled), findsOneWidget);
  });
}

class _ListOf implements JobListApi {
  _ListOf(this.jobs);

  final List<ListedJob> jobs;

  @override
  Future<List<ListedJob>> listJobs() async => jobs;
}
