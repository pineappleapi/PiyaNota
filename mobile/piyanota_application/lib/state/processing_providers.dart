import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../models/processing_status.dart';
import '../services/fake_processing_api.dart';
import '../services/fake_score_library_api.dart';
import '../services/processing_api.dart';
import 'auth_providers.dart';
import 'score_library_providers.dart';

/// Timing rules for following a job. Polls are spaced from the end of the
/// previous request, not on a fixed clock, so a slow network never stacks
/// requests up (scan-status spec §8, "throttle").
class ProcessingTiming {
  ProcessingTiming._();

  /// PIYA-207 AC1: "every 2 seconds".
  static const Duration pollInterval = Duration(seconds: 2);

  /// After this long without one good poll the screen stops showing a bar
  /// that may never move and offers Retry instead (spec §7, "No
  /// internet").
  static const Duration pauseAfter = Duration(seconds: 30);

  /// Spec §7 "Progress stalls": the helper line changes after this long
  /// without the percentage moving.
  static const Duration stallAfter = Duration(seconds: 90);

  static int get pauseAfterFailures =>
      (pauseAfter.inMilliseconds / pollInterval.inMilliseconds).ceil();
  static int get stallAfterPolls =>
      (stallAfter.inMilliseconds / pollInterval.inMilliseconds).ceil();
}

/// Where a followed job stands, as far as the app can tell.
enum TrackedPhase {
  /// Polling; [TrackedJob.status] is the latest answer (null before the
  /// first one).
  active,

  /// The last poll failed (network or server); still polling.
  reconnecting,

  /// Too many failed polls in a row; waiting for Retry.
  paused,
  complete,
  failed,

  /// The job reports `cancelled` (e.g. cancelled from another device).
  cancelled,

  /// 404: gone, or never this account's.
  notFound,
  sessionExpired;

  bool get isFinal =>
      this == complete ||
      this == failed ||
      this == cancelled ||
      this == notFound ||
      this == sessionExpired;
}

@immutable
class TrackedJob {
  const TrackedJob({
    required this.jobId,
    this.phase = TrackedPhase.active,
    this.status,
    this.percent = 0,
    this.failedPolls = 0,
    this.unchangedPolls = 0,
  });

  final String jobId;
  final TrackedPhase phase;

  /// The last good PIYA-102 answer, kept through failed polls so the
  /// progress stays on screen while reconnecting.
  final ProcessingStatus? status;

  /// What the bar shows: never lower than any earlier value, so a server
  /// that recalculates downwards doesn't make the bar jump back.
  final int percent;

  final int failedPolls;

  /// Good polls in a row with no change in [percent].
  final int unchangedPolls;

  bool get isStalled =>
      phase == TrackedPhase.active &&
      status?.stage != ProcessingStage.queued &&
      unchangedPolls >= ProcessingTiming.stallAfterPolls;

  TrackedJob copyWith({
    TrackedPhase? phase,
    ProcessingStatus? status,
    int? percent,
    int? failedPolls,
    int? unchangedPolls,
  }) => TrackedJob(
    jobId: jobId,
    phase: phase ?? this.phase,
    status: status ?? this.status,
    percent: percent ?? this.percent,
    failedPolls: failedPolls ?? this.failedPolls,
    unchangedPolls: unchangedPolls ?? this.unchangedPolls,
  );
}

/// What a Cancel Scan tap ended in.
enum CancelOutcome {
  cancelled,

  /// 409: it finished (or failed) first. The job has been re-polled, so
  /// its current state is already in the tracker.
  alreadyFinished,
  notFound,
  sessionExpired,

  /// Network or server trouble; nothing changed, the user can try again.
  failed,
}

/// The one fake processing backend, shared with the fake upload so a
/// submitted job can be polled. Only read while [ApiConfig.useFakeAuth].
final fakeProcessingApiProvider = Provider<FakeProcessingApi>((ref) {
  final library = ref.watch(scoreLibraryApiProvider);
  return FakeProcessingApi(
    sessionStorage: ref.watch(sessionStorageProvider),
    accountForToken: ref.watch(fakeAuthApiProvider).accountForToken,
    library: library is FakeScoreLibraryApi
        ? library
        : throw StateError('Fake processing needs the fake library'),
  );
});

/// PIYA-102/114. Fake until Module 3 is deployed, under the same flag as
/// the other fakes.
final processingApiProvider = Provider<ProcessingApi>((ref) {
  if (ApiConfig.useFakeAuth) return ref.watch(fakeProcessingApiProvider);
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpProcessingApi(
    ref.watch(dioProvider),
    ref.watch(sessionStorageProvider),
  );
});

/// Every job the app is following, by job id: the one progress source the
/// Processing screen (and later the library card and bell) read (spec §8).
///
/// Not autoDispose and not tied to any screen, so a job keeps being polled
/// after "Convert in Background". Memory only for now: surviving an app
/// restart belongs to the notifications ticket.
final processingJobsProvider =
    NotifierProvider<ProcessingJobsController, Map<String, TrackedJob>>(
      ProcessingJobsController.new,
    );

class ProcessingJobsController extends Notifier<Map<String, TrackedJob>> {
  final Map<String, Timer> _timers = {};

  /// Bumped per job on every poll, retry and forget, so an answer that
  /// arrives late for a superseded request is dropped.
  final Map<String, int> _generations = {};

  @override
  Map<String, TrackedJob> build() {
    ref.onDispose(() {
      for (final timer in _timers.values) {
        timer.cancel();
      }
      _timers.clear();
    });
    return const {};
  }

  /// Starts following [jobId] and polls it straight away. A job already
  /// followed is left alone (opening its screen again doesn't restart it).
  void track(String jobId) {
    if (state.containsKey(jobId)) return;
    _put(TrackedJob(jobId: jobId));
    unawaited(_poll(jobId));
  }

  /// Retry from the paused state.
  Future<void> retry(String jobId) async {
    final job = state[jobId];
    if (job == null || job.phase.isFinal) return;
    _put(job.copyWith(phase: TrackedPhase.reconnecting, failedPolls: 0));
    await _poll(jobId);
  }

  /// Stops following [jobId] (cancelled, replaced by a retake).
  void forget(String jobId) {
    _stop(jobId);
    _generations.remove(jobId);
    if (!state.containsKey(jobId)) return;
    state = {...state}..remove(jobId);
  }

  /// Stops following everything: the session is gone, and the next account
  /// must not see these jobs.
  void forgetAll() {
    for (final jobId in [...state.keys]) {
      forget(jobId);
    }
  }

  /// PIYA-114. On success the job is forgotten and the library reloaded,
  /// since its placeholder score is gone (spec §3).
  Future<CancelOutcome> cancel(String jobId) async {
    try {
      await ref.read(processingApiProvider).cancelJob(jobId);
    } on ProcessingConflictException {
      await _poll(jobId);
      return CancelOutcome.alreadyFinished;
    } on ProcessingJobNotFoundException {
      if (ref.mounted) forget(jobId);
      return CancelOutcome.notFound;
    } on ProcessingSessionExpiredException {
      return CancelOutcome.sessionExpired;
    } on ProcessingException {
      return CancelOutcome.failed;
    }
    if (ref.mounted) {
      forget(jobId);
      ref.invalidate(scoreLibraryProvider);
    }
    return CancelOutcome.cancelled;
  }

  Future<void> _poll(String jobId) async {
    _stop(jobId);
    final generation = (_generations[jobId] ?? 0) + 1;
    _generations[jobId] = generation;
    ProcessingStatus? status;
    ProcessingException? error;
    try {
      status = await ref.read(processingApiProvider).fetchStatus(jobId);
    } on ProcessingException catch (e) {
      error = e;
    } catch (e, stack) {
      // Anything unmapped is treated like a bad server answer: keep the
      // last progress and try again, never stop silently.
      if (kDebugMode) debugPrint('Processing poll failed: $e\n$stack');
      error = const ProcessingServerException();
    }
    if (!ref.mounted || _generations[jobId] != generation) return;
    final job = state[jobId];
    if (job == null) return;

    final next = status != null
        ? _withStatus(job, status)
        : _withError(job, error!);
    _put(next);
    if (next.phase.isFinal || next.phase == TrackedPhase.paused) return;
    _timers[jobId] = Timer(ProcessingTiming.pollInterval, () => _poll(jobId));
  }

  static TrackedJob _withStatus(TrackedJob job, ProcessingStatus status) {
    final reported = status.stage == ProcessingStage.complete
        ? 100
        : status.percentComplete ?? job.percent;
    final percent = reported > job.percent ? reported : job.percent;
    return job.copyWith(
      status: status,
      percent: percent,
      failedPolls: 0,
      unchangedPolls: percent == job.percent && job.status != null
          ? job.unchangedPolls + 1
          : 0,
      phase: switch (status.stage) {
        ProcessingStage.complete => TrackedPhase.complete,
        ProcessingStage.failed => TrackedPhase.failed,
        ProcessingStage.cancelled => TrackedPhase.cancelled,
        _ => TrackedPhase.active,
      },
    );
  }

  static TrackedJob _withError(TrackedJob job, ProcessingException error) {
    final failures = job.failedPolls + 1;
    return job.copyWith(
      failedPolls: failures,
      phase: switch (error) {
        ProcessingSessionExpiredException() => TrackedPhase.sessionExpired,
        ProcessingJobNotFoundException() => TrackedPhase.notFound,
        // 409 only belongs to cancel; on a poll it's as unexpected as a 5xx.
        ProcessingNetworkException() ||
        ProcessingServerException() ||
        ProcessingConflictException() =>
          failures >= ProcessingTiming.pauseAfterFailures
              ? TrackedPhase.paused
              : TrackedPhase.reconnecting,
      },
    );
  }

  void _put(TrackedJob job) => state = {...state, job.jobId: job};

  void _stop(String jobId) => _timers.remove(jobId)?.cancel();
}
