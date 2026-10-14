import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/score_library_screen.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/screens/scan_status/scan_bell.dart';
import 'package:piyanota_application/screens/scan_status/scan_status_messages.dart';
import 'package:piyanota_application/screens/scan_status/scan_toast_host.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';
import 'package:piyanota_application/state/scan_job_store.dart';
import 'package:piyanota_application/state/score_library_providers.dart';

import '../processing/processing_fakes.dart'
    show FakeNetwork, MemoryScanJobStore, done, failed, running;

/// Answers each job's polls from its own script; the last entry repeats.
class _JobsApi implements ProcessingApi {
  final Map<String, List<Object>> scripts = {};
  final Map<String, Object> _last = {};
  final Map<String, int> fetches = {};
  final List<String> cancelled = [];

  void script(String jobId, List<Object> entries) =>
      (scripts[jobId] ??= []).addAll(entries);

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    fetches[jobId] = (fetches[jobId] ?? 0) + 1;
    final queue = scripts[jobId] ?? [];
    final next = queue.isNotEmpty ? queue.removeAt(0) : _last[jobId];
    if (next != null) _last[jobId] = next;
    if (next is ProcessingException) throw next;
    if (next is ProcessingStatus) return next;
    throw StateError('Nothing scripted for $jobId');
  }

  @override
  Future<void> cancelJob(String jobId) async => cancelled.add(jobId);
}

class _LibraryApi implements ScoreLibraryApi {
  _LibraryApi(this.scores);

  final List<ScoreSummary> scores;
  int fetchCalls = 0;
  final List<int> deleted = [];

  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async {
    fetchCalls++;
    return [...scores];
  }

  @override
  Future<void> deleteScore(int scoreId) async => deleted.add(scoreId);

  @override
  Future<void> recordOpened(int scoreId) async {}
}

final _scores = [
  ScoreSummary(
    scoreId: 102,
    title: 'Paraiso',
    lastActivityAt: DateTime(2026, 9, 28, 12),
  ),
  ScoreSummary(
    scoreId: 103,
    title: 'Bahay Kubo',
    lastActivityAt: DateTime(2026, 9, 21, 12),
  ),
];

const _library = 'ROUTE:library';

class _App {
  final api = _JobsApi();
  final libraryApi = _LibraryApi(_scores);
  final store = MemoryScanJobStore();
  final network = FakeNetwork();
  late WidgetTester tester;

  ProviderContainer get container => ProviderScope.containerOf(
    tester.element(find.byType(MaterialApp)),
    listen: false,
  );

  ProcessingJobsController get tracker =>
      container.read(processingJobsProvider.notifier);

  Map<String, TrackedJob> get jobs => container.read(processingJobsProvider);

  List<Override> get overrides => [
    processingApiProvider.overrideWithValue(api),
    scoreLibraryApiProvider.overrideWithValue(libraryApi),
    scanJobStoreProvider.overrideWithValue(store),
    networkAvailabilityProvider.overrideWithValue(network.controller.stream),
  ];

  /// [home] under the app-wide toast host, with animations off so the
  /// bell's spinning ring doesn't keep pumpAndSettle busy.
  Future<void> pump(WidgetTester tester, Widget home) async {
    this.tester = tester;
    FlutterSecureStorage.setMockInitialValues({});
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.reset);
    final navigatorKey = GlobalKey<NavigatorState>();
    final routes = ScanRouteStack();
    await tester.pumpWidget(
      ProviderScope(
        overrides: overrides,
        child: MaterialApp(
          navigatorKey: navigatorKey,
          navigatorObservers: [routes],
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(disableAnimations: true),
            child: ScanToastHost(
              navigatorKey: navigatorKey,
              routes: routes,
              child: child!,
            ),
          ),
          home: home,
          routes: {
            AppRoutes.scoreLibrary: (_) => const Scaffold(body: Text(_library)),
            AppRoutes.login: (_) => const Scaffold(body: Text('ROUTE:login')),
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
              return ProcessingScreen(jobId: args.jobId, title: args.title);
            },
          },
        ),
      ),
    );
    await tester.pump();
  }

  /// One poll round for every followed job.
  Future<void> poll() async {
    await tester.pump(ProcessingTiming.pollInterval);
    await tester.pump();
  }

  /// Unmounts so the tracker's timers go with the container.
  Future<void> end() => tester.pumpWidget(const SizedBox());
}

/// The bell on the header's blue, as the library draws it.
const _bellHome = Scaffold(
  backgroundColor: Color(0xFF2A5EA8),
  body: Center(child: ScanBell()),
);

Finder get _badge => find.byKey(const ValueKey('scan-bell-badge'));
Finder get _ring => find.byKey(const ValueKey('scan-bell-ring'));

String _badgeText(WidgetTester tester) => tester
    .widget<Text>(find.descendant(of: _badge, matching: find.byType(Text)))
    .data!;

Future<void> _openPanel(WidgetTester tester) async {
  await tester.tap(find.byType(ScanBell));
  await tester.pumpAndSettle();
}

Finder _row(String jobId) => find.byKey(ValueKey('scan-row-$jobId'));

void main() {
  group('AC5/AC9 bell', () {
    testWidgets('idle: plain bell, no ring, no badge', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      expect(find.byIcon(Icons.notifications_none_rounded), findsOneWidget);
      expect(_ring, findsNothing);
      expect(_badge, findsNothing);
      await app.end();
    });

    testWidgets('running scans ring the bell but never add to the badge', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(10)]);
      app.api.script('b', [running(20)]);
      app.tracker.track('a', title: 'A');
      app.tracker.track('b', title: 'B');
      await tester.pump();
      expect(_ring, findsOneWidget);
      expect(_badge, findsNothing);
      await app.end();
    });

    testWidgets(
      'completed and failed unread scans count; ring while any runs',
      (tester) async {
        final app = _App();
        await app.pump(tester, _bellHome);
        app.api.script('a', [running(10), done(scoreId: 1)]);
        app.api.script('b', [running(10), failed(FailureReason.stageTimeout)]);
        app.api.script('c', [running(10)]);
        for (final id in ['a', 'b', 'c']) {
          app.tracker.track(id, title: id);
        }
        await tester.pump();
        await app.poll();
        expect(_badgeText(tester), '2');
        expect(_ring, findsOneWidget, reason: 'c is still running');

        app.tracker.markRead('a');
        await tester.pump();
        expect(_badgeText(tester), '1');
        await app.end();
      },
    );

    testWidgets('the badge caps at 9+', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      for (var i = 1; i <= 12; i++) {
        app.api.script('j$i', [done(scoreId: i)]);
        app.tracker.track('j$i', title: 'Score $i');
      }
      await tester.pump();
      await tester.pump();
      expect(_badgeText(tester), '9+');
      expect(_ring, findsNothing);
      await app.end();
    });
  });

  group('AC6 panel', () {
    testWidgets('empty state', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      await _openPanel(tester);
      expect(find.text(ScanStatusMessages.empty), findsOneWidget);
      expect(find.byKey(const ValueKey('scan-mark-all-read')), findsNothing);
      await app.end();
    });

    testWidgets('rows newest first, with each state\'s copy; a running row '
        'turns into its completed row in place', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('old', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('old', title: 'Bahay Kubo', scoreId: 103);
      await tester.pump(const Duration(seconds: 1));
      app.api.script('new', [running(40), done(scoreId: 102)]);
      app.tracker.track('new', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      await _openPanel(tester);

      expect(
        tester.getTopLeft(_row('new')).dy,
        lessThan(tester.getTopLeft(_row('old')).dy),
      );
      expect(
        find.descendant(of: _row('new'), matching: find.byType(RichText)),
        findsWidgets,
      );
      expect(
        find.textContaining(
          'Paraiso${ScanStatusMessages.processingRow}',
          findRichText: true,
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: _row('new'),
          matching: find.byType(LinearProgressIndicator),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: _row('old'),
          matching: find.textContaining(
            'Bahay Kubo${ScanStatusMessages.failedRow}',
            findRichText: true,
          ),
        ),
        findsOneWidget,
      );
      expect(find.text(ScanStatusMessages.failedRowHint), findsOneWidget);
      // A running row can't be swiped away; a finished one can.
      expect(find.byKey(const ValueKey('scan-dismiss-new')), findsNothing);
      expect(find.byKey(const ValueKey('scan-dismiss-old')), findsOneWidget);

      await app.poll();
      expect(_row('new'), findsOneWidget, reason: 'same row, not a new one');
      expect(
        find.textContaining(
          'Paraiso${ScanStatusMessages.readyRow}',
          findRichText: true,
        ),
        findsOneWidget,
      );
      expect(find.text('Just now'), findsOneWidget);
      expect(
        find.descendant(
          of: _row('new'),
          matching: find.byKey(const ValueKey('scan-row-unread')),
        ),
        findsOneWidget,
      );
      await app.end();
    });

    testWidgets('a score never has two rows', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('first', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('first', title: 'Paraiso', scoreId: 102);
      await tester.pump(const Duration(seconds: 1));
      app.api.script('again', [running(5)]);
      app.tracker.track('again', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      await _openPanel(tester);
      expect(_row('again'), findsOneWidget);
      expect(_row('first'), findsNothing);
      await app.end();
    });

    testWidgets('Mark all as read clears the dots and the badge', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [done(scoreId: 1)]);
      app.api.script('b', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'A');
      app.tracker.track('b', title: 'B');
      await tester.pump();
      await _openPanel(tester);
      expect(find.byKey(const ValueKey('scan-row-unread')), findsNWidgets(2));
      await tester.tap(find.byKey(const ValueKey('scan-mark-all-read')));
      await tester.pump();
      expect(find.byKey(const ValueKey('scan-row-unread')), findsNothing);
      expect(app.jobs.values.every((job) => job.read), isTrue);
      expect(_badge, findsNothing);
      await app.end();
    });

    testWidgets('swiping a finished row dismisses it', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [done(scoreId: 1)]);
      app.tracker.track('a', title: 'A');
      await tester.pump();
      await _openPanel(tester);
      await tester.drag(_row('a'), const Offset(-800, 0));
      await tester.pumpAndSettle();
      expect(_row('a'), findsNothing);
      expect(find.text(ScanStatusMessages.empty), findsOneWidget);
      expect(app.jobs['a']!.dismissed, isTrue);
      await app.end();
    });

    testWidgets('scrolls when it has many rows', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      for (var i = 1; i <= ScanHistoryLimits.maxItems; i++) {
        app.api.script('j$i', [done(scoreId: i)]);
        app.tracker.track('j$i', title: 'Score $i');
        await tester.pump(const Duration(milliseconds: 10));
      }
      await _openPanel(tester);
      final screenHeight =
          tester.view.physicalSize.height / tester.view.devicePixelRatio;
      expect(
        tester.getTopLeft(_row('j1')).dy,
        greaterThan(screenHeight),
        reason: 'oldest is off-screen',
      );
      await tester.scrollUntilVisible(
        _row('j1'),
        200,
        scrollable: find
            .ancestor(
              of: _row('j${ScanHistoryLimits.maxItems}'),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      expect(
        tester.getTopLeft(_row('j1')).dy,
        lessThan(
          tester.view.physicalSize.height / tester.view.devicePixelRatio,
        ),
      );
      await app.end();
    });

    testWidgets('a completed row opens Playback and is marked read', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [done(scoreId: 102)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      await _openPanel(tester);
      await tester.tap(_row('a'));
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:playback 102'), findsOneWidget);
      expect(app.jobs['a']!.read, isTrue);
      await app.end();
    });

    testWidgets('a running row opens Processing', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(40)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      await _openPanel(tester);
      await tester.tap(_row('a'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(ProcessingScreen), findsOneWidget);
      expect(find.byType(ScanPanel), findsNothing);
      await app.end();
    });

    testWidgets('a failed row opens the failure view', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      await _openPanel(tester);
      await tester.tap(_row('a'));
      await tester.pumpAndSettle();
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(app.jobs['a']!.read, isTrue);
      await app.end();
    });
  });

  group('AC2/AC4 library processing card', () {
    Finder card(String jobId) => find.byKey(ValueKey('scanning-$jobId'));

    testWidgets('shows title, bar and "Converting… N%", dimmed thumbnail', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [running(40)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();

      expect(card('a'), findsOneWidget);
      expect(
        find.descendant(of: card('a'), matching: find.text('Paraiso')),
        findsOneWidget,
      );
      expect(find.text(ScanStatusMessages.converting(40)), findsOneWidget);
      expect(
        find.descendant(
          of: card('a'),
          matching: find.byType(LinearProgressIndicator),
        ),
        findsOneWidget,
      );
      final dim = tester.widget<Opacity>(
        find.byKey(const ValueKey('scanning-thumbnail')),
      );
      expect(dim.opacity, lessThan(1));
      // The other score is still a normal card.
      expect(find.byType(ScoreCard), findsOneWidget);
      await app.end();
    });

    testWidgets('a scan the list does not have yet still gets a card', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('new', [running(5)]);
      app.tracker.track('new', title: 'Ave Maria');
      await tester.pump();
      expect(find.byKey(const ValueKey('scan-job-new')), findsOneWidget);
      expect(find.text('Ave Maria'), findsOneWidget);
      await app.end();
    });

    testWidgets('tap opens Processing', (tester) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [running(40)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      await tester.tap(card('a'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(ProcessingScreen), findsOneWidget);
      await app.end();
    });

    testWidgets('long-press asks, then cancels through PIYA-114', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [running(40)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();

      await tester.longPress(card('a'));
      await tester.pumpAndSettle();
      expect(find.text(ProcessingMessages.cancelTitle), findsOneWidget);
      await tester.tap(find.text(ProcessingMessages.keepScanning));
      await tester.pumpAndSettle();
      expect(app.api.cancelled, isEmpty);

      await tester.longPress(card('a'));
      await tester.pumpAndSettle();
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await tester.pumpAndSettle();
      expect(app.api.cancelled, ['a']);
      expect(app.jobs, isNot(contains('a')));
      expect(find.text(ProcessingMessages.scanCancelled), findsOneWidget);
      expect(card('a'), findsNothing);
      await app.end();
    });

    testWidgets('completion turns it into a normal card in place, no reload', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      final fetches = app.libraryApi.fetchCalls;
      app.api.script('a', [running(40), done(scoreId: 102)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      expect(card('a'), findsOneWidget);
      await app.poll();
      expect(card('a'), findsNothing);
      expect(find.byType(ScoreCard), findsNWidgets(2));
      expect(app.libraryApi.fetchCalls, fetches);
      // Tapping it now plays it.
      await tester.tap(find.text('Paraiso'));
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:playback 102'), findsOneWidget);
      await app.end();
    });

    testWidgets('a failed scan shows as failed and opens the failure view', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      await tester.pump(ScanToastHost.showFor);
      expect(find.byKey(const ValueKey('score-card-failed')), findsOneWidget);
      await tester.tap(find.text('Paraiso'));
      await tester.pumpAndSettle();
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      await app.end();
    });
  });

  group('AC10 paused and stalled', () {
    testWidgets('no connection: Paused with Retry, then resumes on its own', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [
        running(40),
        for (var i = 0; i < 30; i++) const ProcessingNetworkException(),
      ]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      for (var i = 0; i < 20; i++) {
        await app.poll();
      }
      expect(app.jobs['a']!.phase, TrackedPhase.paused);
      expect(find.text(ScanStatusMessages.paused), findsOneWidget);
      expect(find.byKey(const ValueKey('scanning-retry')), findsOneWidget);

      // The phone goes offline, then back online: polling restarts.
      app.api.scripts['a']!
        ..clear()
        ..add(running(60));
      app.network.set(false);
      await tester.pump();
      app.network.set(true);
      await tester.pump();
      await tester.pump();
      expect(app.jobs['a']!.phase, TrackedPhase.active);
      expect(find.text(ScanStatusMessages.converting(60)), findsOneWidget);
      await app.end();
    });

    testWidgets('Retry on the card polls again', (tester) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [
        running(40),
        for (var i = 0; i < 30; i++) const ProcessingNetworkException(),
      ]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      for (var i = 0; i < 20; i++) {
        await app.poll();
      }
      app.api.scripts['a']!
        ..clear()
        ..add(running(70));
      await tester.tap(find.byKey(const ValueKey('scanning-retry')));
      await tester.pump();
      await tester.pump();
      expect(find.text(ScanStatusMessages.converting(70)), findsOneWidget);
      await app.end();
    });

    testWidgets('90 s without movement says it is a long piece', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [running(40)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      for (
        var t = Duration.zero;
        t <= ProcessingTiming.stallAfter;
        t += ProcessingTiming.pollInterval
      ) {
        await app.poll();
      }
      expect(find.text(ScanStatusMessages.stalled), findsOneWidget);
      await app.end();
    });
  });

  group('AC8 survives restarts', () {
    testWidgets('restores cards and rows, re-polls unfinished jobs and shows '
        'what finished while closed', (tester) async {
      final app = _App();
      app.store.stored = ScanJobStore.encodeJobs([
        TrackedJob(
          jobId: 'running',
          title: 'Paraiso',
          retakeOfScoreId: 102,
          phase: TrackedPhase.paused,
          percent: 30,
          createdAt: DateTime.now(),
        ),
        TrackedJob(
          jobId: 'finished-while-closed',
          title: 'Bahay Kubo',
          scoreId: 103,
          percent: 50,
          createdAt: DateTime.now(),
        ),
      ]);
      app.api.script('running', [running(45)]);
      app.api.script('finished-while-closed', [done(scoreId: 103)]);
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();

      expect(app.api.fetches['running'], 1);
      expect(app.api.fetches['finished-while-closed'], 1);
      final restored = app.jobs['running']!;
      expect(restored.retakeOfScoreId, 102);
      expect(restored.phase, TrackedPhase.active);
      expect(find.byKey(const ValueKey('scanning-running')), findsOneWidget);
      expect(find.text(ScanStatusMessages.converting(45)), findsOneWidget);
      expect(app.jobs['finished-while-closed']!.phase, TrackedPhase.complete);
      // Seen finishing on the re-poll while the app is open: the bell
      // counts it and the toast says so.
      expect(
        find.text(ScanStatusMessages.readyToast('Bahay Kubo')),
        findsOneWidget,
      );
      expect(_badgeText(tester), '1');
      await app.end();
    });

    test('the stored job keeps retakeOfScoreId and bell state', () {
      final encoded = ScanJobStore.encodeJobs([
        TrackedJob(
          jobId: 'a',
          title: 'Paraiso',
          retakeOfScoreId: 102,
          scoreId: 7,
          phase: TrackedPhase.complete,
          read: true,
          dismissed: true,
          finishedAt: DateTime.utc(2026, 10, 14),
          status: done(scoreId: 7),
        ),
        const TrackedJob(jobId: 'gone', phase: TrackedPhase.cancelled),
      ]);
      final jobs = ScanJobStore.decodeJobs(encoded);
      expect(jobs, hasLength(1), reason: 'a cancelled scan is not kept');
      final job = jobs.single;
      expect(job.retakeOfScoreId, 102);
      expect(job.libraryScoreId, 7);
      expect(job.read, isTrue);
      expect(job.dismissed, isTrue);
      expect(job.finishedAt, DateTime.utc(2026, 10, 14));
      expect(ScanJobStore.decodeJobs('not json'), isEmpty);
    });

    testWidgets('keeps the latest 20 finished items, none older than 7 days', (
      tester,
    ) async {
      final app = _App();
      final now = DateTime.now();
      app.store.stored = ScanJobStore.encodeJobs([
        for (var i = 0; i < 25; i++)
          TrackedJob(
            jobId: 'j$i',
            title: 'S$i',
            phase: TrackedPhase.complete,
            createdAt: now.subtract(Duration(minutes: i)),
            finishedAt: now.subtract(Duration(minutes: i)),
          ),
        TrackedJob(
          jobId: 'ancient',
          phase: TrackedPhase.failed,
          createdAt: now.subtract(const Duration(days: 8)),
          finishedAt: now.subtract(const Duration(days: 8)),
        ),
      ]);
      await app.pump(tester, _bellHome);
      await tester.pump();
      expect(app.jobs, hasLength(ScanHistoryLimits.maxItems));
      expect(app.jobs, isNot(contains('ancient')));
      expect(app.jobs, isNot(contains('j24')));
      expect(app.jobs, contains('j0'));
      expect(app.store.storedJobs, hasLength(ScanHistoryLimits.maxItems));
      await app.end();
    });
  });

  group('AC7 in-app toast', () {
    testWidgets('a scan finishing elsewhere shows "[Score] is ready." Open → '
        'Playback', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(40), done(scoreId: 102)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      expect(find.byKey(const ValueKey('scan-toast-open')), findsNothing);
      await app.poll();
      expect(
        find.text(ScanStatusMessages.readyToast('Paraiso')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const ValueKey('scan-toast-open')));
      await tester.pumpAndSettle();
      expect(find.text('ROUTE:playback 102'), findsOneWidget);
      expect(find.text(ScanStatusMessages.readyToast('Paraiso')), findsNothing);
      await app.end();
    });

    testWidgets('a failure says so; a failed retake keeps the old wording', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(40), failed(FailureReason.stageTimeout)]);
      app.api.script('b', [running(40), failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      await app.poll();
      expect(
        find.text(ScanStatusMessages.failedToast('Paraiso')),
        findsOneWidget,
      );
      expect(find.text(ScanStatusMessages.view), findsOneWidget);
      await tester.pump(ScanToastHost.showFor);
      expect(
        find.text(ScanStatusMessages.failedToast('Paraiso')),
        findsNothing,
      );

      app.tracker.track('b', title: 'Bahay Kubo', retakeOfScoreId: 103);
      await tester.pump();
      await app.poll();
      expect(
        find.text(LibraryMessages.retakeFailed('Bahay Kubo')),
        findsOneWidget,
      );
      await tester.pump(ScanToastHost.showFor);
      await app.end();
    });

    testWidgets('not shown on that scan\'s own Processing screen', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(40), failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      tester
          .state<NavigatorState>(find.byType(Navigator).first)
          .pushNamed(
            AppRoutes.processing,
            arguments: const ProcessingArguments(jobId: 'a', title: 'Paraiso'),
          );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      await app.poll();
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(find.byKey(const ValueKey('scan-toast-open')), findsNothing);
      await app.end();
    });
  });

  group('AC3 failure view Delete', () {
    testWidgets('confirms, deletes on the server, back to the library', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      tester
          .state<NavigatorState>(find.byType(Navigator).first)
          .pushNamed(
            AppRoutes.processing,
            arguments: const ProcessingArguments(jobId: 'a', title: 'Paraiso'),
          );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('failure-delete')));
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.deleteDialogTitle), findsOneWidget);
      await tester.tap(find.text(LibraryMessages.deleteCancel));
      await tester.pumpAndSettle();
      expect(app.libraryApi.deleted, isEmpty);

      await tester.tap(find.byKey(const ValueKey('failure-delete')));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(LibraryMessages.deleteConfirm),
        ),
      );
      await tester.pumpAndSettle();
      expect(app.libraryApi.deleted, [102]);
      expect(app.jobs, isNot(contains('a')));
      expect(find.text(_library), findsOneWidget);
      await app.end();
    });

    testWidgets('not offered for a failed retake of a completed score', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso', retakeOfScoreId: 102);
      await tester.pump();
      tester
          .state<NavigatorState>(find.byType(Navigator).first)
          .pushNamed(
            AppRoutes.processing,
            arguments: const ProcessingArguments(jobId: 'a', title: 'Paraiso'),
          );
      await tester.pumpAndSettle();
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(find.byKey(const ValueKey('failure-delete')), findsNothing);
      await app.end();
    });
  });

  group('review fixes', () {
    testWidgets('deleting a score forgets its scans, also on the device', (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, const ScoreLibraryScreen());
      await tester.pumpAndSettle();
      app.api.script('a', [failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso', scoreId: 102);
      await tester.pump();
      await tester.pump(ScanToastHost.showFor);
      expect(_badge, findsOneWidget);

      await tester.tap(
        find.bySemanticsLabel(LibraryMessages.deleteSemantics('Paraiso')),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(LibraryMessages.deleteConfirm),
        ),
      );
      await tester.pumpAndSettle();
      expect(app.libraryApi.deleted, [102]);
      expect(app.jobs, isEmpty);
      expect(_badge, findsNothing);
      expect(app.store.storedJobs, isEmpty, reason: 'not back after restart');
      await app.end();
    });

    test('one unreadable stored entry drops only itself', () {
      final good = ScanJobStore.encodeJobs([
        const TrackedJob(jobId: 'good', title: 'Paraiso', scoreId: 102),
      ]);
      final raw =
          '[${good.substring(1, good.length - 1)},'
          '"not a job",{"jobId":5,"phase":"active"},'
          '{"jobId":"bad-phase","phase":"exploded"},'
          '{"jobId":"bad-status","phase":"failed","status":{"status":7}}]';
      final jobs = ScanJobStore.decodeJobs(raw);
      // A broken status is dropped but its job is kept (same policy as the
      // API parser); entries with no usable id or phase drop alone.
      expect(jobs.map((job) => job.jobId), ['good', 'bad-status']);
      expect(jobs.last.status, isNull);
    });

    testWidgets("the panel's relative times move on while it is open", (
      tester,
    ) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [done(scoreId: 1)]);
      app.tracker.track('a', title: 'A');
      await tester.pump();
      await _openPanel(tester);
      expect(find.text('Just now'), findsOneWidget);
      await tester.pump(const Duration(minutes: 2));
      expect(find.text('2 min ago'), findsOneWidget);
      await app.end();
    });

    testWidgets("a dialog over that scan's Processing still counts as "
        'watching: no toast, and not marked read behind it', (tester) async {
      final app = _App();
      await app.pump(tester, _bellHome);
      app.api.script('a', [running(40), failed(FailureReason.stageTimeout)]);
      app.tracker.track('a', title: 'Paraiso');
      await tester.pump();
      final navigator = tester.state<NavigatorState>(
        find.byType(Navigator).first,
      );
      unawaited(
        navigator.pushNamed(
          AppRoutes.processing,
          arguments: const ProcessingArguments(jobId: 'a', title: 'Paraiso'),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      unawaited(
        showDialog<void>(
          context: navigator.context,
          builder: (_) => const AlertDialog(content: Text('popup')),
        ),
      );
      await tester.pump();
      await app.poll();
      expect(app.jobs['a']!.phase, TrackedPhase.failed);
      expect(find.byKey(const ValueKey('scan-toast-open')), findsNothing);
      expect(app.jobs['a']!.read, isFalse);
      await app.end();
    });
  });
}
