import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/export_service.dart';

/// Where an export is (user decision 2026-10-21: exports run in the
/// background and report in the in-app notifications).
enum ExportTaskStatus { running, saved, failed, cancelled }

/// One export, as the bell, the toast and the Export sheet see it.
@immutable
class ExportTask {
  const ExportTask({
    required this.id,
    required this.scoreId,
    required this.title,
    required this.treeUri,
    required this.startedAt,
    this.status = ExportTaskStatus.running,
    this.progress = 0,
    this.cancelling = false,
    this.result,
    this.failure,
    this.read = false,
    this.dismissed = false,
  });

  final int id;
  final int scoreId;
  final String title;

  /// The folder picked for it, so Retry and "Open folder" reuse it.
  final String treeUri;
  final DateTime startedAt;
  final ExportTaskStatus status;

  /// The whole export's 0..1 ([ExportProgress]).
  final double progress;

  /// The X was pressed and the export is stopping.
  final bool cancelling;

  /// Set once [status] is saved.
  final ExportResult? result;

  /// Set once [status] is failed or cancelled ([Cancelled] for the
  /// latter, which says whether part of the file was left).
  final ExportFailure? failure;

  /// Seen by the user: in the sheet that showed it, or marked read in the
  /// bell. Only finished tasks count towards the badge.
  final bool read;
  final bool dismissed;

  bool get isRunning => status == ExportTaskStatus.running;
  bool get isFinished => !isRunning;

  ExportTask copyWith({
    ExportTaskStatus? status,
    double? progress,
    bool? cancelling,
    ExportResult? result,
    ExportFailure? failure,
    bool? read,
    bool? dismissed,
  }) => ExportTask(
    id: id,
    scoreId: scoreId,
    title: title,
    treeUri: treeUri,
    startedAt: startedAt,
    status: status ?? this.status,
    progress: progress ?? this.progress,
    cancelling: cancelling ?? this.cancelling,
    result: result ?? this.result,
    failure: failure ?? this.failure,
    read: read ?? this.read,
    dismissed: dismissed ?? this.dismissed,
  );
}

/// The work of one export, given its Cancel and progress: everything it
/// needs from Playback must already be captured, because Playback may be
/// gone by the time it runs to the end.
typedef ExportRun = Future<ExportResult> Function(
  ExportCancelToken cancel,
  ValueChanged<double> onProgress,
);

/// Thrown by [ExportJobsController.start] while another export runs: one
/// at a time per app (user decision 2026-10-21).
class ExportAlreadyRunning implements Exception {
  const ExportAlreadyRunning(this.running);

  final ExportTask running;
}

/// App-level, not autoDispose and not tied to the sheet or Playback, like
/// [processingJobsProvider]: an export keeps going when the sheet is
/// closed or the user leaves Playback. It is not kept on the device; an
/// export does not outlive the app process.
///
/// Newest first. A system notification or foreground service can be added
/// later by listening to this provider (as the toast does): nothing here
/// knows about widgets.
final exportJobsProvider =
    NotifierProvider<ExportJobsController, List<ExportTask>>(
      ExportJobsController.new,
    );

/// Tests override it to pin "now".
final exportClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

class ExportJobsController extends Notifier<List<ExportTask>> {
  /// Finished tasks kept for the bell; older ones drop off.
  static const int historyLimit = 5;

  ExportCancelToken? _cancel;
  int _nextId = 1;
  final Set<int> _sheetsOpen = {};

  /// Bumped by [cancelAndForgetAll], so an export from the session that
  /// ended can never put its task back when it finishes.
  int _generation = 0;

  @override
  List<ExportTask> build() {
    ref.onDispose(() => _cancel?.cancel());
    return const [];
  }

  ExportTask? get running {
    for (final task in state) {
      if (task.isRunning) return task;
    }
    return null;
  }

  /// Starts [run] as a tracked export and returns it, running, at once;
  /// `done` completes with the finished task (never with an error: the
  /// task says what happened). Throws [ExportAlreadyRunning] if one is
  /// going.
  ({ExportTask task, Future<ExportTask> done}) start({
    required int scoreId,
    required String title,
    required String treeUri,
    required ExportRun run,
  }) {
    if (running case final busy?) throw ExportAlreadyRunning(busy);
    final token = ExportCancelToken();
    _cancel = token;
    final task = ExportTask(
      id: _nextId++,
      scoreId: scoreId,
      title: title,
      treeUri: treeUri,
      startedAt: ref.read(exportClockProvider)(),
    );
    _put(task);
    return (task: task, done: _run(task.id, token, run));
  }

  Future<ExportTask> _run(
    int id,
    ExportCancelToken token,
    ExportRun run,
  ) async {
    final generation = _generation;
    // Read before the run: after [cancelAndForgetAll] the task is gone
    // from the state, but `done` must still complete with something.
    final started = _find(id)!;
    ExportTask current() => _find(id) ?? started;
    ExportTask finished;
    try {
      final result = await run(token, (fraction) {
        if (generation != _generation) return;
        final task = _find(id);
        if (task == null || !task.isRunning) return;
        _put(task.copyWith(progress: fraction));
      });
      finished = current().copyWith(
        status: ExportTaskStatus.saved,
        progress: 1,
        result: result,
      );
    } on Cancelled catch (cancel) {
      finished = current().copyWith(
        status: ExportTaskStatus.cancelled,
        failure: cancel,
      );
    } on ExportFailure catch (failure) {
      // runExport already maps errors after a Cancel to Cancelled (L9);
      // checked again so the task can't say "failed" after the X.
      finished = current().copyWith(
        status: token.isCancelled
            ? ExportTaskStatus.cancelled
            : ExportTaskStatus.failed,
        failure: token.isCancelled ? const Cancelled() : failure,
      );
    } on Object catch (e, stack) {
      // runExport maps everything to ExportFailure; this is a backstop so
      // a task can never be left "running" forever.
      debugPrint('Export: unexpected error in background export: $e');
      debugPrint('$stack');
      finished = current().copyWith(
        status: token.isCancelled
            ? ExportTaskStatus.cancelled
            : ExportTaskStatus.failed,
        failure: token.isCancelled
            ? const Cancelled()
            : const GenerationFailed(),
      );
    } finally {
      if (identical(_cancel, token)) _cancel = null;
    }
    // The session it belonged to has ended: not shown to the next one.
    if (generation != _generation) return finished;
    // Shown where it happened: no badge for what the open sheet showed.
    // The user's own Cancel is never news either (L2).
    if (_sheetsOpen.contains(finished.scoreId) ||
        finished.status == ExportTaskStatus.cancelled) {
      finished = finished.copyWith(read: true);
    }
    _put(finished);
    _prune();
    return finished;
  }

  /// Logout or a new login (H1): stops the running export and forgets
  /// every task, so nothing of one account's exports reaches the next.
  /// The caller also stops the native side ([ExportService.stopAll]).
  void cancelAndForgetAll() {
    _generation++;
    _cancel?.cancel();
    _cancel = null;
    _sheetsOpen.clear();
    state = const [];
  }

  /// The X, in the sheet (or, later, a notification action).
  void cancel() {
    final task = running;
    final token = _cancel;
    if (task == null || token == null || task.cancelling) return;
    _put(task.copyWith(cancelling: true));
    token.cancel();
  }

  /// The Export sheet for [scoreId] is open: its result is shown there,
  /// not as a toast or an unread bell row.
  void sheetOpened(int scoreId) => _sheetsOpen.add(scoreId);
  void sheetClosed(int scoreId) => _sheetsOpen.remove(scoreId);
  bool isSheetOpen(int scoreId) => _sheetsOpen.contains(scoreId);

  void markRead(int id) {
    final task = _find(id);
    if (task == null || task.read || !task.isFinished) return;
    _put(task.copyWith(read: true));
  }

  void markAllRead() {
    state = [
      for (final task in state)
        task.isFinished && !task.read ? task.copyWith(read: true) : task,
    ];
  }

  /// Swiped away in the bell; a running export can't be.
  void dismiss(int id) {
    final task = _find(id);
    if (task == null || task.isRunning) return;
    state = [
      for (final t in state)
        if (t.id != id) t,
    ];
  }

  ExportTask? _find(int id) {
    for (final task in state) {
      if (task.id == id) return task;
    }
    return null;
  }

  void _put(ExportTask task) {
    final rest = [
      for (final t in state)
        if (t.id != task.id) t,
    ];
    state = [task, ...rest]..sort((a, b) => b.id.compareTo(a.id));
  }

  void _prune() {
    var finished = 0;
    state = [
      for (final task in state)
        if (task.isRunning || ++finished <= historyLimit) task,
    ];
  }
}

/// The running export for [scoreId], if the one export going is for it.
ExportTask? runningExportFor(List<ExportTask> tasks, int scoreId) {
  for (final task in tasks) {
    if (task.isRunning && task.scoreId == scoreId) return task;
  }
  return null;
}

/// The bell's export rows: everything not swiped away, newest first.
List<ExportTask> exportNotifications(List<ExportTask> tasks) => [
  for (final task in tasks)
    if (!task.dismissed) task,
];

int unreadExportCount(List<ExportTask> tasks) =>
    tasks.where((t) => t.isFinished && !t.read && !t.dismissed).length;

bool anyExportRunning(List<ExportTask> tasks) => tasks.any((t) => t.isRunning);
