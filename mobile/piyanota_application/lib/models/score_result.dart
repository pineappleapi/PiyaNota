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
  });

  final int scoreId;
  final String? jobId;

  /// Only the voices that came back with a usable URL; a missing one shows
  /// as a disabled chip rather than failing the whole score.
  final Map<VoicePart, Uri> audioTracks;

  /// One original preprocessed page image per page, in page order
  /// (`pageIndex` 0 is the first). FR-8: never a re-engraved rendering.
  final List<Uri> scoreImages;
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
    if (tracks.isEmpty) {
      throw const FormatException('PIYA-103 result without audio tracks');
    }
    final images = <Uri>[];
    final rawImages = data['scoreImages'];
    if (rawImages is List) {
      for (final image in rawImages) {
        final page = uri(image);
        if (page != null) images.add(page);
      }
    }
    final rawSizes = data['scoreImageSizes'];
    final jobId = data['jobId'];
    final arranger = data['arranger'];
    final tempo = data['tempoBpm'];
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
      tempoBpm:
          tempo is int &&
              tempo >= ScoreDetails.minTempo &&
              tempo <= ScoreDetails.maxTempo
          ? tempo
          : ScoreDetails.defaultTempo,
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
