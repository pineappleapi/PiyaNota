import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/measure_table.dart';
import '../models/score_result.dart';
import '../models/voice_part.dart';
import 'midi_synth.dart';
import 'midi_voice_split.dart';

/// Bump when the render recipe changes (gain, split rules, soundfont) so old
/// caches are not reused.
const int kRenderVersion = 1;

/// Scores whose rendered voices are kept on disk; older ones are deleted.
const int kRenderCacheKeepScores = 3;

/// Common peak target for the four voices: 0.8 of int16 full scale.
const int kRenderTargetPeak = 26214;

/// Upper bound on the common gain so a near-silent render is not blown up.
const double kRenderMaxGain = 4;

/// MIDI channel of each voice in the backend's combined file (backend/midi_combined.py).
const Map<VoicePart, int> kVoiceChannel = {
  VoicePart.soprano: 0,
  VoicePart.alto: 1,
  VoicePart.tenor: 2,
  VoicePart.bass: 3,
};

const int _kPpq = 480;
const int _kMsPerMinute = 60000;
const String _kKeyFile = 'key.txt';
const int _kFnvOffset = 0x811C9DC5;
const int _kFnvPrime = 0x01000193;
const int _kMask32 = 0xFFFFFFFF;

/// Tick spans of [voice] to leave silent, from the result's mutedMeasures.
///
/// The server's mutedMeasures carry the printed bar and start/end ms (the
/// raw start/end ticks are not kept by the parser). The bar's exact ticks
/// from [bars] win; otherwise ms are converted at [bpm], which is exact
/// because the combined MIDI has one base tempo. Entries that resolve to
/// neither are skipped.
List<(int, int)> silentRangesFor(
  VoicePart voice,
  Iterable<MutedMeasure> muted,
  List<BarInfo> bars,
  int bpm,
) {
  final byBar = {for (final b in bars) b.bar: b};
  final ranges = <(int, int)>[];
  for (final m in muted) {
    if (m.voice != voice) continue;
    final bar = m.bar == null ? null : byBar[m.bar];
    if (bar != null) {
      ranges.add((bar.startTick, bar.startTick + bar.durTicks));
    } else if (m.startMs != null && m.endMs != null && m.endMs! > m.startMs!) {
      int toTick(int ms) => ms * bpm * _kPpq ~/ _kMsPerMinute;
      ranges.add((toTick(m.startMs!), toTick(m.endMs!)));
    }
  }
  return ranges;
}

typedef MidiSynthFn =
    Future<int> Function({
      required String sf2Path,
      required String midPath,
      required String wavPath,
    });

/// Renders each voice of the combined MIDI to a WAV and keeps the result on
/// disk so reopening a score does not re-render it.
class MidiRenderCache {
  MidiRenderCache({
    required this.rootDir,
    required this.tempDir,
    required this.soundfont,
    this.synth = renderMidiToWav,
    this.scale = scaleWav,
    this.now = DateTime.now,
  });

  final Future<Directory> Function() rootDir;
  final Future<Directory> Function() tempDir;
  final Future<String> Function() soundfont;
  final MidiSynthFn synth;
  final Future<void> Function(String path, double factor) scale;
  final DateTime Function() now;

  /// The four voice WAVs for [result], or null when the synth or the MIDI is
  /// unusable (the caller plays the MP3s instead). [midiPath] is only called
  /// on a cache miss, so a hit never downloads.
  Future<Map<VoicePart, Uri>?> renderVoices(
    ScoreResult result, {
    required Future<String> Function() midiPath,
    List<BarInfo> bars = const [],
  }) async {
    final midi = result.midiCombined;
    if (midi == null) return null;
    final ranges = {
      for (final v in VoicePart.values)
        v: silentRangesFor(v, result.mutedMeasures, bars, result.tempoBpm),
    };
    final key = '${midi.fileId}|${_hash(ranges.toString())}';
    final root = await rootDir();
    final dir = Directory('${root.path}/${result.scoreId}_v$kRenderVersion');
    try {
      final hit = _readCache(dir, key);
      if (hit != null) {
        _touch(dir);
        return hit;
      }
      final tmp = Directory('${dir.path}.tmp');
      if (tmp.existsSync()) tmp.deleteSync(recursive: true);
      tmp.createSync(recursive: true);
      try {
        final smf = await File(await midiPath()).readAsBytes();
        await _renderAll(smf, ranges, tmp);
        File('${tmp.path}/$_kKeyFile').writeAsStringSync(key, flush: true);
      } on Object {
        if (tmp.existsSync()) tmp.deleteSync(recursive: true);
        rethrow;
      }
      if (dir.existsSync()) dir.deleteSync(recursive: true);
      tmp.renameSync(dir.path);
      _touch(dir);
      _evict(root);
      return _readCache(dir, key);
    } on MidiSynthUnavailable catch (e) {
      debugPrint('MIDI render skipped: $e');
    } on MidiSynthError catch (e) {
      debugPrint('MIDI render failed: $e');
    } on FormatException catch (e) {
      debugPrint('MIDI unusable: $e');
    } on FileSystemException catch (e) {
      debugPrint('MIDI render files: $e');
    }
    return null;
  }

  Future<void> _renderAll(
    Uint8List smf,
    Map<VoicePart, List<(int, int)>> ranges,
    Directory out,
  ) async {
    final sf2 = await soundfont();
    final temp = await tempDir();
    final peaks = <int>[];
    for (final voice in VoicePart.values) {
      final split = splitVoice(
        smf,
        kVoiceChannel[voice]!,
        silentRanges: ranges[voice]!,
      );
      final mid = File('${temp.path}/render_${voice.name}.mid');
      await mid.writeAsBytes(split, flush: true);
      try {
        peaks.add(
          await synth(
            sf2Path: sf2,
            midPath: mid.path,
            wavPath: '${out.path}/${voice.name}.wav',
          ),
        );
      } finally {
        if (mid.existsSync()) mid.deleteSync();
      }
    }
    final maxPeak = peaks.reduce((a, b) => a > b ? a : b);
    if (maxPeak <= 0) return;
    final gain = (kRenderTargetPeak / maxPeak).clamp(0.0, kRenderMaxGain);
    for (final voice in VoicePart.values) {
      await scale('${out.path}/${voice.name}.wav', gain);
    }
  }

  Map<VoicePart, Uri>? _readCache(Directory dir, String key) {
    final keyFile = File('${dir.path}/$_kKeyFile');
    if (!keyFile.existsSync() || keyFile.readAsStringSync() != key) return null;
    final out = <VoicePart, Uri>{};
    for (final v in VoicePart.values) {
      final f = File('${dir.path}/${v.name}.wav');
      if (!f.existsSync()) return null;
      out[v] = f.uri;
    }
    return out;
  }

  void _touch(Directory dir) => File('${dir.path}/used.txt')
      .writeAsStringSync('${now().millisecondsSinceEpoch}', flush: true);

  void _evict(Directory root) {
    final used = <(int, Directory)>[];
    for (final e in root.listSync()) {
      if (e is! Directory || e.path.endsWith('.tmp')) continue;
      final f = File('${e.path}/used.txt');
      final ms = f.existsSync() ? int.tryParse(f.readAsStringSync()) ?? 0 : 0;
      used.add((ms, e));
    }
    used.sort((a, b) => b.$1.compareTo(a.$1));
    for (final (_, d) in used.skip(kRenderCacheKeepScores)) {
      d.deleteSync(recursive: true);
    }
  }

  static String _hash(String s) {
    var h = _kFnvOffset;
    for (final c in s.codeUnits) {
      h = ((h ^ c) * _kFnvPrime) & _kMask32;
    }
    return h.toRadixString(16);
  }
}
