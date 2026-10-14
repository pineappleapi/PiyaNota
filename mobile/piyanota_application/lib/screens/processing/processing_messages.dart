import '../../models/processing_status.dart';

/// Every user-facing string on Processing (PIYA-207), in plain words for
/// choir members (NFR-3). Failure copy is chosen by `failureReason`, never
/// by server text, and never shows a raw code.
class ProcessingMessages {
  ProcessingMessages._();

  // Progress view (mockups 1–3).
  static const String heading = 'Processing';
  static const String beforeFirstPoll = 'Analyzing your score…';
  static const String helper =
      'Hang tight — each page usually takes about 1–2 minutes.';
  static const String stalled = 'Still working, this one\'s a long piece.';
  static const String reconnecting = 'Reconnecting…';
  static const String cancelScan = 'Cancel Scan';
  static const String convertInBackground = 'Convert in Background';
  static const String backToLibrary = 'Back to library';
  static const String lessThanAMinute = 'less than a minute left';

  /// Follows the backend's stage (user decision 2026-10-08).
  static String subtitle(ProcessingStage? stage) => switch (stage) {
    null || ProcessingStage.unknown => beforeFirstPoll,
    ProcessingStage.queued => 'Waiting in line…',
    ProcessingStage.preprocessing => 'Cleaning up your pages…',
    ProcessingStage.detectingStaff => 'Finding the staff lines…',
    ProcessingStage.transcribing => 'Reading the notes…',
    ProcessingStage.reconstructing => 'Putting the voices together…',
    ProcessingStage.synthesizing => 'Making your piano guide…',
    ProcessingStage.complete => 'Analyzing complete!',
    // The failure view replaces the progress view for these.
    ProcessingStage.failed || ProcessingStage.cancelled => beforeFirstPoll,
  };

  static String percent(int value) => '$value%';
  static String page(int current, int total) => 'page $current/$total';

  /// Mockup wording ("approx. 2 min.left"), minutes rounded up so the
  /// estimate never promises less than it is.
  static String timeLeft(int seconds) {
    if (seconds < Duration.secondsPerMinute) return lessThanAMinute;
    final minutes = (seconds / Duration.secondsPerMinute).ceil();
    return 'approx. $minutes min.left';
  }

  /// One label for the whole card, read when the user focuses it, so the
  /// percentage isn't announced on every poll.
  static String cardSemantics({
    required int percent,
    int? currentPage,
    int? totalPages,
    int? secondsLeft,
  }) {
    final parts = <String>['Processing, $percent percent'];
    if (currentPage != null && totalPages != null) {
      parts.add('page $currentPage of $totalPages');
    }
    if (secondsLeft != null) {
      if (secondsLeft < Duration.secondsPerMinute) {
        parts.add('less than a minute left');
      } else {
        final minutes = (secondsLeft / Duration.secondsPerMinute).ceil();
        parts.add(
          minutes == 1 ? 'about 1 minute left' : 'about $minutes minutes left',
        );
      }
    }
    return parts.join(', ');
  }

  // Cancel (scan-status spec §3).
  static const String cancelTitle = 'Cancel scan?';
  static const String cancelBody = 'You\'ll lose your progress.';
  static const String confirmCancel = 'Cancel scan';
  static const String keepScanning = 'Keep scanning';
  static const String cancelling = 'Cancelling…';
  static const String cancelFailed =
      'Couldn\'t cancel the scan. Check your internet connection and try '
      'again.';
  static const String alreadyFinished =
      'This scan finished before it could be cancelled.';
  static const String scanCancelled = 'Scan cancelled.';

  // Completion without a score id (contract gap; see ProcessingStatus).
  static const String readyInLibrary =
      'Your score is ready. Open it from your library.';

  // Connection trouble (spec §7).
  static const String pausedTitle = 'We can\'t reach PiyaNota right now';
  static const String pausedBody =
      'Your scan is safe. Check your internet connection, then try again.';
  static const String retry = 'Try again';

  static const String sessionExpired =
      'Your session has expired. Log in again to keep following this scan.';

  // Failure view (AC5–AC7).
  static const String failedHeading = 'We couldn\'t finish this scan';
  static const String unsupportedHeading = 'This score layout isn\'t supported';
  static const String notFoundHeading = 'This scan no longer exists';
  static const String notFoundBody =
      'It may have been cancelled or removed. You can add the score again '
      'from your library.';
  static const String cancelledHeading = 'This scan was cancelled';
  static const String cancelledBody =
      'Nothing was saved. You can add the score again from your library.';

  /// AC6, verbatim. Deliberately no "retake": a new photo of the same page
  /// can't change its layout.
  static const String unsupportedLayout =
      'This page appears to use a 2-staff SATB layout, which isn\'t '
      'supported. PiyaNota requires each voice part (Soprano, Alto, Tenor, '
      'Bass) on its own staff line.';

  static String foundOnPage(int page) => 'Found on page $page.';
  static String retakePage(int page) => 'Retake page $page';

  static const String retakeTipsTitle = 'For a clearer photo:';

  /// PIYA-127's recapture checklist.
  static const List<String> retakeTips = [
    'Hold your phone steady',
    'Use good, even lighting',
    'Keep the phone level with the page',
    'Make sure nothing covers the music',
  ];

  /// The specific reason (AC5). [page] counts from 1 and is null when the
  /// server didn't say which page.
  static String failureBody(FailureReason reason, int? page) {
    final onPage = page == null ? 'on one of the pages' : 'on page $page';
    return switch (reason) {
      FailureReason.noStaffDetected =>
        'No staff lines detected $onPage — please retake '
            '${page == null ? 'that page' : 'this page'}.',
      FailureReason.ambiguousStaffCount =>
        'We couldn\'t tell the four voice parts apart $onPage. Make sure '
            'the whole page is in the photo, then retake it.',
      FailureReason.preprocessingError =>
        'The photo $onPage was too unclear to read. Please retake it.',
      FailureReason.unsupportedStaffLayout => unsupportedLayout,
      FailureReason.incompleteVoiceSequence =>
        'We couldn\'t find all four voice parts (Soprano, Alto, Tenor, Bass) '
            'in these photos. Re-photographing the whole score may fix it; '
            'check that every page is included.',
      FailureReason.stageTimeout =>
        'This scan took too long to finish. Please add the score again; '
            'fewer pages per score can help.',
      FailureReason.serverRestart =>
        'PiyaNota was interrupted while working on this scan. Please add '
            'the score again.',
      FailureReason.synthesisFailed =>
        'We couldn\'t make the audio for this score. Please try again later.',
      FailureReason.internalError =>
        'Something went wrong on our side while working on this score. '
            'Please try again later.',
      FailureReason.unknown =>
        'Something went wrong on our side while reading this score. Please '
            'add it again.',
    };
  }
}
