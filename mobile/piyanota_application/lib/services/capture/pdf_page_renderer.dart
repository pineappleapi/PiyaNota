import 'dart:typed_data';

import 'package:pdfx/pdfx.dart' as pdfx;

import 'device_channel.dart' show PdfProblem, PdfUnreadableException;

/// An open PDF the preview reads pages from.
abstract interface class PdfPreviewDocument {
  int get pageCount;

  /// PNG bytes of page [index] (0-based), [width] pixels wide.
  Future<Uint8List> renderPage(int index, {required double width});

  Future<void> close();
}

/// Behind an interface because widget tests can't make native calls.
abstract interface class PdfPageRenderer {
  /// Throws [PdfUnreadableException] for a broken or protected file.
  Future<PdfPreviewDocument> open(String path);
}

/// pdfx (Android PdfRenderer): no bundled engine, so a much smaller APK
/// than pdfrx; nothing here needs pdfrx's text or link features.
class PdfxPageRenderer implements PdfPageRenderer {
  const PdfxPageRenderer();

  @override
  Future<PdfPreviewDocument> open(String path) async {
    try {
      return _PdfxDocument(await pdfx.PdfDocument.openFile(path));
    } on Object {
      // The plugin throws untyped platform errors and can't say whether the
      // file is encrypted; the add step already named that case.
      throw const PdfUnreadableException(PdfProblem.corrupt);
    }
  }
}

const String _pageBackground = '#FFFFFF';

class _PdfxDocument implements PdfPreviewDocument {
  _PdfxDocument(this._doc);
  final pdfx.PdfDocument _doc;

  @override
  int get pageCount => _doc.pagesCount;

  @override
  Future<Uint8List> renderPage(int index, {required double width}) async {
    final page = await _doc.getPage(index + 1);
    try {
      final image = await page.render(
        width: width,
        height: width * page.height / page.width,
        format: pdfx.PdfPageImageFormat.png,
        // Without this the PNG keeps a transparent page, and the dark
        // preview backdrop shows through the black notation (dark gray).
        backgroundColor: _pageBackground,
      );
      if (image == null) throw const PdfUnreadableException(PdfProblem.corrupt);
      return image.bytes;
    } finally {
      await page.close();
    }
  }

  @override
  Future<void> close() => _doc.close();
}
