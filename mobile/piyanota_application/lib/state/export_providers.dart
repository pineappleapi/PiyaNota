import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../models/export_selection.dart';
import '../models/voice_part.dart';
import '../services/export_service.dart';
import 'auth_providers.dart';
import 'playback_providers.dart';

/// Tests override it with a fake.
final exportServiceProvider = Provider<ExportService>(
  (ref) => MethodChannelExportService(
    dio: ref.watch(dioProvider),
    workDir: getTemporaryDirectory,
  ),
);

/// The level a ticked track gets when the Voice Mixer does not let it be
/// heard (muted, soloed out, or its slider at 0): the Mixer's reset level
/// (PIYA-209 AC5), so ticking it in the sheet always puts it in the file
/// at a level the user can hear (user decision 2026-10-21).
const double exportDefaultLevel = PlaybackController.fullVolume;

/// The click's level in that case. The Metronome row resets to the same
/// level as the voices, so it is one constant under a name of its own.
const double exportDefaultClickLevel = PlaybackController.fullVolume;

// The Export sheet only reads Playback (user decision 2026-10-21): it
// starts from what the Mixer, the Speed sheet and the chips let be heard,
// and nothing ticked here is ever written back to them.

/// [voice] can be heard in Playback right now: it can play, its chip is
/// on (PIYA-208), it is not muted, not soloed out, and its slider is
/// above 0. Same rule as [PlaybackState.voiceGain], which the engine uses.
bool voiceAudibleForExport(PlaybackState state, VoicePart voice) =>
    state.voiceGain(voice) > 0;

/// The click is switched on and the Mixer lets it be heard. Unlike
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

/// The ticked click's level: the Metronome row's, or
/// [exportDefaultClickLevel] when the Mixer silences it (muted, soloed
/// out by a soloed voice, or slider at 0).
double exportClickGain(PlaybackState state) =>
    _clickSilencedInMixer(state) ? exportDefaultClickLevel : state.clickVolume;

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
/// the file runs as long as the longest ticked track.
///
/// Throws [GenerationFailed] when no ticked voice is left: a file with no
/// ticked voice must never be saved and reported as a success.
ExportJob buildExportJob(
  PlaybackState state,
  ExportSelection selection,
  String title, {
  Uri? clickTrack,
}) {
  final exported = exportableSelection(state, selection);
  if (!exported.canDownload) throw const GenerationFailed();
  final tracks = state.result?.audioTracks ?? const <VoicePart, Uri>{};
  final inputs = <ExportInput>[
    for (final voice in VoicePart.values)
      if (exported.voices.contains(voice))
        (track: tracks[voice]!, gain: exportVoiceGain(state, voice)),
    if (exportWantsClick(state, exported) && clickTrack != null)
      (track: clickTrack, gain: exportClickGain(state)),
  ];
  return ExportJob(
    inputs: inputs,
    speed: state.speed,
    fileName: exportFileName(title: title, selection: exported),
  );
}

/// One export, start to finish: write the click if it is wanted, build
/// the job, make and save the file. The click file is this export's own,
/// so it is deleted here whatever happens.
Future<ExportResult> runExport({
  required ExportService service,
  required PlaybackController controller,
  required PlaybackState state,
  required ExportSelection selection,
  required String title,
  required String treeUri,
  ExportCancelToken? cancel,
  ValueChanged<double>? onProgress,
}) async {
  // Checked before the click is written, so a voice that failed while the
  // folder picker was open costs nothing.
  if (!exportableSelection(state, selection).canDownload) {
    debugPrint('Export: no ticked voice can be played any more');
    throw const GenerationFailed();
  }
  final wantsClick = exportWantsClick(state, selection);
  Uri? click;
  try {
    if (wantsClick) {
      try {
        click = await controller.writeExportClick();
      } on Object catch (e, stack) {
        debugPrint('Export: click not generated: $e\n$stack');
        throw const GenerationFailed();
      }
    }
    cancel?.throwIfCancelled();
    final job = buildExportJob(state, selection, title, clickTrack: click);
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
    throw const GenerationFailed();
  } finally {
    if (click != null) await _deleteQuietly(click);
  }
}

Future<void> _deleteQuietly(Uri file) async {
  // Only a file the writer put on disk (tests hand back other schemes).
  if (file.scheme != 'file') return;
  try {
    await File.fromUri(file).delete();
  } on FileSystemException catch (e) {
    debugPrint('Export: click file not removed: $e');
  }
}
