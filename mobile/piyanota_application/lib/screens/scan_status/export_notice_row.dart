import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/export_jobs.dart';
import '../../state/export_providers.dart';
import '../../theme/app_theme.dart';
import '../playback/export_messages.dart';

/// One export in the bell's panel (user decision 2026-10-21), in the same
/// look as a scan row: "Exporting [title]… n%" with a bar while it runs,
/// then "Saved [file name] to [folder]" (tap opens the folder), or that it
/// failed or was cancelled. Finished rows swipe away; a running one can't.
class ExportNoticeRow extends ConsumerWidget {
  const ExportNoticeRow({super.key, required this.task});

  final ExportTask task;

  static const double _dotSize = 8;
  static const double _dotColumn = 18;
  static const double _barHeight = 4;

  void _tap(BuildContext context, WidgetRef ref) {
    ref.read(exportJobsProvider.notifier).markRead(task.id);
    if (task.status != ExportTaskStatus.saved) return;
    unawaited(ref.read(exportServiceProvider).openFolder(task.treeUri));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final textTheme = Theme.of(context).textTheme;
    final unread = task.isFinished && !task.read;
    final result = task.result;
    final String text;
    String? hint;
    switch (task.status) {
      case ExportTaskStatus.running:
        text = ExportMessages.exportingRow(task.title, task.progress);
      case ExportTaskStatus.saved:
        text = result == null
            ? ExportMessages.successTitle
            : ExportMessages.savedRow(result.fileName, result.location);
      case ExportTaskStatus.failed:
        text = ExportMessages.failedRow(task.title);
        final failure = task.failure;
        hint = failure == null
            ? ExportMessages.failedToastHint
            : ExportMessages.failureMessage(failure);
      case ExportTaskStatus.cancelled:
        text = ExportMessages.cancelledRow(task.title);
        final failure = task.failure;
        if (failure != null) hint = ExportMessages.failureMessage(failure);
    }

    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          text,
          key: ValueKey('export-notice-text-${task.id}'),
          style: textTheme.bodyLarge?.copyWith(
            color: AppTheme.sheetText,
            fontWeight: unread ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
        if (task.isRunning) ...[
          const SizedBox(height: 6),
          LinearProgressIndicator(
            value: task.progress,
            minHeight: _barHeight,
            color: AppTheme.processingSecondary,
            backgroundColor: AppTheme.sheetDivider,
            borderRadius: BorderRadius.circular(_barHeight / 2),
            semanticsLabel: ExportMessages.progressLabel,
            semanticsValue: ExportMessages.percent(task.progress),
          ),
        ],
        if (hint != null) ...[
          const SizedBox(height: 2),
          Text(
            hint,
            style: textTheme.bodySmall?.copyWith(color: AppTheme.sheetSubtle),
          ),
        ],
      ],
    );

    final content = Padding(
      padding: const EdgeInsets.fromLTRB(0, 12, 8, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: _dotColumn,
            child: unread
                ? Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Container(
                      key: const ValueKey('export-notice-unread'),
                      width: _dotSize,
                      height: _dotSize,
                      decoration: const BoxDecoration(
                        color: AppTheme.errorRed,
                        shape: BoxShape.circle,
                      ),
                    ),
                  )
                : null,
          ),
          Expanded(child: body),
        ],
      ),
    );

    // A running row has nothing to do on tap; the X is in the sheet.
    final row = task.isRunning
        ? content
        : Semantics(
            button: true,
            label: unread ? ExportMessages.unread : null,
            hint: task.status == ExportTaskStatus.saved
                ? ExportMessages.openFolder
                : null,
            child: InkWell(
              onTap: () => _tap(context, ref),
              splashFactory: NoSplash.splashFactory,
              highlightColor: AppTheme.darken(Colors.white),
              child: content,
            ),
          );

    final divided = DecoratedBox(
      key: ValueKey('export-notice-${task.id}'),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppTheme.sheetDivider)),
      ),
      child: row,
    );

    if (task.isRunning) return divided;
    return Dismissible(
      key: ValueKey('export-dismiss-${task.id}'),
      direction: DismissDirection.endToStart,
      onDismissed: (_) =>
          ref.read(exportJobsProvider.notifier).dismiss(task.id),
      background: const ColoredBox(
        color: AppTheme.sheetDivider,
        child: Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: EdgeInsets.only(right: 16),
            child: Icon(Icons.close_rounded, color: AppTheme.sheetSubtle),
          ),
        ),
      ),
      child: divided,
    );
  }
}
