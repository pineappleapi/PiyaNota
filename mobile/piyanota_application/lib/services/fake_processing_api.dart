import '../models/processing_status.dart';
import 'fake_score_library_api.dart';
import 'processing_api.dart';
import 'score_upload_api.dart';
import 'session_storage.dart';

/// How a fake job ends. Accounts on [FakeScoreLibraryApi.flakyDomain] cycle
/// through these so every Processing state can be demoed.
enum FakeJobOutcome {
  success,

  /// PIYA-207 AC5/AC7: fails on page 2 with a retake offer.
  noStaffOnPage2,

  /// PIYA-207 AC6/AC7: fails on page 1, no retake.
  unsupportedLayoutOnPage1,

  /// Polls fail for a stretch shorter than the paused threshold, then the
  /// job succeeds: the "Reconnecting…" state.
  networkBlip,
}

/// In-memory stand-in for PIYA-102/114 (and the job side of PIYA-116)
/// until Module 3 is deployed.
///
/// A job walks queued → (preprocessing → detecting_staff → transcribing)
/// per page → reconstructing → synthesizing → complete, one step per
/// [stepDuration], timed from when it was registered. With the default
/// 2 s step a 3-page job takes 24 s. The estimate is null for the first
/// [_unestimatedSteps] steps, as PIYA-115 AC3 allows.
///
/// Jobs are scoped to the account that submitted them; another account or
/// an unknown job id is a 404, a missing token a 401.
class FakeProcessingApi implements ProcessingApi {
  FakeProcessingApi({
    required this._sessionStorage,
    required this._accountForToken,
    required this._library,
    this.stepDuration = defaultStepDuration,
    this.latency = defaultLatency,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  static const Duration defaultStepDuration = Duration(seconds: 2);
  static const Duration defaultLatency = Duration(milliseconds: 300);

  /// The real PIYA-310 counts PDF pages server-side; the fake can't.
  static const int defaultPageCount = 3;
  static const int _stagesPerPage = 3;

  /// queued before the pages; reconstructing and synthesizing after.
  static const int _stepsBefore = 1;
  static const int _stepsAfter = 2;
  static const int _unestimatedSteps = 2;

  /// [FakeJobOutcome.networkBlip] fails polls during these steps: 8 s at
  /// the default step, well under Processing's 30 s paused threshold.
  static const int _blipFirstStep = 3;
  static const int _blipLastStep = 6;

  static const int _percentScale = 100;
  static const int _flakyCycle = 4;

  final Duration stepDuration;
  final Duration latency;
  final SessionStorage _sessionStorage;
  final AccountForToken _accountForToken;
  final FakeScoreLibraryApi _library;
  final DateTime Function() _clock;
  final Map<String, _FakeJob> _jobs = {};
  final Map<String, int> _jobsByAccount = {};
  int _nextReplacement = 1;

  /// Called by the fake upload when a submit succeeds, as the real submit
  /// creates the job row.
  void registerJob({
    required String jobId,
    required String account,
    required int scoreId,
    required int? pageCount,
  }) {
    final count = (_jobsByAccount[account] ?? 0) + 1;
    _jobsByAccount[account] = count;
    final outcome = account.endsWith(FakeScoreLibraryApi.flakyDomain)
        ? switch (count % _flakyCycle) {
            1 => FakeJobOutcome.noStaffOnPage2,
            2 => FakeJobOutcome.unsupportedLayoutOnPage1,
            3 => FakeJobOutcome.networkBlip,
            _ => FakeJobOutcome.success,
          }
        : FakeJobOutcome.success;
    _jobs[jobId] = _FakeJob(
      account: account,
      scoreId: scoreId,
      pages: pageCount ?? defaultPageCount,
      outcome: outcome,
      startedAt: _clock(),
    );
  }

  @override
  Future<ProcessingStatus> fetchStatus(String jobId) async {
    await Future<void>.delayed(latency);
    final job = await _ownedJob(jobId);
    final step = _stepOf(job);
    if (job.outcome == FakeJobOutcome.networkBlip &&
        step >= _blipFirstStep &&
        step <= _blipLastStep) {
      throw const ProcessingNetworkException();
    }
    return _statusAt(job, step);
  }

  @override
  Future<void> cancelJob(String jobId) async {
    await Future<void>.delayed(latency);
    final job = await _ownedJob(jobId);
    if (_statusAt(job, _stepOf(job)).stage.isTerminal) {
      throw const ProcessingConflictException();
    }
    job.cancelled = true;
    _library.removeSubmittedScore(account: job.account, scoreId: job.scoreId);
  }

  /// The job side of PIYA-116, called by the fake upload once it has the
  /// account. Throws the same [UploadRejectedException]s the real endpoint
  /// maps to.
  ResubmittedJob resubmit({
    required String account,
    required String jobId,
    required int pageIndex,
  }) {
    final job = _jobs[jobId];
    if (job == null || job.account != account) {
      throw const UploadRejectedException(
        statusCode: 404,
        code: jobNotFoundCode,
      );
    }
    final status = _statusAt(job, _stepOf(job));
    if (!(status.failureReason?.isRetakeable ?? false) ||
        status.failedPageIndex != pageIndex) {
      throw const UploadRejectedException(
        statusCode: 409,
        code: pageNotRetakeableCode,
      );
    }
    final replacementId = '$jobId-r${_nextReplacement++}';
    _jobs[replacementId] = _FakeJob(
      account: account,
      scoreId: job.scoreId,
      pages: job.pages,
      outcome: FakeJobOutcome.success,
      startedAt: _clock(),
    );
    return ResubmittedJob(
      originalJobId: jobId,
      replacementJobId: replacementId,
      pageIndex: pageIndex,
    );
  }

  Future<_FakeJob> _ownedJob(String jobId) async {
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) throw const ProcessingSessionExpiredException();
    final job = _jobs[jobId];
    if (job == null || job.account != account) {
      throw const ProcessingJobNotFoundException();
    }
    return job;
  }

  int _stepOf(_FakeJob job) {
    final elapsed = _clock().difference(job.startedAt);
    return elapsed.inMicroseconds ~/ stepDuration.inMicroseconds;
  }

  ProcessingStatus _statusAt(_FakeJob job, int step) {
    if (job.cancelled) {
      return const ProcessingStatus(stage: ProcessingStage.cancelled);
    }
    final total = _stepsBefore + job.pages * _stagesPerPage + _stepsAfter;
    final failure = _failureFor(job);
    if (failure != null && step >= failure.step) {
      return ProcessingStatus(
        stage: ProcessingStage.failed,
        currentPage: failure.pageIndex + 1,
        totalPages: job.pages,
        percentComplete: failure.step * _percentScale ~/ total,
        failureReason: failure.reason,
        failedPageIndex: failure.pageIndex,
      );
    }
    if (step >= total) {
      return ProcessingStatus(
        stage: ProcessingStage.complete,
        currentPage: job.pages,
        totalPages: job.pages,
        percentComplete: _percentScale,
        estimatedRemainingSeconds: 0,
        scoreId: job.scoreId,
      );
    }
    final ProcessingStage stage;
    final int? page;
    if (step < _stepsBefore) {
      stage = ProcessingStage.queued;
      page = null;
    } else if (step < _stepsBefore + job.pages * _stagesPerPage) {
      final pageStep = step - _stepsBefore;
      stage = const [
        ProcessingStage.preprocessing,
        ProcessingStage.detectingStaff,
        ProcessingStage.transcribing,
      ][pageStep % _stagesPerPage];
      page = pageStep ~/ _stagesPerPage + 1;
    } else {
      stage = step == total - _stepsAfter
          ? ProcessingStage.reconstructing
          : ProcessingStage.synthesizing;
      page = job.pages;
    }
    return ProcessingStatus(
      stage: stage,
      currentPage: page,
      totalPages: page == null ? null : job.pages,
      percentComplete: step * _percentScale ~/ total,
      estimatedRemainingSeconds: step < _unestimatedSteps
          ? null
          : (total - step) * stepDuration.inSeconds,
    );
  }

  /// The step at which a failing job stops: detecting_staff on its page.
  ({int step, int pageIndex, FailureReason reason})? _failureFor(_FakeJob job) {
    final (int pageIndex, FailureReason reason) = switch (job.outcome) {
      FakeJobOutcome.noStaffOnPage2 => (
        job.pages >= 2 ? 1 : 0,
        FailureReason.noStaffDetected,
      ),
      FakeJobOutcome.unsupportedLayoutOnPage1 => (
        0,
        FailureReason.unsupportedStaffLayout,
      ),
      FakeJobOutcome.success ||
      FakeJobOutcome.networkBlip => (-1, FailureReason.unknown),
    };
    if (pageIndex < 0) return null;
    const detectingOffset = 1;
    return (
      step: _stepsBefore + pageIndex * _stagesPerPage + detectingOffset,
      pageIndex: pageIndex,
      reason: reason,
    );
  }
}

class _FakeJob {
  _FakeJob({
    required this.account,
    required this.scoreId,
    required this.pages,
    required this.outcome,
    required this.startedAt,
  });

  final String account;
  final int scoreId;
  final int pages;
  final FakeJobOutcome outcome;
  final DateTime startedAt;
  bool cancelled = false;
}
