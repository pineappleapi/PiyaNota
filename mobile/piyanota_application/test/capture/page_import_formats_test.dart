import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

import 'package:piyanota_application/services/capture/page_image_processor.dart';

List<int> _heic(String brand) => [
  0,
  0,
  0,
  24,
  0x66,
  0x74,
  0x79,
  0x70,
  ...brand.codeUnits,
  0,
  0,
  0,
  0,
];

final List<int> _webp = [
  ...'RIFF'.codeUnits, 1, 2, 3, 4, ...'WEBPVP8 '.codeUnits, //
];

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('import'));
  tearDown(() => dir.deleteSync(recursive: true));

  File write(String name, List<int> bytes) =>
      File('${dir.path}/$name')..writeAsBytesSync(bytes);

  group('sniffImageFormat', () {
    test('accepts jpeg, png, webp, heic and heif by header, not by name', () {
      expect(
        sniffImageFormat(img.encodeJpg(img.Image(width: 4, height: 4))),
        PickedImageFormat.jpeg,
      );
      expect(
        sniffImageFormat(img.encodePng(img.Image(width: 4, height: 4))),
        PickedImageFormat.png,
      );
      expect(sniffImageFormat(_webp), PickedImageFormat.webp);
      for (final brand in ['heic', 'heix', 'mif1', 'msf1', 'heif']) {
        expect(sniffImageFormat(_heic(brand)), PickedImageFormat.heic);
      }
    });

    test('rejects gif, bmp, pdf, text, other ftyp brands and short files', () {
      expect(sniffImageFormat('GIF89a....'.codeUnits), isNull);
      expect(sniffImageFormat('BM......'.codeUnits), isNull);
      expect(sniffImageFormat('%PDF-1.7 and more'.codeUnits), isNull);
      expect(sniffImageFormat(_heic('mp42')), isNull);
      expect(sniffImageFormat([0xFF, 0xD8]), isNull);
      expect(sniffImageFormat(const []), isNull);
    });
  });

  test('compressMinSide makes the plugin scale cap the long side', () {
    // Mirrors the plugin: scale = max(1, min(w / m, h / m)).
    int longAfter(int w, int h) {
      final m = compressMinSide(w, h);
      final s = [w / m, h / m].reduce((a, b) => a < b ? a : b);
      final scale = s < 1 ? 1.0 : s;
      return ((w > h ? w : h) / scale).round();
    }

    expect(longAfter(8160, 6120), lessThanOrEqualTo(maxLongSide));
    expect(longAfter(4000, 16000), lessThanOrEqualTo(maxLongSide));
    expect(longAfter(16000, 4000), lessThanOrEqualTo(maxLongSide));
    expect(longAfter(6120, 8160), lessThanOrEqualTo(maxLongSide));
    expect(compressMinSide(3000, 2000), 2000);
    expect(longAfter(3000, 2000), 3000);
    expect(compressMinSide(4032, 3024), 3024);
  });

  group('IsolatePageImageProcessor.prepare', () {
    late List<(String, String)> nativeCalls;
    late IsolatePageImageProcessor processor;

    IsolatePageImageProcessor build(NativeCompress compress) =>
        IsolatePageImageProcessor(() async => dir, compress: compress);

    setUp(() {
      nativeCalls = [];
      // Stands in for the platform plugin: writes a small JPEG.
      processor = build((src, dest) async {
        nativeCalls.add((src, dest));
        File(dest)
            .writeAsBytesSync(img.encodeJpg(img.Image(width: 8, height: 8)));
        return dest;
      });
    });

    test(
      'upright JPEG: byte-copy fast path, GPS gone, no native call',
      () async {
        final photo = img.Image(width: 64, height: 48)
          ..exif.gpsIfd.gpsLatitude = 14.5;
        final src = write('a.jpg', img.encodeJpg(photo));
        final out = await processor.prepare(src.path);
        expect(nativeCalls, isEmpty);
        expect(
          img.decodeJpg(File(out).readAsBytesSync())!.exif.gpsIfd.isEmpty,
          isTrue,
        );
      },
    );

    test('rotated JPEG goes native', () async {
      final photo = img.Image(width: 64, height: 48)
        ..exif.imageIfd.orientation = 6;
      final src = write('r.jpg', img.encodeJpg(photo));
      final out = await processor.prepare(src.path);
      expect(nativeCalls.single.$1, src.path);
      expect(out, nativeCalls.single.$2);
      expect(out.endsWith('.jpg'), isTrue);
    });

    test(
      'png, webp and heic/heif each go native and come out as .jpg',
      () async {
        final files = {
          'p.png': img.encodePng(img.Image(width: 8, height: 8)),
          'w.webp': _webp,
          'h.heic': _heic('heic'),
          'h2.heif': _heic('mif1'),
        };
        for (final e in files.entries) {
          final out = await processor.prepare(write(e.key, e.value).path);
          expect(File(out).existsSync(), isTrue, reason: e.key);
          expect(out.endsWith('.jpg'), isTrue, reason: e.key);
        }
        expect(nativeCalls, hasLength(files.length));
      },
    );

    test(
      'gif, text and empty files are unreadable and never reach native',
      () async {
        for (final bytes in [
          'GIF89a......'.codeUnits,
          'hello world'.codeUnits,
          const <int>[],
        ]) {
          await expectLater(
            processor.prepare(write('x.png', bytes).path),
            throwsA(isA<UnreadableImageException>()),
          );
        }
        expect(nativeCalls, isEmpty);
      },
    );

    test(
      'native failure on a real PNG falls back to the Dart decoder',
      () async {
        for (final failing in <NativeCompress>[
          (s, d) async => null,
          (s, d) async => throw Exception('native refused'),
        ]) {
          final p = build(failing);
          final src = write(
            'f.png',
            img.encodePng(img.Image(width: 9, height: 7)),
          );
          final out = await p.prepare(src.path);
          final decoded = img.decodeJpg(File(out).readAsBytesSync())!;
          expect((decoded.width, decoded.height), (9, 7));
        }
      },
    );

    test(
      'native failure on a corrupt HEIC is unreadable, not a crash',
      () async {
        final p = build((s, d) async => null);
        await expectLater(
          p.prepare(write('c.heic', _heic('heic')).path),
          throwsA(isA<UnreadableImageException>()),
        );
      },
    );
  });

  test(
    'prepareInParallel reports progress once per file, failures included',
    () async {
      final good = write(
        'g.jpg',
        img.encodeJpg(img.Image(width: 8, height: 8)),
      );
      final bad = write('b.jpg', [1, 2, 3]);
      final processor = IsolatePageImageProcessor(
        () async => dir,
        compress: (s, d) async => null,
      );
      final ticks = <int>[];
      final out = await prepareInParallel(
        processor,
        [good.path, bad.path, good.path],
        onProgress: (done, total) {
          expect(total, 3);
          ticks.add(done);
        },
      );
      expect(ticks..sort(), [1, 2, 3]);
      expect(out.map((e) => e == null), [false, true, false]);
    },
  );
}
