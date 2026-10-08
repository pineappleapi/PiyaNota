import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/painting.dart';

/// How screens show a page file and learn its pixel size. Behind an
/// interface because widget tests can't decode real files inside the fake
/// test clock.
abstract interface class PageImageSource {
  ImageProvider imageFor(String path);

  /// Pixel size, read from the file header without decoding every pixel.
  Future<Size> sizeOf(String path);
}

/// Decodes [image] no larger than a square of [logicalSide] logical pixels
/// at [devicePixelRatio], keeping its aspect ratio. A 12 MP page decoded at
/// full size is ~48 MB of RAM per copy; the screen never shows more than
/// its own pixels. Edits are still applied to the full-size file.
ImageProvider capToDisplay(
  ImageProvider image, {
  required double logicalSide,
  required double devicePixelRatio,
}) {
  final side = (logicalSide * devicePixelRatio).ceil();
  return ResizeImage(
    image,
    width: side,
    height: side,
    policy: ResizeImagePolicy.fit,
    allowUpscaling: false,
  );
}

class FilePageImageSource implements PageImageSource {
  const FilePageImageSource();

  @override
  ImageProvider imageFor(String path) => FileImage(File(path));

  @override
  Future<Size> sizeOf(String path) async {
    final buffer = await ui.ImmutableBuffer.fromFilePath(path);
    final descriptor = await ui.ImageDescriptor.encoded(buffer);
    final size = Size(
      descriptor.width.toDouble(),
      descriptor.height.toDouble(),
    );
    descriptor.dispose();
    buffer.dispose();
    return size;
  }
}
