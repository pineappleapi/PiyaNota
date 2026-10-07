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

  static String noMatches(String query) => 'No scores match "${query.trim()}"';

  static String deleteDialogBody(String title) =>
      '"$title" and its audio will be permanently removed from your '
      "library. This can't be undone.";

  static String deleted(String title) => '"$title" deleted';

  static String deleteSemantics(String title) => 'Delete $title';

  /// Card subtitle. The date comes first so it is the part that survives
  /// ellipsis — it is the one AC2 requires; composer and page count (the
  /// mockup's subtitle) follow only when the API supplies them.
  static String cardSubtitle(ScoreSummary score) {
    final pages = score.pageCount;
    return [
      formatScoreDate(score.lastActivityAt),
      ?score.composer,
      if (pages != null) '$pages ${pages == 1 ? 'page' : 'pages'}',
    ].join(' • ');
  }

  static const List<String> _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

  /// "Oct 3, 2026" in the device's local time zone — the API sends UTC, and
  /// a late-evening access in Manila would otherwise show the previous day.
  /// Hand-rolled to avoid pulling in `intl` for one format.
  static String formatScoreDate(DateTime when) {
    final local = when.toLocal();
    return '${_months[local.month - 1]} ${local.day}, ${local.year}';
  }
}
