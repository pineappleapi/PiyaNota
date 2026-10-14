import 'package:flutter/foundation.dart';

/// The pipeline stage PIYA-102 reports in `data.status`.
enum ProcessingStage {
  queued('queued'),
  preprocessing('preprocessing'),
  detectingStaff('detecting_staff'),
  transcribing('transcribing'),
  reconstructing('reconstructing'),
  synthesizing('synthesizing'),
  complete('complete'),
  failed('failed'),

  /// Not in PIYA-102's list, but PIYA-114 AC7 names it as a terminal state,
  /// so a job cancelled elsewhere can come back with it.
  cancelled('cancelled'),

  /// A status string this build doesn't know. Treated as still running
  /// (the app keeps polling) rather than as an error, so a backend that
  /// adds a stage doesn't break older installs.
  unknown('');

  const ProcessingStage(this.apiValue);

  final String apiValue;

  bool get isTerminal =>
      this == complete || this == failed || this == cancelled;

  static ProcessingStage fromApi(String value) => values.firstWhere(
    (stage) => stage != unknown && stage.apiValue == value,
    orElse: () => unknown,
  );
}

/// `data.failureReason` when status is `failed`. The codes come from the
/// pipeline tickets (PIYA-105, PIYA-111, PIYA-127); anything else is
/// [unknown] and gets the generic failure copy.
enum FailureReason {
  /// Page-specific; retaking that page can fix it (PIYA-116).
  preprocessingError('preprocessing_error'),
  noStaffDetected('no_staff_detected'),
  ambiguousStaffCount('ambiguous_staff_count'),

  /// Page-specific, but retaking cannot fix it: the score itself is
  /// closed-score SATB (PIYA-207 AC6/AC7).
  unsupportedStaffLayout('unsupported_staff_layout'),

  /// A voice is missing across the whole score, so there is no single page
  /// to retake.
  incompleteVoiceSequence('incomplete_voice_sequence'),
  stageTimeout('stage_timeout'),
  serverRestart('server_restart'),
  synthesisFailed('synthesis_failed'),
  internalError('internal_error'),
  unknown('');

  const FailureReason(this.apiValue);

  final String apiValue;

  /// Reasons a retake of one page can fix (PIYA-207 AC7, PIYA-116
  /// trigger). Only offered when the response also names the page.
  bool get isRetakeable =>
      this == noStaffDetected ||
      this == ambiguousStaffCount ||
      this == preprocessingError;

  static FailureReason fromApi(String value) => values.firstWhere(
    (reason) => reason != unknown && reason.apiValue == value,
    orElse: () => unknown,
  );
}

/// One PIYA-102 status response (`data`).
///
/// Only `status` is required. Every other field may be missing, null or
/// broken and is then dropped to null, so one odd field never stops the
/// progress view (same policy as `ScoreSummary`).
@immutable
class ProcessingStatus {
  const ProcessingStatus({
    required this.stage,
    this.currentPage,
    this.totalPages,
    this.percentComplete,
    this.estimatedRemainingSeconds,
    this.failureReason,
    this.failedPageIndex,
    this.scoreId,
  });

  final ProcessingStage stage;

  /// 1-based, as in the PIYA-102 example (`"currentPage": 2` of 3). Both
  /// page fields are null unless they make sense together.
  final int? currentPage;
  final int? totalPages;

  /// 0–100, clamped.
  final int? percentComplete;

  /// PIYA-115: null when the server isn't confident enough to estimate.
  final int? estimatedRemainingSeconds;

  /// Set only when [stage] is [ProcessingStage.failed].
  final FailureReason? failureReason;

  /// The page that failed (PIYA-102 AC5), counted from 0 like PIYA-101's
  /// `error.pageIndex`. Whether PIYA-102 counts from 0 or 1 is not pinned
  /// down in the ticket; reconcile in PIYA-216. Read from `pageIndex`.
  final int? failedPageIndex;

  /// The library score this job fills in. Not in PIYA-102's schema yet:
  /// Processing needs it on `complete` to open Playback (PIYA-207 AC8), so
  /// backend-lead has to add it. Missing means "can't open Playback".
  final int? scoreId;

  static const int _maxPercent = 100;

  /// Throws [FormatException] only when `status` is missing or not a
  /// string.
  factory ProcessingStatus.fromJson(Map<String, dynamic> json) {
    final status = json['status'];
    if (status is! String) {
      throw FormatException('Processing status without a status: $status');
    }
    final stage = ProcessingStage.fromApi(status);
    var currentPage = _positiveInt(json['currentPage']);
    var totalPages = _positiveInt(json['totalPages']);
    if (currentPage != null && totalPages != null && currentPage > totalPages) {
      // "page 4/3" would only confuse; show neither.
      currentPage = null;
      totalPages = null;
    }
    final percent = json['percentComplete'];
    final remaining = json['estimatedRemainingSeconds'];
    final reason = json['failureReason'];
    final pageIndex = json['pageIndex'];
    return ProcessingStatus(
      stage: stage,
      currentPage: currentPage,
      totalPages: totalPages,
      percentComplete: percent is num && percent.isFinite
          ? percent.round().clamp(0, _maxPercent)
          : null,
      estimatedRemainingSeconds:
          remaining is num && remaining.isFinite && remaining >= 0
          ? remaining.ceil()
          : null,
      failureReason: stage == ProcessingStage.failed
          ? (reason is String
                ? FailureReason.fromApi(reason)
                : FailureReason.unknown)
          : null,
      failedPageIndex:
          stage == ProcessingStage.failed && pageIndex is int && pageIndex >= 0
          ? pageIndex
          : null,
      scoreId: _positiveInt(json['scoreId']),
    );
  }

  static int? _positiveInt(Object? value) =>
      value is int && value > 0 ? value : null;
}
