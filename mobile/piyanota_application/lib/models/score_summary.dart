/// One entry of the user's Score Library — mirrors an element of
/// `data.scores` in the PIYA-308 response.
///
/// Only [scoreId] is required: without it the score can't be opened or
/// deleted. Every other field may be missing or broken in a real response
/// and is then left out of the card rather than failing the whole library
/// (PIYA-308 "client handling of incomplete entries", user decision
/// 2026-10-08).
class ScoreSummary {
  const ScoreSummary({
    required this.scoreId,
    this.title,
    this.lastActivityAt,
    this.thumbnailUrl,
    this.arranger,
    this.pageCount,
  });

  final int scoreId;

  /// Null when the server sent no usable title; the library shows these as
  /// "New Score" (numbered when there are several — see
  /// `buildLibraryEntries`).
  final String? title;

  /// When the user last opened the score (`lastAccessedAt`, PIYA-308 AC3).
  /// Falls back to `lastProcessedAt` only when `lastAccessedAt` is absent or
  /// unparseable; null means never opened, which sorts last.
  final DateTime? lastActivityAt;

  final String? thumbnailUrl;
  final String? arranger;
  final int? pageCount;

  ScoreSummary copyWith({DateTime? lastActivityAt}) => ScoreSummary(
    scoreId: scoreId,
    title: title,
    lastActivityAt: lastActivityAt ?? this.lastActivityAt,
    thumbnailUrl: thumbnailUrl,
    arranger: arranger,
    pageCount: pageCount,
  );

  /// Throws [FormatException] only for a missing or invalid `scoreId` — the
  /// caller skips that entry and keeps the rest. Any other broken field is
  /// dropped to null.
  factory ScoreSummary.fromJson(Map<String, dynamic> json) {
    final scoreId = json['scoreId'];
    if (scoreId is! int || scoreId <= 0) {
      throw FormatException(
        'Score library entry without a valid scoreId: '
        '$scoreId',
      );
    }

    return ScoreSummary(
      scoreId: scoreId,
      title: _nonBlankString(json['title']),
      lastActivityAt:
          _parseDate(json['lastAccessedAt']) ??
          _parseDate(json['lastProcessedAt']),
      thumbnailUrl: _nonBlankString(json['thumbnailUrl']),
      arranger: _nonBlankString(json['arranger']),
      pageCount: switch (json['pageCount']) {
        final int pages when pages > 0 => pages,
        _ => null,
      },
    );
  }

  static String? _nonBlankString(Object? value) =>
      value is String && value.trim().isNotEmpty ? value.trim() : null;

  static DateTime? _parseDate(Object? value) =>
      value is String ? DateTime.tryParse(value) : null;
}
