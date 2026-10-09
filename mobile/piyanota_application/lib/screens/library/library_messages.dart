import '../../models/library_entry.dart';
import '../../models/score_summary.dart';

/// User-facing Score Library copy. [emptySubtitle] is quoted verbatim from
/// PIYA-205 AC4 (and the mockup); [scoreCountSubtitle] reproduces the
/// mockup's "3 Scores • Tap to Listen". Tests assert on these, so change
/// them deliberately.
class LibraryMessages {
  LibraryMessages._();

  static const String title = 'My Scores';
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

  static String deleteSemantics(String title) => 'Delete $title';

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
