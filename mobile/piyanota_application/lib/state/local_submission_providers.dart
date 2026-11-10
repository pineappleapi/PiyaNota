import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/local_submission.dart';
import '../config/api_config.dart';
import '../services/background_completion.dart';
import '../services/local_submission_store.dart';
import '../services/processing_api.dart';
import '../services/submission_reconciler.dart';
import 'processing_providers.dart';
import 'score_library_providers.dart';
import 'submission_reconcile_providers.dart';

final localSubmissionStoreProvider = Provider<LocalSubmissionStore>(
  (ref) => const LocalSubmissionStore(),
);

final backgroundCompletionSchedulerProvider =
    Provider<BackgroundCompletionScheduler>(
      (ref) => BackgroundCompletionScheduler(),
    );

/// The user's persisted submissions, newest first (job-lifecycle plan,
/// Task 3). Not tied to the signed-in state: the rows must be there when the
/// app reopens, and [LocalSubmissionsController.forgetAll] (explicit logout /
/// account switch) is the only wipe: a session expiry never calls it.
final localSubmissionsProvider =
    NotifierProvider<LocalSubmissionsController, List<LocalSubmission>>(
      LocalSubmissionsController.new,
    );

class LocalSubmissionsController extends Notifier<List<LocalSubmission>> {
  /// Bumped by [forgetAll], so a restore still reading storage can't bring
  /// a wiped account's rows back.
  int _clearEpoch = 0;
  final Completer<void> _restored = Completer();

  LocalSubmissionStore get _store => ref.read(localSubmissionStoreProvider);

  @override
  List<LocalSubmission> build() {
    unawaited(_restore());
    return const [];
  }

  Future<void> _restore() async {
    final epoch = _clearEpoch;
    final stored = await _store.load();
    if (ref.mounted && epoch == _clearEpoch) {
      // Rows added while the read was in flight are newer; keep them.
      final live = {for (final r in state) r.clientSubmissionId};
      state = _newestFirst([
        ...state,
        for (final r in stored)
          if (!live.contains(r.clientSubmissionId)) r,
      ]);
    }
    if (!_restored.isCompleted) _restored.complete();
  }

  static List<LocalSubmission> _newestFirst(List<LocalSubmission> rows) =>
      [...rows]..sort((a, b) => b.createdAt.compareTo(a.createdAt));

  /// Applies ONE row's change (an upsert, or a removal when [upsert] is
  /// null) to memory at once, and to disk as a merge by id against a fresh
  /// load, never by writing the whole list: the background isolate may have
  /// changed other rows since this isolate last read them.
  Future<void> _persist(String id, LocalSubmission? upsert) async {
    state = _newestFirst([
      for (final r in state)
        if (r.clientSubmissionId != id) r,
      ?upsert,
    ]);
    final epoch = _clearEpoch;
    await _store.update(
      (disk) => [
        for (final r in disk)
          if (r.clientSubmissionId != id) r,
        ?upsert,
      ],
      fresh: true,
    );
    if (ref.mounted && epoch == _clearEpoch) _syncBackgroundJob();
  }

  /// The Android background job (Task 6) runs only while a row is
  /// converting: scheduled when one is created, cancelled when none is left.
  /// Idempotent on the device. Off with the fake backend (nothing to poll).
  void _syncBackgroundJob() {
    if (ApiConfig.useFakeAuth || !ref.mounted) return;
    final scheduler = ref.read(backgroundCompletionSchedulerProvider);
    unawaited(
      state.any((r) => r.status == SubmissionStatus.processing)
          ? scheduler.schedule()
          : scheduler.cancel(),
    );
  }

  LocalSubmission? byClientId(String clientSubmissionId) => state
      .where((r) => r.clientSubmissionId == clientSubmissionId)
      .firstOrNull;

  /// Writes the row BEFORE the upload starts. Called again with the same id
  /// (a retry after a lost 202) it keeps the original `createdAt`, drops the
  /// failure and goes back to processing.
  Future<void> begin({
    required String clientSubmissionId,
    required String title,
    DateTime? now,
    String? replacesJobId,
  }) async {
    await _restored.future;
    if (!ref.mounted) return;
    final existing = byClientId(clientSubmissionId);
    final row = existing == null
        ? LocalSubmission(
            clientSubmissionId: clientSubmissionId,
            title: title,
            createdAt: (now ?? DateTime.now()).toUtc(),
            replacesJobId: replacesJobId,
          )
        : existing.copyWith(
            status: SubmissionStatus.processing,
            clearFailure: true,
          );
    await _persist(clientSubmissionId, row);
  }

  /// Fills `jobId` (and the score it fills) from the 202.
  Future<void> attachJob({
    required String clientSubmissionId,
    required String jobId,
    int? scoreId,
  }) => _update(
    clientSubmissionId,
    (r) => r.copyWith(
      jobId: jobId,
      scoreId: scoreId,
      status: SubmissionStatus.processing,
      clearFailure: true,
    ),
  );

  /// [code] is the server's `error.code` or a [SubmissionFailure] value.
  Future<void> fail({
    required String clientSubmissionId,
    required String code,
  }) => _update(
    clientSubmissionId,
    (r) => r.copyWith(status: SubmissionStatus.failed, failureCode: code),
  );

  /// Re-reads the store after a reconcile run changed it behind this
  /// controller's back. Rows added meanwhile are kept (same rule as restore).
  Future<void> reload({bool fresh = false}) async {
    await _restored.future;
    final epoch = _clearEpoch;
    final stored = await _store.load(fresh: fresh);
    if (!ref.mounted || epoch != _clearEpoch) return;
    final storedIds = {for (final r in stored) r.clientSubmissionId};
    // A row only in memory was added after the read started; keep it.
    state = _newestFirst([
      ...stored,
      for (final r in state)
        if (!storedIds.contains(r.clientSubmissionId) && _justAdded(r)) r,
    ]);
    _syncBackgroundJob();
  }

  /// Rows made in the last few seconds may not have reached disk when
  /// [reload] read it; anything older that is missing was removed.
  bool _justAdded(LocalSubmission row) =>
      DateTime.now().toUtc().difference(row.createdAt) < _recentRow;

  static const Duration _recentRow = Duration(seconds: 10);

  /// Also remembers the id, so reconcile never rebuilds the row from the
  /// server's job list (retention: [SubmissionReconciler.retention]).
  Future<void> dismiss(String clientSubmissionId) async {
    await _restored.future;
    if (!ref.mounted) return;
    final jobId = byClientId(clientSubmissionId)?.jobId;
    await _store.markDismissed(
      [clientSubmissionId, ?jobId],
      DateTime.now().toUtc(),
      retention: SubmissionReconciler.retention,
    );
    if (!ref.mounted) return;
    await _persist(clientSubmissionId, null);
  }

  /// A retake was accepted (202): deletes the FAILED row of [oldJobId] and
  /// tombstones its ids so reconcile can't bring it back from `GET /api/jobs`.
  /// Memory changes first (no frame shows the old card beside the new one),
  /// the tombstone is written before the row leaves disk. No failed row for
  /// that job (a completed score being re-photographed, or none): no-op.
  Future<void> replaceFailedJob(String oldJobId) async {
    await _restored.future;
    if (!ref.mounted) return;
    final old = state
        .where(
          (r) => r.jobId == oldJobId && r.status == SubmissionStatus.failed,
        )
        .firstOrNull;
    if (old == null) return;
    state = [
      for (final r in state)
        if (r.clientSubmissionId != old.clientSubmissionId) r,
    ];
    await _store.markDismissed(
      [old.clientSubmissionId, oldJobId],
      DateTime.now().toUtc(),
      retention: SubmissionReconciler.retention,
    );
    if (!ref.mounted) return;
    await _persist(old.clientSubmissionId, null);
  }

  /// Explicit cancel of a persisted row (Task 7). No job id yet (pre-202):
  /// cancel by the phone-made id, so the server cancels a job it already
  /// made or refuses the upload still in flight (409 `submission_cancelled`).
  /// A terminal answer (`complete`/`failed`) keeps the row and reconciles
  /// it. A failed call keeps the row so the user can try again, unless
  /// [dismissOnFailure] (the capture screen, which has no row to show):
  /// then the local tombstone alone hides a job that still lands, the old
  /// behaviour. With a job id: POST cancel; 409 means it already finished,
  /// so the row is kept and reconciled instead.
  Future<CancelOutcome> cancel(
    String clientSubmissionId, {
    bool dismissOnFailure = false,
  }) async {
    await _restored.future;
    final jobId = byClientId(clientSubmissionId)?.jobId;
    if (jobId == null) {
      return _cancelUnsent(clientSubmissionId, dismissOnFailure);
    }
    try {
      await ref.read(processingApiProvider).cancelJob(jobId);
    } on ProcessingConflictException {
      if (ref.mounted) {
        await ref.read(reconcileSubmissionsProvider)(force: true);
      }
      return CancelOutcome.alreadyFinished;
    } on ProcessingJobNotFoundException {
      await dismiss(clientSubmissionId);
      return CancelOutcome.notFound;
    } on ProcessingSessionExpiredException {
      return CancelOutcome.sessionExpired;
    } on ProcessingException {
      return CancelOutcome.failed;
    }
    if (!ref.mounted) return CancelOutcome.cancelled;
    await dismiss(clientSubmissionId);
    if (ref.mounted) ref.invalidate(scoreLibraryProvider);
    return CancelOutcome.cancelled;
  }

  Future<CancelOutcome> _cancelUnsent(String id, bool dismissOnFailure) async {
    try {
      final result = await ref
          .read(submissionCancelApiProvider)
          .cancelBySubmission(id);
      if (result.status != 'cancelled') {
        if (ref.mounted) {
          await ref.read(reconcileSubmissionsProvider)(force: true);
        }
        return CancelOutcome.alreadyFinished;
      }
    } on ProcessingSessionExpiredException {
      if (dismissOnFailure) await dismiss(id);
      return CancelOutcome.sessionExpired;
    } on ProcessingException {
      if (dismissOnFailure) await dismiss(id);
      return CancelOutcome.failed;
    }
    if (!ref.mounted) return CancelOutcome.cancelled;
    await dismiss(id);
    if (ref.mounted) ref.invalidate(scoreLibraryProvider);
    return CancelOutcome.cancelled;
  }

  Future<void> _update(
    String clientSubmissionId,
    LocalSubmission Function(LocalSubmission) change,
  ) async {
    await _restored.future;
    if (!ref.mounted || byClientId(clientSubmissionId) == null) return;
    await _persist(
      clientSubmissionId,
      change(
        state.firstWhere((r) => r.clientSubmissionId == clientSubmissionId),
      ),
    );
  }

  /// Logout or account switch: another account must never see these rows.
  void forgetAll() {
    _clearEpoch++;
    state = const [];
    unawaited(_store.clear());
    if (!ApiConfig.useFakeAuth) {
      unawaited(ref.read(backgroundCompletionSchedulerProvider).cancel());
    }
  }
}
