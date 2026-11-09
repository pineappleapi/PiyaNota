import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/services/thumbnail_cache.dart';

void main() {
  late Directory dir;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('thumb_cache_test');
    ThumbnailCache.directoryProvider = () async => dir;
  });

  tearDown(() {
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  });

  test('cached is null before a thumbnail is saved', () async {
    expect(await ThumbnailCache.cached('7'), isNull);
  });

  test('fetch saves the image bytes and cached then returns them', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((req) {
      req.response
        ..add([1, 2, 3, 4])
        ..close();
    });

    await ThumbnailCache.fetch('7', 'http://127.0.0.1:${server.port}/t.png');

    final file = await ThumbnailCache.cached('7');
    expect(file, isNotNull);
    expect(await file!.readAsBytes(), [1, 2, 3, 4]);
  });

  test('a failed download leaves nothing cached', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    server.listen((req) {
      req.response
        ..statusCode = 403
        ..close();
    });

    await ThumbnailCache.fetch('7', 'http://127.0.0.1:${server.port}/t.png');

    expect(await ThumbnailCache.cached('7'), isNull);
  });

  test('clearAll removes saved thumbnails', () async {
    File('${dir.path}/7').writeAsBytesSync([9]);
    expect(await ThumbnailCache.cached('7'), isNotNull);

    await ThumbnailCache.clearAll();

    expect(await ThumbnailCache.cached('7'), isNull);
  });
}
