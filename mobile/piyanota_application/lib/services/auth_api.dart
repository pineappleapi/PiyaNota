import 'package:dio/dio.dart';

import '../config/api_config.dart';
import '../models/auth_session.dart';

/// Failure categories the auth screens must render distinctly (PIYA-202 AC2
/// vs AC7, PIYA-203 AC5) — kept as types, not message strings, so the UI
/// owns the copy and the transport layer can't leak server wording.
sealed class AuthException implements Exception {
  const AuthException();
}

/// 401 from Login — deliberately covers both unknown email and wrong
/// password (PIYA-302 AC3).
class InvalidCredentialsException extends AuthException {
  const InvalidCredentialsException();
}

/// 409 `email_already_registered` from Sign-Up (PIYA-301 AC4).
class EmailAlreadyRegisteredException extends AuthException {
  const EmailAlreadyRegisteredException();
}

/// 400 from either endpoint. [serverMessage] is shown as-is since the
/// backend owns the validation policy wording (e.g. password strength).
class AuthValidationException extends AuthException {
  const AuthValidationException(this.serverMessage);

  final String? serverMessage;
}

/// No response at all — offline, DNS failure, timeout. Distinct from a
/// server error so the UI can say "check your internet" (PIYA-202 AC7).
class AuthNetworkException extends AuthException {
  const AuthNetworkException();
}

/// 5xx, unexpected status, or a response body that breaks the contract.
class AuthServerException extends AuthException {
  const AuthServerException();
}

abstract interface class AuthApi {
  Future<AuthSession> login({required String email, required String password});

  Future<AuthSession> signUp({
    required String email,
    required String password,
    required String passwordConfirmation,
  });
}

/// Talks to the Module 3 Flask API. Request/response shapes follow the
/// PIYA-301/302 schemas; the error envelope (`message` on non-2xx) is an
/// assumption the tickets don't pin down, so it's only read opportunistically.
class HttpAuthApi implements AuthApi {
  HttpAuthApi(this._dio);

  final Dio _dio;

  static const int _badRequest = 400;
  static const int _unauthorized = 401;
  static const int _conflict = 409;

  @override
  Future<AuthSession> login({
    required String email,
    required String password,
  }) {
    return _post(ApiConfig.loginPath, {'email': email, 'password': password});
  }

  @override
  Future<AuthSession> signUp({
    required String email,
    required String password,
    required String passwordConfirmation,
  }) {
    return _post(ApiConfig.signUpPath, {
      'email': email,
      'password': password,
      'passwordConfirmation': passwordConfirmation,
    });
  }

  Future<AuthSession> _post(String path, Map<String, String> body) async {
    final Response<Map<String, dynamic>> response;
    try {
      response = await _dio.post<Map<String, dynamic>>(path, data: body);
    } on DioException catch (e) {
      throw _mapDioError(e);
    }

    final data = response.data?['data'];
    if (data is! Map<String, dynamic>) throw const AuthServerException();
    try {
      return AuthSession.fromJson(data);
    } on FormatException {
      throw const AuthServerException();
    }
  }

  AuthException _mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const AuthNetworkException();
      case DioExceptionType.badResponse:
        return _mapStatus(e.response);
      // A response arrived but couldn't be decoded in time — the network
      // worked, so this isn't the "check your internet" case.
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const AuthServerException();
    }
  }

  AuthException _mapStatus(Response<dynamic>? response) {
    final body = response?.data;
    final message = body is Map<String, dynamic> && body['message'] is String
        ? body['message'] as String
        : null;

    return switch (response?.statusCode) {
      _unauthorized => const InvalidCredentialsException(),
      _conflict => const EmailAlreadyRegisteredException(),
      _badRequest => AuthValidationException(message),
      _ => const AuthServerException(),
    };
  }
}
