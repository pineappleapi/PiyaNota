import 'dart:async';

import 'package:dio/dio.dart' show CancelToken;
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/capture_session.dart';
import '../models/library_entry.dart';
import '../models/local_submission.dart';
import '../models/score_details.dart';
import '../models/score_upload.dart';
import '../models/whole_retake_arguments.dart';
import '../services/score_upload_api.dart';
import 'capture_providers.dart';
import 'local_submission_providers.dart';
import 'processing_providers.dart';
import 'score_library_providers.dart';
import 'settings_providers.dart';

export '../models/score_upload.dart';

/// Uploads in flight or just ended, app-lifetime like
/// [localSubmissionsProvider], so the 202 is handled even after Processing
/// is gone (Back, or the app in the background).
final scoreUploadsProvider =
    NotifierProvider<ScoreUploadsController, Map<String, ScoreUpload>>(
      ScoreUploadsController.new,
    );

class ScoreUploadsController extends Notifier<Map<String, ScoreUpload>> {
  final Map<String, CancelToken> _tokens = {};

  /// Uploads whose Processing screen has closed: they clean up after
  /// themselves when the send ends.
  final Set<String> _detached = {};

  @override
  Map<String, ScoreUpload> build() => const {};

  /// Page files the controller still holds, which Capture's stale-file
  /// sweep must leave alone.
  Set<String> get filesInUse => {
    for (final upload in state.values)
      if (upload.phase != UploadPhase.done)
        for (final item in upload.session.items) item.path,
  };

  /// Starts the send and returns at once; the key is [clientId].
  void start({
    required String clientId,
    required ScoreDetails details,
    required CaptureSession session,
    WholeRetakeArguments? wholeRetake,
    List<String> refusedAttempts = const [],
  }) {
    // A second tap before Processing covers Capture: one send per id.
    if (state[clientId]?.phase == UploadPhase.sending) return;
    state = {
      ...state,
      clientId: ScoreUpload(
        key: clientId,
        clientId: clientId,
        details: details,
        session: session,
        wholeRetake: wholeRetake,
        refusedAttempts: refusedAttempts,
      ),
    };
    unawaited(_send(clientId));
  }

  /// "Try again": the same id after an ambiguous failure, so the server
  /// dedupes; a new one after a definite refusal.
  void retry(String key) {
    final upload = state[key];
    if (upload == null || upload.phase != UploadPhase.failed) return;
    _put(
      upload.copyWith(
        clientId: upload.clientId ?? newClientSubmissionId(),
        clearError: true,
        sent: 0,
        total: 0,
      ),
    );
    unawaited(_send(key));
  }

  /// Aborts the request; [_send] then tells the server and drops the row.
  void cancel(String key) => _tokens[key]?.cancel();

  /// "Back to edit pages": removes the upload WITHOUT deleting its files,
  /// which pass back to Capture.
  ScoreUpload? takeForEdit(String key) {
    final upload = state[key];
    if (upload == null || upload.phase == UploadPhase.sending) return null;
    _remove(key);
    return upload;
  }

  /// Processing closed. A finished upload goes (a failed one with its
  /// files: nothing can resend it now); a running one finishes alone.
  void release(String key) {
    // Called from a microtask after dispose: the scope may be gone too.
    if (!ref.mounted) return;
    final upload = state[key];
    if (upload == null) return;
    if (upload.phase == UploadPhase.sending) {
      _detached.add(key);
      return;
    }
    if (upload.phase != UploadPhase.done) _deleteFiles(upload);
    _remove(key);
  }

  void _put(ScoreUpload upload) {
    if (!ref.mounted) return;
    state = {...state, upload.key: upload};
  }

  void _remove(String key) {
    _detached.remove(key);
    _tokens.remove(key);
    state = {
      for (final e in state.entries)
        if (e.key != key) e.key: e.value,
    };
  }

  void _deleteFiles(ScoreUpload upload) {
    final store = ref.read(captureFileStoreProvider);
    for (final item in upload.session.items) {
      unawaited(store.delete(item.path));
    }
  }

  /// The body of Capture's old `_submit`, unchanged in order and in what
  /// each failure does to the library row and the id.
  Future<void> _send(String key) async {
    final start = state[key];
    final clientId = start?.clientId;
    if (start == null || clientId == null) return;
    final cancelToken = _tokens[key] = CancelToken();
    final details = start.details;
    final wholeRetake = start.wholeRetake;
    final submissions = ref.read(localSubmissionsProvider.notifier);
    try {
      final api = ref.read(scoreUploadApiProvider);
      // Before the upload, so closing the app mid-send keeps the score in
      // the library.
      await submissions.begin(
        clientSubmissionId: clientId,
        title: details.title.trim().isEmpty
            ? untitledScoreLabel
            : details.title.trim(),
        replacesJobId: wholeRetake?.replacesJobId,
      );
      // PIYA-212 AC8: "Not sure" sends the Settings default as a fallback
      // the pipeline uses only when it detects no tempo (PIYA-323).
      final fallbackTempoBpm = details.tempoBpm == null
          ? await readFallbackTempo(ref.read(settingsPrefsServiceProvider))
          : null;
      void progress(int sent, int total) {
        final now = state[key];
        if (now != null) _put(now.copyWith(sent: sent, total: total));
      }

      // AC8: a PDF goes to PIYA-310, camera/gallery photos to PIYA-101.
      final pdf = start.session.pdf;
      final job = pdf != null
          ? await api.submitPdf(
              details: details,
              pdfPath: pdf.path,
              cancelToken: cancelToken,
              replacesJobId: wholeRetake?.replacesJobId,
              fallbackTempoBpm: fallbackTempoBpm,
              clientSubmissionId: clientId,
              onSendProgress: progress,
            )
          : await api.submitImages(
              details: details,
              imagePaths: [for (final page in start.session.photos) page.path],
              cancelToken: cancelToken,
              replacesJobId: wholeRetake?.replacesJobId,
              fallbackTempoBpm: fallbackTempoBpm,
              clientSubmissionId: clientId,
              onSendProgress: progress,
            );
      await submissions.attachJob(
        clientSubmissionId: clientId,
        jobId: job.jobId,
        scoreId: job.scoreId,
      );
      if (wholeRetake != null) {
        // Accepted: only now does the failed scan (and any refused earlier
        // attempt at this retake) leave the Library.
        await submissions.replaceFailedJob(wholeRetake.replacesJobId);
        for (final id in state[key]?.refusedAttempts ?? start.refusedAttempts) {
          await submissions.dismiss(id);
        }
      }
      if (!ref.mounted) return;
      // The server has its own copies now.
      _deleteFiles(start);
      final jobs = ref.read(processingJobsProvider.notifier);
      // The old job is finished with; only the retake is followed.
      if (wholeRetake != null) jobs.forget(wholeRetake.replacesJobId);
      // Tracked here, before Processing switches to it, so the library
      // shows the card as processing from the moment of submit (PIYA-218
      // AC2) and knows at once that an old score is being replaced
      // (PIYA-207 AC12).
      jobs.track(
        job.jobId,
        title: details.title,
        retakeOfScoreId: wholeRetake?.retakeOfScoreId,
        scoreId: job.scoreId,
      );
      ref.invalidate(scoreLibraryProvider);
      _end(key, (u) => u.copyWith(jobId: job.jobId, refusedAttempts: []));
    } on UploadCancelledException {
      // The id is spent: the server now holds a cancel for it (a reused id
      // would get 409 submission_cancelled), so a second send makes a new
      // one. The row goes: the user chose not to send it. The server is told
      // so a request that landed after the abort makes no job (or loses it).
      unawaited(submissions.cancel(clientId, dismissOnFailure: true));
      _end(key, (u) => u.copyWith(clearClientId: true, cancelled: true));
    } on UploadRejectedException catch (e) {
      if (e.code == submissionCancelledCode) {
        // The server holds our cancel for this id: not an error, and the id
        // is spent, so a later send must make a new one.
        unawaited(submissions.dismiss(clientId));
        _end(key, (u) => u.copyWith(clearClientId: true, cancelled: true));
        return;
      }
      await _recordFailure(
        key,
        submissions,
        clientId,
        e.code,
        e,
        definite: e.statusCode != null,
      );
    } on ScoreUploadException catch (e) {
      final (code, definite) = switch (e) {
        UploadSessionExpiredException() => (
          SubmissionFailure.sessionExpired,
          true,
        ),
        UploadFileMissingException() => (SubmissionFailure.fileMissing, true),
        _ => (SubmissionFailure.network, false),
      };
      await _recordFailure(
        key,
        submissions,
        clientId,
        code,
        e,
        definite: definite,
      );
    } catch (e, stack) {
      // Anything unforeseen must still end the upload, never leave
      // Processing "uploading" forever.
      debugPrint('Score upload failed unexpectedly: $e\n$stack');
      await _recordFailure(
        key,
        submissions,
        clientId,
        SubmissionFailure.unknown,
        const UploadRejectedException(statusCode: null),
        definite: false,
      );
    }
  }

  /// Marks the library row failed. A [definite] answer (the server said no,
  /// or the request never left) frees the id, so a resend is a new
  /// submission; an ambiguous one (network drop, no status) keeps it,
  /// because the server may already have the job and a resend must return it.
  Future<void> _recordFailure(
    String key,
    LocalSubmissionsController submissions,
    String clientId,
    String? code,
    ScoreUploadException error, {
    required bool definite,
  }) async {
    try {
      await submissions.fail(
        clientSubmissionId: clientId,
        code: code ?? SubmissionFailure.unknown,
      );
    } catch (e, stack) {
      // The row stays "processing" until the next reconcile; the screen
      // must still leave "uploading".
      debugPrint('Marking the submission failed did not save: $e\n$stack');
    }
    _end(
      key,
      (u) => u.copyWith(
        error: error,
        clearClientId: definite,
        refusedAttempts: definite && u.wholeRetake != null
            ? [...u.refusedAttempts, clientId]
            : null,
      ),
    );
  }

  /// Records how the send ended; with no Processing left to show it, the
  /// upload is dropped (a failed one with its files).
  void _end(String key, ScoreUpload Function(ScoreUpload) change) {
    _tokens.remove(key);
    final upload = state[key];
    if (upload == null || !ref.mounted) return;
    _put(change(upload));
    if (_detached.contains(key)) release(key);
  }
}
