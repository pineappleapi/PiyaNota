import 'dart:async';

import '../models/library_entry.dart';
import '../models/local_submission.dart';
import '../models/processing_status.dart';
import 'local_results_store.dart';
import 'local_submission_store.dart';
import 'processing_api.dart';
import 'score_result_api.dart';

/// How a [SubmissionReconciler.run] ended.
enum ReconcileResult {
  /// Compared the rows with the server and saved what changed.
  done,

  /// Ran too recently (or another run was already going); nothing sent.
  skipped,

  /// 401 or no token. Stopped quietly: local scores and rows are untouched,
  /// the foreground's own 401 handling sends the user to Login.
  sessionExpired,

  /// Offline or a server error on the list call. Nothing changed; the next
  /// run tries again.
  unavailable,

  /// 429: the server asked us to wait. Rows the run already settled are
  /// saved; no run (forced or not) goes out before the wait is over.
  rateLimited,

  /// The caller's cancel check said stop (the app came to the foreground
  /// during a background run). Rows settled so far are saved.
  cancelled,
}

/// Brings the phone's [LocalSubmission] rows in line with the server's jobs
/// (job-lifecycle Task 4), so a score converted while the app was closed
/// shows up, finished or failed, when it opens again.
///
/// Plain Dart: no Riverpod, no widgets, so Task 6's background isolate can
/// build one from `HttpProcessingApi` / `HttpScoreResultApi` (each reads the
/// token from secure storage itself), a [LocalSubmissionStore], a
/// [LocalResultsStore] and call `run(fresh: true)`.
///
/// Cost: one `GET /api/jobs` per run covers every row (status is 120
/// reads/min/user, shared). A single status GET is made only for a row the
/// list does not contain (finished more than 7 days ago, or gone), and the
/// `/result` call (which reorders the library) only for a job that just
/// completed. [minInterval] keeps repeated triggers (resume, library open,
/// timer) from stacking up.
class SubmissionReconciler {
  SubmissionReconciler({
    required this._processing,
    required this._jobList,
    required this._results,
    required this._submissions,
    required this._resultsStore,
    DateTime Function()? now,
    this.minInterval = defaultMinInterval,
    this.isCancelled,
  }) : _now = now ?? DateTime.now;

  final ProcessingApi _processing;
  final JobListApi _jobList;
  final ScoreResultApi _results;
  final LocalSubmissionStore _submissions;
  final LocalResultsStore _resultsStore;
  final DateTime Function() _now;
  final Duration minInterval;

  /// Asked between rows; true stops the run early. The headless background
  /// run passes one so it yields to the foreground, which owns the rows.
  final Future<bool> Function()? isCancelled;

  /// A row with no job is left alone this long: its upload may still be in
  /// flight in the foreground (large PDF, slow network).
  static const Duration pendingGrace = Duration(minutes: 5);

  /// How long finished (ready) rows and dismissed ids are remembered: the
  /// server's list window, after which neither can come back from it.
  static const Duration retention = Duration(days: 7);

  static const Duration defaultMinInterval = Duration(seconds: 10);

  /// Wait after a 429 that carried no Retry-After.
  static const Duration defaultRateLimitWait = Duration(minutes: 1);

  /// Failure codes that mean "the 202 may have been lost", so a server job
  /// with the same clientSubmissionId revives the row.
  static const Set<String> _ambiguousFailures = {
    SubmissionFailure.network,
    SubmissionFailure.unknown,
  };

  Future<ReconcileResult>? _running;
  DateTime? _lastRun;
  DateTime? _blockedUntil;

  /// Single-flight: a call while a run is going gets that run's result.
  /// [fresh] reloads storage first; a background isolate must pass true.
  /// [force] ignores [minInterval] (a user pull-to-refresh).
  Future<ReconcileResult> run({bool fresh = false, bool force = false}) =>
      _running ??= _run(
        fresh: fresh,
        force: force,
      ).whenComplete(() => _running = null);

  Future<ReconcileResult> _run({
    required bool fresh,
    required bool force,
  }) async {
    final started = _now();
    final blocked = _blockedUntil;
    // Even a pull-to-refresh waits out a 429: retrying early only extends it.
    if (blocked != null && started.isBefore(blocked)) {
      return ReconcileResult.skipped;
    }
    final last = _lastRun;
    if (!force && last != null && started.difference(last) < minInterval) {
      return ReconcileResult.skipped;
    }
    _lastRun = started;

    final rows = await _submissions.load(fresh: fresh);
    final List<ListedJob> listed;
    try {
      listed = await _jobList.listJobs();
    } on ProcessingSessionExpiredException {
      return ReconcileResult.sessionExpired;
    } on ProcessingRateLimitedException catch (e) {
      _blockFor(e, started);
      return ReconcileResult.rateLimited;
    } on ProcessingException {
      return ReconcileResult.unavailable;
    }

    final byJob = {for (final j in listed) j.jobId: j};
    final byClient = {
      for (final j in listed)
        if (j.clientSubmissionId != null) j.clientSubmissionId!: j,
    };
    // null = remove the row.
    final changes = <String, LocalSubmission?>{};
    var stopped = false;
    var rateLimited = false;
    var cancelled = false;

    // A replacement that got its 202 supersedes the failed row it names. The
    // capture screen drops that row itself; this covers a crash in between,
    // so it cannot reappear once the replacement ages out.
    final superseded = {
      for (final r in rows)
        if (r.replacesJobId != null && r.jobId != null) r.replacesJobId!,
    };

    for (final row in rows) {
      if (await isCancelled?.call() ?? false) {
        cancelled = true;
        break;
      }
      if (row.status == SubmissionStatus.ready) continue;
      if (row.status == SubmissionStatus.failed &&
          superseded.contains(row.jobId)) {
        changes[row.clientSubmissionId] = null;
        continue;
      }
      // A failed row is revived on purpose even when it has a jobId: the
      // job's real state is re-read, so a wrong "network"/"unknown" failure
      // heals and a true failure just lands back on failed.
      final revivable =
          row.status == SubmissionStatus.failed &&
          _ambiguousFailures.contains(row.failureCode);
      if (row.status == SubmissionStatus.failed && !revivable) continue;

      var job =
          (row.jobId == null ? null : byJob[row.jobId]) ??
          byClient[row.clientSubmissionId];
      if (job == null) {
        if (revivable) continue;
        if (row.jobId == null) {
          // Never reached the server (or not within the grace window yet).
          if (started.difference(row.createdAt) > pendingGrace) {
            changes[row.clientSubmissionId] = row.copyWith(
              status: SubmissionStatus.failed,
              failureCode: SubmissionFailure.interrupted,
            );
          }
          continue;
        }
        // Not in the list: older than its window or gone. Ask directly.
        try {
          final status = await _processing.fetchStatus(row.jobId!);
          job = (
            jobId: row.jobId!,
            clientSubmissionId: row.clientSubmissionId,
            title: row.title,
            createdAt: row.createdAt,
            status: status,
          );
        } on ProcessingJobNotFoundException {
          changes[row.clientSubmissionId] = null;
          continue;
        } on ProcessingSessionExpiredException {
          stopped = true;
          break;
        } on ProcessingRateLimitedException catch (e) {
          _blockFor(e, started);
          rateLimited = true;
          break; // keep what is settled so far; the rest waits
        } on ProcessingException {
          continue; // transient: keep the row, try next run
        }
      }
      if (await _apply(row, job, changes)) {
        stopped = true;
        break;
      }
    }

    final adds = stopped || cancelled
        ? const <LocalSubmission>[]
        : _adoptable(rows, listed);
    final dismissed = await _submissions.loadDismissed(fresh: fresh);
    await _submissions.update((current) {
      final next = <LocalSubmission>[];
      for (final r in current) {
        if (!changes.containsKey(r.clientSubmissionId)) {
          // Finished rows only stop a re-adopt; drop them with the window.
          if (r.status == SubmissionStatus.ready &&
              started.difference(r.createdAt) > retention) {
            continue;
          }
          next.add(r);
        } else if (changes[r.clientSubmissionId] case final changed?) {
          next.add(changed);
        }
      }
      for (final a in adds) {
        final exists = next.any(
          (r) =>
              r.clientSubmissionId == a.clientSubmissionId ||
              (r.jobId != null && r.jobId == a.jobId),
        );
        if (!exists && !_isDismissed(dismissed, a)) next.add(a);
      }
      return next;
    }, fresh: fresh);
    if (stopped) return ReconcileResult.sessionExpired;
    if (cancelled) return ReconcileResult.cancelled;
    return rateLimited ? ReconcileResult.rateLimited : ReconcileResult.done;
  }

  void _blockFor(ProcessingRateLimitedException e, DateTime from) =>
      _blockedUntil = from.add(e.retryAfter ?? defaultRateLimitWait);

  static bool _isDismissed(
    Map<String, DateTime> dismissed,
    LocalSubmission r,
  ) =>
      dismissed.containsKey(r.clientSubmissionId) ||
      (r.jobId != null && dismissed.containsKey(r.jobId));

  /// Server jobs still running that the phone has no row for (submitted from
  /// another install, or the row was lost). Finished server-only jobs are
  /// not adopted: a completed score is already in the library list, and a
  /// failed one the user never saw is not worth resurrecting.
  List<LocalSubmission> _adoptable(
    List<LocalSubmission> rows,
    List<ListedJob> listed,
  ) {
    final ids = {for (final r in rows) r.clientSubmissionId};
    final jobs = {
      for (final r in rows)
        if (r.jobId != null) r.jobId!,
    };
    return [
      for (final j in listed)
        if (!j.status.stage.isTerminal &&
            !jobs.contains(j.jobId) &&
            !(j.clientSubmissionId != null &&
                ids.contains(j.clientSubmissionId)))
          LocalSubmission(
            // The id is the row's key, so a job sent without one gets a
            // stable stand-in; the server never sees it.
            clientSubmissionId: j.clientSubmissionId ?? 'job-${j.jobId}',
            title: (j.title ?? '').trim().isEmpty
                ? untitledScoreLabel
                : j.title!.trim(),
            createdAt: (j.createdAt ?? _now()).toUtc(),
            jobId: j.jobId,
            scoreId: j.status.scoreId,
            percentComplete: j.status.percentComplete,
          ),
    ];
  }

  /// Records what [job] says about [row] in [changes]. True when the session
  /// ended (401) and the run must stop.
  Future<bool> _apply(
    LocalSubmission row,
    ListedJob job,
    Map<String, LocalSubmission?> changes,
  ) async {
    final status = job.status;
    final key = row.clientSubmissionId;
    // Adopts the jobId a lost 202 never delivered; a revived row is
    // processing again.
    final attached = row.copyWith(
      jobId: job.jobId,
      scoreId: status.scoreId,
      status: SubmissionStatus.processing,
      clearFailure: true,
    );
    switch (status.stage) {
      case ProcessingStage.complete:
        final scoreId = status.scoreId ?? row.scoreId;
        if (scoreId != null) {
          try {
            await _download(scoreId);
          } on ScoreResultNotFoundException {
            changes[key] = null;
            return false;
          } on ScoreResultSessionExpiredException {
            return true;
          } on ScoreResultException {
            changes[key] = attached; // keep the jobId, retry the download
            return false;
          }
        }
        changes[key] = attached.copyWith(
          status: SubmissionStatus.ready,
          percentComplete: 100,
        );
      case ProcessingStage.failed:
        changes[key] = attached.copyWith(
          status: SubmissionStatus.failed,
          failureCode: status.failureReason?.apiValue.isNotEmpty == true
              ? status.failureReason!.apiValue
              : SubmissionFailure.unknown,
        );
      case ProcessingStage.cancelled:
        changes[key] = null;
      default:
        changes[key] = attached.copyWith(
          percentComplete: status.percentComplete,
        );
    }
    return false;
  }

  /// Fetches `/result` and downloads the files, so the score plays offline
  /// the moment it is marked ready. [LocalResultsStore.sync] never throws; a
  /// failed download leaves the score streamable and is retried on open.
  Future<void> _download(int scoreId) async {
    final data = (await _results.fetchResult(scoreId)).rawJson;
    if (data == null || !_resultsStore.hasFiles(data)) return;
    await _resultsStore.sync(
      scoreId,
      data,
      refetch: () async => (await _results.fetchResult(scoreId)).rawJson,
    );
    // A retake that finished while the app was closed changed this score's
    // version. If the saved copy is still the old one (a download failed),
    // the next open must not wait out the refresh throttle.
    final version = data['version'];
    if (version is String &&
        await _resultsStore.storedVersion(scoreId) != version) {
      await _resultsStore.resetThrottle(scoreId);
    }
  }
}
