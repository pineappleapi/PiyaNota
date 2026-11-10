import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../services/background_completion.dart';
import '../../services/piano_sync_service.dart';
import '../../services/scan_tracking_service.dart';
import '../../state/playback_providers.dart';
import '../../state/processing_providers.dart';
import '../../state/score_library_providers.dart';
import '../../state/submission_reconcile_providers.dart';
import '../../state/work_owner.dart';
import '../library/library_messages.dart';
import 'notification_landing_screen.dart';
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
    // Flag raised while the app is on screen is handled now; one raised
    // while it is away waits for the next resume.
    ref.listenManual(sessionExpiredFlagProvider, (_, raised) {
      if (raised && _inForeground()) _consumeSessionExpired();
    });
    // Piano octave: reconcile once the session is ready (AC 40), and retry a
    // pending PUT when the network returns or the app resumes (AC 47).
    ref.listenManual(signedInProvider, (_, signedIn) {
      if (signedIn) _pianoSync((s) => s.reconcile());
    }, fireImmediately: true);
    try {
      _online = ref.read(networkAvailabilityProvider).listen((online) {
        if (online && _wasOffline) _pianoSync((s) => s.flush());
        _wasOffline = !online;
      }, onError: (Object e) => debugPrint('Piano: connectivity: $e'));
    } on Object catch (e) {
      debugPrint('Piano: connectivity unavailable: $e');
    }
  }

  StreamSubscription<bool>? _online;
  bool _wasOffline = false;

  void _pianoSync(Future<Object?> Function(PianoSyncService) run) {
    if (!ref.read(signedInProvider)) return;
    try {
      unawaited(
        run(ref.read(pianoSyncServiceProvider)).catchError((Object e) {
          debugPrint('Piano: sync failed: $e');
          return null;
        }),
      );
    } on Object catch (e) {
      debugPrint('Piano: sync unavailable: $e');
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _resync();
      _pianoSync((s) => s.flush());
      unawaited(ref.read(reconcileSubmissionsProvider)(fresh: true));
      if (ref.read(sessionExpiredFlagProvider)) _consumeSessionExpired();
    }
  }

  /// A background refresh saw a 401. The Library re-asks the server and
  /// shows its own Login prompt if the token is really dead; a stray 401
  /// costs one list call. Local data is untouched.
  void _consumeSessionExpired() {
    ref.read(sessionExpiredFlagProvider.notifier).set(false);
    if (ref.read(signedInProvider)) ref.invalidate(scoreLibraryProvider);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_online?.cancel());
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
    // So the background run (Task 6) doesn't announce the same job again.
    unawaited(const NotifiedJobsStore().add(job.jobId));
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

  /// A tapped notification (warm start). The in-memory tracker may not know
  /// the job (the app was killed and relaunched, or the job came from the
  /// server list), so the landing screen asks the server first. Signed out:
  /// the app just comes to the front on Login.
  void _open(String payload) {
    final navigator = widget.navigatorKey.currentState;
    if (navigator == null || !ref.read(signedInProvider)) return;
    unawaited(openScanNotification(navigator, payload));
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
