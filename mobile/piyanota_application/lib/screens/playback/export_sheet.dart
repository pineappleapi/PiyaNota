import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/export_selection.dart';
import '../../models/voice_part.dart';
import '../../services/export_service.dart';
import '../../state/export_jobs.dart';
import '../../state/export_providers.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/notification_ask.dart';
import '../../widgets/primary_pill_button.dart';
import '../auth/widgets/auth_error_banner.dart';
import 'export_messages.dart';
import 'mixer_sheet.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// What the sheet pops with after a save: the file, and the folder it went
/// to so the success dialog can open it.
typedef ExportSaved = ({ExportResult result, String treeUri});

/// Opens Export Audio over Playback (PIYA-211) and, after a save seen in
/// the sheet, the success dialog (AC16). The sheet can be closed at any
/// time, also mid-export (user decision 2026-10-21, withdrawing AC12's
/// hold): the export goes on in [exportJobsProvider] and reports in the
/// bell and a banner instead.
Future<void> openExportAudio(
  BuildContext context,
  WidgetRef ref, {
  required int scoreId,
  required String title,
}) async {
  final saved = await showPlaybackSheet<ExportSaved>(
    context,
    (_) => ExportAudioSheet(scoreId: scoreId, title: title),
  );
  if (saved == null || !context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (_) => ExportSuccessDialog(
      saved: saved,
      service: ref.read(exportServiceProvider),
    ),
  );
}

/// Export Audio (PIYA-211, references/PIYA211_ExportAudioModal_UI_1.png):
/// tick voices (and the click), then Download Audio makes one MP3 of them,
/// mixed as Playback plays them, in a folder the user picks.
class ExportAudioSheet extends ConsumerStatefulWidget {
  const ExportAudioSheet({
    super.key,
    required this.scoreId,
    required this.title,
  });

  final int scoreId;

  /// The score title, for the file name (AC14).
  final String title;

  @override
  ConsumerState<ExportAudioSheet> createState() => _ExportAudioSheetState();
}

class _ExportAudioSheetState extends ConsumerState<ExportAudioSheet> {
  // Opens on what Playback lets be heard (user decision 2026-10-21); the
  // ticks here are never written back to the Mixer or the chips.
  late ExportSelection _selection = initialExportSelection(
    ref.read(playbackControllerProvider(widget.scoreId)),
  );

  /// Read once: [dispose] can't use ref.
  late final ExportJobsController _jobs = ref.read(exportJobsProvider.notifier);

  /// The folder picker is open.
  bool _picking = false;

  /// The export this sheet shows: started here, or already running for
  /// this score when the sheet was reopened. Its result is shown here when
  /// it finishes while the sheet is open.
  int? _taskId;
  ExportFailure? _failure;

  /// The last export was cancelled; says so calmly, nothing to retry.
  bool _cancelled = false;

  /// That cancel left part of the file in the folder (L8).
  bool _partialLeft = false;

  /// The last folder picked was not on the phone; shown while the picker
  /// is reopened, and after, if that pick is cancelled too.
  bool _notLocal = false;

  /// Download was tapped while another score's export ran.
  bool _blockedByOther = false;

  /// The last failure was every ticked voice failing before the file was
  /// made, which Retry cannot fix.
  bool _nothingLeft = false;

  /// The folder of the last attempt, so Retry after a dropped connection
  /// or a failed encode does not ask for it again.
  String? _treeUri;

  static const double _pillDisabledOpacity = 0.38;
  static const double _barHeight = 6;
  static const TextStyle _buttonLabel = TextStyle(
    // Large text: the sampled gradient only clears the 3:1 floor (see
    // AppTheme.exportDownloadGradient).
    fontSize: 18,
    fontWeight: FontWeight.w700,
  );

  @override
  void initState() {
    super.initState();
    _jobs.sheetOpened(widget.scoreId);
    // Reopened while this score's export runs: show its live progress
    // and the X.
    final running = runningExportFor(
      ref.read(exportJobsProvider),
      widget.scoreId,
    );
    if (running != null) {
      _taskId = running.id;
      _treeUri = running.treeUri;
    }
  }

  @override
  void dispose() {
    _jobs.sheetClosed(widget.scoreId);
    super.dispose();
  }

  ExportTask? _task(List<ExportTask> tasks) {
    final id = _taskId;
    if (id == null) return null;
    for (final task in tasks) {
      if (task.id == id) return task;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    closeSheetWhenNotReady(context, ref, widget.scoreId);
    ref.listen(exportJobsProvider, _onTasksChanged);
    final state = ref.watch(playbackControllerProvider(widget.scoreId));
    final tasks = ref.watch(exportJobsProvider);
    final task = _task(tasks);
    final exporting = task != null && task.isRunning;
    final busy = _picking || exporting;
    final other = _jobs.running;
    final otherTitle = other != null && other.scoreId != widget.scoreId
        ? other.title
        : null;
    // A voice can fail while the sheet is open: follow Playback live so it
    // is unticked and disabled here too. Assigned without setState because
    // this build is already applying it.
    _selection = exportableSelection(state, _selection);
    final rows = <Widget>[];
    void divider() =>
        rows.add(const Divider(height: 1, color: AppTheme.sheetDivider));

    for (final voice in VoicePart.values) {
      final usable = _selection.available.contains(voice);
      final ticked = _selection.voices.contains(voice);
      rows.add(
        _ExportRow(
          key: ValueKey('export-row-${voice.name}'),
          label: SheetPill(
            label: voice.label,
            color: VoiceMixerSheet.pillColors[voice]!,
          ),
          enabled: usable,
          value: ticked,
          semanticsLabel: ExportMessages.voiceBox(voice),
          onChanged: busy
              ? null
              : (_) => _update(_selection.toggleVoice(voice)),
        ),
      );
      if (!usable) {
        rows.add(SheetNote(ExportMessages.voiceUnavailable(voice)));
      }
      divider();
    }

    rows.add(
      _ExportRow(
        key: const ValueKey('export-row-all'),
        label: const SheetPill(
          label: ExportMessages.allVoices,
          color: AppTheme.exportAllVoicesPill,
        ),
        enabled: _selection.available.isNotEmpty,
        value: _selection.allVoices,
        semanticsLabel: ExportMessages.allVoicesBox,
        onChanged: busy ? null : (_) => _update(_selection.toggleAll()),
      ),
    );
    divider();

    // Review Focus 5: no tempo, no bars to click on, so no click.
    final clickUsable = !state.clickNeedsTempo;
    rows.add(
      _ExportRow(
        key: const ValueKey('export-row-click'),
        label: Text(
          ExportMessages.withClick,
          style: Theme.of(context).textTheme.bodyMedium
              ?.copyWith(color: AppTheme.sheetText),
        ),
        enabled: clickUsable,
        value: clickUsable && _selection.withClick,
        semanticsLabel: ExportMessages.clickBox,
        onChanged: busy ? null : (_) => _update(_selection.toggleClick()),
      ),
    );
    if (!clickUsable) {
      rows.add(const SheetNote(PlaybackMessages.metronomeNeedsTempo));
    }

    final failure = _failure;
    return SheetFrame(
      key: const ValueKey('export-sheet'),
      title: ExportMessages.title,
      children: [
        ...rows,
        const SizedBox(height: 24),
        if (_notLocal)
          const SheetNote(
            ExportMessages.notLocalFolder,
            key: ValueKey('export-not-local'),
          ),
        if (_blockedByOther && otherTitle != null)
          SheetNote(
            ExportMessages.alreadyExporting(otherTitle),
            key: const ValueKey('export-busy-elsewhere'),
          ),
        if (_cancelled && !busy)
          SheetNote(
            _partialLeft
                ? ExportMessages.cancelledPartial
                : ExportMessages.cancelled,
            key: const ValueKey('export-cancelled'),
          ),
        if (failure != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(0, 0, 8, 16),
            child: AuthErrorBanner(
              key: const ValueKey('export-error'),
              message: _nothingLeft
                  ? ExportMessages.nothingToExport
                  : ExportMessages.failureMessage(failure),
              // Nothing left to retry once every ticked voice failed.
              actionLabel: _nothingLeft ? null : ExportMessages.retry,
              onAction: busy || !_selection.canDownload ? null : _retry,
            ),
          ),
        Padding(
          padding: const EdgeInsets.only(right: 8),
          child: PrimaryPillButton(
            key: const ValueKey('export-download'),
            label: ExportMessages.download,
            loadingLabel: ExportMessages.preparing,
            gradient: AppTheme.exportDownloadGradient,
            labelStyle: _buttonLabel,
            isLoading: busy,
            // AC8: nothing to export until a voice is ticked.
            onPressed: _selection.canDownload ? _download : null,
          ),
        ),
        if (exporting) ..._progressRows(task),
      ],
    );
  }

  /// The bar, its percentage and the X, under Download while the file is
  /// made (user decision 2026-10-21: determinate end to end, an X icon for
  /// Cancel).
  List<Widget> _progressRows(ExportTask task) {
    final percent = ExportMessages.percent(task.progress);
    return [
      const SizedBox(height: 8),
      Padding(
        padding: const EdgeInsets.only(left: 10),
        child: Row(
          children: [
            Expanded(
              child: LinearProgressIndicator(
                key: const ValueKey('export-progress'),
                value: task.progress,
                minHeight: _barHeight,
                color: AppTheme.playbackNavy,
                backgroundColor: AppTheme.sheetDivider,
                borderRadius: BorderRadius.circular(_barHeight / 2),
                semanticsLabel: ExportMessages.progressLabel,
                semanticsValue: percent,
              ),
            ),
            const SizedBox(width: 8),
            ExcludeSemantics(
              // The bar already speaks the same value.
              child: Text(
                task.cancelling ? ExportMessages.cancelling : percent,
                key: const ValueKey('export-percent'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppTheme.sheetText,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ),
            IconButton(
              key: const ValueKey('export-cancel'),
              onPressed: task.cancelling ? null : _jobs.cancel,
              tooltip: ExportMessages.cancelExport,
              icon: const Icon(Icons.close),
              color: AppTheme.playbackNavy,
              constraints: const BoxConstraints(
                minWidth: kMinInteractiveDimension,
                minHeight: kMinInteractiveDimension,
              ),
            ),
          ],
        ),
      ),
    ];
  }

  /// This sheet's export finished while it is open: show the result here
  /// (the tracker has already marked it read, so the bell has no badge
  /// for it and no banner shows).
  void _onTasksChanged(List<ExportTask>? previous, List<ExportTask> next) {
    final before = previous == null ? null : _task(previous);
    final task = _task(next);
    if (task == null || !task.isFinished) return;
    if (before != null && before.isFinished) return;
    _taskId = null;
    switch (task.status) {
      case ExportTaskStatus.saved:
        // Let the sheet close before the dialog opens (AC16).
        Navigator.of(context)
            .pop<ExportSaved>((result: task.result!, treeUri: task.treeUri));
      case ExportTaskStatus.cancelled:
        final cancel = task.failure;
        setState(() {
          _cancelled = true;
          _partialLeft = cancel is Cancelled && cancel.partialFileLeft;
        });
      case ExportTaskStatus.failed:
        final failure = task.failure ?? const GenerationFailed();
        setState(() {
          _failure = failure;
          _nothingLeft =
              failure is GenerationFailed &&
              !exportableSelection(
                ref.read(playbackControllerProvider(widget.scoreId)),
                _selection,
              ).canDownload;
        });
      case ExportTaskStatus.running:
        break;
    }
  }

  void _update(ExportSelection next) => setState(() {
    _selection = next;
    // L-c: "nothing to export" was about the old ticks; a new tick makes
    // it, and its banner, stale.
    if (_nothingLeft) {
      _nothingLeft = false;
      _failure = null;
    }
  });

  /// Permission errors mean that folder is the problem, so Retry asks for
  /// a folder again; anything else retries the same one.
  void _retry() {
    if (_failure is PermissionDenied) _treeUri = null;
    _download();
  }

  Future<void> _download() async {
    if (_picking || _taskId != null || !_selection.canDownload) return;
    // One export at a time per app: say so before asking for a folder.
    if (_jobs.running != null) {
      setState(() => _blockedByOther = true);
      return;
    }
    final service = ref.read(exportServiceProvider);
    final provider = playbackControllerProvider(widget.scoreId);
    setState(() {
      _picking = true;
      _failure = null;
      _nothingLeft = false;
      _cancelled = false;
      _partialLeft = false;
      _blockedByOther = false;
    });
    String? treeUri;
    try {
      if (_treeUri == null) await _askForNotifications();
      if (!mounted) return;
      treeUri = _treeUri ?? await _pickLocalFolder(service);
    } on ExportFailure catch (failure) {
      if (mounted) setState(() => _failure = failure);
    } finally {
      if (mounted) setState(() => _picking = false);
    }
    // AC11: picker cancelled, back to the sheet with the ticks kept. A
    // sheet closed while the picker was open starts nothing.
    if (treeUri == null || !mounted) return;
    _treeUri = treeUri;
    // Everything the export needs from Playback is read now: it goes on
    // after the sheet and Playback close (user decision 2026-10-21).
    final controller = ref.read(provider.notifier);
    final state = ref.read(provider);
    final writeClick = controller.exportClickWriter();
    final selection = _selection;
    final title = widget.title;
    final folder = treeUri;
    try {
      final started = _jobs.start(
        scoreId: widget.scoreId,
        title: title,
        treeUri: folder,
        run: (cancel, onProgress) => runExport(
          service: service,
          writeClick: writeClick,
          state: state,
          selection: selection,
          title: title,
          treeUri: folder,
          notice: ExportMessages.notice(title),
          cancel: cancel,
          onProgress: onProgress,
        ),
      );
      setState(() {
        _taskId = started.task.id;
        _notLocal = false;
      });
    } on ExportAlreadyRunning {
      // Started elsewhere while the picker was open.
      setState(() => _blockedByOther = true);
    }
  }

  /// Android 13+ only shows the export's notification if allowed: asked
  /// once, before the first folder pick, in plain words (user decision
  /// 2026-10-22). Either answer goes on to the export.
  Future<void> _askForNotifications() => askForNotificationsOnce(
    context,
    ref.read(notificationPermissionProvider),
    title: ExportMessages.notificationsTitle,
    body: ExportMessages.notificationsBody,
    later: ExportMessages.notificationsLater,
    allow: ExportMessages.notificationsAllow,
  );

  /// The picker, again and again until the folder is on this phone or the
  /// user backs out (user decision 2026-10-21): a Drive or app folder
  /// shows "Pick a folder on this phone." and reopens it straight away.
  Future<String?> _pickLocalFolder(ExportService service) async {
    while (true) {
      // Folders an export row or a Retry may still use keep their
      // permission; any other kept from earlier picks is given back.
      final keep = {
        for (final task in ref.read(exportJobsProvider)) task.treeUri,
        ?_treeUri,
      };
      try {
        return await service.pickFolder(keep: keep);
      } on NotLocalFolder {
        if (!mounted) return null;
        setState(() => _notLocal = true);
      }
    }
  }
}

/// A row of the mockup: the label on the left, the grey checkbox on the
/// right. The pill is a picture of the name; the checkbox carries the
/// spoken label and checked state (AC21).
class _ExportRow extends StatelessWidget {
  const _ExportRow({
    super.key,
    required this.label,
    required this.enabled,
    required this.value,
    required this.semanticsLabel,
    required this.onChanged,
  });

  final Widget label;
  final bool enabled;
  final bool value;
  final String semanticsLabel;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 10),
    child: Row(
      children: [
        Expanded(
          child: ExcludeSemantics(
            child: Opacity(
              opacity: enabled
                  ? 1
                  : _ExportAudioSheetState._pillDisabledOpacity,
              child: Align(alignment: Alignment.centerLeft, child: label),
            ),
          ),
        ),
        SheetCheckbox(
          value: value,
          label: semanticsLabel,
          onChanged: enabled ? onChanged : null,
        ),
      ],
    ),
  );
}

/// "Download Successful!" (AC16, references/..._UI_2.png): the saved name
/// and folder, "Open folder" (hidden once the phone says no app can open
/// it) and OK.
class ExportSuccessDialog extends StatefulWidget {
  const ExportSuccessDialog({
    super.key,
    required this.saved,
    required this.service,
  });

  final ExportSaved saved;
  final ExportService service;

  @override
  State<ExportSuccessDialog> createState() => _ExportSuccessDialogState();
}

class _ExportSuccessDialogState extends State<ExportSuccessDialog> {
  bool _canOpen = true;

  static const double _radius = 20;
  static const double _okRadius = 10;
  static const TextStyle _okLabel = TextStyle(
    // Large text: the sampled fill only clears 3:1 (AppTheme.exportOkFill).
    fontSize: 18,
    fontWeight: FontWeight.w700,
  );

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final result = widget.saved.result;
    return AlertDialog(
      key: const ValueKey('export-success'),
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_radius),
      ),
      title: Text(
        ExportMessages.successTitle,
        style: textTheme.headlineSmall?.copyWith(
          fontWeight: FontWeight.w700,
          color: AppTheme.sheetText,
        ),
      ),
      content: Text(
        '${ExportMessages.savedAs(result.fileName)}\n'
        '${ExportMessages.savedIn(result.location)}',
        style: textTheme.bodyMedium?.copyWith(color: AppTheme.sheetText),
      ),
      actions: [
        if (_canOpen)
          TextButton(
            key: const ValueKey('export-open-folder'),
            onPressed: _openFolder,
            style: TextButton.styleFrom(
              foregroundColor: AppTheme.playbackNavy,
              minimumSize: const Size(64, kMinInteractiveDimension),
            ),
            child: const Text(ExportMessages.openFolder),
          ),
        FilledButton(
          key: const ValueKey('export-ok'),
          onPressed: () => Navigator.of(context).pop(),
          style: FilledButton.styleFrom(
            backgroundColor: AppTheme.exportOkFill,
            foregroundColor: Colors.white,
            minimumSize: const Size(64, kMinInteractiveDimension),
            textStyle: _okLabel,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(_okRadius),
            ),
          ),
          child: const Text(ExportMessages.ok),
        ),
      ],
    );
  }

  Future<void> _openFolder() async {
    final opened = await widget.service.openFolder(widget.saved.treeUri);
    if (!opened && mounted) setState(() => _canOpen = false);
  }
}
