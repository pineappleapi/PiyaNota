import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

import 'package:piyanota_application/models/measure_table.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/demo/playback_demo.dart';

/// Path of the app package, whatever directory the tests run from.
String get _app => Directory.current.path;

void main() {
  group('PlaybackDemo', () {
    test('every voice fills every bar, pickup and meter changes '
        'included', () {
      final notes = PlaybackDemo.notes();
      for (final voice in VoicePart.values) {
        for (var bar = 0; bar < PlaybackDemo.barCount; bar++) {
          final ticks = notes
              .where((note) => note.voice == voice && note.bar == bar)
              .fold<int>(0, (sum, note) => sum + note.ticks);
          expect(ticks, PlaybackDemo.bars[bar].durTicks, reason: '$voice $bar');
        }
      }
    });

    test('the timing file parses: events in time order, and a gapless '
        'measure table with a pickup and consecutive meter changes', () {
      final file = TimingFile.parse(
        jsonDecode(jsonEncode(PlaybackDemo.timingJson())),
      );
      final notes = PlaybackDemo.notes();
      expect(file.events, hasLength(notes.length));
      for (var i = 0; i < file.events.length; i++) {
        expect(file.events[i].voice, notes[i].voice);
        expect(file.events[i].bar, notes[i].bar);
        expect(file.events[i].systemTopY, lessThan(file.events[i].y));
        expect(file.events[i].systemBottomY, greaterThan(file.events[i].y));
      }
      // 90 bpm: bar 1 starts after the one-quarter pickup, at 667 ms.
      expect(
        file.events.where((e) => e.bar == 1).map((e) => e.timestampMs).toSet(),
        contains(667),
      );
      final bars = file.bars;
      expect(bars.map((b) => b.bar), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
      expect(bars.first.pickup, isTrue);
      expect(bars.first.durTicks, 480);
      for (var i = 1; i < bars.length; i++) {
        expect(bars[i].startTick, bars[i - 1].startTick + bars[i - 1].durTicks);
        expect(bars[i].startMs, bars[i - 1].startMs! + bars[i - 1].durMs!);
        expect(bars[i].meterSource.trusted, isTrue);
      }
      expect(
        [for (final b in bars) '${b.numerator}/${b.denominator}'],
        [
          '3/4', '3/4', '3/4', '5/8', '2/4', '6/8', '6/8', '4/4', '4/4', //
        ],
      );
    });

    test('a failed Tenor has no events; the measure table is unchanged', () {
      final file = TimingFile.parse(
        jsonDecode(
          jsonEncode(PlaybackDemo.timingJson(failed: {VoicePart.tenor})),
        ),
      );
      expect(file.events.where((e) => e.voice == VoicePart.tenor), isEmpty);
      expect(file.events, isNotEmpty);
      expect(file.bars, hasLength(PlaybackDemo.barCount));
    });

    test('the muted Bass measure is silent but still timed', () {
      final muted = MutedMeasure.tryParse(PlaybackDemo.mutedMeasureJson())!;
      expect(muted.voice, VoicePart.bass);
      expect(muted.bar, PlaybackDemo.mutedBar);
      final events = TimingFile.parse(
        jsonDecode(jsonEncode(PlaybackDemo.timingJson())),
      ).events;
      expect(
        events.where((e) => e.voice == VoicePart.bass && e.bar == muted.bar),
        isNotEmpty,
      );
      final wav = PlaybackDemo.wav(VoicePart.bass);
      final pcm = ByteData.sublistView(wav, 44);
      int loudest(int fromMs, int toMs) {
        var peak = 0;
        final from = fromMs * PlaybackDemo.sampleRate ~/ 1000;
        final to = toMs * PlaybackDemo.sampleRate ~/ 1000;
        for (var i = from; i < to; i++) {
          final v = pcm.getInt16(i * 2, Endian.little).abs();
          if (v > peak) peak = v;
        }
        return peak;
      }

      // Inside the muted bar, clear of the rounding at its edges.
      expect(loudest(muted.startMs! + 5, muted.endMs! - 5), 0);
      expect(loudest(muted.endMs! + 60, muted.endMs! + 600), greaterThan(1000));
    });

    test('the indicator lands on ink: a notehead at every event', () {
      final page = PlaybackDemo.page();
      expect(page.width, PlaybackDemo.pageWidth);
      expect(page.height, PlaybackDemo.pageHeight);
      final events = PlaybackDemo.timingJson()['events']! as List<Object>;
      for (final event in events.cast<Map<String, Object>>()) {
        final x = event['x']! as int;
        final y = event['y']! as int;
        // Hollow heads (half/whole notes) have their ink on the rim.
        final dark = [
          for (var dx = -5; dx <= 5; dx++) page.getPixel(x + dx, y).luminance,
        ].any((luminance) => luminance < 128);
        expect(dark, isTrue, reason: '$event');
      }
    });

    test('each track is a mono 16-bit WAV as long as the score', () {
      final wav = PlaybackDemo.wav(VoicePart.bass);
      final header = ByteData.sublistView(wav, 0, 44);
      expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
      expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
      expect(header.getUint16(22, Endian.little), 1);
      expect(header.getUint32(24, Endian.little), PlaybackDemo.sampleRate);
      expect(header.getUint16(34, Endian.little), 16);
      final samples = header.getUint32(40, Endian.little) ~/ 2;
      expect(
        samples / PlaybackDemo.sampleRate,
        closeTo(PlaybackDemo.length.inMilliseconds / 1000, 0.01),
      );
      final pcm = ByteData.sublistView(wav, 44);
      var peak = 0;
      for (var i = 0; i < samples; i++) {
        final value = pcm.getInt16(i * 2, Endian.little).abs();
        if (value > peak) peak = value;
      }
      // Normalised to 0.35 of full scale: audible, never clipping.
      expect(peak, closeTo(0.35 * 32767, 2));
    });

    test('writeTo writes the files once and the PNG decodes', () async {
      final root = await Directory.systemTemp.createTemp('piyanota_demo');
      addTearDown(() => root.delete(recursive: true));
      final dir = Directory('${root.path}/demo');
      final files = await PlaybackDemo.writeTo(dir);
      for (final uri in [
        ...files.tracks.values,
        files.page,
        files.timing,
        files.timingWithoutTenor,
      ]) {
        expect(File.fromUri(uri).existsSync(), isTrue, reason: '$uri');
      }
      final png = img.decodePng(File.fromUri(files.page).readAsBytesSync())!;
      expect(png.width, PlaybackDemo.pageWidth);
      final written = File.fromUri(files.page).lastModifiedSync();
      await PlaybackDemo.writeTo(dir);
      expect(File.fromUri(files.page).lastModifiedSync(), written);
    });
  });

  // User decision 2026-10-09: the demo page (and audio) must not ship in
  // release/profile builds. Release builds have ApiConfig.useFakeAuth ==
  // false (a const), so what they contain is decided by what's bundled and
  // by what the non-fake path can reach; these pin both.
  group('release builds carry no demo', () {
    test('pubspec bundles no demo assets, and none exist', () {
      final pubspec = File('$_app/pubspec.yaml').readAsStringSync();
      expect(pubspec, isNot(contains('assets/demo')));
      expect(Directory('$_app/assets/demo').existsSync(), isFalse);
      // Only the branding assets are bundled.
      final bundled = RegExp(
        r'^\s+- (assets/\S*)',
        multiLine: true,
      ).allMatches(pubspec).map((m) => m[1]);
      expect(bundled, ['assets/branding/']);
    });

    test('no app code refers to a demo asset', () {
      for (final file in _dartFiles('$_app/lib')) {
        expect(
          file.readAsStringSync(),
          isNot(contains('assets/demo')),
          reason: file.path,
        );
      }
    });

    test('the demo is reachable only through the fake result API, which '
        'is built only under ApiConfig.useFakeAuth', () {
      final importers = [
        for (final file in _dartFiles('$_app/lib'))
          if (file.readAsStringSync().contains('demo/playback_demo.dart'))
            _relative(file),
      ];
      expect(importers, ['lib/services/fake_score_result_api.dart']);

      final constructors = [
        for (final file in _dartFiles('$_app/lib'))
          if (file.readAsStringSync().contains('FakeScoreResultApi('))
            _relative(file),
      ];
      expect(constructors, [
        'lib/services/fake_score_result_api.dart',
        'lib/state/playback_providers.dart',
      ]);
      final providers = File('$_app/lib/state/playback_providers.dart')
          .readAsStringSync();
      final gate = providers.indexOf('if (ApiConfig.useFakeAuth) {');
      final built = providers.indexOf('return FakeScoreResultApi(');
      final gateEnd =
          RegExp(r'\r?\n  \}\r?\n')
              .firstMatch(providers.substring(gate))!
              .start +
          gate;
      expect(gate, greaterThan(-1));
      expect(built, allOf(greaterThan(gate), lessThan(gateEnd)));
    });
  });
}

List<File> _dartFiles(String dir) {
  final files = [
    for (final entity in Directory(dir).listSync(recursive: true))
      if (entity is File && entity.path.endsWith('.dart')) entity,
  ]..sort((a, b) => a.path.compareTo(b.path));
  return files;
}

String _relative(File file) => file.path
    .substring(_app.length + 1)
    .replaceAll(Platform.pathSeparator, '/');
