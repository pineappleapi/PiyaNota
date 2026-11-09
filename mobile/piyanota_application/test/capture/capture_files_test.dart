import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/capture_page.dart';
import 'package:piyanota_application/models/capture_session.dart';
import 'package:piyanota_application/services/capture/capture_files.dart';

PhotoPage _photo(int id, [String? path]) =>
    PhotoPage(id: id, path: path ?? 'p$id.jpg', source: PageSource.camera);

void main() {
  group('CaptureFileLedger', () {
    late List<String> deleted;
    late CaptureFileLedger ledger;

    setUp(() {
      deleted = [];
      ledger = CaptureFileLedger(deleted.add);
    });

    test('a removed page is kept while Undo is offered, then deleted', () {
      final session = CaptureSession([_photo(1), _photo(2)]);
      ledger
        ..own('p1.jpg')
        ..own('p2.jpg');
      final removed = session.remove(2);
      ledger.sweep(removed, keep: ['p2.jpg']);
      expect(deleted, isEmpty);
      ledger.sweep(removed);
      expect(deleted, ['p2.jpg']);
      expect(ledger.owned, {'p1.jpg'});
    });

    test('an edit deletes the pre-edit file only', () {
      final session = CaptureSession([_photo(1)]);
      ledger.own('p1.jpg');
      ledger.own('p1-edit.jpg');
      ledger.sweep(session.replacePath(1, 'p1-edit.jpg'));
      expect(deleted, ['p1.jpg']);
    });

    test('a PDF replacing photos deletes the photos', () {
      final session = CaptureSession([_photo(1), _photo(2)]);
      ledger
        ..own('p1.jpg')
        ..own('p2.jpg')
        ..own('score.pdf');
      ledger.sweep(
        session.withPdf(
          const PdfDocument(id: 3, path: 'score.pdf', name: 's', pages: 2),
        ),
      );
      expect(deleted, unorderedEquals(['p1.jpg', 'p2.jpg']));
      expect(ledger.owned, {'score.pdf'});
    });

    test('photos replacing a PDF delete the PDF', () {
      const pdf = PdfDocument(id: 1, path: 'score.pdf', name: 's', pages: 2);
      final session = CaptureSession([pdf]);
      ledger
        ..own('score.pdf')
        ..own('p2.jpg');
      ledger.sweep(session.withoutAll().addPhotos([_photo(2)]));
      expect(deleted, ['score.pdf']);
    });

    test('files it does not own are never deleted', () {
      ledger.sweep(CaptureSession([_photo(1)]));
      ledger.sweep(const CaptureSession());
      expect(deleted, isEmpty);
    });

    test('deleteAll empties it, and a second call deletes nothing', () {
      ledger
        ..own('a')
        ..own('b');
      ledger.deleteAll();
      ledger.deleteAll();
      expect(deleted, unorderedEquals(['a', 'b']));
      expect(ledger.owned, isEmpty);
    });
  });

  group('DiskCaptureFileStore', () {
    late Directory dir;

    setUp(() => dir = Directory.systemTemp.createTempSync('piya206_files'));
    tearDown(() {
      if (dir.existsSync()) dir.deleteSync(recursive: true);
    });

    test('clearStale deletes only files older than the cut-off', () async {
      final old = File('${dir.path}/old.jpg')..writeAsBytesSync([1]);
      old.setLastModifiedSync(DateTime(2020));
      final fresh = File('${dir.path}/fresh.jpg')..writeAsBytesSync([2]);
      await DiskCaptureFileStore(() async => dir)
          .clearStale(DateTime.now().subtract(const Duration(hours: 1)));
      expect(old.existsSync(), isFalse);
      expect(fresh.existsSync(), isTrue);
    });

    test('deleting a missing file or folder never throws', () async {
      final store = DiskCaptureFileStore(
        () async => Directory('${dir.path}/missing'),
      );
      await store.delete('${dir.path}/nope.jpg');
      await store.clearStale(DateTime.now());
    });
  });
}
