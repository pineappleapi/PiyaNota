import 'package:flutter/foundation.dart';

import '../services/score_upload_api.dart' show ScoreUploadException;
import 'capture_session.dart';
import 'score_details.dart';
import 'whole_retake_arguments.dart';

/// Where one upload stands. [ScoreUpload.jobId] set means the 202 arrived.
enum UploadPhase { sending, failed, cancelled, done }

/// One "Create score" send, from the tap to the 202. Keyed in
/// `scoreUploadsProvider` by the FIRST client id it used, which is what
/// Processing was opened with; [clientId] may change after a definite
/// failure, as it did on Capture.
@immutable
class ScoreUpload {
  const ScoreUpload({
    required this.key,
    required this.clientId,
    required this.details,
    required this.session,
    this.wholeRetake,
    this.refusedAttempts = const [],
    this.sent = 0,
    this.total = 0,
    this.error,
    this.cancelled = false,
    this.jobId,
  });

  final String key;

  /// The id the next send uses; null once spent (definite refusal or a
  /// cancel), so the next send makes a new one.
  final String? clientId;
  final ScoreDetails details;

  /// The pages as Capture had them. Their files belong to the controller
  /// until a 202 (deleted) or "Back to edit pages" (handed back).
  final CaptureSession session;
  final WholeRetakeArguments? wholeRetake;

  /// Whole-retake attempts the server refused for good. Each left a failed
  /// row of its own; they go once a later attempt is accepted.
  final List<String> refusedAttempts;
  final int sent;
  final int total;
  final ScoreUploadException? error;
  final bool cancelled;
  final String? jobId;

  UploadPhase get phase => jobId != null
      ? UploadPhase.done
      : cancelled
      ? UploadPhase.cancelled
      : error != null
      ? UploadPhase.failed
      : UploadPhase.sending;

  String get title => details.title;

  ScoreUpload copyWith({
    String? clientId,
    bool clearClientId = false,
    List<String>? refusedAttempts,
    int? sent,
    int? total,
    ScoreUploadException? error,
    bool clearError = false,
    bool? cancelled,
    String? jobId,
  }) => ScoreUpload(
    key: key,
    clientId: clearClientId ? null : (clientId ?? this.clientId),
    details: details,
    session: session,
    wholeRetake: wholeRetake,
    refusedAttempts: refusedAttempts ?? this.refusedAttempts,
    sent: sent ?? this.sent,
    total: total ?? this.total,
    error: clearError ? null : (error ?? this.error),
    cancelled: cancelled ?? this.cancelled,
    jobId: jobId ?? this.jobId,
  );
}
