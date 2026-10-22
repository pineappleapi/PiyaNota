import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/screens/processing/processing_messages.dart';
import 'package:piyanota_application/screens/processing/processing_screen.dart';
import 'package:piyanota_application/screens/scan_status/scan_status_messages.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import 'processing_fakes.dart';

/// [pumpProcessing] leaves the clock 1.1 s after the first poll, so each
/// call here crosses exactly one 2 s poll and lets the percent tween end.
Future<void> _nextPoll(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 1300));
  await tester.pump(const Duration(milliseconds: 700));
}

/// From [pumpProcessing]'s first good poll, far enough that polls failing
/// from the next one on have failed for [ProcessingTiming.pauseAfter].
Future<void> _pumpPastPause(WidgetTester tester) async {
  final end = ProcessingTiming.pauseAfter + ProcessingTiming.pollInterval * 2;
  for (var t = Duration.zero; t < end; t += ProcessingTiming.pollInterval) {
    await tester.pump(ProcessingTiming.pollInterval);
  }
  await tester.pump();
}

Future<void> _settleNavigation(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
}

Finder get _retakeWording =>
    find.textContaining(RegExp('retake', caseSensitive: false));

TextButton _cancelButton(WidgetTester tester) => tester.widget<TextButton>(
  find.ancestor(
    of: find.text(ProcessingMessages.cancelScan),
    matching: find.byWidgetPredicate((w) => w is TextButton),
  ),
);

void main() {
  group('progress (AC1–AC3, AC8)', () {
    testWidgets('0% → 75% → 100%, then Playback within 2 s', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(0, stage: ProcessingStage.queued, page: null, seconds: null),
          running(75, seconds: 120),
          running(80, seconds: 45),
          done(scoreId: 7),
        ]),
      );
      await pumpProcessing(tester, h);

      expect(find.text(ProcessingMessages.heading), findsOneWidget);
      expect(find.text('0%'), findsOneWidget);
      expect(find.text('Waiting in line…'), findsOneWidget);
      expect(find.textContaining(RegExp(r'page \d')), findsNothing);
      expect(find.textContaining('left'), findsNothing);
      expect(find.text(ProcessingMessages.helper), findsOneWidget);

      await _nextPoll(tester);
      expect(find.text('75%'), findsOneWidget);
      expect(find.text('page 2/3'), findsOneWidget);
      expect(find.text('approx. 2 min.left'), findsOneWidget);
      expect(find.text('Reading the notes…'), findsOneWidget);
      expect(
        find.bySemanticsLabel(
          'Processing, 75 percent, page 2 of 3, about 2 minutes left',
        ),
        findsOneWidget,
      );
      final bar = tester.widget<LinearProgressIndicator>(
        find.byType(LinearProgressIndicator),
      );
      expect(bar.value, closeTo(0.75, 0.001));

      await _nextPoll(tester);
      expect(find.text('less than a minute left'), findsOneWidget);
      expect(h.api.fetches, 3);

      // The poll that says complete lands 0.9 s into this step; the tween
      // then runs from the next frame.
      await _nextPoll(tester);
      expect(h.job!.phase, TrackedPhase.complete);
      expect(find.text('100%'), findsOneWidget);
      expect(find.text('page 3/3'), findsOneWidget);
      expect(find.text('Analyzing complete!'), findsOneWidget);
      expect(find.textContaining('left'), findsNothing);
      expect(_cancelButton(tester).onPressed, isNull);
      expect(find.textContaining('ROUTE:playback'), findsNothing);

      // 1.1 s since complete; the hold is 1.2 s, so 1.3 s is inside AC8's 2 s.
      // The extra zero-time frame is the push's first frame, which the
      // HeroController keeps offstage; no clock moves.
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pump();
      expect(find.text(playbackMarker(7)), findsOneWidget);
      await _settleNavigation(tester);
      expect(find.text(ProcessingMessages.heading), findsNothing);
    });

    testWidgets('a job already complete on arrival opens Playback at once', (
      tester,
    ) async {
      final h = ProcessingHarness(ScriptedProcessingApi([done(scoreId: 4)]));
      await pumpProcessing(tester, h);
      expect(find.text(playbackMarker(4)), findsOneWidget);
    });

    testWidgets('no scoreId on complete: library with a note', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(90), done(scoreId: null)]),
      );
      await pumpProcessing(tester, h);
      await _nextPoll(tester);
      await tester.pump(ProcessingScreen.completionHold);
      await _settleNavigation(tester);
      expect(find.text(kLibrary), findsOneWidget);
      expect(find.text(ProcessingMessages.readyInLibrary), findsOneWidget);
    });

    testWidgets('the helper changes after 90 s without movement', (
      tester,
    ) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(40)]));
      await pumpProcessing(tester, h);
      for (var i = 0; i < ProcessingTiming.stallAfterPolls; i++) {
        await tester.pump(ProcessingTiming.pollInterval);
      }
      expect(find.text(ProcessingMessages.stalled), findsOneWidget);
      expect(find.text(ProcessingMessages.helper), findsNothing);
    });
  });

  group('cancel (AC4)', () {
    testWidgets('asks first; Keep scanning changes nothing', (tester) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      expect(find.text(ProcessingMessages.cancelTitle), findsOneWidget);
      expect(find.text(ProcessingMessages.cancelBody), findsOneWidget);

      await tester.tap(find.text(ProcessingMessages.keepScanning));
      await _settleNavigation(tester);
      expect(find.text(ProcessingMessages.cancelTitle), findsNothing);
      expect(h.api.cancels, 0);
      expect(find.text('30%'), findsOneWidget);
    });

    testWidgets('confirmed: cancels, forgets the job, back to library', (
      tester,
    ) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await _settleNavigation(tester);

      expect(h.api.cancels, 1);
      expect(find.text(kLibrary), findsOneWidget);
      expect(find.text(ProcessingMessages.scanCancelled), findsOneWidget);
      expect(h.job, isNull);
      final fetches = h.api.fetches;
      await tester.pump(ProcessingTiming.pollInterval * 3);
      expect(h.api.fetches, fetches, reason: 'polling stopped');
    });

    testWidgets('works while still queued', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(0, stage: ProcessingStage.queued, page: null, seconds: null),
        ]),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await _settleNavigation(tester);
      expect(find.text(kLibrary), findsOneWidget);
    });

    testWidgets('finished first (409): says so and opens Playback', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(95)])
          ..cancelError = const ProcessingConflictException(),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      h.api.then([done(scoreId: 3)]);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await tester.pump();
      expect(find.text(ProcessingMessages.alreadyFinished), findsOneWidget);
      await tester.pump(ProcessingScreen.completionHold);
      await _settleNavigation(tester);
      expect(find.text(playbackMarker(3)), findsOneWidget);
    });

    testWidgets('finished while the dialog was open, then cancel fails: '
        'still opens Playback (AC8)', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(90)])
          ..cancelError = const ProcessingNetworkException(),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      h.api.then([done(scoreId: 3)]);
      await _nextPoll(tester);
      expect(h.job!.phase, TrackedPhase.complete);
      expect(find.text(ProcessingMessages.cancelTitle), findsOneWidget);
      expect(find.text(playbackMarker(3)), findsNothing, reason: 'waits');

      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await tester.pump();
      expect(find.text(ProcessingMessages.alreadyFinished), findsOneWidget);
      expect(find.text(ProcessingMessages.cancelFailed), findsNothing);
      await tester.pump(ProcessingScreen.completionHold);
      await _settleNavigation(tester);
      expect(find.text(playbackMarker(3)), findsOneWidget);
    });

    testWidgets('finished while the cancel request was out, then it fails: '
        'still opens Playback (AC8)', (tester) async {
      final gate = Completer<void>();
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(90)])
          ..cancelGate = gate
          ..cancelError = const ProcessingServerException(),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await _settleNavigation(tester);
      expect(h.api.cancels, 1);

      h.api.then([done(scoreId: 3)]);
      await _nextPoll(tester);
      expect(h.job!.phase, TrackedPhase.complete);
      expect(find.text(playbackMarker(3)), findsNothing);

      gate.complete();
      await tester.pump();
      await tester.pump(ProcessingScreen.completionHold);
      await _settleNavigation(tester);
      expect(find.text(playbackMarker(3)), findsOneWidget);
    });

    testWidgets('failed while the dialog was open, then cancel fails: '
        'shows the failure', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(40)])
          ..cancelError = const ProcessingNetworkException(),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      h.api.then([failed(FailureReason.noStaffDetected, pageIndex: 1)]);
      await _nextPoll(tester);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await _settleNavigation(tester);
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(find.text('Retake page 2'), findsOneWidget);
    });

    testWidgets('a failed cancel request stays and says so', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([running(30)])
          ..cancelError = const ProcessingNetworkException(),
      );
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.cancelScan));
      await _settleNavigation(tester);
      await tester.tap(find.text(ProcessingMessages.confirmCancel));
      await _settleNavigation(tester);
      expect(find.text(ProcessingMessages.cancelFailed), findsOneWidget);
      expect(find.text(ProcessingMessages.heading), findsOneWidget);
      expect(h.job, isNotNull);
    });
  });

  group('leaving keeps the job followed', () {
    final exits = <String, Future<void> Function(WidgetTester)>{
      'Convert in Background': (tester) =>
          tester.tap(find.text(ProcessingMessages.convertInBackground)),
      'back arrow': (tester) =>
          tester.tap(find.byTooltip(ProcessingMessages.backToLibrary)),
      'system Back': (tester) async {
        await tester.binding.handlePopRoute();
        // Leaving now waits on the notification check (review M7), which
        // settles a frame later on this path than after a tap.
        await tester.pump();
      },
    };
    for (final MapEntry(key: name, value: leave) in exits.entries) {
      testWidgets(name, (tester) async {
        final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
        await pumpProcessing(tester, h);
        await leave(tester);
        await _settleNavigation(tester);
        expect(find.text(kLibrary), findsOneWidget);
        expect(find.text(ProcessingMessages.heading), findsNothing);

        final fetches = h.api.fetches;
        h.api.then([running(60)]);
        await tester.pump(ProcessingTiming.pollInterval * 2);
        expect(h.api.fetches, greaterThan(fetches));
        expect(h.job!.percent, 60);
        expect(h.job!.title, kTitle, reason: 'labels the row later');
      });
    }
  });

  group('Convert in Background asks for notifications (PIYA-218)', () {
    testWidgets('once, on Android 13+: Allow shows the system prompt and '
        'goes on to the library', (tester) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
      h.notifications.askFirst = true;
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.convertInBackground));
      await _settleNavigation(tester);
      expect(find.text(ScanStatusMessages.notificationsTitle), findsOneWidget);
      expect(find.text(kLibrary), findsNothing);

      await tester.tap(find.text(ScanStatusMessages.notificationsAllow));
      await _settleNavigation(tester);
      expect(h.notifications.asks, 1);
      expect(h.notifications.requests, 1);
      expect(find.text(kLibrary), findsOneWidget);
      expect(h.job, isNotNull, reason: 'still followed');
    });

    testWidgets('"Not now" still leaves, without the prompt; a finish while '
        'the question is open does not move the screen under it', (
      tester,
    ) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
      h.notifications.askFirst = true;
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.convertInBackground));
      await _settleNavigation(tester);
      h.api.then([done()]);
      await tester.pump(ProcessingTiming.pollInterval);
      await _settleNavigation(tester);
      expect(h.job!.phase, TrackedPhase.complete);
      expect(find.text(ScanStatusMessages.notificationsTitle), findsOneWidget);

      await tester.tap(find.text(ScanStatusMessages.notificationsLater));
      await _settleNavigation(tester);
      expect(h.notifications.requests, 0);
      expect(find.text(kLibrary), findsOneWidget);
      expect(find.textContaining('ROUTE:playback'), findsNothing);
    });

    for (final (name, leave) in <(String, Future<void> Function(WidgetTester))>[
      (
        'the back arrow',
        (tester) =>
            tester.tap(find.byTooltip(ProcessingMessages.backToLibrary)),
      ),
      (
        'system Back',
        (tester) async {
          await tester.binding.handlePopRoute();
          await tester.pump();
        },
      ),
    ]) {
      testWidgets('$name asks the same way while the scan runs (review '
          'M7)', (tester) async {
        final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
        h.notifications.askFirst = true;
        await pumpProcessing(tester, h);
        await leave(tester);
        await _settleNavigation(tester);
        expect(
          find.text(ScanStatusMessages.notificationsTitle),
          findsOneWidget,
        );
        await tester.tap(find.text(ScanStatusMessages.notificationsLater));
        await _settleNavigation(tester);
        expect(find.text(kLibrary), findsOneWidget);
        expect(h.notifications.asks, 1);
      });
    }

    testWidgets('a finished scan leaves without asking', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([failed(FailureReason.noStaffDetected)]),
      );
      h.notifications.askFirst = true;
      await pumpProcessing(tester, h);
      await tester.tap(find.byTooltip(ProcessingMessages.backToLibrary));
      await _settleNavigation(tester);
      expect(find.text(ScanStatusMessages.notificationsTitle), findsNothing);
      expect(find.text(kLibrary), findsOneWidget);
    });

    testWidgets('not asked when already asked: straight to the library', (
      tester,
    ) async {
      final h = ProcessingHarness(ScriptedProcessingApi([running(30)]));
      await pumpProcessing(tester, h);
      await tester.tap(find.text(ProcessingMessages.convertInBackground));
      await _settleNavigation(tester);
      expect(find.text(ScanStatusMessages.notificationsTitle), findsNothing);
      expect(h.notifications.asks, 0);
      expect(find.text(kLibrary), findsOneWidget);
    });
  });

  group('failure views (AC5–AC7)', () {
    testWidgets('no staff on page 2: reason, tips, retake that page', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(20),
          failed(FailureReason.noStaffDetected, pageIndex: 1),
        ]),
      );
      await pumpProcessing(tester, h);
      await _nextPoll(tester);

      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(
        find.text(
          'No staff lines detected on page 2 — please retake this page.',
        ),
        findsOneWidget,
      );
      expect(find.text(ProcessingMessages.retakeTipsTitle), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(find.text(ProcessingMessages.cancelScan), findsNothing);
      expect(find.text(ProcessingMessages.backToLibrary), findsOneWidget);

      await tester.tap(find.text('Retake page 2'));
      await _settleNavigation(tester);
      expect(find.text(retakeMarker(kJob, 1)), findsOneWidget);
    });

    testWidgets('2-staff layout: exact AC6 copy, no retake, library only', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          failed(FailureReason.unsupportedStaffLayout, pageIndex: 0),
        ]),
      );
      await pumpProcessing(tester, h);

      expect(
        find.text(
          'This page appears to use a 2-staff SATB layout, which isn\'t '
          'supported. PiyaNota requires each voice part (Soprano, Alto, '
          'Tenor, Bass) on its own staff line.',
        ),
        findsOneWidget,
      );
      expect(find.text(ProcessingMessages.unsupportedHeading), findsOneWidget);
      expect(find.text(ProcessingMessages.foundOnPage(1)), findsOneWidget);
      expect(_retakeWording, findsNothing);
      expect(find.text(ProcessingMessages.retakeTipsTitle), findsNothing);

      await tester.tap(find.text(ProcessingMessages.backToLibrary));
      await _settleNavigation(tester);
      expect(find.text(kLibrary), findsOneWidget);
    });

    testWidgets('a whole-score failure has no retake', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([failed(FailureReason.stageTimeout)]),
      );
      await pumpProcessing(tester, h);
      expect(find.text(ProcessingMessages.failedHeading), findsOneWidget);
      expect(
        find.text(
          ProcessingMessages.failureBody(FailureReason.stageTimeout, null),
        ),
        findsOneWidget,
      );
      expect(_retakeWording, findsNothing);
      expect(find.text(ProcessingMessages.backToLibrary), findsOneWidget);
    });

    testWidgets('a retakeable reason without a page offers no retake', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([failed(FailureReason.noStaffDetected)]),
      );
      await pumpProcessing(tester, h);
      expect(find.textContaining('on one of the pages'), findsOneWidget);
      expect(find.textContaining('Retake page'), findsNothing);
    });

    testWidgets('a vanished job (404) says so', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([const ProcessingJobNotFoundException()]),
      );
      await pumpProcessing(tester, h);
      expect(find.text(ProcessingMessages.notFoundHeading), findsOneWidget);
      expect(find.text(ProcessingMessages.cancelScan), findsNothing);
    });

    testWidgets('cancelled elsewhere has its own view', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          const ProcessingStatus(stage: ProcessingStage.cancelled),
        ]),
      );
      await pumpProcessing(tester, h);
      expect(find.text(ProcessingMessages.cancelledHeading), findsOneWidget);
    });
  });

  group('connection trouble', () {
    testWidgets('a failed poll keeps the progress and says Reconnecting', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(40),
          const ProcessingNetworkException(),
          running(55),
        ]),
      );
      await pumpProcessing(tester, h);
      await _nextPoll(tester);
      expect(find.text(ProcessingMessages.reconnecting), findsOneWidget);
      expect(find.text('40%'), findsOneWidget);
      expect(find.text('page 2/3'), findsOneWidget);

      await _nextPoll(tester);
      expect(find.text(ProcessingMessages.reconnecting), findsNothing);
      expect(find.text('55%'), findsOneWidget);
    });

    testWidgets('after 30 s offline: paused with Try again', (tester) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(40),
          const ProcessingNetworkException(),
        ]),
      );
      await pumpProcessing(tester, h);
      await _pumpPastPause(tester);
      expect(find.text(ProcessingMessages.pausedTitle), findsOneWidget);
      expect(find.text('40%'), findsOneWidget);
      expect(find.text(ProcessingMessages.reconnecting), findsNothing);

      h.api.then([running(65)]);
      await tester.tap(find.text(ProcessingMessages.retry));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 700));
      expect(find.text(ProcessingMessages.pausedTitle), findsNothing);
      expect(find.text('65%'), findsOneWidget);
    });

    testWidgets('an expired session goes to login and forgets the job', (
      tester,
    ) async {
      final h = ProcessingHarness(
        ScriptedProcessingApi([
          running(10),
          const ProcessingSessionExpiredException(),
        ]),
      );
      await pumpProcessing(tester, h);
      await _nextPoll(tester);
      await _settleNavigation(tester);
      expect(find.text(kLogin), findsOneWidget);
      expect(find.text(ProcessingMessages.sessionExpired), findsOneWidget);
      expect(h.secureStorage.values.containsKey('session_token'), isFalse);
      expect(h.container.read(processingJobsProvider), isEmpty);
    });
  });

  group('large text (NFR-10)', () {
    for (final (name, script) in <(String, List<Object>)>[
      ('progress', [running(75)]),
      ('retake failure', [failed(FailureReason.noStaffDetected, pageIndex: 1)]),
      (
        'unsupported layout',
        [failed(FailureReason.unsupportedStaffLayout, pageIndex: 0)],
      ),
      ('paused', [running(40), const ProcessingNetworkException()]),
    ]) {
      testWidgets('$name fits 320 dp at 2x', (tester) async {
        final h = ProcessingHarness(ScriptedProcessingApi(script));
        await pumpProcessing(
          tester,
          h,
          size: const Size(320, 640),
          textScale: 2,
        );
        await _pumpPastPause(tester);
        expect(tester.takeException(), isNull);
      });
    }
  });
}
