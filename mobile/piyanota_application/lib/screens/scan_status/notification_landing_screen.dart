import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../models/local_submission.dart';
import '../../routes/app_routes.dart';
import '../../services/scan_notification_payload.dart';
import '../../state/local_submission_providers.dart';
import '../../state/processing_providers.dart';
import '../../state/score_library_providers.dart';
import '../../state/submission_reconcile_providers.dart';
import '../../theme/app_theme.dart';
import 'scan_status_messages.dart';

/// Opens the screen for a tapped result notification. Warm and cold start
/// both come here with the raw payload. A payload that is not a job id (an
/// older notification, garbage) opens the Library; a good one shows
/// [NotificationLandingScreen].
Future<void> openScanNotification(NavigatorState navigator, Object? payload) {
  final jobId = ScanNotificationPayload.parse(payload);
  if (jobId == null) {
    return navigator.pushNamedAndRemoveUntil(
      AppRoutes.scoreLibrary,
      (_) => false,
    );
  }
  return navigator.push<void>(
    MaterialPageRoute<void>(
      settings: const RouteSettings(name: '/notification'),
      builder: (_) => NotificationLandingScreen(jobId: jobId),
    ),
  );
}

/// What a notification tap lands on while the app asks the server what became
/// of the job (the app may have been closed for the whole conversion). It
/// then replaces itself with the score, its Processing screen, or the Library
/// with a message; it never stays blank.
class NotificationLandingScreen extends ConsumerStatefulWidget {
  const NotificationLandingScreen({super.key, required this.jobId});

  final String jobId;

  /// A slow or hung server must not trap the user here.
  static const Duration reconcileTimeout = Duration(seconds: 15);

  /// Side gutter and the gap under the spinner (16 dp: the app's standard).
  static const double sideGutter = 16;
  static const double spinnerGap = 16;

  @override
  ConsumerState<NotificationLandingScreen> createState() =>
      _NotificationLandingScreenState();
}

class _NotificationLandingScreenState
    extends ConsumerState<NotificationLandingScreen> {
  @override
  void initState() {
    super.initState();
    unawaited(_resolve());
  }

  Future<void> _resolve() async {
    final jobs = ref.read(processingJobsProvider.notifier);
    final reconcile = ref.read(reconcileSubmissionsProvider);
    final store = ref.read(localSubmissionStoreProvider);
    await jobs.restored;
    try {
      await reconcile(
        force: true,
        fresh: true,
      ).timeout(NotificationLandingScreen.reconcileTimeout);
    } on Object catch (e) {
      // Offline or slow: what is already on the phone still decides below.
      debugPrint('Notification landing: reconcile failed: $e');
    }
    List<LocalSubmission> rows;
    try {
      // Fresh: the background isolate may have written rows this process's
      // preferences cache has not seen.
      rows = await store.load(fresh: true);
    } on Object catch (e) {
      debugPrint('Notification landing: reading submissions failed: $e');
      rows = const [];
    }
    if (!mounted) return;

    final id = widget.jobId;
    final row = rows.where((r) => r.jobId == id).firstOrNull;
    final tracked = ref.read(processingJobsProvider)[id];
    final title = row?.title ?? tracked?.title ?? untitledScoreLabel;
    final trackedScore = tracked?.phase == TrackedPhase.complete
        ? tracked?.libraryScoreId
        : null;
    final readyScore = row?.status == SubmissionStatus.ready
        ? row?.scoreId
        : null;
    final scoreId = readyScore ?? trackedScore;

    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    if (scoreId != null) {
      if (tracked?.isFinished ?? false) jobs.markRead(id);
      final library = ref.read(scoreLibraryProvider.notifier);
      library.markOpened(scoreId);
      // A score finished while the app was closed is not in the loaded list.
      unawaited(library.reload());
      unawaited(
        navigator.pushReplacementNamed(
          AppRoutes.playback,
          arguments: PlaybackArguments(scoreId: scoreId, title: title),
        ),
      );
      return;
    }
    final failed =
        row?.status == SubmissionStatus.failed ||
        tracked?.phase == TrackedPhase.failed;
    // A tracked "complete" with no score id yet: Processing explains where to
    // find the score (same rule as openScanJob).
    final running =
        !failed &&
        (row?.status == SubmissionStatus.processing ||
            (tracked != null &&
                (tracked.isRunning || tracked.phase == TrackedPhase.complete)));
    if (running) {
      unawaited(
        navigator.pushReplacementNamed(
          AppRoutes.processing,
          arguments: ProcessingArguments(jobId: id, title: title),
        ),
      );
      return;
    }
    // A failed job opens its failure view (reason and Retake) in place of
    // the Library-only snackbar.
    if (failed) {
      unawaited(
        navigator.pushReplacementNamed(
          AppRoutes.processing,
          arguments: ProcessingArguments(jobId: id, title: title),
        ),
      );
      return;
    }
    unawaited(
      navigator.pushNamedAndRemoveUntil(AppRoutes.scoreLibrary, (_) => false),
    );
    // A finished row with no score id is not "gone": the Library lists it.
    if (row?.status == SubmissionStatus.ready) return;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: const Text(ScanStatusMessages.notificationGone),
          duration: AppTheme.snackBarDuration,
          behavior: SnackBarBehavior.floating,
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: NotificationLandingScreen.sideGutter,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const CircularProgressIndicator(
                  semanticsLabel: ScanStatusMessages.openingFromNotification,
                ),
                const SizedBox(height: NotificationLandingScreen.spinnerGap),
                Text(
                  ScanStatusMessages.openingFromNotification,
                  key: const ValueKey('notification-loading'),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
