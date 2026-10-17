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

/// Any 401 from an endpoint that needs a session (PIYA-322 AC1). Kept apart
/// from [InvalidCredentialsException] because the right action differs:
/// log in again, not retype a password.
class AuthSessionExpiredException extends AuthException {
  const AuthSessionExpiredException();
}

/// 403 `invalid_current_password` from Change Password (PIYA-322 AC3). Its
/// own type, not [InvalidCredentialsException], because Login's 401 means
/// something else and the sheet marks one specific field.
class CurrentPasswordIncorrectException extends AuthException {
  const CurrentPasswordIncorrectException();
}

/// 429 `rate_limited` from Change Password (PIYA-322 AC5). The account is
/// not locked; [retryAfterSeconds] is how long to wait, or null when the
/// server gave no usable wait.
class AuthRateLimitedException extends AuthException {
  const AuthRateLimitedException({this.retryAfterSeconds});

  final int? retryAfterSeconds;
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

/// PIYA-322 AC4's `error.code` / `error.field` for a new password that
/// fails the shared Sign-Up strength validator.
const String weakPasswordCode = 'weak_password';
const String newPasswordField = 'newPassword';

/// 400 from any endpoint. [code] and [field] are the envelope's
/// `error.code` / `error.field` when sent. Sign-Up and Reset still show
/// [serverMessage]; Change Password does not, since PIYA-322 AC4 gives the
/// wording to the client and PIYA-101 AC9 says `message` is for logs.
class AuthValidationException extends AuthException {
  const AuthValidationException(this.serverMessage, {this.code, this.field});

  final String? serverMessage;
  final String? code;
  final String? field;
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

  /// PIYA-322. [token] is the current session's and stays valid on success
  /// (other sessions are revoked). A wrong [currentPassword] is
  /// [CurrentPasswordIncorrectException], any 401
  /// [AuthSessionExpiredException], too many wrong attempts
  /// [AuthRateLimitedException], a weak [newPassword] an
  /// [AuthValidationException] with code [weakPasswordCode].
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
  static const int _forbidden = 403;
  static const int _conflict = 409;
  static const int _gone = 410;
  static const int _tooManyRequests = 429;

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
      mapStatus: _mapChangePasswordStatus,
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

  /// [mapStatus] turns an error response into a failure. It is per call
  /// because the same status means different things per endpoint: a 401 is
  /// a wrong password on Login but a dead session on Change Password.
  Future<Response<Map<String, dynamic>>> _post(
    String path,
    Map<String, String> body, {
    Map<String, String>? headers,
    AuthException Function(Response<dynamic>?) mapStatus = _mapStatus,
  }) async {
    try {
      return await _dio.post<Map<String, dynamic>>(
        path,
        data: body,
        options: headers == null ? null : Options(headers: headers),
      );
    } on DioException catch (e) {
      throw _mapDioError(e, mapStatus);
    }
  }

  static AuthException _mapDioError(
    DioException e,
    AuthException Function(Response<dynamic>?) mapStatus,
  ) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const AuthNetworkException();
      case DioExceptionType.badResponse:
        return mapStatus(e.response);
      // A response arrived but couldn't be decoded in time — the network
      // worked, so this isn't the "check your internet" case.
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const AuthServerException();
    }
  }

  /// Sign-Up, Login and Password Reset (PIYA-301–304).
  static AuthException _mapStatus(Response<dynamic>? response) {
    // 410 is mapped on status alone, not on the `reset_token_expired_or_
    // invalid` error code, because the error-envelope field holding that
    // code isn't pinned down by PIYA-304 (reconcile in PIYA-214).
    return switch (response?.statusCode) {
      _unauthorized => const InvalidCredentialsException(),
      _conflict => const EmailAlreadyRegisteredException(),
      _gone => const ResetCodeInvalidException(),
      _badRequest => _validationFailure(response),
      _ => const AuthServerException(),
    };
  }

  /// PIYA-322. Mapped on status, not body, wherever the contract allows:
  /// AC1 says any 401 here is a dead session, so a proxy's bare 401 still
  /// sends the user to Login instead of blaming their current password.
  static AuthException _mapChangePasswordStatus(Response<dynamic>? response) {
    return switch (response?.statusCode) {
      _unauthorized => const AuthSessionExpiredException(),
      _forbidden => const CurrentPasswordIncorrectException(),
      _tooManyRequests => AuthRateLimitedException(
        retryAfterSeconds: _retryAfterSeconds(response),
      ),
      _badRequest => _validationFailure(response),
      _ => const AuthServerException(),
    };
  }

  static AuthValidationException _validationFailure(
    Response<dynamic>? response,
  ) {
    final body = response?.data;
    final message = body is Map<String, dynamic> && body['message'] is String
        ? body['message'] as String
        : null;
    final error = _errorObject(body);
    return AuthValidationException(
      message,
      code: _errorCode(body),
      field: error?['field'] is String ? error!['field'] as String : null,
    );
  }

  /// PIYA-322 AC5 sends the wait twice; the body wins, as on uploads
  /// (PIYA-101 AC6). Only the delta-seconds form of `Retry-After` is read:
  /// the contract never sends an HTTP date, and a wrong guess is worse
  /// than the sheet's "try again later".
  static int? _retryAfterSeconds(Response<dynamic>? response) {
    final fromBody = _errorObject(response?.data)?['retryAfterSeconds'];
    if (fromBody is int && fromBody >= 0) return fromBody;
    final header = int.tryParse(
      response?.headers.value('retry-after')?.trim() ?? '',
    );
    return header != null && header >= 0 ? header : null;
  }

  static Map<String, dynamic>? _errorObject(Object? body) {
    if (body is! Map<String, dynamic>) return null;
    final error = body['error'];
    return error is Map<String, dynamic> ? error : null;
  }

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
