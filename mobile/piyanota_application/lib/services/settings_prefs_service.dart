import 'package:shared_preferences/shared_preferences.dart';

import '../models/score_details.dart';

/// Settings-only preferences (PIYA-212). The default voice is not here: it
/// is the same pref onboarding writes, so it lives in
/// OnboardingPrefsService and both screens can never disagree (AC7).
class SettingsPrefsService {
  /// Public so tests can seed a stored value.
  static const String defaultTempoKey = 'settings_default_tempo';

  /// AC8: the tempo sent as `fallbackTempoBpm` when Speed is "Not sure".
  /// Clamped on read too, so a value written by an older build with other
  /// limits can never reach the upload as a 400 `invalid_tempo`.
  Future<int> getDefaultTempo() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getInt(defaultTempoKey);
    return _clamp(stored ?? ScoreDetails.defaultTempo);
  }

  Future<void> setDefaultTempo(int bpm) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(defaultTempoKey, _clamp(bpm));
  }

  static int _clamp(int bpm) =>
      bpm.clamp(ScoreDetails.minTempo, ScoreDetails.maxTempo);
}
