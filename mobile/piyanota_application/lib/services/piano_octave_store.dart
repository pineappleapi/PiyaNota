import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/voice_part.dart';
import 'piano_octave.dart';

/// The user's last piano octave, local only (AC 37-39). Server sync
/// (PIYA-321) is not wired yet; the timestamp is stored so it can be later.
class PianoOctaveStore {
  static const String octaveKey = 'piano_octave';
  static const String updatedAtKey = 'piano_octave_updated_at';

  /// The saved octave, or the voice default when none or corrupt (AC 39).
  Future<int> load(VoicePart? voice) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.get(octaveKey);
      if (isValidOctave(saved)) return saved! as int;
    } on Object catch (e) {
      debugPrint('Piano: octave not read: $e');
    }
    return defaultOctaveFor(voice);
  }

  Future<void> save(int octave, {DateTime? now}) async {
    if (!isValidOctave(octave)) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt(octaveKey, octave);
      await prefs.setString(
        updatedAtKey,
        (now ?? DateTime.now()).toUtc().toIso8601String(),
      );
    } on Object catch (e) {
      debugPrint('Piano: octave not saved: $e');
    }
  }
}
