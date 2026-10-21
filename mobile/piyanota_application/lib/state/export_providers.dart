import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../models/export_selection.dart';
import '../models/voice_part.dart';
import '../services/export_service.dart';
import '../services/notification_permission.dart';
import 'auth_providers.dart';
import 'capture_providers.dart';
import 'playback_providers.dart';

/// Tests override it with a fake.
final exportServiceProvider = Provider<ExportService>(
  (ref) => MethodChannelExportService(
    dio: ref.watch(dioProvider),
    workDir: getTemporaryDirectory,
  ),
);

/// Android 13+'s notification permission, asked before the first export
/// (user decision 2026-10-22). Tests override it with a fake.
final notificationPermissionProvider = Provider<NotificationPermission>(
  (ref) => PluginNotificationPermission(ref.watch(deviceChannelProvider)),
);

/// The level a ticked voice or click gets when the Voice Mixer does not
/// let it be heard (muted, soloed out, or its slider at 0): 80%, not full
/// (user decision 2026-10-21, kept 2026-10-22 when unmute stopped
/// resetting the level). Not the Mixer's reset level, which stays at
/// [PlaybackController.fullVolume] (PIYA-209 AC5).
const double exportDefaultLevel = 0.8;

// The Export sheet only reads Playback (user decision 2026-10-21): it
// starts from what the Mixer, the Speed sheet and the chips let be heard,
// and nothing ticked here is ever written back to them.

/// [voice] can be heard in Playback right now: it can play, its chip is
/// on (PIYA-208), it is not muted, not soloed out, and its slider is
/// above 0. Same rule as [PlaybackState.voiceGain], which the engine uses.
bool voiceAudibleForExport(PlaybackState state, VoicePart voice) =>
    state.voiceGain(voice) > 0;

/// The click is switched on and the Mixer lets it be heard. The click is
/// treated exactly like a voice (user decision 2026-10-21): pre-ticked
/// only when it is on and audible, and a ticked click that the Mixer
/// silences goes in at [exportDefaultLevel]. Unlike
/// [PlaybackState.clickGain] it does not wait for the playback click to
/// load: the export writes a click of its own.
bool clickAudibleForExport(PlaybackState state) =>
    state.metronomeOn &&
    state.clickStatus != ClickStatus.unavailable &&
    !state.clickNeedsTempo &&
    !_clickSilencedInMixer(state);

bool _clickSilencedInMixer(PlaybackState state) =>
    state.clickMuted ||
    (state.anySoloed && !state.clickSoloed) ||
    state.clickVolume <= 0;

bool _voiceSilencedInMixer(PlaybackState state, VoicePart voice) =>
    state.muted.contains(voice) ||
    (state.anySoloed && !state.soloed.contains(voice)) ||
    (state.volumes[voice] ?? PlaybackController.fullVolume) <= 0;

/// What the sheet starts with: the voices that can be heard, and the click
/// if it can be heard. A voice whose chip is off starts unticked.
ExportSelection initialExportSelection(PlaybackState state) {
  final selection = ExportSelection.preTicked(
    available: state.available,
    voices: {
      for (final voice in VoicePart.values)
        if (voiceAudibleForExport(state, voice)) voice,
    },
    withClick: clickAudibleForExport(state),
  );
  return exportableSelection(state, selection);
}

/// A ticked voice's level in the file: its Mixer level, or
/// [exportDefaultLevel] when the Mixer silences it. A voice ticked with
/// its chip off but not silenced in the Mixer keeps its Mixer level: the
/// chip is an on/off, not a level.
double exportVoiceGain(PlaybackState state, VoicePart voice) =>
    _voiceSilencedInMixer(state, voice)
    ? exportDefaultLevel
    : state.volumes[voice] ?? PlaybackController.fullVolume;

/// The ticked click's level: the Metronome row's, or [exportDefaultLevel]
/// when the Mixer silences it (muted, soloed out by a soloed voice, or
/// slider at 0), exactly as for a voice (user decision 2026-10-21).
double exportClickGain(PlaybackState state) =>
    _clickSilencedInMixer(state) ? exportDefaultLevel : state.clickVolume;

/// The click is written into the file: ticked, and the score has a tempo
/// to click at. Playback's own click failing to load does not matter: the
/// export writes its own, and says so if that fails too.
bool exportWantsClick(PlaybackState state, ExportSelection selection) =>
    selection.withClick && !state.clickNeedsTempo;

/// [selection] narrowed to the voices that can still be exported: a voice
/// that failed after it was ticked, or has no track, is dropped here so
/// the file name never names a voice the file does not hold.
ExportSelection exportableSelection(
  PlaybackState state,
  ExportSelection selection,
) {
  final tracks = state.result?.audioTracks ?? const <VoicePart, Uri>{};
  return selection.withAvailable({
    for (final voice in state.available)
      if (tracks[voice] != null) voice,
  });
}

/// Only the ticked voices (and the click, if ticked) at their export
/// levels, at the Playback speed. Unticked voices are not sent at all, so
/// the file runs as long as the longest ticked track. The click is
/// written by [writeClick] inside the export (L4), so its time is on the
/// bar and under Cancel; with no [writeClick] there is no click.
///
/// Throws [GenerationFailed] when no ticked voice is left: a file with no
/// ticked voice must never be saved and reported as a success.
ExportJob buildExportJob(
  PlaybackState state,
  ExportSelection selection,
  String title, {
  Future<Uri> Function()? writeClick,
  ExportNoticeText notice = ExportNoticeText.plain,
}) {
  final exported = exportableSelection(state, selection);
  if (!exported.canDownload) throw const GenerationFailed();
  final tracks = state.result?.audioTracks ?? const <VoicePart, Uri>{};
  final inputs = <ExportInput>[
    for (final voice in VoicePart.values)
      if (exported.voices.contains(voice))
        (track: tracks[voice]!, gain: exportVoiceGain(state, voice)),
  ];
  final clickGain = exportClickGain(state);
  return ExportJob(
    inputs: inputs,
    prepare: exportWantsClick(state, exported) && writeClick != null
        ? () async => (track: await writeClick(), gain: clickGain)
        : null,
    speed: state.speed,
    fileName: exportFileName(title: title, selection: exported),
    notice: notice,
  );
}

/// One export, start to finish: build the job, make and save the file,
/// writing the click on the way if it is wanted. The click file is this
/// export's own, so it is deleted here whatever happens. [state] and
/// [writeClick] are captured when the export starts
/// ([PlaybackController.exportClickWriter]) so it can finish after
/// Playback has closed.
Future<ExportResult> runExport({
  required ExportService service,
  required Future<Uri> Function() writeClick,
  required PlaybackState state,
  required ExportSelection selection,
  required String title,
  required String treeUri,
  ExportNoticeText notice = ExportNoticeText.plain,
  ExportCancelToken? cancel,
  ValueChanged<double>? onProgress,
}) async {
  // Checked first, so a voice that failed while the folder picker was
  // open costs nothing.
  if (!exportableSelection(state, selection).canDownload) {
    debugPrint('Export: no ticked voice can be played any more');
    throw const GenerationFailed();
  }
  Uri? click;
  try {
    final job = buildExportJob(
      state,
      selection,
      title,
      writeClick: () async => click = await writeClick(),
      notice: notice,
    );
    return await service.export(
      job,
      treeUri,
      cancel: cancel,
      onProgress: onProgress,
    );
  } on ExportFailure {
    rethrow;
  } on Object catch (e, stack) {
    // A bug or a plugin throwing something unexpected: the sheet still
    // shows a message and Retry rather than going quiet.
    debugPrint('Export: unexpected error: $e\n$stack');
    cancel?.throwIfCancelled();
    throw const GenerationFailed();
  } finally {
    if (click case final file?) await _deleteQuietly(file);
  }
}

Future<void> _deleteQuietly(Uri file) async {
  // Only a file the writer put on disk (tests hand back other schemes).
  if (file.scheme != 'file') return;
  try {
    await File.fromUri(file).delete();
  } on PathNotFoundException {
    // Moved into the export's work folder and removed with it.
  } on FileSystemException catch (e) {
    debugPrint('Export: click file not removed: $e');
  }
}
