import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../models/library_entry.dart';
import '../models/local_submission.dart';
import '../screens/scan_status/scan_status_messages.dart';
import 'local_results_store.dart';
import 'local_submission_store.dart';
import 'processing_api.dart';
import 'scan_notification_payload.dart';
import 'score_result_api.dart';
import 'session_storage.dart';
import 'submission_reconciler.dart';

/// Job ids whose "finished" notification was already posted, by the
/// foreground tracker or by the background run, so the other never repeats
/// it (job-lifecycle Task 6). Plain ids in SharedPreferences, no secrets.
/// shortcut: read-modify-write is not atomic across isolates; the worst case
/// is one repeated notification, which has the same id and so replaces the
/// first. Upgrade only if that is ever seen.
class NotifiedJobsStore {
  const NotifiedJobsStore();

  @visibleForTesting
  static const String storageKey = 'notified_jobs_v1';

  /// Far more than a user converts in the 7 days a job stays listed.
  static const int _keep = 100;

  Future<Set<String>> load({bool fresh = false}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (fresh) await prefs.reload();
      return (prefs.getStringList(storageKey) ?? const []).toSet();
    } on Object catch (e) {
      debugPrint('Notified jobs not restored: $e');
      return {};
    }
  }

  Future<void> add(String jobId, {bool fresh = false}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (fresh) await prefs.reload();
      final ids =
          (prefs.getStringList(storageKey) ?? const <String>[])
              .where((id) => id != jobId)
              .toList()
            ..add(jobId);
      await prefs.setStringList(
        storageKey,
        ids.length > _keep ? ids.sublist(ids.length - _keep) : ids,
      );
    } on Object catch (e) {
      debugPrint('Notified job not saved: $e');
    }
  }
}

/// A finished conversion the background run found and should announce.
typedef BackgroundNotice = ({String jobId, String title, bool ok});

/// What one background run decided.
typedef BackgroundOutcome = ({
  bool keepScheduled,
  List<BackgroundNotice> notices,
});

/// The decision logic of the background run, free of the platform so it can
/// be tested with fakes: run the foreground's reconciler (Task 4), then
/// announce each row that went from converting to ready or failed during
/// this run and was not announced before.
class BackgroundCompletion {
  BackgroundCompletion({
    required this._reconciler,
    required this._submissions,
    required this._notified,
    this.isCancelled,
  });

  /// Same check the reconciler was given: the app came to the foreground.
  final Future<bool> Function()? isCancelled;

  final SubmissionReconciler _reconciler;
  final LocalSubmissionStore _submissions;
  final NotifiedJobsStore _notified;

  Future<BackgroundOutcome> run() async {
    if (await isCancelled?.call() ?? false) return _retryLater;
    // A background isolate has a stale preferences cache: always fresh.
    final before = {
      for (final r in await _submissions.load(fresh: true))
        r.clientSubmissionId: r,
    };
    if (!before.values.any(_isProcessing)) {
      return (keepScheduled: false, notices: const <BackgroundNotice>[]);
    }
    final result = await _reconciler.run(fresh: true, force: true);
    if (result == ReconcileResult.sessionExpired) {
      // Quiet stop: nothing cleared, the foreground sends the user to Login.
      return (keepScheduled: false, notices: const <BackgroundNotice>[]);
    }
    // Cancelled: the foreground is up and says it itself; nothing to announce.
    if (result != ReconcileResult.done) return _retryLater;
    if (await isCancelled?.call() ?? false) return _retryLater;
    final after = await _submissions.load(fresh: true);
    final notified = await _notified.load(fresh: true);
    final notices = <BackgroundNotice>[];
    for (final row in after) {
      final was = before[row.clientSubmissionId];
      final jobId = row.jobId;
      if (was == null || !_isProcessing(was) || jobId == null) continue;
      final ok = row.status == SubmissionStatus.ready;
      if (!ok && row.status != SubmissionStatus.failed) continue;
      if (notified.contains(jobId)) continue;
      notices.add((jobId: jobId, title: row.title, ok: ok));
    }
    return (keepScheduled: after.any(_isProcessing), notices: notices);
  }

  static const BackgroundOutcome _retryLater = (
    keepScheduled: true,
    notices: <BackgroundNotice>[],
  );

  /// Called after each notification was handed to the device.
  Future<void> markNotified(String jobId) => _notified.add(jobId, fresh: true);

  static bool _isProcessing(LocalSubmission r) =>
      r.status == SubmissionStatus.processing;
}

/// Tells Android to run (or stop running) the background job. Quiet on
/// failure: the foreground reconcile is the primary path.
class BackgroundCompletionScheduler {
  BackgroundCompletionScheduler([MethodChannel? channel])
    : _channel = channel ?? const MethodChannel(channelName);

  static const String channelName = 'piyanota/background';

  final MethodChannel _channel;

  Future<void> schedule() => _quietly('schedule');

  Future<void> cancel() => _quietly('cancel');

  /// A system picker (gallery, PDF) is open over the app: the job skips its
  /// run while it is, as it does while the app is on screen.
  Future<void> pickerOpen(bool open) => _quietly('pickerOpen', {'open': open});

  Future<void> _quietly(String method, [Object? arguments]) async {
    try {
      await _channel.invokeMethod<void>(method, arguments);
    } on PlatformException catch (e) {
      debugPrint('Background completion: $method failed: $e');
    } on MissingPluginException {
      // Tests and platforms without the native side.
    }
  }
}

/// Entry point of the headless Flutter engine the Android job starts
/// (BackgroundCompletionJob.kt) while the app is closed. Never runs in the
/// app's own isolate. Tokens come from secure storage inside the Http APIs;
/// nothing here logs or stores one.
@pragma('vm:entry-point')
Future<void> backgroundCompletionMain() async {
  WidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel(BackgroundCompletionScheduler.channelName);
  var keep = false;
  try {
    keep = await _runBackground(channel);
  } on Object catch (e) {
    // Best effort: a failed run is retried at the next period.
    debugPrint('Background completion failed: $e');
    keep = true;
  } finally {
    await channel.invokeMethod<void>('finish', {'keep': keep});
  }
}

Future<bool> _runBackground(MethodChannel channel) async {
  if (ApiConfig.useFakeAuth || ApiConfig.configurationError() != null) {
    return false;
  }
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.connectTimeout,
      receiveTimeout: ApiConfig.receiveTimeout,
      contentType: Headers.jsonContentType,
    ),
  );
  final session = SessionStorage();
  final api = HttpProcessingApi(dio, session);
  // Asked between steps: the app on screen owns the rows, so this run yields.
  Future<bool> cancelled() async {
    try {
      return await channel.invokeMethod<bool>('cancelRequested') ?? false;
    } on PlatformException {
      return false;
    }
  }

  const submissions = LocalSubmissionStore();
  const notified = NotifiedJobsStore();
  final completion = BackgroundCompletion(
    reconciler: SubmissionReconciler(
      processing: api,
      jobList: api,
      results: HttpScoreResultApi(dio, session),
      submissions: submissions,
      isCancelled: cancelled,
      resultsStore: LocalResultsStore(
        // Same folder as localResultsStoreProvider.
        rootProvider: () async {
          final support = await getApplicationSupportDirectory();
          return Directory('${support.path}${Platform.pathSeparator}results');
        },
        downloader: DioFileDownloader(dio),
      ),
    ),
    submissions: submissions,
    notified: notified,
    isCancelled: cancelled,
  );
  final outcome = await completion.run();
  for (final notice in outcome.notices) {
    if (await cancelled()) break;
    final payload = ScanNotificationPayload.build(notice.jobId);
    if (payload == null) continue;
    final title = notice.title.trim().isEmpty
        ? untitledScoreLabel
        : notice.title;
    try {
      await channel.invokeMethod<void>('notifyResult', {
        'jobId': payload,
        'title': notice.ok
            ? ScanStatusMessages.readyNotification(title)
            : ScanStatusMessages.failedToast(title),
        'text': notice.ok
            ? ScanStatusMessages.readyNotificationHint
            : ScanStatusMessages.failedRowHint,
        'ok': notice.ok,
      });
      await completion.markNotified(notice.jobId);
    } on PlatformException catch (e) {
      debugPrint('Background completion: notify failed: $e');
    }
  }
  return outcome.keepScheduled;
}
