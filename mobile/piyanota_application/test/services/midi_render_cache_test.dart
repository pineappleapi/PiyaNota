import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/midi_render_cache.dart';
import 'package:piyanota_application/services/midi_synth.dart';

const _eot = [0x00, 0xFF, 0x2F, 0x00];
Uint8List _track(List<int> b) =>
    Uint8List.fromList([0x4D, 0x54, 0x72, 0x6B, 0, 0, 0, b.length, ...b]);
final Uint8List _smf = Uint8List.fromList([
  0x4D, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 1, 0, 1, 0x01, 0xE0,
  ..._track([0x00, 0x90, 60, 90, 0x60, 0x80, 60, 0, ..._eot]),
]);

ScoreResult _result(int id, {String fileId = 'f', List<MutedMeasure> muted = const []}) =>
    ScoreResult(
      scoreId: id,
      audioTracks: {VoicePart.soprano: Uri.parse('https://x/s.mp3')},
      scoreImages: const [],
      review: const ReviewSummary(reviewNeeded: false),
      mutedMeasures: muted,
      midiCombined: MidiCombinedFile(url: Uri.parse('https://x/c.mid'), fileId: fileId),
    );

void main() {
  late Directory tmp;
  late File mid;
  var renders = 0;
  final peaks = <int>[1000, 2000, 5000, 500];
  final scaled = <double>[];
  var tick = 0;

  MidiRenderCache make({MidiSynthFn? synth}) => MidiRenderCache(
    rootDir: () async => Directory('${tmp.path}/cache')..createSync(recursive: true),
    tempDir: () async => tmp,
    soundfont: () async => 'sf2',
    synth: synth ?? ({required sf2Path, required midPath, required wavPath}) async {
      File(wavPath).writeAsBytesSync([0]);
      return peaks[renders++ % 4];
    },
    scale: (p, f) async => scaled.add(f),
    now: () => DateTime.fromMillisecondsSinceEpoch(tick++),
  );

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('rc');
    mid = File('${tmp.path}/c.mid')..writeAsBytesSync(_smf);
    renders = 0;
    scaled.clear();
    tick = 1;
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  test('success: 4 wavs, one common gain from max peak', () async {
    final out = await make().renderVoices(_result(1), midiPath: () async => mid.path);
    expect(out!.keys, VoicePart.values);
    expect(scaled, [2.0, 2.0, 2.0, 2.0]);
  });

  test('cache hit skips render and midiPath', () async {
    final c = make();
    await c.renderVoices(_result(1), midiPath: () async => mid.path);
    final before = renders;
    final out = await c.renderVoices(_result(1), midiPath: () async => throw StateError('no'));
    expect(out, isNotNull);
    expect(renders, before);
  });

  test('changed fileId re-renders', () async {
    final c = make();
    await c.renderVoices(_result(1), midiPath: () async => mid.path);
    await c.renderVoices(_result(1, fileId: 'g'), midiPath: () async => mid.path);
    expect(renders, 8);
  });

  test('keeps newest 3 scores', () async {
    final c = make();
    for (final id in [1, 2, 3, 4]) {
      await c.renderVoices(_result(id), midiPath: () async => mid.path);
    }
    final names = Directory('${tmp.path}/cache').listSync().map((e) => e.uri.pathSegments.where((s) => s.isNotEmpty).last).toSet();
    expect(names, {'2_v2', '3_v2', '4_v2'});
  });

  test('orphaned .tmp dirs are evicted', () async {
    final orphan = Directory('${tmp.path}/cache/9_v2.1.tmp')..createSync(recursive: true);
    await make().renderVoices(_result(1), midiPath: () async => mid.path);
    expect(orphan.existsSync(), isFalse);
  });

  test('synth unavailable -> null and no half cache', () async {
    final c = make(synth: ({required sf2Path, required midPath, required wavPath}) async =>
        throw const MidiSynthUnavailable('x'));
    expect(await c.renderVoices(_result(1), midiPath: () async => mid.path), isNull);
    expect(Directory('${tmp.path}/cache').listSync(), isEmpty);
  });

  test('bad midi -> null', () async {
    File(mid.path).writeAsBytesSync([1, 2, 3]);
    expect(await make().renderVoices(_result(1), midiPath: () async => mid.path), isNull);
  });

  test('silentRangesFor: bar ticks win, ms fallback, per voice', () {
    const bars = [BarInfo(bar: 2, startTick: 1920, durTicks: 1920)];
    final r = silentRangesFor(
      VoicePart.alto,
      const [
        MutedMeasure(voice: VoicePart.alto, bar: 2),
        MutedMeasure(voice: VoicePart.alto, bar: 9, startMs: 1000, endMs: 2000),
        MutedMeasure(voice: VoicePart.bass, bar: 2),
        MutedMeasure(voice: VoicePart.alto, pageIndex: 0),
      ],
      bars,
      120,
    );
    expect(r, [(1920, 3840), (960, 1920)]);
  });
}
