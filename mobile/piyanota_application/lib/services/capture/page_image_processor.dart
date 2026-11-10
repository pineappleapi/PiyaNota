import 'dart:io';
import 'dart:typed_data' show BytesBuilder;
import 'dart:isolate';
import 'dart:ui' as ui;
import 'dart:ui' show Size;

import 'package:flutter/foundation.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
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
  /// JPEG, whatever the input (JPEG, PNG, WebP, HEIC). Throws
  /// [UnreadableImageException] for anything else. Returns the new path.
  Future<String> prepare(String sourcePath);

  /// Writes [edit] applied to the image at [path] as a new JPEG.
  Future<String> applyEdit(String path, PageEdit edit);
}

/// PIYA-101 AC10: larger pages are scaled down before upload.
const int maxLongSide = 4032;
const int _jpegQuality = 90;

/// Re-encodes [source] to [dest] as an upright, metadata-free JPEG with the
/// long side at most [maxLongSide]; null when the platform can't. Native, so
/// HEIC/WebP/PNG decode and EXIF rotation run off the UI thread at hardware
/// speed instead of in the pure-Dart decoder (the slow gallery import).
typedef NativeCompress = Future<String?> Function(String source, String dest);

/// The plugin scales by `max(1, min(w / minWidth, h / minHeight))`, so the
/// min side, not the long side, is what a box caps. Passing the same value
/// for both makes the scale `short / m`; this `m` gives `long / maxLongSide`
/// (floored, so the result never rounds above the cap). Symmetric in w/h, so
/// EXIF rotation cannot swap it wrong. A small image gets `short`, scale 1.
@visibleForTesting
int compressMinSide(int width, int height) {
  final long = width > height ? width : height;
  final short = width > height ? height : width;
  if (long <= maxLongSide) return short;
  final m = (short * maxLongSide) ~/ long;
  return m < 1 ? 1 : m;
}

Future<String?> flutterImageCompress(String source, String dest) async {
  final int side;
  try {
    final buffer = await ui.ImmutableBuffer.fromFilePath(source);
    try {
      final d = await ui.ImageDescriptor.encoded(buffer);
      side = compressMinSide(d.width, d.height);
      d.dispose();
    } finally {
      buffer.dispose();
    }
  } on Exception {
    return null; // can't read the size natively: the Dart decoder takes over
  }
  final out = await FlutterImageCompress.compressAndGetFile(
    source,
    dest,
    minWidth: side,
    minHeight: side,
    quality: _jpegQuality,
    autoCorrectionAngle: true,
    keepExif: false,
  );
  return out?.path;
}

class IsolatePageImageProcessor implements PageImageProcessor {
  IsolatePageImageProcessor(
    this._outputDir, {
    this._compress = flutterImageCompress,
  });

  /// Resolves the folder new files go in (the app's temp folder).
  final Future<Directory> Function() _outputDir;
  final NativeCompress _compress;
  int _counter = 0;

  @override
  Future<String> prepare(String sourcePath) async {
    final out = await _nextPath('page');
    final route = await Isolate.run(
      () => prepareImageFileFast(sourcePath, out),
    );
    switch (route) {
      case PrepareRoute.done:
        return out;
      case PrepareRoute.unsupported:
        throw const UnreadableImageException();
      case PrepareRoute.native:
        break;
    }
    try {
      final done = await _compress(sourcePath, out);
      if (done != null && File(done).existsSync()) return done;
    } on Exception {
      // Native decoder refused (e.g. HEIC below Android 9, out of memory):
      // the Dart decoder gets one try; it throws Unreadable if it can't.
    }
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

/// What [prepareImageFileFast] decided for a picked file.
enum PrepareRoute { done, native, unsupported }

/// Formats the picker may hand over (the backend takes JPEG and PNG pages,
/// so everything else is converted to JPEG here).
enum PickedImageFormat { jpeg, png, webp, heic }

const List<String> _heicBrands = [
  'heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'hevm', 'hevs', 'mif1',
  'msf1', 'heif', //
];

/// Format from the file header, ignoring the file name; null for anything
/// else (GIF, BMP, PDF, text, truncated files).
PickedImageFormat? sniffImageFormat(List<int> b) {
  bool at(int i, List<int> sig) {
    if (b.length < i + sig.length) return false;
    for (var k = 0; k < sig.length; k++) {
      if (b[i + k] != sig[k]) return false;
    }
    return true;
  }

  if (at(0, const [0xFF, 0xD8, 0xFF])) return PickedImageFormat.jpeg;
  if (at(0, const [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])) {
    return PickedImageFormat.png;
  }
  if (at(0, const [0x52, 0x49, 0x46, 0x46]) &&
      at(8, const [0x57, 0x45, 0x42, 0x50])) {
    return PickedImageFormat.webp; // RIFF....WEBP
  }
  if (at(4, const [0x66, 0x74, 0x79, 0x70]) && b.length >= 12) {
    final brand = String.fromCharCodes(b.sublist(8, 12));
    if (_heicBrands.contains(brand)) return PickedImageFormat.heic;
  }
  return null;
}

/// Isolate entry: the cheap routes. An upright JPEG only loses its metadata
/// (byte copy, F11); an unknown format is rejected before any decoder runs;
/// the rest needs a real decode ([PrepareRoute.native]).
PrepareRoute prepareImageFileFast(String sourcePath, String outPath) {
  final bytes = File(sourcePath).readAsBytesSync();
  final stripped = stripJpegMetadata(bytes);
  if (stripped != null) {
    File(outPath).writeAsBytesSync(stripped);
    return PrepareRoute.done;
  }
  return sniffImageFormat(bytes) == null
      ? PrepareRoute.unsupported
      : PrepareRoute.native;
}

/// Isolate entry: full Dart decode, the fallback when the native one fails.
void prepareImageFile(String sourcePath, String outPath) {
  final bytes = File(sourcePath).readAsBytesSync();
  File(outPath).writeAsBytesSync(prepareImageBytesFull(bytes));
}

/// Isolate entry for [IsolatePageImageProcessor.applyEdit].
void editImageFile(String sourcePath, String outPath, PageEdit edit) {
  final decoded = img.decodeJpg(File(sourcePath).readAsBytesSync());
  if (decoded == null) throw const UnreadableImageException();
  final edited = applyPageEdit(decoded, edit);
  File(outPath).writeAsBytesSync(img.encodeJpg(edited, quality: _jpegQuality));
}

/// Strip-only path first, else the Dart decode. Production goes through
/// [prepareImageFileFast] and the native compressor; this stays for the F11
/// benchmark and as the decode fallback.
@visibleForTesting
Uint8List prepareImageBytes(Uint8List bytes) =>
    stripJpegMetadata(bytes) ?? prepareImageBytesFull(bytes);

/// Decode, bake orientation, cap the long side and re-encode. Also the
/// "before" side of the F11 benchmark.
@visibleForTesting
Uint8List prepareImageBytesFull(Uint8List bytes) {
  final img.Image? decoded;
  try {
    decoded = img.decodeImage(bytes);
  } on Exception {
    throw const UnreadableImageException();
  } on RangeError {
    // The decoder reads truncated headers past the end instead of throwing
    // a FormatException; still just an unreadable file.
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

const int _jpegMarker = 0xFF;
const int _markerSoi = 0xD8;
const int _markerSos = 0xDA;
const int _markerApp1 = 0xE1;
const int _markerApp3 = 0xE3;
const int _markerApp12 = 0xEC;
const int _markerApp13 = 0xED;
const int _markerCom = 0xFE;
const int _markerEoi = 0xD9;
const int _orientationTag = 0x0112;

/// Returns [bytes] without EXIF/XMP (APP1), APP3-APP12, IPTC (APP13) and
/// comment segments, cut after the first end-of-image so a trailer (Ultra
/// HDR, Multi-Picture) cannot carry its own EXIF. Null when the cheap strip
/// is not enough: not a JPEG, a file that does not end in EOI (possibly
/// truncated, and the body is never decoded here), a rotation tag other
/// than "upright", a long side over [maxLongSide], or a layout it can't
/// walk. The caller then takes the full decode path, so a null here
/// is always safe.
@visibleForTesting
Uint8List? stripJpegMetadata(Uint8List bytes) {
  if (bytes.length < 4 || bytes[0] != _jpegMarker || bytes[1] != _markerSoi) {
    return null;
  }
  if (bytes[bytes.length - 2] != _jpegMarker ||
      bytes[bytes.length - 1] != _markerEoi) {
    return null;
  }
  final out = BytesBuilder(copy: false)..add(const [_jpegMarker, _markerSoi]);
  var pos = 2;
  var sawSize = false;
  while (pos + 4 <= bytes.length) {
    if (bytes[pos] != _jpegMarker) return null;
    final marker = bytes[pos + 1];
    final length = (bytes[pos + 2] << 8) | bytes[pos + 3];
    final end = pos + 2 + length;
    if (length < 2 || end > bytes.length) return null;
    if (marker == _markerApp1) {
      if (_exifOrientation(bytes, pos + 4, end) > 1) return null;
    } else if (marker != _markerSos && // copied whole with its scan below
        marker != _markerApp13 &&
        marker != _markerCom &&
        (marker < _markerApp3 || marker > _markerApp12)) {
      out.add(Uint8List.sublistView(bytes, pos, end));
    }
    // Start-of-frame (any coding mode, not the DHT/JPG/DAC markers).
    if (marker >= 0xC0 &&
        marker <= 0xCF &&
        marker != 0xC4 &&
        marker != 0xC8 &&
        marker != 0xCC) {
      if (length < 9) return null;
      final height = (bytes[pos + 5] << 8) | bytes[pos + 6];
      final width = (bytes[pos + 7] << 8) | bytes[pos + 8];
      if (height > maxLongSide || width > maxLongSide) return null;
      sawSize = true;
    }
    if (marker == _markerSos) {
      if (!sawSize) return null;
      // Entropy data never holds FFD9 (a 0xFF there is stuffed or RSTn).
      var eoi = end;
      while (eoi + 1 < bytes.length &&
          !(bytes[eoi] == _jpegMarker && bytes[eoi + 1] == _markerEoi)) {
        eoi++;
      }
      if (eoi + 1 >= bytes.length) return null;
      out.add(Uint8List.sublistView(bytes, pos, eoi + 2));
      return out.takeBytes();
    }
    pos = end;
  }
  return null;
}

/// EXIF orientation (1 = upright) from an APP1 payload in `[start, end)`;
/// 1 for payloads that aren't EXIF or carry no tag.
int _exifOrientation(Uint8List b, int start, int end) {
  const header = [0x45, 0x78, 0x69, 0x66, 0, 0]; // "Exif\0\0"
  if (end - start < header.length + 8) return 1;
  for (var i = 0; i < header.length; i++) {
    if (b[start + i] != header[i]) return 1;
  }
  final tiff = start + header.length;
  final little = b[tiff] == 0x49;
  int u16(int at) =>
      little ? b[at] | (b[at + 1] << 8) : (b[at] << 8) | b[at + 1];
  int u32(int at) =>
      little ? u16(at) | (u16(at + 2) << 16) : (u16(at) << 16) | u16(at + 2);
  final ifd = tiff + u32(tiff + 4);
  if (ifd + 2 > end) return 1;
  final count = u16(ifd);
  for (var i = 0; i < count; i++) {
    final entry = ifd + 2 + i * 12;
    if (entry + 12 > end) return 1;
    if (u16(entry) == _orientationTag) return u16(entry + 8);
  }
  return 1;
}

/// Prepares [paths] with at most [workers] running at once, keeping order.
/// An entry is null when that file is not a readable image. Two workers
/// match the two isolates the phone can spare without starving the UI.
Future<List<String?>> prepareInParallel(
  PageImageProcessor processor,
  List<String> paths, {
  int workers = 2,
  void Function(int done, int total)? onProgress,
}) async {
  final results = List<String?>.filled(paths.length, null);
  var next = 0;
  var done = 0;
  Future<void> worker() async {
    while (next < paths.length) {
      final i = next++;
      try {
        results[i] = await processor.prepare(paths[i]);
      } on UnreadableImageException {
        results[i] = null;
      }
      onProgress?.call(++done, paths.length);
    }
  }

  await Future.wait([for (var w = 0; w < workers; w++) worker()]);
  return results;
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
