import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/api_config.dart';
import '../models/measure_table.dart';
import '../models/score_result.dart';
import 'session_storage.dart';

/// Typed failures so Playback owns the wording and each one gets its own
/// state (FR-14): "still converting" and "not found" ask for different
/// things than "check your connection".
sealed class ScoreResultException implements Exception {
  const ScoreResultException();
}

/// 401, or no stored token: only logging in again fixes it.
class ScoreResultSessionExpiredException extends ScoreResultException {
  const ScoreResultSessionExpiredException();
}

/// No response: offline, DNS failure, timeout.
class ScoreResultNetworkException extends ScoreResultException {
  const ScoreResultNetworkException();
}

/// 404: no such score, or not the caller's (PIYA-103) — indistinguishable
/// by design.
class ScoreResultNotFoundException extends ScoreResultException {
  const ScoreResultNotFoundException();
}

/// 409: the score's job hasn't finished yet (PIYA-103).
class ScoreResultNotReadyException extends ScoreResultException {
  const ScoreResultNotReadyException();
}

/// 5xx, an unexpected status, or a body Playback can't use.
class ScoreResultServerException extends ScoreResultException {
  const ScoreResultServerException();
}

abstract interface class ScoreResultApi {
  /// PIYA-103 for [scoreId].
  Future<ScoreResult> fetchResult(int scoreId);

  /// The PIYA-117 timing file at a result's `timingMetadataUrl`: its
  /// events, and its `bars` table (AC9) when it has one.
  Future<TimingFile> fetchTiming(Uri url);
}

/// Background revalidation of a score that is already on the phone. Separate
/// from [ScoreResultApi] so existing fakes keep compiling.
abstract interface class ScoreRevalidator {
  /// `/result?touch=false[&version=...]`: touch=false so a mere local open
  /// never reorders the library by last access. Returns null when the server
  /// says [knownVersion] is still current (no files or URLs sent).
  Future<ScoreResult?> revalidate(int scoreId, {String? knownVersion});
}

class HttpScoreResultApi implements ScoreResultApi, ScoreRevalidator {
  HttpScoreResultApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  static const int _unauthorized = 401;
  static const int _notFound = 404;
  static const int _conflict = 409;

  /// PIYA-101 AC12 `job_superseded`: a whole-score retake replaced this
  /// result, so for Playback it is as gone as a 404.
  static const int _gone = 410;

  @override
  Future<ScoreResult> fetchResult(int scoreId) async {
    final response = await _get(scoreId, null);
    return parseResult(response.data);
  }

  @override
  Future<ScoreResult?> revalidate(int scoreId, {String? knownVersion}) async {
    final response = await _get(scoreId, {
      'touch': 'false',
      'version': ?knownVersion,
    });
    final body = response.data;
    final data = body is Map<String, dynamic> ? body['data'] : null;
    if (data is Map<String, dynamic> && data['unchanged'] == true) return null;
    return parseResult(body);
  }

  Future<Response<dynamic>> _get(
    int scoreId,
    Map<String, String>? query,
  ) async {
    final token = await _sessionStorage.readToken();
    if (token == null || token.isEmpty) {
      throw const ScoreResultSessionExpiredException();
    }
    try {
      return await _dio.get<dynamic>(
        ApiConfig.scoreResultPath(scoreId),
        queryParameters: query,
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  /// The timing file is fetched from its own URL with no Authorization
  /// header: PIYA-103 doesn't say whether its URLs are pre-signed or need
  /// the session token, and the bearer token must not leak to a CDN.
  /// Reconcile in PIYA-216.
  @override
  Future<TimingFile> fetchTiming(Uri url) async {
    final Response<dynamic> response;
    try {
      response = await _dio.getUri<dynamic>(url);
    } on DioException catch (e) {
      throw mapDioError(e);
    }
    return parseTiming(response.data);
  }

  @visibleForTesting
  static ScoreResult parseResult(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    if (data is! Map<String, dynamic>) {
      throw const ScoreResultServerException();
    }
    try {
      return ScoreResult.fromJson(data);
    } on FormatException {
      throw const ScoreResultServerException();
    }
  }

  /// dio decodes JSON only when the response says it is JSON; a CDN may
  /// serve the file as text.
  @visibleForTesting
  static TimingFile parseTiming(Object? body) {
    try {
      return TimingFile.parse(body is String ? jsonDecode(body) : body);
    } on FormatException {
      throw const ScoreResultServerException();
    }
  }

  @visibleForTesting
  static ScoreResultException mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const ScoreResultNetworkException();
      case DioExceptionType.badResponse:
        return switch (e.response?.statusCode) {
          _unauthorized => const ScoreResultSessionExpiredException(),
          _notFound || _gone => const ScoreResultNotFoundException(),
          _conflict => const ScoreResultNotReadyException(),
          _ => const ScoreResultServerException(),
        };
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const ScoreResultServerException();
    }
  }
}
