import 'dart:async';

import 'package:clock/clock.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../models/processing_status.dart';
import '../services/fake_processing_api.dart';
import '../services/fake_score_library_api.dart';
import '../services/processing_api.dart';
import 'auth_providers.dart';
import 'scan_job_store.dart';
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

  static int get stallAfterPolls =>
      (stallAfter.inMilliseconds / pollInterval.inMilliseconds).ceil();
}

/// PIYA-218 AC6: how much finished-scan history the bell keeps — "the
/// latest 20 items or 7 days, whichever is fewer". Scans still running
/// are never dropped.
class ScanHistoryLimits {
  ScanHistoryLimits._();

  static const int maxItems = 20;
  static const Duration maxAge = Duration(days: 7);
}

/// Where a followed job stands, as far as the app can tell.
enum TrackedPhase {
  /// Polling; [TrackedJob.status] is the latest answer (null before the
  /// first one).
  active,

  /// The last poll failed (network or server); still polling.
  reconnecting,

  /// Polls have failed for [ProcessingTiming.pauseAfter]; waiting for
  /// Retry.
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
    this.title,
    this.phase = TrackedPhase.active,
    this.status,
    this.percent = 0,
    this.failedPolls = 0,
    this.failingSince,
    this.unchangedPolls = 0,
    this.retakeOfScoreId,
    this.scoreId,
    this.createdAt,
    this.finishedAt,
    this.read = false,
    this.dismissed = false,
  });

  final String jobId;

  /// The library score this job fills, from the submit answer (PIYA-218
  /// backend dependency: PIYA-101/310 return it) or carried over from the
  /// job a page retake replaced. Null until the server says.
  final int? scoreId;

  /// When the app started following the job; orders the bell newest first.
  final DateTime? createdAt;

  /// When the job reached `complete` or `failed`, for the bell's relative
  /// time and the 7-day history limit.
  final DateTime? finishedAt;

  /// The finished row has been seen (bell tap, "Mark all as read", or
  /// watched to the end on Processing). Only finished rows count towards
  /// the bell badge (AC5).
  final bool read;

  /// Swiped out of the bell panel (AC6). The job stays known, e.g. for
  /// the library card's navigation rule.
  final bool dismissed;

  /// Set when this job is a whole-score retake of a completed score
  /// (PIYA-207 AC12): the score it fills, whose card shows as processing
  /// and can't be opened until the retake ends.
  final int? retakeOfScoreId;

  /// The score's title as the user typed it, so a list of jobs (the
  /// library card, the PIYA-218 bell) can be labelled from the tracker
  /// alone. PIYA-102 doesn't return it.
  final String? title;
  final TrackedPhase phase;

  /// The last good PIYA-102 answer, kept through failed polls so the
  /// progress stays on screen while reconnecting.
  final ProcessingStatus? status;

  /// What the bar shows: never lower than any earlier value, so a server
  /// that recalculates downwards doesn't make the bar jump back.
  final int percent;

  final int failedPolls;

  /// When the current run of failed polls began; null after a good poll.
  /// The pause rule is measured from here, not by counting failures: a
  /// poll that hangs to the 10 s connect timeout takes 12 s per failure,
  /// so counting would stretch "30 s" to minutes.
  final DateTime? failingSince;

  /// Good polls in a row with no change in [percent].
  final int unchangedPolls;

  /// The score card this job belongs to: PIYA-102's answer once it has
  /// one, else the submit answer, else the completed score a whole-score
  /// retake fills.
  int? get libraryScoreId => status?.scoreId ?? scoreId ?? retakeOfScoreId;

  /// Still running as far as the app knows (including reconnecting and
  /// paused): the card and bell row show progress.
  bool get isRunning => !phase.isFinal;

  /// Finished in a way the bell reports (AC5/AC6).
  bool get isFinished =>
      phase == TrackedPhase.complete || phase == TrackedPhase.failed;

  bool get isStalled =>
      phase == TrackedPhase.active &&
      status?.stage != ProcessingStage.queued &&
      unchangedPolls >= ProcessingTiming.stallAfterPolls;

  /// [failingSince] is always given, since null is a meaningful value.
  TrackedJob copyWith({
    TrackedPhase? phase,
    ProcessingStatus? status,
    int? percent,
    int? failedPolls,
    required DateTime? failingSince,
    int? unchangedPolls,
    String? title,
    int? scoreId,
    DateTime? finishedAt,
    bool? read,
    bool? dismissed,
  }) => TrackedJob(
    jobId: jobId,
    retakeOfScoreId: retakeOfScoreId,
    title: title ?? this.title,
    phase: phase ?? this.phase,
    status: status ?? this.status,
    percent: percent ?? this.percent,
    failedPolls: failedPolls ?? this.failedPolls,
    failingSince: failingSince,
    unchangedPolls: unchangedPolls ?? this.unchangedPolls,
    scoreId: scoreId ?? this.scoreId,
    createdAt: createdAt,
    finishedAt: finishedAt ?? this.finishedAt,
    read: read ?? this.read,
    dismissed: dismissed ?? this.dismissed,
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

/// The tracker's wall clock. `clock.now` rather than `DateTime.now` so
/// widget tests and fake_async move it with fake time; tests may also
/// override it outright.
final processingClockProvider = Provider<DateTime Function()>(
  (ref) => clock.now,
);

/// Where the tracker keeps its jobs between app runs (PIYA-218 AC8).
final scanJobStoreProvider = Provider<ScanJobStore>(
  (ref) => const ScanJobStore(),
);

/// Emits whether the phone has a network, on every change (PIYA-218
/// AC10: paused jobs resume by themselves when it returns). Only listened
/// to once a job has paused, so screens and tests that never pause never
/// touch the platform channel.
final networkAvailabilityProvider = Provider<Stream<bool>>(
  (ref) => Connectivity().onConnectivityChanged.map(
    (results) => results.any((result) => result != ConnectivityResult.none),
  ),
);

/// Every job the app is following, by job id: the one progress source the
/// Processing screen, the library card and the bell read (PIYA-218 AC1,
/// spec §8).
///
/// Not autoDispose and not tied to any screen, so a job keeps being polled
/// after "Convert in Background". Kept on the device by [ScanJobStore], so
/// cards and bell rows come back after a restart and unfinished jobs are
/// polled again (AC8).
final processingJobsProvider =
    NotifierProvider<ProcessingJobsController, Map<String, TrackedJob>>(
      ProcessingJobsController.new,
    );

class ProcessingJobsController extends Notifier<Map<String, TrackedJob>> {
  final Map<String, Timer> _timers = {};

  /// Bumped per job on every poll, retry and forget, so an answer that
  /// arrives late for a superseded request is dropped. Never reset: a
  /// forgotten then re-tracked id must not reuse a number an in-flight
  /// poll from the old loop still holds.
  final Map<String, int> _generations = {};

  /// Bumped by [forgetAll], so a restore that was still reading storage
  /// when the session ended doesn't bring the old account's jobs back.
  int _clearEpoch = 0;

  /// False until the stored jobs have been read: saving before then would
  /// overwrite them with whatever was tracked in the meantime.
  bool _restored = false;
  String? _lastSaved;

  StreamSubscription<bool>? _network;

  /// The last network state reported; null before the first report.
  bool? _online;

  @override
  Map<String, TrackedJob> build() {
    ref.onDispose(() {
      for (final timer in _timers.values) {
        timer.cancel();
      }
      _timers.clear();
      unawaited(_network?.cancel());
      _network = null;
    });
    unawaited(_restore());
    return const {};
  }

  DateTime _now() => ref.read(processingClockProvider)();

  ScanJobStore get _store => ref.read(scanJobStoreProvider);

  /// AC8: brings back the jobs of the previous run and polls every one
  /// that hadn't finished, so anything that ended while the app was
  /// closed shows up. Jobs tracked since launch win over stored copies.
  Future<void> _restore() async {
    final epoch = _clearEpoch;
    final stored = await _store.load();
    if (!ref.mounted || epoch != _clearEpoch) return;
    _restored = true;
    final added = [
      for (final job in stored)
        if (!state.containsKey(job.jobId)) job,
    ];
    if (added.isNotEmpty) {
      state = {...state, for (final job in added) job.jobId: job};
    }
    _prune();
    _persist();
    for (final job in added) {
      if (job.isRunning && state.containsKey(job.jobId)) {
        unawaited(_poll(job.jobId));
      }
    }
  }

  /// Starts following [jobId] and polls it straight away. A job already
  /// followed is left alone (opening its screen again doesn't restart it),
  /// apart from picking up a [title] or [scoreId] it didn't have.
  /// [retakeOfScoreId] as in [TrackedJob.retakeOfScoreId].
  void track(
    String jobId, {
    String? title,
    int? retakeOfScoreId,
    int? scoreId,
  }) {
    final existing = state[jobId];
    if (existing != null) {
      final newTitle = existing.title == null && title != null;
      final newScore = existing.scoreId == null && scoreId != null;
      if (newTitle || newScore) {
        _put(
          existing.copyWith(
            title: newTitle ? title : null,
            scoreId: newScore ? scoreId : null,
            failingSince: existing.failingSince,
          ),
        );
      }
      return;
    }
    _put(
      TrackedJob(
        jobId: jobId,
        title: title,
        retakeOfScoreId: retakeOfScoreId,
        scoreId: scoreId,
        createdAt: _now(),
      ),
    );
    unawaited(_poll(jobId));
  }

  /// The newest job for the library card of [scoreId], if the tracker
  /// knows one (PIYA-218 AC3/AC4).
  TrackedJob? latestJobFor(int scoreId) => latestScanJobFor(state, scoreId);

  /// AC6: a completed or failed row has been seen.
  void markRead(String jobId) {
    final job = state[jobId];
    if (job == null || job.read || !job.isFinished) return;
    _put(job.copyWith(read: true, failingSince: job.failingSince));
  }

  /// AC6 "Mark all as read".
  void markAllRead() {
    final unread = [
      for (final job in state.values)
        if (job.isFinished && !job.read) job,
    ];
    if (unread.isEmpty) return;
    state = {
      ...state,
      for (final job in unread)
        job.jobId: job.copyWith(read: true, failingSince: job.failingSince),
    };
    _persist();
  }

  /// AC6: swipe a completed or failed row away. A running scan can't be
  /// dismissed.
  void dismiss(String jobId) {
    final job = state[jobId];
    if (job == null || !job.isFinished || job.dismissed) return;
    _put(
      job.copyWith(dismissed: true, read: true, failingSince: job.failingSince),
    );
  }

  /// The whole-score retake still running for [scoreId], if any: the
  /// library opens its Processing instead of the old result (PIYA-207
  /// AC12, PIYA-218 AC3).
  TrackedJob? runningRetakeOf(int scoreId) {
    for (final job in state.values) {
      if (job.retakeOfScoreId == scoreId && !job.phase.isFinal) return job;
    }
    return null;
  }

  /// The tracked job that completed as [scoreId], for a result that came
  /// without its `jobId` (PIYA-207 AC12 needs one to send
  /// `replacesJobId`). Null when the tracker never saw it.
  TrackedJob? completedJobOf(int scoreId) {
    for (final job in state.values) {
      if (job.phase == TrackedPhase.complete && job.libraryScoreId == scoreId) {
        return job;
      }
    }
    return null;
  }

  /// Retry from the paused state.
  Future<void> retry(String jobId) async {
    final job = state[jobId];
    if (job == null || job.phase.isFinal) return;
    _put(
      job.copyWith(
        phase: TrackedPhase.reconnecting,
        failedPolls: 0,
        failingSince: null,
      ),
    );
    await _poll(jobId);
  }

  /// Stops following [jobId] (cancelled, replaced by a retake).
  void forget(String jobId) {
    _stop(jobId);
    _generations[jobId] = (_generations[jobId] ?? 0) + 1;
    if (!state.containsKey(jobId)) return;
    state = {...state}..remove(jobId);
    _persist();
  }

  /// Stops following every job of [scoreId]: the score was deleted, so
  /// its bell rows and card state must go too, here and on the device.
  void forgetScore(int scoreId) {
    for (final job in [...state.values]) {
      if (job.libraryScoreId == scoreId) forget(job.jobId);
    }
  }

  /// Stops following everything and wipes the stored copy: the session is
  /// gone, and the next account must not see these jobs.
  void forgetAll() {
    _clearEpoch++;
    for (final jobId in [...state.keys]) {
      forget(jobId);
    }
    // Nothing is left to restore; save normally from now on.
    _restored = true;
    _lastSaved = ScanJobStore.encodeJobs(const []);
    unawaited(_store.clear());
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

    final now = _now();
    var next = status != null
        ? _withStatus(job, status)
        : _withError(job, error!, now);
    final justFinished = next.isFinished && !job.isFinished;
    if (justFinished) {
      next = next.copyWith(finishedAt: now, failingSince: next.failingSince);
    }
    _put(next);
    if (justFinished) _prune();
    if (next.phase == TrackedPhase.paused) _listenForNetwork();
    if (next.phase.isFinal || next.phase == TrackedPhase.paused) return;
    // Belt and braces with the generation check: whatever timer is there
    // belongs to a superseded loop, and must not keep running beside this.
    _stop(jobId);
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
      failingSince: null,
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

  /// [now] is when the failed poll finished. The run of failures counts
  /// from the first one's finish, so a single slow failure never pauses
  /// on its own; after that, 30 s of wall-clock failure pauses however
  /// long each attempt took.
  static TrackedJob _withError(
    TrackedJob job,
    ProcessingException error,
    DateTime now,
  ) {
    final failures = job.failedPolls + 1;
    final since = job.failingSince ?? now;
    return job.copyWith(
      failedPolls: failures,
      failingSince: since,
      phase: switch (error) {
        ProcessingSessionExpiredException() => TrackedPhase.sessionExpired,
        ProcessingJobNotFoundException() => TrackedPhase.notFound,
        // 409 only belongs to cancel; on a poll it's as unexpected as a 5xx.
        ProcessingNetworkException() ||
        ProcessingServerException() ||
        ProcessingConflictException() =>
          now.difference(since) >= ProcessingTiming.pauseAfter
              ? TrackedPhase.paused
              : TrackedPhase.reconnecting,
      },
    );
  }

  void _put(TrackedJob job) {
    state = {...state, job.jobId: job};
    _persist();
  }

  /// Writes only when what is stored changed, so a poll that changes
  /// nothing a card or row shows doesn't touch the disk.
  void _persist() {
    if (!_restored) return;
    final encoded = ScanJobStore.encodeJobs(state.values);
    if (encoded == _lastSaved) return;
    _lastSaved = encoded;
    unawaited(_store.save(encoded));
  }

  /// AC6: finished jobs older than [ScanHistoryLimits.maxAge] go, then the
  /// oldest beyond [ScanHistoryLimits.maxItems] rows. Running jobs stay.
  void _prune() {
    final cutoff = _now().subtract(ScanHistoryLimits.maxAge);
    final running = state.values.where((job) => job.isRunning).length;
    final finished = [
      for (final job in state.values)
        if (job.phase.isFinal) job,
    ]..sort(compareScanJobsNewestFirst);
    final keep = ScanHistoryLimits.maxItems - running;
    final drop = <String>{
      for (var i = 0; i < finished.length; i++)
        if (i >= keep || _activityOf(finished[i]).isBefore(cutoff))
          finished[i].jobId,
    };
    if (drop.isEmpty) return;
    for (final jobId in drop) {
      _stop(jobId);
    }
    state = {...state}..removeWhere((jobId, _) => drop.contains(jobId));
    _persist();
  }

  /// Retries every paused job once the network comes back (AC10). Only a
  /// change from offline to online counts: the first report is the
  /// current state, and retrying on it would undo the pause whenever the
  /// server, not the phone, is the problem.
  void _listenForNetwork() {
    if (_network != null) return;
    try {
      _network = ref.read(networkAvailabilityProvider).listen(
        (online) {
          final wasOffline = _online == false;
          _online = online;
          if (!online || !wasOffline || !ref.mounted) return;
          for (final job in [...state.values]) {
            if (job.phase == TrackedPhase.paused) {
              unawaited(retry(job.jobId));
            }
          }
        },
        onError: (Object e) =>
            debugPrint('Connectivity updates unavailable: $e'),
      );
    } on Object catch (e) {
      // No connectivity plugin (e.g. an unsupported platform): Retry on
      // the card, the bell row and Processing still works.
      debugPrint('Connectivity updates unavailable: $e');
    }
  }

  static DateTime _activityOf(TrackedJob job) =>
      job.finishedAt ??
      job.createdAt ??
      DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);

  void _stop(String jobId) => _timers.remove(jobId)?.cancel();
}

/// Newest first, by when the app started following the job: a row keeps
/// its place when it finishes (PIYA-218 AC6 "in place").
int compareScanJobsNewestFirst(TrackedJob a, TrackedJob b) {
  final aWhen = a.createdAt;
  final bWhen = b.createdAt;
  if (aWhen != null && bWhen != null) {
    final byStart = bWhen.compareTo(aWhen);
    if (byStart != 0) return byStart;
  } else if (aWhen != null) {
    return -1;
  } else if (bWhen != null) {
    return 1;
  }
  return b.jobId.compareTo(a.jobId);
}

/// The newest job for the library card of [scoreId], if any.
TrackedJob? latestScanJobFor(Map<String, TrackedJob> jobs, int scoreId) {
  TrackedJob? latest;
  for (final job in jobs.values) {
    if (job.libraryScoreId != scoreId) continue;
    if (latest == null || compareScanJobsNewestFirst(job, latest) < 0) {
      latest = job;
    }
  }
  return latest;
}

/// The bell panel's rows (PIYA-218 AC6), newest first: every running,
/// completed or failed job that wasn't swiped away, one per score — a
/// score whose scan was replaced shows only its newest job.
List<TrackedJob> scanNotifications(Map<String, TrackedJob> jobs) {
  final rows = [
    for (final job in jobs.values)
      if (!job.dismissed && (job.isRunning || job.isFinished)) job,
  ]..sort(compareScanJobsNewestFirst);
  final seenScores = <int>{};
  final unique = <TrackedJob>[];
  for (final job in rows) {
    final scoreId = job.libraryScoreId;
    if (scoreId == null || seenScores.add(scoreId)) unique.add(job);
  }
  return unique;
}

/// AC5: the bell's badge counts finished rows not yet seen; running scans
/// never add to it.
int unreadScanCount(Map<String, TrackedJob> jobs) =>
    scanNotifications(jobs).where((job) => job.isFinished && !job.read).length;

/// AC5/AC9: the bell's ring shows while any scan is running.
bool anyScanRunning(Map<String, TrackedJob> jobs) =>
    jobs.values.any((job) => job.isRunning);
