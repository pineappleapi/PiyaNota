import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/library_entry.dart';
import '../../state/processing_providers.dart';
import '../../theme/app_theme.dart';
import '../playback/sheet_parts.dart';
import 'scan_navigation.dart';
import 'scan_status_messages.dart';

/// PIYA-218 AC5: the library header's notification bell.
///
/// Plain when nothing is going on, a thin spinning ring while any scan
/// runs (AC9), and a red count badge for completed and failed scans not
/// yet seen. Running scans never add to the badge. Every state is read
/// from [processingJobsProvider], the same source as the card and
/// Processing (AC1).
///
/// No reference mockup draws the bell, so every colour is an existing
/// token: white like the header's other glyphs, [AppTheme.errorRed] for
/// the badge (the app's one error/attention red).
class ScanBell extends ConsumerWidget {
  const ScanBell({super.key});

  static const double size = 48;
  static const double _iconSize = 26;
  static const double _ringSize = 36;
  static const double _ringStroke = 2;
  // Reduce motion: the ring stays, drawn still, three-quarters round.
  static const double _staticRingValue = 0.75;
  static const double _badgeMinSize = 18;
  static const double _badgeFontSize = 11;
  static const double _badgeInset = 4;
  static const double _badgeBorder = 1.5;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(processingJobsProvider.select(unreadScanCount));
    final active = ref.watch(processingJobsProvider.select(anyScanRunning));
    final reduceMotion = MediaQuery.disableAnimationsOf(context);

    return Semantics(
      button: true,
      label: ScanStatusMessages.bellSemantics(unread: unread, active: active),
      excludeSemantics: true,
      onTap: () => showScanPanel(context),
      child: SizedBox.square(
        key: const ValueKey('scan-bell'),
        dimension: size,
        child: Stack(
          alignment: Alignment.center,
          clipBehavior: Clip.none,
          children: [
            if (active)
              SizedBox.square(
                key: const ValueKey('scan-bell-ring'),
                dimension: _ringSize,
                child: CircularProgressIndicator(
                  value: reduceMotion ? _staticRingValue : null,
                  strokeWidth: _ringStroke,
                  color: Colors.white,
                ),
              ),
            IconButton(
              tooltip: ScanStatusMessages.bellIdle,
              onPressed: () => showScanPanel(context),
              iconSize: _iconSize,
              color: Colors.white,
              icon: Icon(
                active || unread > 0
                    ? Icons.notifications_rounded
                    : Icons.notifications_none_rounded,
              ),
            ),
            if (unread > 0)
              Positioned(
                top: _badgeInset,
                right: _badgeInset,
                child: IgnorePointer(
                  child: DecoratedBox(
                    key: const ValueKey('scan-bell-badge'),
                    decoration: BoxDecoration(
                      color: AppTheme.errorRed,
                      borderRadius: BorderRadius.circular(_badgeMinSize / 2),
                      border: Border.all(
                        color: Colors.white,
                        width: _badgeBorder,
                      ),
                    ),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(
                        minWidth: _badgeMinSize,
                        minHeight: _badgeMinSize,
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: Center(
                          widthFactor: 1,
                          heightFactor: 1,
                          child: MediaQuery.withNoTextScaling(
                            child: Text(
                              ScanStatusMessages.badge(unread),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: _badgeFontSize,
                                fontWeight: FontWeight.w700,
                                height: 1,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// AC6: the bell's panel, a scrollable bottom sheet in the Playback
/// sheets' frame.
Future<void> showScanPanel(BuildContext context) =>
    showPlaybackSheet(context, (_) => const ScanPanel());

/// The rows themselves: newest first, one per score, updated in place as
/// the tracker changes (AC6).
class ScanPanel extends ConsumerWidget {
  const ScanPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final jobs = ref.watch(processingJobsProvider);
    final rows = scanNotifications(jobs);
    final unread = unreadScanCount(jobs);
    final now = ref.read(processingClockProvider)();
    final textTheme = Theme.of(context).textTheme;

    return SheetFrame(
      title: ScanStatusMessages.panelTitle,
      subtitle: ScanStatusMessages.panelSubtitle,
      children: [
        if (unread > 0)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              key: const ValueKey('scan-mark-all-read'),
              onPressed: () =>
                  ref.read(processingJobsProvider.notifier).markAllRead(),
              style: TextButton.styleFrom(
                foregroundColor: AppTheme.processingSecondary,
                minimumSize: const Size(48, 48),
              ),
              child: const Text(ScanStatusMessages.markAllRead),
            ),
          ),
        if (rows.isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 24, 10, 32),
            child: Text(
              ScanStatusMessages.empty,
              key: const ValueKey('scan-panel-empty'),
              textAlign: TextAlign.center,
              style: textTheme.bodyLarge?.copyWith(color: AppTheme.sheetSubtle),
            ),
          )
        else
          for (final job in rows)
            _ScanRow(
              key: ValueKey('scan-row-${job.jobId}'),
              job: job,
              now: now,
            ),
      ],
    );
  }
}

class _ScanRow extends ConsumerWidget {
  const _ScanRow({super.key, required this.job, required this.now});

  final TrackedJob job;
  final DateTime now;

  static const double _dotSize = 8;
  static const double _dotColumn = 18;
  static const double _barHeight = 4;
  static const double _maxPercent = 100;

  void _open(BuildContext context, WidgetRef ref) {
    final navigator = Navigator.of(context);
    // The sheet closes first, so Back from the opened screen returns to
    // the library, not to a stale panel. The row is still mounted while
    // the sheet animates out, so [ref] is usable for the push.
    navigator.pop();
    unawaited(openScanJob(navigator, ref, job));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final textTheme = Theme.of(context).textTheme;
    final title = job.title ?? untitledScoreLabel;
    final unread = job.isFinished && !job.read;
    final String suffix;
    final String? hint;
    switch (job.phase) {
      case TrackedPhase.complete:
        suffix = ScanStatusMessages.readyRow;
        final when = job.finishedAt;
        hint = when == null
            ? null
            : ScanStatusMessages.relativeTime(now.difference(when));
      case TrackedPhase.failed:
        suffix = ScanStatusMessages.failedRow;
        hint = ScanStatusMessages.failedRowHint;
      case _:
        suffix = ScanStatusMessages.processingRow;
        hint = job.phase == TrackedPhase.paused
            ? ScanStatusMessages.pausedRowHint
            : job.isStalled
            ? ScanStatusMessages.stalled
            : null;
    }

    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text.rich(
          TextSpan(
            children: [
              TextSpan(
                text: title,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              TextSpan(text: suffix),
            ],
          ),
          style: textTheme.bodyLarge?.copyWith(
            color: AppTheme.sheetText,
            fontWeight: unread ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
        if (job.isRunning) ...[
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: LinearProgressIndicator(
                  value: job.percent / _maxPercent,
                  minHeight: _barHeight,
                  color: AppTheme.processingSecondary,
                  backgroundColor: AppTheme.sheetDivider,
                  borderRadius: BorderRadius.circular(_barHeight / 2),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '${job.percent}%',
                style: textTheme.labelMedium?.copyWith(
                  color: AppTheme.sheetSubtle,
                ),
              ),
            ],
          ),
        ],
        if (hint != null) ...[
          const SizedBox(height: 2),
          Text(
            hint,
            style: textTheme.bodySmall?.copyWith(color: AppTheme.sheetSubtle),
          ),
        ],
        if (job.phase == TrackedPhase.paused)
          TextButton.icon(
            onPressed: () =>
                ref.read(processingJobsProvider.notifier).retry(job.jobId),
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.processingSecondary,
              minimumSize: const Size(48, 48),
              padding: EdgeInsets.zero,
            ),
            icon: const Icon(Icons.refresh_rounded),
            label: const Text(ScanStatusMessages.retry),
          ),
      ],
    );

    final row = Semantics(
      button: true,
      label: unread ? ScanStatusMessages.unread : null,
      child: InkWell(
        onTap: () => _open(context, ref),
        splashFactory: NoSplash.splashFactory,
        highlightColor: AppTheme.darken(Colors.white),
        child: Padding(
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
                          key: const ValueKey('scan-row-unread'),
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
        ),
      ),
    );

    final divided = DecoratedBox(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppTheme.sheetDivider)),
      ),
      child: row,
    );

    // AC6: running rows can't be swiped away.
    if (!job.isFinished) return divided;
    return Dismissible(
      key: ValueKey('scan-dismiss-${job.jobId}'),
      direction: DismissDirection.endToStart,
      onDismissed: (_) =>
          ref.read(processingJobsProvider.notifier).dismiss(job.jobId),
      background: const ColoredBox(
        color: AppTheme.sheetDivider,
        child: Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: EdgeInsets.only(right: 16),
            child: Icon(Icons.close_rounded, color: AppTheme.sheetClose),
          ),
        ),
      ),
      child: divided,
    );
  }
}
