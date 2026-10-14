import 'dart:io';

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

/// The replacement job PIYA-116 created for a retaken page. Processing
/// polls [replacementJobId]; the failed job is not polled again.
@immutable
class ResubmittedJob {
  const ResubmittedJob({
    required this.originalJobId,
    required this.replacementJobId,
    required this.pageIndex,
  });

  final String originalJobId;
  final String replacementJobId;
  final int pageIndex;
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

/// A page file (or the PDF) is gone from the phone before it could be
/// read for upload — Android may clear the app's temp folder. [pageIndex]
/// counts from 0 and is null for a PDF.
class UploadFileMissingException extends ScoreUploadException {
  const UploadFileMissingException({this.pageIndex});
  final int? pageIndex;
}

/// The user cancelled the upload. Not an error to show.
class UploadCancelledException extends ScoreUploadException {
  const UploadCancelledException();
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
  /// [cancelToken] aborts the request; the future then fails with
  /// [UploadCancelledException]. [replacesJobId] makes it a whole-score
  /// retake of that job (PIYA-101 AC12, PIYA-207 AC12).
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
    String? replacesJobId,
  });

  /// PIYA-310: one PDF, rasterised by the server. [replacesJobId] as for
  /// [submitImages].
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
    String? replacesJobId,
  });

  /// PIYA-116: replaces page [pageIndex] (0-based) of the failed job
  /// [jobId] with [imagePath] and starts a new job. A bare 404 comes back
  /// as code [jobNotFoundCode], a bare 409 (the job didn't fail on a page)
  /// as [pageNotRetakeableCode].
  Future<ResubmittedJob> resubmitPage({
    required String jobId,
    required int pageIndex,
    required String imagePath,
    CancelToken? cancelToken,
  });
}

/// Codes the client gives PIYA-116's 404/409 when the body names none.
const String jobNotFoundCode = 'job_not_found';
const String pageNotRetakeableCode = 'page_not_retakeable';

/// PIYA-101 AC12's 409 codes for a whole-score retake: the old job can't be
/// retaken (or already was), or a retake of it is already running.
const String notRetakeableCode = 'not_retakeable';
const String retakeInProgressCode = 'retake_in_progress';

/// PIYA-101 AC12's 410 code: the old job was already replaced by a retake.
const String jobSupersededCode = 'job_superseded';

/// The PIYA-101 AC8 text parts. Optional fields are left out when unset —
/// never sent empty or as "null" — and "Other" time also leaves its field
/// out.
List<MapEntry<String, String>> scoreFormFields(
  ScoreDetails details, {
  String? replacesJobId,
}) {
  final arranger = details.arranger.trim();
  return [
    if (replacesJobId != null) MapEntry('replacesJobId', replacesJobId),
    MapEntry('title', details.title.trim()),
    if (arranger.isNotEmpty) MapEntry('arranger', arranger),
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
  static const int _notFound = 404;
  static const int _conflict = 409;
  static const int _gone = 410;
  static final DioMediaType _jpeg = DioMediaType('image', 'jpeg');
  static final DioMediaType _pdf = DioMediaType('application', 'pdf');

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
    String? replacesJobId,
  }) async {
    // Part order is page order (PIYA-101 context note).
    final form = FormData()
      ..fields.addAll(scoreFormFields(details, replacesJobId: replacesJobId));
    for (var i = 0; i < imagePaths.length; i++) {
      form.files.add(
        MapEntry(
          'pages',
          await _readFile(
            imagePaths[i],
            filename: 'page-${i + 1}.jpg',
            contentType: _jpeg,
            pageIndex: i,
          ),
        ),
      );
    }
    return _submit(
      () => _post(ApiConfig.submitImagesPath, form, cancelToken: cancelToken),
      replacesJobId: replacesJobId,
    );
  }

  /// A whole-score retake's rejections get their PIYA-101 AC12 code even
  /// when a proxy or an older server sends none.
  Future<SubmittedJob> _submit(
    Future<SubmittedJob> Function() post, {
    required String? replacesJobId,
  }) async {
    try {
      return await post();
    } on UploadRejectedException catch (e) {
      if (replacesJobId == null) rethrow;
      throw wholeRetakeRejection(e);
    }
  }

  /// Bare 404 → [jobNotFoundCode], bare 409 → [notRetakeableCode]. A 410
  /// (`job_superseded`) means the old job is already replaced, which for
  /// the singer is the same dead end as [notRetakeableCode].
  @visibleForTesting
  static UploadRejectedException wholeRetakeRejection(
    UploadRejectedException e,
  ) {
    final code = switch ((e.statusCode, e.code)) {
      (_gone, _) || (_, jobSupersededCode) => notRetakeableCode,
      (_notFound, null) => jobNotFoundCode,
      (_conflict, null) => notRetakeableCode,
      (_, final code) => code,
    };
    if (code == e.code) return e;
    return UploadRejectedException(
      statusCode: e.statusCode,
      code: code,
      field: e.field,
      pageIndex: e.pageIndex,
      retryAfter: e.retryAfter,
    );
  }

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
    String? replacesJobId,
  }) async {
    final form = FormData()
      ..fields.addAll(scoreFormFields(details, replacesJobId: replacesJobId))
      ..files.add(
        MapEntry(
          'file',
          await _readFile(pdfPath, filename: 'score.pdf', contentType: _pdf),
        ),
      );
    return _submit(
      () => _post(
        ApiConfig.submitPdfPath,
        form,
        receiveTimeout: ApiConfig.pdfReceiveTimeout,
        cancelToken: cancelToken,
      ),
      replacesJobId: replacesJobId,
    );
  }

  @override
  Future<ResubmittedJob> resubmitPage({
    required String jobId,
    required int pageIndex,
    required String imagePath,
    CancelToken? cancelToken,
  }) async {
    final form = FormData()
      ..fields.add(MapEntry('pageIndex', pageIndex.toString()))
      ..files.add(
        MapEntry(
          'page',
          await _readFile(
            imagePath,
            filename: 'page-${pageIndex + 1}.jpg',
            contentType: _jpeg,
            pageIndex: pageIndex,
          ),
        ),
      );
    final Response<dynamic> response;
    try {
      response = await _postRaw(
        ApiConfig.resubmitPagePath(jobId),
        form,
        cancelToken: cancelToken,
      );
    } on UploadRejectedException catch (e) {
      throw resubmitRejection(e);
    }
    return parseResubmittedJob(response.data, jobId, pageIndex);
  }

  /// PIYA-116 names 404 and 409 without an error code; give them one so
  /// Capture can word them.
  @visibleForTesting
  static UploadRejectedException resubmitRejection(UploadRejectedException e) {
    if (e.code != null) return e;
    final code = switch (e.statusCode) {
      _notFound => jobNotFoundCode,
      _conflict => pageNotRetakeableCode,
      _ => null,
    };
    return UploadRejectedException(
      statusCode: e.statusCode,
      code: code,
      field: e.field,
      pageIndex: e.pageIndex,
      retryAfter: e.retryAfter,
    );
  }

  /// Reads `data.replacementJobId` from the PIYA-116 202 response.
  @visibleForTesting
  static ResubmittedJob parseResubmittedJob(
    Object? body,
    String jobId,
    int pageIndex,
  ) {
    final data = body is Map<String, dynamic> ? body['data'] : null;
    final replacement = data is Map<String, dynamic>
        ? data['replacementJobId']
        : null;
    if (replacement is! String || replacement.isEmpty) {
      throw const UploadRejectedException(statusCode: null);
    }
    return ResubmittedJob(
      originalJobId: jobId,
      replacementJobId: replacement,
      pageIndex: pageIndex,
    );
  }

  /// Opens a part's file, turning a vanished temp file into a typed failure
  /// instead of an unhandled FileSystemException.
  static Future<MultipartFile> _readFile(
    String path, {
    required String filename,
    required DioMediaType contentType,
    int? pageIndex,
  }) async {
    try {
      return await MultipartFile.fromFile(
        path,
        filename: filename,
        contentType: contentType,
      );
    } on FileSystemException {
      throw UploadFileMissingException(pageIndex: pageIndex);
    }
  }

  Future<SubmittedJob> _post(
    String path,
    FormData form, {
    Duration? receiveTimeout,
    CancelToken? cancelToken,
  }) async {
    final response = await _postRaw(
      path,
      form,
      receiveTimeout: receiveTimeout,
      cancelToken: cancelToken,
    );
    return parseSubmittedJob(response.data);
  }

  Future<Response<dynamic>> _postRaw(
    String path,
    FormData form, {
    Duration? receiveTimeout,
    CancelToken? cancelToken,
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
          sendTimeout: ApiConfig.uploadSendTimeout,
          receiveTimeout: receiveTimeout,
        ),
        cancelToken: cancelToken,
      );
    } on DioException catch (e) {
      throw _mapDioError(e);
    }
    return response;
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
      case DioExceptionType.cancel:
        return const UploadCancelledException();
      case DioExceptionType.unknown when e.error is FileSystemException:
        // A file vanished while the body was streaming.
        return const UploadFileMissingException();
      case DioExceptionType.transformTimeout:
      case DioExceptionType.badCertificate:
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
