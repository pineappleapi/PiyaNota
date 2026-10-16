import 'voice_part.dart';

/// What the Export Audio modal (PIYA-211) has ticked.
///
/// Immutable so the sheet can keep the selection across a failed export
/// (AC19) simply by holding on to the old value.
class ExportSelection {
  const ExportSelection._({
    required this.available,
    required this.voices,
    required this.withClick,
  });

  /// Nothing ticked (AC2). [available] is the set of voices that can
  /// play; a failed or unreadable voice is left out so it can never be
  /// ticked or counted towards "All Voices" (Review Focus 4).
  factory ExportSelection.empty(Set<VoicePart> available) => ExportSelection._(
    available: Set.unmodifiable(available),
    voices: const {},
    withClick: false,
  );

  final Set<VoicePart> available;
  final Set<VoicePart> voices;
  final bool withClick;

  /// "All Voices" is derived, not stored, so it can never disagree with
  /// the individual boxes (AC5, AC6). It needs at least one available
  /// voice, else an empty score would show All as ticked.
  bool get allVoices =>
      available.isNotEmpty && voices.length == available.length;

  /// The click on its own is not a useful file (AC8).
  bool get canDownload => voices.isNotEmpty;

  ExportSelection toggleVoice(VoicePart voice) {
    if (!available.contains(voice)) return this;
    final next = {...voices};
    if (!next.remove(voice)) next.add(voice);
    return _with(voices: next);
  }

  ExportSelection toggleAll() =>
      _with(voices: allVoices ? const {} : {...available});

  ExportSelection toggleClick() => _with(withClick: !withClick);

  ExportSelection _with({Set<VoicePart>? voices, bool? withClick}) =>
      ExportSelection._(
        available: available,
        voices: Set.unmodifiable(voices ?? this.voices),
        withClick: withClick ?? this.withClick,
      );
}

/// Characters Android's shared storage (and FAT-formatted SD cards)
/// refuse in a file name, plus the path separators.
final RegExp _unsafeFileNameChars = RegExp('[/\\\\:*?"<>|]');

const String _untitledScoreName = 'Score';
const String _allVoicesName = 'AllVoices';
const String _clickSuffix = '_Click';
const String _voiceJoiner = '-';
const String exportExtension = '.mp3';

/// `[ScoreName]_[Voices][_Click].mp3` (PIYA-211 AC14).
String exportFileName({
  required String title,
  required ExportSelection selection,
}) {
  final trimmed = title.trim();
  final name = trimmed.isEmpty
      ? _untitledScoreName
      : trimmed.replaceAll(_unsafeFileNameChars, '_');
  // VoicePart.values is SATB order, whatever order the boxes were ticked.
  final voices = selection.allVoices
      ? _allVoicesName
      : VoicePart.values
            .where(selection.voices.contains)
            .map((v) => v.label)
            .join(_voiceJoiner);
  final click = selection.withClick ? _clickSuffix : '';
  return '${name}_$voices$click$exportExtension';
}

/// [name], or `name (n).ext` with the first free n (AC15).
///
/// Compared case-insensitively because Android's shared storage is, so
/// `x.MP3` already blocks `X.mp3`.
String uniqueFileName(String name, Set<String> existing) {
  final taken = {for (final n in existing) n.toLowerCase()};
  if (!taken.contains(name.toLowerCase())) return name;
  final dot = name.lastIndexOf('.');
  final stem = dot > 0 ? name.substring(0, dot) : name;
  final ext = dot > 0 ? name.substring(dot) : '';
  for (var n = 1; ; n++) {
    final candidate = '$stem ($n)$ext';
    if (!taken.contains(candidate.toLowerCase())) return candidate;
  }
}
