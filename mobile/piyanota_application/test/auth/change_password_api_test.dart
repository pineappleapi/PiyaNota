import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/config/api_config.dart';
import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/auth_validators.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';

/// One canned response (or a connection error) per request; records the
/// last request so the PIYA-322 payload and auth header can be checked.
class _StubAdapter implements HttpClientAdapter {
  _StubAdapter({
    this.status = 200,
    this.body,
    this.headers = const {},
    this.connectionFails = false,
  });

  final int status;
  final Object? body;
  final Map<String, List<String>> headers;
  final bool connectionFails;
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    lastRequest = options;
    if (connectionFails) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: 'Simulated offline',
      );
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        ...headers,
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

HttpAuthApi _apiWith(_StubAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'https://api.test'))
    ..httpClientAdapter = adapter;
  return HttpAuthApi(dio);
}

Future<void> _change(AuthApi api, {String token = 'sess_1'}) =>
    api.changePassword(
      token: token,
      currentPassword: 'old secret 1',
      newPassword: 'new secret 2',
    );

Map<String, Object> _errorBody(String code) => {
  'success': false,
  'error': {'code': code},
};

void main() {
  group('HttpAuthApi.changePassword (PIYA-322)', () {
    test('200: posts both passwords with the bearer token', () async {
      final adapter = _StubAdapter(
        body: {'data': null, 'success': true, 'status': 200},
      );
      await _change(_apiWith(adapter));

      final request = adapter.lastRequest!;
      expect(request.path, ApiConfig.changePasswordPath);
      expect(request.method, 'POST');
      expect(request.headers['Authorization'], 'Bearer sess_1');
      expect(request.data, {
        'currentPassword': 'old secret 1',
        'newPassword': 'new secret 2',
      });
    });

    // AC1: any 401 here means the session is dead, whatever the body. A
    // wrong current password is a 403 (AC3), never a 401.
    for (final (label, body) in <(String, Object?)>[
      ('invalid_credentials', _errorBody('invalid_credentials')),
      ('session_expired', _errorBody('session_expired')),
      ('an empty body', <String, Object>{}),
      ('no body', null),
    ]) {
      test('401 with $label is an expired session', () async {
        await expectLater(
          _change(_apiWith(_StubAdapter(status: 401, body: body))),
          throwsA(isA<AuthSessionExpiredException>()),
        );
      });
    }

    test('403 invalid_current_password is a wrong current password', () async {
      final adapter = _StubAdapter(
        status: 403,
        body: _errorBody('invalid_current_password'),
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(isA<CurrentPasswordIncorrectException>()),
      );
    });

    test('429 prefers error.retryAfterSeconds over the header', () async {
      final adapter = _StubAdapter(
        status: 429,
        body: {
          'success': false,
          'error': {'code': 'rate_limited', 'retryAfterSeconds': 125},
        },
        headers: {
          'retry-after': ['900'],
        },
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(
          isA<AuthRateLimitedException>().having(
            (e) => e.retryAfterSeconds,
            'retryAfterSeconds',
            125,
          ),
        ),
      );
    });

    test('429 falls back to the Retry-After header', () async {
      final adapter = _StubAdapter(
        status: 429,
        body: _errorBody('rate_limited'),
        headers: {
          'retry-after': ['600'],
        },
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(
          isA<AuthRateLimitedException>().having(
            (e) => e.retryAfterSeconds,
            'retryAfterSeconds',
            600,
          ),
        ),
      );
    });

    test('429 with no wait given still maps, with no seconds', () async {
      await expectLater(
        _change(_apiWith(_StubAdapter(status: 429, body: {}))),
        throwsA(
          isA<AuthRateLimitedException>().having(
            (e) => e.retryAfterSeconds,
            'retryAfterSeconds',
            isNull,
          ),
        ),
      );
    });

    test('400 weak_password carries its code and field', () async {
      final adapter = _StubAdapter(
        status: 400,
        body: {
          'message': 'Too weak',
          'error': {'code': 'weak_password', 'field': 'newPassword'},
        },
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(
          isA<AuthValidationException>()
              .having((e) => e.code, 'code', weakPasswordCode)
              .having((e) => e.field, 'field', newPasswordField),
        ),
      );
    });

    test(
      'Login keeps its own mapping: a 401 is still bad credentials',
      () async {
        final adapter = _StubAdapter(
          status: 401,
          body: _errorBody('session_expired'),
        );
        await expectLater(
          _apiWith(adapter).login(email: 'a@b.co', password: 'x'),
          throwsA(isA<InvalidCredentialsException>()),
        );
      },
    );

    test('no connection is a network failure', () async {
      await expectLater(
        _change(_apiWith(_StubAdapter(connectionFails: true))),
        throwsA(isA<AuthNetworkException>()),
      );
    });

    test('5xx is a server failure', () async {
      await expectLater(
        _change(_apiWith(_StubAdapter(status: 503, body: {}))),
        throwsA(isA<AuthServerException>()),
      );
    });
  });

  group('FakeAuthApi.changePassword', () {
    late FakeAuthApi fake;
    late String token;

    setUp(() async {
      fake = FakeAuthApi(latency: Duration.zero);
      final session = await fake.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      token = session.sessionToken;
    });

    test(
      'success: the new password logs in, the old one no longer does',
      () async {
        await fake.changePassword(
          token: token,
          currentPassword: FakeAuthApi.demoPassword,
          newPassword: 'brand new 7',
        );
        await fake.login(email: FakeAuthApi.demoEmail, password: 'brand new 7');
        await expectLater(
          fake.login(
            email: FakeAuthApi.demoEmail,
            password: FakeAuthApi.demoPassword,
          ),
          throwsA(isA<InvalidCredentialsException>()),
        );
      },
    );

    test(
      'success keeps the caller signed in and ends the other sessions',
      () async {
        final other = await fake.login(
          email: FakeAuthApi.demoEmail,
          password: FakeAuthApi.demoPassword,
        );
        await fake.changePassword(
          token: token,
          currentPassword: FakeAuthApi.demoPassword,
          newPassword: 'brand new 7',
        );
        expect(fake.accountForToken(token), FakeAuthApi.demoEmail);
        expect(fake.accountForToken(other.sessionToken), isNull);
      },
    );

    test('wrong current password is a 403', () async {
      await expectLater(
        fake.changePassword(
          token: token,
          currentPassword: 'not it 1',
          newPassword: 'brand new 7',
        ),
        throwsA(isA<CurrentPasswordIncorrectException>()),
      );
    });

    test('a weak new password is a 400 weak_password on newPassword', () async {
      await expectLater(
        fake.changePassword(
          token: token,
          currentPassword: FakeAuthApi.demoPassword,
          newPassword: 'short',
        ),
        throwsA(
          isA<AuthValidationException>()
              .having(
                (e) => e.serverMessage,
                'serverMessage',
                AuthValidators.passwordPolicyDescription,
              )
              .having((e) => e.code, 'code', weakPasswordCode)
              .having((e) => e.field, 'field', newPasswordField),
        ),
      );
    });

    test('an unknown token is an expired session', () async {
      await expectLater(
        fake.changePassword(
          token: 'nope',
          currentPassword: FakeAuthApi.demoPassword,
          newPassword: 'brand new 7',
        ),
        throwsA(isA<AuthSessionExpiredException>()),
      );
    });
  });

  group('FakeAuthApi.changePassword rate limit (PIYA-322 AC5)', () {
    late DateTime now;
    late FakeAuthApi fake;
    late String token;

    Future<void> wrong() => fake.changePassword(
      token: token,
      currentPassword: 'not it 1',
      newPassword: 'brand new 7',
    );

    Future<void> right() => fake.changePassword(
      token: token,
      currentPassword: FakeAuthApi.demoPassword,
      newPassword: 'brand new 7',
    );

    Future<void> failTimes(int count, {Duration apart = Duration.zero}) async {
      for (var i = 0; i < count; i++) {
        now = now.add(apart);
        await expectLater(
          wrong(),
          throwsA(isA<CurrentPasswordIncorrectException>()),
        );
      }
    }

    setUp(() async {
      now = DateTime.utc(2026, 10, 17, 9);
      fake = FakeAuthApi(latency: Duration.zero, clock: () => now);
      token = (await fake.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      )).sessionToken;
    });

    test(
      'five wrong passwords in 15 minutes block even the right one',
      () async {
        await failTimes(
          FakeAuthApi.changePasswordMaxFailures,
          apart: const Duration(minutes: 1),
        );
        // The first failure was at 09:01, so it ages out at 09:16; now is
        // 09:05, 11 minutes before that.
        await expectLater(
          right(),
          throwsA(
            isA<AuthRateLimitedException>().having(
              (e) => e.retryAfterSeconds,
              'retryAfterSeconds',
              11 * Duration.secondsPerMinute,
            ),
          ),
        );
      },
    );

    test('four wrong passwords are not limited yet', () async {
      await failTimes(FakeAuthApi.changePasswordMaxFailures - 1);
      await right();
    });

    test(
      'the window slides: once the oldest ages out, it works again',
      () async {
        await failTimes(FakeAuthApi.changePasswordMaxFailures);
        now = now.add(FakeAuthApi.changePasswordFailureWindow);
        await right();
      },
    );
  });
}
