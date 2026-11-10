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

    test('stripped file decodes to the same pixels (one scan header)', () {
      final out = stripJpegMetadata(upright)!;
      final a = img.decodeJpg(upright)!;
      final b = img.decodeJpg(out)!;
      for (final (x, y) in [(0, 0), (2000, 1500), (4031, 3023), (123, 2900)]) {
        expect(b.getPixel(x, y), a.getPixel(x, y));
      }
      // A doubled SOS header made decoders paint flat gray (1.6.0 bug).
      var sosCount = 0;
      for (var i = 0; i + 1 < 600; i++) {
        if (out[i] == 0xFF && out[i + 1] == 0xDA) sosCount++;
      }
      expect(sosCount, lessThanOrEqualTo(1));
    });

    test('COM, APP3-APP12 and bytes after the first EOI are dropped', () {
      List<int> seg(int marker, List<int> body) => [
        0xFF,
        marker,
        0,
        body.length + 2,
        ...body,
      ];
      final sos = upright.length;
      final noisy = Uint8List.fromList([
        ...upright.sublist(0, 2),
        ...seg(0xFE, [1, 2, 3]),
        ...seg(0xE5, [4, 5]),
        ...upright.sublist(2),
        ...seg(0xE1, [9, 9]), // trailer, then it must also end in EOI
        0xFF,
        0xD9,
      ]);
      expect(sos, greaterThan(0));
      final out = stripJpegMetadata(noisy)!;
      expect(out.length, lessThan(upright.length));
      expect(out.sublist(out.length - 2), [0xFF, 0xD9]);
      expect(img.decodeJpg(out)!.exif.gpsIfd.isEmpty, isTrue);
      // No COM/APP5 marker bytes survive in the header area.
      final head = out.sublist(0, 400);
      for (var i = 0; i + 1 < head.length; i++) {
        expect(
          head[i] == 0xFF && (head[i + 1] == 0xFE || head[i + 1] == 0xE5),
          isFalse,
        );
      }
    });

    test('a file not ending in EOI takes the full path', () {
      final cut = Uint8List.sublistView(upright, 0, upright.length - 2);
      expect(stripJpegMetadata(cut), isNull);
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
      // No native plugin on the desktop VM: null sends it to the Dart decoder.
      final processor = IsolatePageImageProcessor(
        () async => dir,
        compress: (_, _) async => null,
      );
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
