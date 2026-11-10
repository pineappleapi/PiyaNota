import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/submission_reconcile_providers.dart';

/// Task 3: the Library shows scores the phone sent that have no job yet.
void main() {
  const settle = Duration(seconds: 2);

  Widget card({required bool failed, VoidCallback? onDismiss}) => MaterialApp(
    home: Scaffold(
      body: LocalSubmissionCard(
        title: 'Ave Maria',
        failed: failed,
        failureCode: 'queue_full',
        onDismiss: onDismiss ?? () {},
      ),
    ),
  );

  test('failure copy for a card with a job never says to add it again', () {
    for (final code in [
      'no_staff_detected',
      'ambiguous_staff_count',
      'preprocessing_error',
      'incomplete_voice_sequence',
      'interrupted',
      'stage_timeout',
      null,
    ]) {
      final text = LibraryMessages.submissionFailed(code, hasJob: true);
      expect(text, isNot(contains('add it again')), reason: '$code');
      expect(text, isNot(contains('Add the whole')), reason: '$code');
      expect(text, isNot(contains('Add this')), reason: '$code');
      expect(
        text,
        contains(LibraryMessages.openFailedSubmission),
        reason: '$code',
      );
    }
    expect(
      LibraryMessages.submissionFailed('no_staff_detected', hasJob: true),
      contains('re-photograph'),
    );
  });

  test('pre-job failures keep the add-again copy even with hasJob', () {
    expect(
      LibraryMessages.submissionFailed('queue_full', hasJob: true),
      LibraryMessages.submissionFailed('queue_full'),
    );
    expect(
      LibraryMessages.submissionFailed('network'),
      contains('add it again'),
    );
  });

  testWidgets('sending card: bar and label, no dismiss', (tester) async {
    await tester.pumpWidget(card(failed: false));
    expect(find.text('Ave Maria'), findsOneWidget);
    expect(find.text(LibraryMessages.uploading), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.byKey(const ValueKey('submission-dismiss')), findsNothing);
  });

  testWidgets('failed card: reason in words, 48 dp Dismiss calls back', (
    tester,
  ) async {
    var dismissed = 0;
    await tester.pumpWidget(card(failed: true, onDismiss: () => dismissed++));
    expect(
      find.text(LibraryMessages.submissionFailed('queue_full')),
      findsOneWidget,
    );
    expect(find.byType(LinearProgressIndicator), findsNothing);
    final size = tester.getSize(
      find.byKey(const ValueKey('submission-dismiss')),
    );
    expect(size.height, greaterThanOrEqualTo(48));
    await tester.tap(find.byKey(const ValueKey('submission-dismiss')));
    expect(dismissed, 1);
  });

  testWidgets('failed card with a job: card tap and 48 dp open button call '
      'onOpen; without onOpen there is no button', (tester) async {
    var opened = 0;
    Widget withOpen(VoidCallback? onOpen) => MaterialApp(
      home: Scaffold(
        body: LocalSubmissionCard(
          title: 'Ave Maria',
          failed: true,
          failureCode: 'incomplete_voice_sequence',
          onDismiss: () {},
          onOpen: onOpen,
        ),
      ),
    );
    await tester.pumpWidget(withOpen(() => opened++));
    const open = ValueKey('submission-open');
    expect(tester.getSize(find.byKey(open)).height, greaterThanOrEqualTo(48));
    expect(find.byKey(const ValueKey('submission-dismiss')), findsOneWidget);
    await tester.tap(find.byKey(open));
    await tester.tap(find.text('Ave Maria'));
    expect(opened, 2);

    await tester.pumpWidget(withOpen(null));
    expect(find.byKey(open), findsNothing);
  });

  test('unknown codes read generically, never as a raw code', () {
    expect(
      LibraryMessages.submissionFailed('some_future_code'),
      LibraryMessages.submissionFailedGeneric,
    );
    expect(
      LibraryMessages.submissionFailed(null),
      LibraryMessages.submissionFailedGeneric,
    );
  });

  testWidgets('library lists a sending row and a failed row; Dismiss removes '
      'it from the screen and from storage', (tester) async {
    SharedPreferences.setMockInitialValues({'onboarding_completed': true});
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(
            FakeAuthApi(latency: Duration.zero),
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

    final container = ProviderScope.containerOf(
      tester.element(find.byType(PiyaNotaApp)),
    );
    // No runAsync: the controller's restore lives on the test clock.
    final subs = container.read(localSubmissionsProvider.notifier);
    unawaited(
      subs.begin(clientSubmissionId: 'sending-1', title: 'Sending One'),
    );
    await tester.pump(settle);
    unawaited(subs.begin(clientSubmissionId: 'failed-1', title: 'Failed One'));
    await tester.pump(settle);
    unawaited(subs.fail(clientSubmissionId: 'failed-1', code: 'queue_full'));
    await tester.pump(settle);

    expect(find.text('Sending One'), findsOneWidget);
    expect(find.text('Failed One'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('submission-dismiss')));
    await tester.pump(settle);
    expect(find.text('Failed One'), findsNothing);
    expect(find.text('Sending One'), findsOneWidget);
    expect(
      container.read(localSubmissionsProvider).map((r) => r.clientSubmissionId),
      ['sending-1'],
    );
  });

  testWidgets('a persisted converting row with a jobId shows in the Library '
      'after a restart, with no in-memory tracker, and reconcile feeds its '
      'progress', (tester) async {
    final row = LocalSubmission(
      clientSubmissionId: 'c-restart',
      title: 'Restarted Score',
      createdAt: DateTime.now().toUtc(),
      jobId: 'job-restart',
      percentComplete: 10,
    );
    SharedPreferences.setMockInitialValues({
      'onboarding_completed': true,
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode([row]),
    });
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          fakeAuthApiProvider.overrideWithValue(
            FakeAuthApi(latency: Duration.zero),
          ),
          jobListApiProvider.overrideWithValue(
            _ListOf([
              (
                jobId: 'job-restart',
                clientSubmissionId: 'c-restart',
                title: 'Restarted Score',
                createdAt: null,
                status: const ProcessingStatus(
                  stage: ProcessingStage.transcribing,
                  percentComplete: 42,
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

    final container = ProviderScope.containerOf(
      tester.element(find.byType(PiyaNotaApp)),
    );
    expect(container.read(processingJobsProvider), isEmpty);
    expect(find.text('Restarted Score'), findsOneWidget);
    expect(find.text('Converting… 42%'), findsOneWidget);
    expect(find.byKey(const ValueKey('submission-dismiss')), findsNothing);
  });
}

class _ListOf implements JobListApi {
  _ListOf(this.jobs);

  final List<ListedJob> jobs;

  @override
  Future<List<ListedJob>> listJobs() async => jobs;
}
