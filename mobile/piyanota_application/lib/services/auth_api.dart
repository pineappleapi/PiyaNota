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

/// 401 `session_expired` from an endpoint that needs a session (PIYA-322
/// AC1). Kept apart from [InvalidCredentialsException] because the right
/// action differs: log in again, not retype the current password.
class AuthSessionExpiredException extends AuthException {
  const AuthSessionExpiredException();
}

/// 409 `email_already_registered` from Sign-Up (PIYA-301 AC4).
class EmailAlreadyRegisteredException extends AuthException {
  const EmailAlreadyRegisteredException();
}

/// 410 `reset_token_expired_or_invalid` from Password Reset Confirm
/// (PIYA-304 AC3) — the code is expired, already used, or never existed.
/// The UI sends the user back to the code step rather than letting them
/// resubmit the same new password against a dead code.
class ResetCodeInvalidException extends AuthException {
  const ResetCodeInvalidException();
}

/// 400 from any endpoint. [serverMessage] is shown as-is since the
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

  /// PIYA-303. Completes normally whether or not [email] is registered
  /// (AC2: no account enumeration), so callers must not branch on it.
  Future<void> requestPasswordReset({required String email});

  /// PIYA-304. [resetToken] is the code the user received by email.
  Future<void> confirmPasswordReset({
    required String resetToken,
    required String newPassword,
    required String newPasswordConfirmation,
  });

  /// PIYA-322 (stub). [token] is the current session's; a wrong
  /// [currentPassword] is [InvalidCredentialsException], a dead session
  /// [AuthSessionExpiredException].
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  });
}

/// Talks to the Module 3 Flask API. Request/response shapes follow the
/// PIYA-301–304 schemas; the error envelope (`message` on non-2xx) is an
/// assumption the tickets don't pin down, so it's only read opportunistically.
class HttpAuthApi implements AuthApi {
  HttpAuthApi(this._dio);

  final Dio _dio;

  static const int _badRequest = 400;
  static const int _unauthorized = 401;
  static const int _conflict = 409;
  static const int _gone = 410;

  @override
  Future<AuthSession> login({required String email, required String password}) {
    return _postForSession(ApiConfig.loginPath, {
      'email': email,
      'password': password,
    });
  }

  @override
  Future<AuthSession> signUp({
    required String email,
    required String password,
    required String passwordConfirmation,
  }) {
    return _postForSession(ApiConfig.signUpPath, {
      'email': email,
      'password': password,
      'passwordConfirmation': passwordConfirmation,
    });
  }

  @override
  Future<void> requestPasswordReset({required String email}) async {
    // The 200 body's `message` is deliberately ignored: the UI owns the
    // confirmation copy, which must read the same for registered and
    // unregistered emails (PIYA-204 AC3) whatever the server says.
    await _post(ApiConfig.passwordResetRequestPath, {'email': email});
  }

  @override
  Future<void> confirmPasswordReset({
    required String resetToken,
    required String newPassword,
    required String newPasswordConfirmation,
  }) async {
    await _post(ApiConfig.passwordResetConfirmPath, {
      'resetToken': resetToken,
      'newPassword': newPassword,
      'newPasswordConfirmation': newPasswordConfirmation,
    });
  }

  @override
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    await _post(
      ApiConfig.changePasswordPath,
      {'currentPassword': currentPassword, 'newPassword': newPassword},
      headers: {'Authorization': 'Bearer $token'},
    );
  }

  Future<AuthSession> _postForSession(
    String path,
    Map<String, String> body,
  ) async {
    final response = await _post(path, body);
    final data = response.data?['data'];
    if (data is! Map<String, dynamic>) throw const AuthServerException();
    try {
      return AuthSession.fromJson(data);
    } on FormatException {
      throw const AuthServerException();
    }
  }

  Future<Response<Map<String, dynamic>>> _post(
    String path,
    Map<String, String> body, {
    Map<String, String>? headers,
  }) async {
    try {
      return await _dio.post<Map<String, dynamic>>(
        path,
        data: body,
        options: headers == null ? null : Options(headers: headers),
      );
    } on DioException catch (e) {
      throw _mapDioError(e);
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

    // A 401 means "wrong password" everywhere except PIYA-322, where
    // `session_expired` must send the user to Login instead (AC1 vs AC2).
    if (response?.statusCode == _unauthorized &&
        _errorCode(body) == _sessionExpiredCode) {
      return const AuthSessionExpiredException();
    }

    // 410 is mapped on status alone, not on the `reset_token_expired_or_
    // invalid` error code, because the error-envelope field holding that
    // code isn't pinned down by PIYA-304 (reconcile in PIYA-214).
    return switch (response?.statusCode) {
      _unauthorized => const InvalidCredentialsException(),
      _conflict => const EmailAlreadyRegisteredException(),
      _gone => const ResetCodeInvalidException(),
      _badRequest => AuthValidationException(message),
      _ => const AuthServerException(),
    };
  }

  static const String _sessionExpiredCode = 'session_expired';

  /// The error code from the envelope. Where it sits isn't pinned down
  /// (PIYA-214), so both `error.code` and a bare string `error` are read.
  static String? _errorCode(Object? body) {
    if (body is! Map<String, dynamic>) return null;
    return switch (body['error']) {
      {'code': final String code} => code,
      final String code => code,
      _ => null,
    };
  }
}
