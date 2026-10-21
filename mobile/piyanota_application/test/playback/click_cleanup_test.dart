import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/metronome_click.dart';

/// Click tracks a killed run left in the cache go at the next start; the
/// rest of the cache, and export work folders (cleared at the next
/// export, after the device says none is running), stay.
void main() {
  late Directory cache;
  final sep = Platform.pathSeparator;

  setUp(() async {
    cache = await Directory.systemTemp.createTemp('click_cleanup_');
  });

  tearDown(() async {
    if (cache.existsSync()) await cache.delete(recursive: true);
  });

  test('removes only stale click WAVs', () async {
    File f(String name) =>
        File('${cache.path}$sep$name')..writeAsStringSync('x');
    final stale = [
      f('${clickTrackPrefix}1.wav'),
      f('${clickTrackPrefix}2.wav'),
    ];
    final kept = [f('voice.wav'), f('${clickTrackPrefix}notes.txt')];
    final work = Directory('${cache.path}${sep}export_abc')..createSync();
    final inWork = File('${work.path}$sep${clickTrackPrefix}3.wav')
      ..writeAsStringSync('x');

    await clearStaleClickTracks(cache);

    for (final file in stale) {
      expect(file.existsSync(), isFalse);
    }
    for (final file in kept) {
      expect(file.existsSync(), isTrue);
    }
    expect(inWork.existsSync(), isTrue, reason: 'not recursive');
  });

  test('a missing cache folder is not an error', () async {
    await cache.delete(recursive: true);
    await clearStaleClickTracks(cache);
  });
}
