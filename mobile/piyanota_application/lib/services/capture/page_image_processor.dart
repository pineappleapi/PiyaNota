import 'dart:io';
import 'dart:isolate';
import 'dart:ui' show Size;

import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

import '../../models/page_edit.dart';

/// The picked file isn't an image the app can read (e.g. HEIC on a phone
/// without a decoder, a renamed document). Rejected at selection (AC7).
class UnreadableImageException implements Exception {
  const UnreadableImageException();
}

/// Turns picked photos into the files that upload (PIYA-101 AC10) and
/// applies Edit Page results. Both run off the UI isolate.
abstract interface class PageImageProcessor {
  /// Applies EXIF orientation, strips EXIF (location and device data never
  /// leave the phone), caps the long side at [maxLongSide] and writes a
  /// JPEG. Returns the new file's path.
  Future<String> prepare(String sourcePath);

  /// Writes [edit] applied to the image at [path] as a new JPEG.
  Future<String> applyEdit(String path, PageEdit edit);
}

/// PIYA-101 AC10: larger pages are scaled down before upload.
const int maxLongSide = 4032;
const int _jpegQuality = 90;

class IsolatePageImageProcessor implements PageImageProcessor {
  IsolatePageImageProcessor(this._outputDir);

  /// Resolves the folder new files go in (the app's temp folder).
  final Future<Directory> Function() _outputDir;
  int _counter = 0;

  @override
  Future<String> prepare(String sourcePath) async {
    final out = await _nextPath('page');
    await Isolate.run(() => prepareImageFile(sourcePath, out));
    return out;
  }

  @override
  Future<String> applyEdit(String path, PageEdit edit) async {
    final out = await _nextPath('edit');
    await Isolate.run(() => editImageFile(path, out, edit));
    return out;
  }

  Future<String> _nextPath(String prefix) async {
    final dir = await _outputDir();
    final stamp = DateTime.now().microsecondsSinceEpoch;
    return '${dir.path}${Platform.pathSeparator}$prefix-$stamp-${_counter++}.jpg';
  }
}

/// Isolate entry for [IsolatePageImageProcessor.prepare].
void prepareImageFile(String sourcePath, String outPath) {
  final bytes = File(sourcePath).readAsBytesSync();
  File(outPath).writeAsBytesSync(prepareImageBytes(bytes));
}

/// Isolate entry for [IsolatePageImageProcessor.applyEdit].
void editImageFile(String sourcePath, String outPath, PageEdit edit) {
  final decoded = img.decodeJpg(File(sourcePath).readAsBytesSync());
  if (decoded == null) throw const UnreadableImageException();
  final edited = applyPageEdit(decoded, edit);
  File(outPath).writeAsBytesSync(img.encodeJpg(edited, quality: _jpegQuality));
}

@visibleForTesting
Uint8List prepareImageBytes(Uint8List bytes) {
  final img.Image? decoded;
  try {
    decoded = img.decodeImage(bytes);
  } on Exception {
    throw const UnreadableImageException();
  }
  if (decoded == null) throw const UnreadableImageException();
  var page = _flattenToRgb8(img.bakeOrientation(decoded));
  final longSide = page.width > page.height ? page.width : page.height;
  if (longSide > maxLongSide) {
    page = page.width >= page.height
        ? img.copyResize(
            page,
            width: maxLongSide,
            interpolation: img.Interpolation.average,
          )
        : img.copyResize(
            page,
            height: maxLongSide,
            interpolation: img.Interpolation.average,
          );
  }
  // encodeJpg writes whatever EXIF the image carries; an empty block is
  // skipped, so this drops GPS, device and the (now baked) orientation.
  page.exif = img.ExifData();
  return img.encodeJpg(page, quality: _jpegQuality);
}

/// The [PageEdit] maths applied to pixels. Quarter turns alone take the
/// package's exact fast path; anything with a straighten angle samples
/// each output pixel back through [frameToSource] with bilinear filtering.
@visibleForTesting
img.Image applyPageEdit(img.Image source, PageEdit edit) {
  final k = edit.quarterTurns % 4;
  if (edit.straightenDegrees == 0) {
    final turned = img.copyRotate(source, angle: 90 * k);
    final w = turned.width;
    final h = turned.height;
    final left = (edit.crop.left * w).round();
    final top = (edit.crop.top * h).round();
    return img.copyCrop(
      turned,
      x: left,
      y: top,
      width: ((edit.crop.right * w).round() - left).clamp(1, w),
      height: ((edit.crop.bottom * h).round() - top).clamp(1, h),
    );
  }
  final sourceSize = Size(source.width.toDouble(), source.height.toDouble());
  final outSize = editedOutputSize(sourceSize, edit);
  final out = img.Image(
    width: outSize.width.toInt(),
    height: outSize.height.toInt(),
  );
  for (final p in out) {
    final frame = outputToFrame(
      p.x.toDouble(),
      p.y.toDouble(),
      sourceSize,
      edit,
    );
    final s = frameToSource(frame, sourceSize, edit);
    // Pixel centres sit at +0.5; getPixelInterpolate indexes corners.
    p.set(
      source.getPixelInterpolate(
        (s.dx - 0.5).clamp(0, source.width - 1),
        (s.dy - 0.5).clamp(0, source.height - 1),
      ),
    );
  }
  return out;
}

/// JPEG has no alpha or palette: flatten transparent PNGs onto white (a
/// black background would read as a solid page) and expand palettes.
img.Image _flattenToRgb8(img.Image src) {
  if (src.numChannels == 3 &&
      !src.hasPalette &&
      src.format == img.Format.uint8) {
    return src;
  }
  final out = img.Image(width: src.width, height: src.height);
  for (final p in src) {
    final a = src.hasAlpha ? p.aNormalized.toDouble() : 1.0;
    int blend(num channel) => ((channel * a + (1 - a)) * 255).round();
    out.setPixelRgb(
      p.x,
      p.y,
      blend(p.rNormalized),
      blend(p.gNormalized),
      blend(p.bNormalized),
    );
  }
  return out;
}
