import 'dart:math';

import 'package:flutter/foundation.dart';

/// Where a locally persisted submission stands. Stored by [name]; add values
/// at the end of the meaning, never rename (rows outlive app versions).
enum SubmissionStatus {
  /// Created before the upload starts; stays until the job finishes.
  processing,

  /// Finished and playable. Written by reconcile (Task 4); a saved score
  /// that has no row at all is also ready, so no migration is needed.
  ready,

  /// Upload refused or lost, or the job failed. [LocalSubmission.failureCode]
  /// says why.
  failed,
}

/// Failure codes the app itself sets, besides the server's `error.code`
/// strings (`queue_full`, `score_limit_reached`, `too_many_active_jobs`, ...).
/// Any code not listed in the library copy is shown generically.
class SubmissionFailure {
  SubmissionFailure._();

  static const String network = 'network';
  static const String sessionExpired = 'session_expired';
  static const String fileMissing = 'file_missing';
  static const String unknown = 'unknown';

  /// The app died before the 202 and the server has no job for the id, so
  /// the upload never arrived. Set by reconcile; dismiss-only.
  static const String interrupted = 'interrupted';
}

/// One score the user sent (or is sending) for conversion, kept on the phone
/// so closing the app mid-upload or mid-conversion never loses it.
///
/// Plain data, no Riverpod or widget dependency: a background isolate reads
/// and writes it through `LocalSubmissionStore`. Holds file ids at most,
/// never signed URLs, and never a session token.
@immutable
class LocalSubmission {
  const LocalSubmission({
    required this.clientSubmissionId,
    required this.title,
    required this.createdAt,
    this.jobId,
    this.scoreId,
    this.status = SubmissionStatus.processing,
    this.failureCode,
    this.percentComplete,
    this.replacesJobId,
  });

  /// UUID v4 made on the phone before the upload and sent as the
  /// `clientSubmissionId` form field; the server returns the existing job
  /// for a repeat, so a retry after a lost 202 never makes a second score.
  final String clientSubmissionId;

  /// Null until the 202 names it.
  final String? jobId;

  /// The library score the job fills, when the 202 said.
  final int? scoreId;
  final String title;
  final SubmissionStatus status;

  /// Why [status] is failed; null otherwise.
  final String? failureCode;
  final DateTime createdAt;

  /// Last 0-100 progress reconcile saw, so a restarted app can draw the bar
  /// before the next poll. Null until then (older rows, rows still sending).
  final int? percentComplete;

  /// The failed job this row is a retake of. While this row exists the
  /// Library hides that failed row, so the piece shows one card, and the
  /// failed row is deleted once the 202 arrives. Persisted so a restart
  /// mid-retake keeps the link.
  final String? replacesJobId;

  LocalSubmission copyWith({
    String? jobId,
    int? scoreId,
    SubmissionStatus? status,
    String? failureCode,
    int? percentComplete,
    bool clearFailure = false,
  }) => LocalSubmission(
    clientSubmissionId: clientSubmissionId,
    title: title,
    createdAt: createdAt,
    jobId: jobId ?? this.jobId,
    scoreId: scoreId ?? this.scoreId,
    status: status ?? this.status,
    failureCode: clearFailure ? null : failureCode ?? this.failureCode,
    percentComplete: percentComplete ?? this.percentComplete,
    replacesJobId: replacesJobId,
  );

  Map<String, Object?> toJson() => {
    'clientSubmissionId': clientSubmissionId,
    'jobId': jobId,
    'scoreId': scoreId,
    'title': title,
    'status': status.name,
    'failureCode': failureCode,
    'percentComplete': percentComplete,
    'replacesJobId': replacesJobId,
    'createdAt': createdAt.toUtc().toIso8601String(),
  };

  /// Null when [json] lacks a usable id, title or time. An unknown status
  /// (a newer app version wrote it) reads as processing, so reconcile
  /// re-checks it rather than the row vanishing.
  static LocalSubmission? fromJson(Map<String, dynamic> json) {
    final id = json['clientSubmissionId'];
    final title = json['title'];
    final created = json['createdAt'];
    if (id is! String || id.isEmpty || title is! String || created is! String) {
      return null;
    }
    final createdAt = DateTime.tryParse(created);
    if (createdAt == null) return null;
    final jobId = json['jobId'];
    final scoreId = json['scoreId'];
    final failure = json['failureCode'];
    final percent = json['percentComplete'];
    final replaces = json['replacesJobId'];
    return LocalSubmission(
      clientSubmissionId: id,
      title: title,
      createdAt: createdAt,
      jobId: jobId is String && jobId.isNotEmpty ? jobId : null,
      scoreId: scoreId is int && scoreId > 0 ? scoreId : null,
      status:
          SubmissionStatus.values
              .where((s) => s.name == json['status'])
              .firstOrNull ??
          SubmissionStatus.processing,
      failureCode: failure is String && failure.isNotEmpty ? failure : null,
      percentComplete: percent is int ? percent.clamp(0, 100) : null,
      replacesJobId: replaces is String && replaces.isNotEmpty
          ? replaces
          : null,
    );
  }
}

/// A random (version 4) UUID, lower-case with hyphens. [random] is for tests.
String newClientSubmissionId([Random? random]) {
  const versionByte = 6;
  const variantByte = 8;
  final rng = random ?? Random.secure();
  final bytes = List<int>.generate(16, (_) => rng.nextInt(256));
  bytes[versionByte] = (bytes[versionByte] & 0x0f) | 0x40;
  bytes[variantByte] = (bytes[variantByte] & 0x3f) | 0x80;
  final hex = [for (final b in bytes) b.toRadixString(16).padLeft(2, '0')];
  return '${hex.sublist(0, 4).join()}-${hex.sublist(4, 6).join()}-'
      '${hex.sublist(6, 8).join()}-${hex.sublist(8, 10).join()}-'
      '${hex.sublist(10).join()}';
}
