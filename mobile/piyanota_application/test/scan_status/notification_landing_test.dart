import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/local_submission.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/scan_status/notification_landing_screen.dart';
import 'package:piyanota_application/screens/scan_status/scan_background_host.dart';
import 'package:piyanota_application/screens/scan_status/scan_status_messages.dart';
import 'package:piyanota_application/services/local_submission_store.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/services/submission_reconciler.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/score_library_providers.dart';
import 'package:piyanota_application/state/submission_reconcile_providers.dart';
import 'package:piyanota_application/state/work_owner.dart';

import '../processing/processing_fakes.dart';

class _LibraryApi implements ScoreLibraryApi {
  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async => [];

  @override
  Future<void> deleteScore(int scoreId) async {}

  @override
  Future<ScoreSummary> updateScore(
    int scoreId, {
    required String title,
    String? arranger,
  }) => throw UnimplementedError();

  @override
  Future<void> recordOpened(int scoreId) async {}
}

/// A tapped result notification: reconcile first, loading state meanwhile,
/// then the score, its Processing screen, or the Library with a message.
void main() {
  late FakeScanTrackingService device;
  late Completer<ReconcileResult> reconcileGate;
  late List<bool> reconcileForce;
  Object? reconcileError;

  final created = DateTime.utc(2026, 11, 9);

  Future<void> pump(
    WidgetTester tester, {
    List<LocalSubmission> rows = const [],
    bool gated = true,
  }) async {
    SharedPreferences.setMockInitialValues({});
    await const LocalSubmissionStore().save(rows);
    device = FakeScanTrackingService();
    reconcileGate = Completer();
    reconcileForce = [];
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
          scanTrackingServiceProvider.overrideWithValue(device),
          scoreLibraryApiProvider.overrideWithValue(_LibraryApi()),
          signedInOverride(),
          reconcileSubmissionsProvider.overrideWithValue(({
            bool force = false,
            bool fresh = false,
          }) async {
            reconcileForce.add(force);
            if (reconcileError != null) throw reconcileError!;
            return gated ? reconcileGate.future : ReconcileResult.done;
          }),
        ],
        child: MaterialApp(
          navigatorKey: navigatorKey,
          builder: (context, child) =>
              ScanBackgroundHost(navigatorKey: navigatorKey, child: child!),
          home: const Scaffold(body: Text('ROUTE:home')),
          routes: {
            AppRoutes.scoreLibrary: (_) =>
                const Scaffold(body: Text('ROUTE:library')),
            AppRoutes.playback: (context) {
              final args =
                  ModalRoute.of(context)!.settings.arguments!
                      as PlaybackArguments;
              return Scaffold(body: Text('ROUTE:playback ${args.scoreId}'));
            },
            AppRoutes.processing: (context) {
              final args =
                  ModalRoute.of(context)!.settings.arguments!
                      as ProcessingArguments;
              return Scaffold(body: Text('ROUTE:processing ${args.jobId}'));
            },
          },
        ),
      ),
    );
    await tester.pump();
  }

  LocalSubmission row(
    SubmissionStatus status, {
    String jobId = 'j1',
    int? scoreId,
    String? failure,
  }) => LocalSubmission(
    clientSubmissionId: 'c-$jobId',
    title: 'Paraiso',
    createdAt: created,
    jobId: jobId,
    scoreId: scoreId,
    status: status,
    failureCode: failure,
  );

  setUp(() => reconcileError = null);

  Future<void> end(WidgetTester tester) => tester.pumpWidget(const SizedBox());

  testWidgets('warm start: loading shows while reconcile runs, then the '
      'score opens', (tester) async {
    await pump(tester, rows: [row(SubmissionStatus.ready, scoreId: 7)]);
    device.tap('j1');
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text(ScanStatusMessages.openingFromNotification), findsWidgets);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('ROUTE:playback 7'), findsNothing);
    expect(reconcileForce, [true]);

    reconcileGate.complete(ReconcileResult.done);
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:playback 7'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    await end(tester);
  });

  testWidgets('a job still converting opens its Processing screen', (
    tester,
  ) async {
    await pump(tester, rows: [row(SubmissionStatus.processing)], gated: false);
    device.tap('j1');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:processing j1'), findsOneWidget);
    await end(tester);
  });

  testWidgets('a failed job lands on its failure view (reason, Retake)', (
    tester,
  ) async {
    await pump(
      tester,
      rows: [row(SubmissionStatus.failed, failure: 'no_staff_detected')],
      gated: false,
    );
    device.tap('j1');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:processing j1'), findsOneWidget);
    await end(tester);
  });

  testWidgets('a job that is gone lands on the Library with a message', (
    tester,
  ) async {
    await pump(tester, gated: false);
    device.tap('j-missing');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:library'), findsOneWidget);
    expect(find.text(ScanStatusMessages.notificationGone), findsOneWidget);
    await end(tester);
  });

  testWidgets('reconcile failing (offline) still opens what is on the '
      'phone', (tester) async {
    reconcileError = StateError('offline');
    await pump(tester, rows: [row(SubmissionStatus.ready, scoreId: 9)]);
    device.tap('j1');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:playback 9'), findsOneWidget);
    await end(tester);
  });

  testWidgets('a malformed or legacy payload opens the Library, no reconcile', (
    tester,
  ) async {
    for (final bad in ['', 'https://x.example/a?t=1', '{"id":1}']) {
      await pump(tester, gated: false);
      device.tap(bad);
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:library'), findsOneWidget, reason: bad);
      expect(reconcileForce, isEmpty, reason: bad);
      await end(tester);
    }
  });

  testWidgets('signed out: a tap changes nothing', (tester) async {
    // The host ignores taps without a session; Login stays where it is.
    await pump(tester, gated: false);
    final container = ProviderScope.containerOf(
      tester.element(find.text('ROUTE:home')),
    );
    container.read(signedInProvider.notifier).set(false);
    device.tap('j1');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:home'), findsOneWidget);
    expect(reconcileForce, isEmpty);
    await end(tester);
  });

  testWidgets('cold-start entry point: openScanNotification routes the '
      'same way', (tester) async {
    await pump(
      tester,
      rows: [row(SubmissionStatus.ready, scoreId: 3)],
      gated: false,
    );
    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    unawaited(openScanNotification(navigator, 'j1'));
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:playback 3'), findsOneWidget);
    expect(navigator.canPop(), isTrue, reason: 'back goes to what was under');
    await end(tester);
  });
}
