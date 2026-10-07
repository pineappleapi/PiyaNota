/// One entry of the user's Score Library — mirrors an element of
/// `data.scores` in the PIYA-308 response.
class ScoreSummary {
  const ScoreSummary({
    required this.scoreId,
    required this.title,
    required this.lastActivityAt,
    this.thumbnailUrl,
    this.composer,
    this.pageCount,
  });

  final int scoreId;
  final String title;

  /// `lastAccessedAt`, falling back to `lastProcessedAt`: PIYA-308 AC3 names
  /// them as alternatives ("lastAccessedAt/lastProcessedAt") and its schema
  /// only shows the first, so either is accepted until PIYA-215 pins it.
  final DateTime lastActivityAt;

  /// In PIYA-308 AC3 but unused by the PIYA-205 mockup (which shows a
  /// music-note tile), so optional rather than a reason to reject an entry.
  final String? thumbnailUrl;

  /// Not in the PIYA-308 contract. The mockup's card subtitle shows
  /// "composer • N pages"; these are rendered only when the API supplies
  /// them (open question for backend-lead).
  final String? composer;
  final int? pageCount;

  /// Throws [FormatException] when a field the screen depends on is missing
  /// or mistyped, so contract drift surfaces as an explicit error state
  /// instead of a card with a blank title or a crash mid-render.
  factory ScoreSummary.fromJson(Map<String, dynamic> json) {
    final scoreId = json['scoreId'];
    final title = json['title'];
    final activity = json['lastAccessedAt'] ?? json['lastProcessedAt'];
    final thumbnailUrl = json['thumbnailUrl'];
    final composer = json['composer'];
    final pageCount = json['pageCount'];

    if (scoreId is! int || title is! String || activity is! String) {
      throw const FormatException('Malformed score library entry');
    }
    final lastActivityAt = DateTime.tryParse(activity);
    if (lastActivityAt == null) {
      throw const FormatException('Malformed score library timestamp');
    }

    return ScoreSummary(
      scoreId: scoreId,
      title: title,
      lastActivityAt: lastActivityAt,
      // Optional extras are dropped, not rejected, when mistyped: they're
      // decoration, and a bad one shouldn't hide the whole library.
      thumbnailUrl: thumbnailUrl is String ? thumbnailUrl : null,
      composer: composer is String && composer.isNotEmpty ? composer : null,
      pageCount: pageCount is int && pageCount > 0 ? pageCount : null,
    );
  }
}
