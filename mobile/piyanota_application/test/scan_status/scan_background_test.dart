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
import 'package:piyanota_application/state/work_owner.dart';

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
    if (next is ProcessingException) throw next;
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

  late FakeNetwork network;

  Future<void> pump(WidgetTester tester, {bool signedIn = true}) async {
    api = _JobsApi();
    device = FakeScanTrackingService();
    network = FakeNetwork();
    final navigatorKey = GlobalKey<NavigatorState>();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          processingApiProvider.overrideWithValue(api),
          scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
          scanTrackingServiceProvider.overrideWithValue(device),
          scoreLibraryApiProvider.overrideWithValue(_LibraryApi()),
          networkAvailabilityProvider.overrideWithValue(
            network.controller.stream,
          ),
          networkCheckProvider.overrideWithValue(network.check),
          if (signedIn) signedInOverride(),
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
      ScanStatusMessages.scanningInBackground(['Paraiso']),
    ]);
    // AC12: "scan", not "convert".
    expect(device.shown.single, 'Scanning Paraiso…');

    tracker().track('b', title: 'Bahay Kubo');
    await tester.pump();
    expect(device.shown.last, 'Scanning 2 scores…');

    // Progress alone doesn't touch the notification.
    await poll(tester);
    expect(device.shown, hasLength(2));

    tracker().forget('b');
    await tester.pump();
    expect(device.shown.last, 'Scanning Paraiso…');
    expect(device.stops, 0);

    await poll(tester);
    expect(tracker().state['a']!.phase, TrackedPhase.complete);
    expect(device.stops, 1);
    await end(tester);
  });

  Future<void> pauseOffline(WidgetTester tester) async {
    // 30 s of failed polls: paused.
    for (var i = 0; i < 17; i++) {
      await poll(tester);
    }
    expect(tracker().state['a']!.phase, TrackedPhase.paused);
  }

  testWidgets('an offline pause keeps the service, waiting for the '
      'connection, and polling resumes by itself (review N1)', (tester) async {
    await pump(tester);
    api.script('a', [running(10), const ProcessingNetworkException()]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    expect(device.shown, ['Scanning Paraiso…']);

    await pauseOffline(tester);
    expect(device.stops, 0, reason: 'the engine must stay for the resume');
    expect(device.shown.last, ScanStatusMessages.waitingForConnection);
    expect(device.shown.last, 'Waiting for connection…');

    network.set(false);
    await tester.pump();
    api.script('a', [running(20)]);
    network.set(true);
    await tester.pump();
    await tester.pump();
    expect(tracker().state['a']!.phase, TrackedPhase.active);
    expect(device.shown.last, 'Scanning Paraiso…');
    expect(device.stops, 0);
    await end(tester);
  });

  testWidgets('one scan paused, another polled: still "Scanning"', (
    tester,
  ) async {
    await pump(tester);
    api.script('a', [running(10), const ProcessingNetworkException()]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    await pauseOffline(tester);
    api.script('b', [running(10)]);
    tracker().track('b', title: 'Bahay Kubo');
    await tester.pump();
    expect(device.shown.last, 'Scanning Bahay Kubo…');
    await end(tester);
  });

  testWidgets('a stop from the device side: the words go again on the next '
      'change, or when the app comes back (review M1)', (tester) async {
    await pump(tester);
    api.script('a', [running(10)]);
    api.script('b', [running(10)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    expect(device.shown, ['Scanning Paraiso…']);

    // Android 15's timeout while away: nothing is re-sent at once.
    toBackground(tester);
    device.stopByItself();
    await tester.pump();
    await poll(tester);
    expect(device.shown, hasLength(1), reason: 'silent while away');

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(device.shown, ['Scanning Paraiso…', 'Scanning Paraiso…']);

    // Same words after another native stop: a change re-sends them.
    device.stopByItself();
    await tester.pump();
    tracker().track('b', title: 'Bahay Kubo');
    await tester.pump();
    tracker().forget('b');
    await tester.pump();
    expect(device.shown.last, 'Scanning Paraiso…');
    expect(device.shown, hasLength(4));
    await end(tester);
  });

  testWidgets('before login nothing runs the service (review M1)', (
    tester,
  ) async {
    await pump(tester, signedIn: false);
    api.script('a', [running(10)]);
    tracker().track('a', title: 'Paraiso');
    await tester.pump();
    expect(device.shown, isEmpty);

    container.read(signedInProvider.notifier).set(true);
    await tester.pump();
    expect(device.shown, ['Scanning Paraiso…']);
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
    // AC7, word for word.
    expect(result.title, 'Your piano guide for Paraiso is ready.');
    expect(result.title, ScanStatusMessages.readyNotification('Paraiso'));
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
