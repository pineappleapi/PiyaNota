import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

/// A PDF the user chose, copied into app storage so it stays readable.
@immutable
class PickedPdf {
  const PickedPdf({required this.path, required this.name});
  final String path;
  final String name;
}

/// The chosen file isn't a PDF, whatever its name says (AC7).
class NotAPdfException implements Exception {
  const NotAPdfException();
}

/// Gallery and document pickers for Capture.
abstract interface class PagePicker {
  /// Photos chosen in the gallery, in the order the picker returns them.
  /// Empty when the user backs out.
  Future<List<String>> pickGalleryImages();

  /// Null when the user backs out. Throws [NotAPdfException].
  Future<PickedPdf?> pickPdf();
}

/// Tells the device a system picker is open over the app. The picker pauses
/// the Activity, which looks like "the user left" to the closed-app job; it
/// must not start writing the rows the user is submitting into.
class SignalingPagePicker implements PagePicker {
  const SignalingPagePicker(this._inner, this._pickerOpen);

  final PagePicker _inner;
  final Future<void> Function(bool open) _pickerOpen;

  Future<T> _around<T>(Future<T> Function() pick) async {
    await _pickerOpen(true);
    try {
      return await pick();
    } finally {
      await _pickerOpen(false);
    }
  }

  @override
  Future<List<String>> pickGalleryImages() =>
      _around(_inner.pickGalleryImages);

  @override
  Future<PickedPdf?> pickPdf() => _around(_inner.pickPdf);
}

/// Every PDF starts with this signature (ISO 32000-1 §7.5.2). Checked on
/// the bytes because a file manager can return any file whose name ends
/// in ".pdf", or ignore the extension filter.
const List<int> _pdfMagic = [0x25, 0x50, 0x44, 0x46, 0x2D]; // %PDF-

/// Some writers put a few junk bytes before the header; readers accept it
/// within the first kilobyte.
const int _pdfHeaderSearchBytes = 1024;

bool looksLikePdf(List<int> bytes) {
  final limit = bytes.length < _pdfHeaderSearchBytes
      ? bytes.length
      : _pdfHeaderSearchBytes;
  for (var start = 0; start + _pdfMagic.length <= limit; start++) {
    var match = true;
    for (var i = 0; i < _pdfMagic.length; i++) {
      if (bytes[start + i] != _pdfMagic[i]) {
        match = false;
        break;
      }
    }
    if (match) return true;
  }
  return false;
}

class PluginPagePicker implements PagePicker {
  PluginPagePicker(this._outputDir, {ImagePicker? imagePicker})
    : _imagePicker = imagePicker ?? ImagePicker();

  final Future<Directory> Function() _outputDir;
  final ImagePicker _imagePicker;

  @override
  Future<List<String>> pickGalleryImages() async {
    // Full metadata off: on Android 13+ this keeps the permission-less
    // system photo picker (AC3); orientation is still read from the file.
    // No resize/quality here: that made the plugin decode and re-encode every
    // photo, then prepare() did it again. The originals (JPEG, PNG, WebP,
    // HEIC) go to prepare(), which converts once, natively.
    final files = await _imagePicker.pickMultiImage(requestFullMetadata: false);
    return [for (final file in files) file.path];
  }

  @override
  Future<PickedPdf?> pickPdf() async {
    final file = await FilePicker.pickFile(
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
    );
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    if (!looksLikePdf(bytes)) throw const NotAPdfException();
    final dir = await _outputDir();
    final stamp = DateTime.now().microsecondsSinceEpoch;
    final copy = File('${dir.path}${Platform.pathSeparator}score-$stamp.pdf');
    await copy.writeAsBytes(bytes, flush: true);
    return PickedPdf(path: copy.path, name: file.name);
  }
}
