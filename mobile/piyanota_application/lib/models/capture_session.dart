import 'package:flutter/foundation.dart';

import 'capture_page.dart';

/// The pages being assembled on Capture, with the PIYA-206 rules kept in
/// one place: at most [maxPages] pages, and either photos or a single PDF,
/// never both (PIYA-310 AC1 / PIYA-101 `mixed_input_types`).
@immutable
class CaptureSession {
  const CaptureSession([this.items = const []]);

  /// PIYA-101 AC2 and PIYA-206 AC6.
  static const int maxPages = 20;

  final List<CaptureItem> items;

  bool get isEmpty => items.isEmpty;
  bool get hasPdf => items.any((item) => item is PdfDocument);
  bool get hasPhotos => items.any((item) => item is PhotoPage);
  int get pageCount => items.fold(0, (sum, item) => sum + item.pageCount);

  /// How many more photos fit.
  int get photoRoom => hasPdf ? 0 : maxPages - pageCount;

  PdfDocument? get pdf {
    for (final item in items) {
      if (item is PdfDocument) return item;
    }
    return null;
  }

  List<PhotoPage> get photos => [
    for (final item in items)
      if (item is PhotoPage) item,
  ];

  /// Endpoint choice at submit (AC8).
  PageSource? get inputKind {
    if (items.isEmpty) return null;
    return hasPdf ? PageSource.pdf : PageSource.camera;
  }

  /// Adds photos at the end, keeping only as many as fit. Callers must
  /// clear a PDF first (see [withoutAll]).
  CaptureSession addPhotos(List<PhotoPage> photos) {
    assert(!hasPdf, 'photos and a PDF cannot be mixed');
    final room = photoRoom.clamp(0, maxPages);
    return CaptureSession([...items, ...photos.take(room)]);
  }

  /// Replaces everything with [pdf]: one PDF per score, never mixed.
  CaptureSession withPdf(PdfDocument pdf) {
    assert(pdf.pages <= maxPages, 'check the page limit before adding');
    return CaptureSession([pdf]);
  }

  CaptureSession withoutAll() => const CaptureSession();

  CaptureSession remove(int id) =>
      CaptureSession([for (final item in items) if (item.id != id) item]);

  /// Puts back an item removed from [index] (Undo).
  CaptureSession insert(int index, CaptureItem item) {
    final next = [...items]..insert(index.clamp(0, items.length), item);
    return CaptureSession(next);
  }

  /// [newIndex] follows [ReorderableListView]'s convention: the index the
  /// item had in the list *before* removal, so moving right overshoots by 1.
  CaptureSession reorder(int oldIndex, int newIndex) {
    final next = [...items];
    final target = newIndex > oldIndex ? newIndex - 1 : newIndex;
    next.insert(target, next.removeAt(oldIndex));
    return CaptureSession(next);
  }

  CaptureSession replacePath(int id, String path) => CaptureSession([
    for (final item in items)
      if (item.id == id && item is PhotoPage) item.withPath(path) else item,
  ]);

  int indexOf(int id) => items.indexWhere((item) => item.id == id);
}
