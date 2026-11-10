import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/api_config.dart';
import '../models/processing_status.dart';
import 'retry_after.dart';
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

/// 429 `rate_limited` on a status poll (PIYA-102 AC9: 120 reads per user
/// per minute). Not a failure of the job or the network: the tracker
/// waits [retryAfter] (or its own default when the server gives none)
/// before the next poll, PIYA-218 AC13.
class ProcessingRateLimitedException extends ProcessingException {
  const ProcessingRateLimitedException({this.retryAfter});

  final Duration? retryAfter;
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

/// One item of `GET /api/jobs`: the status payload plus the id the phone
/// sent and when the job was made.
typedef ListedJob = ({
  String jobId,
  String? clientSubmissionId,
  String? title,
  DateTime? createdAt,
  ProcessingStatus status,
});

/// `GET /api/jobs` (job-lifecycle Task 1): the caller's active jobs and
/// those of the last 7 days, newest first, in one request. A separate
/// interface so the many [ProcessingApi] fakes stay as they are.
abstract interface class JobListApi {
  /// Throws the same [ProcessingException]s as [ProcessingApi.fetchStatus].
  Future<List<ListedJob>> listJobs();
}

/// `POST /api/jobs/by-submission/<id>/cancel`: [jobId] is null when the
/// server never got the job (it then remembers the cancel for 7 days and
/// refuses a later send of that id with 409 `submission_cancelled`).
/// [status] is `cancelled`, or the job's own terminal status when it had
/// already finished (`complete`/`failed`, left alone by the server).
typedef SubmissionCancelResult = ({String? jobId, String status});

/// Separate from [ProcessingApi] so the many fakes of that stay as they are.
abstract interface class SubmissionCancelApi {
  /// Throws the same [ProcessingException]s as [ProcessingApi.cancelJob].
  Future<SubmissionCancelResult> cancelBySubmission(String clientSubmissionId);
}

class HttpProcessingApi
    implements ProcessingApi, JobListApi, SubmissionCancelApi {
  HttpProcessingApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  static const int _unauthorized = 401;
  static const int _notFound = 404;
  static const int _conflict = 409;
  static const int _tooManyRequests = 429;

  /// PIYA-101 AC12 `job_superseded`: a whole-score retake replaced the
  /// job, so for polling it is as gone as a 404 (as in PIYA-103).
  static const int _gone = 410;

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

  @override
  Future<SubmissionCancelResult> cancelBySubmission(
    String clientSubmissionId,
  ) async {
    final response = await _send(
      (options) => _dio.post<dynamic>(
        ApiConfig.cancelSubmissionPath(clientSubmissionId),
        options: options,
      ),
    );
    return parseSubmissionCancel(response.data);
  }

  @visibleForTesting
  static SubmissionCancelResult parseSubmissionCancel(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    final status = data is Map<String, dynamic> ? data['status'] : null;
    if (data is! Map<String, dynamic> || status is! String) {
      throw const ProcessingServerException();
    }
    final jobId = data['jobId'];
    return (
      jobId: jobId is String && jobId.isNotEmpty ? jobId : null,
      status: status,
    );
  }

  @override
  Future<List<ListedJob>> listJobs() async {
    final response = await _send(
      (options) =>
          _dio.get<dynamic>(ApiConfig.submitImagesPath, options: options),
    );
    return parseJobList(response.data);
  }

  /// Items that don't parse are skipped: one odd job must not hide the rest.
  @visibleForTesting
  static List<ListedJob> parseJobList(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    final jobs = data is Map<String, dynamic> ? data['jobs'] : null;
    if (jobs is! List) throw const ProcessingServerException();
    final out = <ListedJob>[];
    for (final item in jobs) {
      if (item is! Map<String, dynamic>) continue;
      final jobId = item['jobId'];
      if (jobId is! String || jobId.isEmpty) continue;
      final ProcessingStatus status;
      try {
        status = ProcessingStatus.fromJson(item);
      } on FormatException {
        continue;
      }
      final client = item['clientSubmissionId'];
      final title = item['title'];
      final created = item['createdAt'];
      out.add((
        jobId: jobId,
        clientSubmissionId: client is String && client.isNotEmpty
            ? client
            : null,
        title: title is String ? title : null,
        createdAt: created is String ? DateTime.tryParse(created) : null,
        status: status,
      ));
    }
    return out;
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
          _notFound || _gone => const ProcessingJobNotFoundException(),
          _conflict => const ProcessingConflictException(),
          _tooManyRequests => ProcessingRateLimitedException(
            retryAfter: switch (retryAfterSecondsOf(e.response)) {
              final seconds? => Duration(seconds: seconds),
              null => null,
            },
          ),
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
