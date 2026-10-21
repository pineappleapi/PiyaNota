import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../routes/app_routes.dart';
import '../../state/export_jobs.dart';
import '../../state/export_providers.dart';
import '../../state/processing_providers.dart';
import '../../theme/app_theme.dart';
import '../library/library_messages.dart';
import '../playback/export_messages.dart';
import 'scan_navigation.dart';
import 'scan_status_messages.dart';

/// PIYA-218 AC7, foreground half: when a scan completes or fails while the
/// app is open, a small banner says so, "[Score] is ready. [Open]" (or
/// its failure equivalent), wherever the user is, unless they are on that
/// scan's own Processing screen, which shows the result itself.
///
/// Sits above the Navigator (MaterialApp.builder), so it covers every
/// screen without each one listening. Drawn at the top so it never hides
/// the library's bottom nav or a screen's own snackbars.
///
/// Exports use the same banner (user decision 2026-10-21): "Saved [file]
/// to [folder]. Open folder" or that it failed, unless that score's
/// Export sheet is open and showing the result itself. A cancel is not
/// announced: only the sheet's X cancels.
///
/// Background push (the app closed or in the background) is not built
/// here: it needs an OS notification plugin and a server-side sender
/// (ticket's backend dependencies), so a scan that finishes while the app
/// is in the background shows only in the bell and on its card.
class ScanToastHost extends ConsumerStatefulWidget {
  const ScanToastHost({
    super.key,
    required this.navigatorKey,
    required this.routes,
    required this.child,
  });

  final GlobalKey<NavigatorState> navigatorKey;

  /// The navigator's stack, so a dialog or sheet over a scan's Processing
  /// screen still counts as watching it.
  final ScanRouteStack routes;
  final Widget child;

  /// Long enough to read and reach the button; the bell keeps the item.
  static const Duration showFor = Duration(seconds: 4);

  @override
  ConsumerState<ScanToastHost> createState() => _ScanToastHostState();
}

class _ScanToastHostState extends ConsumerState<ScanToastHost> {
  TrackedJob? _shown;

  /// An export's banner; only one banner shows at a time.
  ExportTask? _shownExport;
  Timer? _hideTimer;

  static const double _margin = 16;
  static const double _radius = 12;
  static const double _elevation = 6;
  static const Duration _fade = Duration(milliseconds: 200);

  @override
  void dispose() {
    _hideTimer?.cancel();
    super.dispose();
  }

  void _onJobsChanged(
    Map<String, TrackedJob>? previous,
    Map<String, TrackedJob> next,
  ) {
    for (final job in next.values) {
      final before = previous?[job.jobId];
      // Only a change seen live: a job restored already finished has no
      // "before". A restored running job that the re-poll finds finished
      // does toast, since the user is here now and hasn't heard (AC8).
      if (before == null || before.isFinished || !job.isFinished) continue;
      if (!_inForeground() || _isWatching(job.jobId)) continue;
      _show(job);
    }
  }

  static bool _inForeground() {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == null || state == AppLifecycleState.resumed;
  }

  /// True when the top screen is Processing for [jobId], even with a
  /// popup (dialog, sheet, menu) open over it.
  bool _isWatching(String jobId) {
    final screen = widget.routes.topScreen;
    final settings = screen?.settings;
    final arguments = settings?.arguments;
    return settings?.name == AppRoutes.processing &&
        arguments is ProcessingArguments &&
        arguments.jobId == jobId;
  }

  void _show(TrackedJob job) {
    _hideTimer?.cancel();
    _hideTimer = Timer(ScanToastHost.showFor, _hide);
    setState(() {
      _shown = job;
      _shownExport = null;
    });
  }

  void _onExportsChanged(List<ExportTask>? previous, List<ExportTask> next) {
    final jobs = ref.read(exportJobsProvider.notifier);
    for (final task in next) {
      final before = previous?.where((t) => t.id == task.id).firstOrNull;
      if (before == null || before.isFinished || !task.isFinished) continue;
      if (task.status == ExportTaskStatus.cancelled) continue;
      if (!_inForeground() || jobs.isSheetOpen(task.scoreId)) continue;
      _hideTimer?.cancel();
      _hideTimer = Timer(ScanToastHost.showFor, _hide);
      setState(() {
        _shownExport = task;
        _shown = null;
      });
    }
  }

  void _hide() {
    _hideTimer?.cancel();
    _hideTimer = null;
    if (mounted) {
      setState(() {
        _shown = null;
        _shownExport = null;
      });
    }
  }

  void _openExportFolder(ExportTask task) {
    _hide();
    ref.read(exportJobsProvider.notifier).markRead(task.id);
    unawaited(ref.read(exportServiceProvider).openFolder(task.treeUri));
  }

  void _open(TrackedJob job) {
    _hide();
    final navigator = widget.navigatorKey.currentState;
    if (navigator == null) return;
    // The latest state, not the one the toast was built from.
    final current = ref.read(processingJobsProvider)[job.jobId] ?? job;
    unawaited(openScanJob(navigator, ref, current));
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(processingJobsProvider, _onJobsChanged);
    ref.listen(exportJobsProvider, _onExportsChanged);
    final job = _shown;
    final export = _shownExport;
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    return Stack(
      children: [
        widget.child,
        Positioned(
          top: MediaQuery.paddingOf(context).top + _margin / 2,
          left: _margin,
          right: _margin,
          child: AnimatedSwitcher(
            duration: reduceMotion ? Duration.zero : _fade,
            child: job != null
                ? _banner(context, job)
                : export != null
                ? _exportBanner(context, export)
                : const SizedBox.shrink(),
          ),
        ),
      ],
    );
  }

  Widget _banner(BuildContext context, TrackedJob job) {
    final title = job.title ?? untitledScoreLabel;
    final ready = job.phase == TrackedPhase.complete;
    final message = ready
        ? ScanStatusMessages.readyToast(title)
        // A failed retake of a completed score left that score as it was
        // (PIYA-207 AC12); say so rather than "couldn't be converted".
        : job.retakeOfScoreId != null
        ? LibraryMessages.retakeFailed(title)
        : ScanStatusMessages.failedToast(title);
    return _bannerFrame(
      context,
      key: ValueKey('scan-toast-${job.jobId}'),
      ok: ready,
      message: message,
      action: TextButton(
        key: const ValueKey('scan-toast-open'),
        onPressed: () => _open(job),
        style: _actionStyle,
        child: Text(ready ? ScanStatusMessages.open : ScanStatusMessages.view),
      ),
    );
  }

  Widget _exportBanner(BuildContext context, ExportTask task) {
    final result = task.result;
    final saved = task.status == ExportTaskStatus.saved && result != null;
    return _bannerFrame(
      context,
      key: ValueKey('export-toast-${task.id}'),
      ok: saved,
      message: saved
          ? ExportMessages.savedToast(result.fileName, result.location)
          : ExportMessages.failedToast(task.title),
      action: saved
          ? TextButton(
              key: const ValueKey('export-toast-open'),
              onPressed: () => _openExportFolder(task),
              style: _actionStyle,
              child: const Text(ExportMessages.openFolder),
            )
          : null,
    );
  }

  static final ButtonStyle _actionStyle = TextButton.styleFrom(
    foregroundColor: Colors.white,
    minimumSize: const Size(48, 48),
    textStyle: const TextStyle(fontWeight: FontWeight.w700),
  );

  Widget _bannerFrame(
    BuildContext context, {
    required Key key,
    required bool ok,
    required String message,
    required Widget? action,
  }) {
    final textTheme = Theme.of(context).textTheme;
    return Semantics(
      key: key,
      container: true,
      liveRegion: true,
      child: Material(
        color: AppTheme.sheetText,
        elevation: _elevation,
        borderRadius: BorderRadius.circular(_radius),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 4, 4),
          child: Row(
            children: [
              Icon(
                ok ? Icons.check_circle_rounded : Icons.error_rounded,
                color: Colors.white,
                size: 20,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  message,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: textTheme.bodyMedium?.copyWith(color: Colors.white),
                ),
              ),
              ?action,
              Semantics(
                button: true,
                label: ScanStatusMessages.dismissToast,
                excludeSemantics: true,
                child: InkResponse(
                  key: const ValueKey('scan-toast-close'),
                  onTap: _hide,
                  radius: 24,
                  child: const SizedBox.square(
                    dimension: 48,
                    child: Icon(
                      Icons.close_rounded,
                      color: Colors.white,
                      size: 20,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Keeps the app navigator's route stack, for [ScanToastHost] to see which
/// screen is under any popup. Register it in `navigatorObservers`.
class ScanRouteStack extends NavigatorObserver {
  final List<Route<dynamic>> _stack = [];

  /// The topmost route that isn't a popup (dialog, bottom sheet, menu).
  Route<dynamic>? get topScreen {
    for (final route in _stack.reversed) {
      if (route is! PopupRoute) return route;
    }
    return null;
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _stack.add(route);

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _stack.remove(route);

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _stack.remove(route);

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    final index = oldRoute == null ? -1 : _stack.indexOf(oldRoute);
    if (newRoute == null) {
      if (index >= 0) _stack.removeAt(index);
    } else if (index >= 0) {
      _stack[index] = newRoute;
    } else {
      _stack.add(newRoute);
    }
  }
}
