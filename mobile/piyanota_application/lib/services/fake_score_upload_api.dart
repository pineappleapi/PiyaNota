import 'package:dio/dio.dart' show CancelToken;

import '../models/score_details.dart';
import 'fake_score_library_api.dart';
import 'score_upload_api.dart';
import 'session_storage.dart';

/// In-memory stand-in for PIYA-101/310 until Module 3 is deployed.
///
/// - Returns a job id after [latency] and adds the score to the fake
///   library, as the real submit creates the score row.
/// - Accounts on [FakeScoreLibraryApi.flakyDomain] cycle through the error
///   states the Capture screen must word: a 429 with a wait, a network
///   failure, a 415 naming a page, then success.
/// - An unknown or missing token is a 401.
class FakeScoreUploadApi implements ScoreUploadApi {
  FakeScoreUploadApi({
    required this._sessionStorage,
    required this._accountForToken,
    required this._library,
    this.latency = defaultLatency,
  });

  static const Duration defaultLatency = Duration(milliseconds: 1200);
  static const Duration _fakeRetryAfter = Duration(seconds: 30);

  final Duration latency;
  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final FakeScoreLibraryApi _library;
  final Map<String, int> _callsByAccount = {};
  int _nextJob = 1;

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
  }) => _submit(details, imagePaths.length, cancelToken);

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
  }) =>
      // The real PIYA-310 counts the pages itself; the fake has no PDF
      // parser, so the library card shows no page count.
      _submit(details, null, cancelToken);

  Future<SubmittedJob> _submit(
    ScoreDetails details,
    int? pageCount,
    CancelToken? cancelToken,
  ) async {
    await Future.any<void>([
      Future<void>.delayed(latency),
      if (cancelToken != null) cancelToken.whenCancel,
    ]);
    if (cancelToken?.isCancelled ?? false) {
      throw const UploadCancelledException();
    }
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) throw const UploadSessionExpiredException();
    if (account.endsWith(FakeScoreLibraryApi.flakyDomain)) {
      final call = (_callsByAccount[account] ?? 0) + 1;
      _callsByAccount[account] = call;
      switch (call % 4) {
        case 1:
          throw const UploadRejectedException(
            statusCode: 429,
            code: 'queue_full',
            retryAfter: _fakeRetryAfter,
          );
        case 2:
          throw const UploadNetworkException();
        case 3:
          throw const UploadRejectedException(
            statusCode: 415,
            code: 'unsupported_file_type',
            pageIndex: 0,
          );
      }
    }
    final composer = details.composer.trim();
    _library.addSubmittedScore(
      account: account,
      title: details.title.trim(),
      composer: composer.isEmpty ? null : composer,
      pageCount: pageCount,
    );
    return SubmittedJob(
      jobId: 'fake-job-${_nextJob++}',
      pageCount: pageCount,
      status: 'queued',
    );
  }
}
