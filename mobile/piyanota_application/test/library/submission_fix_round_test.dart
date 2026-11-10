import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/app.dart';
import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/screens/onboarding/widgets/splash_overlay.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/state/auth_providers.dart';
import 'package:piyanota_application/state/local_submission_providers.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/scan_job_store.dart';
import 'package:piyanota_application/state/work_owner.dart';

import '../processing/processing_fakes.dart';

/// Fix round 1 for Tasks 3-8: I3 (a stopped tracker job must not hide the
/// row), I4 (no duplicate of the server placeholder), I5 (Cancel reachable
/// by TalkBack), I6/I7 (foreground merges per id against fresh prefs).
void main() {
  const settle = Duration(seconds: 2);

  Future<void> openLibrary(
    WidgetTester tester, {
    required List<LocalSubmission> rows,
    List<TrackedJob> tracked = const [],
  }) async {
    SharedPreferences.setMockInitialValues({
      'onboarding_completed': true,
      // The demo account owns the stored work, so login does not wipe it.
      WorkOwnerStore.storageKey: FakeAuthApi.demoUserId,
      LocalSubmissionStore.storageKey: LocalSubmissionStore.encode(rows),
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
          scanJobStoreProvider.overrideWithValue(
            MemoryScanJobStore(ScanJobStore.encodeJobs(tracked)),
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
  }

  LocalSubmission row(String id, {String? jobId, int? scoreId}) =>
      LocalSubmission(
        clientSubmissionId: id,
        title: 'Row $id',
        createdAt: DateTime.now().toUtc(),
        jobId: jobId,
        scoreId: scoreId,
        percentComplete: 10,
      );

  testWidgets('I3: a processing row stays visible when the tracker holds the '
      'job but it is failed', (tester) async {
    await openLibrary(
      tester,
      rows: [row('c1', jobId: 'job-f')],
      tracked: const [TrackedJob(jobId: 'job-f', phase: TrackedPhase.failed)],
    );
    expect(find.text('Row c1'), findsOneWidget);
  });

  testWidgets('I4: a processing row and the server placeholder with the same '
      'scoreId render one card', (tester) async {
    // 101 is "Bituin Walang Ningning" in the fake library list.
    await openLibrary(tester, rows: [row('c2', jobId: 'job-p', scoreId: 101)]);
    expect(find.text('Row c2'), findsOneWidget);
    expect(find.text('Bituin Walang Ningning'), findsNothing);
    expect(find.text('Paraiso'), findsOneWidget);
  });

  testWidgets('I5: the Cancel button is in the semantics tree', (tester) async {
    final handle = tester.ensureSemantics();
    var cancelled = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LocalSubmissionCard(
            title: 'Ave',
            failed: false,
            failureCode: null,
            hasJob: true,
            onCancel: () => cancelled++,
            onDismiss: () {},
          ),
        ),
      ),
    );
    final cancel = find.semantics.byLabel(
      RegExp(LibraryMessages.cancelSubmissionSemantics('Ave')),
    );
    expect(cancel, findsOneWidget);
    // The cancel node itself carries the tap action, and TalkBack's tap
    // reaches the callback.
    expect(
      find.semantics
          .byAction(SemanticsAction.tap)
          .evaluate()
          .any(
            (n) => n.label.contains(
              LibraryMessages.cancelSubmissionSemantics('Ave'),
            ),
          ),
      isTrue,
    );
    tester.semantics.tap(cancel);
    await tester.pump();
    expect(cancelled, 1);
    handle.dispose();
  });

  test('I6/I7: begin merges into rows another isolate wrote, never '
      'overwrites the whole list', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final ctl = container.read(localSubmissionsProvider.notifier);
    await ctl.begin(clientSubmissionId: 'mine', title: 'Mine');
    // The background isolate saved its own row after this isolate loaded.
    const store = LocalSubmissionStore();
    await store.update((cur) => [...cur, row('from-background')]);

    await ctl.begin(clientSubmissionId: 'second', title: 'Second');
    final onDisk = await store.load(fresh: true);
    expect(onDisk.map((r) => r.clientSubmissionId).toSet(), {
      'mine',
      'from-background',
      'second',
    });

    await ctl.reload(fresh: true);
    expect(
      container.read(localSubmissionsProvider).map((r) => r.clientSubmissionId),
      contains('from-background'),
    );
  });
}
