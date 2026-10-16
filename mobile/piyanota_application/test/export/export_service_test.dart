import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/export_service.dart';

/// PIYA-211: the Dart side of `piyanota/export`. The channel is mocked, so
/// these check the call sequence and the error-code mapping (AC18), not
/// the audio, which needs a device.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('piyanota/export');
  late Directory work;
  late List<MethodCall> calls;

  setUp(() async {
    work = await Directory.systemTemp.createTemp('export_test_');
    calls = [];
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    if (work.existsSync()) await work.delete(recursive: true);
  });

  void mock(Object? Function(MethodCall call) handler) =>
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            calls.add(call);
            return handler(call);
          });

  MethodChannelExportService service({Dio? dio}) =>
      MethodChannelExportService(dio: dio ?? Dio(), workDir: () async => work);

  final local = Uri.file('/data/tracks/soprano.mp3');
  ExportJob job({List<ExportInput>? inputs}) => ExportJob(
    inputs: inputs ?? [(track: local, gain: 0.5)],
    speed: 0.75,
    fileName: 'Song_Soprano.mp3',
  );

  test('render, list, save in order with a clash-free name', () async {
    mock(
      (call) => switch (call.method) {
        'render' => null,
        'listNames' => ['song_soprano.mp3', 'Other.mp3'],
        'save' => {
          'fileName': (call.arguments as Map)['fileName'],
          'location': 'Internal storage/Music',
        },
        _ => throw MissingPluginException(),
      },
    );

    final result = await service().export(job(), 'content://tree/x');

    expect(calls.map((c) => c.method), ['render', 'listNames', 'save']);
    final render = calls[0].arguments as Map;
    expect(render['speed'], 0.75);
    expect(render['inputs'], [
      {'path': local.toFilePath(), 'gain': 0.5},
    ]);
    expect(result.fileName, 'Song_Soprano (1).mp3');
    expect(result.location, 'Internal storage/Music');
    expect((calls[2].arguments as Map)['srcPath'], render['outPath']);
    // The work folder is cleaned up.
    expect(work.listSync(), isEmpty);
  });

  for (final (code, type) in [
    ('storage_full', StorageFull),
    ('permission_denied', PermissionDenied),
    ('interrupted', Interrupted),
    ('generation_failed', GenerationFailed),
    ('bad_args', GenerationFailed),
  ]) {
    test('$code maps to $type, and temp files are removed', () async {
      mock((call) => throw PlatformException(code: code));
      await expectLater(
        service().export(job(), 'content://tree/x'),
        throwsA(
          isA<ExportFailure>().having((e) => e.runtimeType, 'type', type),
        ),
      );
      expect(work.listSync(), isEmpty);
    });
  }

  test('no channel at all is GenerationFailed', () async {
    await expectLater(
      service().export(job(), 'content://tree/x'),
      throwsA(isA<GenerationFailed>()),
    );
  });

  test('pickFolder: a cancel is null, a refusal is PermissionDenied', () async {
    mock((_) => null);
    expect(await service().pickFolder(), isNull);
    mock((_) => throw PlatformException(code: 'permission_denied'));
    await expectLater(service().pickFolder(), throwsA(isA<PermissionDenied>()));
  });

  test('pickFolder: no picker app on the phone is NoFolderPicker', () async {
    mock((_) => throw PlatformException(code: 'no_folder_picker'));
    await expectLater(service().pickFolder(), throwsA(isA<NoFolderPicker>()));
  });

  test('L5: export folders a killed run left behind are cleared first, '
      'and nothing else in the cache is touched', () async {
    final sep = Platform.pathSeparator;
    final stale = Directory('${work.path}${sep}export_old')..createSync();
    File('${stale.path}${sep}export.mp3').writeAsStringSync('x');
    final other = Directory('${work.path}${sep}playback_demo')..createSync();
    mock(
      (call) => switch (call.method) {
        'render' => null,
        'listNames' => <String>[],
        'save' => {'fileName': 'a.mp3', 'location': 'here'},
        _ => throw MissingPluginException(),
      },
    );

    await service().export(job(), 'content://tree/x');
    expect(stale.existsSync(), isFalse);
    expect(other.existsSync(), isTrue);
  });

  test('openFolder: false on an error instead of throwing', () async {
    mock((_) => true);
    expect(await service().openFolder('content://tree/x'), isTrue);
    mock((_) => throw PlatformException(code: 'no_app'));
    expect(await service().openFolder('content://tree/x'), isFalse);
  });

  group('remote tracks', () {
    Dio failingDio(DioExceptionType type, {Object? error}) {
      final dio = Dio();
      dio.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) => handler.reject(
            DioException(requestOptions: options, type: type, error: error),
          ),
        ),
      );
      return dio;
    }

    final remote = [(track: Uri.parse('https://cdn.test/alto.mp3'), gain: 1.0)];

    for (final (type, failure) in [
      (DioExceptionType.connectionError, Interrupted),
      (DioExceptionType.receiveTimeout, Interrupted),
    ]) {
      test('a $type download is $failure, before any native call', () async {
        mock((_) => null);
        await expectLater(
          service(dio: failingDio(type))
              .export(job(inputs: remote), 'content://tree/x'),
          throwsA(
            isA<ExportFailure>().having((e) => e.runtimeType, 'type', failure),
          ),
        );
        expect(calls, isEmpty);
      });
    }

    test(
      'a 404 is GenerationFailed: retrying the same URL will not help',
      () async {
        mock((_) => null);
        final dio = Dio()..httpClientAdapter = _StatusAdapter(404);
        await expectLater(
          service(dio: dio).export(job(inputs: remote), 'content://tree/x'),
          throwsA(isA<GenerationFailed>()),
        );
        expect(calls, isEmpty);
      },
    );

    test('a full disk while downloading is StorageFull', () async {
      mock((_) => null);
      const full = FileSystemException(
        'write failed',
        'track_0',
        OSError('No space left on device', 28),
      );
      await expectLater(
        service(dio: failingDio(DioExceptionType.unknown, error: full))
            .export(job(inputs: remote), 'content://tree/x'),
        throwsA(isA<StorageFull>()),
      );
    });

    test('an unknown scheme is GenerationFailed', () async {
      mock((_) => null);
      await expectLater(
        service().export(
          job(inputs: [(track: Uri.parse('content://x/y'), gain: 1.0)]),
          'content://tree/x',
        ),
        throwsA(isA<GenerationFailed>()),
      );
      expect(calls, isEmpty);
    });
  });
}

/// Answers every request with [status] and an empty body, as a server
/// would; Dio turns a 4xx into a badResponse itself.
class _StatusAdapter implements HttpClientAdapter {
  _StatusAdapter(this.status);

  final int status;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => ResponseBody.fromString('', status);

  @override
  void close({bool force = false}) {}
}
