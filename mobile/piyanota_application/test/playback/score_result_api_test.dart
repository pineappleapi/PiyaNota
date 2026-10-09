import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/demo/playback_demo.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_processing_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_result_api.dart';
import 'package:piyanota_application/services/score_result_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

/// The demo is written here instead of the cache dir (no path_provider
/// plugin in unit tests).
late Directory _demoDir;

class _Fakes {
  _Fakes() {
    storage = SessionStorage(FaultySecureStorage());
    library = FakeScoreLibraryApi(
      sessionStorage: storage,
      accountForToken: auth.accountForToken,
      latency: Duration.zero,
    );
    processing = FakeProcessingApi(
      sessionStorage: storage,
      accountForToken: auth.accountForToken,
      library: library,
      latency: Duration.zero,
    );
    api = FakeScoreResultApi(
      sessionStorage: storage,
      accountForToken: auth.accountForToken,
      library: library,
      processing: processing,
      demoFiles: () => PlaybackDemo.writeTo(_demoDir),
      latency: Duration.zero,
    );
  }

  final auth = FakeAuthApi(latency: Duration.zero);
  late final SessionStorage storage;
  late final FakeScoreLibraryApi library;
  late final FakeProcessingApi processing;
  late final FakeScoreResultApi api;

  Future<void> signIn(String email) async {
    if (email == FakeAuthApi.demoEmail) {
      await storage.save(
        await auth.login(email: email, password: FakeAuthApi.demoPassword),
      );
      return;
    }
    await storage.save(
      await auth.signUp(
        email: email,
        password: 'secret123',
        passwordConfirmation: 'secret123',
      ),
    );
  }
}

/// One canned response for every request; records the last one.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter({this.status = 200, this.body, this.text});

  final int status;
  final Object? body;
  final String? text;
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastRequest = options;
    return ResponseBody.fromString(
      text ?? jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [
          text != null ? 'text/plain' : Headers.jsonContentType,
        ],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

HttpScoreResultApi _http(_StubAdapter adapter) => HttpScoreResultApi(
  Dio(BaseOptions(baseUrl: 'https://api.test'))..httpClientAdapter = adapter,
  SessionStorage(FaultySecureStorage({'session_token': 'sess_t'})),
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    _demoDir = Directory(
      '${(await Directory.systemTemp.createTemp('piyanota_demo')).path}/demo',
    );
  });
  tearDownAll(() async {
    await _demoDir.parent.delete(recursive: true);
  });

  group('FakeScoreResultApi', () {
    test(
      'a demo score plays the generated demo through the real parser',
      () async {
        final f = _Fakes();
        await f.signIn(FakeAuthApi.demoEmail);
        final result = await f.api.fetchResult(101);
        expect(result.scoreId, 101);
        expect(result.audioTracks.keys.toSet(), {...VoicePart.values});
        for (final uri in [
          ...result.audioTracks.values,
          ...result.scoreImages.nonNulls,
          result.timingMetadataUrl!,
        ]) {
          expect(uri.scheme, 'file');
          expect(
            File.fromUri(uri).parent.path,
            File.fromUri(Uri.file('${_demoDir.path}/x')).parent.path,
          );
          expect(File.fromUri(uri).existsSync(), isTrue, reason: '$uri');
        }
        expect(
          result.audioTracks[VoicePart.soprano]!.pathSegments.last,
          'soprano.wav',
        );
        expect(result.review.reviewNeeded, isTrue);
        expect(result.arranger, 'Robert Delgado');
        expect(result.tempoBpm, PlaybackDemo.bpm);
        expect(
          result.pageSizeAt(0),
          const Size(
            PlaybackDemo.pageWidth + 0.0,
            PlaybackDemo.pageHeight + 0.0,
          ),
        );

        final timing = await f.api.fetchTiming(result.timingMetadataUrl!);
        final events = timing.events;
        expect(events, isNotEmpty);
        expect(timing.bars, hasLength(PlaybackDemo.barCount));
        for (final event in events) {
          expect(event.pageIndex, 0);
          expect(event.x, lessThan(PlaybackDemo.pageWidth));
          expect(event.y, lessThan(PlaybackDemo.pageHeight));
        }
        expect(events.map((e) => e.voice).toSet(), {...VoicePart.values});
        expect(events, hasLength(PlaybackDemo.notes().length));

        // Every demo score has the muted Bass measure; none failed.
        expect(result.mutedMeasures.single.voice, VoicePart.bass);
        expect(result.mutedMeasures.single.bar, PlaybackDemo.mutedBar);
        expect(result.failedVoices, isEmpty);

        // Generated once: a second fetch reuses the same files.
        final page = File.fromUri(result.scoreImages.single!);
        final written = page.lastModifiedSync();
        final again = await f.api.fetchResult(101);
        expect(again.scoreImages.single, result.scoreImages.single);
        expect(page.lastModifiedSync(), written);
      },
    );

    test('score 102 comes back with the Tenor failed on the server', () async {
      final f = _Fakes();
      await f.signIn(FakeAuthApi.demoEmail);
      final result = await f.api.fetchResult(
        FakeScoreResultApi.failedOnServerScoreId,
      );
      expect(result.declaredFailedVoices, {VoicePart.tenor});
      expect(result.failedVoices, {VoicePart.tenor});
      expect(result.audioTracks.keys, isNot(contains(VoicePart.tenor)));
      expect(result.review.reasons, contains('voice_failed'));
      final timing = await f.api.fetchTiming(result.timingMetadataUrl!);
      expect(timing.events.where((e) => e.voice == VoicePart.tenor), isEmpty);
      expect(timing.bars, hasLength(PlaybackDemo.barCount));
    });

    test('score 103 has an Alto file that is not there', () async {
      final f = _Fakes();
      await f.signIn(FakeAuthApi.demoEmail);
      final result = await f.api.fetchResult(
        FakeScoreResultApi.failsOnDeviceScoreId,
      );
      expect(result.failedVoices, isEmpty);
      expect(result.audioTracks.keys.toSet(), {...VoicePart.values});
      expect(
        File.fromUri(result.audioTracks[VoicePart.alto]!).existsSync(),
        isFalse,
      );
      expect(
        File.fromUri(result.audioTracks[VoicePart.bass]!).existsSync(),
        isTrue,
      );
    });

    test('a timing URL outside the demo is a 404', () async {
      final f = _Fakes();
      await expectLater(
        f.api.fetchTiming(Uri.parse('https://example.com/timing.json')),
        throwsA(isA<ScoreResultNotFoundException>()),
      );
      await expectLater(
        f.api.fetchTiming(Uri.file('${_demoDir.path}/missing.json')),
        throwsA(isA<ScoreResultNotFoundException>()),
      );
    });

    test('a score the account does not have is a 404', () async {
      final f = _Fakes();
      await f.signIn('new@example.com');
      await expectLater(
        f.api.fetchResult(101),
        throwsA(isA<ScoreResultNotFoundException>()),
      );
    });

    test('a score whose job has not completed is a 409', () async {
      final f = _Fakes();
      await f.signIn(FakeAuthApi.demoEmail);
      f.processing.registerJob(
        jobId: 'job-x',
        account: FakeAuthApi.demoEmail,
        scoreId: 101,
        pageCount: 3,
      );
      await expectLater(
        f.api.fetchResult(101),
        throwsA(isA<ScoreResultNotReadyException>()),
      );
      // Other scores are unaffected.
      expect((await f.api.fetchResult(102)).scoreId, 102);
    });

    test('flaky accounts fail every odd fetch', () async {
      final f = _Fakes();
      await f.signIn('choir${FakeScoreLibraryApi.flakyDomain}');
      await expectLater(
        f.api.fetchResult(101),
        throwsA(isA<ScoreResultServerException>()),
      );
      expect((await f.api.fetchResult(101)).scoreId, 101);
      await expectLater(
        f.api.fetchResult(101),
        throwsA(isA<ScoreResultServerException>()),
      );
    });

    test('no session is a 401', () async {
      final f = _Fakes();
      await expectLater(
        f.api.fetchResult(101),
        throwsA(isA<ScoreResultSessionExpiredException>()),
      );
    });
  });

  group('HttpScoreResultApi', () {
    const okBody = {
      'success': true,
      'status': 200,
      'data': {
        'jobId': 'j1',
        'scoreId': 7,
        'audioTracks': {
          'Soprano': 'https://cdn.test/s.mp3',
          'bass': 'https://cdn.test/b.mp3',
        },
        'scoreImages': ['https://cdn.test/p1.png'],
        'timingMetadataUrl': 'https://cdn.test/timing.json',
        'review': {'reviewNeeded': false, 'reasons': <String>[]},
      },
    };

    test('sends the bearer token to the result path and parses it', () async {
      final adapter = _StubAdapter(body: okBody);
      final result = await _http(adapter).fetchResult(7);
      expect(adapter.lastRequest!.path, '/api/scores/7/result');
      expect(adapter.lastRequest!.headers['Authorization'], 'Bearer sess_t');
      expect(result.audioTracks.keys, {VoicePart.soprano, VoicePart.bass});
      expect(result.review.reviewNeeded, isFalse);
    });

    for (final (status, matcher) in [
      (401, isA<ScoreResultSessionExpiredException>()),
      (404, isA<ScoreResultNotFoundException>()),
      (409, isA<ScoreResultNotReadyException>()),
      (500, isA<ScoreResultServerException>()),
    ]) {
      test('$status maps to its own error', () async {
        final adapter = _StubAdapter(status: status, body: {'success': false});
        await expectLater(_http(adapter).fetchResult(7), throwsA(matcher));
      });
    }

    test('a body without audio tracks is a server error', () async {
      final adapter = _StubAdapter(
        body: {
          'data': {'scoreId': 7, 'audioTracks': <String, String>{}},
        },
      );
      await expectLater(
        _http(adapter).fetchResult(7),
        throwsA(isA<ScoreResultServerException>()),
      );
    });

    test('timing served as text is parsed, without the bearer token', () async {
      final adapter = _StubAdapter(
        text: jsonEncode({
          'events': [
            {'timestampMs': 0, 'pageIndex': 0, 'x': 1, 'y': 2, 'voice': 'ALTO'},
          ],
        }),
      );
      final timing = await _http(adapter)
          .fetchTiming(Uri.parse('https://cdn.test/timing.json'));
      expect(timing.events.single.voice, VoicePart.alto);
      expect(timing.bars, isEmpty);
      expect(adapter.lastRequest!.headers['Authorization'], isNull);
    });
  });
}
