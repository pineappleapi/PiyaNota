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
  _StubAdapter({this.status = 200, this.body, this.connectionFails = false});

  final int status;
  final Object? body;
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

    test('401 invalid_credentials is a wrong current password', () async {
      final adapter = _StubAdapter(
        status: 401,
        body: _errorBody('invalid_credentials'),
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(isA<InvalidCredentialsException>()),
      );
    });

    test('401 session_expired is a dead session, not a wrong password',
        () async {
      final adapter = _StubAdapter(
        status: 401,
        body: _errorBody('session_expired'),
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(isA<AuthSessionExpiredException>()),
      );
    });

    test('400 weak_password carries the server wording', () async {
      final adapter = _StubAdapter(
        status: 400,
        body: {
          'message': 'Too weak',
          'error': {'code': 'weak_password'},
        },
      );
      await expectLater(
        _change(_apiWith(adapter)),
        throwsA(
          isA<AuthValidationException>().having(
            (e) => e.serverMessage,
            'serverMessage',
            'Too weak',
          ),
        ),
      );
    });

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

    test('success: the new password logs in, the old one no longer does',
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
    });

    test('wrong current password is a 401 invalid_credentials', () async {
      await expectLater(
        fake.changePassword(
          token: token,
          currentPassword: 'not it 1',
          newPassword: 'brand new 7',
        ),
        throwsA(isA<InvalidCredentialsException>()),
      );
    });

    test('a weak new password is a 400 with the Sign-Up rule', () async {
      await expectLater(
        fake.changePassword(
          token: token,
          currentPassword: FakeAuthApi.demoPassword,
          newPassword: 'short',
        ),
        throwsA(
          isA<AuthValidationException>().having(
            (e) => e.serverMessage,
            'serverMessage',
            AuthValidators.passwordPolicyDescription,
          ),
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
}
