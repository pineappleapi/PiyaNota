import 'dart:ui' show Size;

import 'package:flutter/foundation.dart';

import '../config/api_config.dart';

import 'score_details.dart';
import 'voice_part.dart';

/// Reads a voice name from either contract: PIYA-103 keys its audio tracks
/// in lowercase (`soprano`), the PIYA-117 timing file writes `Soprano`.
/// Matching ignores case so neither side has to change (backend-lead,
/// 2026-10-09). Unknown names are null.
VoicePart? parseVoicePart(Object? value) {
  if (value is! String) return null;
  final needle = value.trim().toLowerCase();
  for (final voice in VoicePart.values) {
    if (voice.name == needle) return voice;
  }
  return null;
}

/// PIYA-103's per-score review summary.
@immutable
class ReviewSummary {
  const ReviewSummary({
    required this.reviewNeeded,
    this.reasons = const [],
    this.itemCount = 0,
    this.truncated = false,
  });

  /// Used when a response has no usable `review` block. The pipeline's
  /// real-world accuracy is unmeasured (BUG-011), so a missing signal is
  /// treated as "check it", never as "it's correct".
  static const ReviewSummary unknown = ReviewSummary(reviewNeeded: true);

  final bool reviewNeeded;
  final List<String> reasons;

  /// How many flagged items the response listed. The items themselves are
  /// not shown yet; PIYA-208 only surfaces the banner.
  final int itemCount;
  final bool truncated;

  static ReviewSummary fromJson(Object? json) {
    if (json is! Map<String, dynamic>) return unknown;
    final needed = json['reviewNeeded'];
    if (needed is! bool) return unknown;
    final reasons = json['reasons'];
    final items = json['items'];
    return ReviewSummary(
      reviewNeeded: needed,
      reasons: [
        if (reasons is List)
          for (final reason in reasons)
            if (reason is String) reason,
      ],
      itemCount: items is List ? items.length : 0,
      truncated: json['truncated'] == true,
    );
  }
}

/// One PIYA-103 AC9 `mutedMeasures` entry: a span of one voice that Stage 5
/// rendered as silence because Stage 4's repair threw notes away. The
/// audio already carries the silence; the app only tells the user.
@immutable
class MutedMeasure {
  const MutedMeasure({
    required this.voice,
    this.bar,
    this.pageIndex,
    this.systemIndex,
    this.startMs,
    this.endMs,
    this.reason,
  });

  final VoicePart voice;

  /// Printed measure number (pickup = 0); null when Stage 4 could not
  /// anchor the voice-strip to the bar grid. Then [pageIndex] and
  /// [systemIndex] (both 0-based) say where it is.
  final int? bar;
  final int? pageIndex;
  final int? systemIndex;
  final int? startMs;
  final int? endMs;
  final String? reason;

  /// Null for an entry that can't be named to the user (no voice, or
  /// neither a bar nor a page); one bad entry never fails the result.
  static MutedMeasure? tryParse(Object? json) {
    if (json is! Map) return null;
    final voice = parseVoicePart(json['voice']);
    if (voice == null) return null;
    final bar = _nonNegative(json['bar']);
    final page = _nonNegative(json['pageIndex']);
    if (bar == null && page == null) return null;
    final reason = json['reason'];
    return MutedMeasure(
      voice: voice,
      bar: bar,
      pageIndex: page,
      systemIndex: _nonNegative(json['systemIndex']),
      startMs: _nonNegative(json['startMs']),
      endMs: _nonNegative(json['endMs']),
      reason: reason is String ? reason : null,
    );
  }

  static int? _nonNegative(Object? value) =>
      value is int && value >= 0 ? value : null;
}

/// The `data` of a PIYA-103 result: everything Playback needs to load.
@immutable
class ScoreResult {
  const ScoreResult({
    required this.scoreId,
    required this.audioTracks,
    required this.scoreImages,
    required this.review,
    this.jobId,
    this.timingMetadataUrl,
    this.pageSizes = const [],
    this.arranger,
    this.tempoBpm = ScoreDetails.defaultTempo,
    this.tempoKnown = true,
    this.declaredFailedVoices = const {},
    this.mutedMeasures = const [],
  });

  final int scoreId;
  final String? jobId;

  /// Only the voices that came back with a usable URL; a missing one shows
  /// as a disabled chip rather than failing the whole score.
  final Map<VoicePart, Uri> audioTracks;

  /// One original preprocessed page image per page, in page order
  /// (`pageIndex` 0 is the first). FR-8: never a re-engraved rendering.
  /// A page whose URL was unusable keeps its slot as null, so the pages
  /// after it keep their `pageIndex`; it shows blank, without the band.
  final List<Uri?> scoreImages;
  final Uri? timingMetadataUrl;
  final ReviewSummary review;

  /// Pixel size of each page in [scoreImages], in the coordinate space of
  /// the timing file's `x`/`y`. NOT in PIYA-103: proposed to backend-lead
  /// (only the fake sends `scoreImageSizes`). Without it the client uses
  /// the decoded image's own size, which is only right while the server
  /// sends the image the coordinates were measured on, never a downscale.
  final List<Size?> pageSizes;

  /// PIYA-103 AC7 (added 2026-10-09), omitted when absent. Playback falls back
  /// to the library entry's arranger.
  final String? arranger;

  /// PIYA-103 AC8: the tempo the tracks were rendered at, in quarter notes
  /// per minute (PIYA-101 AC8). The Speed modal (PIYA-210) plays at
  /// chosen BPM / this, and the metronome click is laid out on it. Absent,
  /// not an int, or outside [ScoreDetails.minTempo]–[ScoreDetails.maxTempo]
  /// reads as [ScoreDetails.defaultTempo] (90), the value the server
  /// renders at when none was submitted.
  final int tempoBpm;

  /// False when the server sent no usable `tempoBpm` and [tempoBpm] is the
  /// assumed 90. The Speed slider still works on that, but the metronome
  /// is unavailable: a click off the music's real beat is worse than none.
  final bool tempoKnown;

  /// PIYA-103 AC10 `failedVoices`: voices the server could not render.
  final Set<VoicePart> declaredFailedVoices;

  /// PIYA-103 AC9, in the server's order; empty when nothing was muted.
  /// Entries for a failed voice are dropped (it has no audio to mute).
  final List<MutedMeasure> mutedMeasures;

  /// Every voice that won't play from the server's side: listed in
  /// `failedVoices`, or missing from `audioTracks` (PIYA-216 AC5 treats a
  /// missing track as failed, not as an error for the whole score). The
  /// device can fail more on load; see PlaybackState.failedVoices.
  Set<VoicePart> get failedVoices => {
    ...declaredFailedVoices,
    for (final voice in VoicePart.values)
      if (!audioTracks.containsKey(voice)) voice,
  };

  /// Whether page [pageIndex] has an image to draw on.
  bool hasPage(int pageIndex) =>
      pageIndex >= 0 &&
      pageIndex < scoreImages.length &&
      scoreImages[pageIndex] != null;

  /// Parses `data` (the envelope is unwrapped by the API). Throws
  /// [FormatException] when no audio track or score id is usable, since
  /// then there is nothing to play.
  ///
  /// URLs must be http(s). `file:` is accepted only when
  /// [allowLocalFiles], which defaults to the debug-only fake build (its
  /// demo score lives in the cache dir): a real server has no business
  /// pointing the app at files on the phone.
  static ScoreResult fromJson(
    Map<String, dynamic> data, {
    bool allowLocalFiles = ApiConfig.useFakeAuth,
  }) {
    Uri? uri(Object? value) => _uri(value, allowLocalFiles: allowLocalFiles);
    final scoreId = data['scoreId'];
    if (scoreId is! int) {
      throw const FormatException('PIYA-103 result without an int scoreId');
    }
    final tracks = <VoicePart, Uri>{};
    final rawTracks = data['audioTracks'];
    if (rawTracks is Map) {
      rawTracks.forEach((key, value) {
        final voice = parseVoicePart(key);
        final track = uri(value);
        if (voice != null && track != null) tracks[voice] = track;
      });
    }
    final rawFailed = data['failedVoices'];
    final declaredFailed = <VoicePart>{
      if (rawFailed is List)
        for (final name in rawFailed) ?parseVoicePart(name),
    };
    // A voice the server calls failed has no audio to trust, even if a
    // track was sent anyway (AC10 says it has none).
    tracks.removeWhere((voice, _) => declaredFailed.contains(voice));
    if (tracks.isEmpty) {
      throw const FormatException('PIYA-103 result without audio tracks');
    }
    final rawMuted = data['mutedMeasures'];
    final muted = <MutedMeasure>[
      if (rawMuted is List)
        for (final entry in rawMuted)
          if (MutedMeasure.tryParse(entry) case final measure?)
            if (tracks.containsKey(measure.voice)) measure,
    ];
    final rawImages = data['scoreImages'];
    // Rejected entries stay as null: dropping them would shift every later
    // page onto the wrong timing events.
    final images = <Uri?>[
      if (rawImages is List)
        for (final image in rawImages) uri(image),
    ];
    final rawSizes = data['scoreImageSizes'];
    final jobId = data['jobId'];
    final arranger = data['arranger'];
    final tempo = data['tempoBpm'];
    final tempoKnown =
        tempo is int &&
        tempo >= ScoreDetails.minTempo &&
        tempo <= ScoreDetails.maxTempo;
    return ScoreResult(
      scoreId: scoreId,
      jobId: jobId is String ? jobId : null,
      audioTracks: Map.unmodifiable(tracks),
      scoreImages: List.unmodifiable(images),
      timingMetadataUrl: uri(data['timingMetadataUrl']),
      review: ReviewSummary.fromJson(data['review']),
      pageSizes: [
        if (rawSizes is List)
          for (final size in rawSizes) _size(size),
      ],
      arranger: arranger is String && arranger.trim().isNotEmpty
          ? arranger.trim()
          : null,
      tempoBpm: tempo is int && tempoKnown ? tempo : ScoreDetails.defaultTempo,
      tempoKnown: tempoKnown,
      declaredFailedVoices: Set.unmodifiable(declaredFailed),
      mutedMeasures: List.unmodifiable(muted),
    );
  }

  /// [pageSizes] for [pageIndex], or null when the server didn't say.
  Size? pageSizeAt(int pageIndex) =>
      pageIndex < pageSizes.length ? pageSizes[pageIndex] : null;

  static Uri? _uri(Object? value, {required bool allowLocalFiles}) {
    if (value is! String || value.trim().isEmpty) return null;
    final uri = Uri.tryParse(value.trim());
    if (uri == null) return null;
    return switch (uri.scheme) {
      'http' || 'https' => uri,
      'file' when allowLocalFiles => uri,
      _ => null,
    };
  }

  static Size? _size(Object? value) {
    if (value is! Map) return null;
    final width = value['width'];
    final height = value['height'];
    if (width is! num || height is! num || width <= 0 || height <= 0) {
      return null;
    }
    return Size(width.toDouble(), height.toDouble());
  }
}

/// One entry of the PIYA-117 timing file: a note onset placed on the page.
///
/// Chord notes share [timestampMs] and [eventId] is not guaranteed unique
/// (backend-lead, 2026-10-09), so nothing is keyed on either; events are
/// kept as an ordered list.
@immutable
class TimingEvent {
  const TimingEvent({
    required this.timestampMs,
    required this.pageIndex,
    required this.x,
    required this.y,
    this.voice,
    this.tick,
    this.bar,
    this.systemIndex,
    this.systemTopY,
    this.systemBottomY,
  });

  final int timestampMs;

  /// 0-based, like PIYA-101's `pageIndex` (the proposed API convention):
  /// index 0 is `scoreImages[0]`.
  final int pageIndex;

  /// Pixels in the original preprocessed page image (PIYA-118 AC2).
  final double x;
  final double y;
  final VoicePart? voice;
  final int? tick;

  /// 1-based measure number; a pickup (anacrusis) is 0. Null when Stage 4
  /// couldn't number the measure.
  final int? bar;

  /// Optional per-event system geometry (backend-lead, 2026-10-09). When
  /// present it decides the band's vertical extent; otherwise the client
  /// derives it from the events' own y values.
  final int? systemIndex;
  final double? systemTopY;
  final double? systemBottomY;

  /// Null for an entry that can't be placed (missing or negative time,
  /// page or coordinates); one bad entry never discards the whole file.
  static TimingEvent? tryParse(Object? json) {
    if (json is! Map) return null;
    final timestamp = json['timestampMs'];
    final page = json['pageIndex'];
    final x = json['x'];
    final y = json['y'];
    if (timestamp is! num || timestamp < 0) return null;
    if (page is! int || page < 0) return null;
    if (x is! num || y is! num || x < 0 || y < 0) return null;
    final top = json['systemTopY'];
    final bottom = json['systemBottomY'];
    final hasSystemBox = top is num && bottom is num && bottom > top;
    return TimingEvent(
      timestampMs: timestamp.round(),
      pageIndex: page,
      x: x.toDouble(),
      y: y.toDouble(),
      voice: parseVoicePart(json['voice']),
      tick: _nonNegativeInt(json['tick']),
      bar: _nonNegativeInt(json['bar']),
      systemIndex: _nonNegativeInt(json['systemIndex']),
      systemTopY: hasSystemBox ? top.toDouble() : null,
      systemBottomY: hasSystemBox ? bottom.toDouble() : null,
    );
  }

  static int? _nonNegativeInt(Object? value) =>
      value is int && value >= 0 ? value : null;
}

/// Reads a timing file: a bare list of events, or an object holding them
/// under `events` (PIYA-117 doesn't pin the top level). Unplaceable
/// entries are skipped; the rest are sorted by time, stably, so file order
/// breaks ties.
List<TimingEvent> parseTimingEvents(Object? json) {
  final raw = json is Map ? json['events'] : json;
  if (raw is! List) {
    throw const FormatException('Timing file is not a list of events');
  }
  final events = <TimingEvent>[
    for (final entry in raw) ?TimingEvent.tryParse(entry),
  ];
  mergeSort(events, compare: (a, b) => a.timestampMs - b.timestampMs);
  return List.unmodifiable(events);
}
