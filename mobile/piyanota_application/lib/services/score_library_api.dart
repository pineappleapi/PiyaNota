import 'package:dio/dio.dart';

import '../config/api_config.dart';
import '../models/score_summary.dart';
import 'session_storage.dart';

/// Failure categories the Score Library must render distinctly — typed, not
/// message strings, so the screen owns the copy (same split as
/// AuthException).
sealed class ScoreLibraryException implements Exception {
  const ScoreLibraryException();
}

/// 401 (PIYA-308/309 AC1), or no stored token at all. The fix is to log in
/// again, which a Retry can't do — so it gets its own state.
class SessionExpiredException extends ScoreLibraryException {
  const SessionExpiredException();
}

/// 404 from Delete: the score doesn't exist or isn't the caller's
/// (indistinguishable by design, PIYA-309 AC2). Either way it is not in
/// this user's library any more.
class ScoreNotFoundException extends ScoreLibraryException {
  const ScoreNotFoundException();
}

/// No response at all — offline, DNS failure, timeout.
class ScoreLibraryNetworkException extends ScoreLibraryException {
  const ScoreLibraryNetworkException();
}

/// 5xx, unexpected status, or a body that breaks the PIYA-308 contract.
class ScoreLibraryServerException extends ScoreLibraryException {
  const ScoreLibraryServerException();
}

abstract interface class ScoreLibraryApi {
  /// PIYA-308. [query] filters by title server-side (AC4); null or blank
  /// fetches the whole library. Returns an empty list, not an error, for a
  /// user with no scores (AC5).
  Future<List<ScoreSummary>> fetchLibrary({String? query});

  /// PIYA-309. Completes only once the server confirms the deletion (200);
  /// callers must not remove the entry before this resolves (PIYA-215 AC2).
  Future<void> deleteScore(int scoreId);
}

/// Talks to the Module 3 Flask API with the stored session as a Bearer
/// token. The token is read per request, not cached, so a re-login or
/// logout is picked up without rebuilding this client.
class HttpScoreLibraryApi implements ScoreLibraryApi {
  HttpScoreLibraryApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  static const int _unauthorized = 401;
  static const int _notFound = 404;

  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) async {
    final trimmed = query?.trim() ?? '';
    final response = await _send(
      (options) => _dio.get<Map<String, dynamic>>(
        ApiConfig.scoreLibraryPath,
        queryParameters: trimmed.isEmpty
            ? null
            : {ApiConfig.scoreLibrarySearchParam: trimmed},
        options: options,
      ),
    );

    final data = response.data?['data'];
    final scores = data is Map<String, dynamic> ? data['scores'] : null;
    if (scores is! List) throw const ScoreLibraryServerException();
    try {
      return [
        for (final entry in scores)
          if (entry is Map<String, dynamic>)
            ScoreSummary.fromJson(entry)
          else
            throw const FormatException('Score entry is not an object'),
      ];
    } on FormatException {
      throw const ScoreLibraryServerException();
    }
  }

  @override
  Future<void> deleteScore(int scoreId) async {
    await _send(
      (options) => _dio.delete<Map<String, dynamic>>(
        ApiConfig.scorePath(scoreId),
        options: options,
      ),
    );
  }

  Future<Response<Map<String, dynamic>>> _send(
    Future<Response<Map<String, dynamic>>> Function(Options options) request,
  ) async {
    final token = await _sessionStorage.readToken();
    // Without a token the server can only answer 401, so skip the round
    // trip and report the same thing.
    if (token == null || token.isEmpty) throw const SessionExpiredException();
    try {
      return await request(
        Options(headers: {'Authorization': 'Bearer $token'}),
      );
    } on DioException catch (e) {
      throw _mapDioError(e);
    }
  }

  ScoreLibraryException _mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const ScoreLibraryNetworkException();
      case DioExceptionType.badResponse:
        return switch (e.response?.statusCode) {
          _unauthorized => const SessionExpiredException(),
          _notFound => const ScoreNotFoundException(),
          _ => const ScoreLibraryServerException(),
        };
      // A response arrived but was unusable — the network worked, so this
      // isn't the "check your internet" case.
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const ScoreLibraryServerException();
    }
  }
}
