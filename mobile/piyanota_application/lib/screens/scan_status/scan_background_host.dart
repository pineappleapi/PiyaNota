import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../services/scan_tracking_service.dart';
import '../../state/processing_providers.dart';
import '../library/library_messages.dart';
import 'scan_navigation.dart';
import 'scan_status_messages.dart';

/// PIYA-218, background half (user decision 2026-10-22): keeps scans
/// followed when the user leaves the app, and says when they finish.
///
/// - While any scan is running (paused included: it resumes by itself
///   when the network returns, AC10) the device's foreground service is
///   kept on with "Converting <title>…", so the tracker's poll goes on.
/// - A scan that completes or fails while the app is not on screen gets a
///   system notification; tapping it opens the score or its Processing
///   screen by the same rule as the bell ([openScanJob]). While the app is
///   on screen [ScanToastHost]'s banner says it instead, never both.
/// - A result seen in the app (read), or a job forgotten, takes its
///   notification away.
///
/// Logout's clean-up is [ScanTrackingService.stopAll], from
/// session_actions.
class ScanBackgroundHost extends ConsumerStatefulWidget {
  const ScanBackgroundHost({
    super.key,
    required this.navigatorKey,
    required this.child,
  });

  final GlobalKey<NavigatorState> navigatorKey;
  final Widget child;

  @override
  ConsumerState<ScanBackgroundHost> createState() => _ScanBackgroundHostState();
}

class _ScanBackgroundHostState extends ConsumerState<ScanBackgroundHost> {
  StreamSubscription<String>? _opened;

  /// The ongoing notification's words as last sent; null when stopped.
  String? _shown;

  ScanTrackingService get _device => ref.read(scanTrackingServiceProvider);

  @override
  void initState() {
    super.initState();
    _opened = _device.opened.listen(_open);
  }

  @override
  void dispose() {
    unawaited(_opened?.cancel());
    super.dispose();
  }

  void _onJobsChanged(
    Map<String, TrackedJob>? previous,
    Map<String, TrackedJob> next,
  ) {
    final running = [
      for (final job in next.values)
        if (job.isRunning) job.title ?? untitledScoreLabel,
    ];
    final words = running.isEmpty
        ? null
        : ScanStatusMessages.convertingInBackground(running);
    if (words != _shown) {
      _shown = words;
      unawaited(words == null ? _device.stop() : _device.show(words));
    }

    for (final job in next.values) {
      final before = previous?[job.jobId];
      if (before == null) continue;
      if (!before.isFinished && job.isFinished && !_inForeground()) {
        unawaited(_notify(job));
      } else if (!before.read && job.read) {
        unawaited(_device.clearResult(job.jobId));
      }
    }
    for (final jobId in previous?.keys ?? const <String>[]) {
      if (!next.containsKey(jobId)) unawaited(_device.clearResult(jobId));
    }
  }

  static bool _inForeground() {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == null || state == AppLifecycleState.resumed;
  }

  /// The same words as the in-app banner, so the two never disagree.
  Future<void> _notify(TrackedJob job) {
    final title = job.title ?? untitledScoreLabel;
    final ready = job.phase == TrackedPhase.complete;
    return _device.notifyResult(
      jobId: job.jobId,
      title: ready
          ? ScanStatusMessages.readyToast(title)
          // A failed retake left the earlier version as it was (PIYA-207
          // AC12).
          : job.retakeOfScoreId != null
          ? LibraryMessages.retakeFailed(title)
          : ScanStatusMessages.failedToast(title),
      text: ready
          ? ScanStatusMessages.readyNotificationHint
          : ScanStatusMessages.failedRowHint,
      ok: ready,
    );
  }

  /// A tapped notification. A job no longer followed (logged out since,
  /// or deleted) opens nothing: the app just comes to the front.
  void _open(String jobId) {
    final job = ref.read(processingJobsProvider)[jobId];
    final navigator = widget.navigatorKey.currentState;
    if (job == null || navigator == null) return;
    unawaited(openScanJob(navigator, ref, job));
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(processingJobsProvider, _onJobsChanged);
    return widget.child;
  }
}
