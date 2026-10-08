import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

import 'package:piyanota_application/models/page_edit.dart';
import 'package:piyanota_application/services/capture/page_image_processor.dart';

Matcher _near(Offset expected, [double tolerance = 1e-9]) => isA<Offset>()
    .having((o) => (o - expected).distance, 'distance', lessThan(tolerance));

void main() {
  const source = Size(300, 400);

  group('PageEdit model', () {
    test('identity and copyWith wrap quarter turns', () {
      expect(const PageEdit().isIdentity, isTrue);
      expect(const PageEdit().copyWith(quarterTurns: 5).quarterTurns, 1);
      expect(const PageEdit(quarterTurns: 4).isIdentity, isTrue);
    });

    test('rotating resets the crop', () {
      const edit = PageEdit(crop: Rect.fromLTRB(0.1, 0.1, 0.9, 0.9));
      final turned = edit.rotatedClockwise();
      expect(turned.quarterTurns, 1);
      expect(turned.crop, PageEdit.fullCrop);
      expect(
        const PageEdit(quarterTurns: 3).rotatedClockwise().quarterTurns,
        0,
      );
    });
  });

  group('rotatedSize / coverScale', () {
    test('odd turns swap sides', () {
      expect(rotatedSize(source, 1), const Size(400, 300));
      expect(rotatedSize(source, 2), source);
    });

    test('no straighten needs no zoom', () {
      expect(coverScale(source, 0), 1);
    });

    test('a turned picture zoomed by coverScale covers the frame corners', () {
      for (final degrees in [-45.0, -12.5, 3.0, 30.0, 45.0]) {
        final edit = PageEdit(straightenDegrees: degrees);
        for (final corner in [
          Offset.zero,
          Offset(source.width, 0),
          Offset(0, source.height),
          Offset(source.width, source.height),
        ]) {
          final s = frameToSource(corner, source, edit);
          expect(s.dx, inInclusiveRange(-1e-6, source.width + 1e-6));
          expect(s.dy, inInclusiveRange(-1e-6, source.height + 1e-6));
        }
      }
    });

    test('coverScale is the smallest such zoom (a corner touches an edge)', () {
      const edit = PageEdit(straightenDegrees: 20);
      final s = frameToSource(Offset.zero, source, edit);
      final touches = [
        s.dx,
        s.dy,
        source.width - s.dx,
        source.height - s.dy,
      ].any((d) => d.abs() < 1e-6);
      final other = frameToSource(Offset(source.width, 0), source, edit);
      final otherTouches = [
        other.dx,
        other.dy,
        source.width - other.dx,
        source.height - other.dy,
      ].any((d) => d.abs() < 1e-6);
      expect(touches || otherTouches, isTrue);
    });
  });

  group('frameToSource', () {
    test('identity maps points to themselves', () {
      expect(
        frameToSource(const Offset(12, 34), source, const PageEdit()),
        _near(const Offset(12, 34)),
      );
    });

    test('quarter turns are clockwise', () {
      // After one clockwise turn the frame is 400x300; its top-left came
      // from the source's bottom-left.
      expect(
        frameToSource(Offset.zero, source, const PageEdit(quarterTurns: 1)),
        _near(const Offset(0, 400)),
      );
      expect(
        frameToSource(Offset.zero, source, const PageEdit(quarterTurns: 2)),
        _near(const Offset(300, 400)),
      );
      expect(
        frameToSource(Offset.zero, source, const PageEdit(quarterTurns: 3)),
        _near(const Offset(300, 0)),
      );
    });

    test('the centre stays put when straightening', () {
      expect(
        frameToSource(
          const Offset(150, 200),
          source,
          const PageEdit(straightenDegrees: 17),
        ),
        _near(const Offset(150, 200)),
      );
    });

    test('positive straighten turns the picture clockwise on screen', () {
      // A frame point right of centre shows picture content from above-
      // right of centre when the picture is turned clockwise.
      final s = frameToSource(
        const Offset(250, 200),
        source,
        const PageEdit(straightenDegrees: 10),
      );
      expect(s.dx, greaterThan(150));
      expect(s.dy, lessThan(200));
    });
  });

  group('editedOutputSize / outputToFrame', () {
    test('crop with no straighten keeps source resolution', () {
      const edit = PageEdit(crop: Rect.fromLTRB(0.5, 0, 1, 0.25));
      expect(editedOutputSize(source, edit), const Size(150, 100));
      expect(
        outputToFrame(0, 0, source, edit),
        _near(const Offset(150.5, 0.5)),
      );
    });

    test('straightening shrinks the output by the zoom', () {
      const edit = PageEdit(straightenDegrees: 30);
      final scale = coverScale(source, 30 * math.pi / 180);
      final size = editedOutputSize(source, edit);
      expect(size.width, (300 / scale).roundToDouble());
      expect(size.height, (400 / scale).roundToDouble());
    });
  });

  group('dragCropCorner', () {
    test('moves only the dragged corner', () {
      final crop = dragCropCorner(
        PageEdit.fullCrop,
        Alignment.topLeft,
        const Offset(0.2, 0.3),
      );
      expect(crop, const Rect.fromLTRB(0.2, 0.3, 1, 1));
    });

    test('clamps inside the frame', () {
      final crop = dragCropCorner(
        PageEdit.fullCrop,
        Alignment.bottomRight,
        const Offset(1.5, -2),
      );
      expect(crop.right, 1);
      expect(crop.bottom, closeTo(PageEdit.minCropFraction, 1e-9));
    });

    test('keeps the minimum side', () {
      final crop = dragCropCorner(
        const Rect.fromLTRB(0.4, 0.4, 0.6, 0.6),
        Alignment.topLeft,
        const Offset(0.9, 0.9),
      );
      expect(crop.width, closeTo(PageEdit.minCropFraction, 1e-9));
      expect(crop.height, closeTo(PageEdit.minCropFraction, 1e-9));
    });
  });

  group('applyPageEdit (pixels follow the maths)', () {
    /// 3x2 image with a distinct colour per pixel.
    img.Image grid() {
      final image = img.Image(width: 3, height: 2);
      for (final p in image) {
        p.setRgb(p.x * 80, p.y * 120, 7);
      }
      return image;
    }

    test('quarter-turn fast path matches quarterTurnToSource', () {
      final src = grid();
      for (final k in [1, 2, 3]) {
        final out = applyPageEdit(src, PageEdit(quarterTurns: k));
        expect(out.width, k.isOdd ? 2 : 3);
        for (final p in out) {
          final s = quarterTurnToSource(
            Offset(p.x + 0.5, p.y + 0.5),
            const Size(3, 2),
            k,
          );
          final expected = src.getPixel(s.dx.floor(), s.dy.floor());
          expect(p.r, expected.r, reason: 'k=$k at (${p.x},${p.y})');
          expect(p.g, expected.g, reason: 'k=$k at (${p.x},${p.y})');
        }
      }
    });

    test('one clockwise turn puts the left edge on top', () {
      final src = img.Image(width: 2, height: 1)
        ..setPixelRgb(0, 0, 255, 0, 0)
        ..setPixelRgb(1, 0, 0, 0, 255);
      final out = applyPageEdit(src, const PageEdit(quarterTurns: 1));
      expect(out.width, 1);
      expect(out.height, 2);
      expect(out.getPixel(0, 0).r, 255);
      expect(out.getPixel(0, 1).b, 255);
    });

    test('crop cuts the expected pixels', () {
      final out = applyPageEdit(
        grid(),
        const PageEdit(crop: Rect.fromLTRB(1 / 3, 0.5, 1, 1)),
      );
      expect(out.width, 2);
      expect(out.height, 1);
      expect(out.getPixel(0, 0).r, 80);
      expect(out.getPixel(0, 0).g, 120);
    });

    test('straightened output has the computed size', () {
      final src = img.Image(width: 60, height: 80);
      const edit = PageEdit(straightenDegrees: 15);
      final out = applyPageEdit(src, edit);
      final size = editedOutputSize(const Size(60, 80), edit);
      expect(out.width, size.width);
      expect(out.height, size.height);
    });
  });

  group('prepareImageBytes', () {
    test('strips EXIF and bakes orientation', () {
      final src = img.Image(width: 4, height: 2)..setPixelRgb(0, 0, 255, 0, 0);
      src.exif.imageIfd.orientation = 6; // rotate 90° CW to display
      src.exif.gpsIfd['GPSLatitude'] = img.IfdValueRational(14, 1);
      final jpeg = img.encodeJpg(src);
      final out = img.decodeJpg(prepareImageBytes(jpeg))!;
      expect(out.width, 2, reason: 'orientation baked into pixels');
      expect(out.height, 4);
      expect(out.exif.isEmpty, isTrue);
    });

    test('caps the long side at 4032 px', () {
      final src = img.Image(width: 5000, height: 100);
      final out = img.decodeJpg(prepareImageBytes(img.encodePng(src)))!;
      expect(out.width, maxLongSide);
    });

    test('flattens transparency onto white', () {
      final src = img.Image(width: 2, height: 2, numChannels: 4);
      final out = img.decodeJpg(prepareImageBytes(img.encodePng(src)))!;
      expect(out.getPixel(0, 0).r, greaterThan(245));
    });

    test('rejects bytes that are not an image', () {
      expect(
        () => prepareImageBytes(Uint8List.fromList('%PDF-1.7'.codeUnits)),
        throwsA(isA<UnreadableImageException>()),
      );
    });
  });
}
