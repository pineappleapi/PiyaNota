import 'dart:async';

import 'package:fake_async/fake_async.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/services/processing_api.dart';
import 'package:piyanota_application/state/processing_providers.dart';

import 'processing_fakes.dart';

const _tick = ProcessingTiming.pollInterval;

/// Runs [body] under fake time with a container whose only real piece is
/// the tracker, and checks no poll timer outlives the container.
void _withTracker(
  ScriptedProcessingApi api,
  void Function(
    FakeAsync async,
    ProcessingJobsController tracker,
    TrackedJob? Function() job,
  )
  body,
) {
  fakeAsync((async) {
    final container = ProviderContainer(
      overrides: [
        processingApiProvider.overrideWithValue(api),
        scanJobStoreProvider.overrideWithValue(MemoryScanJobStore()),
        networkAvailabilityProvider.overrideWithValue(const Stream.empty()),
      ],
    );
    final tracker = container.read(processingJobsProvider.notifier);
    body(async, tracker, () => container.read(processingJobsProvider)[kJob]);
    container.dispose();
    async.flushMicrotasks();
    expect(async.pendingTimers, isEmpty, reason: 'a poll timer leaked');
  });
}

void main() {
  group('polling (AC1)', () {
    test('polls at once, then every 2 s, updating the percentage', () {
      final api = ScriptedProcessingApi([
        running(10),
        running(25),
        running(40),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        expect(api.fetches, 1);
        expect(job()!.percent, 10);
        expect(job()!.phase, TrackedPhase.active);

        async.elapse(_tick - const Duration(milliseconds: 1));
        expect(api.fetches, 1, reason: 'not before 2 s');
        async.elapse(const Duration(milliseconds: 1));
        expect(api.fetches, 2);
        expect(job()!.percent, 25);

        async.elapse(_tick);
        expect(api.fetches, 3);
        expect(job()!.percent, 40);
        expect(job()!.status!.currentPage, 2);
      });
    });

    test('tracking the same job twice does not start a second loop', () {
      final api = ScriptedProcessingApi([running(10)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(_tick * 3);
        expect(api.fetches, 4);
      });
    });

    test('the percentage never goes backwards', () {
      final api = ScriptedProcessingApi([
        running(50),
        running(42),
        running(60),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(_tick);
        expect(job()!.percent, 50);
        expect(job()!.status!.percentComplete, 42);
        async.elapse(_tick);
        expect(job()!.percent, 60);
      });
    });

    test('complete stops polling and reads as 100%', () {
      final api = ScriptedProcessingApi([running(80), done()]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.complete);
        expect(job()!.percent, 100);
        async.elapse(_tick * 5);
        expect(api.fetches, 2);
        expect(async.pendingTimers, isEmpty);
      });
    });

    test('failed and cancelled stop polling', () {
      for (final (status, phase) in [
        (
          failed(FailureReason.noStaffDetected, pageIndex: 1),
          TrackedPhase.failed,
        ),
        (
          const ProcessingStatus(stage: ProcessingStage.cancelled),
          TrackedPhase.cancelled,
        ),
      ]) {
        final api = ScriptedProcessingApi([status]);
        _withTracker(api, (async, tracker, job) {
          tracker.track(kJob);
          async.flushMicrotasks();
          expect(job()!.phase, phase);
          async.elapse(_tick * 3);
          expect(api.fetches, 1);
        });
      }
    });

    test('an unknown stage keeps polling', () {
      final api = ScriptedProcessingApi([
        const ProcessingStatus(stage: ProcessingStage.unknown),
        running(30),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        expect(job()!.phase, TrackedPhase.active);
        async.elapse(_tick);
        expect(job()!.percent, 30);
      });
    });

    test('flags a stall after 90 s without movement', () {
      final api = ScriptedProcessingApi([running(40)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(ProcessingTiming.stallAfter - _tick);
        expect(job()!.isStalled, isFalse);
        async.elapse(_tick);
        expect(job()!.isStalled, isTrue);
        api.then([running(41)]);
        async.elapse(_tick);
        expect(job()!.isStalled, isFalse);
      });
    });

    test('forget then track during an in-flight poll runs one loop', () {
      final api = ScriptedProcessingApi([running(10)]);
      _withTracker(api, (async, tracker, job) {
        // Made inside the fake zone, so completing it is fake-async too.
        api.fetchGate = Completer<void>();
        tracker.track(kJob);
        async.flushMicrotasks();
        tracker.forget(kJob);
        tracker.track(kJob);
        async.flushMicrotasks();
        expect(api.fetches, 2, reason: 'both polls are in flight');

        // The first loop's answer lands after the job was re-tracked; it
        // must be dropped, not start a second timer.
        api.fetchGate!.complete();
        api.fetchGate = null;
        async.flushMicrotasks();
        expect(job()!.percent, 10);
        async.elapse(_tick * 3);
        expect(api.fetches, 2 + 3, reason: 'one poll per 2 s, not two');
      });
    });

    test('keeps the title so rows can be labelled from the tracker', () {
      final api = ScriptedProcessingApi([running(10)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        expect(job()!.title, isNull);
        tracker.track(kJob, title: kTitle);
        expect(job()!.title, kTitle);
        expect(api.fetches, 1, reason: 'adding a title is not a restart');
        tracker.track(kJob, title: 'Other');
        expect(job()!.title, kTitle);
        async.elapse(_tick);
        expect(job()!.title, kTitle, reason: 'polls keep it');
      });
    });

    test('forget stops the loop and drops the job', () {
      final api = ScriptedProcessingApi([running(10)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        tracker.forget(kJob);
        async.elapse(_tick * 3);
        expect(api.fetches, 1);
        expect(job(), isNull);
      });
    });
  });

  group('poll errors', () {
    test('a transient error keeps the progress and keeps polling', () {
      final api = ScriptedProcessingApi([
        running(40),
        const ProcessingNetworkException(),
        const ProcessingServerException(),
        running(55),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.reconnecting);
        expect(job()!.percent, 40);
        expect(job()!.status!.percentComplete, 40);
        async.elapse(_tick);
        expect(job()!.failedPolls, 2);
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.active);
        expect(job()!.percent, 55);
        expect(job()!.failedPolls, 0);
      });
    });

    test('pauses after 30 s of failures; Retry resumes', () {
      final api = ScriptedProcessingApi([
        running(40),
        const ProcessingNetworkException(),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        // First failure at 2 s; 30 s of failing is reached at 32 s.
        async.elapse(_tick * 15);
        expect(job()!.phase, TrackedPhase.reconnecting);
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.paused);
        expect(job()!.failedPolls, 16);
        expect(job()!.percent, 40);
        final fetches = api.fetches;
        async.elapse(_tick * 5);
        expect(api.fetches, fetches, reason: 'paused means no polling');

        api.then([running(70)]);
        tracker.retry(kJob);
        async.flushMicrotasks();
        expect(job()!.phase, TrackedPhase.active);
        expect(job()!.percent, 70);
        async.elapse(_tick);
        expect(api.fetches, fetches + 2, reason: 'polling resumed');
      });
    });

    test('the pause is wall-clock time, not a count of failures', () {
      // A server that only fails at a 10 s connect timeout: each failure
      // takes 12 s. Counting 15 failures would take three minutes.
      const timeout = Duration(seconds: 10);
      final api = ScriptedProcessingApi([
        running(40),
        const ProcessingNetworkException(),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        api.fetchDelay = timeout;
        // Poll 2 starts at 2 s and fails at 12 s; then 24, 36, 48 s.
        async.elapse(const Duration(seconds: 12));
        expect(job()!.phase, TrackedPhase.reconnecting);
        expect(job()!.failingSince, isNotNull);
        async.elapse(const Duration(seconds: 47 - 12));
        expect(job()!.phase, TrackedPhase.reconnecting);
        expect(job()!.failedPolls, 3);
        async.elapse(const Duration(seconds: 1));
        expect(job()!.phase, TrackedPhase.paused, reason: '36 s failing');
        expect(job()!.failedPolls, 4);
        final fetches = api.fetches;
        async.elapse(timeout * 5);
        expect(api.fetches, fetches);
      });
    });

    test('a good poll restarts the failure clock', () {
      final api = ScriptedProcessingApi([
        running(40),
        for (var i = 0; i < 10; i++) const ProcessingNetworkException(),
        running(45),
        const ProcessingNetworkException(),
      ]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        async.elapse(_tick * 11);
        expect(job()!.phase, TrackedPhase.active);
        expect(job()!.failingSince, isNull);
        // 20 s of failing before the good poll don't count towards 30.
        async.elapse(_tick * 15);
        expect(job()!.phase, TrackedPhase.reconnecting);
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.paused);
      });
    });

    test('401 ends in sessionExpired, 404 in notFound', () {
      for (final (error, phase) in [
        (
          const ProcessingSessionExpiredException(),
          TrackedPhase.sessionExpired,
        ),
        (const ProcessingJobNotFoundException(), TrackedPhase.notFound),
      ]) {
        final api = ScriptedProcessingApi([running(10), error]);
        _withTracker(api, (async, tracker, job) {
          tracker.track(kJob);
          async.flushMicrotasks();
          async.elapse(_tick);
          expect(job()!.phase, phase);
          async.elapse(_tick * 3);
          expect(api.fetches, 2);
        });
      }
    });

    test('an unmapped error is treated as a server hiccup', () {
      final api = ScriptedProcessingApi([running(10)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        api.then([StateError('boom')]);
        async.elapse(_tick);
        expect(job()!.phase, TrackedPhase.reconnecting);
      });
    });
  });

  group('cancel (AC4)', () {
    test('success forgets the job and stops polling', () {
      final api = ScriptedProcessingApi([running(30)]);
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        CancelOutcome? outcome;
        tracker.cancel(kJob).then((o) => outcome = o);
        async.flushMicrotasks();
        expect(outcome, CancelOutcome.cancelled);
        expect(job(), isNull);
        async.elapse(_tick * 3);
        expect(api.fetches, 1);
      });
    });

    test('409 re-polls so the real state shows', () {
      final api = ScriptedProcessingApi([running(90)])
        ..cancelError = const ProcessingConflictException();
      _withTracker(api, (async, tracker, job) {
        tracker.track(kJob);
        async.flushMicrotasks();
        api.then([done()]);
        CancelOutcome? outcome;
        tracker.cancel(kJob).then((o) => outcome = o);
        async.flushMicrotasks();
        expect(outcome, CancelOutcome.alreadyFinished);
        expect(job()!.phase, TrackedPhase.complete);
      });
    });

    test('other errors keep the job and report failure', () {
      for (final (error, expected) in [
        (const ProcessingNetworkException(), CancelOutcome.failed),
        (const ProcessingServerException(), CancelOutcome.failed),
        (
          const ProcessingSessionExpiredException(),
          CancelOutcome.sessionExpired,
        ),
        (const ProcessingJobNotFoundException(), CancelOutcome.notFound),
      ]) {
        final api = ScriptedProcessingApi([running(30)])..cancelError = error;
        _withTracker(api, (async, tracker, job) {
          tracker.track(kJob);
          async.flushMicrotasks();
          CancelOutcome? outcome;
          tracker.cancel(kJob).then((o) => outcome = o);
          async.flushMicrotasks();
          expect(outcome, expected);
          if (expected == CancelOutcome.notFound) {
            expect(job(), isNull);
          } else {
            expect(job(), isNotNull);
          }
          tracker.forgetAll();
        });
      }
    });
  });
}
