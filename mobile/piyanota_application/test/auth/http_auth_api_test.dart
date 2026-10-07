import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/auth_session.dart';
import 'package:piyanota_application/services/auth_api.dart';

/// Returns one canned response (or throws a connection error) for every
/// request, recording the last request so the payload shape can be checked.
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

const _successBody = {
  'data': {
    'userId': 214,
    'email': 'maria@example.com',
    'role': 'choir_member',
    'sessionToken': 'sess_a1b2c3d4',
    'expiresAt': '2026-09-11T09:15:00Z',
  },
  'success': true,
  'status': 200,
  'message': 'Login successful',
};

Future<AuthSession> _login(HttpAuthApi api) =>
    api.login(email: 'maria@example.com', password: 'secret123');

void main() {
  test('parses the PIYA-302 success schema and posts email/password',
      () async {
    final adapter = _StubAdapter(body: _successBody);
    final session = await _login(_apiWith(adapter));

    expect(session.sessionToken, 'sess_a1b2c3d4');
    expect(session.userId, 214);
    expect(session.expiresAt, DateTime.utc(2026, 9, 11, 9, 15));
    expect(adapter.lastRequest?.data, {
      'email': 'maria@example.com',
      'password': 'secret123',
    });
  });

  test('sign-up sends passwordConfirmation per PIYA-301', () async {
    final adapter = _StubAdapter(status: 201, body: _successBody);
    await _apiWith(adapter).signUp(
      email: 'maria@example.com',
      password: 'choir2026',
      passwordConfirmation: 'choir2026',
    );

    expect(
      (adapter.lastRequest?.data as Map)['passwordConfirmation'],
      'choir2026',
    );
  });

  test('401 maps to InvalidCredentialsException', () {
    final api = _apiWith(_StubAdapter(status: 401, body: {'message': 'x'}));
    expect(_login(api), throwsA(isA<InvalidCredentialsException>()));
  });

  test('409 maps to EmailAlreadyRegisteredException', () {
    final api = _apiWith(_StubAdapter(status: 409, body: {}));
    expect(
      api.signUp(
        email: 'a@b.co',
        password: 'choir2026',
        passwordConfirmation: 'choir2026',
      ),
      throwsA(isA<EmailAlreadyRegisteredException>()),
    );
  });

  test('400 carries the server message through', () async {
    final api = _apiWith(
      _StubAdapter(status: 400, body: {'message': 'Password too weak'}),
    );
    await expectLater(
      _login(api),
      throwsA(
        isA<AuthValidationException>().having(
          (e) => e.serverMessage,
          'serverMessage',
          'Password too weak',
        ),
      ),
    );
  });

  test('connection failure maps to AuthNetworkException', () {
    final api = _apiWith(_StubAdapter(connectionFails: true));
    expect(_login(api), throwsA(isA<AuthNetworkException>()));
  });

  test('500 maps to AuthServerException', () {
    final api = _apiWith(_StubAdapter(status: 500, body: {}));
    expect(_login(api), throwsA(isA<AuthServerException>()));
  });

  test('2xx with a malformed body maps to AuthServerException', () {
    final api = _apiWith(
      _StubAdapter(body: {
        'data': {'userId': 214},
      }),
    );
    expect(_login(api), throwsA(isA<AuthServerException>()));
  });
}
