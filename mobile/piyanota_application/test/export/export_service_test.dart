import 'dart:async';
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

  /// The channel calls that only tell the device something.
  const quiet = {'begin', 'notifyProgress', 'end', 'cancel'};

  /// Calls other than [quiet] ones, in order.
  List<String> steps() => [
    for (final c in calls)
      if (!quiet.contains(c.method)) c.method,
  ];

  MethodChannelExportService service({Dio? dio}) =>
      MethodChannelExportService(dio: dio ?? Dio(), workDir: () async => work);

  final local = Uri.file('/data/tracks/soprano.mp3');
  ExportJob job({List<ExportInput>? inputs}) => ExportJob(
    inputs: inputs ?? [(track: local, gain: 0.5)],
    speed: 0.75,
    fileName: 'Song_Soprano.mp3',
  );

  test('begin, list, then run on the device with a clash-free name', () async {
    mock(
      (call) => switch (call.method) {
        'begin' || 'notifyProgress' => null,
        'listNames' => ['song_soprano.mp3', 'Other.mp3'],
        'run' => {
          'fileName': (call.arguments as Map)['fileName'],
          'location': 'Internal storage/Music',
        },
        _ => throw MissingPluginException(),
      },
    );

    final result = await service().export(
      ExportJob(
        inputs: [(track: local, gain: 0.5)],
        speed: 0.75,
        fileName: 'Song_Soprano.mp3',
        notice: const ExportNoticeText(
          exporting: 'Exporting Song…',
          cancel: 'Cancel',
          saved: 'Saved {file} to {folder}',
          failedTitle: 'Song was not exported',
          failures: {'interrupted': 'Try again.'},
          fallbackFailure: 'Try again.',
        ),
      ),
      'content://tree/x',
    );

    expect(calls.first.method, 'begin');
    expect((calls.first.arguments as Map)['notice'], {
      'exporting': 'Exporting Song…',
      'cancel': 'Cancel',
      'saved': 'Saved {file} to {folder}',
      'failedTitle': 'Song was not exported',
      'failures': {'interrupted': 'Try again.'},
      'fallbackFailure': 'Try again.',
    });
    expect(steps(), ['listNames', 'run']);
    final run = calls.last.arguments as Map;
    expect(run['speed'], 0.75);
    expect(run['inputs'], [
      {'path': local.toFilePath(), 'gain': 0.5},
    ]);
    expect(run['fileName'], 'Song_Soprano (1).mp3');
    expect(run['treeUri'], 'content://tree/x');
    // Local tracks only: the render starts the bar.
    expect(run['from'], 0.0);
    expect(
      (run['renderShare'] as double) + (run['saveShare'] as double),
      closeTo(1.0, 1e-9),
    );
    expect(result.fileName, 'Song_Soprano (1).mp3');
    expect(result.location, 'Internal storage/Music');
    // Handed over: the device ends the notification, not Dart.
    expect(calls.map((c) => c.method), isNot(contains('end')));
    // The work folder is cleaned up.
    expect(work.listSync(), isEmpty);
  });

  test('busy: an earlier export still on the device is StillExporting, '
      'and its work folder is left alone', () async {
    final sep = Platform.pathSeparator;
    final running = Directory('${work.path}${sep}export_bg')..createSync();
    mock((call) => throw PlatformException(code: 'busy'));
    await expectLater(
      service().export(job(), 'content://tree/x'),
      throwsA(isA<StillExporting>()),
    );
    expect(running.existsSync(), isTrue);
    expect(calls.map((c) => c.method), ['begin']);
  });

  test('a failure before the hand-over ends the notification with its '
      'code; a cancel ends it as cancelled', () async {
    mock(
      (call) => switch (call.method) {
        'listNames' => throw PlatformException(code: 'permission_denied'),
        _ => null,
      },
    );
    await expectLater(
      service().export(job(), 'content://tree/x'),
      throwsA(isA<PermissionDenied>()),
    );
    expect(calls.last.method, 'end');
    expect(calls.last.arguments, {
      'outcome': 'failed',
      'code': 'permission_denied',
    });

    calls.clear();
    final token = ExportCancelToken();
    mock((call) {
      if (call.method == 'listNames') {
        token.cancel();
        return <String>[];
      }
      return null;
    });
    await expectLater(
      service().export(job(), 'content://tree/x', cancel: token),
      throwsA(isA<Cancelled>()),
    );
    expect(calls.last.method, 'end');
    expect(calls.last.arguments, {'outcome': 'cancelled'});
    expect(calls.map((c) => c.method), isNot(contains('run')));
  });

  test('the Cancel in the notification cancels the export', () async {
    final token = ExportCancelToken();
    mock((call) async {
      if (call.method == 'listNames') {
        await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .handlePlatformMessage(
              channel.name,
              channel.codec.encodeMethodCall(
                const MethodCall('cancelRequested'),
              ),
              (_) {},
            );
        return <String>[];
      }
      return null;
    });
    await expectLater(
      service().export(job(), 'content://tree/x', cancel: token),
      throwsA(isA<Cancelled>()),
    );
    expect(token.isCancelled, isTrue);
  });

  test('L4: the prepare step (the click) is on the bar before the render '
      'and its input goes last', () async {
    final seen = <double>[];
    mock(
      (call) => switch (call.method) {
        'listNames' => <String>[],
        'run' => {'fileName': 'a.mp3', 'location': 'here'},
        _ => null,
      },
    );
    final click = Uri.file('/data/click.wav');
    await service().export(
      ExportJob(
        inputs: [(track: local, gain: 0.5)],
        prepare: () async => (track: click, gain: 0.3),
        speed: 1,
        fileName: 'a.mp3',
      ),
      'content://tree/x',
      onProgress: seen.add,
    );
    const total =
        ExportProgress.prepareShare +
        ExportProgress.renderShare +
        ExportProgress.saveShare;
    expect(seen.first, 0.0);
    expect(seen, contains(closeTo(ExportProgress.prepareShare / total, 1e-9)));
    final run = calls.lastWhere((c) => c.method == 'run').arguments as Map;
    expect(run['from'], closeTo(ExportProgress.prepareShare / total, 1e-9));
    expect((run['inputs'] as List).last, {
      'path': click.toFilePath(),
      'gain': 0.3,
    });
    // The notification was fed while Dart wrote the click.
    expect(calls.map((c) => c.method), contains('notifyProgress'));
  });

  test('a prepare step that throws is GenerationFailed, or Cancelled '
      'after a Cancel', () async {
    mock((_) => null);
    await expectLater(
      service().export(
        ExportJob(
          inputs: [(track: local, gain: 0.5)],
          prepare: () async => throw const FileSystemException('x'),
          speed: 1,
          fileName: 'a.mp3',
        ),
        'content://tree/x',
      ),
      throwsA(isA<GenerationFailed>()),
    );
    final token = ExportCancelToken();
    await expectLater(
      service().export(
        ExportJob(
          inputs: [(track: local, gain: 0.5)],
          prepare: () async {
            token.cancel();
            throw const FileSystemException('x');
          },
          speed: 1,
          fileName: 'a.mp3',
        ),
        'content://tree/x',
        cancel: token,
      ),
      throwsA(isA<Cancelled>()),
    );
  });

  for (final (code, type) in [
    ('storage_full', StorageFull),
    ('permission_denied', PermissionDenied),
    ('interrupted', Interrupted),
    ('cancelled', Cancelled),
    ('cancelled_partial', Cancelled),
    ('not_local_folder', NotLocalFolder),
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

  group('local-only folders (user decision 2026-10-21)', () {
    for (final tree in [
      'content://com.android.externalstorage.documents/tree/primary%3AMusic',
      'content://com.android.externalstorage.documents/tree/1A2B-3C4D%3A',
      'content://com.android.providers.downloads.documents/tree/downloads',
    ]) {
      test('accepts $tree', () async {
        mock((_) => tree);
        expect(await service().pickFolder(), tree);
      });
    }

    for (final tree in [
      'content://com.google.android.apps.docs.storage/tree/acc%3D1',
      'content://com.android.providers.media.documents/tree/audio',
      'file:///sdcard/Music',
    ]) {
      test('refuses $tree as NotLocalFolder', () async {
        mock((_) => tree);
        await expectLater(
          service().pickFolder(),
          throwsA(isA<NotLocalFolder>()),
        );
      });
    }

    test('the native refusal is NotLocalFolder too', () async {
      mock((_) => throw PlatformException(code: 'not_local_folder'));
      await expectLater(service().pickFolder(), throwsA(isA<NotLocalFolder>()));
    });
  });

  test('a cancelled save that left part of the file says so (L8)', () async {
    mock((call) => throw PlatformException(code: 'cancelled_partial'));
    await expectLater(
      service().export(job(), 'content://tree/x'),
      throwsA(
        isA<Cancelled>().having((c) => c.partialFileLeft, 'partial', isTrue),
      ),
    );
  });

  test(
    'L7: a failing work folder still removes the progress handler',
    () async {
      var handled = 0;
      mock((_) => null);
      final failing = MethodChannelExportService(
        dio: Dio(),
        workDir: () async => throw const FileSystemException('no cache'),
      );
      await expectLater(
        failing.export(job(), 'content://tree/x', onProgress: (_) => handled++),
        throwsA(isA<FileSystemException>()),
      );
      final before = handled;
      await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .handlePlatformMessage(
            channel.name,
            channel.codec.encodeMethodCall(const MethodCall('progress', 0.5)),
            (_) {},
          );
      expect(handled, before, reason: 'handler removed in finally');
    },
  );

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
        'listNames' => <String>[],
        'run' => {'fileName': 'a.mp3', 'location': 'here'},
        _ => null,
      },
    );

    await service().export(job(), 'content://tree/x');
    expect(stale.existsSync(), isFalse);
    expect(other.existsSync(), isTrue);
  });

  group('cancel and progress', () {
    /// What the native side does: sends `progress` back on the channel.
    Future<void> sendProgress(Object? value) =>
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .handlePlatformMessage(
              channel.name,
              channel.codec.encodeMethodCall(MethodCall('progress', value)),
              (_) {},
            );

    Future<void> sendSaveProgress(Object? value) =>
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .handlePlatformMessage(
              channel.name,
              channel.codec.encodeMethodCall(MethodCall('saveProgress', value)),
              (_) {},
            );

    test('render and save progress fill one bar, clamped, never going '
        'back, ending at exactly 1.0', () async {
      final seen = <double>[];
      mock((call) async {
        switch (call.method) {
          case 'listNames':
            return <String>[];
          case 'run':
            for (final v in [0.5, 0.4, 'x', 2.0]) {
              await sendProgress(v);
            }
            for (final v in [0.0, 0.5, 1.0]) {
              await sendSaveProgress(v);
            }
            return {'fileName': 'a.mp3', 'location': 'here'};
        }
        return null;
      });
      await service().export(job(), 'content://tree/x', onProgress: seen.add);
      // Local tracks only: no download share, so render is 0.7 of 0.8 of
      // the bar and save the rest.
      const render = ExportProgress.renderShare;
      const total = render + ExportProgress.saveShare;
      expect(seen.first, 0.0);
      expect(seen[1], closeTo(0.5 * render / total, 1e-9));
      expect(seen[2], closeTo(render / total, 1e-9));
      expect(
        seen[3],
        closeTo((render + 0.5 * ExportProgress.saveShare) / total, 1e-9),
      );
      expect(seen.last, 1.0);
      for (var i = 1; i < seen.length; i++) {
        expect(seen[i], greaterThan(seen[i - 1]));
      }
    });

    test(
      'downloads count too: received bytes, summed over the tracks',
      () async {
        final seen = <double>[];
        mock(
          (call) => switch (call.method) {
            'listNames' => <String>[],
            'run' => {'fileName': 'a.mp3', 'location': 'here'},
            _ => null,
          },
        );
        final dio = Dio()
          ..httpClientAdapter = _StatusAdapter(200, body: 'x' * 100);
        await service(dio: dio).export(
          job(
            inputs: [
              (track: Uri.parse('https://cdn.test/s.mp3'), gain: 1.0),
              (track: Uri.parse('https://cdn.test/a.mp3'), gain: 1.0),
            ],
          ),
          'content://tree/x',
          onProgress: seen.add,
        );
        // After the first of two tracks: half the download share.
        expect(seen, contains(closeTo(ExportProgress.downloadShare / 2, 1e-9)));
        expect(seen, contains(closeTo(ExportProgress.downloadShare, 1e-9)));
        expect(seen.last, 1.0);
        for (var i = 1; i < seen.length; i++) {
          expect(seen[i], greaterThan(seen[i - 1]));
        }
      },
    );

    test('L9: a non-cancel error after Cancel is still Cancelled', () async {
      final token = ExportCancelToken();
      mock((call) {
        if (call.method == 'run') {
          token.cancel();
          throw PlatformException(code: 'generation_failed');
        }
        return call.method == 'listNames' ? <String>[] : null;
      });
      await expectLater(
        service().export(job(), 'content://tree/x', cancel: token),
        throwsA(isA<Cancelled>()),
      );
    });

    test('Cancel during the render tells the native side, ends in '
        'Cancelled, saves nothing and removes the temp files', () async {
      final token = ExportCancelToken();
      final stopped = Completer<void>();
      mock((call) async {
        switch (call.method) {
          case 'listNames':
            return <String>[];
          case 'run':
            token.cancel();
            await stopped.future;
            throw PlatformException(code: 'cancelled');
          case 'cancel':
            stopped.complete();
            return null;
        }
        return null;
      });
      await expectLater(
        service().export(job(), 'content://tree/x', cancel: token),
        throwsA(isA<Cancelled>()),
      );
      expect(steps(), ['listNames', 'run']);
      expect(calls.map((c) => c.method), contains('cancel'));
      // Handed over: the device ends its own notification.
      expect(calls.map((c) => c.method), isNot(contains('end')));
      expect(work.listSync(), isEmpty);
    });

    test('a token cancelled before the export starts nothing', () async {
      mock((_) => null);
      final token = ExportCancelToken()..cancel();
      await expectLater(
        service().export(job(), 'content://tree/x', cancel: token),
        throwsA(isA<Cancelled>()),
      );
      expect(calls, isEmpty);
      expect(work.listSync(), isEmpty);
    });

    test('Cancel before the hand-over never starts the render', () async {
      final token = ExportCancelToken();
      mock((call) {
        if (call.method == 'listNames') {
          token.cancel();
          return <String>[];
        }
        return null;
      });
      await expectLater(
        service().export(job(), 'content://tree/x', cancel: token),
        throwsA(isA<Cancelled>()),
      );
      expect(calls.map((c) => c.method), isNot(contains('run')));
      expect(work.listSync(), isEmpty);
    });

    test('a Cancel after the file is saved changes nothing', () async {
      final token = ExportCancelToken();
      mock(
        (call) => switch (call.method) {
          'listNames' => <String>[],
          'run' => {'fileName': 'a.mp3', 'location': 'here'},
          _ => null,
        },
      );
      final result = await service().export(
        job(),
        'content://tree/x',
        cancel: token,
      );
      token.cancel();
      await Future<void>.delayed(Duration.zero);
      expect(result.fileName, 'a.mp3');
      expect(calls.map((c) => c.method), isNot(contains('cancel')));
    });

    test('ExportProgress ignores bad and backward values', () {
      final seen = <double>[];
      const render = ExportPhase.render;
      final progress = ExportProgress(seen.add, downloads: false)
        ..report(render, -1)
        ..report(render, double.nan)
        ..report(render, null)
        ..report(render, 0.3)
        ..report(render, 0.3)
        ..report(render, 0.2)
        ..report(ExportPhase.download, 1)
        ..report(render, 7);
      const share =
          ExportProgress.renderShare /
          (ExportProgress.renderShare + ExportProgress.saveShare);
      expect(seen, [0.0, closeTo(0.3 * share, 1e-9), closeTo(share, 1e-9)]);
      progress.finish();
      expect(progress.value, 1.0);
    });

    test('ExportProgress phases run download, render, save', () {
      final seen = <double>[];
      ExportProgress(seen.add)
        ..report(ExportPhase.download, 1)
        ..report(ExportPhase.render, 1)
        ..report(ExportPhase.save, 0.5)
        ..finish();
      expect(seen, [
        closeTo(ExportProgress.downloadShare, 1e-9),
        closeTo(
          ExportProgress.downloadShare + ExportProgress.renderShare,
          1e-9,
        ),
        closeTo(1 - ExportProgress.saveShare / 2, 1e-9),
        1.0,
      ]);
    });
  });

  group('isLocalFolder matches the authority exactly, as Android does', () {
    for (final tree in [
      'content://COM.ANDROID.EXTERNALSTORAGE.DOCUMENTS/tree/primary%3AMusic',
      'content://user@com.android.externalstorage.documents/tree/x',
      'content://com.android.externalstorage.documents:80/tree/x',
      'CONTENT://com.android.externalstorage.documents/tree/x',
      'content://com.android.externalstorage.documents.evil/tree/x',
      'content://',
    ]) {
      test('refuses $tree', () => expect(isLocalFolder(tree), isFalse));
    }
    test('accepts the bare authority and one with a query', () {
      expect(
        isLocalFolder('content://com.android.externalstorage.documents'),
        isTrue,
      );
      expect(
        isLocalFolder('content://com.android.providers.downloads.documents?x'),
        isTrue,
      );
    });
  });

  test('pickFolder sends the folders to keep, and gives back a refused '
      'one', () async {
    const drive = 'content://com.google.android.apps.docs.storage/tree/a';
    mock((call) => call.method == 'pickFolder' ? drive : null);
    await expectLater(
      service().pickFolder(keep: {'content://keep/1'}),
      throwsA(isA<NotLocalFolder>()),
    );
    expect(calls.first.arguments, {
      'keep': ['content://keep/1'],
    });
    expect(calls.last.method, 'releaseFolder');
    expect(calls.last.arguments, {'treeUri': drive});
  });

  test('stopAll never throws', () async {
    mock((_) => throw PlatformException(code: 'x'));
    await service().stopAll();
    expect(calls.single.method, 'stopAll');
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
      test('a $type download is $failure, before the device renders', () async {
        mock((_) => null);
        await expectLater(
          service(dio: failingDio(type))
              .export(job(inputs: remote), 'content://tree/x'),
          throwsA(
            isA<ExportFailure>().having((e) => e.runtimeType, 'type', failure),
          ),
        );
        expect(steps(), isEmpty);
        expect(calls.last.method, 'end');
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
        expect(steps(), isEmpty);
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
      expect(steps(), isEmpty);
    });
  });
}

/// Answers every request with [status] and an empty body, as a server
/// would; Dio turns a 4xx into a badResponse itself.
class _StatusAdapter implements HttpClientAdapter {
  _StatusAdapter(this.status, {this.body = ''});

  final int status;
  final String body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => ResponseBody.fromString(
    body,
    status,
    headers: {
      Headers.contentLengthHeader: ['${body.length}'],
    },
  );

  @override
  void close({bool force = false}) {}
}
