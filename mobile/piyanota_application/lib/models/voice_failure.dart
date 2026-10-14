import 'score_details.dart';
import 'score_result.dart';
import 'voice_part.dart';

/// Why the server could not produce a voice (PIYA-103 AC10
/// `failedVoiceCauses`, also sent by PIYA-102 AC7 on `complete`).
enum VoiceFailureCause {
  /// The voice could not be read from the photos. A whole-score retake
  /// (PIYA-207 AC12) may fix it, so the app offers one.
  unreadable('unreadable'),

  /// Audio rendering failed. Retaking cannot help; "try again later".
  renderFailed('render_failed');

  const VoiceFailureCause(this.apiValue);

  final String apiValue;

  /// PIYA-103 AC10: any value this build doesn't know is [renderFailed], so
  /// a new server cause never offers a retake that may not help.
  static VoiceFailureCause fromApi(Object? value) =>
      value == unreadable.apiValue ? unreadable : renderFailed;
}

/// Parses `failedVoiceCauses` for the voices in [failedVoices]. A failed
/// voice the object leaves out (or an object that is missing or broken)
/// reads as [VoiceFailureCause.renderFailed], and keys for voices that are
/// not failed are ignored: the cause only explains a failure, it never
/// creates one.
Map<VoicePart, VoiceFailureCause> parseFailedVoiceCauses(
  Object? raw,
  Set<VoicePart> failedVoices,
) {
  final given = <VoicePart, Object?>{};
  if (raw is Map) {
    raw.forEach((key, value) {
      final voice = parseVoicePart(key);
      if (voice != null) given[voice] = value;
    });
  }
  return Map.unmodifiable({
    for (final voice in failedVoices)
      voice: VoiceFailureCause.fromApi(given[voice]),
  });
}

/// Parses a `failedVoices` list into voices, ignoring unknown names.
Set<VoicePart> parseFailedVoices(Object? raw) => Set.unmodifiable({
  if (raw is List)
    for (final name in raw) ?parseVoicePart(name),
});

/// The PIYA-101 AC8 details echoed on a PIYA-102 response (PIYA-102 AC8),
/// used to pre-fill a whole-score retake (PIYA-207 AC12). Null when no
/// usable `title` came back. Optional fields that are missing or unknown
/// stay empty ("Not sure"), so the user can still fix them before
/// submitting.
ScoreDetails? scoreDetailsFromJson(Map<String, dynamic> json) {
  final title = json['title'];
  if (title is! String || title.trim().isEmpty) return null;
  final arranger = json['arranger'];
  final key = json['keySignature'];
  final time = json['timeSignature'];
  final tempo = json['tempoBpm'];
  return ScoreDetails(
    title: title.trim(),
    arranger: arranger is String ? arranger.trim() : '',
    keySignature: key is String
        ? KeySignature.values.where((k) => k.apiValue == key).firstOrNull
        : null,
    timeSignature: time is String
        ? TimeSignature.values
              .where((t) => t.apiValue != null && t.apiValue == time)
              .firstOrNull
        : null,
    tempoBpm:
        tempo is int &&
            tempo >= ScoreDetails.minTempo &&
            tempo <= ScoreDetails.maxTempo
        ? tempo
        : null,
  );
}
