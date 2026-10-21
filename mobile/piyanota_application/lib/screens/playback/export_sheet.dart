import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/export_selection.dart';
import '../../models/voice_part.dart';
import '../../services/export_service.dart';
import '../../state/export_providers.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import '../auth/widgets/auth_error_banner.dart';
import 'export_messages.dart';
import 'mixer_sheet.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// What the sheet pops with after a save: the file, and the folder it went
/// to so the success dialog can open it.
typedef ExportSaved = ({ExportResult result, String treeUri});

/// Opens Export Audio over Playback (PIYA-211) and, after a save, the
/// success dialog (AC16). Drag-to-close is off: it would pop the sheet
/// mid-export, past the PopScope that holds it open (AC12).
Future<void> openExportAudio(
  BuildContext context,
  WidgetRef ref, {
  required int scoreId,
  required String title,
}) async {
  final saved = await showPlaybackSheet<ExportSaved>(
    context,
    (_) => ExportAudioSheet(scoreId: scoreId, title: title),
    enableDrag: false,
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
  bool _busy = false;
  ExportFailure? _failure;

  /// Set once a folder is picked: the file is being made, so the bar and
  /// Cancel show. Null between exports.
  ExportCancelToken? _cancel;

  /// The whole export's 0..1, download to save (user decision
  /// 2026-10-21); 0 until the first report.
  double _progress = 0;

  /// Cancel was pressed and the export is stopping.
  bool _cancelling = false;

  /// The last export was cancelled; says so calmly, nothing to retry.
  bool _cancelled = false;

  /// That cancel left part of the file in the folder (L8).
  bool _partialLeft = false;

  /// The last folder picked was not on the phone; shown while the picker
  /// is reopened, and after, if that pick is cancelled too.
  bool _notLocal = false;

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
  Widget build(BuildContext context) {
    closeSheetWhenNotReady(context, ref, widget.scoreId);
    final state = ref.watch(playbackControllerProvider(widget.scoreId));
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
          onChanged: _busy
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
        onChanged: _busy ? null : (_) => _update(_selection.toggleAll()),
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
        onChanged: _busy ? null : (_) => _update(_selection.toggleClick()),
      ),
    );
    if (!clickUsable) {
      rows.add(const SheetNote(PlaybackMessages.metronomeNeedsTempo));
    }

    final failure = _failure;
    return PopScope(
      // AC12: no X, back or scrim tap while the file is being made.
      canPop: !_busy,
      child: SheetFrame(
        key: const ValueKey('export-sheet'),
        title: ExportMessages.title,
        canClose: !_busy,
        children: [
          ...rows,
          const SizedBox(height: 24),
          if (_notLocal)
            const SheetNote(
              ExportMessages.notLocalFolder,
              key: ValueKey('export-not-local'),
            ),
          if (_cancelled && !_busy)
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
                    : _messageFor(failure),
                // Nothing left to retry once every ticked voice failed.
                actionLabel: _nothingLeft ? null : ExportMessages.retry,
                onAction: _busy || !_selection.canDownload ? null : _retry,
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
              isLoading: _busy,
              // AC8: nothing to export until a voice is ticked.
              onPressed: _selection.canDownload ? _download : null,
            ),
          ),
          if (_busy && _cancel != null) ..._progressRows(),
        ],
      ),
    );
  }

  /// The bar, its percentage and the X, under Download while the file is
  /// made (user decision 2026-10-21: determinate end to end, an X icon for
  /// Cancel).
  List<Widget> _progressRows() {
    final percent = ExportMessages.percent(_progress);
    return [
      const SizedBox(height: 8),
      Padding(
        padding: const EdgeInsets.only(left: 10),
        child: Row(
          children: [
            Expanded(
              child: LinearProgressIndicator(
                key: const ValueKey('export-progress'),
                value: _progress,
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
                _cancelling ? ExportMessages.cancelling : percent,
                key: const ValueKey('export-percent'),
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppTheme.sheetText,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ),
            IconButton(
              key: const ValueKey('export-cancel'),
              onPressed: _cancelling ? null : _cancelExport,
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

  void _cancelExport() {
    final token = _cancel;
    if (token == null || _cancelling) return;
    setState(() => _cancelling = true);
    token.cancel();
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
    if (_busy || !_selection.canDownload) return;
    final service = ref.read(exportServiceProvider);
    final provider = playbackControllerProvider(widget.scoreId);
    setState(() {
      _busy = true;
      _failure = null;
      _nothingLeft = false;
      _cancelled = false;
      _partialLeft = false;
    });
    final selection = _selection;
    var saved = false;
    try {
      final treeUri = _treeUri ?? await _pickLocalFolder(service);
      // AC11: picker cancelled, back to the sheet with the ticks kept.
      if (treeUri == null) return;
      _treeUri = treeUri;
      final token = ExportCancelToken();
      if (mounted) {
        setState(() {
          _cancel = token;
          _progress = 0;
          _cancelling = false;
          _notLocal = false;
        });
      }
      final result = await runExport(
        service: service,
        controller: ref.read(provider.notifier),
        state: ref.read(provider),
        selection: selection,
        title: widget.title,
        treeUri: treeUri,
        cancel: token,
        onProgress: (fraction) {
          if (mounted) setState(() => _progress = fraction);
        },
      );
      if (!mounted) return;
      // Let the sheet close before the dialog opens (AC16).
      setState(() => _busy = false);
      saved = true;
      Navigator.of(context)
          .pop<ExportSaved>((result: result, treeUri: treeUri));
    } on Cancelled catch (cancel) {
      // Not a failure: the ticks stay, nothing was saved, no Retry.
      if (mounted) {
        setState(() {
          _cancelled = true;
          _partialLeft = cancel.partialFileLeft;
        });
      }
    } on ExportFailure catch (failure) {
      if (mounted) {
        setState(() {
          _failure = failure;
          _nothingLeft =
              failure is GenerationFailed &&
              !exportableSelection(ref.read(provider), selection).canDownload;
        });
      }
    } finally {
      _cancel = null;
      _cancelling = false;
      if (mounted && _busy) setState(() => _busy = false);
      if (mounted && !saved) _closeIfPlaybackGone();
    }
  }

  /// The picker, again and again until the folder is on this phone or the
  /// user backs out (user decision 2026-10-21): a Drive or app folder
  /// shows "Pick a folder on this phone." and reopens it straight away.
  Future<String?> _pickLocalFolder(ExportService service) async {
    while (true) {
      try {
        return await service.pickFolder();
      } on NotLocalFolder {
        if (!mounted) return null;
        setState(() => _notLocal = true);
      }
    }
  }

  /// [closeSheetWhenNotReady] fires once, when Playback leaves ready; if
  /// that happened mid-export, the PopScope (AC12) held the sheet open, so
  /// it is closed here instead, onto Playback's error view.
  void _closeIfPlaybackGone() {
    final phase = ref.read(playbackControllerProvider(widget.scoreId)).phase;
    if (phase == PlaybackPhase.ready) return;
    // Navigator.pop, not maybePop: the PopScope's canPop is only rebuilt
    // on the next frame, and the sheet must go now.
    Navigator.of(context).pop();
  }

  static String _messageFor(ExportFailure failure) => switch (failure) {
    StorageFull() => ExportMessages.storageFull,
    PermissionDenied() => ExportMessages.permissionDenied,
    GenerationFailed() => ExportMessages.generationFailed,
    Interrupted() => ExportMessages.interrupted,
    NoFolderPicker() => ExportMessages.noFolderPicker,
    // Handled by reopening the picker; only reached if that is bypassed.
    NotLocalFolder() => ExportMessages.notLocalFolder,
    // Shown by its own calm note, never as an error banner.
    Cancelled() => ExportMessages.cancelled,
  };
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
