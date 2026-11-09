import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/capture_page.dart';
import 'package:piyanota_application/models/capture_session.dart';
import 'package:piyanota_application/screens/capture/capture_messages.dart';
import 'package:piyanota_application/services/capture/device_channel.dart';
import 'package:piyanota_application/services/capture/page_picker.dart';
import 'package:piyanota_application/services/score_upload_api.dart';

PhotoPage _photo(int id) =>
    PhotoPage(id: id, path: 'p$id.jpg', source: PageSource.camera);

List<int> _ids(CaptureSession s) => [for (final i in s.items) i.id];

void main() {
  group('CaptureSession', () {
    test('reorder follows the "index before removal" convention', () {
      final s = CaptureSession([_photo(1), _photo(2), _photo(3)]);
      expect(_ids(s.reorder(0, 3)), [2, 3, 1], reason: 'first to last');
      expect(_ids(s.reorder(2, 0)), [3, 1, 2], reason: 'last to first');
      expect(_ids(s.reorder(0, 2)), [2, 1, 3], reason: 'one step right');
    });

    test('remove then insert puts the page back where it was (Undo)', () {
      final s = CaptureSession([_photo(1), _photo(2), _photo(3)]);
      final removed = s.remove(2);
      expect(_ids(removed), [1, 3]);
      expect(_ids(removed.insert(1, _photo(2))), [1, 2, 3]);
      expect(_ids(removed.insert(99, _photo(2))), [1, 3, 2]);
    });

    test('addPhotos keeps only what fits under 20 pages (AC6)', () {
      final s = const CaptureSession().addPhotos([
        for (var i = 0; i < 25; i++) _photo(i),
      ]);
      expect(s.pageCount, CaptureSession.maxPages);
      expect(s.photoRoom, 0);
    });

    test('a PDF replaces everything and leaves no photo room', () {
      final s = CaptureSession([_photo(1)]).withPdf(
        const PdfDocument(id: 9, path: 'x.pdf', name: 'x.pdf', pages: 7),
      );
      expect(_ids(s), [9]);
      expect(s.pageCount, 7);
      expect(s.photoRoom, 0);
      expect(s.inputKind, PageSource.pdf);
    });

    test('photos choose PIYA-101, empty chooses nothing (AC8)', () {
      expect(const CaptureSession().inputKind, isNull);
      expect(CaptureSession([_photo(1)]).inputKind, PageSource.camera);
    });

    test('replacePath swaps the file but keeps id and order', () {
      final s = CaptureSession([_photo(1), _photo(2)]).replacePath(2, 'new');
      expect(_ids(s), [1, 2]);
      expect(s.items[1].path, 'new');
    });
  });

  group('looksLikePdf (AC7)', () {
    test('accepts the %PDF- signature, even after a little junk', () {
      expect(looksLikePdf('%PDF-1.7\n'.codeUnits), isTrue);
      expect(looksLikePdf([0, 0, 0, ...'%PDF-1.4'.codeUnits]), isTrue);
    });

    test('rejects images, text and empty files renamed to .pdf', () {
      expect(looksLikePdf([0xFF, 0xD8, 0xFF, 0xE0]), isFalse);
      expect(looksLikePdf('hello world'.codeUnits), isFalse);
      expect(looksLikePdf(const []), isFalse);
      expect(looksLikePdf('%PDF'.codeUnits), isFalse);
    });

    test('ignores a signature beyond the first kilobyte', () {
      expect(
        looksLikePdf([...List.filled(1100, 0), ...'%PDF-'.codeUnits]),
        isFalse,
      );
    });
  });

  group('CaptureMessages', () {
    test('page counts read naturally', () {
      expect(CaptureMessages.createScoreWith(1), 'Create score · 1 page');
      expect(CaptureMessages.createScoreWith(3), 'Create score · 3 pages');
      expect(CaptureMessages.discardTitle(2), 'Discard 2 pages?');
    });

    test('PDF limit message names the real page count', () {
      expect(CaptureMessages.pdfTooLong(31), contains('31 pages'));
      expect(CaptureMessages.pdfTooLong(31), contains('up to 20'));
    });

    test('server page indexes are shown counting from 1', () {
      final text = CaptureMessages.uploadError(
        const UploadRejectedException(
          statusCode: 415,
          code: 'unsupported_file_type',
          pageIndex: 0,
        ),
      );
      expect(text, startsWith('Page 1 '));
    });

    test('waits are worded, never raw seconds counts in the thousands', () {
      String wait(int s) => CaptureMessages.uploadError(
        UploadRejectedException(
          statusCode: 429,
          code: 'queue_full',
          retryAfter: Duration(seconds: s),
        ),
      );
      expect(wait(30), contains('30 seconds'));
      expect(wait(60), contains('1 minute'));
      expect(wait(150), contains('3 minutes'));
      expect(
        CaptureMessages.uploadError(
          const UploadRejectedException(statusCode: 429, code: 'rate_limited'),
        ),
        contains('a few minutes'),
      );
    });

    test('unknown codes fall back to plain words, not the code', () {
      final text = CaptureMessages.uploadError(
        const UploadRejectedException(statusCode: 500, code: 'kaboom_42'),
      );
      expect(text, CaptureMessages.generic);
      expect(text, isNot(contains('kaboom')));
    });

    test('session, network and PDF problems each have their own wording', () {
      expect(
        {
          CaptureMessages.uploadError(const UploadSessionExpiredException()),
          CaptureMessages.uploadError(const UploadNetworkException()),
          CaptureMessages.pdfProblem(PdfProblem.encrypted),
          CaptureMessages.pdfProblem(PdfProblem.corrupt),
          CaptureMessages.generic,
        }.length,
        5,
      );
    });
  });
}
