import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../routes/app_routes.dart';
import '../../state/processing_providers.dart';
import '../../state/score_library_providers.dart';

/// PIYA-218 AC3's navigation rule, shared by every tap handler (library
/// card, bell row, toast) so they can't drift apart:
///
/// - running (active, reconnecting, paused) → Processing;
/// - failed → Processing, which shows the PIYA-207 failure view with its
///   Retake / Re-photograph / Delete actions;
/// - complete → Playback, which shows the PIYA-207 AC11 offer first when
///   a voice is unreadable and the offer is unanswered for that job.
///   Without a score id yet (PIYA-102 contract gap) it goes through
///   Processing, whose finish step explains where to find the score.
///
/// Finished jobs are marked read: the user has now seen them (AC6).
Future<void> openScanJob(
  NavigatorState navigator,
  WidgetRef ref,
  TrackedJob job, {
  String? title,
}) {
  final jobs = ref.read(processingJobsProvider.notifier);
  if (job.isFinished) jobs.markRead(job.jobId);
  final shownTitle = title ?? job.title ?? untitledScoreLabel;
  final scoreId = job.libraryScoreId;
  if (job.phase == TrackedPhase.complete && scoreId != null) {
    ref.read(scoreLibraryProvider.notifier).markOpened(scoreId);
    return navigator.pushNamed(
      AppRoutes.playback,
      arguments: PlaybackArguments(scoreId: scoreId, title: shownTitle),
    );
  }
  return navigator.pushNamed(
    AppRoutes.processing,
    arguments: ProcessingArguments(jobId: job.jobId, title: shownTitle),
  );
}
