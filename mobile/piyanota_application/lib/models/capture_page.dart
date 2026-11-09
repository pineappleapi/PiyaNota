import 'package:flutter/foundation.dart';

/// Where a page came from. Decides the endpoint at submit (PIYA-206 AC8):
/// camera and gallery photos go to PIYA-101, a PDF to PIYA-310.
enum PageSource { camera, gallery, pdf }

/// One item in the capture strip: a single photo, or a whole PDF shown as
/// one card. A PDF can't be mixed with photos (PIYA-310 AC1).
@immutable
sealed class CaptureItem {
  const CaptureItem({required this.id, required this.path});

  /// Stable across reorders and edits, for keys and undo.
  final int id;

  /// Local file the item uploads from. For a photo this is the prepared
  /// JPEG (orientation applied, EXIF stripped, ≤ 4032 px), replaced after
  /// each edit.
  final String path;

  /// Pages this item adds to the job.
  int get pageCount;
}

class PhotoPage extends CaptureItem {
  const PhotoPage({
    required super.id,
    required super.path,
    required this.source,
  });

  final PageSource source;

  @override
  int get pageCount => 1;

  PhotoPage withPath(String newPath) =>
      PhotoPage(id: id, path: newPath, source: source);
}

class PdfDocument extends CaptureItem {
  const PdfDocument({
    required super.id,
    required super.path,
    required this.name,
    required this.pages,
  });

  final String name;
  final int pages;

  @override
  int get pageCount => pages;
}
