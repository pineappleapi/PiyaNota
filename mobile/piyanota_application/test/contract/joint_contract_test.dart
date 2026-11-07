// Joint backend/frontend contract (v2-checks joint-contract.md, J1-J8): the
// real HTTP clients parse the contract JSON into typed fields, and the fakes
// answer with the same typed shapes. The backend half asserts the same JSON
// on the real app.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/processing_status.dart';
import 'package:piyanota_application/models/score_details.dart';
import 'package:piyanota_application/models/score_result.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_processing_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/fake_score_upload_api.dart';
import 'package:piyanota_application/services/local_results_store.dart';
import 'package:piyanota_application/services/score_upload_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

/// One canned response for every request.
class _Stub implements HttpClientAdapter {
  _Stub(this.status, this.body, {this.headers = const {}});

  final int status;
  final Object? body;
  final Map<String, String> headers;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => ResponseBody.fromString(
    jsonEncode(body),
    status,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      for (final e in headers.entries) e.key: [e.value],
    },
  );

  @override
  void close({bool force = false}) {}
}

class _NoDownloader implements FileDownloader {
  @override
  Future<void> download(Uri url, String savePath) async {}
}

HttpAuthApi _http(int status, Object? body, {Map<String, String>? headers}) =>
    HttpAuthApi(
      Dio(BaseOptions(baseUrl: 'https://api.test'))
        ..httpClientAdapter = _Stub(status, body, headers: headers ?? {}),
    );

Map<String, Object?> _err(
  String code, [
  Map<String, Object?> extra = const {},
]) => {
  'success': false,
  'error': {'code': code, ...extra},
};

Future<Object> _thrown(Future<void> Function() call) async {
  try {
    await call();
  } on Object catch (e) {
    return e;
  }
  fail('did not throw');
}

Future<Object> _loginFails(HttpAuthApi api) =>
    _thrown(() => api.login(email: 'a@b.co', password: 'x'));

class _Clock {
  DateTime now = DateTime(2026, 11, 6, 9);
}

/// Fake library, jobs and upload wired as the providers do.
class _Fakes {
  _Fakes(this.account, {this.clock}) {
    final session = SessionStorage(
      FaultySecureStorage({'session_token': account}),
    );
    String? lookup(String t) => t;
    library = FakeScoreLibraryApi(
      sessionStorage: session,
      accountForToken: lookup,
      latency: Duration.zero,
    );
    jobs = FakeProcessingApi(
      sessionStorage: session,
      accountForToken: lookup,
      library: library,
      latency: Duration.zero,
      clock: clock == null ? null : () => clock!.now,
    );
    upload = FakeScoreUploadApi(
      sessionStorage: session,
      accountForToken: lookup,
      library: library,
      jobs: jobs,
      latency: Duration.zero,
    );
  }

  final String account;
  final _Clock? clock;
  late final FakeScoreLibraryApi library;
  late final FakeProcessingApi jobs;
  late final FakeScoreUploadApi upload;
}

void main() {
  group('J1 verify reset code', () {
    test('real client: 200 {expiresInSeconds} returns normally', () async {
      await _http(200, {
        'data': {'expiresInSeconds': 1800},
      }).verifyPasswordReset(email: 'a@b.co', code: '123456');
    });

    test('real client: 400, 400+wait, 410, 429 map to types', () async {
      Future<Object> verify(HttpAuthApi api) =>
          _thrown(() => api.verifyPasswordReset(email: 'a@b.co', code: '1'));

      final wrong = await verify(
        _http(400, _err('reset_code_invalid', {'field': 'resetToken'})),
      ) as ResetCodeWrongException;
      expect(wrong.retryAfterSeconds, isNull);

      final fifth = await verify(
        _http(
          400,
          _err('reset_code_invalid', {'retryAfterSeconds': 30}),
          headers: {'Retry-After': '30'},
        ),
      ) as ResetCodeWrongException;
      expect(fifth.retryAfterSeconds, 30);

      expect(
        await verify(_http(410, _err('reset_token_expired_or_invalid'))),
        isA<ResetCodeInvalidException>(),
      );
      final limited = await verify(
        _http(
          429,
          _err('rate_limited', {'retryAfterSeconds': 60}),
          headers: {'Retry-After': '60'},
        ),
      ) as AuthRateLimitedException;
      expect(limited.retryAfterSeconds, 60);
    });

    test('fake: 410 without code; 400 x4; waits 30..900; code kept', () async {
      final clock = _Clock();
      final fake = FakeAuthApi(latency: Duration.zero, clock: () => clock.now);
      const email = FakeAuthApi.demoEmail;
      Future<Object> verify(String code) =>
          _thrown(() => fake.verifyPasswordReset(email: email, code: code));

      expect(await verify('000000'), isA<ResetCodeInvalidException>());
      await fake.requestPasswordReset(email: email);
      final good = fake.demoInboxCodeFor(email)!;
      final bad = good == '000000' ? '111111' : '000000';
      for (var i = 1; i <= 4; i++) {
        final e = await verify(bad) as ResetCodeWrongException;
        expect(e.retryAfterSeconds, isNull);
      }
      // Verify never consumes the code, nor clears the failure count.
      await fake.verifyPasswordReset(email: email, code: good);
      expect(fake.demoInboxCodeFor(email), good);
      // D0.2: wrongs 5-10 wait 30, 60, 120, 240, 480, 900. An 11th would land
      // at 1830 s, after the 30 min code expired, so stop at the 10th.
      const waits = [30, 60, 120, 240, 480, 900];
      for (final (i, expected) in waits.indexed) {
        final e = await verify(bad) as ResetCodeWrongException;
        expect(e.retryAfterSeconds, expected);
        expect(await verify(good), isA<AuthRateLimitedException>());
        if (i < waits.length - 1) {
          clock.now = clock.now.add(Duration(seconds: expected));
        }
      }
    });
  });

  group('J2 login lockout', () {
    test('real client: error.attemptsRemaining on wrongs 1-4', () async {
      for (final n in [4, 3, 2, 1]) {
        final e = await _loginFails(
          _http(401, _err('invalid_credentials', {'attemptsRemaining': n})),
        ) as InvalidCredentialsException;
        expect((e.attemptsRemaining, e.retryAfterSeconds), (n, null));
      }
    });

    test('real client: retryAfterSeconds on wrong 5+, 3600 at 10', () async {
      for (final s in [30, 60, 90, 120, 150, 3600]) {
        final e = await _loginFails(
          _http(
            401,
            _err('invalid_credentials', {'retryAfterSeconds': s}),
            headers: {'Retry-After': '$s'},
          ),
        ) as InvalidCredentialsException;
        expect((e.attemptsRemaining, e.retryAfterSeconds), (null, s));
      }
    });

    test('real client: 429 during a wait carries remaining seconds', () async {
      final e = await _loginFails(
        _http(
          429,
          _err('rate_limited', {'retryAfterSeconds': 42}),
          headers: {'Retry-After': '42'},
        ),
      ) as AuthRateLimitedException;
      expect(e.retryAfterSeconds, 42);
    });

    test('fake: 4..1, 30..150, 429, 3600 lock, step-down to 30', () async {
      final clock = _Clock();
      final fake = FakeAuthApi(latency: Duration.zero, clock: () => clock.now);
      Future<InvalidCredentialsException> wrong() async => await _thrown(
        () => fake.login(email: FakeAuthApi.demoEmail, password: 'no'),
      ) as InvalidCredentialsException;

      for (final n in [4, 3, 2, 1]) {
        final e = await wrong();
        expect((e.attemptsRemaining, e.retryAfterSeconds), (n, null));
      }
      for (final s in [30, 60, 90, 120, 150]) {
        final e = await wrong();
        expect((e.attemptsRemaining, e.retryAfterSeconds), (null, s));
        // The right password during the wait is still the 429.
        final during = await _thrown(
          () => fake.login(
            email: FakeAuthApi.demoEmail,
            password: FakeAuthApi.demoPassword,
          ),
        ) as AuthRateLimitedException;
        expect(during.retryAfterSeconds, s);
        clock.now = clock.now.add(Duration(seconds: s));
      }
      expect((await wrong()).retryAfterSeconds, 3600); // wrong 10
      clock.now = clock.now.add(const Duration(hours: 1));
      expect((await wrong()).retryAfterSeconds, 30); // step-down to wrong 5
    });
  });

  group('J3 delete account', () {
    test('real client: 403 wrong password, 401 session, 200 ok', () async {
      Future<void> call(HttpAuthApi api) =>
          api.deleteAccount(token: 't', password: 'p');
      expect(
        await _thrown(() => call(_http(403, _err('invalid_current_password')))),
        isA<CurrentPasswordIncorrectException>(),
      );
      expect(
        await _thrown(() => call(_http(401, _err('unauthorized')))),
        isA<AuthSessionExpiredException>(),
      );
      await call(_http(200, {'success': true}));
    });

    test('fake: wrong password, success, then login is unknown', () async {
      final fake = FakeAuthApi(latency: Duration.zero);
      final session = await fake.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      expect(
        await _thrown(
          () => fake.deleteAccount(token: session.sessionToken, password: 'no'),
        ),
        isA<CurrentPasswordIncorrectException>(),
      );
      await fake.deleteAccount(
        token: session.sessionToken,
        password: FakeAuthApi.demoPassword,
      );
      final e = await _thrown(
        () => fake.login(
          email: FakeAuthApi.demoEmail,
          password: FakeAuthApi.demoPassword,
        ),
      ) as InvalidCredentialsException;
      // Unknown account: the ordinary first wrong password.
      expect(e.attemptsRemaining, 4);
    });
  });

  group('J4 /result additive fields', () {
    Map<String, Object?> file(String key) => {
      'url': 'https://cdn.test/$key?sig=1',
      'fileId': key,
      'sizeBytes': 1234,
    };
    final old = <String, dynamic>{
      'scoreId': 7,
      'audioTracks': {'soprano': 'https://cdn.test/s.mp3'},
      'scoreImages': ['https://cdn.test/p0.png'],
    };
    final store = LocalResultsStore(
      rootProvider: () => throw UnimplementedError(),
      downloader: _NoDownloader(),
    );
    const voices = ['soprano', 'alto', 'tenor', 'bass'];

    test('contract JSON parses and every file group is recognised', () {
      final data = <String, dynamic>{
        ...old,
        'audioFiles': {for (final v in voices) v: file('audio/$v.mp3')},
        'pageFiles': [file('pages/p0.png')],
        'timingFile': file('timing/t.json'),
        'midiTracks': {for (final v in voices) v: file('midi/$v.mid')},
      };
      final result = ScoreResult.fromJson(data);
      expect(result.scoreId, 7);
      expect(result.rawJson, data);
      expect(store.hasFiles(data), isTrue);
    });

    test('midiTracks/timingFile null and absent fields do not fail', () {
      final nulls = <String, dynamic>{
        ...old,
        'audioFiles': {'soprano': file('audio/s.mp3')},
        'pageFiles': [file('pages/p0.png')],
        'timingFile': null,
        'midiTracks': null,
      };
      expect(ScoreResult.fromJson(nulls).audioTracks, hasLength(1));
      expect(store.hasFiles(nulls), isTrue);
      expect(ScoreResult.fromJson(old).audioTracks, hasLength(1));
      expect(store.hasFiles(old), isFalse); // server before B6
    });
  });

  group('midiCombined parse', () {
    final base = <String, dynamic>{
      'scoreId': 7,
      'audioTracks': {'soprano': 'https://cdn.test/s.mp3'},
    };
    test('present', () {
      final m = ScoreResult.fromJson({
        ...base,
        'midiCombined': {
          'url': 'https://cdn.test/all.mid',
          'fileId': 'midi/all.mid',
          'sizeBytes': 99,
        },
      }).midiCombined!;
      expect(m.url, Uri.parse('https://cdn.test/all.mid'));
      expect(m.fileId, 'midi/all.mid');
      expect(m.sizeBytes, 99);
    });

    test('null, absent and malformed are null, never a throw', () {
      for (final bad in <Object?>[
        null,
        'x',
        {'url': 'https://cdn.test/a.mid'},
        {'url': 42, 'fileId': 'f'},
        {'url': 'https://cdn.test/a.mid', 'fileId': ''},
      ]) {
        expect(
          ScoreResult.fromJson({...base, 'midiCombined': bad}).midiCombined,
          isNull,
          reason: '$bad',
        );
      }
      expect(ScoreResult.fromJson(base).midiCombined, isNull);
    });
  });

  group('J5 percentComplete', () {
    test('real parser: int 0-100, 100 only on complete', () {
      for (final p in [0, 5, 24, 40, 85, 92, 99]) {
        final s = ProcessingStatus.fromJson({
          'status': 'transcribing',
          'percentComplete': p,
        });
        expect(s.percentComplete, p);
      }
      final done = ProcessingStatus.fromJson({
        'status': 'complete',
        'percentComplete': 100,
        'scoreId': 3,
      });
      expect(done.stage, ProcessingStage.complete);
      expect(done.percentComplete, 100);
    });

    test('fake: monotonic, below 100 until complete', () async {
      final f = _Fakes('singer@example.com', clock: _Clock());
      final id = (await f.upload.submitImages(
        details: const ScoreDetails(title: 'Ave'),
        imagePaths: ['a.jpg', 'b.jpg', 'c.jpg'],
      )).jobId;
      final start = f.clock!.now;
      var last = 0;
      var sawComplete = false;
      for (var step = 0; step <= 60 && !sawComplete; step++) {
        f.clock!.now = start.add(FakeProcessingApi.defaultStepDuration * step);
        final s = await f.jobs.fetchStatus(id);
        final p = s.percentComplete;
        if (p != null) {
          expect(p, greaterThanOrEqualTo(last));
          last = p;
        }
        if (s.stage == ProcessingStage.complete) {
          expect(p, 100);
          sawComplete = true;
        } else {
          expect(p ?? 0, lessThan(100));
        }
      }
      expect(sawComplete, isTrue);
    });
  });

  group('J6 failed upload leaves no card', () {
    test('fake: a rejected create adds no score', () async {
      final account = 'singer${FakeScoreLibraryApi.flakyDomain}';
      final f = _Fakes(account);
      final before = f.library.scoreCount(account);
      // The flaky cycle fails calls 1-3 (429, network, 415).
      for (var i = 0; i < 3; i++) {
        await expectLater(
          f.upload.submitImages(
            details: const ScoreDetails(title: 'X'),
            imagePaths: ['a.jpg'],
          ),
          throwsA(isA<ScoreUploadException>()),
        );
        expect(f.library.scoreCount(account), before);
      }
    });
  });

  group('J8 score limit', () {
    test('real parser: 409 score_limit_reached with error.limit', () {
      final e = HttpScoreUploadApi.rejectionFrom(
        Response<dynamic>(
          requestOptions: RequestOptions(),
          statusCode: 409,
          data: _err('score_limit_reached', {'limit': 20}),
        ),
      ) as UploadRejectedException;
      expect((e.statusCode, e.code, e.limit), (409, scoreLimitReachedCode, 20));
      expect(e.isScoreLimit, isTrue);
      expect(maxScoresPerUser, 20);
    });

    test('fake: 21st create is the same 409; retake not blocked', () async {
      const account = 'singer@example.com';
      final f = _Fakes(account);
      final first = await f.upload.submitImages(
        details: const ScoreDetails(title: 'First'),
        imagePaths: ['a.jpg'],
      );
      while (f.library.scoreCount(account) < maxScoresPerUser) {
        f.library.addSubmittedScore(account: account, title: 'S', pageCount: 1);
      }
      final e = await _thrown(
        () => f.upload.submitImages(
          details: const ScoreDetails(title: 'Over'),
          imagePaths: ['a.jpg'],
        ),
      ) as UploadRejectedException;
      expect((e.statusCode, e.code, e.limit), (409, scoreLimitReachedCode, 20));
      // Retake of the unfinished job may fail for its own reasons, never
      // with the limit.
      try {
        await f.upload.submitImages(
          details: const ScoreDetails(title: 'First'),
          imagePaths: ['a.jpg'],
          replacesJobId: first.jobId,
        );
      } on UploadRejectedException catch (r) {
        expect(r.code, isNot(scoreLimitReachedCode));
      }
    });
  });
}
