import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../services/scan_tracking_service.dart';
import '../../state/processing_providers.dart';
import '../../state/work_owner.dart';
import '../library/library_messages.dart';
import 'scan_navigation.dart';
import 'scan_status_messages.dart';

/// PIYA-218, background half (user decision 2026-10-22): keeps scans
/// followed when the user leaves the app, and says when they finish.
///
/// - While any scan is followed, after login, the device's foreground
///   service is kept on with "Scanning <title>…", so the tracker's poll
///   goes on. A scan paused for want of a network keeps it too, with
///   "Waiting for connection…" once every scan is paused (review N1): the
///   service keeps the engine, and so the network listener that resumes
///   the poll (AC10), alive while the app is away.
/// - When the service went by itself (Android 15+'s timeout, a refused
///   start) the device says so, and the words are sent again at the next
///   change or when the app comes back to the foreground, where a start is
///   allowed. No notice of its own: the timeout stays silent until then.
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

class _ScanBackgroundHostState extends ConsumerState<ScanBackgroundHost>
    with WidgetsBindingObserver {
  StreamSubscription<String>? _opened;
  StreamSubscription<void>? _stopped;

  /// The device stopped the service itself. From the background a new
  /// start would only be refused again (and after Android 15's timeout it
  /// must not be tried), so it waits for the foreground.
  bool _stoppedByDevice = false;

  /// The ongoing notification's words as last sent; null when stopped.
  String? _shown;

  ScanTrackingService get _device => ref.read(scanTrackingServiceProvider);

  @override
  void initState() {
    super.initState();
    _opened = _device.opened.listen(_open);
    _stopped = _device.stopped.listen((_) {
      _shown = null;
      _stoppedByDevice = true;
    });
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _resync();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_stopped?.cancel());
    unawaited(_opened?.cancel());
    super.dispose();
  }

  void _onJobsChanged(
    Map<String, TrackedJob>? previous,
    Map<String, TrackedJob> next,
  ) {
    _syncService(next);

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

  /// Back in the foreground: show the words again, in case the service
  /// went while the app was away (a foreground start is allowed now).
  void _resync() {
    if (!mounted) return;
    _shown = null;
    _stoppedByDevice = false;
    _syncService(ref.read(processingJobsProvider));
  }

  /// The service runs while any scan is followed after login (nothing
  /// polls before, M1), offline-paused ones included (N1). It stops once
  /// none is left, or on logout.
  void _syncService(Map<String, TrackedJob> jobs) {
    final followed = [
      if (ref.read(signedInProvider))
        for (final job in jobs.values)
          if (job.isRunning) job,
    ];
    final polled = [
      for (final job in followed)
        if (job.phase != TrackedPhase.paused) job.title ?? untitledScoreLabel,
    ];
    final words = followed.isEmpty
        ? null
        : polled.isEmpty
        ? ScanStatusMessages.waitingForConnection
        : ScanStatusMessages.scanningInBackground(polled);
    if (words != null && _stoppedByDevice && !_inForeground()) return;
    _stoppedByDevice = false;
    if (words != _shown) {
      _shown = words;
      unawaited(words == null ? _device.stop() : _device.show(words));
    }
  }

  static bool _inForeground() {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == null || state == AppLifecycleState.resumed;
  }

  /// The banner's failure words; for a ready scan AC7's own notification
  /// wording ("Your piano guide for [Score] is ready.").
  Future<void> _notify(TrackedJob job) {
    final title = job.title ?? untitledScoreLabel;
    final ready = job.phase == TrackedPhase.complete;
    return _device.notifyResult(
      jobId: job.jobId,
      title: ready
          ? ScanStatusMessages.readyNotification(title)
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
    ref.listen<bool>(
      signedInProvider,
      (_, _) => _syncService(ref.read(processingJobsProvider)),
    );
    return widget.child;
  }
}
