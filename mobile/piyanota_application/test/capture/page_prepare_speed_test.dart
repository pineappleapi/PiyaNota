import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

import 'package:piyanota_application/services/capture/page_image_processor.dart';

/// Synthetic ~12 MP photo (4032x3024) with GPS-bearing EXIF. Noise-free
/// gradient so the encode is quick; decode/encode cost still scales with
/// pixel count, which is what the benchmark measures.
Uint8List _photo({int orientation = 1, bool gps = true}) {
  final image = img.Image(width: 4032, height: 3024);
  for (final p in image) {
    p.setRgb(p.x % 256, p.y % 256, (p.x + p.y) % 256);
  }
  image.exif.imageIfd.orientation = orientation;
  if (gps) image.exif.gpsIfd.gpsLatitude = 14.5;
  return img.encodeJpg(image, quality: 90);
}

void main() {
  late Uint8List upright;
  late Uint8List rotated;

  setUpAll(() {
    upright = _photo();
    rotated = _photo(orientation: 6);
  });

  group('stripJpegMetadata', () {
    test('upright photo: GPS gone, pixels untouched, no re-encode', () {
      final out = stripJpegMetadata(upright)!;
      expect(img.decodeJpg(out)!.exif.gpsIfd.isEmpty, isTrue);
      expect(img.decodeJpg(upright)!.exif.gpsIfd.isEmpty, isFalse);
      expect(out.length, lessThan(upright.length));
      final a = img.decodeJpg(out)!;
      expect((a.width, a.height), (4032, 3024));
    });

    test('rotated, oversize and non-JPEG inputs take the full path', () {
      expect(stripJpegMetadata(rotated), isNull);
      expect(stripJpegMetadata(Uint8List.fromList([1, 2, 3, 4, 5])), isNull);
      final big = img.encodeJpg(img.Image(width: 5000, height: 100));
      expect(stripJpegMetadata(big), isNull);
    });

    test('prepareImageBytes bakes orientation 6 and strips GPS', () {
      final out = img.decodeJpg(prepareImageBytes(rotated))!;
      expect((out.width, out.height), (3024, 4032));
      expect(out.exif.gpsIfd.isEmpty, isTrue);
    });
  });

  test('prepareInParallel keeps order and marks unreadable as null', () async {
    final dir = Directory.systemTemp.createTempSync('prep');
    addTearDown(() => dir.deleteSync(recursive: true));
    final good = File('${dir.path}/a.jpg')
      ..writeAsBytesSync(img.encodeJpg(img.Image(width: 10, height: 10)));
    final bad = File('${dir.path}/b.jpg')..writeAsBytesSync([1, 2, 3]);
    final processor = IsolatePageImageProcessor(() async => dir);
    final out = await prepareInParallel(processor, [
      good.path,
      bad.path,
      good.path,
    ]);
    expect(out.map((e) => e == null), [false, true, false]);
  });

  test('SYNTHETIC benchmark: 4 x 12 MP gallery photos, before vs after', () {
    final sw = Stopwatch()..start();
    for (var i = 0; i < 4; i++) {
      prepareImageBytesFull(upright);
    }
    final before = sw.elapsedMilliseconds;
    sw
      ..reset()
      ..start();
    for (var i = 0; i < 4; i++) {
      prepareImageBytes(upright);
    }
    final after = sw.elapsedMilliseconds;
    // ignore: avoid_print
    print(
      'F11 synthetic (desktop VM, not phone): upright 4x12MP '
      'before=${before}ms after=${after}ms',
    );
    expect(after, lessThan(before));
  }, timeout: const Timeout(Duration(minutes: 3)));

  test(
    'SYNTHETIC benchmark: 4 x 12 MP rotated photos, 1 vs 2 isolates',
    () async {
      final dir = Directory.systemTemp.createTempSync('prep');
      addTearDown(() => dir.deleteSync(recursive: true));
      final paths = [
        for (var i = 0; i < 4; i++)
          (File('${dir.path}/r$i.jpg')..writeAsBytesSync(rotated)).path,
      ];
      final processor = IsolatePageImageProcessor(() async => dir);
      final sw = Stopwatch()..start();
      await prepareInParallel(processor, paths, workers: 1);
      final one = sw.elapsedMilliseconds;
      sw
        ..reset()
        ..start();
      await prepareInParallel(processor, paths);
      final two = sw.elapsedMilliseconds;
      // ignore: avoid_print
      print(
        'F11 synthetic (desktop VM, not phone): rotated 4x12MP '
        'sequential=${one}ms two-isolates=${two}ms',
      );
      expect(two, lessThan(one));
    },
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
