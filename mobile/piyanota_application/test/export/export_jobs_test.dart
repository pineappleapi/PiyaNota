import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/export_service.dart';
import 'package:piyanota_application/state/export_jobs.dart';

import 'export_fakes.dart';

/// The app-level export tracker behind background export (user decision
/// 2026-10-21): one at a time, kept for the bell, read when seen.
void main() {
  late ProviderContainer container;
  ExportJobsController jobs() => container.read(exportJobsProvider.notifier);
  List<ExportTask> tasks() => container.read(exportJobsProvider);

  setUp(() => container = ProviderContainer());
  tearDown(() => container.dispose());

  /// A run the test finishes by hand, recording its Cancel and progress.
  ({
    ExportRun run,
    Completer<ExportResult> done,
    List<ExportCancelToken> cancels,
    List<void Function(double)> progress,
  })
  held() {
    final done = Completer<ExportResult>();
    final cancels = <ExportCancelToken>[];
    final progress = <void Function(double)>[];
    return (
      run: (cancel, onProgress) {
        cancels.add(cancel);
        progress.add(onProgress);
        return done.future;
      },
      done: done,
      cancels: cancels,
      progress: progress,
    );
  }

  ({ExportTask task, Future<ExportTask> done}) start(
    ExportRun run, {
    int scoreId = 1,
  }) => jobs().start(
    scoreId: scoreId,
    title: 'Score $scoreId',
    treeUri: kTreeUri,
    run: run,
  );

  test('starts running at 0 and follows progress', () async {
    final h = held();
    final started = start(h.run);
    expect(started.task.isRunning, isTrue);
    expect(tasks().single.progress, 0);
    expect(anyExportRunning(tasks()), isTrue);
    expect(runningExportFor(tasks(), 1)?.id, started.task.id);
    expect(runningExportFor(tasks(), 2), isNull);

    h.progress.single(0.25);
    expect(tasks().single.progress, 0.25);

    h.done.complete(kSaved);
    final finished = await started.done;
    expect(finished.status, ExportTaskStatus.saved);
    expect(finished.progress, 1);
    expect(finished.result, kSaved);
    expect(anyExportRunning(tasks()), isFalse);
    expect(unreadExportCount(tasks()), 1);
  });

  test('a failure is kept as failed with its reason', () async {
    final started = start((_, _) async => throw const StorageFull());
    final finished = await started.done;
    expect(finished.status, ExportTaskStatus.failed);
    expect(finished.failure, isA<StorageFull>());
  });

  test('an unexpected error still ends the task, as failed', () async {
    final started = start((_, _) async => throw StateError('boom'));
    final finished = await started.done;
    expect(finished.status, ExportTaskStatus.failed);
    expect(finished.failure, isA<GenerationFailed>());
  });

  test('cancel marks it cancelling, cancels the token, and an error after '
      'the X is reported as cancelled, not failed', () async {
    final h = held();
    final started = start(h.run);
    jobs().cancel();
    expect(tasks().single.cancelling, isTrue);
    expect(h.cancels.single.isCancelled, isTrue);

    h.done.completeError(const Interrupted());
    final finished = await started.done;
    expect(finished.status, ExportTaskStatus.cancelled);
    expect(finished.failure, isA<Cancelled>());
  });

  test('Cancelled keeps whether part of the file was left', () async {
    final started = start(
      (_, _) async => throw const Cancelled(partialFileLeft: true),
    );
    final finished = await started.done;
    expect(finished.status, ExportTaskStatus.cancelled);
    expect((finished.failure! as Cancelled).partialFileLeft, isTrue);
  });

  test('one at a time: a second start throws ExportAlreadyRunning', () async {
    final h = held();
    final first = start(h.run);
    expect(
      () => start((_, _) async => kSaved, scoreId: 2),
      throwsA(
        isA<ExportAlreadyRunning>().having(
          (e) => e.running.id,
          'running',
          first.task.id,
        ),
      ),
    );
    h.done.complete(kSaved);
    await first.done;
    final second = start((_, _) async => kSaved, scoreId: 2);
    expect((await second.done).status, ExportTaskStatus.saved);
  });

  test('finished while its sheet is open: already read', () async {
    jobs().sheetOpened(1);
    final finished = await start((_, _) async => kSaved).done;
    expect(finished.read, isTrue);
    expect(unreadExportCount(tasks()), 0);

    jobs().sheetClosed(1);
    expect(jobs().isSheetOpen(1), isFalse);
    final unseen = await start((_, _) async => kSaved).done;
    expect(unseen.read, isFalse);
  });

  test('newest first, markRead, markAllRead and dismiss', () async {
    final a = await start((_, _) async => kSaved).done;
    final b = await start((_, _) async => kSaved, scoreId: 2).done;
    expect(tasks().map((t) => t.id), [b.id, a.id]);
    expect(unreadExportCount(tasks()), 2);

    jobs().markRead(a.id);
    expect(unreadExportCount(tasks()), 1);
    jobs().markAllRead();
    expect(unreadExportCount(tasks()), 0);

    jobs().dismiss(b.id);
    expect(exportNotifications(tasks()).map((t) => t.id), [a.id]);
  });

  test('a running export cannot be dismissed or marked read', () async {
    final h = held();
    final started = start(h.run);
    jobs()
      ..dismiss(started.task.id)
      ..markRead(started.task.id);
    expect(tasks().single.isRunning, isTrue);
    expect(tasks().single.read, isFalse);
    h.done.complete(kSaved);
    await started.done;
  });

  test('keeps only the last historyLimit finished exports', () async {
    for (var i = 0; i < ExportJobsController.historyLimit + 2; i++) {
      await start((_, _) async => kSaved).done;
    }
    expect(tasks(), hasLength(ExportJobsController.historyLimit));
  });

  test('disposing the app cancels a running export', () {
    final h = held();
    start(h.run);
    container.dispose();
    expect(h.cancels.single.isCancelled, isTrue);
    container = ProviderContainer();
  });
}
