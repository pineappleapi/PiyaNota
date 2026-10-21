import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/scan_status/scan_background_host.dart';
import 'package:piyanota_application/screens/scan_status/scan_status_messages.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/score_library_providers.dart';

import '../processing/processing_fakes.dart';

/// Answers each job's polls from its own script; the last entry repeats.
class _JobsApi implements ProcessingApi {
  final Map<String, List<Object>> _scripts = {};
  final Map<String, Object> _last = {};

  void script(String jobId, List<Object> entries) =>
      (_scripts[jobId] ??= []).addAll(entries);

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    final queue = _scripts[jobId] ?? [];
    final next = queue.isNotEmpty ? queue.removeAt(0) : _last[jobId];
    if (next != null) _last[jobId] = next;
    if (next is ProcessingStatus) return next;
    throw StateError('Nothing scripted for $jobId');
  }

  @override
  Future<void> cancelJob(String jobId) async {}
}

class _LibraryApi implements ScoreLibraryApi {
  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async => [];

  @override
  Future<void> deleteScore(int scoreId) async {}

  @override
  Future<void> recordOpened(int scoreId) async {}
}

/// PIYA-218, background half: the foreground service follows running
/// scans, and a scan that finishes while the app is away gets a system
/// notification that opens it.
void main() {
  late _JobsApi api;
  late FakeScanTrackingService device;
  late ProviderContainer container;

  ProcessingJobsController tracker() =>
      container.read(processingJobsProvider.notifier);

  Future<void> pump(WidgetTester tester) async {
    api = _JobsApi();
    device = FakeScanTrackingService();
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          processingApiProvider.overrideWithValue(api),
          scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
          scanTrackingServiceProvider.overrideWithValue(device),
          scoreLibraryApiProvider.overrideWithValue(_LibraryApi()),
        ],
        child: MaterialApp(
          navigatorKey: navigatorKey,
          builder: (context, child) =>
              ScanBackgroundHost(navigatorKey: navigatorKey, child: child!),
          home: Builder(
            builder: (context) {
              container = ProviderScope.containerOf(context);
              return const Scaffold(body: Text('ROUTE:library'));
            },
          ),
          routes: {
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

  Future<void> poll(WidgetTester tester) async {
    await tester.pump(ProcessingTiming.pollInterval);
    await tester.pump();
  }

  void toBackground(WidgetTester tester) {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    addTearDown(
      () => tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      ),
    );
  }

  Future<void> end(WidgetTester tester) => tester.pumpWidget(const SizedBox());

  testWidgets('the service follows running scans, and stops when none is '
      'left', (tester) async {
    await pump(tester);
    api.script('a', [running(10), running(50), done(scoreId: 7)]);
    api.script('b', [running(10)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    expect(device.shown, [
      ScanStatusMessages.convertingInBackground(['Paraiso']),
    ]);
    expect(device.shown.single, 'Converting Paraiso…');

    tracker().track('b', title: 'Bahay Kubo');
    await tester.pump();
    expect(device.shown.last, 'Converting 2 scores…');

    // Progress alone doesn't touch the notification.
    await poll(tester);
    expect(device.shown, hasLength(2));

    tracker().forget('b');
    await tester.pump();
    expect(device.shown.last, 'Converting Paraiso…');
    expect(device.stops, 0);

    await poll(tester);
    expect(tracker().state['a']!.phase, TrackedPhase.complete);
    expect(device.stops, 1);
    await end(tester);
  });

  testWidgets('a paused scan keeps the service: it resumes by itself', (
    tester,
  ) async {
    await pump(tester);
    api.script('a', [running(10)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    expect(device.shown, hasLength(1));
    // isRunning covers paused (AC10), so nothing stops it.
    expect(device.stops, 0);
    await end(tester);
  });

  testWidgets('ready while the app is away: a notification that opens '
      'Playback', (tester) async {
    await pump(tester);
    api.script('a', [running(10), done(scoreId: 7)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    toBackground(tester);
    await poll(tester);

    expect(device.results, hasLength(1));
    final result = device.results.single;
    expect(result.jobId, 'a');
    expect(result.title, ScanStatusMessages.readyToast('Paraiso'));
    expect(result.text, ScanStatusMessages.readyNotificationHint);
    expect(result.ok, isTrue);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    device.tap('a');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:playback 7'), findsOneWidget);
    expect(tracker().state['a']!.read, isTrue, reason: 'seen now');
    expect(device.cleared, ['a'], reason: 'seen, so the shade lets go');
    await end(tester);
  });

  testWidgets('failed while away: the failure words, opening Processing', (
    tester,
  ) async {
    await pump(tester);
    api.script('a', [running(10), failed(FailureReason.noStaffDetected)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    toBackground(tester);
    await poll(tester);

    final result = device.results.single;
    expect(result.title, ScanStatusMessages.failedToast('Paraiso'));
    expect(result.text, ScanStatusMessages.failedRowHint);
    expect(result.ok, isFalse);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    device.tap('a');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:processing a'), findsOneWidget);
    await end(tester);
  });

  testWidgets('a failed retake says the earlier version is kept', (
    tester,
  ) async {
    await pump(tester);
    api.script('r', [running(10), failed(FailureReason.noStaffDetected)]);
    tracker().track('r', title: 'Paraiso', retakeOfScoreId: 7);
    await tester.pump();
    toBackground(tester);
    await poll(tester);
    expect(
      device.results.single.title,
      LibraryMessages.retakeFailed('Paraiso'),
    );
    await end(tester);
  });

  testWidgets('finished while on screen: no notification (the banner says '
      'it)', (tester) async {
    await pump(tester);
    api.script('a', [running(10), done(scoreId: 7)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    await poll(tester);
    expect(tracker().state['a']!.phase, TrackedPhase.complete);
    expect(device.results, isEmpty);
    await end(tester);
  });

  testWidgets('a forgotten job takes its notification away, and a tap on a '
      'job no longer followed opens nothing', (tester) async {
    await pump(tester);
    api.script('a', [running(10), done(scoreId: 7)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    toBackground(tester);
    await poll(tester);
    tracker().forget('a');
    await tester.pump();
    expect(device.cleared, ['a']);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    device.tap('a');
    await tester.pumpAndSettle();
    expect(find.text('ROUTE:library'), findsOneWidget);
    await end(tester);
  });
}
