import '../../models/library_entry.dart';
import '../../models/score_summary.dart';

/// User-facing Score Library copy. [emptySubtitle] is quoted verbatim from
/// PIYA-205 AC4 (and the mockup); [scoreCountSubtitle] reproduces the
/// mockup's "3 Scores • Tap to Listen". Tests assert on these, so change
/// them deliberately.
class LibraryMessages {
  LibraryMessages._();

  static const String title = 'My Scores';

  /// PIYA-207 AC12: a whole-score retake of a completed score ended
  /// without a result, so the card is back to the earlier version.
  static String retakeFailed(String title) =>
      'The new photos of "$title" couldn\'t be used. Your earlier version '
      'is still here.';
  static const String emptySubtitle = 'No Scores • Tap Capture Button';
  static const String loadingSubtitle = 'Loading your scores…';
  static const String errorSubtitle = 'Scores unavailable';
  static const String searchHint = 'Search here';

  static const String addScoreTitle = 'Add Score';
  static const String addScoreSubtitle =
      'Take photos of your favorite sheet music';

  static const String loadingSemantics = 'Loading your scores';
  static const String loadNetworkError =
      "Can't load your scores — check your internet connection.";
  static const String loadServerError =
      "Couldn't load your scores. Please try again.";
  static const String sessionExpired =
      'Your session has expired. Log in again to see your scores.';
  static const String retry = 'Retry';
  static const String logInAgain = 'Log In';

  static const String deleteDialogTitle = 'Delete score?';
  static const String deleteConfirm = 'Delete';
  static const String deleteCancel = 'Cancel';
  static const String deleteNetworkError =
      "Couldn't delete — check your internet connection.";
  static const String deleteServerError =
      "Couldn't delete this score. Please try again.";
  static const String deleteAlreadyGone =
      'That score was already removed from your library.';

  static String scoreCountSubtitle(int count) =>
      '$count ${count == 1 ? 'Score' : 'Scores'} • Tap to Listen';

  static const String noResultsTitle = 'No results';
  static String noResultsHint(String query) =>
      'Nothing matches "${query.trim()}". Try a title, arranger or date.';
  static const String clearSearch = 'Clear search';

  static String deleteDialogBody(String title) =>
      '"$title" and its audio will be permanently removed from your '
      "library. This can't be undone.";

  static String deleted(String title) => '"$title" deleted';

  static const String editDialogTitle = 'Edit score details';
  static const String editSave = 'Save';
  static const String editCancel = 'Cancel';
  static String editSemantics(String title) => 'Edit details of $title';
  static const String editNetworkError =
      "Couldn't save — check your internet connection.";
  static const String editServerError =
      "Couldn't save your changes. Please try again.";
  static const String editSaved = 'Score details saved';
  static const String editSaving = 'Saving…';

  static String deleteSemantics(String title) => 'Delete $title';

  /// Library card for a score that is still being sent (no job yet).
  static const String uploading = 'Sending…';
  static const String dismissSubmission = 'Dismiss';
  static const String cancelSubmission = 'Cancel';
  static String cancelSubmissionSemantics(String title) =>
      'Cancel converting $title';
  static String dismissSubmissionSemantics(String title) =>
      'Dismiss failed score $title';

  /// Opens the failure view (what went wrong, Retake).
  static const String openFailedSubmission = 'See what happened';
  static String openFailedSubmissionSemantics(String title) =>
      'See what went wrong with $title';

  /// Why a send failed, in plain words and with the next step. Unknown
  /// server codes (any other 409/429 included) get [submissionFailedGeneric].
  ///
  /// [hasJob]: the server has a job for this card, so it opens the failure
  /// view and the only fix is its Re-photograph (which replaces this card).
  /// "Add it again" there would make a second card beside the failed one.
  static String submissionFailed(String? code, {bool hasJob = false}) {
    if (hasJob && !_beforeJobCodes.contains(code)) {
      return switch (code) {
        'unsupported_staff_layout' => _unsupportedLayout,
        'no_staff_detected' ||
        'ambiguous_staff_count' ||
        'preprocessing_error' =>
          "We couldn't read the staves. Tap See what happened to "
              're-photograph the score with every staff in view.',
        'incomplete_voice_sequence' =>
          "We couldn't find all four voices. Tap See what happened to "
              're-photograph the whole score.',
        _ =>
          "Couldn't finish this score. Tap See what happened to "
              'see what to do.',
      };
    }
    return _submissionFailedNoJob(code);
  }

  // Refused or lost before any job existed: only a new Add Score helps.
  static const Set<String?> _beforeJobCodes = {
    'queue_full',
    'score_limit_reached',
    'too_many_active_jobs',
    'network',
    'session_expired',
    'file_missing',
  };

  static const String _unsupportedLayout =
      'This looks like a piano-style score. PiyaNota reads scores with one '
      'staff per voice.';

  static String _submissionFailedNoJob(String? code) => switch (code) {
    'queue_full' => 'PiyaNota is busy. Add this score again in a few minutes.',
    'score_limit_reached' =>
      'Your library is full. Delete a score, then add this one again.',
    'too_many_active_jobs' =>
      'Too many scores converting. Add this one again when one finishes.',
    'network' => "Couldn't send — check your connection and add it again.",
    'session_expired' => 'Your session expired. Log in and add it again.',
    'file_missing' => 'The photos are gone. Add this score again.',
    // Found by reconcile after the app was closed (conversion failed or the
    // upload never arrived).
    'interrupted' =>
      'This score never finished sending. Add it again when you are online.',
    'no_staff_detected' || 'ambiguous_staff_count' || 'preprocessing_error' =>
      "We couldn't read the staves. Retake the photo with every staff in "
          'view and add it again.',
    'unsupported_staff_layout' => _unsupportedLayout,
    'incomplete_voice_sequence' =>
      "We couldn't find all four voices. Add the whole score again.",
    _ => submissionFailedGeneric,
  };

  static const String submissionFailedGeneric =
      "Couldn't send this score. Add it again.";

  /// Read out for the trash/swipe spinner while the delete is in flight.
  static const String deleting = 'Deleting…';

  /// Card subtitle. The date comes first so it is the part that survives
  /// ellipsis; arranger and page count follow when known. Missing parts are
  /// left out entirely, so there is never a dangling "•".
  static String cardSubtitle(ScoreSummary score) {
    final pages = score.pageCount;
    final when = score.lastActivityAt;
    return [
      if (when != null) formatScoreDate(when),
      ?score.arranger,
      if (pages != null) '$pages ${pages == 1 ? 'page' : 'pages'}',
    ].join(' • ');
  }
}
