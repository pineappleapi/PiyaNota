import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/voice_part.dart';
import 'piano_octave.dart';

/// The user's last piano octave (AC 37-39), with the timestamp and pending
/// flag that [PianoSyncService] reconciles against the server (AC 41-47).
class PianoOctaveStore {
  static const String octaveKey = 'piano_octave';
  static const String updatedAtKey = 'piano_octave_updated_at';
  static const String pendingKey = 'piano_octave_sync_pending';

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

  /// What the user saved (or adopted from the server), or null when they
  /// never did; the voice default is not a saved value (AC 41).
  Future<({int octave, DateTime updatedAt})?> loadSaved() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final octave = prefs.get(octaveKey);
      final at = prefs.get(updatedAtKey);
      final parsed = at is String ? DateTime.tryParse(at) : null;
      if (isValidOctave(octave) && parsed != null) {
        return (octave: octave! as int, updatedAt: parsed.toUtc());
      }
    } on Object catch (e) {
      debugPrint('Piano: saved octave not read: $e');
    }
    return null;
  }

  /// Takes the server's value (AC 41, 45), keeping its timestamp.
  Future<void> adopt(int octave, DateTime updatedAt) =>
      save(octave, now: updatedAt);

  Future<bool> isPending() async {
    try {
      return (await SharedPreferences.getInstance()).getBool(pendingKey) ??
          false;
    } on Object catch (e) {
      debugPrint('Piano: pending flag not read: $e');
      return false;
    }
  }

  Future<void> setPending(bool value) async {
    try {
      await (await SharedPreferences.getInstance()).setBool(pendingKey, value);
    } on Object catch (e) {
      debugPrint('Piano: pending flag not saved: $e');
    }
  }
}
