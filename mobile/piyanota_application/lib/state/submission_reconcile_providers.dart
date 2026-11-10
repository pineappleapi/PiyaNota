import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';
import '../services/processing_api.dart';
import '../services/score_result_api.dart';
import '../services/submission_reconciler.dart';
import 'auth_providers.dart';
import 'local_submission_providers.dart';
import 'playback_providers.dart';
import 'processing_providers.dart';
import 'work_owner.dart';

/// No job list exists in the fake backend: reconcile then stops as
/// "unavailable" and leaves every row as it is. Tests override
/// [jobListApiProvider] to exercise it.
class _NoJobListApi implements JobListApi {
  const _NoJobListApi();

  @override
  Future<List<ListedJob>> listJobs() async =>
      throw const ProcessingServerException();
}

final jobListApiProvider = Provider<JobListApi>((ref) {
  if (ApiConfig.useFakeAuth) return const _NoJobListApi();
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpProcessingApi(
    ref.watch(dioProvider),
    ref.watch(sessionStorageProvider),
  );
});

/// The fake backend keeps no by-submission table: a cancel there always
/// reports the job as not existing.
class _FakeSubmissionCancelApi implements SubmissionCancelApi {
  const _FakeSubmissionCancelApi();

  @override
  Future<SubmissionCancelResult> cancelBySubmission(String id) async =>
      (jobId: null, status: 'cancelled');
}

final submissionCancelApiProvider = Provider<SubmissionCancelApi>((ref) {
  if (ApiConfig.useFakeAuth) return const _FakeSubmissionCancelApi();
  final configError = ApiConfig.configurationError();
  if (configError != null) throw StateError(configError);
  return HttpProcessingApi(
    ref.watch(dioProvider),
    ref.watch(sessionStorageProvider),
  );
});

final submissionReconcilerProvider = Provider<SubmissionReconciler>((ref) {
  final fake = ApiConfig.useFakeAuth;
  return SubmissionReconciler(
    processing: ref.watch(processingApiProvider),
    jobList: ref.watch(jobListApiProvider),
    // Not the local-first wrapper: its download is fire-and-forget, and
    // reconcile must finish the download before it marks a score ready.
    results: fake
        ? ref.watch(scoreResultApiProvider)
        : HttpScoreResultApi(
            ref.watch(dioProvider),
            ref.watch(sessionStorageProvider),
          ),
    submissions: ref.watch(localSubmissionStoreProvider),
    resultsStore: ref.watch(localResultsStoreProvider),
  );
});

/// The foreground's way in: app start (after login), resume, Library open and
/// the Library's timer all call it. Does nothing while signed out; after a
/// run that changed rows it refreshes the controller the Library watches.
/// Single-flight and rate-limited by the reconciler itself.
final reconcileSubmissionsProvider =
    Provider<Future<ReconcileResult> Function({bool force, bool fresh})>(
      (ref) => ({bool force = false, bool fresh = false}) async {
        if (!ref.read(signedInProvider)) return ReconcileResult.skipped;
        final SubmissionReconciler reconciler;
        try {
          reconciler = ref.read(submissionReconcilerProvider);
        } on Object {
          // The fake backend has no processing API without the fake library
          // (and a bad build config throws too): nothing to reconcile, and a
          // background refresh must never break the screen that asked.
          return ReconcileResult.unavailable;
        }
        // [fresh]: the background isolate may have written rows while this
        // one was away, and prefs are cached per isolate.
        final result = await reconciler.run(force: force, fresh: fresh);
        if ((result == ReconcileResult.done || fresh) && ref.mounted) {
          await ref
              .read(localSubmissionsProvider.notifier)
              .reload(fresh: fresh);
        }
        return result;
      },
    );
