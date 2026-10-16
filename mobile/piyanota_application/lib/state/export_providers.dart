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

/// Playback as the export would hear it: the ticked voices stand in for
/// the Playback chips, and the click counts as on and loaded when ticked.
/// Mute, Solo and levels are Playback's own (PIYA-211 AC23).
///
/// Built on [PlaybackState.voiceGain] and [PlaybackState.clickGain] so the
/// export can never disagree with what the engine plays.
PlaybackState exportView(PlaybackState state, ExportSelection selection) =>
    state.copyWith(
      selected: selection.voices,
      metronomeOn: selection.withClick && !state.clickNeedsTempo,
      clickStatus: ClickStatus.ready,
    );

/// The ticked voices (and the click) with their effective gains, at the
/// Playback speed. A ticked voice the Mixer silences stays in at gain 0,
/// so the file still runs the length of the piece.
ExportJob buildExportJob(
  PlaybackState state,
  ExportSelection selection,
  String title, {
  Uri? clickTrack,
}) {
  final view = exportView(state, selection);
  final tracks = state.result?.audioTracks ?? const <VoicePart, Uri>{};
  final inputs = <ExportInput>[
    for (final voice in VoicePart.values)
      // A voice that failed while the sheet was open is left out.
      if (selection.voices.contains(voice) &&
          state.available.contains(voice) &&
          tracks[voice] != null)
        (track: tracks[voice]!, gain: view.voiceGain(voice)),
    if (view.metronomeOn && clickTrack != null)
      (track: clickTrack, gain: view.clickGain),
  ];
  return ExportJob(
    inputs: inputs,
    speed: state.speed,
    fileName: exportFileName(title: title, selection: selection),
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
}) async {
  final wantsClick = exportView(state, selection).metronomeOn;
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
    final job = buildExportJob(state, selection, title, clickTrack: click);
    return await service.export(job, treeUri);
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
