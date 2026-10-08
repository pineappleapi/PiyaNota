import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/api_config.dart';
import '../models/processing_status.dart';
import 'session_storage.dart';

/// Typed failures so Processing owns the wording and picks the right
/// state: a transient one keeps the last progress, the others end polling.
sealed class ProcessingException implements Exception {
  const ProcessingException();
}

/// 401, or no stored token: only logging in again fixes it.
class ProcessingSessionExpiredException extends ProcessingException {
  const ProcessingSessionExpiredException();
}

/// No response: offline, DNS failure, timeout. Transient.
class ProcessingNetworkException extends ProcessingException {
  const ProcessingNetworkException();
}

/// 404: the job doesn't exist or isn't the caller's (PIYA-102 AC4,
/// PIYA-114 AC2) — indistinguishable by design.
class ProcessingJobNotFoundException extends ProcessingException {
  const ProcessingJobNotFoundException();
}

/// 409 from cancel: the job already finished, failed or was cancelled
/// (PIYA-114 AC7).
class ProcessingConflictException extends ProcessingException {
  const ProcessingConflictException();
}

/// 5xx, an unexpected status, or a body without a usable `data.status`.
/// Treated as transient while polling: the server may recover.
class ProcessingServerException extends ProcessingException {
  const ProcessingServerException();
}

abstract interface class ProcessingApi {
  /// PIYA-102.
  Future<ProcessingStatus> fetchStatus(String jobId);

  /// PIYA-114. Completes once the server confirms the cancel.
  Future<void> cancelJob(String jobId);
}

class HttpProcessingApi implements ProcessingApi {
  HttpProcessingApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  static const int _unauthorized = 401;
  static const int _notFound = 404;
  static const int _conflict = 409;

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    final response = await _send(
      (options) =>
          _dio.get<dynamic>(ApiConfig.jobStatusPath(jobId), options: options),
    );
    return parseStatus(response.data);
  }

  @override
  Future<void> cancelJob(String jobId) async {
    await _send(
      (options) => _dio.post<dynamic>(
        ApiConfig.cancelJobPath(jobId),
        data: {'jobId': jobId},
        options: options,
      ),
    );
  }

  /// Reads `data` from a PIYA-102 response.
  @visibleForTesting
  static ProcessingStatus parseStatus(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    if (data is! Map<String, dynamic>) {
      throw const ProcessingServerException();
    }
    try {
      return ProcessingStatus.fromJson(data);
    } on FormatException {
      throw const ProcessingServerException();
    }
  }

  Future<Response<dynamic>> _send(
    Future<Response<dynamic>> Function(Options options) request,
  ) async {
    final token = await _sessionStorage.readToken();
    if (token == null || token.isEmpty) {
      throw const ProcessingSessionExpiredException();
    }
    try {
      return await request(
        Options(headers: {'Authorization': 'Bearer $token'}),
      );
    } on DioException catch (e) {
      throw mapDioError(e);
    }
  }

  @visibleForTesting
  static ProcessingException mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const ProcessingNetworkException();
      case DioExceptionType.badResponse:
        return switch (e.response?.statusCode) {
          _unauthorized => const ProcessingSessionExpiredException(),
          _notFound => const ProcessingJobNotFoundException(),
          _conflict => const ProcessingConflictException(),
          _ => const ProcessingServerException(),
        };
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const ProcessingServerException();
    }
  }
}
