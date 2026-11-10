import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/capture/page_picker.dart';

class _Inner implements PagePicker {
  _Inner(this.log);
  final List<String> log;
  Object? error;

  @override
  Future<List<String>> pickGalleryImages() async {
    log.add('gallery');
    if (error != null) throw error!;
    return ['a.jpg'];
  }

  @override
  Future<PickedPdf?> pickPdf() async {
    log.add('pdf');
    if (error != null) throw error!;
    return null;
  }
}

void main() {
  test('the picker is flagged open for exactly as long as it is shown, '
      'including when it throws', () async {
    final log = <String>[];
    final inner = _Inner(log);
    final picker = SignalingPagePicker(inner, (open) async {
      log.add(open ? 'open' : 'closed');
    });

    expect(await picker.pickGalleryImages(), ['a.jpg']);
    expect(await picker.pickPdf(), isNull);
    expect(log, ['open', 'gallery', 'closed', 'open', 'pdf', 'closed']);

    log.clear();
    inner.error = const NotAPdfException();
    await expectLater(picker.pickPdf(), throwsA(isA<NotAPdfException>()));
    expect(log, ['open', 'pdf', 'closed']);
  });
}
