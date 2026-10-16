import 'package:dio/dio.dart' show CancelToken;

import '../models/score_details.dart';
import 'fake_processing_api.dart';
import 'fake_score_library_api.dart';
import 'score_upload_api.dart';
import 'session_storage.dart';

/// In-memory stand-in for PIYA-101/310/116 until Module 3 is deployed.
///
/// - Returns a job id after [latency] and adds the score to the fake
///   library, as the real submit creates the score row. With a
///   [FakeProcessingApi] given, the job is also registered there so
///   Processing (PIYA-207) can poll it and open the right score.
/// - Accounts on [FakeScoreLibraryApi.flakyDomain] cycle through the error
///   states the Capture screen must word: a 429 with a wait, a network
///   failure, a 415 naming a page, then success.
/// - An unknown or missing token is a 401.
class FakeScoreUploadApi implements ScoreUploadApi {
  FakeScoreUploadApi({
    required this._sessionStorage,
    required this._accountForToken,
    required this._library,
    this._jobs,
    this.latency = defaultLatency,
  });

  static const Duration defaultLatency = Duration(milliseconds: 1200);
  static const Duration _fakeRetryAfter = Duration(seconds: 30);

  final Duration latency;
  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final FakeScoreLibraryApi _library;
  final FakeProcessingApi? _jobs;
  final Map<String, int> _callsByAccount = {};
  int _nextJob = 1;

  @override
  Future<SubmittedJob> submitImages({
    required ScoreDetails details,
    required List<String> imagePaths,
    CancelToken? cancelToken,
    String? replacesJobId,
  }) => _submit(details, imagePaths.length, cancelToken, replacesJobId);

  @override
  Future<SubmittedJob> submitPdf({
    required ScoreDetails details,
    required String pdfPath,
    CancelToken? cancelToken,
    String? replacesJobId,
  }) =>
      // The real PIYA-310 counts the pages itself; the fake has no PDF
      // parser, so the library card shows no page count.
      _submit(details, null, cancelToken, replacesJobId);

  /// Retakes never fail on the flaky accounts: the job they replace has
  /// already demoed a failure.
  @override
  Future<ResubmittedJob> resubmitPage({
    required String jobId,
    required int pageIndex,
    required String imagePath,
    CancelToken? cancelToken,
  }) async {
    final account = await _accountAfterLatency(cancelToken);
    final jobs = _jobs;
    if (jobs == null) {
      throw const UploadRejectedException(
        statusCode: 404,
        code: jobNotFoundCode,
      );
    }
    return jobs.resubmit(account: account, jobId: jobId, pageIndex: pageIndex);
  }

  Future<String> _accountAfterLatency(CancelToken? cancelToken) async {
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
    return account;
  }

  Future<SubmittedJob> _submit(
    ScoreDetails details,
    int? pageCount,
    CancelToken? cancelToken,
    String? replacesJobId,
  ) async {
    final account = await _accountAfterLatency(cancelToken);
    if (replacesJobId != null) {
      return _submitRetake(account, details, pageCount, replacesJobId);
    }
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
    final arranger = details.arranger.trim();
    final scoreId = _library.addSubmittedScore(
      account: account,
      title: details.title.trim(),
      arranger: arranger.isEmpty ? null : arranger,
      pageCount: pageCount,
    );
    final jobId = 'fake-job-${_nextJob++}';
    _jobs?.registerJob(
      jobId: jobId,
      account: account,
      scoreId: scoreId,
      pageCount: pageCount,
      details: details,
    );
    return SubmittedJob(
      jobId: jobId,
      pageCount: pageCount,
      status: 'queued',
      scoreId: scoreId,
    );
  }

  /// PIYA-101 AC12. Never fails on the flaky accounts, like a page retake.
  /// A completed score keeps its id and card; a failed scan's card is
  /// replaced by the new one.
  SubmittedJob _submitRetake(
    String account,
    ScoreDetails details,
    int? pageCount,
    String replacesJobId,
  ) {
    final jobs = _jobs;
    if (jobs == null) {
      throw const UploadRejectedException(
        statusCode: 404,
        code: jobNotFoundCode,
      );
    }
    final old = jobs.checkWholeRetake(account: account, jobId: replacesJobId);
    final int scoreId;
    if (old.keepsScore) {
      scoreId = old.scoreId;
    } else {
      _library.removeSubmittedScore(account: account, scoreId: old.scoreId);
      final arranger = details.arranger.trim();
      scoreId = _library.addSubmittedScore(
        account: account,
        title: details.title.trim(),
        arranger: arranger.isEmpty ? null : arranger,
        pageCount: pageCount,
      );
    }
    final jobId = 'fake-job-retake-${_nextJob++}';
    jobs.registerJob(
      jobId: jobId,
      account: account,
      scoreId: scoreId,
      pageCount: pageCount,
      details: details,
      replacesJobId: replacesJobId,
      keepsScore: old.keepsScore,
    );
    return SubmittedJob(
      jobId: jobId,
      pageCount: pageCount,
      status: 'queued',
      scoreId: scoreId,
    );
  }
}
