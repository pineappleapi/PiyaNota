import '../models/processing_status.dart';
import '../models/score_details.dart';
import '../models/voice_failure.dart';
import '../models/voice_part.dart';
import 'fake_score_library_api.dart';
import 'processing_api.dart';
import 'score_upload_api.dart';
import 'session_storage.dart';

/// How a fake job ends. Accounts on [FakeScoreLibraryApi.flakyDomain] cycle
/// through the first four so every Processing state can be demoed.
enum FakeJobOutcome {
  success,

  /// PIYA-207 AC5/AC7: fails on page 2 with a retake offer.
  noStaffOnPage2,

  /// PIYA-207 AC6/AC7: fails on page 1, no retake.
  unsupportedLayoutOnPage1,

  /// Polls fail for a stretch shorter than the paused threshold, then the
  /// job succeeds: the "Reconnecting…" state.
  networkBlip,

  /// Completes with the Tenor `unreadable` (PIYA-207 AC11 offer).
  unreadableTenor,

  /// Completes with the Tenor `render_failed` (no offer; PIYA-208 alert).
  renderFailedTenor,

  /// Fails with `incomplete_voice_sequence` (PIYA-207 AC7 whole-score
  /// Re-photograph).
  incompleteVoices,
}

/// The newest completed job for a score, as the fake PIYA-103 serves it.
typedef FakeCompletedJob = ({
  String jobId,
  Map<VoicePart, VoiceFailureCause> causes,
});

/// In-memory stand-in for PIYA-102/114 (and the job side of PIYA-116 and
/// PIYA-101 AC12) until Module 3 is deployed.
///
/// A job walks queued → (preprocessing → detecting_staff → transcribing)
/// per page → reconstructing → synthesizing → complete, one step per
/// [stepDuration], timed from when it was registered. With the default
/// 2 s step a 3-page job takes 24 s. The estimate is null for the first
/// [_unestimatedSteps] steps, as PIYA-115 AC3 allows.
///
/// Jobs are scoped to the account that submitted them; another account or
/// an unknown job id is a 404, a missing token a 401.
///
/// Titles containing [unreadableTitleKeyword] or [missingVoiceTitleKeyword]
/// end as [FakeJobOutcome.unreadableTenor] or
/// [FakeJobOutcome.incompleteVoices], so the whole-score retake (PIYA-207
/// AC11/AC12) can be demoed on a phone. A retake itself always succeeds.
/// The demo library's scores answer as completed jobs [demoJobId], so a
/// retake can start from them too.
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

  static const String unreadableTitleKeyword = 'unreadable';
  static const String missingVoiceTitleKeyword = 'missing voice';

  static const String _demoJobPrefix = 'fake-job-';

  /// The job id the demo library's score [scoreId] was "processed" by.
  static String demoJobId(int scoreId) => '$_demoJobPrefix$scoreId';

  /// "Paraiso": its Tenor could be read but not rendered.
  /// The tempo the demo jobs report (PlaybackDemo's 90 bpm; repeated, not
  /// imported, so the demo audio stays reachable only through the fake
  /// result API).
  static const int demoTempoBpm = 90;

  static const int renderFailedDemoScoreId = 102;

  /// "Ama Namin": its Tenor couldn't be read from the photos.
  static const int unreadableDemoScoreId = 106;

  static FakeJobOutcome _demoOutcome(int scoreId) => switch (scoreId) {
    renderFailedDemoScoreId => FakeJobOutcome.renderFailedTenor,
    unreadableDemoScoreId => FakeJobOutcome.unreadableTenor,
    _ => FakeJobOutcome.success,
  };

  /// `failedVoiceCauses` a job with [outcome] completes with.
  static Map<VoicePart, VoiceFailureCause> causesFor(FakeJobOutcome outcome) =>
      switch (outcome) {
        FakeJobOutcome.unreadableTenor => const {
          VoicePart.tenor: VoiceFailureCause.unreadable,
        },
        FakeJobOutcome.renderFailedTenor => const {
          VoicePart.tenor: VoiceFailureCause.renderFailed,
        },
        _ => const {},
      };

  /// What a demo score's result says when no job of it was ever polled.
  static Map<VoicePart, VoiceFailureCause> demoCausesFor(int scoreId) =>
      causesFor(_demoOutcome(scoreId));

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
  /// creates the job row. [keepsScore] marks a whole-score retake of a
  /// completed score, which fills the same score.
  void registerJob({
    required String jobId,
    required String account,
    required int scoreId,
    required int? pageCount,
    ScoreDetails? details,
    String? replacesJobId,
    bool keepsScore = false,
  }) {
    final FakeJobOutcome outcome;
    if (replacesJobId != null) {
      outcome = FakeJobOutcome.success;
    } else {
      final count = (_jobsByAccount[account] ?? 0) + 1;
      _jobsByAccount[account] = count;
      final title = details?.title.toLowerCase() ?? '';
      if (title.contains(unreadableTitleKeyword)) {
        outcome = FakeJobOutcome.unreadableTenor;
      } else if (title.contains(missingVoiceTitleKeyword)) {
        outcome = FakeJobOutcome.incompleteVoices;
      } else if (account.endsWith(FakeScoreLibraryApi.flakyDomain)) {
        outcome = switch (count % _flakyCycle) {
          1 => FakeJobOutcome.noStaffOnPage2,
          2 => FakeJobOutcome.unsupportedLayoutOnPage1,
          3 => FakeJobOutcome.networkBlip,
          _ => FakeJobOutcome.success,
        };
      } else {
        outcome = FakeJobOutcome.success;
      }
    }
    _jobs[jobId] = _FakeJob(
      account: account,
      scoreId: scoreId,
      pages: pageCount ?? defaultPageCount,
      outcome: outcome,
      startedAt: _clock(),
      details: details,
      replacesJobId: replacesJobId,
      keepsScore: keepsScore,
    );
  }

  /// The PIYA-101 AC12 checks on `replacesJobId`, made before the fake
  /// upload creates anything. Returns the old job's score and whether the
  /// retake keeps it (a completed job) or replaces its card (a failed job).
  ({int scoreId, bool keepsScore}) checkWholeRetake({
    required String account,
    required String jobId,
  }) {
    final job = _jobFor(account, jobId);
    if (job == null) {
      throw const UploadRejectedException(
        statusCode: 404,
        code: jobNotFoundCode,
      );
    }
    final status = _statusAt(job, _stepOf(job));
    final completedUnreadable =
        status.stage == ProcessingStage.complete &&
        status.unreadableVoices.isNotEmpty;
    final missingVoice =
        status.stage == ProcessingStage.failed &&
        status.failureReason == FailureReason.incompleteVoiceSequence;
    if ((!completedUnreadable && !missingVoice) || _isSuperseded(jobId)) {
      throw const UploadRejectedException(
        statusCode: 409,
        code: notRetakeableCode,
      );
    }
    final running = _jobs.values.any(
      (other) =>
          other.replacesJobId == jobId &&
          !_statusAt(other, _stepOf(other)).stage.isTerminal,
    );
    if (running) {
      throw const UploadRejectedException(
        statusCode: 409,
        code: retakeInProgressCode,
      );
    }
    return (scoreId: job.scoreId, keepsScore: completedUnreadable);
  }

  /// A completed job is superseded once its retake completes, a failed one
  /// as soon as its retake is created (PIYA-101 AC12).
  bool _isSuperseded(String jobId) => _jobs.values.any((other) {
    if (other.replacesJobId != jobId) return false;
    if (!other.keepsScore) return true;
    return _statusAt(other, _stepOf(other)).stage == ProcessingStage.complete;
  });

  /// The newest completed job of [scoreId], or null when the fake knows of
  /// none (a demo score whose job was never asked about).
  FakeCompletedJob? latestCompletedJob({
    required String account,
    required int scoreId,
  }) {
    FakeCompletedJob? latest;
    DateTime? latestStart;
    for (final MapEntry(key: id, value: job) in _jobs.entries) {
      if (job.account != account || job.scoreId != scoreId) continue;
      if (_statusAt(job, _stepOf(job)).stage != ProcessingStage.complete) {
        continue;
      }
      if (latestStart == null || !job.startedAt.isBefore(latestStart)) {
        latestStart = job.startedAt;
        latest = (jobId: id, causes: causesFor(job.outcome));
      }
    }
    return latest;
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
    // A cancelled retake of a completed score leaves the score on its old
    // result (PIYA-207 AC12); any other cancelled scan takes its card.
    if (!job.keepsScore) {
      _library.removeSubmittedScore(account: job.account, scoreId: job.scoreId);
    }
  }

  /// The job side of PIYA-116, called by the fake upload once it has the
  /// account. Throws the same [UploadRejectedException]s the real endpoint
  /// maps to.
  ResubmittedJob resubmit({
    required String account,
    required String jobId,
    required int pageIndex,
  }) {
    final job = _jobFor(account, jobId);
    if (job == null) {
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
      details: job.details,
    );
    return ResubmittedJob(
      originalJobId: jobId,
      replacementJobId: replacementId,
      pageIndex: pageIndex,
    );
  }

  /// The fake PIYA-103's 409: [account] has a job for [scoreId] still
  /// running (a whole-score retake of a completed score included, whose
  /// old version can't be opened meanwhile, PIYA-207 AC12), or has jobs
  /// for it and none of them completed. Scores with no fake job (the demo
  /// library) count as finished.
  bool hasUnfinishedJob({required String account, required int scoreId}) {
    var any = false;
    var completed = false;
    for (final job in _jobs.values) {
      if (job.account != account || job.scoreId != scoreId) continue;
      any = true;
      final stage = _statusAt(job, _stepOf(job)).stage;
      if (!stage.isTerminal) return true;
      if (stage == ProcessingStage.complete) completed = true;
    }
    return any && !completed;
  }

  Future<_FakeJob> _ownedJob(String jobId) async {
    final token = await _sessionStorage.readToken();
    final account = token == null ? null : _accountForToken(token);
    if (account == null) throw const ProcessingSessionExpiredException();
    final job = _jobFor(account, jobId);
    if (job == null) throw const ProcessingJobNotFoundException();
    return job;
  }

  /// [jobId] if [account] owns it. A demo library score's job is created
  /// on first use, already completed.
  _FakeJob? _jobFor(String account, String jobId) {
    final job = _jobs[jobId];
    if (job != null) return job.account == account ? job : null;
    if (!jobId.startsWith(_demoJobPrefix)) return null;
    final scoreId = int.tryParse(jobId.substring(_demoJobPrefix.length));
    if (scoreId == null ||
        !FakeScoreLibraryApi.demoScores.any((s) => s.scoreId == scoreId)) {
      return null;
    }
    final score = _library.scoreFor(account: account, scoreId: scoreId);
    if (score == null) return null;
    final title = score.title;
    return _jobs[jobId] = _FakeJob(
      account: account,
      scoreId: scoreId,
      pages: score.pageCount ?? defaultPageCount,
      outcome: _demoOutcome(scoreId),
      startedAt: DateTime.fromMillisecondsSinceEpoch(0),
      details: title == null
          ? null
          : ScoreDetails(
              title: title,
              arranger: score.arranger ?? '',
              tempoBpm: demoTempoBpm,
            ),
    );
  }

  int _stepOf(_FakeJob job) {
    final elapsed = _clock().difference(job.startedAt);
    return elapsed.inMicroseconds ~/ stepDuration.inMicroseconds;
  }

  ProcessingStatus _statusAt(_FakeJob job, int step) {
    final details = job.details;
    if (job.cancelled) {
      return ProcessingStatus(
        stage: ProcessingStage.cancelled,
        details: details,
      );
    }
    final total = _stepsBefore + job.pages * _stagesPerPage + _stepsAfter;
    final failure = _failureFor(job);
    if (failure != null && step >= failure.step) {
      final pageIndex = failure.pageIndex;
      return ProcessingStatus(
        stage: ProcessingStage.failed,
        currentPage: pageIndex == null ? null : pageIndex + 1,
        totalPages: pageIndex == null ? null : job.pages,
        percentComplete: failure.step * _percentScale ~/ total,
        failureReason: failure.reason,
        failedPageIndex: pageIndex,
        details: details,
      );
    }
    if (step >= total) {
      final causes = causesFor(job.outcome);
      return ProcessingStatus(
        stage: ProcessingStage.complete,
        currentPage: job.pages,
        totalPages: job.pages,
        percentComplete: _percentScale,
        estimatedRemainingSeconds: 0,
        scoreId: job.scoreId,
        failedVoices: causes.keys.toSet(),
        failedVoiceCauses: causes,
        details: details,
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
      details: details,
    );
  }

  /// The step at which a failing job stops: detecting_staff on its page,
  /// or reconstructing for a voice missing from the whole score.
  ({int step, int? pageIndex, FailureReason reason})? _failureFor(
    _FakeJob job,
  ) {
    const detectingOffset = 1;
    return switch (job.outcome) {
      FakeJobOutcome.noStaffOnPage2 => (
        step:
            _stepsBefore +
            (job.pages >= 2 ? 1 : 0) * _stagesPerPage +
            detectingOffset,
        pageIndex: job.pages >= 2 ? 1 : 0,
        reason: FailureReason.noStaffDetected,
      ),
      FakeJobOutcome.unsupportedLayoutOnPage1 => (
        step: _stepsBefore + detectingOffset,
        pageIndex: 0,
        reason: FailureReason.unsupportedStaffLayout,
      ),
      FakeJobOutcome.incompleteVoices => (
        step: _stepsBefore + job.pages * _stagesPerPage,
        pageIndex: null,
        reason: FailureReason.incompleteVoiceSequence,
      ),
      FakeJobOutcome.success ||
      FakeJobOutcome.networkBlip ||
      FakeJobOutcome.unreadableTenor ||
      FakeJobOutcome.renderFailedTenor => null,
    };
  }
}

class _FakeJob {
  _FakeJob({
    required this.account,
    required this.scoreId,
    required this.pages,
    required this.outcome,
    required this.startedAt,
    this.details,
    this.replacesJobId,
    this.keepsScore = false,
  });

  final String account;
  final int scoreId;
  final int pages;
  final FakeJobOutcome outcome;
  final DateTime startedAt;

  /// What was submitted (PIYA-102 AC8 echoes it on every status).
  final ScoreDetails? details;

  /// Set on a whole-score retake (PIYA-101 AC12).
  final String? replacesJobId;

  /// A retake of a completed score: it fills the same score, which stays
  /// on its old result when the retake is cancelled.
  final bool keepsScore;
  bool cancelled = false;
}
