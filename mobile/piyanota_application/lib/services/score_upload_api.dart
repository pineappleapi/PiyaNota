import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/api_config.dart';
import '../models/score_details.dart';
import 'session_storage.dart';

/// The job PIYA-101/310 created. Processing (PIYA-207) polls it by [jobId].
@immutable
class SubmittedJob {
  const SubmittedJob({
    required this.jobId,
    required this.pageCount,
    required this.status,
  });

  final String jobId;
  final int? pageCount;
  final String status;
}

/// Typed failures so the Capture screen owns the wording (PIYA-215 AC3).
sealed class ScoreUploadException implements Exception {
  const ScoreUploadException();
}

/// 401, or no stored token: only logging in again fixes it.
class UploadSessionExpiredException extends ScoreUploadException {
  const UploadSessionExpiredException();
}

/// No response: offline, DNS failure, timeout.
class UploadNetworkException extends ScoreUploadException {
  const UploadNetworkException();
}

/// The server answered with an error. [code] is `error.code` from the
/// PIYA-101 AC9 envelope (null when the body had none), [pageIndex] is set
/// for errors about one file, [retryAfter] for 429.
class UploadRejectedException extends ScoreUploadException {
  const UploadRejectedException({
    required this.statusCode,
    this.code,
    this.field,
    this.pageIndex,
    this.retryAfter,
  });

  final int? statusCode;
  final String? code;
  final String? field;
  final int? pageIndex;
  final Duration? retryAfter;
}

abstract interface class ScoreUploadApi {
  /// PIYA-101: camera and gallery pages, in page order.
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
  });

  /// PIYA-310: one PDF, rasterised by the server.
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
  });
}

/// The PIYA-101 AC8 text parts. Optional fields are left out when unset —
/// never sent empty or as "null" — and "Other" time also leaves its field
/// out.
List<MapEntry<String, String>> scoreFormFields(ScoreDetails details) {
  final composer = details.composer.trim();
  return [
    MapEntry('title', details.title.trim()),
    if (composer.isNotEmpty) MapEntry('composer', composer),
    if (details.tempoBpm case final tempo?)
      MapEntry('tempoBpm', tempo.toString()),
    if (details.keySignature case final key?)
      MapEntry('keySignature', key.apiValue),
    if (details.timeSignature?.apiValue case final time?)
      MapEntry('timeSignature', time),
  ];
}

class HttpScoreUploadApi implements ScoreUploadApi {
  HttpScoreUploadApi(this._dio, this._sessionStorage);

  final Dio _dio;
  final SessionStorage _sessionStorage;

  static const int _unauthorized = 401;
  static const int _payloadTooLarge = 413;
  static final DioMediaType _jpeg = DioMediaType('image', 'jpeg');
  static final DioMediaType _pdf = DioMediaType('application', 'pdf');

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
  }) async {
    // Part order is page order (PIYA-101 context note).
    final form = FormData()..fields.addAll(scoreFormFields(details));
    for (var i = 0; i < imagePaths.length; i++) {
      form.files.add(
        MapEntry(
          'pages',
          await MultipartFile.fromFile(
            imagePaths[i],
            filename: 'page-${i + 1}.jpg',
            contentType: _jpeg,
          ),
        ),
      );
    }
    return _post(ApiConfig.submitImagesPath, form);
  }

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
  }) async {
    final form = FormData()
      ..fields.addAll(scoreFormFields(details))
      ..files.add(
        MapEntry(
          'file',
          await MultipartFile.fromFile(
            pdfPath,
            filename: 'score.pdf',
            contentType: _pdf,
          ),
        ),
      );
    return _post(
      ApiConfig.submitPdfPath,
      form,
      receiveTimeout: ApiConfig.pdfReceiveTimeout,
    );
  }

  Future<SubmittedJob> _post(
    String path,
    FormData form, {
    Duration? receiveTimeout,
  }) async {
    final token = await _sessionStorage.readToken();
    if (token == null || token.isEmpty) {
      throw const UploadSessionExpiredException();
    }
    final Response<dynamic> response;
    try {
      response = await _dio.post<dynamic>(
        path,
        data: form,
        options: Options(
          headers: {'Authorization': 'Bearer $token'},
          contentType: 'multipart/form-data',
          receiveTimeout: receiveTimeout,
        ),
      );
    } on DioException catch (e) {
      throw _mapDioError(e);
    }
    return parseSubmittedJob(response.data);
  }

  /// Reads `data.jobId` from the PIYA-101/310 202 response.
  @visibleForTesting
  static SubmittedJob parseSubmittedJob(Object? body) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    final jobId = data is Map<String, dynamic> ? data['jobId'] : null;
    if (data is! Map<String, dynamic> || jobId is! String || jobId.isEmpty) {
      throw const UploadRejectedException(statusCode: null);
    }
    final pageCount = data['pageCount'];
    final status = data['status'];
    return SubmittedJob(
      jobId: jobId,
      pageCount: pageCount is int ? pageCount : null,
      status: status is String ? status : 'queued',
    );
  }

  ScoreUploadException _mapDioError(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return const UploadNetworkException();
      case DioExceptionType.badResponse:
        return rejectionFrom(e.response);
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return const UploadRejectedException(statusCode: null);
    }
  }

  /// Maps an error response to a typed failure, reading the PIYA-101 AC9
  /// envelope. A 413 with no readable code is the reverse proxy's own HTML
  /// page, which the contract says to treat as `request_too_large`.
  @visibleForTesting
  static ScoreUploadException rejectionFrom(Response<dynamic>? response) {
    final status = response?.statusCode;
    if (status == _unauthorized) return const UploadSessionExpiredException();
    final body = response?.data;
    final error = body is Map<String, dynamic> ? body['error'] : null;
    final fields = error is Map<String, dynamic> ? error : const {};
    final code = fields['code'];
    final field = fields['field'];
    final pageIndex = fields['pageIndex'];
    final retrySeconds = fields['retryAfterSeconds'] is int
        ? fields['retryAfterSeconds'] as int
        : int.tryParse(response?.headers.value('retry-after') ?? '');
    return UploadRejectedException(
      statusCode: status,
      code: code is String
          ? code
          : (status == _payloadTooLarge ? 'request_too_large' : null),
      field: field is String ? field : null,
      pageIndex: pageIndex is int ? pageIndex : null,
      retryAfter: retrySeconds == null ? null : Duration(seconds: retrySeconds),
    );
  }
}
