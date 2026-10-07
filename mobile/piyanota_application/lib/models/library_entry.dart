import 'score_summary.dart';

/// A [ScoreSummary] paired with the title the library actually shows, which
/// differs from the server's title for untitled or colliding entries.
class LibraryEntry {
  const LibraryEntry({required this.score, required this.displayTitle});

  final ScoreSummary score;
  final String displayTitle;

  int get scoreId => score.scoreId;
}

/// Label for an entry with no usable title (PIYA-308 client handling, user
/// decision 2026-10-08).
const String untitledScoreLabel = 'New Score';

const List<String> _months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/// "Oct 3, 2026" in the device's local time zone — the API sends UTC, and a
/// late-evening open in Manila would otherwise show the previous day.
/// Hand-rolled to avoid pulling in `intl` for one format. Search matches
/// against this exact string, and PIYA-308 AC4 asks the server to match the
/// same format, so change both together.
String formatScoreDate(DateTime when) {
  final local = when.toLocal();
  return '${_months[local.month - 1]} ${local.day}, ${local.year}';
}

/// Sorts most recently opened first, whatever order the server sent (the
/// server sorts too, PIYA-308 AC7, but the UI doesn't rely on it). Never-
/// opened scores go last, by title, then by id so the order is stable.
///
/// Then assigns display titles: untitled entries, and real titles that are
/// literally "New Score", share one numbered sequence in display order —
/// "New Score", "New Score (1)", "New Score (2)"… — skipping any label a
/// real title already uses, so no two rows ever read the same.
List<LibraryEntry> buildLibraryEntries(List<ScoreSummary> scores) {
  final sorted = [...scores]..sort(_compareForLibrary);

  final reserved = <String>{
    for (final score in sorted)
      if (score.title != null && !_isUntitledLabel(score.title!))
        score.title!.toLowerCase(),
  };

  var nextNumber = 0;
  String nextUntitledLabel() {
    while (true) {
      final label = nextNumber == 0
          ? untitledScoreLabel
          : '$untitledScoreLabel ($nextNumber)';
      nextNumber++;
      if (!reserved.contains(label.toLowerCase())) return label;
    }
  }

  return [
    for (final score in sorted)
      LibraryEntry(
        score: score,
        displayTitle: score.title == null || _isUntitledLabel(score.title!)
            ? nextUntitledLabel()
            : score.title!,
      ),
  ];
}

bool _isUntitledLabel(String title) =>
    title.trim().toLowerCase() == untitledScoreLabel.toLowerCase();

int _compareForLibrary(ScoreSummary a, ScoreSummary b) {
  final aWhen = a.lastActivityAt;
  final bWhen = b.lastActivityAt;
  if (aWhen != null && bWhen != null) {
    final byDate = bWhen.compareTo(aWhen);
    if (byDate != 0) return byDate;
  } else if (aWhen != null) {
    return -1;
  } else if (bWhen != null) {
    return 1;
  }
  final byTitle = (a.title ?? untitledScoreLabel)
      .toLowerCase()
      .compareTo((b.title ?? untitledScoreLabel).toLowerCase());
  if (byTitle != 0) return byTitle;
  return a.scoreId.compareTo(b.scoreId);
}

/// Case-insensitive, partial match on what the card shows: the display
/// title (so "new score" finds untitled entries), the composer and the
/// formatted date ("oct", "2026", "oct 3"). Keeps the input order, i.e.
/// newest-opened first. PIYA-215 AC1 moves search to a debounced PIYA-308
/// call, which must keep these semantics (PIYA-308 AC4).
List<LibraryEntry> filterLibraryEntries(
  List<LibraryEntry> entries,
  String query,
) {
  final needle = query.trim().toLowerCase();
  if (needle.isEmpty) return entries;
  return [
    for (final entry in entries)
      if (scoreMatchesQuery(entry.score, needle, title: entry.displayTitle))
        entry,
  ];
}

/// Shared by the client filter and the fake server's search so the two
/// can't drift. [needle] must already be trimmed and lower-cased.
bool scoreMatchesQuery(ScoreSummary score, String needle, {String? title}) {
  final when = score.lastActivityAt;
  return [
    title ?? score.title ?? untitledScoreLabel,
    ?score.composer,
    if (when != null) formatScoreDate(when),
  ].any((field) => field.toLowerCase().contains(needle));
}
