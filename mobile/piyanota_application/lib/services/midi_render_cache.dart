import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/measure_table.dart';
import '../models/score_result.dart';
import '../models/voice_part.dart';
import 'metronome_click.dart';
import 'midi_synth.dart';
import 'midi_voice_split.dart';

/// Bump when the render recipe changes (gain, split rules, soundfont) so old
/// caches are not reused.
const int kRenderVersion = 3;

/// Renders (one per score and tempo) kept on disk; older ones are deleted.
/// A few, so dragging the slider back to a recent tempo is instant.
const int kRenderCacheKeepScores = 4;

/// Common peak target for the four voices: about 0.3 of int16 full scale.
const int kRenderTargetPeak = 10000;

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
const String _kClickFile = 'click.wav';
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

/// The four voice WAVs and the metronome click WAV (null when the score has
/// no bar table to lay a click on).
typedef MidiRender = ({Map<VoicePart, Uri> voices, Uri? click});

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
  ///
  /// [bpm] is the chosen tempo (default: the score's own); the MIDI's tempo
  /// is scaled to it so the audio is rendered, never time-stretched.
  Future<MidiRender?> renderVoices(
    ScoreResult result, {
    required Future<String> Function() midiPath,
    List<BarInfo> bars = const [],
    int? bpm,
  }) async {
    final chosen = bpm ?? result.tempoBpm;
    final midi = result.midiCombined;
    if (midi == null) return null;
    final ranges = {
      for (final v in VoicePart.values)
        v: silentRangesFor(v, result.mutedMeasures, bars, result.tempoBpm),
    };
    final key = '${midi.fileId}|$chosen|${_hash(ranges.toString())}|'
        '${_hash(bars.map((b) => '${b.startTick}/${b.durTicks}').join(','))}';
    final root = await rootDir();
    final dir = Directory(
      '${root.path}/${result.scoreId}_v${kRenderVersion}_b$chosen',
    );
    try {
      final hit = _readCache(dir, key);
      if (hit != null) {
        _touch(dir);
        return hit;
      }
      // Unique per load so overlapping loads of one score cannot collide.
      final stamp = now().microsecondsSinceEpoch;
      final tmp = Directory('${dir.path}.$stamp.tmp');
      tmp.createSync(recursive: true);
      try {
        final smf = await File(await midiPath()).readAsBytes();
        await _renderAll(
          smf,
          ranges,
          tmp,
          stamp,
          chosen / result.tempoBpm,
          chosen,
          bars,
        );
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
    int stamp,
    double tempoScale,
    int bpm,
    List<BarInfo> bars,
  ) async {
    final sf2 = await soundfont();
    final temp = await tempDir();
    final peaks = <int>[];
    for (final voice in VoicePart.values) {
      final split = splitVoice(
        smf,
        kVoiceChannel[voice]!,
        silentRanges: ranges[voice]!,
        tempoScale: tempoScale,
      );
      final mid = File('${temp.path}/render_${voice.name}_$stamp.mid');
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
    if (maxPeak > 0) {
      final gain = (kRenderTargetPeak / maxPeak).clamp(0.0, kRenderMaxGain);
      for (final voice in VoicePart.values) {
        await scale('${out.path}/${voice.name}.wav', gain);
      }
    }
    await _renderClick(sf2, temp, out, stamp, bpm, bars);
  }

  /// The click as its own WAV (own level: it is toggled and mixed apart
  /// from the voices). Skipped without bars: there is no grid to lay it on.
  Future<void> _renderClick(
    String sf2,
    Directory temp,
    Directory out,
    int stamp,
    int bpm,
    List<BarInfo> bars,
  ) async {
    if (bars.isEmpty) return;
    // planClicks times are tick x usPerTick; at 125 bpm that is exactly
    // 1 ms per tick, so a click's millisecond is its tick.
    const msPerTickBpm = 125;
    final last = bars.last;
    final plan = planClicks(
      bars: bars,
      events: const [],
      tempoBpm: msPerTickBpm,
      chosenBpm: bpm,
      length: Duration(milliseconds: last.startTick + last.durTicks),
    );
    final clicks = [
      for (var i = 0; i < plan.clicks.length; i++)
        (plan.clicks[i].inMilliseconds, plan.levels[i] == ClickLevel.downbeat),
    ];
    if (clicks.isEmpty) return;
    final mid = File('${temp.path}/render_click_$stamp.mid');
    await mid.writeAsBytes(buildClickMidi(clicks, bpm), flush: true);
    try {
      final wav = '${out.path}/$_kClickFile';
      final peak = await synth(sf2Path: sf2, midPath: mid.path, wavPath: wav);
      if (peak > 0) await scale(wav, kRenderTargetPeak / peak);
    } finally {
      if (mid.existsSync()) mid.deleteSync();
    }
  }

  MidiRender? _readCache(Directory dir, String key) {
    final keyFile = File('${dir.path}/$_kKeyFile');
    if (!keyFile.existsSync() || keyFile.readAsStringSync() != key) return null;
    final out = <VoicePart, Uri>{};
    for (final v in VoicePart.values) {
      final f = File('${dir.path}/${v.name}.wav');
      if (!f.existsSync()) return null;
      out[v] = f.uri;
    }
    final click = File('${dir.path}/$_kClickFile');
    return (voices: out, click: click.existsSync() ? click.uri : null);
  }

  void _touch(Directory dir) => File('${dir.path}/used.txt')
      .writeAsStringSync('${now().millisecondsSinceEpoch}', flush: true);

  void _evict(Directory root) {
    final used = <(int, Directory)>[];
    for (final e in root.listSync()) {
      if (e is! Directory) continue;
      // Orphan of a killed render; a live one is not at risk because renders
      // of different scores rarely overlap and a lost one just re-renders.
      if (e.path.endsWith('.tmp')) {
        e.deleteSync(recursive: true);
        continue;
      }
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
